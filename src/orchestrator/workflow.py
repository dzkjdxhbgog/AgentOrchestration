"""Workflow Manager — Defines and executes multi-step agent workflows."""

import logging
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set
from uuid import uuid4

import yaml

logger = logging.getLogger(__name__)


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowDefinitionError(ValueError):
    """Raised when a workflow definition is unsafe to register."""


class WorkflowStep:
    def __init__(
        self,
        name: str,
        handler: Callable,
        retries: int = 0,
        timeout: int = 300,
        step_id: Optional[str] = None,
    ):
        self.id = step_id or str(uuid4())
        self.name = name
        self.handler = handler
        self.retries = retries
        self.timeout = timeout
        self.status = StepStatus.PENDING
        self.result: Any = None
        self.error: Optional[str] = None


class Workflow:
    def __init__(self, name: str, description: str = ""):
        self.id = str(uuid4())
        self.name = name
        self.description = description
        self.steps: List[WorkflowStep] = []
        self._step_map: Dict[str, WorkflowStep] = {}
        self.status = StepStatus.PENDING

    def add_step(self, step: WorkflowStep) -> "Workflow":
        if step.id in self._step_map:
            logger.warning("Rejected duplicate workflow step id: %s", step.id)
            raise WorkflowDefinitionError(f"Duplicate workflow step id: {step.id}")
        self.steps.append(step)
        self._step_map[step.id] = step
        return self

    def get_step(self, step_id: str) -> Optional[WorkflowStep]:
        return self._step_map.get(step_id)


class WorkflowManager:
    def __init__(self):
        self._workflows: Dict[str, Workflow] = {}

    def create_workflow(self, name: str, description: str = "") -> Workflow:
        workflow = Workflow(name, description)
        self._workflows[workflow.id] = workflow
        return workflow

    def load_workflow_from_yaml(
        self,
        path: str,
        handlers: Optional[Dict[str, Callable]] = None,
    ) -> Workflow:
        workflow_path = Path(path)
        definition = yaml.safe_load(workflow_path.read_text()) or {}
        return self.register_workflow_definition(definition, handlers, workflow_path.parent)

    def register_workflow_definition(
        self,
        definition: Dict[str, Any],
        handlers: Optional[Dict[str, Callable]] = None,
        base_path: Optional[Path] = None,
    ) -> Workflow:
        nodes = self.validate_workflow_definition(definition, base_path)
        workflow = Workflow(
            str(definition.get("name", "workflow")),
            str(definition.get("description", "")),
        )

        for node in nodes:
            node_id = str(node.get("id") or node.get("name"))
            handler = self._resolve_handler(node, handlers)
            workflow.add_step(
                WorkflowStep(
                    name=str(node.get("name") or node_id),
                    handler=handler,
                    retries=int(node.get("retries", 0)),
                    timeout=int(node.get("timeout", 300)),
                    step_id=node_id,
                )
            )

        self._workflows[workflow.id] = workflow
        return workflow

    def validate_workflow_definition(
        self,
        definition: Dict[str, Any],
        base_path: Optional[Path] = None,
    ) -> List[Dict[str, Any]]:
        nodes = list(self._collect_nodes(definition, base_path, set()))
        seen: Set[str] = set()
        workflow_name = str(definition.get("name", "workflow"))

        for node in nodes:
            node_id = node.get("id") or node.get("name")
            if not node_id:
                logger.warning("Rejected workflow definition with unnamed node")
                raise WorkflowDefinitionError("Workflow node requires an id or name")

            node_id = str(node_id)
            if node_id in seen:
                logger.warning(
                    "Rejected workflow definition %s with duplicate node id: %s",
                    workflow_name,
                    node_id,
                )
                raise WorkflowDefinitionError(f"Duplicate workflow node id: {node_id}")
            seen.add(node_id)

        return nodes

    def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        return self._workflows.get(workflow_id)

    def list_workflows(self) -> List[Workflow]:
        return list(self._workflows.values())

    def delete_workflow(self, workflow_id: str) -> bool:
        return self._workflows.pop(workflow_id, None) is not None

    def execute_workflow(self, workflow_id: str) -> bool:
        workflow = self._workflows.get(workflow_id)
        if not workflow:
            return False

        workflow.status = StepStatus.RUNNING
        for step in workflow.steps:
            step.status = StepStatus.RUNNING
            try:
                result = step.handler()
                step.result = result
                step.status = StepStatus.COMPLETED
            except Exception as e:
                step.error = str(e)
                step.status = StepStatus.FAILED
                workflow.status = StepStatus.FAILED
                return False

        workflow.status = StepStatus.COMPLETED
        return True

    def _collect_nodes(
        self,
        definition: Dict[str, Any],
        base_path: Optional[Path],
        imported_paths: Set[Path],
    ) -> Iterable[Dict[str, Any]]:
        if not isinstance(definition, dict):
            raise WorkflowDefinitionError("Workflow definition must be a mapping")

        imports = definition.get("imports", []) or []
        if not isinstance(imports, list):
            raise WorkflowDefinitionError("Workflow imports must be a list")

        for imported in imports:
            if isinstance(imported, dict):
                yield from self._collect_nodes(imported, base_path, imported_paths)
                continue

            if not isinstance(imported, str):
                raise WorkflowDefinitionError("Workflow import must be a path or mapping")

            import_path = Path(imported)
            if not import_path.is_absolute() and base_path is not None:
                import_path = base_path / import_path
            import_path = import_path.resolve()

            if import_path in imported_paths:
                logger.warning("Rejected cyclic workflow import: %s", import_path.name)
                raise WorkflowDefinitionError(f"Cyclic workflow import: {import_path.name}")

            next_paths = set(imported_paths)
            next_paths.add(import_path)
            imported_definition = yaml.safe_load(import_path.read_text()) or {}
            yield from self._collect_nodes(imported_definition, import_path.parent, next_paths)

        nodes = definition.get("nodes", definition.get("steps", [])) or []
        if not isinstance(nodes, list):
            raise WorkflowDefinitionError("Workflow nodes must be a list")

        for node in nodes:
            if not isinstance(node, dict):
                raise WorkflowDefinitionError("Workflow node must be a mapping")
            yield node

    def _resolve_handler(
        self,
        node: Dict[str, Any],
        handlers: Optional[Dict[str, Callable]],
    ) -> Callable:
        handler_ref = node.get("handler") or node.get("name") or node.get("id")
        if callable(handler_ref):
            return handler_ref
        if handlers and handler_ref in handlers:
            return handlers[handler_ref]
        return self._noop_handler

    @staticmethod
    def _noop_handler() -> None:
        return None

# 2019-03-27T19:58:07 update

# 2019-05-09T09:42:56 update

# 2019-12-03T10:07:42 update

# 2020-01-16T18:43:28 update

# 2020-03-20T10:40:15 update

# 2020-04-17T15:36:50 update

# 2020-05-04T14:44:01 update

# 2020-06-16T13:17:31 update

# 2020-08-05T17:00:24 update

# 2020-09-04T08:29:23 update

# 2020-09-09T17:52:02 update

# 2020-10-23T10:57:44 update

# 2020-12-05T20:55:47 update

# 2021-01-15T19:23:40 update

# 2021-02-03T20:43:12 update

# 2021-03-16T12:26:47 update

# 2021-04-20T14:33:28 update

# 2021-10-14T15:03:32 update

# 2021-10-21T17:24:55 update

# 2021-11-16T17:01:08 update

# 2021-11-22T09:51:21 update

# 2021-12-21T16:15:47 update

# 2022-03-23T16:52:27 update

# 2022-12-21T09:25:50 update

# 2023-01-09T09:55:25 update

# 2023-01-13T11:06:15 update

# 2023-01-26T11:00:59 update

# 2023-02-23T08:56:54 update

# 2023-05-17T08:07:16 update

# 2023-06-06T17:09:34 update

# 2023-06-13T10:35:28 update

# 2023-08-24T20:36:06 update

# 2023-10-30T19:10:13 update

# 2024-01-02T08:27:25 update

# 2024-01-24T12:13:15 update

# 2024-02-08T13:35:49 update

# 2024-05-07T16:09:24 update

# 2024-05-11T09:48:46 update

# 2024-05-21T19:25:41 update

# 2024-06-05T12:00:30 update

# 2024-06-25T09:40:26 update

# 2024-09-17T13:49:39 update

# 2024-10-14T17:39:35 update

# 2024-11-27T20:14:35 update

# 2024-12-25T19:31:41 update

# 2025-01-16T13:15:09 update

# 2025-02-05T14:06:59 update

# 2025-02-17T20:55:11 update

# 2025-04-30T19:36:53 update

# 2025-07-17T10:14:40 update

# 2025-08-29T12:13:15 update

# 2025-09-03T13:51:11 update

# 2025-09-19T16:08:24 update

# 2025-11-27T08:38:12 update

# 2026-01-27T13:23:38 update

# 2026-01-28T11:22:50 update
