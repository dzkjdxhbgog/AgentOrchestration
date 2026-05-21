"""Artifact retention validation for workflow cleanup scheduling."""

from dataclasses import dataclass
from enum import Enum
import hashlib
from typing import Dict, List, Tuple


class CleanupDecision(Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DEFERRED = "deferred"


class WorkflowLifecycle(Enum):
    PENDING = "pending"
    REGISTERED = "registered"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_LIFECYCLES = {
    WorkflowLifecycle.COMPLETED,
    WorkflowLifecycle.FAILED,
    WorkflowLifecycle.CANCELLED,
}


@dataclass(frozen=True)
class ArtifactRetentionPolicy:
    name: str
    retention_days: int
    cleanup_after_days: int
    legal_hold: bool = False
    artifact_names: Tuple[str, ...] = ()
    max_cleanup_batch: int = 1000
    version: int = 1


@dataclass(frozen=True)
class WorkflowRetentionContext:
    workflow_id: str
    lifecycle: WorkflowLifecycle
    lifecycle_revision: int
    expected_revision: int
    policies: Tuple[ArtifactRetentionPolicy, ...]


@dataclass(frozen=True)
class CleanupScheduleRecord:
    workflow_id: str
    policy_digest: str
    due_in_days: int
    lifecycle_revision: int
    policy_version: int


@dataclass(frozen=True)
class CleanupValidationResult:
    decision: CleanupDecision
    reason: str
    lifecycle: WorkflowLifecycle
    lifecycle_revision: int
    scheduled: Tuple[CleanupScheduleRecord, ...] = ()


class ArtifactRetentionCleanupScheduler:
    """Validate retention rules before mutating cleanup scheduling state."""

    def __init__(self) -> None:
        self._scheduled: Dict[Tuple[str, str, int], CleanupScheduleRecord] = {}
        self._audit_records: List[Dict[str, object]] = []

    @property
    def scheduled_cleanups(self) -> Tuple[CleanupScheduleRecord, ...]:
        return tuple(self._scheduled.values())

    @property
    def audit_records(self) -> Tuple[Dict[str, object], ...]:
        return tuple(dict(record) for record in self._audit_records)

    def schedule_cleanup(
        self,
        context: WorkflowRetentionContext,
    ) -> CleanupValidationResult:
        if not context.workflow_id.strip():
            return self._record_result(
                context,
                CleanupDecision.REJECTED,
                "workflow_id_required",
            )

        if context.lifecycle_revision != context.expected_revision:
            return self._record_result(
                context,
                CleanupDecision.DEFERRED,
                "stale_lifecycle_revision",
            )

        if context.lifecycle not in TERMINAL_LIFECYCLES:
            return self._record_result(
                context,
                CleanupDecision.DEFERRED,
                "workflow_not_terminal",
            )

        policy_error = self._validate_policies(context.policies)
        if policy_error:
            return self._record_result(
                context,
                CleanupDecision.REJECTED,
                policy_error,
            )

        records = tuple(
            CleanupScheduleRecord(
                workflow_id=context.workflow_id,
                policy_digest=self._policy_digest(policy),
                due_in_days=policy.cleanup_after_days,
                lifecycle_revision=context.lifecycle_revision,
                policy_version=policy.version,
            )
            for policy in context.policies
        )
        for record in records:
            key = (
                record.workflow_id,
                record.policy_digest,
                record.policy_version,
            )
            if key in self._scheduled:
                return self._record_result(
                    context,
                    CleanupDecision.REJECTED,
                    "duplicate_cleanup_schedule",
                )

        for record in records:
            key = (
                record.workflow_id,
                record.policy_digest,
                record.policy_version,
            )
            self._scheduled[
                key
            ] = record

        return self._record_result(
            context,
            CleanupDecision.ACCEPTED,
            "cleanup_scheduled",
            records,
        )

    def _validate_policies(
        self,
        policies: Tuple[ArtifactRetentionPolicy, ...],
    ) -> str:
        if not policies:
            return "retention_policy_required"

        seen_names = set()
        for policy in policies:
            policy_name = policy.name.strip()
            if not policy_name:
                return "retention_policy_name_required"
            if policy_name in seen_names:
                return "duplicate_retention_policy"
            seen_names.add(policy_name)

            if policy.version <= 0:
                return "retention_policy_version_invalid"
            if policy.retention_days <= 0:
                return "retention_period_invalid"
            if policy.cleanup_after_days < 0:
                return "cleanup_delay_invalid"
            if policy.cleanup_after_days > policy.retention_days:
                return "cleanup_after_retention_period"
            if policy.max_cleanup_batch <= 0:
                return "cleanup_batch_invalid"
            if policy.legal_hold:
                return "retention_policy_legal_hold"
        return ""

    def _record_result(
        self,
        context: WorkflowRetentionContext,
        decision: CleanupDecision,
        reason: str,
        scheduled: Tuple[CleanupScheduleRecord, ...] = (),
    ) -> CleanupValidationResult:
        self._audit_records.append(
            {
                "workflow_id": context.workflow_id,
                "decision": decision.value,
                "reason": reason,
                "lifecycle": context.lifecycle.value,
                "lifecycle_revision": context.lifecycle_revision,
                "policy_count": len(context.policies),
                "policy_digests": tuple(
                    self._policy_digest(policy) for policy in context.policies
                ),
            }
        )
        return CleanupValidationResult(
            decision=decision,
            reason=reason,
            lifecycle=context.lifecycle,
            lifecycle_revision=context.lifecycle_revision,
            scheduled=scheduled,
        )

    def _policy_digest(self, policy: ArtifactRetentionPolicy) -> str:
        digest_source = (
            f"{policy.name.strip()}:{policy.version}:"
            f"{policy.max_cleanup_batch}"
        )
        return hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:16]
