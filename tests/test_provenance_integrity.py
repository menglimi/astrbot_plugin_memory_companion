"""P11：来源账本从裸 sha256 升级为带密钥的哈希链。

这里只验证「能被发现」这件事本身：
  * 正常写入后链完整；
  * 改一条记录、改一条链、剪掉链尾，都要被认出来；
  * 密钥文件稳定、够长；
  * 服务层把自己的账本状态如实报出来。
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from core.provenance_store import (
    GENESIS_MAC,
    ProvenanceLedger,
    load_or_create_integrity_key,
)
from core.service import MemoryCompanionService


ROOT = Path(__file__).resolve().parents[1]


def _apply_two(ledger: ProvenanceLedger) -> list[str]:
    preview = ledger.preview_legacy(
        [
            {"memory_id": "memory-1", "record_revision": 0},
            {"memory_id": "memory-2", "record_revision": 0},
        ],
        operation_ref_hash="d" * 64,
    )
    memory_ids = []
    for operation in preview["operations"]:
        applied = ledger.apply(operation)
        if applied.get("ok"):
            memory_ids.append(operation["memory_id"])
    return memory_ids


class ProvenanceIntegrityTests(unittest.TestCase):
    def test_keyless_ledger_is_still_chained(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = ProvenanceLedger(Path(directory) / "provenance_ledger.json")
            memory_ids = _apply_two(ledger)

            result = ledger.verify_integrity()

            self.assertEqual(["memory-1", "memory-2"], memory_ids)
            self.assertTrue(result["ok"], result)
            self.assertEqual(2, result["entries"])
            self.assertEqual(2, result["records_checked"])
            self.assertFalse(result["keyed"])
            snapshot = ledger.snapshot()
            self.assertEqual(2, snapshot["integrity"]["chain_entries"])
            self.assertNotEqual(GENESIS_MAC, snapshot["integrity"]["head"])

    def test_keyed_ledger_detects_a_modified_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "provenance_ledger.json"
            key = b"k" * 32
            ledger = ProvenanceLedger(path, integrity_key=key)
            _apply_two(ledger)
            self.assertTrue(ledger.verify_integrity()["ok"])

            document = json.loads(path.read_text(encoding="utf-8"))
            document["records"]["memory-1"]["record_revision"] += 5
            path.write_text(json.dumps(document, ensure_ascii=True, sort_keys=True), encoding="utf-8")

            reloaded = ProvenanceLedger(path, integrity_key=key)
            result = reloaded.verify_integrity()

            self.assertFalse(result["ok"])
            self.assertEqual("record_tampered", result["reason"])
            self.assertEqual("memory-1", result["memory_id"])
            self.assertTrue(result["keyed"])

    def test_chain_mac_tampering_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "provenance_ledger.json"
            key = b"k" * 32
            ledger = ProvenanceLedger(path, integrity_key=key)
            _apply_two(ledger)

            document = json.loads(path.read_text(encoding="utf-8"))
            document["chain"][0]["payload"]["after_digest"] = "f" * 64
            path.write_text(json.dumps(document, ensure_ascii=True, sort_keys=True), encoding="utf-8")

            result = ProvenanceLedger(path, integrity_key=key).verify_integrity()

            self.assertFalse(result["ok"])
            self.assertEqual("mac_mismatch", result["reason"])

    def test_truncated_chain_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "provenance_ledger.json"
            key = b"k" * 32
            ledger = ProvenanceLedger(path, integrity_key=key)
            _apply_two(ledger)

            document = json.loads(path.read_text(encoding="utf-8"))
            document["chain"].pop()
            path.write_text(json.dumps(document, ensure_ascii=True, sort_keys=True), encoding="utf-8")

            result = ProvenanceLedger(path, integrity_key=key).verify_integrity()

            self.assertFalse(result["ok"])
            self.assertEqual("truncated", result["reason"])

    def test_wrong_key_is_detected_as_mac_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "provenance_ledger.json"
            ProvenanceLedger(path, integrity_key=b"a" * 32)
            ProvenanceLedger(path, integrity_key=b"a" * 32).apply(
                ProvenanceLedger(path, integrity_key=b"a" * 32)
                .preview_legacy(
                    [{"memory_id": "memory-1", "record_revision": 0}],
                    operation_ref_hash="d" * 64,
                )["operations"][0]
            )

            result = ProvenanceLedger(path, integrity_key=b"b" * 32).verify_integrity()

            self.assertFalse(result["ok"])
            self.assertEqual("mac_mismatch", result["reason"])

    def test_key_file_is_stable_and_long_enough(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "provenance_ledger.key"
            first = load_or_create_integrity_key(path)
            second = load_or_create_integrity_key(path)

            self.assertEqual(first, second)
            self.assertEqual(32, len(first))
            self.assertTrue(path.is_file())


class ServiceReportsIntegrityTests(unittest.TestCase):
    def test_service_status_reports_a_keyed_intact_chain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = MemoryCompanionService(
                context=None,
                config={"startup": {"background_grace_seconds": 60}},
                plugin_root=ROOT,
                data_dir=Path(directory),
            )
            try:
                status = service.p5_capability_status()
                integrity = status["provenance_integrity"]
            finally:
                service.close()

            self.assertTrue(integrity["ok"], integrity)
            self.assertTrue(integrity["keyed"])
            self.assertEqual("empty", integrity["state"])
            self.assertTrue((Path(directory) / "provenance_ledger.key").is_file())


class CorruptLedgerTests(unittest.TestCase):
    """P11：账本读不出来时必须报 corrupt，而不是当成「空账本」报健康。"""

    def test_missing_ledger_file_is_a_healthy_empty_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "provenance_ledger.json"
            result = ProvenanceLedger(path).verify_integrity()

            self.assertTrue(result["ok"], result)
            self.assertEqual("empty", result["state"])
            self.assertEqual("", result["reason"])

    def test_unparseable_ledger_is_reported_as_corrupt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "provenance_ledger.json"
            path.write_text("{not json", encoding="utf-8")

            result = ProvenanceLedger(path).verify_integrity()

            self.assertFalse(result["ok"], result)
            self.assertEqual("corrupt", result["state"])
            self.assertTrue(result["reason"].startswith("unparseable"), result["reason"])
            self.assertEqual(0, result["entries"])

    def test_half_written_ledger_is_reported_as_corrupt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "provenance_ledger.json"
            # 崩溃最容易留下的形态：JSON 写了一半。
            path.write_text('{"schema_version": 2, "records": {"memory-1":', encoding="utf-8")

            result = ProvenanceLedger(path).verify_integrity()

            self.assertFalse(result["ok"], result)
            self.assertEqual("corrupt", result["state"])
            self.assertTrue(result["reason"].startswith("unparseable"), result["reason"])

    def test_schema_mismatch_is_reported_as_corrupt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "provenance_ledger.json"
            path.write_text(
                json.dumps({"schema_version": 1, "records": {}, "chain": [], "head": GENESIS_MAC}),
                encoding="utf-8",
            )

            result = ProvenanceLedger(path).verify_integrity()

            self.assertFalse(result["ok"], result)
            self.assertEqual("corrupt", result["state"])
            self.assertTrue(result["reason"].startswith("schema_mismatch"), result["reason"])

    def test_corrupt_ledger_is_not_silently_reset_by_apply(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "provenance_ledger.json"
            broken = '{"schema_version": 2, "records": '
            path.write_text(broken, encoding="utf-8")
            ledger = ProvenanceLedger(path)
            operation = ledger.preview_legacy(
                [{"memory_id": "memory-1", "record_revision": 0}],
                operation_ref_hash="d" * 64,
            )["operations"][0]

            applied = ledger.apply(operation)

            self.assertFalse(applied["ok"], applied)
            self.assertEqual("corrupt", applied["state"])
            # 损坏的原文件必须原样留着，供人排查/恢复。
            self.assertEqual(broken, path.read_text(encoding="utf-8"))

    def test_corrupt_ledger_is_not_silently_reset_by_record_observed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "provenance_ledger.json"
            broken = "not a ledger at all"
            path.write_text(broken, encoding="utf-8")
            ledger = ProvenanceLedger(path)

            observed = ledger.record_observed(["memory-1"], {"id": "memory-1"})

            self.assertFalse(observed["ok"], observed)
            self.assertEqual("corrupt", observed["state"])
            self.assertEqual(broken, path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
