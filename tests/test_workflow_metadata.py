import pytest

from src.orchestrator.workflow import (
    StepStatus,
    WorkflowManager,
    WorkflowStep,
    find_reserved_metadata_keys,
)


def test_find_reserved_metadata_keys_is_case_insensitive():
    invalid = find_reserved_metadata_keys(
        {
            "Run_ID": "run-1",
            "safe_key": "safe",
            "STATUS": "running",
        }
    )

    assert invalid == ["Run_ID", "STATUS"]


def test_create_workflow_rejects_reserved_metadata_keys():
    manager = WorkflowManager()

    with pytest.raises(ValueError, match="status"):
        manager.create_workflow(
            "unsafe",
            metadata={"status": "running", "owner": "team-a"},
        )

    assert manager.list_workflows() == []
    assert manager.audit_records == [
        {
            "event": "workflow.metadata_rejected",
            "workflow_name": "unsafe",
            "invalid_keys": ["status"],
        }
    ]
    assert "running" not in repr(manager.audit_records)


def test_add_step_rejects_reserved_metadata_without_registering_step():
    workflow = WorkflowManager().create_workflow(
        "safe",
        metadata={"owner": "team-a"},
    )
    step = WorkflowStep(
        "run",
        lambda: "ok",
        metadata={"queue": "priority", "purpose": "test"},
    )

    with pytest.raises(ValueError, match="queue"):
        workflow.add_step(step)

    assert workflow.status is StepStatus.PENDING
    assert workflow.steps == []
    assert workflow.audit_records == [
        {
            "event": "workflow.step_metadata_rejected",
            "workflow_id": workflow.id,
            "step_id": step.id,
            "invalid_keys": ["queue"],
        }
    ]
    assert "priority" not in repr(workflow.audit_records)


def test_execute_workflow_defers_if_metadata_is_mutated_after_registration():
    manager = WorkflowManager()
    workflow = manager.create_workflow("safe", metadata={"owner": "team-a"})
    step = WorkflowStep("run", lambda: "ok", metadata={"purpose": "test"})
    workflow.add_step(step)
    step.metadata["lifecycle"] = "force-completed"

    assert manager.execute_workflow(workflow.id) is False

    assert workflow.status is StepStatus.PENDING
    assert step.status is StepStatus.PENDING
    assert step.result is None
    assert workflow.audit_records == [
        {
            "event": "workflow.execution_deferred",
            "workflow_id": workflow.id,
            "invalid_keys": [f"step.{step.id}.lifecycle"],
            "status": "pending",
        }
    ]


def test_workflow_runs_with_non_reserved_user_metadata():
    manager = WorkflowManager()
    workflow = manager.create_workflow("safe", metadata={"owner": "team-a"})
    workflow.add_step(
        WorkflowStep("run", lambda: "ok", metadata={"purpose": "test"})
    )

    assert manager.execute_workflow(workflow.id) is True

    assert workflow.status is StepStatus.COMPLETED
    assert workflow.steps[0].status is StepStatus.COMPLETED
    assert workflow.steps[0].result == "ok"
