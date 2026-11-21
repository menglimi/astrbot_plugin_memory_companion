"""Persistent admission for a bounded, in-process summary recovery trial."""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any


class SummaryAdmission:
    """Only an explicitly started task may consume a frozen trial manifest.

    A persisted trial never resumes automatically after restart. Normal traffic
    and manual force calls stay blocked until an operator explicitly resumes.
    The file stores identifiers and hashes, never source text or credentials.
    """

    def __init__(self, path: Path):
        self.path = path
        self.state: dict[str, Any] = {"mode": "normal", "batches": [], "results": []}
        if path.exists():
            self.state = json.loads(path.read_text(encoding="utf-8"))
            if self.state.get("mode") not in {"normal", "paused", "trial"}:
                raise ValueError("invalid_summary_admission_mode")
        self.owner: asyncio.Task[Any] | None = None
        self.current_batch = ""
        self.operation_lock = asyncio.Lock()

    @property
    def normal(self) -> bool:
        return self.state["mode"] == "normal"

    def save(self, **changes: Any) -> None:
        state = {**self.state, **changes}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)
        self.state = state

    def allows(self, batch_id: str = "", *, force: bool = False) -> bool:
        if self.normal:
            return True
        return bool(
            self.state["mode"] == "trial"
            and not force
            and batch_id
            and batch_id == self.current_batch
            and asyncio.current_task() is self.owner
            and any(item["id"] == batch_id for item in self.state["batches"])
        )

    @staticmethod
    def fingerprint(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()


class SummaryAdmissionMethods:
    """Service operations; use the live service's providers, locks and budget."""

    def _summary_trial_provider_keys(self, attempts: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
        # current_session has an empty configured ID. Include runtime identity
        # and the actual in-process object so a switched provider cannot look
        # identical merely because both attempts say "current_session".
        return [(
            str(item.get("provider_id") or ""), str(item.get("source") or ""),
            self._provider_runtime_id(item["provider"], fallback_type=False), id(item["provider"]),
        ) for item in attempts]

    async def _drain_summary_admissions(self) -> None:
        # Admission is already paused. A caller queued on a session lock must
        # recheck admission under that lock, so it cannot start new work here.
        dispatcher = self._summary_recovery_task
        if dispatcher is not None and not dispatcher.done():
            dispatcher.cancel()
            await asyncio.gather(dispatcher, return_exceptions=True)
        workers = [task for task in self._summary_workers.values() if not task.done()]
        if workers:
            await asyncio.gather(*workers)
        for lock in list(self._summary_locks.values()):
            async with lock:
                pass
        self._summary_pending.clear()
        self._summary_pending_contexts.clear()
        self._summary_pending_reasons.clear()

    async def pause_summary_admission(self) -> dict[str, Any]:
        gate = self._summary_admission
        async with gate.operation_lock:
            gate.save(mode="paused")
            await self._drain_summary_admissions()
            return dict(gate.state)

    async def resume_summary_admission(self) -> None:
        """Explicitly restore normal admission; never called by trial cleanup."""
        gate = self._summary_admission
        async with gate.operation_lock:
            gate.save(mode="normal", batches=[], results=[], stop_reason="")
            self._ensure_summary_recovery_dispatcher()

    async def _summary_trial_snapshot(self, batch: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
        context, reason = await self._summary_recovery_context(batch)
        if context is None:
            raise ValueError(f"trial_identity:{reason}")
        if not self._scope_feature_enabled(context, "capture"):
            raise ValueError("trial_capture_disabled")
        persisted = await self.store.summary_batch_context(batch["id"])
        rows = await self.store.summary_batch_rows(batch["id"])
        if not persisted or not rows or {row["id"] for row in rows} != {
            row["id"] for row in persisted["events"]
        }:
            raise ValueError("trial_source_ownership_changed")
        attempts = await self._summary_provider_attempts(context)
        if not attempts:
            raise ValueError("trial_provider_unavailable")
        # Provider identities are compared inside the summary call too; the
        # actual provider objects are always resolved by this service instance.
        providers = self._summary_trial_provider_keys(attempts)
        return context, {
            "id": batch["id"],
            "source_hash": self._summary_admission.fingerprint(persisted),
            "rows_hash": self._summary_admission.fingerprint(rows),
            "providers_hash": self._summary_admission.fingerprint(providers),
        }

    async def _validate_summary_trial(self, batch: dict[str, Any], attempts: list[dict[str, Any]]) -> None:
        gate = self._summary_admission
        if gate.normal:
            return
        if not gate.allows(batch["id"]):
            raise ValueError("trial_admission_changed")
        _, current = await self._summary_trial_snapshot(batch)
        expected = next(item for item in gate.state["batches"] if item["id"] == batch["id"])
        providers = self._summary_trial_provider_keys(attempts)
        if current != expected or gate.fingerprint(providers) != expected["providers_hash"]:
            raise ValueError("trial_source_or_provider_changed")

    async def run_summary_recovery_trial(self, *, limit: int = 5) -> dict[str, Any]:
        """Attempt at most five oldest due persisted IDs exactly once, then pause.

        An incomplete batch (including budget/provider failure or a review
        candidate) stops dispatch. Fallbacks and repairs within that one attempt
        retain ordinary automatic reservations; selected IDs are never replaced.
        """
        if not 1 <= limit <= 5:
            raise ValueError("summary_trial_limit_must_be_between_1_and_5")
        gate = self._summary_admission
        async with gate.operation_lock:
            gate.save(mode="paused", batches=[], results=[], stop_reason="")
            try:
                await self._drain_summary_admissions()
                batches = await self.store.oldest_due_summary_batches(limit=limit)
                manifest = []
                for batch in batches:
                    _, snapshot = await self._summary_trial_snapshot(batch)
                    manifest.append(snapshot)
                gate.save(mode="trial", batches=manifest)
                gate.owner = asyncio.current_task()
                for frozen in manifest:
                    batch = await self.store.get_summary_batch(frozen["id"])
                    if batch is None:
                        raise ValueError("trial_batch_missing")
                    context, snapshot = await self._summary_trial_snapshot(batch)
                    if snapshot != frozen:
                        raise ValueError("trial_source_or_provider_changed")
                    due = await self.store.get_due_summary_batch(
                        batch["id"], session_id=context.session_id, scope=context.scope,
                    )
                    if due is None:
                        raise ValueError("trial_batch_no_longer_due")
                    gate.current_batch = batch["id"]
                    await self.maybe_summarize_session(context, recovery_batch_id=batch["id"])
                    result = await self.store.get_summary_batch(batch["id"])
                    state = str((result or {}).get("state") or "missing")
                    gate.save(results=[*gate.state["results"], {"id": batch["id"], "state": state}])
                    if result and result.get("memory_id"):
                        record = await self.store.get_memory(result["memory_id"])
                        if record is None or record.review_status == "pending":
                            raise ValueError("trial_batch_needs_review")
                    if state not in {"completed", "no_memory"}:
                        raise ValueError(f"trial_batch_incomplete:{state}")
            except asyncio.CancelledError:
                gate.save(stop_reason="cancelled")
                raise
            except Exception as exc:
                # Error codes are deliberately fixed; provider exception bodies
                # can contain private material and do not belong in this file.
                reason = str(exc) if isinstance(exc, ValueError) and str(exc).startswith("trial_") else "trial_failed"
                gate.save(stop_reason=reason)
            finally:
                gate.owner = None
                gate.current_batch = ""
                gate.save(mode="paused")
            return dict(gate.state)
