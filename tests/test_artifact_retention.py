from src.orchestrator.artifact_retention import (
    ArtifactRetentionCleanupScheduler,
    ArtifactRetentionPolicy,
    CleanupDecision,
    WorkflowLifecycle,
    WorkflowRetentionContext,
)
from src.orchestrator.scheduler import TaskScheduler


def make_context(
    lifecycle=WorkflowLifecycle.COMPLETED,
    revision=7,
    expected_revision=7,
    policies=None,
):
    return WorkflowRetentionContext(
        workflow_id="workflow-123",
        lifecycle=lifecycle,
        lifecycle_revision=revision,
        expected_revision=expected_revision,
        policies=tuple(
            policies
            if policies is not None
            else (
                ArtifactRetentionPolicy(
                    name="default",
                    retention_days=30,
                    cleanup_after_days=7,
                    artifact_names=("customer-invoice.pdf",),
                ),
            )
        ),
    )


def test_completed_workflow_schedules_cleanup_with_sanitized_audit():
    scheduler = ArtifactRetentionCleanupScheduler()

    result = scheduler.schedule_cleanup(make_context())

    assert result.decision == CleanupDecision.ACCEPTED
    assert result.reason == "cleanup_scheduled"
    assert len(result.scheduled) == 1
    assert len(scheduler.scheduled_cleanups) == 1

    audit = scheduler.audit_records[-1]
    assert audit["decision"] == "accepted"
    assert audit["reason"] == "cleanup_scheduled"
    assert "policy_digests" in audit
    assert "customer-invoice.pdf" not in str(audit)
    assert "retention_days" not in audit
    assert "cleanup_after_days" not in audit


def test_running_workflow_defers_without_mutating_schedule():
    scheduler = ArtifactRetentionCleanupScheduler()

    result = scheduler.schedule_cleanup(
        make_context(lifecycle=WorkflowLifecycle.RUNNING)
    )

    assert result.decision == CleanupDecision.DEFERRED
    assert result.reason == "workflow_not_terminal"
    assert result.lifecycle == WorkflowLifecycle.RUNNING
    assert result.lifecycle_revision == 7
    assert scheduler.scheduled_cleanups == ()


def test_stale_lifecycle_revision_defers_without_mutating_schedule():
    scheduler = ArtifactRetentionCleanupScheduler()

    result = scheduler.schedule_cleanup(
        make_context(revision=8, expected_revision=7)
    )

    assert result.decision == CleanupDecision.DEFERRED
    assert result.reason == "stale_lifecycle_revision"
    assert scheduler.scheduled_cleanups == ()


def test_duplicate_policy_rejected_before_schedule_commit():
    scheduler = ArtifactRetentionCleanupScheduler()
    duplicate_policies = (
        ArtifactRetentionPolicy("default", 30, 7),
        ArtifactRetentionPolicy("default", 14, 3),
    )

    result = scheduler.schedule_cleanup(
        make_context(policies=duplicate_policies)
    )

    assert result.decision == CleanupDecision.REJECTED
    assert result.reason == "duplicate_retention_policy"
    assert scheduler.scheduled_cleanups == ()


def test_policy_violation_rejected_before_schedule_commit():
    scheduler = ArtifactRetentionCleanupScheduler()
    invalid_policies = (
        ArtifactRetentionPolicy(
            name="legal-hold",
            retention_days=30,
            cleanup_after_days=7,
            legal_hold=True,
        ),
    )

    result = scheduler.schedule_cleanup(
        make_context(policies=invalid_policies)
    )

    assert result.decision == CleanupDecision.REJECTED
    assert result.reason == "retention_policy_legal_hold"
    assert scheduler.scheduled_cleanups == ()


def test_duplicate_cleanup_request_rejected_without_extra_schedule():
    scheduler = ArtifactRetentionCleanupScheduler()

    first = scheduler.schedule_cleanup(make_context())
    second = scheduler.schedule_cleanup(make_context())

    assert first.decision == CleanupDecision.ACCEPTED
    assert second.decision == CleanupDecision.REJECTED
    assert second.reason == "duplicate_cleanup_schedule"
    assert len(scheduler.scheduled_cleanups) == 1


def test_task_scheduler_validates_retention_before_dispatch_binding():
    scheduler = TaskScheduler()

    result = scheduler.schedule_artifact_cleanup(
        make_context(lifecycle=WorkflowLifecycle.RUNNING)
    )

    assert result.decision == CleanupDecision.DEFERRED
    assert result.reason == "workflow_not_terminal"
    assert scheduler.artifact_retention_scheduler.scheduled_cleanups == ()
