from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "portrait_renderer_memory"
if PACKAGE not in sys.modules:
    module = types.ModuleType(PACKAGE)
    module.__path__ = [str(ROOT)]
    sys.modules[PACKAGE] = module

from portrait_renderer_memory.core.portrait import build_evidence, normalized_claim_hash
from portrait_renderer_memory.core.portrait_renderer import (
    PortraitRenderer,
    render_portrait_items,
)
from portrait_renderer_memory.core.portrait_service import PortraitService
from portrait_renderer_memory.core.store import MemoryStore
from portrait_renderer_memory.unified_profile_contract import (
    build_capability_summary,
    build_portrait_request,
    build_profile_dto,
)


PERSON_REF = {
    "person_id": "person_" + "1" * 24,
    "resolved_identity_key": "chat-origin-v1:" + "2" * 64,
    "projection_revision": 1,
    "identity_assurance": "verified",
    "profile_status": "active",
}


class _Config:
    @staticmethod
    def int(_key: str, default: int) -> int:
        return default

    @staticmethod
    def float(_key: str, default: float) -> float:
        return default


class PortraitRendererTests(unittest.IsolatedAsyncioTestCase):
    def make_store(self) -> MemoryStore:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        store = MemoryStore(Path(temp.name) / "memory.db")
        store.initialize()
        self.addCleanup(store.close)
        return store

    async def asyncSetUp(self) -> None:
        self.store = self.make_store()
        await self.store.upsert_portrait_person_projection(
            PERSON_REF,
            build_capability_summary(
                {
                    "private_companion_enabled": True,
                    "portrait_mode": "learn_and_use",
                    "grant_source": "administrator",
                }
            ),
            source_scope="private",
        )
        self.service = PortraitService(self.store, _Config())
        self.request = build_portrait_request(
            person_ref=PERSON_REF,
            requester_person_id=PERSON_REF["person_id"],
            target_person_id=PERSON_REF["person_id"],
            scope="private",
            purpose="summarize_to_subject",
        )

    async def add_fact(
        self,
        *,
        key: str,
        dimension: str,
        summary: str,
        epistemic_status: str = "explicit",
        sensitivity: str = "low",
        tier: str = "base",
    ) -> dict[str, object]:
        evidence = build_evidence(
            person_ref=PERSON_REF,
            scope="private",
            session_id="fixture-session",
            message_id=f"fixture-{key}",
            source_identity_key=PERSON_REF["resolved_identity_key"],
            text=f"synthetic source {key}",
        )
        await self.store.add_portrait_evidence(evidence)
        return await self.store.upsert_portrait_fact(
            {
                "person_id": PERSON_REF["person_id"],
                "dimension": dimension,
                "normalized_claim_hash": normalized_claim_hash(dimension, key),
                "claim_summary": summary,
                "portrait_tier": tier,
                "producer_kind": "renderer_fixture",
                "producer_version": "renderer.fixture.v1",
                "derivation_kind": "explicit_statement",
                "epistemic_status": epistemic_status,
                "source_scope": "private",
                "usable_scope": "self_low_global",
                "confidence": 0.93,
                "sensitivity": sensitivity,
                "evidence_hashes": [evidence["evidence_hash"]],
                "operation_id": f"renderer-fixture-{key}",
            }
        )

    async def test_store_provenance_is_opt_in_and_contains_only_opaque_refs(self) -> None:
        await self.add_fact(
            key="food",
            dimension="preference",
            summary="喜欢烤肉",
        )
        plain = await self.store.portrait_summary(PERSON_REF["person_id"], scope="private")
        self.assertNotIn("provenance", plain["items"][0])
        detailed = await self.store.portrait_summary(
            PERSON_REF["person_id"],
            scope="private",
            include_provenance=True,
        )
        provenance = detailed["items"][0]["provenance"]
        self.assertTrue(provenance["fact_id"])
        self.assertRegex(provenance["evidence_refs"][0], r"^[0-9a-f]{64}$")
        self.assertNotIn("synthetic source", str(detailed))

    async def test_renderer_groups_stable_dimensions_and_traces_each_sentence(self) -> None:
        await self.add_fact(
            key="food",
            dimension="preference",
            summary="喜欢烤肉",
        )
        await self.add_fact(
            key="chat",
            dimension="communication_preference",
            summary="通常希望回复简短",
        )
        await self.add_fact(
            key="unknown",
            dimension="future_unreviewed_dimension",
            summary="不应显示",
        )
        await self.add_fact(
            key="health",
            dimension="preference",
            summary="敏感内容",
            sensitivity="high",
        )

        rendered = await PortraitRenderer(self.service).render(self.request)

        self.assertTrue(rendered["ok"])
        self.assertTrue(rendered["read_only"])
        self.assertEqual(["preference", "communication_preference"], list(rendered["dimensions"]))
        self.assertEqual({"preference", "communication_preference"}, {fact["dimension"] for fact in rendered["facts"]})
        self.assertEqual(len(rendered["facts"]), len(rendered["sentences"]))
        self.assertEqual(
            {sentence["fact_id"] for sentence in rendered["sentences"]},
            {fact["fact_id"] for fact in rendered["facts"]},
        )
        for sentence in rendered["sentences"]:
            self.assertTrue(sentence["evidence_refs"])
            self.assertIn(sentence["fact_id"], str(rendered["facts"]))
        self.assertIn("喜欢烤肉", rendered["natural_language"])
        self.assertNotIn("不应显示", str(rendered))
        self.assertNotIn("敏感内容", str(rendered))
        # The store's low-sensitivity gate removes the high-sensitivity row;
        # the renderer then omits the unsupported dimension.
        self.assertEqual(1, rendered["omitted"]["count"])

    async def test_inferred_fact_uses_cautious_language(self) -> None:
        await self.add_fact(
            key="inferred-food",
            dimension="preference",
            summary="喜欢烤肉",
            epistemic_status="inferred",
            tier="intelligent",
        )
        rendered = await PortraitRenderer(self.service).render(self.request)
        self.assertIn("从多条独立证据看", rendered["natural_language"])
        self.assertEqual("inferred", rendered["facts"][0]["epistemic_status"])

    async def test_service_exposes_the_same_read_only_renderer(self) -> None:
        await self.add_fact(
            key="service-adapter",
            dimension="preference",
            summary="喜欢烤肉",
        )
        rendered = await self.service.render_readonly_portrait(self.request)
        self.assertTrue(rendered["read_only"])
        self.assertEqual(1, len(rendered["facts"]))
        self.assertTrue(rendered["sentences"][0]["evidence_refs"])
        history_rendered = await self.service.render_history_portrait(
            {
                "target_person_id": PERSON_REF["person_id"],
                "target_identity": PERSON_REF["resolved_identity_key"],
                "source_scopes": ["private"],
                "operation_id": "renderer-history-read",
            }
        )
        self.assertTrue(history_rendered["read_only"])
        self.assertEqual(1, len(history_rendered["facts"]))

    async def test_renderer_is_read_only_and_denied_request_returns_no_portrait(self) -> None:
        await self.add_fact(
            key="food",
            dimension="preference",
            summary="喜欢烤肉",
        )
        with self.store._lock:
            before = self.store._conn.execute(
                "SELECT COUNT(*) AS count FROM portrait_facts"
            ).fetchone()["count"]
        await PortraitRenderer(self.service).render(self.request)
        with self.store._lock:
            after = self.store._conn.execute(
                "SELECT COUNT(*) AS count FROM portrait_facts"
            ).fetchone()["count"]
        self.assertEqual(before, after)

        denied = dict(self.request)
        denied["requester_person_id"] = "person_" + "9" * 24
        denied_result = await PortraitRenderer(self.service).render(denied)
        self.assertFalse(denied_result["ok"])
        self.assertEqual([], denied_result["facts"])
        self.assertEqual("", denied_result["natural_language"])
        self.assertEqual("", denied_result["person_id"])

    def test_renderer_omits_untraceable_and_empty_dimensions(self) -> None:
        rendered = render_portrait_items(
            [
                {
                    "dimension": "preference",
                    "summary": "没有证据引用",
                    "sensitivity": "low",
                    "epistemic_status": "explicit",
                    "confidence": 0.9,
                },
                {
                    "dimension": "preference",
                    "summary": "应显示",
                    "sensitivity": "low",
                    "epistemic_status": "explicit",
                    "confidence": 0.9,
                    "provenance": {
                        "fact_id": "fact-fixture",
                        "evidence_refs": ["a" * 64],
                        "source_scope": "private",
                    },
                },
                {
                    "dimension": "preference",
                    "summary": "置信度无效",
                    "sensitivity": "low",
                    "epistemic_status": "explicit",
                    "confidence": "not-a-number",
                    "provenance": {
                        "fact_id": "fact-invalid-confidence",
                        "evidence_refs": ["b" * 64],
                    },
                },
            ]
        )
        self.assertEqual(["preference"], list(rendered["dimensions"]))
        self.assertNotIn("没有证据引用", str(rendered))
        self.assertNotIn("置信度无效", str(rendered))
        self.assertEqual(1, rendered["omitted"]["reasons"]["provenance_missing"])
        self.assertEqual(1, rendered["omitted"]["reasons"]["confidence_invalid"])


if __name__ == "__main__":
    unittest.main()
