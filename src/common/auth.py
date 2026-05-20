"""Authentication and authorization helpers."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Iterable, Set


@dataclass(frozen=True)
class Principal:
    subject: str
    workspace_id: str
    roles: Set[str] = field(default_factory=set)
    scopes: Set[str] = field(default_factory=set)
    disabled: bool = False
    revoked: bool = False
    expires_at: float | None = None

    @property
    def is_anonymous(self) -> bool:
        return not self.subject or self.subject == "anonymous"


class AuthorizationError(Exception):
    """Raised when a principal cannot perform a protected action."""


def _normalise(values: Iterable[str]) -> Set[str]:
    return {value.strip().lower() for value in values if value.strip()}


def require_webhook_management(
    principal: Principal,
    workspace_id: str,
    *,
    now: float | None = None,
) -> None:
    """Require a fresh workspace operator/admin principal for webhook changes."""

    current_time = time.time() if now is None else now

    if principal.is_anonymous:
        raise AuthorizationError("anonymous principals cannot manage webhooks")
    if principal.revoked:
        raise AuthorizationError("revoked principals cannot manage webhooks")
    if principal.disabled:
        raise AuthorizationError("disabled principals cannot manage webhooks")
    if principal.expires_at is not None and principal.expires_at <= current_time:
        raise AuthorizationError("expired principals cannot manage webhooks")
    if principal.workspace_id != workspace_id:
        raise AuthorizationError("principal is not authorized for this workspace")

    roles = _normalise(principal.roles)
    scopes = _normalise(principal.scopes)

    if not ({"operator", "admin"} & roles):
        raise AuthorizationError("webhook management requires operator or admin role")
    if "webhooks:manage" not in scopes:
        raise AuthorizationError("webhook management requires webhooks:manage scope")
