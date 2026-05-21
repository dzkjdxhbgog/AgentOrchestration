import pytest

from src.orchestrator.workflow import (
    StepStatus,
    WorkflowDefinitionError,
    WorkflowManager,
    WorkflowStep,
    parse_timeout_seconds,
)


def noop():
    return "ok"


def test_conflicting_timeout_units_are_rejected_before_registration():
    manager = WorkflowManager()
    definition = {
        "name": "bad-timeouts",
        "steps": [
            {
                "name": "agent-run",
                "handler": noop,
                "timeout_seconds": 5,
                "timeout_ms": 5000,
            }
        ],
    }

    with pytest.raises(WorkflowDefinitionError) as exc:
        manager.create_workflow_from_definition(definition)

    assert exc.value.reason == "conflicting_timeout_units"
    assert manager.list_workflows() == []
    assert manager.audit_records == [
        {
            "event": "workflow_definition_rejected",
            "reason": "conflicting_timeout_units",
            "fields": "timeout_seconds,timeout_ms",
        }
    ]
    assert manager.validation_metrics["conflicting_timeout_units"] == 1


def test_failed_definition_does_not_advance_existing_workflow_lifecycle():
    manager = WorkflowManager()
    existing = manager.create_workflow("existing")

    with pytest.raises(WorkflowDefinitionError):
        manager.create_workflow_from_definition(
            {
                "name": "invalid",
                "steps": [
                    {
                        "handler": noop,
                        "timeout": 1,
                        "timeout_minutes": 1,
                    }
                ],
            }
        )

    assert existing.status == StepStatus.PENDING
    assert manager.get_workflow(existing.id) is existing


def test_duration_parser_normalizes_single_timeout_unit():
    assert parse_timeout_seconds({"timeout_ms": 2500}) == 2.5

    step = WorkflowStep("short", noop, timeout={"timeout_minutes": 2})

    assert step.timeout == 120
