"""Human approval service helpers."""

from enum import Enum
from typing import Any, Dict, Optional


class ApprovalRunState(Enum):
    WAITING_FOR_HUMAN = "waiting_for_human"
    APPROVED = "approved"
    REJECTED = "rejected"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ApprovalError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class HumanApprovalService:
    def __init__(self):
        self._run_states: Dict[str, ApprovalRunState] = {}
        self._runs: Dict[str, Dict[str, Any]] = {}
        self.protected_lookup_count = 0
        self.mutation_count = 0

    def reset(self):
        self._run_states.clear()
        self._runs.clear()
        self.protected_lookup_count = 0
        self.mutation_count = 0

    def register_run(
        self,
        run_id: str,
        state: ApprovalRunState = ApprovalRunState.WAITING_FOR_HUMAN,
        steps: Optional[Dict[str, Dict[str, Any]]] = None,
    ):
        self._run_states[run_id] = state
        self._runs[run_id] = {"id": run_id, "steps": steps or {}}

    def approve_human_step(
        self,
        run_id: str,
        step_id: str,
        approved: bool,
        actor: Optional[str] = None,
    ) -> Dict[str, Any]:
        run_id = self._validate_identifier(run_id, "run_id")
        step_id = self._validate_identifier(step_id, "step_id")

        state = self._run_states.get(run_id)
        if state is None:
            raise ApprovalError(404, "Run not found")
        if state != ApprovalRunState.WAITING_FOR_HUMAN:
            raise ApprovalError(409, "Run is not waiting for human approval")

        run = self._get_run_for_mutation(run_id)
        steps = run.setdefault("steps", {})
        if step_id not in steps:
            raise ApprovalError(404, "Human step not found")

        self.mutation_count += 1
        step = steps[step_id]
        step["approved"] = approved
        step["approved_by"] = actor or "api"
        self._run_states[run_id] = (
            ApprovalRunState.APPROVED if approved else ApprovalRunState.REJECTED
        )
        return {
            "run_id": run_id,
            "step_id": step_id,
            "approved": approved,
            "state": self._run_states[run_id].value,
        }

    def _get_run_for_mutation(self, run_id: str) -> Dict[str, Any]:
        self.protected_lookup_count += 1
        run = self._runs.get(run_id)
        if run is None:
            raise ApprovalError(404, "Run not found")
        return run

    @staticmethod
    def _validate_identifier(value: str, field_name: str) -> str:
        if not value or not value.strip():
            raise ApprovalError(422, f"{field_name} must be a non-empty string")
        return value.strip()


approval_service = HumanApprovalService()
