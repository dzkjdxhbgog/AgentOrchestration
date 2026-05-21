import logging

import pytest

from src.orchestrator.workflow import WorkflowDefinitionError, WorkflowManager


class TestWorkflowDefinitions:
    def test_yaml_imports_reject_duplicate_node_ids(self, tmp_path, caplog):
        imported = tmp_path / "shared.yml"
        imported.write_text(
            """
nodes:
  - id: build
    handler: build
""".strip()
        )
        root = tmp_path / "workflow.yml"
        root.write_text(
            """
name: release
imports:
  - shared.yml
nodes:
  - id: build
    handler: publish
""".strip()
        )

        manager = WorkflowManager()

        with caplog.at_level(logging.WARNING), pytest.raises(WorkflowDefinitionError, match="Duplicate workflow node id: build"):
            manager.load_workflow_from_yaml(str(root))

        assert manager.list_workflows() == []
        assert "duplicate node id: build" in caplog.text

    def test_yaml_imports_register_unique_nodes_before_execution(self, tmp_path):
        imported = tmp_path / "shared.yml"
        imported.write_text(
            """
nodes:
  - id: build
    handler: build
""".strip()
        )
        root = tmp_path / "workflow.yml"
        root.write_text(
            """
name: release
imports:
  - shared.yml
nodes:
  - id: publish
    handler: publish
""".strip()
        )
        calls = []

        manager = WorkflowManager()
        workflow = manager.load_workflow_from_yaml(
            str(root),
            handlers={
                "build": lambda: calls.append("build"),
                "publish": lambda: calls.append("publish"),
            },
        )

        assert [step.id for step in workflow.steps] == ["build", "publish"]
        assert manager.execute_workflow(workflow.id)
        assert calls == ["build", "publish"]
