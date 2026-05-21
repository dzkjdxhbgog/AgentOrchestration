from src.orchestrator.workflow import (
    StepStatus,
    WorkflowManager,
    WorkflowStep,
)


def test_partial_rollback_blocks_downstream_steps():
    manager = WorkflowManager()
    workflow = manager.create_workflow("rollback-blocking")
    executed = []

    workflow.add_step(
        WorkflowStep("prepare", lambda: executed.append("prepare"))
    )
    workflow.add_step(
        WorkflowStep(
            "charge",
            lambda: (_ for _ in ()).throw(RuntimeError("card-token-123")),
            compensation_handler=lambda: False,
        )
    )
    downstream = WorkflowStep("ship", lambda: executed.append("ship"))
    workflow.add_step(downstream)

    assert manager.execute_workflow(workflow.id) is False

    assert executed == ["prepare"]
    assert workflow.status is StepStatus.FAILED
    assert workflow.rollback_state == "partial"
    assert downstream.status is StepStatus.BLOCKED
    assert downstream.blocked_reason == "partial_rollback"

    assert {
        "event": "workflow_compensation",
        "decision": "partial_rollback",
        "reason": "compensation_incomplete",
    }.items() <= workflow.audit_records[0].items()
    assert {
        "event": "workflow_downstream_blocked",
        "step_id": downstream.id,
        "decision": "blocked",
        "reason": "partial_rollback",
    }.items() <= workflow.audit_records[1].items()
    assert "card-token-123" not in str(workflow.audit_records)


def test_completed_step_compensation_failure_blocks_downstream_steps():
    manager = WorkflowManager()
    workflow = manager.create_workflow("completed-step-rollback")
    executed = []

    def fail_compensation():
        executed.append("rollback")
        raise RuntimeError("private rollback payload")

    workflow.add_step(
        WorkflowStep(
            "reserve",
            lambda: executed.append("reserve"),
            compensation_handler=fail_compensation,
        )
    )
    workflow.add_step(
        WorkflowStep(
            "dispatch",
            lambda: (_ for _ in ()).throw(RuntimeError("failed")),
        )
    )
    downstream = WorkflowStep("notify", lambda: executed.append("notify"))
    workflow.add_step(downstream)

    assert manager.execute_workflow(workflow.id) is False

    assert executed == ["reserve", "rollback"]
    assert workflow.rollback_state == "partial"
    assert workflow.steps[0].status is StepStatus.ROLLBACK_FAILED
    assert downstream.status is StepStatus.BLOCKED
    assert downstream.blocked_reason == "partial_rollback"
    assert "private rollback payload" not in str(workflow.audit_records)


def test_missing_compensation_handler_blocks_downstream_steps():
    manager = WorkflowManager()
    workflow = manager.create_workflow("missing-compensation")
    downstream = WorkflowStep("notify", lambda: "should not run")

    workflow.add_step(
        WorkflowStep(
            "write",
            lambda: (_ for _ in ()).throw(RuntimeError("failed")),
        )
    )
    workflow.add_step(downstream)

    assert manager.execute_workflow(workflow.id) is False

    assert workflow.rollback_state == "partial"
    assert downstream.status is StepStatus.BLOCKED
    assert downstream.blocked_reason == "partial_rollback"
    assert workflow.audit_records[0]["decision"] == "not_configured"


def test_blocked_workflow_rejects_registration_and_dispatch():
    manager = WorkflowManager()
    workflow = manager.create_workflow("guarded")
    executed = []

    workflow.add_step(
        WorkflowStep(
            "write",
            lambda: (_ for _ in ()).throw(RuntimeError("failed")),
        )
    )
    downstream = WorkflowStep("notify", lambda: executed.append("notify"))
    workflow.add_step(downstream)

    assert manager.execute_workflow(workflow.id) is False
    assert manager.dispatch_step(workflow.id, downstream.id) is False

    try:
        workflow.add_step(
            WorkflowStep("late", lambda: executed.append("late"))
        )
        assert False
    except ValueError:
        pass

    assert executed == []
    assert downstream.status is StepStatus.BLOCKED
    assert any(
        record["event"] == "workflow_dispatch_blocked"
        and record["reason"] == "partial_rollback"
        for record in workflow.audit_records
    )


def test_successful_compensation_is_audited_without_partial_rollback():
    manager = WorkflowManager()
    workflow = manager.create_workflow("successful-compensation")
    downstream = WorkflowStep("downstream", lambda: "should not run")

    workflow.add_step(
        WorkflowStep(
            "write",
            lambda: (_ for _ in ()).throw(RuntimeError("failed")),
            compensation_handler=lambda: True,
        )
    )
    workflow.add_step(downstream)

    assert manager.execute_workflow(workflow.id) is False

    assert workflow.rollback_state == "rolled_back"
    assert workflow.steps[0].status is StepStatus.ROLLED_BACK
    assert downstream.status is StepStatus.BLOCKED
    assert downstream.blocked_reason == "failed_step"
    assert workflow.audit_records[0]["decision"] == "rolled_back"
