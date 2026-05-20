"""Authentication and authorization helpers for API dependencies."""

from dataclasses import dataclass
from typing import FrozenSet

from fastapi import HTTPException, Request


AUTHORIZED_TEMPLATE_CLONE_ROLES = frozenset({"admin", "owner", "operator"})
REVOKED_CREDENTIAL_STATES = frozenset({"revoked", "stale", "expired"})
TEMPLATE_CLONE_SCOPES = frozenset({"template:clone", "templates:write", "*"})


@dataclass(frozen=True)
class Principal:
    subject: str
    workspace_id: str
    role: str
    source: str
    scopes: FrozenSet[str]


def _split_scopes(raw_scopes: str) -> FrozenSet[str]:
    scopes = raw_scopes.replace(",", " ").split()
    return frozenset(scope.strip().lower() for scope in scopes if scope.strip())


class PermissionService:
    def principal_for_request(self, request: Request) -> Principal:
        credential_state = request.headers.get("x-credential-state", "active").lower()
        if credential_state in REVOKED_CREDENTIAL_STATES:
            raise HTTPException(status_code=401, detail="Credential is no longer active")

        workspace_id = request.headers.get("x-workspace-id", "").strip()
        role = request.headers.get("x-role", "").strip().lower()
        subject = request.headers.get("x-user-id", "").strip()

        auth_header = request.headers.get("authorization", "")
        token = auth_header.removeprefix("Bearer ").strip() if auth_header.startswith("Bearer ") else ""
        session_id = request.headers.get("x-session-id", "").strip() or request.cookies.get("ao_session", "")

        if token:
            source = "token"
            subject = subject or token
            scopes = _split_scopes(request.headers.get("x-token-scopes", ""))
        elif session_id:
            source = "browser"
            subject = subject or session_id
            scopes = _split_scopes(request.headers.get("x-session-scopes", "template:clone"))
        else:
            raise HTTPException(status_code=401, detail="Authentication required")

        if not workspace_id or not role:
            raise HTTPException(status_code=401, detail="Workspace and role are required")

        return Principal(
            subject=subject,
            workspace_id=workspace_id,
            role=role,
            source=source,
            scopes=scopes,
        )

    def require_template_clone(self, request: Request) -> Principal:
        principal = self.principal_for_request(request)
        if principal.role not in AUTHORIZED_TEMPLATE_CLONE_ROLES:
            raise HTTPException(status_code=403, detail="Insufficient workspace role")
        if principal.source == "token" and not (principal.scopes & TEMPLATE_CLONE_SCOPES):
            raise HTTPException(status_code=403, detail="Insufficient token scope")
        return principal


permission_service = PermissionService()


def require_template_clone_principal(request: Request) -> Principal:
    return permission_service.require_template_clone(request)
