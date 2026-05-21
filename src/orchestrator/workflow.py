"""Workflow Manager — Defines and executes multi-step agent workflows."""

import logging
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    COMPENSATING = "compensating"
    BLOCKED = "blocked"
    ROLLBACK_FAILED = "rollback_failed"
    ROLLED_BACK = "rolled_back"


class WorkflowStep:
    def __init__(
        self,
        name: str,
        handler: Callable,
        retries: int = 0,
        timeout: int = 300,
        compensation_handler: Optional[Callable] = None,
    ):
        self.id = str(uuid4())
        self.name = name
        self.handler = handler
        self.compensation_handler = compensation_handler
        self.retries = retries
        self.timeout = timeout
        self.status = StepStatus.PENDING
        self.result: Any = None
        self.error: Optional[str] = None
        self.rollback_error: Optional[str] = None
        self.blocked_reason: Optional[str] = None


class Workflow:
    def __init__(self, name: str, description: str = ""):
        self.id = str(uuid4())
        self.name = name
        self.description = description
        self.steps: List[WorkflowStep] = []
        self._step_map: Dict[str, WorkflowStep] = {}
        self.status = StepStatus.PENDING
        self.rollback_state = "none"
        self.blocked_reason: Optional[str] = None
        self.audit_records: List[Dict[str, Any]] = []

    def add_step(self, step: WorkflowStep) -> "Workflow":
        if self.blocked_reason:
            raise ValueError(
                "cannot add steps after workflow dispatch is blocked"
            )
        self.steps.append(step)
        self._step_map[step.id] = step
        return self

    def get_step(self, step_id: str) -> Optional[WorkflowStep]:
        return self._step_map.get(step_id)

    def audit(
        self,
        event: str,
        step: WorkflowStep,
        decision: str,
        reason: str,
    ) -> None:
        self.audit_records.append(
            {
                "event": event,
                "step_id": step.id,
                "step_name": step.name,
                "decision": decision,
                "reason": reason,
            }
        )


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

    def dispatch_step(self, workflow_id: str, step_id: str) -> bool:
        workflow = self._workflows.get(workflow_id)
        if not workflow:
            return False

        step = workflow.get_step(step_id)
        if step is None or not self._can_dispatch(workflow, step):
            return False

        step.status = StepStatus.RUNNING
        try:
            step.result = step.handler()
            step.status = StepStatus.COMPLETED
            return True
        except Exception as e:
            step.error = str(e)
            step.status = StepStatus.FAILED
            workflow.status = StepStatus.FAILED
            if not self._compensate_step(workflow, step):
                workflow.rollback_state = "partial"
                self._block_pending_downstream(
                    workflow,
                    step,
                    "partial_rollback",
                )
            else:
                workflow.rollback_state = "rolled_back"
                self._block_pending_downstream(
                    workflow,
                    step,
                    "failed_step",
                )
            return False

    def execute_workflow(self, workflow_id: str) -> bool:
        workflow = self._workflows.get(workflow_id)
        if not workflow:
            return False
        if workflow.rollback_state == "partial":
            return False

        workflow.status = StepStatus.RUNNING
        completed_steps: List[WorkflowStep] = []
        for step in workflow.steps:
            if not self._can_dispatch(workflow, step):
                workflow.status = StepStatus.FAILED
                return False

            step.status = StepStatus.RUNNING
            try:
                result = step.handler()
                step.result = result
                step.status = StepStatus.COMPLETED
                completed_steps.append(step)
            except Exception as e:
                step.error = str(e)
                step.status = StepStatus.FAILED
                workflow.status = StepStatus.FAILED
                completed_rollback = self._compensate_completed_steps(
                    workflow,
                    completed_steps,
                )
                failed_step_rollback = self._compensate_step(workflow, step)
                if not completed_rollback or not failed_step_rollback:
                    workflow.rollback_state = "partial"
                    self._block_pending_downstream(
                        workflow,
                        step,
                        "partial_rollback",
                    )
                else:
                    workflow.rollback_state = "rolled_back"
                    self._block_pending_downstream(
                        workflow,
                        step,
                        "failed_step",
                    )
                return False

        workflow.status = StepStatus.COMPLETED
        return True

    def _can_dispatch(self, workflow: Workflow, step: WorkflowStep) -> bool:
        reason = workflow.blocked_reason or step.blocked_reason
        if reason:
            if step.status is StepStatus.PENDING:
                step.status = StepStatus.BLOCKED
            step.blocked_reason = reason
            workflow.audit(
                "workflow_dispatch_blocked",
                step,
                "blocked",
                reason,
            )
            return False

        if step.status is not StepStatus.PENDING:
            workflow.audit(
                "workflow_dispatch_blocked",
                step,
                "blocked",
                "non_pending_state",
            )
            return False

        return True

    def _compensate_completed_steps(
        self,
        workflow: Workflow,
        completed_steps: List[WorkflowStep],
    ) -> bool:
        rollback_complete = True
        for step in reversed(completed_steps):
            if step.compensation_handler is None:
                continue
            if not self._compensate_step(workflow, step):
                rollback_complete = False
                break
        return rollback_complete

    def _compensate_step(self, workflow: Workflow, step: WorkflowStep) -> bool:
        if step.compensation_handler is None:
            workflow.audit(
                "workflow_compensation",
                step,
                "not_configured",
                "no_compensation_handler",
            )
            return False

        step.status = StepStatus.COMPENSATING
        try:
            result = step.compensation_handler()
        except Exception as exc:
            step.rollback_error = str(exc)
            step.status = StepStatus.ROLLBACK_FAILED
            workflow.audit(
                "workflow_compensation",
                step,
                "partial_rollback",
                "compensation_failed",
            )
            logger.exception(
                "Workflow compensation failed for step %s",
                step.name,
            )
            return False

        if result is False:
            step.status = StepStatus.ROLLBACK_FAILED
            workflow.audit(
                "workflow_compensation",
                step,
                "partial_rollback",
                "compensation_incomplete",
            )
            logger.warning(
                "Workflow compensation incomplete for step %s",
                step.name,
            )
            return False

        step.status = StepStatus.ROLLED_BACK
        workflow.audit(
            "workflow_compensation",
            step,
            "rolled_back",
            "compensation_completed",
        )
        return True

    def _block_pending_downstream(
        self,
        workflow: Workflow,
        failed_step: WorkflowStep,
        reason: str,
    ) -> None:
        workflow.blocked_reason = reason
        block = False
        for step in workflow.steps:
            if step is failed_step:
                block = True
                continue
            if not block or step.status is not StepStatus.PENDING:
                continue
            step.status = StepStatus.BLOCKED
            step.blocked_reason = reason
            workflow.audit(
                "workflow_downstream_blocked",
                step,
                "blocked",
                reason,
            )
            logger.warning(
                "Blocked downstream workflow step %s: %s",
                step.name,
                reason,
            )

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
