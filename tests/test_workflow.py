from src.orchestrator.workflow import StepStatus, WorkflowManager, WorkflowStep


def raise_runtime_error(message):
    raise RuntimeError(message)


def fail_rollback():
    raise_runtime_error("rollback lost lock")


def test_partial_rollback_blocks_downstream_and_records_audit():
    events = []
    manager = WorkflowManager()
    workflow = manager.create_workflow("rollback-guard")

    workflow.add_step(
        WorkflowStep(
            "reserve-capacity",
            handler=lambda: events.append("reserved"),
            compensation_handler=fail_rollback,
        )
    )
    workflow.add_step(
        WorkflowStep(
            "dispatch-agent",
            handler=lambda: raise_runtime_error("dispatch failed"),
        )
    )
    workflow.add_step(
        WorkflowStep(
            "notify-downstream",
            handler=lambda: events.append("downstream-ran"),
        )
    )

    assert manager.execute_workflow(workflow.id) is False

    reserve, dispatch, downstream = workflow.steps
    assert reserve.status is StepStatus.COMPLETED
    assert reserve.compensation_error == "rollback lost lock"
    assert dispatch.status is StepStatus.FAILED
    assert downstream.status is StepStatus.SKIPPED
    assert downstream.blocked_reason == "partial_rollback"
    assert events == ["reserved"]
    assert [entry["event"] for entry in workflow.audit_log] == [
        "workflow.compensation.failed",
        "workflow.downstream_blocked",
    ]
    assert workflow.audit_log[1]["reason"] == "partial_rollback"


def test_failed_step_blocks_downstream_after_successful_compensation():
    events = []
    manager = WorkflowManager()
    workflow = manager.create_workflow("compensation-guard")

    workflow.add_step(
        WorkflowStep(
            "write-state",
            handler=lambda: events.append("write-state"),
            compensation_handler=lambda: events.append("compensated"),
        )
    )
    workflow.add_step(
        WorkflowStep(
            "bind-routing",
            handler=lambda: raise_runtime_error("invalid binding"),
        )
    )
    workflow.add_step(
        WorkflowStep(
            "start-downstream",
            handler=lambda: events.append("downstream-ran"),
        )
    )

    assert manager.execute_workflow(workflow.id) is False

    downstream = workflow.steps[2]
    assert downstream.status is StepStatus.SKIPPED
    assert downstream.blocked_reason == "step_failed"
    assert events == ["write-state", "compensated"]
    assert workflow.audit_log[-1]["event"] == "workflow.downstream_blocked"
