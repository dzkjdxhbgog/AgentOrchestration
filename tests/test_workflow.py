import logging

import pytest

from src.common.metrics import metrics
from src.orchestrator.workflow import MatrixExpansionError, StepStatus, Workflow, WorkflowManager, WorkflowStep


def noop():
    return "ok"


class TestWorkflowMatrixExpansion:
    def test_add_step_rejects_matrix_expansion_over_limit(self, caplog):
        workflow = Workflow("fan-out")
        step = WorkflowStep(
            "oversized matrix",
            noop,
            matrix={"region": ["us", "eu", "apac"], "runtime": ["py", "js"]},
            max_matrix_expansion=4,
        )

        with caplog.at_level(logging.WARNING):
            with pytest.raises(MatrixExpansionError):
                workflow.add_step(step)

        assert workflow.status == StepStatus.PENDING
        assert workflow.steps == []
        assert workflow.get_step(step.id) is None
        assert workflow.audit_records[-1]["reason"] == "expansion_limit_exceeded"
        assert "Rejected workflow matrix expansion" in caplog.text
        assert metrics.snapshot()["counters"]["workflow.matrix_expansion.rejected"] >= 1

    def test_execute_workflow_rejects_dynamic_fanout_before_state_changes(self):
        manager = WorkflowManager()
        workflow = manager.create_workflow("dynamic fanout")
        step = WorkflowStep(
            "mutable matrix",
            noop,
            matrix={"shard": ["a"]},
            max_matrix_expansion=2,
        )
        workflow.add_step(step)

        step.matrix = {"shard": ["a", "b", "c"]}

        assert manager.execute_workflow(workflow.id) is False
        assert workflow.status == StepStatus.PENDING
        assert step.status == StepStatus.PENDING
        assert workflow.audit_records[-1]["reason"] == "expansion_limit_exceeded"

    def test_add_step_rejects_duplicate_matrix_values(self):
        workflow = Workflow("duplicate fanout")
        step = WorkflowStep("duplicate matrix", noop, matrix={"region": ["us", "us"]})

        with pytest.raises(MatrixExpansionError):
            workflow.add_step(step)

        assert workflow.steps == []
        assert workflow.audit_records[-1]["reason"] == "duplicate_dimension_values"

    def test_valid_matrix_executes_normally(self):
        manager = WorkflowManager()
        workflow = manager.create_workflow("valid fanout")
        workflow.add_step(WorkflowStep("bounded matrix", noop, matrix={"region": ["us", "eu"]}))

        assert manager.execute_workflow(workflow.id) is True
        assert workflow.status == StepStatus.COMPLETED
        assert workflow.steps[0].status == StepStatus.COMPLETED
