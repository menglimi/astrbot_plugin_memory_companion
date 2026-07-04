from __future__ import annotations

from typing import Any


class ConfigView:
    ALIASES = {
        # retrieval → retrieval_advanced
        "retrieval.embedding_candidate_limit": ("retrieval_advanced.embedding_candidate_limit",),
        "retrieval.embedding_top_k": ("retrieval_advanced.embedding_top_k",),
        "retrieval.embedding_score_threshold": ("retrieval_advanced.embedding_score_threshold",),
        "retrieval.embedding_weight": ("retrieval_advanced.embedding_weight",),
        "retrieval.embedding_timeout_ms": ("retrieval_advanced.embedding_timeout_ms",),
        "retrieval.rerank_timeout_ms": ("retrieval_advanced.rerank_timeout_ms",),
        "retrieval.embedding_max_text_chars": ("retrieval_advanced.embedding_max_text_chars",),
        "retrieval.embedding_backfill_enabled": ("retrieval_advanced.embedding_backfill_enabled",),
        "retrieval.embedding_backfill_batch_size": ("retrieval_advanced.embedding_backfill_batch_size",),
        # conversation_memory → conversation_memory_advanced
        "conversation_memory.recent_events_for_followup": ("conversation_memory_advanced.recent_events_for_followup",),
        "conversation_memory.time_window_timeline_limit": ("conversation_memory_advanced.time_window_timeline_limit",),
        "conversation_memory.low_information_guard_enabled": ("conversation_memory_advanced.low_information_guard_enabled",),
        "conversation_memory.low_information_gap_minutes": ("conversation_memory_advanced.low_information_gap_minutes",),
        "conversation_memory.suppress_memory_on_low_information": ("conversation_memory_advanced.suppress_memory_on_low_information",),
        "conversation_memory.topic_shift_guard_enabled": ("conversation_memory_advanced.topic_shift_guard_enabled",),
        "conversation_memory.suppress_memory_on_topic_shift": ("conversation_memory_advanced.suppress_memory_on_topic_shift",),
        "conversation_memory.topic_shift_guard_recent_events": ("conversation_memory_advanced.topic_shift_guard_recent_events",),
        # context_orchestration → context_orchestration_advanced
        "context_orchestration.intent_max_chars": ("context_orchestration_advanced.intent_max_chars",),
        "context_orchestration.self_timeline_limit": ("context_orchestration_advanced.self_timeline_limit",),
        "context_orchestration.user_profile_limit": ("context_orchestration_advanced.user_profile_limit",),
        "context_orchestration.current_window_limit": ("context_orchestration_advanced.current_window_limit",),
        "context_orchestration.conversation_summary_limit": ("context_orchestration_advanced.conversation_summary_limit",),
        "context_orchestration.stable_memory_limit": ("context_orchestration_advanced.stable_memory_limit",),
        # maintenance → maintenance_decay
        "maintenance.memory_decay_after_days": ("maintenance_decay.memory_decay_after_days",),
        "maintenance.memory_decay_idle_days": ("maintenance_decay.memory_decay_idle_days",),
        "maintenance.memory_decay_max_importance_percent": ("maintenance_decay.memory_decay_max_importance_percent",),
        "maintenance.memory_decay_max_access_count": ("maintenance_decay.memory_decay_max_access_count",),
        "maintenance.memory_decay_score_threshold_percent": ("maintenance_decay.memory_decay_score_threshold_percent",),
        "maintenance.memory_decay_max_candidates": ("maintenance_decay.memory_decay_max_candidates",),
        "maintenance.memory_decay_max_groups": ("maintenance_decay.memory_decay_max_groups",),
        "maintenance.memory_decay_min_items_per_summary": ("maintenance_decay.memory_decay_min_items_per_summary",),
        "maintenance.memory_decay_max_items_per_summary": ("maintenance_decay.memory_decay_max_items_per_summary",),
        "maintenance.memory_decay_summary_input_chars": ("maintenance_decay.memory_decay_summary_input_chars",),
        "maintenance.memory_decay_summary_chars": ("maintenance_decay.memory_decay_summary_chars",),
    }

    def __init__(self, raw: Any):
        self.raw = raw or {}

    def get(self, dotted: str, default: Any = None) -> Any:
        marker = object()
        value = self._get_exact(dotted, marker)
        if value is not marker:
            return value
        for alias in self.ALIASES.get(dotted, ()):
            value = self._get_exact(alias, marker)
            if value is not marker:
                return value
        return default

    def _get_exact(self, dotted: str, default: Any = None) -> Any:
        cur: Any = self.raw
        for part in dotted.split("."):
            if isinstance(cur, dict):
                if part not in cur:
                    return default
                cur = cur.get(part)
            else:
                getter = getattr(cur, "get", None)
                if callable(getter):
                    cur = getter(part, default)
                    if cur is default:
                        return default
                else:
                    return default
            if cur is None:
                return default
        return cur

    def bool(self, dotted: str, default: bool) -> bool:
        value = self.get(dotted, default)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on", "开", "开启"}
        return bool(value)

    def int(self, dotted: str, default: int) -> int:
        try:
            return int(self.get(dotted, default))
        except Exception:
            return default

    def float(self, dotted: str, default: float) -> float:
        try:
            return float(self.get(dotted, default))
        except Exception:
            return default
