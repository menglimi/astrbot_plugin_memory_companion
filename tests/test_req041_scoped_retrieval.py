from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from core.namespace import NamespaceContext
from core.scoped_domain_contract import build_scoped_domain_payload
from core.scoped_store import ScopedRecordConflict, ScopedRevisionGap, ScopedStore, ScopedStoreError


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


class ScopedStoreTests(unittest.TestCase):
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

    def test_private_group_a_and_group_b_are_physically_isolated(self) -> None:
        contexts = ((self.private, "private-sentinel"), (self.group_a, "group-a-sentinel"), (self.group_b, "group-b-sentinel"))
        for index, (context, marker) in enumerate(contexts, start=1):
            self.assertEqual(
                "created",
                self.store.upsert(
                    context,
                    record_kind="memory",
                    record_id="same-record-id",
                    revision=1,
                    payload={"marker": marker},
                    event_id=f"event-{index}",
                ),
            )
        self.assertEqual("private-sentinel", self.store.read(self.private, record_kind="memory", record_id="same-record-id")["payload"]["marker"])
        self.assertEqual("group-a-sentinel", self.store.read(self.group_a, record_kind="memory", record_id="same-record-id")["payload"]["marker"])
        self.assertEqual("group-b-sentinel", self.store.read(self.group_b, record_kind="memory", record_id="same-record-id")["payload"]["marker"])

    def test_another_identity_in_same_group_is_isolated(self) -> None:
        other = _context("group_member", identity="person-b", group="group-a")
        self.store.upsert(self.group_a, record_kind="profile_fact", record_id="nickname", revision=1, payload={"value": "A"}, event_id="a-1")
        self.assertIsNone(self.store.read(other, record_kind="profile_fact", record_id="nickname"))

    def test_same_identity_and_group_are_isolated_between_personas(self) -> None:
        other_persona = NamespaceContext(
            kind="private", identity_id="person-a", group_id="", assurance="verified",
            profile_status="active", policy_version="req041-v1", migration_epoch="shadow-20260810",
            persona_id="persona-b",
        )
        self.store.upsert(
            self.private, record_kind="memory", record_id="same-id", revision=1,
            payload={"marker": "default"}, event_id="persona-default",
        )
        self.store.upsert(
            other_persona, record_kind="memory", record_id="same-id", revision=1,
            payload={"marker": "persona-b"}, event_id="persona-b",
        )
        self.assertEqual("default", self.store.read(self.private, record_kind="memory", record_id="same-id")["payload"]["marker"])
        self.assertEqual("persona-b", self.store.read(other_persona, record_kind="memory", record_id="same-id")["payload"]["marker"])

    def test_policy_and_epoch_changes_do_not_create_a_second_owner_namespace(self) -> None:
        self.store.upsert(
            self.private, record_kind="memory", record_id="m1", revision=1,
            payload={"value": "stable"}, event_id="event-1",
        )
        next_epoch = NamespaceContext(
            kind="private", identity_id="person-a", group_id="", assurance="explicit_linked",
            profile_status="active", policy_version="req041-v2", migration_epoch="shadow-20260811",
        )
        self.assertEqual("stable", self.store.read(next_epoch, record_kind="memory", record_id="m1")["payload"]["value"])

    def test_pending_unverified_and_missing_context_fail_closed(self) -> None:
        pending = _context("pending")
        unverified = NamespaceContext(**{**self.private.__dict__, "assurance": "unverified"}) if hasattr(self.private, "__dict__") else NamespaceContext(
            kind="private", identity_id="person-a", group_id="", assurance="unverified", profile_status="active",
            policy_version="req041-v1", migration_epoch="shadow-20260810",
        )
        with self.assertRaisesRegex(ScopedStoreError, "namespace_pending_denied"):
            self.store.read(pending, record_kind="memory", record_id="x")
        with self.assertRaisesRegex(ScopedStoreError, "identity_assurance_insufficient"):
            self.store.read(unverified, record_kind="memory", record_id="x")
        with self.assertRaisesRegex(ScopedStoreError, "namespace_context_missing"):
            self.store.read(None, record_kind="memory", record_id="x")  # type: ignore[arg-type]

    def test_revision_and_event_id_are_idempotent_and_conflict_safe(self) -> None:
        create = dict(record_kind="memory", record_id="m1", revision=1, payload={"value": 1}, event_id="event-1")
        self.assertEqual("created", self.store.upsert(self.private, **create))
        self.assertEqual("duplicate", self.store.upsert(self.private, **create))
        with self.assertRaises(ScopedRecordConflict):
            self.store.upsert(self.private, **{**create, "payload": {"value": 2}})
        with self.assertRaises(ScopedRevisionGap):
            self.store.upsert(self.private, record_kind="memory", record_id="m1", revision=3, payload={"value": 3}, event_id="event-3")
        self.assertEqual(
            "updated",
            self.store.upsert(self.private, record_kind="memory", record_id="m1", revision=2, payload={"value": 2}, event_id="event-2"),
        )

    def test_tombstone_is_next_revision_and_prevents_resurrection(self) -> None:
        self.store.upsert(self.private, record_kind="memory", record_id="m1", revision=1, payload={"value": 1}, event_id="event-1")
        self.assertEqual("tombstoned", self.store.tombstone(self.private, record_kind="memory", record_id="m1", revision=2, event_id="delete-1"))
        self.assertIsNone(self.store.read(self.private, record_kind="memory", record_id="m1"))
        self.assertEqual("duplicate", self.store.tombstone(self.private, record_kind="memory", record_id="m1", revision=2, event_id="delete-1"))
        with self.assertRaisesRegex(ScopedRecordConflict, "scoped_record_tombstoned"):
            self.store.upsert(self.private, record_kind="memory", record_id="m1", revision=3, payload={"value": 3}, event_id="event-3")
        with closing(sqlite3.connect(self.store.path)) as connection:
            payload_json, payload_hash = connection.execute(
                "SELECT payload_json,payload_hash FROM scoped_records WHERE record_id='m1'"
            ).fetchone()
        self.assertEqual("{}", payload_json)
        self.assertEqual(64, len(payload_hash))

    def test_group_shared_cannot_store_subject_profile(self) -> None:
        shared = _context("group_shared", identity="", group="group-a")
        with self.assertRaisesRegex(ScopedStoreError, "group_shared_subject_access_denied"):
            self.store.upsert(shared, record_kind="profile_fact", record_id="nickname", revision=1, payload={"value": "x"}, event_id="event-1")
        self.assertEqual(
            "created",
            self.store.upsert(shared, record_kind="memory", record_id="group-topic", revision=1, payload={"value": "topic"}, event_id="event-2"),
        )

    def test_namespace_tombstone_is_atomic_idempotent_and_prevents_resurrection(self) -> None:
        self.store.upsert(
            self.private, record_kind="memory", record_id="req041-private-memory-a", revision=1,
            payload=build_scoped_domain_payload(
                domain="memory", source_kind="private", content={"value": "a"}, source_revision=1,
            ), event_id="write-a",
        )
        self.store.upsert(
            self.private, record_kind="rule", record_id="req041-private-rule-a", revision=1,
            payload=build_scoped_domain_payload(
                domain="learning", source_kind="private", content={"value": "rule"},
                source_revision=1, approval_state="approved", approved_by="user",
            ), event_id="write-rule",
        )
        self.store.upsert(
            self.private, record_kind="memory", record_id="legacy-unmanaged", revision=1,
            payload={"value": "keep"}, event_id="write-legacy",
        )
        result = self.store.tombstone_namespace(
            self.private, operation_id="archive-1", reason_code="person_archive",
        )
        self.assertEqual(2, result["count"])
        self.assertEqual(result, self.store.tombstone_namespace(
            self.private, operation_id="archive-1", reason_code="person_archive",
        ))
        self.assertIsNone(self.store.read(self.private, record_kind="memory", record_id="req041-private-memory-a"))
        self.assertEqual("keep", self.store.read(
            self.private, record_kind="memory", record_id="legacy-unmanaged"
        )["payload"]["value"])
        with self.assertRaisesRegex(ScopedRecordConflict, "scoped_record_tombstoned"):
            self.store.upsert(
                self.private, record_kind="memory", record_id="req041-private-memory-a", revision=3,
                payload=build_scoped_domain_payload(
                    domain="memory", source_kind="private", content={"value": "resurrect"},
                    source_revision=3,
                ), event_id="resurrect-a",
            )
        with self.assertRaisesRegex(ScopedRecordConflict, "scoped_namespace_operation_conflict"):
            self.store.tombstone_namespace(
                self.private, operation_id="archive-1", reason_code="different_reason",
            )

    def test_identity_archive_tombstones_private_and_all_member_scopes_only(self) -> None:
        shared = _context("group_shared", identity="", group="group-a")
        other = _context("private", identity="person-b")
        contexts = (
            (self.private, "req041-private-memory", "private"),
            (self.group_a, "req041-group-a-member", "group_member"),
            (self.group_b, "req041-group-b-member", "group_member"),
            (shared, "req041-group-shared", "group_shared"),
            (other, "req041-other-private", "private"),
        )
        for index, (context, record_id, source_kind) in enumerate(contexts, start=1):
            self.store.upsert(
                context, record_kind="memory", record_id=record_id, revision=1,
                payload=build_scoped_domain_payload(
                    domain="memory", source_kind=source_kind,
                    content={"marker": record_id}, source_revision=1,
                ), event_id=f"identity-archive-write-{index}",
            )
        result = self.store.tombstone_identity_scopes(
            self.private, operation_id="person-archive-1", reason_code="person_archive",
        )
        self.assertEqual(3, result["count"])
        self.assertEqual(3, result["namespace_count"])
        self.assertEqual(result, self.store.tombstone_identity_scopes(
            self.private, operation_id="person-archive-1", reason_code="person_archive",
        ))
        for context, record_id, _source_kind in contexts[:3]:
            self.assertIsNone(self.store.read(context, record_kind="memory", record_id=record_id))
        with closing(sqlite3.connect(self.store.path)) as connection:
            erased = connection.execute(
                "SELECT payload_json FROM scoped_records WHERE deleted=1 ORDER BY record_id"
            ).fetchall()
        self.assertEqual([("{}",), ("{}",), ("{}",)], erased)
        self.assertIsNotNone(self.store.read(shared, record_kind="memory", record_id="req041-group-shared"))
        self.assertIsNotNone(self.store.read(other, record_kind="memory", record_id="req041-other-private"))
        with self.assertRaisesRegex(ScopedStoreError, "scoped_identity_archive_context_invalid"):
            self.store.tombstone_identity_scopes(
                self.group_a, operation_id="bad-member-context", reason_code="person_archive",
            )
        with self.assertRaisesRegex(ScopedRecordConflict, "scoped_namespace_operation_conflict"):
            self.store.tombstone_identity_scopes(
                self.private, operation_id="person-archive-1", reason_code="different_reason",
            )

    def test_group_reset_erases_shared_and_all_members_but_allows_relearning(self) -> None:
        shared_a = _context("group_shared", identity="", group="group-a")
        member_a_other = _context("group_member", identity="person-b", group="group-a")
        shared_b = _context("group_shared", identity="", group="group-b")
        contexts = (
            (shared_a, "req041-shared-a", "group_shared"),
            (self.group_a, "req041-member-a", "group_member"),
            (member_a_other, "req041-member-a-other", "group_member"),
            (shared_b, "req041-shared-b", "group_shared"),
            (self.private, "req041-private", "private"),
        )
        for index, (context, record_id, source_kind) in enumerate(contexts, start=1):
            self.store.upsert(
                context, record_kind="memory", record_id=record_id, revision=1,
                payload=build_scoped_domain_payload(
                    domain="memory", source_kind=source_kind,
                    content={"sentinel": record_id}, source_revision=1,
                ), event_id=f"group-reset-write-{index}",
            )
        result = self.store.erase_group_scopes(
            shared_a, operation_id="group-reset-1", reason_code="group_reset",
        )
        self.assertEqual(3, result["count"])
        self.assertEqual(3, result["namespace_count"])
        for context, record_id, _source_kind in contexts[:3]:
            record = self.store.read(context, record_kind="memory", record_id=record_id)
            self.assertEqual({}, record["payload"]["content"])
            self.assertEqual(2, record["revision"])
        self.assertEqual("req041-shared-b", self.store.read(
            shared_b, record_kind="memory", record_id="req041-shared-b"
        )["payload"]["content"]["sentinel"])
        self.assertEqual("req041-private", self.store.read(
            self.private, record_kind="memory", record_id="req041-private"
        )["payload"]["content"]["sentinel"])
        self.assertEqual("updated", self.store.upsert(
            self.group_a, record_kind="memory", record_id="req041-member-a", revision=3,
            payload=build_scoped_domain_payload(
                domain="memory", source_kind="group_member", content={"sentinel": "relearned"},
                source_revision=3,
            ), event_id="group-relearn",
        ))
        self.assertEqual("relearned", self.store.read(
            self.group_a, record_kind="memory", record_id="req041-member-a"
        )["payload"]["content"]["sentinel"])
        with self.assertRaisesRegex(ScopedStoreError, "scoped_group_erase_context_invalid"):
            self.store.erase_group_scopes(
                self.group_a, operation_id="bad-group-reset", reason_code="group_reset",
            )

    def test_persona_reset_erases_all_four_scoped_kinds_and_preserves_other_persona(self) -> None:
        persona = "persona-a"
        private = _context("private", persona=persona)
        member = _context("group_member", group="group-a", persona=persona)
        shared = _context("group_shared", identity="", group="group-a", persona=persona)
        global_rules = _context("persona_global", identity="", persona=persona)
        other = _context("private", persona="persona-b")
        writes = (
            (private, "memory", "req041-private", "memory", "private", "not_applicable", ""),
            (member, "profile_fact", "req041-member", "profile", "group_member", "not_applicable", ""),
            (shared, "memory", "req041-shared", "memory", "group_shared", "not_applicable", ""),
            (global_rules, "rule", "req041-global", "learning", "persona_global", "approved", "administrator"),
            (other, "memory", "req041-other", "memory", "private", "not_applicable", ""),
        )
        for index, (context, record_kind, record_id, domain, source, approval, approved_by) in enumerate(writes, start=1):
            self.store.upsert(
                context, record_kind=record_kind, record_id=record_id, revision=1,
                payload=build_scoped_domain_payload(
                    domain=domain, source_kind=source, content={"sentinel": record_id},
                    source_revision=1, approval_state=approval, approved_by=approved_by,
                ), event_id=f"persona-reset-write-{index}",
            )
        result = self.store.erase_persona_scopes(
            global_rules, operation_id="persona-reset-1", reason_code="persona_reset",
        )
        self.assertEqual(4, result["count"])
        self.assertEqual({"group_member", "group_shared", "persona_global", "private"}, set(result["namespace_kinds"]))
        for context, record_kind, record_id, *_rest in writes[:4]:
            record = self.store.read(context, record_kind=record_kind, record_id=record_id)
            self.assertEqual({}, record["payload"]["content"])
            self.assertEqual(2, record["revision"])
        self.assertEqual("req041-other", self.store.read(
            other, record_kind="memory", record_id="req041-other",
        )["payload"]["content"]["sentinel"])
        self.assertEqual("updated", self.store.upsert(
            private, record_kind="memory", record_id="req041-private", revision=3,
            payload=build_scoped_domain_payload(
                domain="memory", source_kind="private", content={"sentinel": "relearned"},
                source_revision=3,
            ), event_id="persona-relearn",
        ))
        with self.assertRaisesRegex(ScopedStoreError, "scoped_persona_erase_context_invalid"):
            self.store.erase_persona_scopes(
                private, operation_id="bad-persona-reset", reason_code="persona_reset",
            )


if __name__ == "__main__":
    unittest.main()
