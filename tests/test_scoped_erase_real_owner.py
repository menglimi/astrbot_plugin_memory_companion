from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid

from core.namespace import NamespaceContext
from core.scoped_domain_contract import build_scoped_domain_payload
from core.scoped_store import ScopedStore


def _context(
    kind: str, *, identity: str = "person-a", group: str = "", persona: str = "default"
) -> NamespaceContext:
    return NamespaceContext(
        kind=kind,
        identity_id=identity,
        group_id=group,
        assurance="verified",
        profile_status="active",
        policy_version="req041-v1",
        migration_epoch="shadow-20260810",
        persona_id=persona,
    )


def _uuid() -> str:
    # 真实运行时的 record_id 是 uuid，不是测试专用的 req041- 前缀。
    return str(uuid.uuid4())


class ScopedEraseRealOwnerTests(unittest.TestCase):
    """擦除必须按真实归属字段（namespace_scope 里的 persona_id/group_id）命中。

    修复前 erase_* 用 record_id LIKE 'req041-%' 找候选，线上 record_id 是 uuid，
    于是返回成功却一条没擦；且擦完 payload 换 {} 后 list_records 仍会列出。
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ScopedStore(Path(self.tmp.name) / "scoped.sqlite3", clock=lambda: 100.0)
        self.private = _context("private")
        self.group_a = _context("group_member", group="group-a")
        self.group_b = _context("group_member", group="group-b")

    def tearDown(self) -> None:
        # Windows 上被打开的 sqlite 文件无法删除：先关连接再清临时目录。
        close = getattr(self.store, "close", None)
        if callable(close):
            close()
        self.tmp.cleanup()

    def _write(self, context, record_kind, record_id, source_kind, domain="memory", **kwargs) -> None:
        self.store.upsert(
            context,
            record_kind=record_kind,
            record_id=record_id,
            revision=1,
            payload=build_scoped_domain_payload(
                domain=domain,
                source_kind=source_kind,
                content={"sentinel": record_id},
                source_revision=1,
                **kwargs,
            ),
            event_id=f"event-{record_id}",
        )

    def _erased_ids(self) -> list[str]:
        with closing(sqlite3.connect(self.store.path)) as connection:
            rows = connection.execute(
                "SELECT record_id FROM scoped_records WHERE erased=1 ORDER BY record_id"
            ).fetchall()
        return [str(row[0]) for row in rows]

    def test_group_erase_matches_real_uuid_records_and_empties_lists(self) -> None:
        shared_a = _context("group_shared", identity="", group="group-a")
        member_a_other = _context("group_member", identity="person-b", group="group-a")
        shared_b = _context("group_shared", identity="", group="group-b")
        shared_id, member_id, other_member_id = _uuid(), _uuid(), _uuid()
        group_b_id, private_id = _uuid(), _uuid()
        self._write(shared_a, "memory", shared_id, "group_shared")
        self._write(self.group_a, "memory", member_id, "group_member")
        self._write(member_a_other, "memory", other_member_id, "group_member")
        self._write(shared_b, "memory", group_b_id, "group_shared")
        self._write(self.private, "memory", private_id, "private")

        # 先确认这些 uuid 记录本来是对外可见的，避免「本来就空」造成假阳性。
        self.assertEqual(
            [member_id],
            [item["record_id"] for item in self.store.list_records(self.group_a, record_kind="memory")],
        )

        result = self.store.erase_group_scopes(
            shared_a, operation_id="group-reset-1", reason_code="group_reset",
        )
        # 真实删除条数：shared-a + person-a 的 group_member + person-b 的 group_member。
        self.assertEqual(3, result["count"])
        self.assertEqual(3, result["deleted"])
        self.assertEqual(3, result["namespace_count"])
        for context in (shared_a, self.group_a, member_a_other):
            self.assertEqual([], self.store.list_records(context, record_kind="memory"))
        # 记录没有被删行，只是内容被擦空、revision +1（旧数据仍可读、可重新学习）。
        for context, record_id in (
            (shared_a, shared_id),
            (self.group_a, member_id),
            (member_a_other, other_member_id),
        ):
            record = self.store.read(context, record_kind="memory", record_id=record_id)
            self.assertEqual({}, record["payload"]["content"])
            self.assertEqual(2, record["revision"])
        self.assertEqual(
            sorted([shared_id, member_id, other_member_id]), sorted(self._erased_ids())
        )

        # 其它 group / private 完全不受影响。
        self.assertEqual(
            [group_b_id],
            [item["record_id"] for item in self.store.list_records(shared_b, record_kind="memory")],
        )
        self.assertEqual(
            [private_id],
            [item["record_id"] for item in self.store.list_records(self.private, record_kind="memory")],
        )

        # 换个 operation_id 再擦同一批：不重复 bump revision，返回真实 0 条。
        replay = self.store.erase_group_scopes(
            shared_a, operation_id="group-reset-2", reason_code="group_reset",
        )
        self.assertEqual(0, replay["count"])
        self.assertEqual(0, replay["deleted"])
        self.assertEqual("group_scopes_already_empty", replay["code"])
        self.assertEqual(2, self.store.read(self.group_a, record_kind="memory", record_id=member_id)["revision"])

    def test_persona_erase_matches_real_uuid_records_and_empties_lists(self) -> None:
        persona = "persona-a"
        private = _context("private", persona=persona)
        member = _context("group_member", group="group-a", persona=persona)
        shared = _context("group_shared", identity="", group="group-a", persona=persona)
        global_rules = _context("persona_global", identity="", persona=persona)
        other_persona = _context("private", persona="persona-b")
        private_id, member_id, shared_id, global_id, other_id = (
            _uuid(), _uuid(), _uuid(), _uuid(), _uuid(),
        )
        self._write(private, "memory", private_id, "private")
        self._write(member, "profile_fact", member_id, "group_member", domain="profile")
        self._write(shared, "memory", shared_id, "group_shared")
        self._write(
            global_rules, "rule", global_id, "persona_global", domain="learning",
            approval_state="approved", approved_by="administrator",
        )
        self._write(other_persona, "memory", other_id, "private")

        result = self.store.erase_persona_scopes(
            global_rules, operation_id="persona-reset-1", reason_code="persona_reset",
        )
        self.assertEqual(4, result["count"])
        self.assertEqual(4, result["deleted"])
        self.assertEqual(
            {"group_member", "group_shared", "persona_global", "private"},
            set(result["namespace_kinds"]),
        )
        for context, record_kind in (
            (private, "memory"),
            (member, "profile_fact"),
            (shared, "memory"),
            (global_rules, "rule"),
        ):
            self.assertEqual([], self.store.list_records(context, record_kind=record_kind))
        for context, record_kind, record_id in (
            (private, "memory", private_id),
            (member, "profile_fact", member_id),
            (shared, "memory", shared_id),
            (global_rules, "rule", global_id),
        ):
            record = self.store.read(context, record_kind=record_kind, record_id=record_id)
            self.assertEqual({}, record["payload"]["content"])
            self.assertEqual(2, record["revision"])
        self.assertEqual(
            sorted([private_id, member_id, shared_id, global_id]), sorted(self._erased_ids())
        )
        # 别的 persona 一条不能动。
        self.assertEqual(
            [other_id],
            [item["record_id"] for item in self.store.list_records(other_persona, record_kind="memory")],
        )

    def test_identity_tombstone_matches_real_uuid_records(self) -> None:
        member_a = _context("group_member", group="group-a")
        other_person = _context("private", identity="person-b")
        private_id, member_id, other_id = _uuid(), _uuid(), _uuid()
        self._write(self.private, "memory", private_id, "private")
        self._write(member_a, "memory", member_id, "group_member")
        self._write(other_person, "memory", other_id, "private")

        result = self.store.tombstone_identity_scopes(
            self.private, operation_id="person-archive-1", reason_code="person_archive",
        )
        self.assertEqual(2, result["count"])
        self.assertEqual(2, result["deleted"])
        for context, record_id in ((self.private, private_id), (member_a, member_id)):
            self.assertIsNone(self.store.read(context, record_kind="memory", record_id=record_id))
            self.assertEqual([], self.store.list_records(context, record_kind="memory"))
        self.assertEqual(
            [other_id],
            [item["record_id"] for item in self.store.list_records(other_person, record_kind="memory")],
        )


if __name__ == "__main__":
    unittest.main()
