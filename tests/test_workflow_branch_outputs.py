import pytest

from src.orchestrator.workflow import (
    BranchOutputNamespaceError,
    StepStatus,
    WorkflowStep,
    WorkflowManager,
)


class TestWorkflowBranchOutputs:
    def setup_method(self):
        self.manager = WorkflowManager()

    def test_rejects_duplicate_branch_output_namespace_at_registration(self):
        workflow = self.manager.create_workflow("parallel")
        workflow.add_branch_step("branch-a", lambda: {"a": 1}, "branch-a", "result", "join")

        with pytest.raises(BranchOutputNamespaceError):
            workflow.add_branch_step("branch-b", lambda: {"b": 1}, "branch-b", "result", "join")

        assert len(workflow.steps) == 1
        assert workflow.status == StepStatus.PENDING

    def test_rejects_nested_branch_output_namespace_at_registration(self):
        workflow = self.manager.create_workflow("parallel")
        workflow.add_branch_step("branch-a", lambda: {"a": 1}, "branch-a", "result", "join")

        with pytest.raises(BranchOutputNamespaceError):
            workflow.add_branch_step("branch-b", lambda: {"b": 1}, "branch-b", "result.extra", "join")

        assert len(workflow.steps) == 1
        assert workflow.status == StepStatus.PENDING

    def test_pre_dispatch_validation_blocks_mutated_namespace_collision(self):
        called = []
        workflow = self.manager.create_workflow("parallel")
        workflow.add_branch_step("branch-a", lambda: called.append("a"), "branch-a", "alpha", "join")
        workflow.add_branch_step("branch-b", lambda: called.append("b"), "branch-b", "beta", "join")
        workflow.add_join_step("join", lambda outputs: outputs, "join", ["branch-a", "branch-b"])
        workflow.steps[1].output_namespace = "alpha.child"

        assert not self.manager.execute_workflow(workflow.id)
        assert called == []
        assert workflow.status == StepStatus.FAILED
        assert all(step.status == StepStatus.PENDING for step in workflow.steps)
        assert workflow.audit_records[-1]["reason"] == "branch_namespace_collision"

    def test_unknown_join_branch_blocks_dispatch(self):
        called = []
        workflow = self.manager.create_workflow("parallel")
        workflow.add_branch_step("branch-a", lambda: called.append("a"), "branch-a", "alpha", "join")
        workflow.add_join_step("join", lambda outputs: outputs, "join", ["branch-a", "missing"])

        assert not self.manager.execute_workflow(workflow.id)
        assert called == []
        assert workflow.status == StepStatus.FAILED
        assert workflow.audit_records[-1]["reason"] == "unknown_join_branch"

    def test_valid_branch_outputs_are_namespaced_before_join(self):
        workflow = self.manager.create_workflow("parallel")
        workflow.add_branch_step("branch-a", lambda: {"value": "a"}, "branch-a", "alpha", "join")
        workflow.add_branch_step("branch-b", lambda: {"value": "b"}, "branch-b", "beta", "join")
        workflow.add_join_step("join", lambda outputs: {"seen": sorted(outputs)}, "join", ["branch-a", "branch-b"])

        assert self.manager.execute_workflow(workflow.id)
        assert workflow.status == StepStatus.COMPLETED
        assert workflow.outputs["alpha"] == {"value": "a"}
        assert workflow.outputs["beta"] == {"value": "b"}
        assert workflow.steps[-1].result == {"seen": ["alpha", "beta"]}

    def test_rejection_audit_uses_sanitized_references(self):
        workflow = self.manager.create_workflow("parallel")
        workflow.add_branch_step("branch-secret-a", lambda: 1, "branch-secret-a", "alpha", "join-secret")
        workflow.add_branch_step("branch-secret-b", lambda: 2, "branch-secret-b", "beta", "join-secret")
        workflow.add_join_step("join", lambda outputs: outputs, "join-secret", ["branch-secret-a", "branch-secret-b"])
        workflow.steps[1].output_namespace = "alpha"

        assert not self.manager.execute_workflow(workflow.id)
        audit_text = str(workflow.audit_records[-1])
        assert "branch-secret" not in audit_text
        assert "join-secret" not in audit_text
        assert "alpha" not in audit_text

    def test_plain_linear_workflows_still_execute_without_branch_metadata(self):
        workflow = self.manager.create_workflow("linear")
        workflow.add_step(WorkflowStep("first", lambda: 1))
        workflow.add_step(WorkflowStep("second", lambda: 2))

        assert self.manager.execute_workflow(workflow.id)
        assert [step.result for step in workflow.steps] == [1, 2]
