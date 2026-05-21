"""Authentication helpers for API route guards."""

import os
from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, Optional, Set

from fastapi import HTTPException, Request


DOCS_READ_SCOPE = "docs:read"
WORKSPACE_READER_ROLE = "workspace:reader"


@dataclass(frozen=True)
class Principal:
    token: str
    scopes: Set[str]
    roles: Set[str]
    revoked: bool = False
    fresh: bool = True


class AuthService:
    def __init__(self, tokens: Optional[Mapping[str, Mapping]] = None):
        configured_tokens = tokens or self._tokens_from_env()
        self._tokens = {
            token: self._principal_from_mapping(token, data)
            for token, data in configured_tokens.items()
            if token
        }

    def authenticate_request(self, request: Request) -> Principal:
        token = self._token_from_request(request)
        principal = self._tokens.get(token)
        if principal is None:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        if principal.revoked:
            raise HTTPException(status_code=401, detail="Revoked credentials")
        if not principal.fresh:
            raise HTTPException(status_code=401, detail="Stale credentials")
        return principal

    def require_docs_access(self, request: Request) -> Principal:
        principal = self.authenticate_request(request)
        if DOCS_READ_SCOPE not in principal.scopes:
            raise HTTPException(status_code=403, detail="Missing docs scope")
        if WORKSPACE_READER_ROLE not in principal.roles:
            raise HTTPException(
                status_code=403,
                detail="Missing workspace role",
            )
        return principal

    def _token_from_request(self, request: Request) -> str:
        authorization = request.headers.get("Authorization")
        if authorization:
            prefix = "Bearer "
            if not authorization.startswith(prefix):
                raise HTTPException(
                    status_code=401,
                    detail="Malformed bearer token",
                )
            token = authorization[len(prefix):].strip()
            if not token:
                raise HTTPException(
                    status_code=401,
                    detail="Missing bearer token",
                )
            return token

        session_token = request.cookies.get("ao_session")
        if session_token:
            return session_token.strip()

        raise HTTPException(status_code=401, detail="Authentication required")

    def _principal_from_mapping(self, token: str, data: Mapping) -> Principal:
        return Principal(
            token=token,
            scopes=set(self._iter_values(data.get("scopes", []))),
            roles=set(self._iter_values(data.get("roles", []))),
            revoked=bool(data.get("revoked", False)),
            fresh=bool(data.get("fresh", True)),
        )

    def _tokens_from_env(self) -> Dict[str, Mapping]:
        token = os.getenv("AO_DOCS_TOKEN", "").strip()
        if not token:
            return {}
        return {
            token: {
                "scopes": [DOCS_READ_SCOPE],
                "roles": [WORKSPACE_READER_ROLE],
            },
        }

    def _iter_values(self, values: Iterable[str]) -> Iterable[str]:
        if isinstance(values, str):
            return [values]
        return values


async def require_docs_access(request: Request) -> Principal:
    auth_service = getattr(request.app.state, "auth_service", AuthService())
    return auth_service.require_docs_access(request)
