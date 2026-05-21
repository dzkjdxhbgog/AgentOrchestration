"""Workflow Manager — Defines and executes multi-step agent workflows."""

import hashlib
import inspect
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from src.common.metrics import metrics


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class BranchOutputNamespaceError(ValueError):
    pass


class WorkflowStep:
    def __init__(
        self,
        name: str,
        handler: Callable,
        retries: int = 0,
        timeout: int = 300,
        branch_id: Optional[str] = None,
        output_namespace: Optional[str] = None,
        join_id: Optional[str] = None,
        join_sources: Optional[List[str]] = None,
    ):
        self.id = str(uuid4())
        self.name = name
        self.handler = handler
        self.retries = retries
        self.timeout = timeout
        self.branch_id = branch_id
        self.output_namespace = output_namespace
        self.join_id = join_id
        self.join_sources = join_sources or []
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
        self.outputs: Dict[str, Any] = {}
        self.audit_records: List[Dict[str, Any]] = []

    def add_step(self, step: WorkflowStep) -> "Workflow":
        self._validate_new_step(step)
        self.steps.append(step)
        self._step_map[step.id] = step
        return self

    def add_branch_step(
        self,
        name: str,
        handler: Callable,
        branch_id: str,
        output_namespace: str,
        join_id: str,
        retries: int = 0,
        timeout: int = 300,
    ) -> "Workflow":
        return self.add_step(
            WorkflowStep(
                name,
                handler,
                retries=retries,
                timeout=timeout,
                branch_id=branch_id,
                output_namespace=output_namespace,
                join_id=join_id,
            )
        )

    def add_join_step(
        self,
        name: str,
        handler: Callable,
        join_id: str,
        branch_ids: List[str],
        retries: int = 0,
        timeout: int = 300,
    ) -> "Workflow":
        return self.add_step(
            WorkflowStep(
                name,
                handler,
                retries=retries,
                timeout=timeout,
                join_id=join_id,
                join_sources=branch_ids,
            )
        )

    def get_step(self, step_id: str) -> Optional[WorkflowStep]:
        return self._step_map.get(step_id)

    def validate_graph(self) -> bool:
        branch_groups: Dict[str, List[WorkflowStep]] = {}
        branch_ids: Dict[str, WorkflowStep] = {}
        joins: Dict[str, List[WorkflowStep]] = {}

        for step in self.steps:
            if step.branch_id or step.output_namespace:
                if not self._is_valid_branch_step(step):
                    self._record_audit("reject", "missing_branch_namespace_metadata", step)
                    return False
                step.output_namespace = self._normalize_namespace(step.output_namespace)
                branch_groups.setdefault(step.join_id, []).append(step)
                branch_ids[step.branch_id] = step
            if step.join_sources:
                joins.setdefault(step.join_id, []).append(step)

        for join_id, branch_steps in branch_groups.items():
            for index, left in enumerate(branch_steps):
                for right in branch_steps[index + 1:]:
                    if self._namespaces_conflict(left.output_namespace, right.output_namespace):
                        self._record_audit("reject", "branch_namespace_collision", left, join_id)
                        return False
            if join_id not in joins:
                self._record_audit("reject", "missing_join_for_branch_outputs", branch_steps[0], join_id)
                return False

        for join_id, join_steps in joins.items():
            for step in join_steps:
                if not join_id or not step.join_sources:
                    self._record_audit("reject", "invalid_join_binding", step, join_id)
                    return False
                for branch_id in step.join_sources:
                    branch = branch_ids.get(branch_id)
                    if not branch or branch.join_id != join_id:
                        self._record_audit("reject", "unknown_join_branch", step, join_id)
                        return False
        return True

    def _validate_new_step(self, step: WorkflowStep) -> None:
        if not (step.branch_id or step.output_namespace):
            return
        if not self._is_valid_branch_step(step):
            raise BranchOutputNamespaceError("branch output steps require branch_id, join_id, and output_namespace")

        step.output_namespace = self._normalize_namespace(step.output_namespace)
        for existing in self.steps:
            if existing.join_id != step.join_id or not existing.output_namespace:
                continue
            existing_namespace = self._normalize_namespace(existing.output_namespace)
            if self._namespaces_conflict(existing_namespace, step.output_namespace):
                raise BranchOutputNamespaceError(
                    f"branch output namespace collision for join '{step.join_id}'"
                )

    def _is_valid_branch_step(self, step: WorkflowStep) -> bool:
        return bool(step.branch_id and step.join_id and step.output_namespace)

    def _normalize_namespace(self, namespace: Optional[str]) -> str:
        if not isinstance(namespace, str):
            raise BranchOutputNamespaceError("output namespace must be a string")
        normalized = ".".join(part.strip() for part in namespace.strip().split(".") if part.strip())
        if not normalized:
            raise BranchOutputNamespaceError("output namespace cannot be empty")
        return normalized

    def _namespaces_conflict(self, left: str, right: str) -> bool:
        return left == right or left.startswith(f"{right}.") or right.startswith(f"{left}.")

    def _record_audit(
        self,
        decision: str,
        reason: str,
        step: Optional[WorkflowStep] = None,
        join_id: Optional[str] = None,
    ) -> None:
        metrics.increment(f"workflow.branch_outputs.{decision}.{reason}")
        self.audit_records.append(
            {
                "decision": decision,
                "reason": reason,
                "workflow_ref": self._safe_ref(self.id),
                "step_ref": self._safe_ref(step.id) if step else None,
                "join_ref": self._safe_ref(join_id or getattr(step, "join_id", None)),
                "namespace_ref": self._safe_ref(getattr(step, "output_namespace", None)),
            }
        )

    def _safe_ref(self, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]

    def _branch_namespace(self, branch_id: str) -> Optional[str]:
        for step in self.steps:
            if step.branch_id == branch_id:
                return step.output_namespace
        return None


class WorkflowManager:
    def __init__(self):
        self._workflows: Dict[str, Workflow] = {}

    def create_workflow(self, name: str, description: str = "") -> Workflow:
        workflow = Workflow(name, description)
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

        if not workflow.validate_graph():
            workflow.status = StepStatus.FAILED
            return False

        workflow.status = StepStatus.RUNNING
        for step in workflow.steps:
            step.status = StepStatus.RUNNING
            try:
                if step.join_sources:
                    result = self._run_join_step(workflow, step)
                else:
                    result = step.handler()
                step.result = result
                if step.output_namespace:
                    workflow.outputs[step.output_namespace] = result
                step.status = StepStatus.COMPLETED
            except Exception as e:
                step.error = str(e)
                step.status = StepStatus.FAILED
                workflow.status = StepStatus.FAILED
                return False

        workflow.status = StepStatus.COMPLETED
        return True

    def _run_join_step(self, workflow: Workflow, step: WorkflowStep) -> Any:
        branch_outputs = {}
        for branch_id in step.join_sources:
            namespace = workflow._branch_namespace(branch_id)
            if namespace in workflow.outputs:
                branch_outputs[namespace] = workflow.outputs[namespace]

        try:
            signature = inspect.signature(step.handler)
        except (TypeError, ValueError):
            return step.handler(branch_outputs)

        accepts_payload = any(
            parameter.kind in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.VAR_POSITIONAL,
            )
            for parameter in signature.parameters.values()
        )
        if accepts_payload:
            return step.handler(branch_outputs)
        return step.handler()

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
