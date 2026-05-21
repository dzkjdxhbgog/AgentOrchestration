"""Central authorization checks for protected API routes."""

import time
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Set, Tuple

from starlette.requests import Request


@dataclass(frozen=True)
class Principal:
    subject: str
    workspace_id: str
    scopes: Set[str]
    roles: Set[str]
    expires_at: float
    revoked: bool = False

    def is_fresh(self, now: Optional[float] = None) -> bool:
        return not self.revoked and self.expires_at > (now or time.time())


@dataclass(frozen=True)
class AuthorizationResult:
    allowed: bool
    status_code: int
    reason: str
    principal: Optional[Principal] = None


class PermissionService:
    """Validates token and browser-session credentials before routing."""

    SESSION_COOKIE = "ao_session"

    def __init__(self, principals: Optional[Dict[str, Principal]] = None):
        self._principals = principals or self._default_principals()

    def authorize(self, request: Request) -> AuthorizationResult:
        required_scope, required_role = self.required_access(
            request.method,
            request.url.path,
        )
        if required_scope is None:
            return AuthorizationResult(True, 200, "public")

        credential = self._credential_from_request(request)
        if not credential:
            return AuthorizationResult(False, 401, "anonymous")

        principal = self._principals.get(credential)
        if principal is None:
            return AuthorizationResult(False, 401, "malformed_or_unknown")
        if not principal.is_fresh():
            return AuthorizationResult(False, 401, "stale_or_revoked")
        if required_scope not in principal.scopes:
            return AuthorizationResult(
                False,
                403,
                "insufficient_scope",
                principal,
            )
        if required_role not in principal.roles:
            return AuthorizationResult(
                False,
                403,
                "insufficient_role",
                principal,
            )

        return AuthorizationResult(True, 200, "authorized", principal)

    def required_access(
        self,
        method: str,
        path: str,
    ) -> Tuple[Optional[str], Optional[str]]:
        normalized = self._normalize_path(path)
        if not normalized.startswith("/api/v2"):
            return None, None
        if normalized == "/api/v2/auth/token":
            return None, None

        read_methods = {"GET", "HEAD", "OPTIONS"}
        scope = (
            "agents:read"
            if method.upper() in read_methods
            else "agents:write"
        )
        return scope, "workspace:member"

    def _credential_from_request(self, request: Request) -> Optional[str]:
        authorization = request.headers.get("Authorization", "")
        if authorization.startswith("Bearer "):
            token = authorization[len("Bearer "):].strip()
            return token or None
        return request.cookies.get(self.SESSION_COOKIE)

    def _normalize_path(self, path: str) -> str:
        if path != "/" and path.endswith("/"):
            return path.rstrip("/")
        return path

    def _default_principals(self) -> Dict[str, Principal]:
        future = time.time() + 3600
        expired = time.time() - 3600
        return {
            "valid-token": self._principal(
                "token-user",
                future,
                scopes=("agents:read", "agents:write"),
            ),
            "read-token": self._principal(
                "read-user",
                future,
                scopes=("agents:read",),
            ),
            "stale-token": self._principal(
                "stale-user",
                expired,
                scopes=("agents:read", "agents:write"),
            ),
            "revoked-token": self._principal(
                "revoked-user",
                future,
                scopes=("agents:read", "agents:write"),
                revoked=True,
            ),
            "no-role-token": self._principal(
                "roleless-user",
                future,
                scopes=("agents:read", "agents:write"),
                roles=(),
            ),
            "valid-session": self._principal(
                "browser-user",
                future,
                scopes=("agents:read", "agents:write"),
            ),
            "stale-session": self._principal(
                "stale-browser-user",
                expired,
                scopes=("agents:read", "agents:write"),
            ),
            "revoked-session": self._principal(
                "revoked-browser-user",
                future,
                scopes=("agents:read", "agents:write"),
                revoked=True,
            ),
        }

    def _principal(
        self,
        subject: str,
        expires_at: float,
        scopes: Iterable[str],
        roles: Iterable[str] = ("workspace:member",),
        revoked: bool = False,
    ) -> Principal:
        return Principal(
            subject=subject,
            workspace_id="default",
            scopes=set(scopes),
            roles=set(roles),
            expires_at=expires_at,
            revoked=revoked,
        )
