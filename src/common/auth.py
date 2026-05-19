"""Authorization helpers for operator-scoped actions."""

from dataclasses import dataclass, field
import time
from typing import Optional, Set


RUN_CANCEL_SCOPE = "runs:cancel"
ADMIN_ROLE = "admin"
OPERATOR_ROLE = "operator"


class PermissionDenied(Exception):
    """Raised when an authenticated principal cannot perform an action."""


@dataclass(frozen=True)
class OperatorPrincipal:
    subject: str
    workspace_id: str
    role: str
    scopes: Set[str] = field(default_factory=set)
    expires_at: Optional[float] = None
    revoked: bool = False


class AuthorizationService:
    def require_run_cancellation(
        self,
        principal: Optional[OperatorPrincipal],
        *,
        workspace_id: str,
        now: Optional[float] = None,
    ) -> None:
        if principal is None:
            raise PermissionDenied("anonymous principals cannot cancel runs")

        if principal.revoked:
            raise PermissionDenied("revoked operator token")

        current_time = time.time() if now is None else now
        if principal.expires_at is not None and principal.expires_at <= current_time:
            raise PermissionDenied("stale operator token")

        if principal.workspace_id != workspace_id:
            raise PermissionDenied("operator token is scoped to a different workspace")

        if principal.role not in {OPERATOR_ROLE, ADMIN_ROLE}:
            raise PermissionDenied("operator role required to cancel runs")

        if "*" not in principal.scopes and RUN_CANCEL_SCOPE not in principal.scopes:
            raise PermissionDenied("runs:cancel scope required")
