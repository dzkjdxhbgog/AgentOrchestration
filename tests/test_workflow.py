from src.orchestrator.workflow import (
    StepStatus,
    WorkflowManager,
)


class TestWorkflowManager:
    def setup_method(self):
        self.manager = WorkflowManager()

    def test_rejects_subworkflow_start_after_parent_failure(self):
        parent = self.manager.create_workflow("parent")
        assert self.manager.update_workflow_status(
            parent.id,
            StepStatus.RUNNING,
        )
        parent_attempt = parent.attempt
        parent_revision = parent.revision

        assert self.manager.update_workflow_status(
            parent.id,
            StepStatus.FAILED,
        )

        subworkflow = self.manager.start_subworkflow(
            parent.id,
            "child",
            expected_parent_attempt=parent_attempt,
            expected_parent_revision=parent_revision,
        )

        assert subworkflow is None
        assert parent.status == StepStatus.FAILED
        assert parent.subworkflow_ids == []
        assert self.manager.audit_events()[-1]["reason"] == "stale_revision"

    def test_rejects_subworkflow_start_for_terminal_parent_snapshot(self):
        parent = self.manager.create_workflow("parent")
        assert self.manager.update_workflow_status(
            parent.id,
            StepStatus.RUNNING,
        )
        assert self.manager.update_workflow_status(
            parent.id,
            StepStatus.FAILED,
        )

        subworkflow = self.manager.start_subworkflow(
            parent.id,
            "child",
            expected_parent_attempt=parent.attempt,
            expected_parent_revision=parent.revision,
        )

        assert subworkflow is None
        assert parent.status == StepStatus.FAILED
        assert parent.subworkflow_ids == []
        assert self.manager.audit_events()[-1]["reason"] == "terminal_parent"

    def test_starts_subworkflow_when_parent_snapshot_is_current(self):
        parent = self.manager.create_workflow("parent")
        assert self.manager.update_workflow_status(
            parent.id,
            StepStatus.RUNNING,
        )

        subworkflow = self.manager.start_subworkflow(
            parent.id,
            "child",
            expected_parent_attempt=parent.attempt,
            expected_parent_revision=parent.revision,
        )

        assert subworkflow is not None
        assert subworkflow.parent_id == parent.id
        assert subworkflow.parent_attempt == 1
        assert subworkflow.status == StepStatus.RUNNING
        assert parent.subworkflow_ids == [subworkflow.id]
        assert self.manager.audit_events()[-1]["decision"] == "started"

    def test_rejects_subworkflow_start_before_parent_runs(self):
        parent = self.manager.create_workflow("parent")

        subworkflow = self.manager.start_subworkflow(
            parent.id,
            "child",
            expected_parent_attempt=parent.attempt,
            expected_parent_revision=parent.revision,
        )

        assert subworkflow is None
        assert parent.status == StepStatus.PENDING
        assert parent.subworkflow_ids == []
        assert (
            self.manager.audit_events()[-1]["reason"]
            == "parent_not_running"
        )
