"""Authentication helpers for API and worker-to-worker calls."""

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional


AGENT_WORKER_AUDIENCE = "agent-workers"


class AuthenticationError(Exception):
    """Raised when credentials are absent, stale, revoked, or malformed."""


class AuthorizationError(Exception):
    """Raised when valid credentials lack the required permissions."""


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))


@dataclass(frozen=True)
class Principal:
    subject: str
    audience: List[str]
    scopes: List[str]
    workspace_roles: Dict[str, List[str]]
    expires_at: int
    token_id: str

    def has_audience(self, expected: str) -> bool:
        return expected in self.audience

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes

    def has_workspace_role(
        self,
        workspace_id: str,
        allowed_roles: Iterable[str],
    ) -> bool:
        roles = set(self.workspace_roles.get(workspace_id, []))
        roles.update(self.workspace_roles.get("*", []))
        return bool(roles.intersection(set(allowed_roles)))


class AuthService:
    def __init__(
        self,
        secret: Optional[str] = None,
        issuer: str = "agent-orchestration",
    ):
        self.secret = secret or os.getenv(
            "AO_AUTH_SECRET",
            "dev-agent-orchestration-secret",
        )
        self.issuer = issuer
        self._revoked_token_ids = set()
        self._sessions: Dict[str, Principal] = {}

    def issue_token(
        self,
        subject: str,
        audience: Iterable[str],
        scopes: Iterable[str],
        workspace_roles: Dict[str, Iterable[str]],
        ttl_seconds: int = 300,
        token_id: Optional[str] = None,
    ) -> str:
        now = int(time.time())
        jti = token_id or hashlib.sha256(
            f"{subject}:{now}:{time.time_ns()}".encode("utf-8")
        ).hexdigest()
        payload = {
            "sub": subject,
            "aud": list(audience),
            "scope": " ".join(scopes),
            "workspace_roles": {
                key: list(value)
                for key, value in workspace_roles.items()
            },
            "iat": now,
            "exp": now + ttl_seconds,
            "iss": self.issuer,
            "jti": jti,
        }
        header = {"alg": "HS256", "typ": "JWT"}
        signing_input = ".".join(
            [
                _b64encode(
                    json.dumps(header, separators=(",", ":")).encode("utf-8")
                ),
                _b64encode(
                    json.dumps(payload, separators=(",", ":")).encode("utf-8")
                ),
            ]
        )
        signature = hmac.new(
            self.secret.encode("utf-8"),
            signing_input.encode("ascii"),
            hashlib.sha256,
        ).digest()
        return f"{signing_input}.{_b64encode(signature)}"

    def revoke_token(self, token_id: str) -> None:
        self._revoked_token_ids.add(token_id)

    def register_session(
        self,
        session_id: str,
        principal: Principal,
    ) -> None:
        self._sessions[session_id] = principal

    def clear_sessions(self) -> None:
        self._sessions.clear()

    def reset(self) -> None:
        self._revoked_token_ids.clear()
        self._sessions.clear()

    def authenticate_bearer(self, token: str) -> Principal:
        parts = token.split(".")
        if len(parts) != 3:
            raise AuthenticationError("Malformed bearer token")

        signing_input = ".".join(parts[:2])
        expected = hmac.new(
            self.secret.encode("utf-8"),
            signing_input.encode("ascii"),
            hashlib.sha256,
        ).digest()
        try:
            provided = _b64decode(parts[2])
            header = json.loads(_b64decode(parts[0]).decode("utf-8"))
            payload = json.loads(_b64decode(parts[1]).decode("utf-8"))
        except (ValueError, json.JSONDecodeError) as exc:
            raise AuthenticationError("Malformed bearer token") from exc

        if not hmac.compare_digest(provided, expected):
            raise AuthenticationError("Invalid bearer token signature")
        if header.get("alg") != "HS256":
            raise AuthenticationError("Unsupported bearer token algorithm")
        if payload.get("iss") != self.issuer:
            raise AuthenticationError("Invalid bearer token issuer")

        return self._principal_from_payload(payload)

    def authenticate_session(self, session_id: str) -> Principal:
        principal = self._sessions.get(session_id)
        if principal is None:
            raise AuthenticationError("Unknown session")
        self._validate_principal(principal)
        return principal

    def authorize_agent_worker(
        self,
        principal: Principal,
        workspace_id: str,
        required_scope: str,
    ) -> None:
        self._validate_principal(principal)
        if not principal.has_audience(AGENT_WORKER_AUDIENCE):
            raise AuthorizationError("Invalid token audience")
        if not principal.has_scope(required_scope):
            raise AuthorizationError("Insufficient token scope")
        if not principal.has_workspace_role(
            workspace_id,
            {"worker", "operator", "admin"},
        ):
            raise AuthorizationError("Insufficient workspace role")

    def _principal_from_payload(self, payload: Dict[str, Any]) -> Principal:
        token_id = payload.get("jti")
        subject = payload.get("sub")
        expires_at = payload.get("exp")
        if not token_id or not subject or not isinstance(expires_at, int):
            raise AuthenticationError("Bearer token missing required claims")

        audience = payload.get("aud", [])
        if isinstance(audience, str):
            audience = [audience]
        if not isinstance(audience, list):
            raise AuthenticationError("Bearer token audience is invalid")

        scope_claim = payload.get("scope", "")
        scopes = scope_claim.split() if isinstance(scope_claim, str) else []
        workspace_roles = payload.get("workspace_roles", {})
        if not isinstance(workspace_roles, dict):
            raise AuthenticationError("Bearer token roles are invalid")

        principal = Principal(
            subject=subject,
            audience=[str(item) for item in audience],
            scopes=[str(item) for item in scopes],
            workspace_roles={
                str(key): [str(role) for role in value]
                for key, value in workspace_roles.items()
                if isinstance(value, list)
            },
            expires_at=expires_at,
            token_id=token_id,
        )
        self._validate_principal(principal)
        return principal

    def _validate_principal(self, principal: Principal) -> None:
        if principal.token_id in self._revoked_token_ids:
            raise AuthenticationError("Credentials have been revoked")
        if principal.expires_at <= int(time.time()):
            raise AuthenticationError("Credentials are stale")


auth_service = AuthService()
