"""Small append-only provenance ledger for the chat-side memory plugin.

The ledger stores only validated provenance records and migration audit
metadata.  It never accepts prompt text, conversation content, media,
credentials, or arbitrary source prose.  Writes are atomic and every mutation
creates a backup before the current projection changes.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import shutil
import threading
import time
from typing import Any, Mapping

from .provenance import (
    apply_planned_operation,
    plan_legacy_migration,
    provenance_record_digest,
    rollback_planned_operation,
    validate_operation,
    validate_provenance_record,
)


LEDGER_SCHEMA_VERSION = "ops.p5.provenance.ledger.v1"
# P11：账本从「裸 sha256 数字」升级为「带密钥的哈希链」。
# 每写一次就在 chain 里追加一条 {seq, kind, payload, prev, mac}：
#   - payload 只含 memory_id 与摘要（绝不含正文、提示词、凭据）；
#   - prev 指向上一条的 mac，构成链；
#   - mac = HMAC-SHA256(key, 链版本|seq|kind|sha256(payload)|prev)。
# 顶层 head 记录链尾 mac，用来发现「把尾巴剪掉」这类截断。
# 局限（必须诚实）：拿到账本文件且同时拿到密钥文件的人仍可整本重造。
# 链的作用是让「改一条、删一条、剪尾巴」这类局部篡改可见，不是防有全权的本机主人。
INTEGRITY_CHAIN_VERSION = "ops.p5.provenance.chain.v1"
GENESIS_MAC = "0" * 64
INTEGRITY_KEY_BYTES = 32


def _canonical_payload(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _payload_digest(payload: Any) -> str:
    return hashlib.sha256(_canonical_payload(payload).encode("utf-8")).hexdigest()


def _chain_mac(key: bytes, *, seq: int, kind: str, payload_digest: str, prev_mac: str) -> str:
    message = f"{INTEGRITY_CHAIN_VERSION}|{seq}|{kind}|{payload_digest}|{prev_mac}".encode("utf-8")
    return hmac.new(key or b"", message, hashlib.sha256).hexdigest()


def load_or_create_integrity_key(path: Path) -> bytes:
    """读取（或第一次生成）账本密钥。

    密钥是本机随机 32 字节，落在 data 目录里，尽量按 0600 收紧权限。
    读不到就现生成；写不进去也返回内存里的这把（当次运行仍然可用）。
    """

    target = Path(path)
    try:
        raw = target.read_bytes()
    except OSError:
        raw = b""
    if len(raw) >= INTEGRITY_KEY_BYTES:
        return raw[:INTEGRITY_KEY_BYTES]
    key = secrets.token_bytes(INTEGRITY_KEY_BYTES)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(key)
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
    except OSError:
        pass
    return key


class ProvenanceLedger:
    """Persist validated provenance projections with CAS-protected writes."""

    def __init__(self, path: Path, *, integrity_key: bytes | None = None):
        self.path = Path(path)
        # 没有密钥时仍然建链（等价于空密钥 HMAC），链能发现改/删/截断，
        # 但本机有全权的人可以重算——这一点在 verify_integrity 的 keyed 字段里如实标出。
        self._key = bytes(integrity_key or b"")
        self.key_id = hashlib.sha256(self._key).hexdigest()[:16] if self._key else "none"
        self._lock = threading.RLock()
        # mtime/size 缓存：避免每次 mutation 前全量 read_text + json.loads + 逐条校验。
        # 所有读写均在 self._lock 内进行，缓存无需额外同步。
        self._cache_document: dict[str, Any] | None = None
        self._cache_mtime_ns: int | None = None
        self._cache_size: int | None = None
        # 上一次读盘失败的说明。空字符串 = 文件缺失（首次运行）或读取正常。
        # verify_integrity() 靠它把「账本损坏」和「账本还是空的」区分开。
        self._load_error = ""

    def _empty(self) -> dict[str, Any]:
        return {
            "schema_version": LEDGER_SCHEMA_VERSION,
            "records": {},
            "operations": [],
            "observations": [],
            "chain": [],
            "head": GENESIS_MAC,
        }

    def _load_locked(self) -> dict[str, Any]:
        try:
            stat_result = self.path.stat()
        except FileNotFoundError:
            # 首次运行：文件还不存在，这是正常状态而不是损坏。
            self._cache_document = None
            self._cache_mtime_ns = None
            self._cache_size = None
            self._load_error = ""
            return self._empty()
        except OSError as exc:
            # 文件在但读不了（权限、坏盘、被别的进程锁住）：不是「空账本」，
            # 必须让 verify_integrity() 报 corrupt，否则损坏会被当成健康。
            self._cache_document = None
            self._cache_mtime_ns = None
            self._cache_size = None
            self._load_error = f"unreadable: {type(exc).__name__}: {exc}"
            return self._empty()
        mtime_ns = stat_result.st_mtime_ns
        size = stat_result.st_size
        if (
            self._cache_document is not None
            and self._cache_mtime_ns == mtime_ns
            and self._cache_size == size
        ):
            # mtime+size 未变化：跳过全量读与逐条校验，直接深拷贝缓存返回。
            self._load_error = ""
            return deepcopy(self._cache_document)
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            self._cache_document = None
            self._cache_mtime_ns = None
            self._cache_size = None
            self._load_error = f"unparseable: {type(exc).__name__}: {exc}"
            return self._empty()
        if not isinstance(raw, dict) or raw.get("schema_version") != LEDGER_SCHEMA_VERSION:
            self._cache_document = None
            self._cache_mtime_ns = None
            self._cache_size = None
            found = raw.get("schema_version") if isinstance(raw, dict) else type(raw).__name__
            self._load_error = f"schema_mismatch: {found!r}"
            return self._empty()
        records: dict[str, dict[str, Any]] = {}
        raw_records = raw.get("records")
        if isinstance(raw_records, dict):
            for memory_id, value in raw_records.items():
                checked = validate_provenance_record(value if isinstance(value, Mapping) else None)
                if checked.get("ok") and checked.get("record", {}).get("memory_id") == memory_id:
                    records[memory_id] = deepcopy(checked["record"])
        operations: list[dict[str, Any]] = []
        raw_operations = raw.get("operations")
        if isinstance(raw_operations, list):
            for value in raw_operations:
                checked = validate_operation(value if isinstance(value, Mapping) else None)
                if checked.get("ok"):
                    operations.append(deepcopy(checked["operation"]))
                elif isinstance(value, dict) and value.get("kind") == "rollback":
                    safe = self._safe_rollback_audit(value)
                    if safe is not None:
                        operations.append(safe)
        observations: list[dict[str, Any]] = []
        raw_observations = raw.get("observations")
        if isinstance(raw_observations, list):
            for value in raw_observations:
                safe = self._safe_observation(value)
                if safe is not None:
                    observations.append(safe)
        chain: list[dict[str, Any]] = []
        raw_chain = raw.get("chain")
        if isinstance(raw_chain, list):
            for value in raw_chain:
                safe_entry = self._safe_chain_entry(value)
                if safe_entry is not None:
                    chain.append(safe_entry)
        raw_head = raw.get("head")
        head = raw_head.lower() if isinstance(raw_head, str) and len(raw_head) == 64 else GENESIS_MAC
        document = {
            "schema_version": LEDGER_SCHEMA_VERSION,
            "records": records,
            "operations": operations,
            "observations": observations,
            "chain": chain,
            "head": head,
        }
        # 记录加载时文件的 mtime/size，并缓存文档（存深拷贝副本，
        # 避免调用方对返回值的修改污染缓存）。
        self._cache_mtime_ns = mtime_ns
        self._cache_size = size
        self._cache_document = deepcopy(document)
        self._load_error = ""
        return document

    @staticmethod
    def _safe_observation(value: Any) -> dict[str, Any] | None:
        if not isinstance(value, Mapping) or set(value) != {
            "memory_id", "record_digest", "record_revision", "source_event_ref_hash",
            "authority_attestation_ref_hash", "provenance_state",
        }:
            return None
        if (
            not isinstance(value.get("memory_id"), str)
            or not value["memory_id"]
            or not isinstance(value.get("record_digest"), str)
            or len(value["record_digest"]) != 64
            or not isinstance(value.get("source_event_ref_hash"), str)
            or len(value["source_event_ref_hash"]) != 64
            or not isinstance(value.get("authority_attestation_ref_hash"), str)
            or len(value["authority_attestation_ref_hash"]) != 64
            or not isinstance(value.get("record_revision"), int)
            or value["record_revision"] < 1
            or value.get("provenance_state") not in {"observed", "owner_recovered"}
        ):
            return None
        return {
            "memory_id": value["memory_id"][:120],
            "record_digest": value["record_digest"].lower(),
            "record_revision": value["record_revision"],
            "source_event_ref_hash": value["source_event_ref_hash"].lower(),
            "authority_attestation_ref_hash": value["authority_attestation_ref_hash"].lower(),
            "provenance_state": value["provenance_state"],
        }

    @staticmethod
    def _safe_rollback_audit(value: Mapping[str, Any]) -> dict[str, Any] | None:
        memory_id = value.get("memory_id")
        before_digest = value.get("before_digest")
        after_digest = value.get("after_digest")
        from_revision = value.get("from_revision")
        to_revision = value.get("to_revision")
        if (
            not isinstance(memory_id, str)
            or not memory_id
            or not isinstance(before_digest, str)
            or len(before_digest) != 64
            or not isinstance(after_digest, str)
            or len(after_digest) != 64
            or not isinstance(from_revision, int)
            or from_revision < 0
            or not isinstance(to_revision, int)
            or to_revision < 0
        ):
            return None
        return {
            "kind": "rollback",
            "memory_id": memory_id[:120],
            "before_digest": before_digest.lower(),
            "after_digest": after_digest.lower(),
            "from_revision": from_revision,
            "to_revision": to_revision,
        }

    @staticmethod
    def _safe_chain_entry(value: Any) -> dict[str, Any] | None:
        if not isinstance(value, Mapping) or set(value) != {"seq", "kind", "payload", "prev", "mac"}:
            return None
        seq = value.get("seq")
        kind = value.get("kind")
        payload = value.get("payload")
        prev = value.get("prev")
        mac = value.get("mac")
        if (
            not isinstance(seq, int)
            or isinstance(seq, bool)
            or seq < 1
            or not isinstance(kind, str)
            or not kind
            or len(kind) > 40
            or not isinstance(payload, Mapping)
            or not isinstance(prev, str)
            or len(prev) != 64
            or not isinstance(mac, str)
            or len(mac) != 64
        ):
            return None
        return {
            "seq": seq,
            "kind": kind[:40],
            "payload": deepcopy(dict(payload)),
            "prev": prev.lower(),
            "mac": mac.lower(),
        }

    def _append_chain_locked(self, document: dict[str, Any], kind: str, payload: Mapping[str, Any]) -> None:
        entries = document.setdefault("chain", [])
        previous = entries[-1]["mac"] if entries else GENESIS_MAC
        seq = (entries[-1]["seq"] + 1) if entries else 1
        digest = _payload_digest(payload)
        entries.append(
            {
                "seq": seq,
                "kind": kind,
                "payload": deepcopy(dict(payload)),
                "prev": previous,
                "mac": _chain_mac(self._key, seq=seq, kind=kind, payload_digest=digest, prev_mac=previous),
            }
        )
        document["head"] = entries[-1]["mac"]

    def _write_locked(self, document: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{threading.get_ident()}.tmp")
        temporary.write_text(
            json.dumps(document, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(self.path)
        # 写入成功后刷新缓存，避免下一次 mutation 再全量重读。
        self._cache_document = dict(document)
        try:
            stat_result = self.path.stat()
        except OSError:
            self._cache_mtime_ns = None
            self._cache_size = None
        else:
            self._cache_mtime_ns = stat_result.st_mtime_ns
            self._cache_size = stat_result.st_size

    def _backup_locked(self) -> bool:
        if not self.path.is_file():
            return False
        backup = self.path.with_name(f"{self.path.name}.backup.{time.time_ns()}")
        try:
            shutil.copy2(self.path, backup)
            return True
        except OSError:
            return False

    @staticmethod
    def _minimal_current(memory_id: str, record: Mapping[str, Any] | None) -> dict[str, Any]:
        if isinstance(record, Mapping):
            return deepcopy(dict(record))
        return {"memory_id": memory_id, "record_revision": 0}

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            document = self._load_locked()
            return {
                "schema_version": LEDGER_SCHEMA_VERSION,
                "records": deepcopy(document["records"]),
                "operation_count": len(document["operations"]),
                "observation_count": len(document["observations"]),
                "path_present": self.path.is_file(),
                "integrity": {
                    "chain_version": INTEGRITY_CHAIN_VERSION,
                    "chain_entries": len(document.get("chain") or []),
                    "head": str(document.get("head") or GENESIS_MAC),
                    "key_id": self.key_id,
                    "keyed": bool(self._key),
                },
            }

    def verify_integrity(self) -> dict[str, Any]:
        """校验哈希链、链尾锚点与当前记录摘要是否一致。

        返回 ok=True 表示：条目连续、prev 与 mac 逐条对得上、链尾等于顶层 head、
        以及当前 records 与链上重放出来的摘要完全一致。
        """

        with self._lock:
            document = self._load_locked()
            load_error = self._load_error
        keyed = bool(self._key)
        if load_error:
            # 解析失败 / 版本不符 / 读不了：账本已经不可信，绝不能报 ok=True。
            return {
                "ok": False,
                "state": "corrupt",
                "reason": load_error,
                "broken_at": 0,
                "memory_id": "",
                "entries": 0,
                "records_checked": 0,
                "head": GENESIS_MAC,
                "keyed": keyed,
                "key_id": self.key_id,
            }
        entries = document.get("chain") or []

        def broken(reason: str, *, seq: int = 0, memory_id: str = "") -> dict[str, Any]:
            return {
                "ok": False,
                "state": "tampered",
                "reason": reason,
                "broken_at": seq,
                "memory_id": memory_id,
                "entries": len(entries),
                "keyed": keyed,
                "key_id": self.key_id,
            }

        previous = GENESIS_MAC
        expected_seq = 1
        expected_records: dict[str, str] = {}
        for entry in entries:
            if entry["seq"] != expected_seq:
                return broken("sequence_gap", seq=expected_seq)
            if entry["prev"] != previous:
                return broken("prev_mismatch", seq=expected_seq)
            digest = _payload_digest(entry["payload"])
            expected_mac = _chain_mac(
                self._key,
                seq=entry["seq"],
                kind=entry["kind"],
                payload_digest=digest,
                prev_mac=entry["prev"],
            )
            if not hmac.compare_digest(expected_mac, entry["mac"]):
                return broken("mac_mismatch", seq=expected_seq)
            payload = entry["payload"]
            kind = entry["kind"]
            memory_id = payload.get("memory_id")
            if kind == "observe":
                digests = payload.get("digests")
                if isinstance(digests, Mapping):
                    for item_id, item_digest in digests.items():
                        if isinstance(item_id, str) and isinstance(item_digest, str):
                            expected_records[item_id] = item_digest
            elif kind in {"apply", "rollback"} and isinstance(memory_id, str):
                if kind == "rollback" and payload.get("removed"):
                    expected_records.pop(memory_id, None)
                else:
                    after_digest = payload.get("after_digest")
                    if isinstance(after_digest, str):
                        expected_records[memory_id] = after_digest
            previous = entry["mac"]
            expected_seq += 1

        chain_head = entries[-1]["mac"] if entries else GENESIS_MAC
        if str(document.get("head") or GENESIS_MAC) != chain_head:
            return broken("truncated", seq=len(entries) + 1)

        records = document.get("records") or {}
        for memory_id, digest in expected_records.items():
            record = records.get(memory_id)
            if not isinstance(record, Mapping):
                return broken("record_missing", seq=len(entries), memory_id=memory_id)
            if provenance_record_digest(record) != digest:
                return broken("record_tampered", seq=len(entries), memory_id=memory_id)
        for memory_id in records:
            if memory_id not in expected_records:
                return broken("record_untracked", seq=len(entries), memory_id=str(memory_id))
        return {
            "ok": True,
            "state": "intact" if entries else "empty",
            "reason": "",
            "entries": len(entries),
            "records_checked": len(expected_records),
            "head": chain_head,
            "keyed": keyed,
            "key_id": self.key_id,
        }

    def preview_legacy(self, candidates: list[Mapping[str, Any]], *, operation_ref_hash: str) -> dict[str, Any]:
        return plan_legacy_migration(candidates, operation_ref_hash=operation_ref_hash)

    def backup(self) -> dict[str, Any]:
        with self._lock:
            if not self.path.is_file():
                return {"ok": True, "state": "nothing_to_backup", "created": False}
            created = self._backup_locked()
            return {"ok": created, "state": "backed_up" if created else "degraded", "created": created}

    def apply(self, operation: Mapping[str, Any]) -> dict[str, Any]:
        checked = validate_operation(operation)
        if not checked.get("ok"):
            return {"ok": False, "state": "invalid", "error_codes": checked.get("error_codes", [])}
        op = checked["operation"]
        with self._lock:
            document = self._load_locked()
            if self._load_error:
                # 账本读不出来时绝不「当成空账本」再写一遍，否则损坏会被覆盖成干净的新账本。
                return {"ok": False, "state": "corrupt", "reason": self._load_error}
            current = self._minimal_current(op["memory_id"], document["records"].get(op["memory_id"]))
            result = apply_planned_operation(current, op)
            if not result.get("ok") or not result.get("changed"):
                return {**result, "backup_created": False}
            backup_created = self._backup_locked()
            document["records"][op["memory_id"]] = deepcopy(result["record"])
            document["operations"].append(deepcopy(op))
            self._append_chain_locked(
                document,
                "apply",
                {
                    "kind": "apply",
                    "memory_id": op["memory_id"],
                    "before_digest": op["before_record_digest"],
                    "after_digest": op["after_record_digest"],
                },
            )
            self._write_locked(document)
            return {**result, "backup_created": backup_created, "operation_count": len(document["operations"])}

    def rollback(self, operation: Mapping[str, Any]) -> dict[str, Any]:
        checked = validate_operation(operation)
        if not checked.get("ok"):
            return {"ok": False, "state": "invalid", "error_codes": checked.get("error_codes", [])}
        op = checked["operation"]
        with self._lock:
            document = self._load_locked()
            if self._load_error:
                return {"ok": False, "state": "corrupt", "reason": self._load_error}
            current = document["records"].get(op["memory_id"])
            result = rollback_planned_operation(current, op)
            if not result.get("ok"):
                return {**result, "backup_created": False}
            backup_created = self._backup_locked()
            if result.get("removed"):
                document["records"].pop(op["memory_id"], None)
            else:
                document["records"][op["memory_id"]] = deepcopy(result["record"])
            document["operations"].append(
                {
                    "kind": "rollback",
                    "memory_id": op["memory_id"],
                    "before_digest": op["after_record_digest"],
                    "after_digest": provenance_record_digest(result.get("record")) if result.get("record") else "0" * 64,
                    "from_revision": op["after_record"]["record_revision"],
                    "to_revision": result.get("record", {}).get("record_revision", 0) if result.get("record") else 0,
                }
            )
            self._append_chain_locked(
                document,
                "rollback",
                {
                    "kind": "rollback",
                    "memory_id": op["memory_id"],
                    "removed": bool(result.get("removed")),
                    "after_digest": provenance_record_digest(result.get("record"))
                    if result.get("record")
                    else "0" * 64,
                },
            )
            self._write_locked(document)
            return {**result, "backup_created": backup_created, "operation_count": len(document["operations"])}

    def record_observed(self, memory_ids: list[str], snapshot: Any) -> dict[str, Any]:
        """Append observed metadata for selected memories without raw payloads."""

        from .provenance import observed_from_companion_snapshot

        safe_ids = [item for item in memory_ids if isinstance(item, str) and item][:64]
        if not safe_ids:
            return {"ok": False, "state": "invalid", "error_code": "memory_ids_empty", "written": 0}
        with self._lock:
            document = self._load_locked()
            if self._load_error:
                return {
                    "ok": False,
                    "state": "corrupt",
                    "reason": self._load_error,
                    "written": 0,
                }
            updates: dict[str, dict[str, Any]] = {}
            for memory_id in safe_ids:
                current = document["records"].get(memory_id)
                revision = int(current.get("record_revision", 0)) if isinstance(current, dict) else 0
                record = observed_from_companion_snapshot(memory_id, snapshot, record_revision=revision + 1)
                checked = validate_provenance_record(record)
                if not checked.get("ok"):
                    continue
                if isinstance(current, dict) and current == checked["record"]:
                    continue
                updates[memory_id] = deepcopy(checked["record"])
            if not updates:
                return {"ok": True, "state": "deduplicated", "written": 0, "backup_created": False}
            backup_created = self._backup_locked()
            document["records"].update(updates)
            for record in updates.values():
                document["observations"].append(
                    {
                        "memory_id": record["memory_id"],
                        "record_digest": provenance_record_digest(record),
                        "record_revision": record["record_revision"],
                        "source_event_ref_hash": record["source_event_ref_hash"],
                        "authority_attestation_ref_hash": record["authority_attestation_ref_hash"],
                        "provenance_state": record["provenance_state"],
                    }
                )
            self._append_chain_locked(
                document,
                "observe",
                {
                    "kind": "observe",
                    "digests": {
                        record["memory_id"]: provenance_record_digest(record)
                        for record in updates.values()
                    },
                },
            )
            self._write_locked(document)
            return {
                "ok": True,
                "state": "written",
                "written": len(updates),
                "memory_ids": list(updates),
                "backup_created": backup_created,
            }


__all__ = [
    "GENESIS_MAC",
    "INTEGRITY_CHAIN_VERSION",
    "INTEGRITY_KEY_BYTES",
    "LEDGER_SCHEMA_VERSION",
    "ProvenanceLedger",
    "load_or_create_integrity_key",
]
