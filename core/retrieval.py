from __future__ import annotations

import math
import re
import inspect
import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from .identity import session_target_id
from .models import MemoryRecord, SearchResult, SessionContext, clean_text
from .store import MemoryStore
from .time_intent import TimeIntent
from .visibility import VisibilityPolicy


class RetrievalEngine:
    def __init__(
        self,
        store: MemoryStore,
        policy: VisibilityPolicy,
        *,
        retrieval_mode: str = "auto",
        rerank_provider: Any = None,
        rerank_provider_id: str = "",
        rerank_candidate_multiplier: int = 5,
        rerank_candidate_limit: int = 32,
        rerank_timeout_ms: int = 1200,
        embedding_provider: Any = None,
        embedding_provider_id: str = "",
        embedding_enabled: bool = False,
        embedding_candidate_limit: int = 1200,
        embedding_top_k: int = 32,
        embedding_score_threshold: float = 0.34,
        embedding_weight: float = 0.55,
        embedding_timeout_ms: int = 5000,
        embedding_max_text_chars: int = 1200,
        current_window_candidate_limit: int = 600,
        keyword_fallback_min_fts_candidates: int = 80,
        knowledge_graph_enabled: bool = True,
        knowledge_graph_expansion_limit: int = 12,
        usage_recorder: Any | None = None,
    ):
        self.store = store
        self.policy = policy
        self.retrieval_mode = clean_text(retrieval_mode or "auto", 40).lower()
        if self.retrieval_mode not in {"auto", "basic", "rerank"}:
            self.retrieval_mode = "auto"
        self.rerank_provider = rerank_provider
        self.rerank_provider_id = clean_text(rerank_provider_id, 160)
        self.rerank_candidate_multiplier = max(1, int(rerank_candidate_multiplier or 5))
        self.rerank_candidate_limit = max(1, int(rerank_candidate_limit or 32))
        self.rerank_timeout_ms = max(0, int(rerank_timeout_ms or 0))
        self.embedding_provider = embedding_provider
        self.embedding_provider_id = clean_text(embedding_provider_id, 160)
        self.embedding_enabled = bool(embedding_enabled)
        self.embedding_candidate_limit = max(1, int(embedding_candidate_limit or 1200))
        self.embedding_top_k = max(1, int(embedding_top_k or 32))
        self.embedding_score_threshold = max(0.0, min(1.0, float(embedding_score_threshold or 0.0)))
        self.embedding_weight = max(0.0, min(2.0, float(embedding_weight or 0.0)))
        self.embedding_timeout_ms = max(0, int(embedding_timeout_ms or 0))
        self.embedding_max_text_chars = max(200, int(embedding_max_text_chars or 1200))
        self.current_window_candidate_limit = max(1, int(current_window_candidate_limit or 600))
        self.keyword_fallback_min_fts_candidates = max(
            0,
            int(keyword_fallback_min_fts_candidates or 0),
        )
        self.knowledge_graph_enabled = bool(knowledge_graph_enabled)
        self.knowledge_graph_expansion_limit = max(0, int(knowledge_graph_expansion_limit or 0))
        self.usage_recorder = usage_recorder if callable(usage_recorder) else None
        self._rank_path_info: dict[str, Any] = {}
        self.last_path_info: dict[str, Any] = {
            "mode": self.retrieval_mode,
            "path": "basic",
            "provider_id": self.rerank_provider_id,
            "reason": "not_started",
            "embedding_enabled": self.embedding_enabled,
            "embedding_provider_id": self.embedding_provider_id,
            "embedding_reason": "not_started",
        }

    async def search(
        self,
        query: str,
        ctx: SessionContext,
        top_k: int = 6,
        *,
        time_intent: TimeIntent | None = None,
    ) -> list[SearchResult]:
        results, _blocked = await self.search_with_diagnostics(query, ctx, top_k, time_intent=time_intent)
        return results

    async def revalidate_cached_results(
        self,
        results: list[SearchResult],
        ctx: SessionContext,
    ) -> list[SearchResult]:
        """Refresh cached rows and re-run current visibility and ACL checks."""
        memory_ids = [
            clean_text(getattr(getattr(item, "memory", None), "id", ""), 120)
            for item in results or []
        ]
        current = await self.store.get_memories_by_ids([memory_id for memory_id in memory_ids if memory_id])
        acl_state = await self._acl_state() if self.policy.enable_acl_rules else self._empty_acl_state()
        validated: list[SearchResult] = []
        for item, memory_id in zip(results or [], memory_ids):
            memory = current.get(memory_id)
            if memory is None:
                continue
            visible_reason, blocked_reason = self._search_visibility_reason(memory, ctx, acl_state)
            if not visible_reason or blocked_reason:
                continue
            item.memory = memory
            validated.append(item)
        return validated

    async def revalidate_cached_diagnostics(
        self,
        blocked: list[dict[str, str]],
        ctx: SessionContext,
    ) -> list[dict[str, str]]:
        """Drop cached diagnostic snippets that are no longer readable."""
        memory_ids = [clean_text(item.get("id"), 120) for item in blocked if isinstance(item, dict)]
        current = await self.store.get_memories_by_ids([memory_id for memory_id in memory_ids if memory_id])
        acl_state = await self._acl_state() if self.policy.enable_acl_rules else self._empty_acl_state()
        validated: list[dict[str, str]] = []
        for item in blocked or []:
            if not isinstance(item, dict):
                continue
            memory_id = clean_text(item.get("id"), 120)
            if not memory_id:
                validated.append({**item, "content": ""})
                continue
            memory = current.get(memory_id)
            if memory is None:
                continue
            visible_reason, blocked_reason = self._search_visibility_reason(memory, ctx, acl_state)
            if not visible_reason or blocked_reason:
                continue
            validated.append({**item, "content": clean_text(memory.content, 120)})
        return validated

    async def search_with_diagnostics(
        self,
        query: str,
        ctx: SessionContext,
        top_k: int = 6,
        *,
        time_intent: TimeIntent | None = None,
    ) -> tuple[list[SearchResult], list[dict[str, str]]]:
        results, blocked = await self._rank_candidates(query, ctx, time_intent=time_intent)
        results = await self._maybe_rerank_results(query, results, max(1, int(top_k or 1)))
        selected = results[: max(1, int(top_k or 1))]
        selected, mutable_blocked = self._collapse_mutable_fact_results(query, ctx, selected)
        blocked.extend(mutable_blocked)
        selected, source_blocked = self._collapse_redundant_source_results(selected)
        blocked.extend(source_blocked)
        await self.store.mark_accessed([item.memory.id for item in selected])
        return selected, blocked

    async def search_by_slots(
        self,
        query: str,
        ctx: SessionContext,
        *,
        slot_limits: dict[str, int],
        total_limit: int = 6,
        time_intent: TimeIntent | None = None,
    ) -> tuple[list[SearchResult], list[dict[str, str]], dict[str, list[SearchResult]]]:
        ranked, blocked = await self._rank_candidates(query, ctx, time_intent=time_intent)
        total = max(1, int(total_limit or 1))
        ranked = await self._maybe_rerank_results(query, ranked, total)
        slot_order = [
            "open_loop",
            "self_timeline",
            "user_profile",
            "current_window",
            "conversation_summary",
            "stable_memory",
        ]
        selected: list[SearchResult] = []
        selected_ids: set[str] = set()
        slot_map: dict[str, list[SearchResult]] = {slot: [] for slot in slot_order}

        for slot in slot_order:
            limit = max(0, int(slot_limits.get(slot, 0) or 0))
            if limit <= 0:
                continue
            for item in ranked:
                if len(selected) >= total or len(slot_map[slot]) >= limit:
                    break
                if item.memory.id in selected_ids:
                    continue
                if self._slot_for_memory(item.memory, ctx) != slot:
                    continue
                item.reason = self._with_slot_reason(item.reason, slot)
                slot_map[slot].append(item)
                selected.append(item)
                selected_ids.add(item.memory.id)

        if len(selected) < total:
            for item in ranked:
                if len(selected) >= total:
                    break
                if item.memory.id in selected_ids:
                    continue
                slot = self._slot_for_memory(item.memory, ctx)
                item.reason = self._with_slot_reason(item.reason, slot)
                slot_map.setdefault(slot, []).append(item)
                selected.append(item)
                selected_ids.add(item.memory.id)

        selected, mutable_blocked, slot_map = self._collapse_mutable_fact_slots(query, ctx, selected, slot_map)
        blocked.extend(mutable_blocked)
        selected, source_blocked, slot_map = self._collapse_redundant_source_slots(selected, slot_map)
        blocked.extend(source_blocked)
        await self.store.mark_accessed([item.memory.id for item in selected])
        return selected, blocked, {slot: items for slot, items in slot_map.items() if items}

    async def _maybe_rerank_results(
        self,
        query: str,
        ranked: list[SearchResult],
        final_limit: int,
    ) -> list[SearchResult]:
        if not ranked:
            self.last_path_info = {
                "mode": self.retrieval_mode,
                "path": "basic",
                "provider_id": self.rerank_provider_id,
                "reason": "no_candidates",
                "candidate_count": 0,
                **self._rank_path_info,
            }
            return ranked
        if self.retrieval_mode == "basic":
            self.last_path_info = {
                "mode": self.retrieval_mode,
                "path": "basic",
                "provider_id": self.rerank_provider_id,
                "reason": "mode_basic",
                "candidate_count": len(ranked),
                **self._rank_path_info,
            }
            return ranked
        if self.rerank_provider is None or not hasattr(self.rerank_provider, "rerank"):
            path = "fallback_basic" if self.retrieval_mode == "rerank" else "basic"
            self.last_path_info = {
                "mode": self.retrieval_mode,
                "path": path,
                "provider_id": self.rerank_provider_id,
                "reason": "no_rerank_provider",
                "candidate_count": len(ranked),
                **self._rank_path_info,
            }
            return ranked

        query_text = clean_text(query, 1000)
        if not query_text:
            path = "fallback_basic" if self.retrieval_mode == "rerank" else "basic"
            self.last_path_info = {
                "mode": self.retrieval_mode,
                "path": path,
                "provider_id": self.rerank_provider_id,
                "reason": "rerank_skipped_empty_query",
                "candidate_count": len(ranked),
                **self._rank_path_info,
            }
            return ranked

        pool_size = min(
            len(ranked),
            max(max(1, int(final_limit or 1)) * self.rerank_candidate_multiplier, max(1, int(final_limit or 1))),
            self.rerank_candidate_limit,
        )
        pool = ranked[:pool_size]
        rerank_pool: list[SearchResult] = []
        documents: list[str] = []
        for item in pool:
            document = clean_text(self._rerank_document_text(item), 1200)
            if not document:
                continue
            rerank_pool.append(item)
            documents.append(document)
        filtered_count = pool_size - len(rerank_pool)
        request_shape = self._rerank_request_shape(query_text, documents)
        if not documents:
            path = "fallback_basic" if self.retrieval_mode == "rerank" else "basic"
            self.last_path_info = {
                "mode": self.retrieval_mode,
                "path": path,
                "provider_id": self.rerank_provider_id,
                "reason": "rerank_skipped_no_valid_documents",
                "candidate_count": len(ranked),
                "rerank_pool": 0,
                "rerank_filtered": filtered_count,
                **request_shape,
                **self._rank_path_info,
            }
            return ranked
        try:
            rerank_resp = await self._call_rerank_provider(query_text, documents)
            reranked = self._apply_rerank_response(rerank_resp, rerank_pool)
        except Exception as error:
            self.last_path_info = {
                "mode": self.retrieval_mode,
                "path": "fallback_basic",
                "provider_id": self.rerank_provider_id,
                "reason": f"rerank_error:{clean_text(error, 160)}",
                "candidate_count": len(ranked),
                "rerank_pool": len(rerank_pool),
                "rerank_filtered": filtered_count,
                **request_shape,
                **self._rank_path_info,
            }
            return ranked

        if not reranked:
            self.last_path_info = {
                "mode": self.retrieval_mode,
                "path": "fallback_basic",
                "provider_id": self.rerank_provider_id,
                "reason": "rerank_empty_response",
                "candidate_count": len(ranked),
                "rerank_pool": len(rerank_pool),
                "rerank_filtered": filtered_count,
                **request_shape,
                **self._rank_path_info,
            }
            return ranked

        anchors = self._rerank_anchor_results(query_text, pool, final_limit)
        merged: list[SearchResult] = []
        seen: set[str] = set()
        for item in [*anchors, *reranked]:
            memory_id = item.memory.id
            if memory_id and memory_id in seen:
                continue
            if memory_id:
                seen.add(memory_id)
            merged.append(item)
        tail = [item for item in pool if not item.memory.id or item.memory.id not in seen]
        rest = ranked[pool_size:]
        self.last_path_info = {
            "mode": self.retrieval_mode,
            "path": "rerank",
            "provider_id": self.rerank_provider_id or "<auto>",
            "reason": "rerank_applied",
            "candidate_count": len(ranked),
            "rerank_pool": len(rerank_pool),
            "rerank_filtered": filtered_count,
            "reranked_count": len(reranked),
            "lexical_anchors": len(anchors),
            **request_shape,
            **self._rank_path_info,
        }
        return merged + tail + rest

    def _rerank_anchor_results(
        self,
        query: str,
        pool: list[SearchResult],
        final_limit: int,
    ) -> list[SearchResult]:
        if not pool:
            return []
        anchors = [
            item
            for item in pool
            if self._strong_lexical_match(query, item.memory)
        ]
        if not anchors:
            return []
        anchors.sort(key=lambda item: item.score, reverse=True)
        return anchors[: max(1, min(len(anchors), int(final_limit or 1)))]

    def _strong_lexical_match(self, query: str, memory: MemoryRecord) -> bool:
        terms = self._terms(query)
        if not terms:
            return False
        haystack = self._haystack(memory)
        compact_haystack = re.sub(r"\s+", "", haystack)
        profile = self._query_profile(query, terms)
        exact_phrases = [str(item) for item in profile.get("exact_phrases", []) if str(item)]
        if any(phrase in compact_haystack for phrase in exact_phrases):
            return True
        hits = sum(1 for term in terms if term and term in haystack)
        contextual_recall = self._looks_like_contextual_recall_query(query)
        if contextual_recall and hits >= 1:
            return True
        return hits >= max(2, int(profile.get("min_hits", 1) or 1))

    async def _call_rerank_provider(self, query: str, documents: list[str]) -> Any:
        method = self.rerank_provider.rerank
        query_text = clean_text(query, 1000)
        document_texts = [clean_text(document, 1200) for document in documents]
        if not query_text:
            raise ValueError("rerank query must not be empty")
        if not document_texts or any(not document for document in document_texts):
            raise ValueError("rerank documents must not contain empty text")
        kwargs: dict[str, Any] = {"query": query_text, "documents": document_texts}
        try:
            signature = inspect.signature(method)
            params = signature.parameters
            accepts_top_n = "top_n" in params or any(
                param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values()
            )
        except Exception:
            accepts_top_n = True
        if accepts_top_n:
            kwargs["top_n"] = len(documents)
        prompt = self._usage_prompt_for_rerank(query_text, document_texts)
        started = datetime.now(timezone.utc)
        resp: Any = None
        success = False
        error = ""
        try:
            result = method(**kwargs)
            if inspect.isawaitable(result):
                if self.rerank_timeout_ms > 0:
                    resp = await asyncio.wait_for(result, timeout=self.rerank_timeout_ms / 1000.0)
                else:
                    resp = await result
            else:
                resp = result
            success = True
            return resp
        except Exception as exc:
            error = str(exc)
            raise
        finally:
            elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
            self._record_usage(
                task="memory_rerank",
                provider_id=self.rerank_provider_id or "<auto>",
                prompt=prompt,
                completion="",
                resp=resp,
                success=success,
                elapsed_ms=elapsed_ms,
                error=error,
            )

    def _rerank_request_shape(self, query: str, documents: list[str]) -> dict[str, Any]:
        lengths = [len(clean_text(document, 1200)) for document in documents]
        model = clean_text(getattr(self.rerank_provider, "model", ""), 240)
        if not model:
            provider_config = getattr(self.rerank_provider, "provider_config", None)
            if isinstance(provider_config, dict):
                model = clean_text(provider_config.get("rerank_model") or provider_config.get("model"), 240)
        return {
            "rerank_query_chars": len(clean_text(query, 1000)),
            "rerank_document_count": len(lengths),
            "rerank_document_min_chars": min(lengths) if lengths else 0,
            "rerank_document_max_chars": max(lengths) if lengths else 0,
            "rerank_model_chars": len(model),
        }

    def _apply_rerank_response(
        self,
        rerank_resp: Any,
        pool: list[SearchResult],
    ) -> list[SearchResult]:
        items = self._extract_rerank_items(rerank_resp)
        if not items:
            return []
        by_id = {item.memory.id: item for item in pool if item.memory.id}
        by_text = {self._rerank_document_text(item): item for item in pool}
        scored: list[tuple[int, SearchResult, float]] = []
        used_ids: set[str] = set()
        for index, item in enumerate(items):
            result = self._rerank_item_to_result(item, index, pool, by_id, by_text)
            if result is None:
                continue
            result_item, score = result
            memory_id = result_item.memory.id
            if memory_id and memory_id in used_ids:
                continue
            if memory_id:
                used_ids.add(memory_id)
            scored.append((index, result_item, score))
        if not scored:
            return []
        max_score = max(score for _index, _item, score in scored)
        min_score = min(score for _index, _item, score in scored)
        ranked: list[SearchResult] = []
        for rank_index, item, score in sorted(scored, key=lambda row: (-row[2], row[0])):
            if max_score > min_score:
                normalized = (score - min_score) / (max_score - min_score)
            else:
                normalized = 1.0 - (rank_index / max(1, len(scored) - 1)) if len(scored) > 1 else 1.0
            ranked.append(
                SearchResult(
                    memory=item.memory,
                    score=float(item.score) + (0.75 * max(0.0, min(1.0, normalized))),
                    reason=f"{item.reason};retrieval_path=rerank;rerank_score={score:.4g}",
                )
            )
        return ranked

    def _extract_rerank_items(self, rerank_resp: Any) -> list[Any]:
        if rerank_resp is None:
            return []
        if isinstance(rerank_resp, dict):
            if rerank_resp.get("code") not in (None, 0, 200, "0", "200"):
                return []
            items = rerank_resp.get("results")
            if items is None:
                data = rerank_resp.get("data")
                if isinstance(data, list):
                    items = data
                elif isinstance(data, dict):
                    items = data.get("results") or data.get("items")
            if isinstance(items, list):
                return items
            return []
        if isinstance(rerank_resp, list):
            return rerank_resp
        results = getattr(rerank_resp, "results", None)
        return results if isinstance(results, list) else []

    def _rerank_item_to_result(
        self,
        item: Any,
        fallback_index: int,
        pool: list[SearchResult],
        by_id: dict[str, SearchResult],
        by_text: dict[str, SearchResult],
    ) -> tuple[SearchResult, float] | None:
        if isinstance(item, (int, float)):
            if 0 <= fallback_index < len(pool):
                return pool[fallback_index], float(item)
            return None
        if not isinstance(item, dict):
            item = {
                "id": getattr(item, "id", None),
                "index": getattr(item, "index", None),
                "score": getattr(item, "score", None),
                "relevance_score": getattr(item, "relevance_score", None),
                "rerank_score": getattr(item, "rerank_score", None),
                "text": getattr(item, "text", None),
                "document": getattr(item, "document", None),
            }
        result_item: SearchResult | None = None
        raw_index = item.get("index")
        if isinstance(raw_index, int) and 0 <= raw_index < len(pool):
            result_item = pool[raw_index]
        if result_item is None:
            item_id = clean_text(
                item.get("id") or item.get("document_id") or item.get("memory_id") or item.get("item_id"),
                200,
            )
            if item_id:
                result_item = by_id.get(item_id)
        if result_item is None:
            text = clean_text(item.get("text") or item.get("document") or item.get("content"), 4000)
            if text:
                result_item = by_text.get(text)
        if result_item is None and 0 <= fallback_index < len(pool):
            result_item = pool[fallback_index]
        if result_item is None:
            return None
        raw_score = item.get("score")
        if raw_score is None:
            raw_score = item.get("relevance_score")
        if raw_score is None:
            raw_score = item.get("rerank_score")
        try:
            score = float(raw_score)
        except Exception:
            score = float(len(pool) - fallback_index)
        return result_item, score

    def _rerank_document_text(self, item: SearchResult) -> str:
        memory = item.memory
        content = clean_text(memory.content, 1000)
        evidence = clean_text(memory.evidence, 600)
        tags = [clean_text(tag, 80) for tag in (memory.tags or []) if clean_text(tag, 80)]
        if not content and not evidence and not tags:
            return ""
        parts = [
            f"类型: {memory.memory_type}",
            f"范围: {memory.scope}/{memory.visibility}",
        ]
        if tags:
            parts.append(f"标签: {' '.join(tags)}")
        if content:
            parts.append(f"内容: {content}")
        if evidence:
            parts.append(f"证据: {evidence}")
        return clean_text("\n".join(parts), 1200)

    def _with_slot_reason(self, reason: str, slot: str) -> str:
        if reason.startswith("slot="):
            return reason
        return f"slot={slot};{reason}"

    def _collapse_mutable_fact_slots(
        self,
        query: str,
        ctx: SessionContext,
        selected: list[SearchResult],
        slot_map: dict[str, list[SearchResult]],
    ) -> tuple[list[SearchResult], list[dict[str, str]], dict[str, list[SearchResult]]]:
        collapsed, blocked = self._collapse_mutable_fact_results(query, ctx, selected)
        if not blocked:
            return selected, blocked, slot_map
        kept_ids = {item.memory.id for item in collapsed if item.memory.id}
        cleaned: dict[str, list[SearchResult]] = {}
        for slot, items in slot_map.items():
            kept = [item for item in items if not item.memory.id or item.memory.id in kept_ids]
            if kept:
                cleaned[slot] = kept
            else:
                cleaned[slot] = []
        return collapsed, blocked, cleaned

    def _collapse_redundant_source_slots(
        self,
        selected: list[SearchResult],
        slot_map: dict[str, list[SearchResult]],
    ) -> tuple[list[SearchResult], list[dict[str, str]], dict[str, list[SearchResult]]]:
        collapsed, blocked = self._collapse_redundant_source_results(selected)
        if not blocked:
            return selected, blocked, slot_map
        kept_ids = {item.memory.id for item in collapsed if item.memory.id}
        cleaned: dict[str, list[SearchResult]] = {}
        for slot, items in slot_map.items():
            cleaned[slot] = [item for item in items if not item.memory.id or item.memory.id in kept_ids]
        return collapsed, blocked, cleaned

    def _collapse_redundant_source_results(
        self,
        results: list[SearchResult],
    ) -> tuple[list[SearchResult], list[dict[str, str]]]:
        if len(results) < 2:
            return results, []
        groups: dict[tuple[str, str, str], list[tuple[int, SearchResult]]] = {}
        for index, item in enumerate(results):
            key = self._redundant_source_key(item.memory)
            if key:
                groups.setdefault(key, []).append((index, item))
        drop_reasons: dict[str, str] = {}
        for key, entries in groups.items():
            if len(entries) < 2:
                continue
            keep_index, keep_item = max(entries, key=lambda entry: (entry[1].score, self._memory_time_rank(entry[1].memory), -entry[0]))
            keep_id = keep_item.memory.id
            for _index, item in entries:
                memory_id = item.memory.id
                if not memory_id or memory_id == keep_id:
                    continue
                drop_reasons.setdefault(
                    memory_id,
                    f"source_summary_duplicate:key={key[0]}:{key[1]};kept={keep_id}",
                )
        if not drop_reasons:
            return results, []
        collapsed = [item for item in results if item.memory.id not in drop_reasons]
        blocked = [
            {
                "id": item.memory.id,
                "reason": drop_reasons[item.memory.id],
                "content": clean_text(item.memory.content, 120),
            }
            for item in results
            if item.memory.id in drop_reasons
        ]
        return collapsed, blocked

    def _redundant_source_key(self, memory: MemoryRecord) -> tuple[str, str, str] | None:
        source_plugin = clean_text(memory.source_plugin, 80).lower()
        memory_type = clean_text(memory.memory_type, 120).lower()
        if source_plugin != "livingmemory" or not memory_type.startswith("livingmemory_graph:"):
            return None
        metadata = memory.metadata if isinstance(memory.metadata, dict) else {}
        source_memory_id = clean_text(metadata.get("source_memory_id"), 120)
        nested = metadata.get("livingmemory_metadata")
        if not source_memory_id and isinstance(nested, dict):
            source_memory_id = clean_text(nested.get("source_memory_id"), 120)
        if not source_memory_id:
            return None
        persona_id = clean_text(metadata.get("persona_id"), 120)
        if not persona_id and isinstance(nested, dict):
            persona_id = clean_text(nested.get("persona_id"), 120)
        session_id = clean_text(memory.session_id, 200)
        if not session_id and isinstance(nested, dict):
            session_id = clean_text(nested.get("session_id"), 200)
        scope_key = f"{memory.scope}:{session_id or memory.group_id}:{persona_id}"
        return ("livingmemory_graph_source", source_memory_id, scope_key)

    def _collapse_mutable_fact_results(
        self,
        query: str,
        ctx: SessionContext,
        results: list[SearchResult],
    ) -> tuple[list[SearchResult], list[dict[str, str]]]:
        query_keys = self._mutable_fact_keys(query)
        if len(results) < 2 or not query_keys:
            return results, []

        groups: dict[tuple[str, str, str], list[tuple[int, SearchResult]]] = {}
        for index, item in enumerate(results):
            memory_keys = self._mutable_fact_keys_for_memory(item.memory)
            matched = query_keys & memory_keys
            if not matched:
                continue
            owner_key = self._mutable_fact_owner_key(item.memory, ctx)
            subject_key = self._mutable_fact_subject_key(item.memory)
            for key in matched:
                groups.setdefault((owner_key, subject_key, key), []).append((index, item))

        drop_reasons: dict[str, str] = {}
        for (_owner_key, _subject_key, key), entries in groups.items():
            if len(entries) < 2:
                continue
            keep_index, keep_item = max(
                entries,
                key=lambda entry: (
                    self._memory_time_rank(entry[1].memory),
                    entry[1].score,
                    -entry[0],
                ),
            )
            keep_id = keep_item.memory.id
            for _index, item in entries:
                memory_id = item.memory.id
                if not memory_id or memory_id == keep_id:
                    continue
                drop_reasons.setdefault(
                    memory_id,
                    f"mutable_fact_latest_only:key={key};kept={keep_id}",
                )

        if not drop_reasons:
            return results, []
        collapsed = [item for item in results if item.memory.id not in drop_reasons]
        blocked = [
            {
                "id": item.memory.id,
                "reason": drop_reasons[item.memory.id],
                "content": clean_text(item.memory.content, 120),
            }
            for item in results
            if item.memory.id in drop_reasons
        ]
        return collapsed, blocked

    def _mutable_fact_keys_for_memory(self, memory: MemoryRecord) -> set[str]:
        metadata = memory.metadata if isinstance(memory.metadata, dict) else {}
        metadata_text = " ".join(
            clean_text(metadata.get(key), 120)
            for key in ("key", "fact_key", "slot", "topic", "title")
            if clean_text(metadata.get(key), 120)
        )
        text = " ".join(
            [
                memory.content,
                memory.evidence,
                " ".join(memory.tags or []),
                memory.memory_type,
                metadata_text,
            ]
        )
        return self._mutable_fact_keys(text)

    def _mutable_fact_keys(self, text: str) -> set[str]:
        compact = re.sub(r"\s+", "", clean_text(text, 1200)).lower()
        if not compact:
            return set()
        families = {
            "password": (
                "密码",
                "口令",
                "暗号",
                "验证码",
                "pin",
                "passcode",
                "password",
                "token",
                "apikey",
                "api_key",
                "密钥",
                "秘钥",
            ),
            "account": ("账号", "账户", "帐号", "用户名", "登录名", "user_id", "userid"),
            "phone": ("手机号", "手机号码", "电话", "联系电话", "号码"),
            "email": ("邮箱", "电子邮件", "email", "e-mail"),
            "address": ("地址", "住址", "位置", "收件地址"),
            "name": ("昵称", "称呼", "名字", "姓名", "网名"),
        }
        keys: set[str] = set()
        for key, aliases in families.items():
            if any(alias in compact for alias in aliases):
                keys.add(key)
        return keys

    def _mutable_fact_owner_key(self, memory: MemoryRecord, ctx: SessionContext) -> str:
        if memory.visibility == "bot_self":
            return "bot:self"
        if memory.scope == "group" or memory.visibility == "group_public":
            owner = memory.group_id or memory.session_id or ctx.group_id or ctx.session_id
            return f"group:{clean_text(owner, 160)}"
        if memory.scope == "private" or memory.visibility == "private_pair":
            owner = ""
            for entity in (memory.subject, memory.object):
                if entity.kind == "user" and entity.id and entity.id != "self":
                    owner = entity.id
                    break
            owner = owner or memory.session_id or ctx.user_id or ctx.session_id
            return f"private:{clean_text(owner, 160)}"
        owner = memory.session_id or ctx.session_id or memory.group_id
        return f"{clean_text(memory.scope or ctx.scope, 40)}:{clean_text(owner, 160)}"

    def _mutable_fact_subject_key(self, memory: MemoryRecord) -> str:
        ids: list[str] = []
        for entity in (memory.subject, memory.object):
            if entity.kind == "user" and entity.id and entity.id != "self":
                ids.append(clean_text(entity.id, 160))
        if ids:
            return "user:" + ",".join(dict.fromkeys(ids))
        return "window"

    def _memory_time_rank(self, memory: MemoryRecord) -> float:
        for value in (memory.occurred_at, memory.updated_at, memory.created_at):
            text = clean_text(value, 80)
            if not text:
                continue
            try:
                dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.timestamp()
            except Exception:
                continue
        return 0.0

    def _memory_overlaps_time_window(self, memory: MemoryRecord, time_intent: TimeIntent) -> bool:
        if not time_intent.active:
            return True
        window_start = self._parse_time(time_intent.start_at)
        window_end = self._parse_time(time_intent.end_at)
        if window_start is None or window_end is None:
            return True
        metadata = memory.metadata if isinstance(memory.metadata, dict) else {}
        candidate_ranges: list[tuple[datetime, datetime]] = []
        start_at = self._parse_time(clean_text(metadata.get("start_at"), 80))
        end_at = self._parse_time(clean_text(metadata.get("end_at"), 80))
        if start_at is not None or end_at is not None:
            start = start_at or end_at
            end = end_at or start_at
            if start is not None and end is not None:
                if end <= start:
                    end = start + timedelta(days=1)
                candidate_ranges.append((start, end))
        for value in (memory.occurred_at, memory.created_at, memory.updated_at):
            dt = self._parse_time(value)
            if dt is not None:
                candidate_ranges.append((dt, dt + timedelta(seconds=1)))
        if not candidate_ranges:
            return False
        return any(start < window_end and end > window_start for start, end in candidate_ranges)

    @staticmethod
    def _parse_time(value: str) -> datetime | None:
        text = clean_text(value, 80)
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except Exception:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    async def _rank_candidates(
        self,
        query: str,
        ctx: SessionContext,
        *,
        time_intent: TimeIntent | None = None,
    ) -> tuple[list[SearchResult], list[dict[str, str]]]:
        query = clean_text(query, 1000)
        terms = self._terms(query)
        graph_terms = []
        if self.knowledge_graph_enabled and self.knowledge_graph_expansion_limit > 0:
            graph_labels = await self.store.related_knowledge_terms(
                terms,
                scope=ctx.scope,
                session_id=ctx.session_id,
                group_id=ctx.group_id,
                limit=self.knowledge_graph_expansion_limit,
            )
            graph_terms = self._knowledge_graph_anchor_terms(
                graph_labels,
                seed_terms=terms,
                limit=self.knowledge_graph_expansion_limit,
            )
        expanded_terms = self._merge_terms(terms, graph_terms)
        include_pending = not self.policy.hide_pending_review
        ranked_candidates = await self.store.list_candidate_memories(limit=2000, include_pending=include_pending)
        current_window_candidates = await self.store.list_current_window_candidate_memories(
            scope=ctx.scope,
            session_id=ctx.session_id,
            user_id=ctx.user_id,
            group_id=ctx.group_id,
            limit=self.current_window_candidate_limit,
            include_pending=include_pending,
        )
        time_window_candidates: list[MemoryRecord] = []
        if time_intent is not None and time_intent.active:
            time_window_candidates = await self.store.list_time_window_candidate_memories(
                time_intent.start_at,
                time_intent.end_at,
                limit=1600,
                include_pending=include_pending,
            )
        keyword_terms = self._keyword_candidate_terms(query, expanded_terms)
        fts_candidates = await self.store.list_fts_candidate_memories(
            keyword_terms,
            limit=1200,
            include_pending=include_pending,
        )
        use_keyword_fallback = len(fts_candidates) < self.keyword_fallback_min_fts_candidates
        keyword_candidates = (
            await self.store.list_keyword_candidate_memories(
                keyword_terms,
                limit=1200,
                include_pending=include_pending,
            )
            if use_keyword_fallback
            else []
        )
        vector_candidates, vector_scores, embedding_info = await self._embedding_candidate_memories(
            query,
            include_pending=include_pending,
        )
        self._rank_path_info = embedding_info
        self._rank_path_info.update(
            {
                "current_window_candidates": len(current_window_candidates),
                "fts_candidates": len(fts_candidates),
                "keyword_fallback_used": use_keyword_fallback,
                "keyword_candidates": len(keyword_candidates),
            }
        )
        candidates, candidate_sources = self._merge_candidate_memories(
            ranked_candidates,
            current_window_candidates,
            fts_candidates,
            keyword_candidates,
            vector_candidates,
            time_window_candidates,
        )
        acl_state = await self._acl_state() if self.policy.enable_acl_rules else self._empty_acl_state()
        searchable: list[tuple[MemoryRecord, str]] = []
        prefiltered: dict[str, int] = {}
        time_filtered = 0
        for memory in candidates:
            visibility_reason, prefilter_reason = self._search_visibility_reason(memory, ctx, acl_state)
            if visibility_reason:
                if time_intent is not None and time_intent.active and not self._memory_overlaps_time_window(memory, time_intent):
                    time_filtered += 1
                    continue
                searchable.append((memory, visibility_reason))
            else:
                key = clean_text(prefilter_reason or "not_visible", 180)
                prefiltered[key] = prefiltered.get(key, 0) + 1
        profile = self._query_profile(query, expanded_terms)
        term_stats = self._term_document_stats([memory for memory, _reason in searchable], expanded_terms)
        results: list[SearchResult] = []
        blocked: list[dict[str, str]] = []
        if prefiltered:
            blocked.append(
                {
                    "id": "",
                    "reason": self._prefilter_summary_reason(prefiltered),
                    "content": "",
                }
            )
        if time_filtered:
            blocked.append(
                {
                    "id": "",
                    "reason": f"time_window_filtered:{time_filtered};range={time_intent.display_range if time_intent else ''}",
                    "content": "",
                }
            )
        for memory, visibility_reason in searchable:
            vector_score = vector_scores.get(clean_text(memory.id, 120), 0.0)
            score, reason = self._score(
                memory,
                expanded_terms,
                ctx,
                profile,
                term_stats,
                vector_score=vector_score,
            )
            if score <= 0:
                if len(blocked) < 40:
                    blocked.append(
                        {
                            "id": memory.id,
                            "reason": reason,
                            "content": clean_text(memory.content, 120),
                        }
                    )
                continue
            graph_reason = f";graph_terms={','.join(graph_terms[:6])}" if graph_terms else ""
            source_reason = self._candidate_source_reason(memory.id, candidate_sources)
            results.append(
                SearchResult(
                    memory=memory,
                    score=score,
                    reason=f"{visibility_reason};{source_reason};{reason}{graph_reason}",
                )
            )
        results.sort(key=lambda item: item.score, reverse=True)
        return results, blocked

    async def _embedding_candidate_memories(
        self,
        query: str,
        *,
        include_pending: bool,
    ) -> tuple[list[MemoryRecord], dict[str, float], dict[str, Any]]:
        info: dict[str, Any] = {
            "embedding_enabled": bool(self.embedding_enabled),
            "embedding_provider_id": self.embedding_provider_id,
            "embedding_reason": "disabled",
            "embedding_candidates": 0,
            "embedding_hits": 0,
        }
        if not self.embedding_enabled:
            return [], {}, info
        if self.embedding_provider is None or not self._is_embedding_provider(self.embedding_provider):
            info["embedding_reason"] = "no_embedding_provider"
            return [], {}, info
        if not self.embedding_provider_id:
            info["embedding_reason"] = "no_embedding_provider_id"
            return [], {}, info
        query = clean_text(query, 2000)
        if not query:
            info["embedding_reason"] = "empty_query"
            return [], {}, info

        try:
            query_vector = await self._call_embedding_provider(query)
            query_vector = self._normalize_vector(query_vector)
        except Exception as error:
            info["embedding_reason"] = f"embedding_query_error:{clean_text(self._describe_exception(error), 120)}"
            return [], {}, info
        if not query_vector:
            info["embedding_reason"] = "empty_query_vector"
            return [], {}, info

        try:
            rows = await self.store.list_embedding_candidate_rows(
                provider_id=self.embedding_provider_id,
                limit=self.embedding_candidate_limit,
                include_pending=include_pending,
            )
        except Exception as error:
            info["embedding_reason"] = f"embedding_store_error:{clean_text(error, 120)}"
            return [], {}, info

        scored: list[tuple[float, MemoryRecord]] = []
        stale_count = 0
        dimension_mismatch = 0
        for memory, vector, text_hash in rows:
            current_hash = self._embedding_text_hash(memory)
            if current_hash and text_hash and current_hash != text_hash:
                stale_count += 1
                continue
            if len(vector) != len(query_vector):
                dimension_mismatch += 1
                continue
            similarity = self._cosine_similarity(query_vector, vector)
            if similarity >= self.embedding_score_threshold:
                scored.append((similarity, memory))

        scored.sort(key=lambda item: item[0], reverse=True)
        selected = scored[: self.embedding_top_k]
        scores = {clean_text(memory.id, 120): float(score) for score, memory in selected if memory.id}
        info.update(
            {
                "embedding_reason": "applied",
                "embedding_candidates": len(rows),
                "embedding_hits": len(selected),
                "embedding_stale": stale_count,
                "embedding_dim_mismatch": dimension_mismatch,
                "embedding_threshold": self.embedding_score_threshold,
            }
        )
        return [memory for _score, memory in selected], scores, info

    @staticmethod
    def _is_embedding_provider(provider: Any) -> bool:
        return any(
            callable(getattr(provider, name, None))
            for name in ("get_embedding", "get_embeddings", "get_embeddings_batch")
        )

    async def _call_embedding_provider(self, text: str) -> list[float]:
        provider = self.embedding_provider
        text = clean_text(text, 2000)
        if provider is None:
            return []

        async def maybe_wait(value: Any) -> Any:
            if inspect.isawaitable(value):
                if self.embedding_timeout_ms > 0:
                    return await asyncio.wait_for(value, timeout=self.embedding_timeout_ms / 1000.0)
                return await value
            return value

        get_embedding = getattr(provider, "get_embedding", None)
        get_embeddings = getattr(provider, "get_embeddings", None)
        get_embeddings_batch = getattr(provider, "get_embeddings_batch", None)
        started = datetime.now(timezone.utc)
        payload: Any = None
        success = False
        error = ""
        called_provider = False
        try:
            if callable(get_embedding):
                called_provider = True
                payload = await maybe_wait(get_embedding(text))
                success = True
                return self._coerce_vector(payload)

            if callable(get_embeddings):
                called_provider = True
                payload = await maybe_wait(get_embeddings([text]))
                success = True
                return self._first_vector(payload)

            if callable(get_embeddings_batch):
                called_provider = True
                try:
                    payload = await maybe_wait(
                        get_embeddings_batch([text], batch_size=1, tasks_limit=1, max_retries=1)
                    )
                except TypeError:
                    payload = await maybe_wait(get_embeddings_batch([text]))
                success = True
                return self._first_vector(payload)
            return []
        except Exception as exc:
            error = self._describe_exception(exc)
            raise
        finally:
            if called_provider:
                elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
                self._record_usage(
                    task="memory_embedding_query",
                    provider_id=self.embedding_provider_id or "<auto>",
                    prompt=text,
                    completion="",
                    resp=payload,
                    success=success,
                    elapsed_ms=elapsed_ms,
                    error=error,
                )

    @staticmethod
    def _describe_exception(error: BaseException) -> str:
        message = str(error).strip()
        name = type(error).__name__
        return f"{name}: {message}" if message else name

    @staticmethod
    def _usage_prompt_for_rerank(query: str, documents: list[str]) -> str:
        doc_lines = [
            f"{index + 1}. {clean_text(document, 700)}"
            for index, document in enumerate(documents[:80])
            if clean_text(document, 700)
        ]
        return clean_text(
            f"query: {clean_text(query, 1000)}\n\ndocuments:\n" + "\n".join(doc_lines),
            12000,
        )

    def _record_usage(
        self,
        *,
        task: str,
        provider_id: str,
        prompt: str,
        completion: str,
        resp: Any,
        success: bool,
        elapsed_ms: int,
        error: str = "",
    ) -> None:
        recorder = self.usage_recorder
        if not callable(recorder):
            return
        try:
            recorder(
                task=task,
                provider_id=provider_id,
                prompt=prompt,
                completion=completion,
                resp=resp,
                success=success,
                elapsed_ms=elapsed_ms,
                error=error,
            )
        except Exception:
            pass

    @staticmethod
    def _coerce_vector(value: Any) -> list[float]:
        if value is None:
            return []
        if isinstance(value, dict):
            for key in ("embedding", "vector"):
                if key in value:
                    vector = RetrievalEngine._coerce_vector(value.get(key))
                    if vector:
                        return vector
            for key in ("data", "embeddings", "vectors"):
                if key in value:
                    vector = RetrievalEngine._coerce_vector(value.get(key))
                    if vector:
                        return vector
            return []
        for attr in ("embedding", "vector", "data", "embeddings", "vectors"):
            if hasattr(value, attr):
                vector = RetrievalEngine._coerce_vector(getattr(value, attr, None))
                if vector:
                    return vector
        if not isinstance(value, (list, tuple)):
            return []
        vector: list[float] = []
        for item in value:
            try:
                vector.append(float(item))
            except Exception:
                return RetrievalEngine._coerce_vector(value[0]) if value else []
        return vector

    def _first_vector(self, payload: Any) -> list[float]:
        return self._coerce_vector(payload)

    @staticmethod
    def _normalize_vector(vector: Any) -> list[float]:
        values = RetrievalEngine._coerce_vector(vector)
        if not values:
            return []
        norm = math.sqrt(sum(value * value for value in values))
        if norm <= 0:
            return []
        return [value / norm for value in values]

    @staticmethod
    def _cosine_similarity(query_vector: list[float], memory_vector: list[float]) -> float:
        if not query_vector or not memory_vector or len(query_vector) != len(memory_vector):
            return 0.0
        normalized_memory = RetrievalEngine._normalize_vector(memory_vector)
        if not normalized_memory:
            return 0.0
        score = sum(a * b for a, b in zip(query_vector, normalized_memory))
        return max(-1.0, min(1.0, float(score)))

    def _embedding_document_text(self, memory: MemoryRecord) -> str:
        metadata = memory.metadata if isinstance(memory.metadata, dict) else {}
        parts = [
            f"类型: {memory.memory_type}",
            f"范围: {memory.scope}/{memory.visibility}",
            f"标签: {' '.join(memory.tags or [])}",
            f"内容: {memory.content}",
        ]
        for key in ("canonical_summary", "persona_summary", "key_facts", "topics"):
            value = metadata.get(key)
            if isinstance(value, list):
                value = " ".join(str(item) for item in value if item)
            value_text = clean_text(value, 1000)
            if value_text:
                parts.append(f"{key}: {value_text}")
        if memory.evidence:
            parts.append(f"证据: {memory.evidence}")
        return clean_text("\n".join(parts), self.embedding_max_text_chars)

    def _embedding_text_hash(self, memory: MemoryRecord) -> str:
        text = self._embedding_document_text(memory)
        if not text:
            return ""
        return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()

    def _keyword_candidate_terms(self, query: str, terms: list[str]) -> list[str]:
        keyword_terms = list(terms)
        compact = re.sub(r"\s+", "", clean_text(query, 1000)).lower()
        for phrase in self._concrete_exact_phrases(compact):
            if phrase not in keyword_terms:
                keyword_terms.append(phrase)
        return keyword_terms[:24]

    def _concrete_exact_phrases(self, compact_query: str) -> list[str]:
        phrases: list[str] = []
        for phrase in re.findall(r"[\u4e00-\u9fff]{3,}", compact_query):
            trimmed = self._trim_query_scaffold_phrase(phrase)
            if len(trimmed) >= 3 and trimmed not in phrases:
                phrases.append(trimmed)
            if len(phrases) >= 8:
                break
        return phrases

    def _knowledge_graph_anchor_terms(
        self,
        labels: list[str],
        *,
        seed_terms: list[str],
        limit: int,
    ) -> list[str]:
        seed = {clean_text(term, 80).lower() for term in seed_terms if clean_text(term, 80)}
        candidates: dict[str, float] = {}
        first_seen: dict[str, int] = {}
        order = 0

        def add(raw: str, bonus: float = 0.0) -> None:
            nonlocal order
            term = self._trim_graph_anchor(raw)
            if self._is_graph_anchor_noise(term):
                return
            score = self._graph_anchor_quality(term) + bonus
            if term in seed:
                score += 0.8
            if score <= 0.65:
                return
            if term not in first_seen:
                first_seen[term] = order
                order += 1
            candidates[term] = max(candidates.get(term, 0.0), score)

        for label in labels or []:
            text = clean_text(label, 240).lower()
            if not text:
                continue
            for quoted in re.findall(r"[\"'“”‘’「」『』]([^\"'“”‘’「」『』]{2,16})[\"'“”‘’「」『』]", text):
                add(quoted, 0.8)
            for token in re.findall(r"[a-z0-9_]{3,}", text):
                add(token, 0.2)
            compact = re.sub(r"[\s,，。.!！~～…、:：;；\"'“”‘’()（）\[\]【】<>《》]+", "", text)
            for block in re.findall(r"[\u4e00-\u9fff]+", compact):
                for segment in self._graph_anchor_segments(block):
                    if 2 <= len(segment) <= 8:
                        add(segment, 0.45 if len(segment) >= 3 else 0.0)
                    for size in range(min(6, len(segment)), 1, -1):
                        for index in range(0, len(segment) - size + 1):
                            add(segment[index : index + size], 0.15 if size >= 3 else 0.0)

        if not candidates:
            return []
        ordered = sorted(
            candidates.items(),
            key=lambda item: (-item[1], first_seen.get(item[0], 9999), -len(item[0]), item[0]),
        )
        selected: list[str] = []
        for term, _score in ordered:
            if self._graph_anchor_redundant(term, selected):
                continue
            selected.append(term)
            if len(selected) >= max(1, int(limit or 1)):
                break
        return selected

    @staticmethod
    def _graph_anchor_segments(block: str) -> list[str]:
        pieces = re.split(
            r"(?:为什么|怎么|什么|哪个|哪次|是否|是不是|有没有|称呼|叫做|起因|原因|因为|所以|"
            r"不爱吃|爱吃|不吃|好吃|难吃|吃|喝|提到|提起|念叨|关于|相关|属于|"
            r"当前|记忆|总结|阶段|会话|用户|消息|回复|来源|可见性|现实层|置信|绰号|"
            r"[我你他她它咱咱们我们你们他们她们它们的是了嘛吗呢吧呀哦啊嗯哈和与或在有把被给让对向从到地为])",
            block,
        )
        return [piece for piece in pieces if piece]

    @staticmethod
    def _trim_graph_anchor(term: str) -> str:
        text = clean_text(term, 80).lower()
        if not text:
            return ""
        leading_units = (
            "为什么",
            "怎么",
            "什么",
            "称呼",
            "叫做",
            "起因",
            "原因",
            "因为",
            "所以",
            "关于",
            "相关",
            "不爱吃",
            "爱吃",
            "不吃",
            "好吃",
            "难吃",
            "吃",
            "喝",
            "提到",
            "提起",
            "念叨",
            "当前",
            "记忆",
            "总结",
            "阶段",
            "会话",
            "用户",
            "消息",
            "回复",
            "绰号",
        )
        trailing_units = leading_units
        changed = True
        while changed and len(text) > 1:
            changed = False
            for unit in leading_units:
                if text.startswith(unit) and len(text) > len(unit) + 1:
                    text = text[len(unit) :]
                    changed = True
                    break
            if changed:
                continue
            for unit in trailing_units:
                if text.endswith(unit) and len(text) > len(unit) + 1:
                    text = text[: -len(unit)]
                    changed = True
                    break
        edge_chars = "的是了嘛吗呢吧呀哦啊嗯哈我你他她它这那才又还再就和与或但把被给让在对向从到为问说叫想地"
        return text.strip(edge_chars)

    @staticmethod
    def _graph_anchor_quality(term: str) -> float:
        if not term:
            return 0.0
        score = 1.0 + min(2.0, len(term) * 0.18)
        if re.fullmatch(r"[a-z_]+", term) and len(term) <= 2:
            score -= 1.0
        if len(term) >= 4:
            score += 0.65
        if len(term) >= 7:
            score -= 0.55
        edge_chars = "的是了嘛吗呢吧呀哦啊嗯哈我你他她它这那才又还再就和与或但把被给让在对向从到为问说叫想地"
        if term[0] in edge_chars:
            score -= 1.0
        if term[-1] in edge_chars:
            score -= 0.7
        if re.search(r"为什么|怎么|什么|称呼|起因|原因|因为|所以|当前|记忆|总结|会话|用户|消息|回复", term):
            score -= 1.2
        if len(term) >= 3 and not re.search(r"[的是了嘛吗呢吧呀哦啊嗯哈我你他她它这那才又还再就和与或但把被给让在对向从到为问说叫想地]", term):
            score += 0.35
        if len(set(term)) <= 1:
            score -= 1.0
        return score

    @staticmethod
    def _is_graph_anchor_noise(term: str) -> bool:
        if not term or len(term) < 2:
            return True
        if re.fullmatch(r"[的是了嘛吗呢吧呀哦啊嗯哈]+", term):
            return True
        if re.fullmatch(
            r"(?:为什么|怎么|什么|称呼|叫做|起因|原因|因为|所以|关于|相关|当前|记忆|总结|阶段|会话|用户|消息|回复|"
            r"来源|可见性|现实层|置信|绰号|id|bot)+",
            term,
        ):
            return True
        return False

    def _graph_anchor_redundant(self, term: str, selected: list[str]) -> bool:
        quality = self._graph_anchor_quality(term)
        for kept in selected:
            if term == kept:
                return True
            kept_quality = self._graph_anchor_quality(kept)
            if term in kept:
                if len(term) == 2 and quality >= kept_quality - 0.25:
                    continue
                return True
            if kept in term and quality <= kept_quality + 0.35:
                return True
        return False

    @staticmethod
    def _trim_query_scaffold_phrase(phrase: str) -> str:
        text = clean_text(phrase, 120)
        prefixes = (
            "就是当时你一直提什么我才说你是",
            "就是当时你一直提什么我才说我是",
            "当时你一直提什么我才说你是",
            "当时你一直提什么我才说我是",
            "就是当时你一直提什么才说你是",
            "就是当时你一直提什么才说我是",
            "当时你一直提什么才说你是",
            "当时你一直提什么才说我是",
            "就是当时你一直提什么",
            "当时你一直提什么",
            "我才说你是",
            "我才说我是",
            "才说你是",
            "才说我是",
            "你再想想为什么说你是",
            "你再想想为什么说我是",
            "再想想为什么说你是",
            "再想想为什么说我是",
            "你想想为什么说你是",
            "你想想为什么说我是",
            "想想为什么说你是",
            "想想为什么说我是",
            "你再想一下为什么说你是",
            "你再想一下为什么说我是",
            "再想一下为什么说你是",
            "再想一下为什么说我是",
            "还记得我为什么说你是",
            "还记得我为什么说我是",
            "记得我为什么说你是",
            "记得我为什么说我是",
            "为什么说你是",
            "为什么说我是",
            "为什么叫你",
            "为什么叫我",
            "你再想想",
            "再想想",
            "你想想",
            "想想",
            "你再想一下",
            "再想一下",
            "你想一下",
            "想一下",
            "你想一想",
            "想一想",
            "你还记得",
            "我还记得",
            "还记得",
            "记得",
            "明明是",
            "就是",
            "原来是",
            "是",
        )
        suffixes = ("是什么", "是啥", "了吗", "吗", "呢", "啊", "呀")
        changed = True
        while changed and text:
            changed = False
            for prefix in prefixes:
                if text == prefix:
                    text = ""
                    changed = True
                    break
                if text.startswith(prefix) and len(text) > len(prefix):
                    text = text[len(prefix) :]
                    changed = True
                    break
            if changed:
                continue
            for suffix in suffixes:
                if text.endswith(suffix) and len(text) > len(suffix):
                    text = text[: -len(suffix)]
                    changed = True
                    break
        return text

    @staticmethod
    def _merge_candidate_memories(
        ranked_candidates: list[MemoryRecord],
        current_window_candidates: list[MemoryRecord],
        fts_candidates: list[MemoryRecord],
        keyword_candidates: list[MemoryRecord],
        vector_candidates: list[MemoryRecord] | None = None,
        time_window_candidates: list[MemoryRecord] | None = None,
    ) -> tuple[list[MemoryRecord], dict[str, set[str]]]:
        merged: list[MemoryRecord] = []
        sources: dict[str, set[str]] = {}
        seen_ids: set[str] = set()

        def add(memory: MemoryRecord, source: str) -> None:
            memory_id = clean_text(memory.id, 120)
            if memory_id:
                sources.setdefault(memory_id, set()).add(source)
            if not memory_id or memory_id not in seen_ids:
                merged.append(memory)
                if memory_id:
                    seen_ids.add(memory_id)

        for memory in fts_candidates:
            add(memory, "fts")
        for memory in current_window_candidates:
            add(memory, "current_window")
        for memory in keyword_candidates:
            add(memory, "keyword")
        for memory in time_window_candidates or []:
            add(memory, "time_window")
        for memory in vector_candidates or []:
            add(memory, "vector")
        for memory in ranked_candidates:
            add(memory, "priority")
        return merged, sources

    @staticmethod
    def _candidate_source_reason(memory_id: str, sources: dict[str, set[str]]) -> str:
        item_sources = sorted(sources.get(clean_text(memory_id, 120), set()))
        if not item_sources:
            item_sources = ["unknown"]
        return "candidate_route=" + "+".join(item_sources)

    @staticmethod
    def _merge_terms(primary: list[str], extra: list[str], *, limit: int = 40) -> list[str]:
        merged: list[str] = []
        for term in [*primary, *extra]:
            text = clean_text(term, 80).lower()
            if text and text not in merged:
                merged.append(text)
            if len(merged) >= limit:
                break
        return merged

    def _search_visibility_reason(
        self,
        memory: MemoryRecord,
        ctx: SessionContext,
        acl_state: dict[str, object],
    ) -> tuple[str, str]:
        visible, visibility_reason = self.policy.is_visible(memory, ctx)
        acl_deny_reason = self._acl_deny_reason(memory, ctx, acl_state)
        if visible:
            if acl_deny_reason:
                return "", acl_deny_reason
            return visibility_reason, ""
        if acl_deny_reason:
            return "", acl_deny_reason
        acl_reason = self._acl_visibility_reason(memory, ctx, visibility_reason, acl_state)
        if acl_reason:
            return acl_reason, ""
        privacy_reason = self._acl_privacy_guard_reason(memory, ctx, visibility_reason, acl_state)
        return "", privacy_reason or visibility_reason

    def _prefilter_summary_reason(self, prefiltered: dict[str, int]) -> str:
        total = sum(max(0, int(count or 0)) for count in prefiltered.values())
        top = sorted(prefiltered.items(), key=lambda item: (-item[1], item[0]))[:6]
        detail = ",".join(f"{reason}:{count}" for reason, count in top)
        return f"prefiltered_out_of_search_range:{total};{detail}"

    def _slot_for_memory(self, memory: MemoryRecord, ctx: SessionContext) -> str:
        tags = {str(tag).lower() for tag in (memory.tags or [])}
        memory_type = (memory.memory_type or "").lower()
        reality = (memory.reality_level or "").lower()
        metadata = memory.metadata if isinstance(memory.metadata, dict) else {}
        if self._memory_is_open_loop(memory, metadata):
            return "open_loop"
        if (
            memory.visibility == "bot_self"
            or reality in {"bot_action", "persona_life", "fictional_content"}
            or memory_type
            in {
                "self_action",
                "persona_life",
                "proactive_message",
                "search_action",
                "creative_work",
                "image_action",
                "qzone_action",
                "reading_memory",
                "schedule_fragment",
                "companion_note",
            }
        ):
            return "self_timeline"
        if (
            memory_type
            in {
                "user_profile",
                "user_preference",
                "relationship_claim",
                "explicit_memory",
                "manual_memory",
            }
            or "stable_fact" in tags
            or "relationship_claim" in tags
        ):
            return "user_profile"
        if memory_type == "conversation_summary" or "summary" in tags:
            return "conversation_summary"
        if (
            (ctx.scope == "private" and (memory.visibility == "private_pair" or memory.scope == "private"))
            or (ctx.scope == "group" and (memory.visibility == "group_public" or memory.scope == "group"))
        ):
            return "current_window"
        return "stable_memory"

    @staticmethod
    def _memory_is_open_loop(memory: MemoryRecord, metadata: dict[str, Any]) -> bool:
        def weight(key: str) -> float:
            try:
                return max(0.0, min(1.0, float(metadata.get(key) or 0.0)))
            except Exception:
                return 0.0

        tags = {clean_text(tag, 80).lower() for tag in (memory.tags or [])}
        memory_type = clean_text(memory.memory_type, 80).lower()
        if (
            memory_type == "conversation_summary"
            and (memory.scope == "group" or memory.visibility == "group_public")
        ):
            return False
        phase = clean_text(metadata.get("relationship_phase"), 80).lower()
        if max(weight("open_loop_weight"), weight("promise_weight"), weight("emotional_debt_weight")) >= 0.35:
            return True
        if max(weight("scar_weight"), weight("emotional_weight")) >= 0.58 and phase in {"conflict", "repair", "comfort", "sensitive"}:
            return True
        if memory_type in {"open_loop", "promise", "todo_memory"}:
            return True
        return bool(tags & {"open_loop", "promise", "todo", "unfinished", "emotional_debt"})

    async def _acl_state(self) -> dict[str, object]:
        rules = await self.store.list_acl_rules(enabled_only=True)
        policies = await self.store.list_acl_policies()
        allow_pairs: set[tuple[str, str, str, str]] = set()
        deny_pairs: set[tuple[str, str, str, str]] = set()
        for rule in rules:
            owner_scope = clean_text(rule.get("owner_scope"), 40)
            owner_id = clean_text(rule.get("owner_id"), 160)
            reader_scope = clean_text(rule.get("reader_scope"), 40)
            reader_id = clean_text(rule.get("reader_id"), 160)
            effect = "deny" if clean_text(rule.get("effect"), 20).lower() == "deny" else "allow"
            if not (owner_scope and owner_id and reader_scope and reader_id):
                continue
            pair = (owner_scope, owner_id, reader_scope, reader_id)
            if effect == "deny":
                deny_pairs.add(pair)
            else:
                allow_pairs.add(pair)
        policy_map: dict[tuple[str, str], dict[str, str]] = {}
        for policy in policies:
            scope = clean_text(policy.get("window_scope"), 40)
            window_id = clean_text(policy.get("window_id"), 160)
            if not scope or not window_id:
                continue
            policy_map[(scope, window_id)] = {
                "read_mode": self._normalize_acl_mode(policy.get("read_mode")),
                "share_mode": self._normalize_acl_mode(policy.get("share_mode")),
            }
        return {"allow": allow_pairs, "deny": deny_pairs, "policies": policy_map}

    def _empty_acl_state(self) -> dict[str, object]:
        return {"allow": set(), "deny": set(), "policies": {}}

    def _acl_deny_reason(
        self,
        memory: MemoryRecord,
        ctx: SessionContext,
        acl_state: dict[str, object],
    ) -> str:
        owner = self._memory_owner(memory)
        reader = self._reader_window(ctx)
        if not owner or not reader or owner == reader:
            return ""
        deny_pairs = acl_state.get("deny", set())
        pair = (owner[0], owner[1], reader[0], reader[1])
        if pair in deny_pairs:
            return f"acl_denied:{owner[0]}:{owner[1]}->{reader[0]}:{reader[1]}"
        return ""

    def _acl_visibility_reason(
        self,
        memory: MemoryRecord,
        ctx: SessionContext,
        default_reason: str,
        acl_state: dict[str, object],
    ) -> str:
        if default_reason not in {"other_group_public", "other_private_pair", "private_pair_not_current_private"}:
            return ""
        owner = self._memory_owner(memory)
        reader = self._reader_window(ctx)
        if not owner or not reader or owner == reader:
            return ""
        pair = (owner[0], owner[1], reader[0], reader[1])
        deny_pairs = acl_state.get("deny", set())
        if pair in deny_pairs:
            return ""
        allow_pairs = acl_state.get("allow", set())
        if pair in allow_pairs:
            return f"acl_allowed:{owner[0]}:{owner[1]}->{reader[0]}:{reader[1]}"
        policies = acl_state.get("policies", {})
        owner_policy = self._acl_policy_for(policies, owner)
        reader_policy = self._acl_policy_for(policies, reader)
        if owner_policy.get("share_mode") == "blacklist" and reader_policy.get("read_mode") == "blacklist":
            if self._requires_explicit_allow(owner, reader):
                return ""
            return f"acl_blacklist_default:{owner[0]}:{owner[1]}->{reader[0]}:{reader[1]}"
        return ""

    def _acl_privacy_guard_reason(
        self,
        memory: MemoryRecord,
        ctx: SessionContext,
        default_reason: str,
        acl_state: dict[str, object],
    ) -> str:
        if default_reason not in {"other_group_public", "other_private_pair", "private_pair_not_current_private"}:
            return ""
        owner = self._memory_owner(memory)
        reader = self._reader_window(ctx)
        if not owner or not reader or owner == reader or not self._requires_explicit_allow(owner, reader):
            return ""
        pair = (owner[0], owner[1], reader[0], reader[1])
        if pair in acl_state.get("allow", set()) or pair in acl_state.get("deny", set()):
            return ""
        policies = acl_state.get("policies", {})
        owner_policy = self._acl_policy_for(policies, owner)
        reader_policy = self._acl_policy_for(policies, reader)
        if owner_policy.get("share_mode") == "blacklist" and reader_policy.get("read_mode") == "blacklist":
            return f"acl_privacy_guard_requires_allow:{owner[0]}:{owner[1]}->{reader[0]}:{reader[1]}"
        return ""

    def _requires_explicit_allow(self, owner: tuple[str, str], reader: tuple[str, str]) -> bool:
        return owner[0] == "private" and reader[0] == "group"

    def _acl_policy_for(self, policies: object, window: tuple[str, str]) -> dict[str, str]:
        if isinstance(policies, dict):
            policy = policies.get(window)
            if isinstance(policy, dict):
                return {
                    "read_mode": self._normalize_acl_mode(policy.get("read_mode")),
                    "share_mode": self._normalize_acl_mode(policy.get("share_mode")),
                }
        default_mode = "blacklist" if window[0] == "group" else "whitelist"
        return {"read_mode": default_mode, "share_mode": default_mode}

    def _normalize_acl_mode(self, mode: object) -> str:
        return "blacklist" if clean_text(mode, 20).lower() == "blacklist" else "whitelist"

    def _memory_owner(self, memory: MemoryRecord) -> tuple[str, str] | None:
        if memory.scope == "group" or memory.visibility == "group_public":
            owner_id = memory.group_id
            if not owner_id and memory.object.kind == "group":
                owner_id = memory.object.id
            if not owner_id and memory.subject.kind == "group":
                owner_id = memory.subject.id
            if not owner_id:
                owner_id = session_target_id(memory.session_id, "group") or memory.session_id
            return ("group", clean_text(owner_id, 160)) if owner_id else None
        if memory.scope == "private" or memory.visibility == "private_pair":
            owner_id = ""
            for entity in (memory.subject, memory.object):
                if entity.kind == "user" and entity.id and entity.id != "self":
                    owner_id = entity.id
                    break
            if not owner_id:
                owner_id = session_target_id(memory.session_id, "private") or memory.session_id
            return ("private", clean_text(owner_id, 160)) if owner_id else None
        return None

    def _reader_window(self, ctx: SessionContext) -> tuple[str, str] | None:
        if ctx.scope == "group":
            reader_id = ctx.group_id or ctx.session_id
            return ("group", clean_text(reader_id, 160)) if reader_id else None
        if ctx.scope == "private":
            reader_id = ctx.user_id or ctx.session_id
            return ("private", clean_text(reader_id, 160)) if reader_id else None
        return None

    def _terms(self, query: str) -> list[str]:
        words = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}", query)
        terms: list[str] = []
        for word in words:
            contextual_word = self._looks_like_contextual_recall_query(word)
            trimmed_word = self._trim_query_scaffold_phrase(word)
            term_word = trimmed_word if (contextual_word or trimmed_word != clean_text(word, 120)) else word
            if not term_word:
                continue
            term_word = term_word or word
            if re.fullmatch(r"[\u4e00-\u9fff]{4,}", term_word):
                terms.extend(term_word[i : i + 2] for i in range(0, len(term_word) - 1))
                if not contextual_word or len(term_word) <= 4:
                    terms.append(term_word)
                continue
            terms.append(term_word)
            terms.extend(self._current_state_anchor_terms(term_word))
        normalized_terms = [
            term
            for term in dict.fromkeys(term.lower() for term in terms if len(term.strip()) >= 2)
            if not self._is_query_scaffold_term(term)
        ]
        normalized_terms.extend(
            term for term in self._preference_equivalent_terms(query) if term not in normalized_terms
        )
        return normalized_terms[:24]

    @staticmethod
    def _preference_equivalent_terms(text: str) -> list[str]:
        compact = re.sub(r"\s+", "", clean_text(text, 1000)).lower()
        if not compact:
            return []
        families = (
            ("无糖", "不加糖", "不要加糖", "不放糖"),
            ("少糖", "低糖", "微糖"),
            ("无冰", "去冰", "不加冰", "不要冰"),
            ("不要香菜", "不吃香菜", "去香菜"),
        )
        expanded: list[str] = []
        for family in families:
            if any(term in compact for term in family):
                expanded.extend(term for term in family if term not in expanded)
        return expanded

    def _query_profile(self, query: str, terms: list[str]) -> dict[str, object]:
        compact = re.sub(r"\s+", "", query).lower()
        contextual_recall = self._looks_like_contextual_recall_query(compact)
        temporal_aggregate = self._looks_like_temporal_aggregate_query(compact)
        current_state = self._looks_like_current_state_query(compact)
        cjk_phrases = re.findall(r"[\u4e00-\u9fff]{4,}", compact)
        exact_phrases = [] if (contextual_recall or temporal_aggregate or current_state) else [phrase for phrase in cjk_phrases if len(phrase) >= 4]
        # Long concrete Chinese phrases should not match by relation/recency alone.
        # Require at least two overlapping fragments unless the whole phrase appears.
        min_hits = 1
        if current_state:
            min_hits = 1
        elif temporal_aggregate:
            min_hits = min(2, max(1, len(terms)))
        elif contextual_recall:
            min_hits = 1 if len(terms) <= 3 else 2
        elif exact_phrases:
            min_hits = min(3, max(2, len(exact_phrases[0]) // 3))
        elif len(terms) >= 4:
            min_hits = 2
        return {
            "exact_phrases": exact_phrases,
            "min_hits": min_hits,
            "contextual_recall": contextual_recall,
            "temporal_aggregate": temporal_aggregate,
            "open_loop_followup": self._looks_like_open_loop_followup(compact),
        }

    @staticmethod
    def _looks_like_current_state_query(text: str) -> bool:
        compact = re.sub(r"\s+", "", clean_text(text, 1000)).lower()
        if not compact:
            return False
        if any(marker in compact for marker in ("记得", "记忆", "之前", "以前", "上次", "那次")):
            return False
        markers = (
            "吃饭",
            "吃了",
            "吃晚饭",
            "晚饭",
            "午饭",
            "早餐",
            "夜宵",
            "喝了",
            "在干嘛",
            "在做什么",
            "忙什么",
            "累不累",
            "困不困",
            "饿不饿",
            "心情",
            "状态",
            "穿什么",
            "穿了什么",
            "衣服颜色",
            "什么颜色",
            "什么色",
        )
        question_markers = ("吗", "呢", "了没", "了吗", "没有", "什么", "啥", "怎么样", "如何")
        return any(marker in compact for marker in markers) and any(marker in compact for marker in question_markers)

    @staticmethod
    def _current_state_anchor_terms(text: str) -> list[str]:
        compact = re.sub(r"\s+", "", clean_text(text, 1000)).lower()
        terms: list[str] = []
        for meal in ("早餐", "早饭", "午饭", "午餐", "晚饭", "晚餐", "夜宵"):
            if meal in compact:
                terms.append(meal)
        if not terms and any(marker in compact for marker in ("吃", "饭", "喝")):
            terms.extend(["吃饭", "吃过", "吃了", "用餐", "喝了"])
        if any(marker in compact for marker in ("干嘛", "做什么", "忙什么")):
            terms.extend(["做", "忙", "上课", "学习", "工作", "玩"])
        if any(marker in compact for marker in ("累", "困", "饿", "心情", "状态")):
            terms.extend(["累", "困", "饿", "心情", "状态", "感觉"])
        if any(marker in compact for marker in ("穿", "衣服", "穿搭", "裙", "外套", "裤", "颜色", "什么色")):
            terms.extend(["穿", "衣服", "穿搭", "今日穿搭", "每日穿搭", "衣服颜色", "颜色", "裙", "外套", "裤"])
        return list(dict.fromkeys(term for term in terms if len(term) >= 2))

    @staticmethod
    def _looks_like_temporal_aggregate_query(text: str) -> bool:
        compact = re.sub(r"\s+", "", clean_text(text, 1000)).lower()
        if not compact:
            return False
        temporal_markers = (
            "最近一周",
            "近一周",
            "这一周",
            "这周",
            "本周",
            "最近几天",
            "这几天",
            "近几天",
            "最近7天",
            "最近七天",
            "过去一周",
            "过去7天",
            "过去七天",
        )
        return any(marker in compact for marker in temporal_markers) or bool(re.search(r"(最近|过去|近)\d{1,2}天", compact))

    @staticmethod
    def _looks_like_contextual_recall_query(text: str) -> bool:
        compact = re.sub(r"\s+", "", clean_text(text, 1000)).lower()
        if not compact:
            return False
        direct_recall_patterns = (
            "为什么说你是",
            "为什么说我是",
            "为什么叫你",
            "为什么叫我",
            "才说你是",
            "才说我是",
            "才叫你",
            "才叫我",
        )
        if any(pattern in compact for pattern in direct_recall_patterns):
            return True
        if any(marker in compact for marker in ("当时", "之前", "以前", "上次", "那次")) and any(
            marker in compact for marker in ("说你是", "说我是", "叫你", "叫我", "一直提什么")
        ):
            return True
        recall_markers = (
            "记得",
            "还记得",
            "想起来",
            "想起",
            "想想",
            "再想想",
            "想一下",
            "想一想",
            "之前",
            "以前",
            "上次",
            "当时",
            "那次",
        )
        question_markers = (
            "为什么",
            "原因",
            "怎么",
            "哪",
            "啥",
            "什么",
            "说你",
            "说我",
            "叫你",
            "叫我",
            "吗",
            "呢",
        )
        return any(marker in compact for marker in recall_markers) and any(
            marker in compact for marker in question_markers
        )

    @staticmethod
    def _looks_like_open_loop_followup(text: str) -> bool:
        compact = re.sub(r"\s+", "", clean_text(text, 1000)).lower()
        if not compact:
            return False
        markers = (
            "继续",
            "接着",
            "还有呢",
            "还有吗",
            "还有的吧",
            "还有什么",
            "后来呢",
            "然后呢",
            "刚才那个",
            "上次那个",
            "没说完",
            "还没说完",
        )
        return any(marker in compact for marker in markers) and len(compact) <= 18

    @staticmethod
    def _is_query_scaffold_term(term: str) -> bool:
        scaffold_terms = {
            "你再",
            "再想",
            "想想",
            "想为",
            "想一",
            "一下",
            "你想",
            "你还",
            "就是",
            "是当",
            "时你",
            "你一",
            "一直",
            "直提",
            "提什",
            "我才",
            "才说",
            "记得",
            "还记",
            "得我",
            "得你",
            "得糖",
            "我为",
            "你为",
            "为什",
            "什么",
            "么说",
            "说你",
            "说我",
            "叫你",
            "叫我",
            "你是",
            "我是",
            "是异",
            "的吗",
            "端吗",
            "骨吗",
            "原因",
            "之前",
            "以前",
            "上次",
            "当时",
            "那次",
            "想起",
            "起来",
            "最近",
            "近一",
            "一周",
            "周的",
            "过去",
            "几天",
            "这几",
            "本周",
            "这周",
            "的胖",
            "次颜",
        }
        return clean_text(term, 80).lower() in scaffold_terms

    def _term_document_stats(self, memories: list[MemoryRecord], terms: list[str]) -> dict[str, float]:
        if not terms:
            return {}
        document_count = max(1, len(memories))
        dfs = dict.fromkeys(terms, 0)
        for memory in memories:
            haystack = self._haystack(memory)
            for term in terms:
                if term in haystack:
                    dfs[term] += 1
        return {
            term: math.log(1 + (document_count - df + 0.5) / (df + 0.5))
            for term, df in dfs.items()
            if df > 0
        }

    def _haystack(self, memory: MemoryRecord) -> str:
        metadata = memory.metadata if isinstance(memory.metadata, dict) else {}
        metadata_text_parts = [
            metadata.get("canonical_summary", ""),
            metadata.get("persona_summary", ""),
            " ".join(str(item) for item in metadata.get("key_facts", []) if item)
            if isinstance(metadata.get("key_facts"), list) else "",
            " ".join(str(item) for item in metadata.get("topics", []) if item)
            if isinstance(metadata.get("topics"), list) else "",
            " ".join(str(item) for item in metadata.get("participants", []) if item)
            if isinstance(metadata.get("participants"), list) else "",
        ]
        return " ".join(
            [
                memory.content,
                memory.evidence,
                " ".join(memory.tags),
                " ".join(clean_text(part, 1000) for part in metadata_text_parts if clean_text(part, 1000)),
                memory.subject.name,
                memory.subject.id,
                memory.object.name,
                memory.object.id,
                memory.group_id,
            ]
        ).lower()

    def _score(
        self,
        memory: MemoryRecord,
        terms: list[str],
        ctx: SessionContext,
        profile: dict[str, object],
        term_stats: dict[str, float],
        *,
        vector_score: float = 0.0,
    ) -> tuple[float, str]:
        haystack = self._haystack(memory)
        compact_haystack = re.sub(r"\s+", "", haystack)
        term_hits = sum(1 for term in terms if term and term in haystack)
        exact_phrases = [str(item) for item in profile.get("exact_phrases", []) if str(item)]
        exact_hit = any(phrase in compact_haystack for phrase in exact_phrases)
        min_hits = int(profile.get("min_hits", 1) or 1)
        vector_relevant = vector_score >= self.embedding_score_threshold if self.embedding_enabled else False
        if terms and not exact_hit and term_hits < min_hits and not vector_relevant:
            return 0.0, f"keyword_hit_too_weak hits={term_hits}/{min_hits}"
        graph_guard_reason = self._livingmemory_graph_relevance_guard(memory, term_hits, exact_hit, min_hits)
        if graph_guard_reason and vector_score < min(0.98, self.embedding_score_threshold + 0.12):
            return 0.0, graph_guard_reason
        bm25 = 0.0
        if terms:
            for term in terms:
                if not term:
                    continue
                freq = haystack.count(term)
                if freq <= 0:
                    continue
                idf = term_stats.get(term, 0.0)
                bm25 += idf * ((freq * 2.2) / (freq + 1.2))
            lexical = (0.42 if exact_hit else 0.24) + min(0.72, bm25 * 0.18)
        else:
            lexical = 0.0

        scope_bonus = 0.0
        if memory.session_id and memory.session_id == ctx.session_id:
            scope_bonus += 0.25
        if ctx.user_id and ctx.user_id in {memory.subject.id, memory.object.id}:
            scope_bonus += 0.15
        if ctx.group_id and ctx.group_id == memory.group_id:
            scope_bonus += 0.15
        if memory.visibility == "bot_self":
            scope_bonus += 0.08

        age_bonus = self._recency_bonus(memory.occurred_at or memory.created_at)
        persona_bonus = self._persona_relevance_bonus(memory, profile)
        dynamics_bonus = self._persona_dynamics_bonus(memory, profile)
        vector_bonus = 0.0
        if vector_relevant:
            if self.embedding_score_threshold < 1.0:
                normalized_vector = (vector_score - self.embedding_score_threshold) / (1.0 - self.embedding_score_threshold)
            else:
                normalized_vector = vector_score
            vector_bonus = self.embedding_weight * max(0.0, min(1.0, normalized_vector))
        score = lexical + scope_bonus + memory.importance * 0.55 + memory.confidence * 0.25 + age_bonus + vector_bonus + persona_bonus + dynamics_bonus
        if not terms:
            score = scope_bonus + memory.importance * 0.8 + age_bonus + vector_bonus + persona_bonus + dynamics_bonus
        return score, (
            f"hits={term_hits};exact={int(exact_hit)};bm25={bm25:.2f};"
            f"vector={vector_score:.3f};importance={memory.importance:.2f};"
            f"persona={persona_bonus:.2f};dynamics={dynamics_bonus:.2f};recency={age_bonus:.2f}"
        )

    @staticmethod
    def _persona_relevance_bonus(memory: MemoryRecord, profile: dict[str, object]) -> float:
        metadata = memory.metadata if isinstance(memory.metadata, dict) else {}

        def weight(key: str) -> float:
            try:
                return max(0.0, min(1.0, float(metadata.get(key) or 0.0)))
            except Exception:
                return 0.0

        persona = weight("persona_importance")
        if persona <= 0:
            return 0.0
        bonus = min(0.10, persona * 0.08)
        contextual = bool(profile.get("contextual_recall"))
        temporal = bool(profile.get("temporal_aggregate"))
        if contextual:
            bonus += min(
                0.10,
                max(weight("open_loop_weight"), weight("promise_weight"), weight("emotional_debt_weight")) * 0.10,
            )
            bonus += min(0.06, weight("relationship_weight") * 0.06)
        if temporal:
            bonus += min(0.06, max(weight("emotional_weight"), weight("self_continuity_weight")) * 0.06)
        return min(0.22, bonus)

    @staticmethod
    def _persona_dynamics_bonus(memory: MemoryRecord, profile: dict[str, object]) -> float:
        metadata = memory.metadata if isinstance(memory.metadata, dict) else {}

        def weight(key: str) -> float:
            try:
                return max(0.0, min(1.0, float(metadata.get(key) or 0.0)))
            except Exception:
                return 0.0

        freshness = weight("freshness_weight")
        scar = weight("scar_weight")
        open_loop = weight("open_loop_weight")
        promise = weight("promise_weight")
        emotional_debt = weight("emotional_debt_weight")
        creative = weight("creative_weight")
        relationship = weight("relationship_weight")
        emotional = weight("emotional_weight")
        decay_mode = clean_text(metadata.get("decay_mode"), 60)
        phase = clean_text(metadata.get("relationship_phase"), 60)

        bonus = min(0.055, freshness * 0.055)
        durable = max(scar, promise, open_loop, emotional_debt, creative)
        if decay_mode in {"no_decay", "scar_slow_decay", "creative_milestone"}:
            bonus += min(0.075, durable * 0.075)
        elif decay_mode == "slow_decay":
            bonus += min(0.045, max(relationship, emotional) * 0.045)
        if phase in {"conflict", "repair", "comfort"}:
            bonus += min(0.045, max(scar, emotional, relationship) * 0.045)

        contextual = bool(profile.get("contextual_recall"))
        temporal = bool(profile.get("temporal_aggregate"))
        open_loop_followup = bool(profile.get("open_loop_followup"))
        if contextual:
            bonus += min(0.055, max(open_loop, promise, emotional_debt, scar) * 0.055)
        if open_loop_followup:
            bonus += min(0.11, max(open_loop, promise, emotional_debt, scar) * 0.11)
        if temporal:
            bonus += min(0.040, max(freshness, emotional) * 0.040)
        return min(0.18, bonus)

    def _livingmemory_graph_relevance_guard(
        self,
        memory: MemoryRecord,
        term_hits: int,
        exact_hit: bool,
        min_hits: int,
    ) -> str:
        if not self._is_livingmemory_graph_memory(memory) or exact_hit:
            return ""
        required_hits = max(3, min_hits + 1)
        age_days = self._age_days(memory.occurred_at or memory.created_at)
        if age_days is not None and age_days >= 30:
            required_hits = max(required_hits, 4)
        if term_hits < required_hits:
            return f"livingmemory_graph_hit_too_weak hits={term_hits}/{required_hits};age_days={age_days:.1f}" if age_days is not None else f"livingmemory_graph_hit_too_weak hits={term_hits}/{required_hits}"
        return ""

    def _is_livingmemory_graph_memory(self, memory: MemoryRecord) -> bool:
        return (
            clean_text(memory.source_plugin, 80).lower() == "livingmemory"
            and clean_text(memory.memory_type, 120).lower().startswith("livingmemory_graph:")
        )

    def _recency_bonus(self, iso_text: str) -> float:
        days = self._age_days(iso_text)
        if days is None:
            return 0.0
        return 0.2 * math.exp(-days / 14.0)

    def _age_days(self, iso_text: str) -> float | None:
        if not iso_text:
            return None
        try:
            dt = datetime.fromisoformat(iso_text.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400)
