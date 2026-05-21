"""Workflow Manager — Defines and executes multi-step agent workflows."""

import logging
from enum import Enum
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Union
from uuid import uuid4

from src.common.metrics import metrics


logger = logging.getLogger(__name__)
TIMEOUT_UNITS = {
    "timeout": 1,
    "timeout_seconds": 1,
    "timeout_minutes": 60,
    "timeout_ms": 0.001,
    "timeout_milliseconds": 0.001,
}


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowDefinitionError(ValueError):
    def __init__(self, message: str, reason: str, fields: Optional[List[str]] = None):
        super().__init__(message)
        self.reason = reason
        self.fields = fields or []


def parse_timeout_seconds(definition: Union[int, float, Dict[str, Any]]) -> float:
    if isinstance(definition, bool):
        raise WorkflowDefinitionError("Timeout must be numeric", "invalid_timeout_type")
    if isinstance(definition, (int, float)):
        return _validate_timeout_value(definition)
    if not isinstance(definition, dict):
        raise WorkflowDefinitionError("Timeout definition must be a number or object", "invalid_timeout_type")

    fields = [field for field in TIMEOUT_UNITS if definition.get(field) is not None]
    if not fields:
        return 300
    if len(fields) > 1:
        raise WorkflowDefinitionError(
            "Workflow step defines conflicting timeout units",
            "conflicting_timeout_units",
            fields,
        )

    field = fields[0]
    return _validate_timeout_value(definition[field]) * TIMEOUT_UNITS[field]


def _validate_timeout_value(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WorkflowDefinitionError("Timeout must be numeric", "invalid_timeout_type")
    if value < 0:
        raise WorkflowDefinitionError("Timeout cannot be negative", "negative_timeout")
    return float(value)


class WorkflowStep:
    def __init__(self, name: str, handler: Callable, retries: int = 0, timeout: Union[int, float, Dict[str, Any]] = 300):
        self.id = str(uuid4())
        self.name = name
        self.handler = handler
        self.retries = retries
        self.timeout = parse_timeout_seconds(timeout)
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
        self.audit_records: List[Dict[str, str]] = []

    def add_step(self, step: WorkflowStep) -> "Workflow":
        self.steps.append(step)
        self._step_map[step.id] = step
        return self

    def get_step(self, step_id: str) -> Optional[WorkflowStep]:
        return self._step_map.get(step_id)


class WorkflowManager:
    def __init__(self):
        self._workflows: Dict[str, Workflow] = {}
        self.audit_records: List[Dict[str, str]] = []
        self.validation_metrics: Dict[str, int] = defaultdict(int)

    def create_workflow(self, name: str, description: str = "") -> Workflow:
        workflow = Workflow(name, description)
        self._workflows[workflow.id] = workflow
        return workflow

    def create_workflow_from_definition(self, definition: Dict[str, Any]) -> Workflow:
        try:
            workflow = self._parse_workflow_definition(definition)
        except WorkflowDefinitionError as exc:
            self._record_definition_rejection(exc)
            raise

        self._workflows[workflow.id] = workflow
        return workflow

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

    def _parse_workflow_definition(self, definition: Dict[str, Any]) -> Workflow:
        if not isinstance(definition, dict):
            raise WorkflowDefinitionError("Workflow definition must be an object", "invalid_definition")

        workflow = Workflow(definition.get("name", "workflow"), definition.get("description", ""))
        for index, step_definition in enumerate(definition.get("steps", [])):
            if not isinstance(step_definition, dict):
                raise WorkflowDefinitionError("Workflow step definition must be an object", "invalid_step")
            handler = step_definition.get("handler")
            if not callable(handler):
                raise WorkflowDefinitionError("Workflow step handler must be callable", "invalid_handler")
            try:
                step = WorkflowStep(
                    step_definition.get("name", f"step-{index}"),
                    handler,
                    retries=step_definition.get("retries", 0),
                    timeout=step_definition,
                )
            except WorkflowDefinitionError as exc:
                exc.fields = exc.fields or ["timeout"]
                raise
            workflow.add_step(step)
        return workflow

    def _record_definition_rejection(self, exc: WorkflowDefinitionError) -> None:
        event = {
            "event": "workflow_definition_rejected",
            "reason": exc.reason,
            "fields": ",".join(exc.fields),
        }
        self.audit_records.append(event)
        self.validation_metrics[exc.reason] += 1
        metrics.increment(f"workflow.definition.rejected.{exc.reason}")
        logger.warning("workflow definition rejected: %s", exc.reason)

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
