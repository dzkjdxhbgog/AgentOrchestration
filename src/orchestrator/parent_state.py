"""Parent run state reducer for child lifecycle events."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Tuple


class LifecycleState(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATES = {
    LifecycleState.SUCCEEDED,
    LifecycleState.FAILED,
    LifecycleState.CANCELLED,
}


@dataclass(frozen=True)
class ChildEvent:
    child_id: str
    lifecycle: LifecycleState
    attempt: int
    revision: int
    runtime_context: Mapping[str, Any] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )


@dataclass(frozen=True)
class AuditRecord:
    decision: str
    reason: str
    parent_lifecycle: str
    child_id: str
    child_lifecycle: str
    attempt: int
    revision: int


@dataclass(frozen=True)
class ParentRunState:
    run_id: str
    lifecycle: LifecycleState
    attempt: int = 1
    revision: int = 0
    children: Dict[str, LifecycleState] = field(default_factory=dict)
    audit: Tuple[AuditRecord, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ReducerDecision:
    accepted: bool
    reason: str
    state: ParentRunState


class ParentStateReducer:
    """Applies child events only when they match the parent attempt and revision."""

    @classmethod
    def apply_child_event(cls, parent: ParentRunState, event: ChildEvent) -> ReducerDecision:
        rejection = cls._rejection_reason(parent, event)
        if rejection:
            audit = cls._audit("rejected", rejection, parent, event)
            return ReducerDecision(
                accepted=False,
                reason=rejection,
                state=replace(parent, audit=parent.audit + (audit,)),
            )

        children = dict(parent.children)
        children[event.child_id] = event.lifecycle
        next_lifecycle = cls._next_parent_lifecycle(parent.lifecycle, event.lifecycle)
        audit = cls._audit("accepted", "child_event_committed", parent, event)
        return ReducerDecision(
            accepted=True,
            reason="child_event_committed",
            state=replace(
                parent,
                lifecycle=next_lifecycle,
                revision=event.revision,
                children=children,
                audit=parent.audit + (audit,),
            ),
        )

    @staticmethod
    def _rejection_reason(parent: ParentRunState, event: ChildEvent) -> Optional[str]:
        if event.attempt != parent.attempt:
            return "attempt_mismatch"
        if event.revision <= parent.revision:
            return "stale_revision"
        if event.revision != parent.revision + 1:
            return "revision_gap"
        if (
            parent.lifecycle == LifecycleState.FAILED
            and event.lifecycle == LifecycleState.SUCCEEDED
        ):
            return "parent_failed_late_child_success"
        if parent.lifecycle in TERMINAL_STATES:
            return "terminal_parent"
        return None

    @staticmethod
    def _next_parent_lifecycle(
        parent_lifecycle: LifecycleState,
        child_lifecycle: LifecycleState,
    ) -> LifecycleState:
        if child_lifecycle == LifecycleState.FAILED:
            return LifecycleState.FAILED
        if (
            parent_lifecycle == LifecycleState.PENDING
            and child_lifecycle == LifecycleState.RUNNING
        ):
            return LifecycleState.RUNNING
        return parent_lifecycle

    @staticmethod
    def _audit(
        decision: str,
        reason: str,
        parent: ParentRunState,
        event: ChildEvent,
    ) -> AuditRecord:
        return AuditRecord(
            decision=decision,
            reason=reason,
            parent_lifecycle=parent.lifecycle.value,
            child_id=event.child_id,
            child_lifecycle=event.lifecycle.value,
            attempt=event.attempt,
            revision=event.revision,
        )
