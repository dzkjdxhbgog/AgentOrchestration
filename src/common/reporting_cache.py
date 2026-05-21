"""Authorization-aware report result caching."""

from __future__ import annotations

import copy
import hashlib
import json
import time
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Callable, Dict, FrozenSet, Mapping, Optional, Tuple


@dataclass(frozen=True)
class ReportAuthContext:
    user_id: str
    workspace_id: str
    roles: FrozenSet[str] = field(default_factory=frozenset)
    scopes: FrozenSet[str] = field(default_factory=frozenset)
    access_version: int = 0

    @classmethod
    def from_values(
        cls,
        user_id: str,
        workspace_id: str,
        roles: Optional[Tuple[str, ...]] = None,
        scopes: Optional[Tuple[str, ...]] = None,
        access_version: int = 0,
    ) -> "ReportAuthContext":
        return cls(
            user_id=user_id,
            workspace_id=workspace_id,
            roles=frozenset(roles or ()),
            scopes=frozenset(scopes or ()),
            access_version=access_version,
        )

    def fingerprint(self) -> str:
        payload = {
            "user_id": self.user_id,
            "workspace_id": self.workspace_id,
            "roles": sorted(self.roles),
            "scopes": sorted(self.scopes),
            "access_version": self.access_version,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass
class ReportCacheEntry:
    value: Any
    auth_context: ReportAuthContext
    created_at: float


AccessValidator = Callable[[ReportAuthContext], bool]


class ReportResultCache:
    """Caches report results without reusing stale authorization state."""

    def __init__(
        self,
        access_validator: Optional[AccessValidator] = None,
    ):
        self._entries: Dict[Tuple[str, str, str], ReportCacheEntry] = {}
        self._access_validator = access_validator
        self._lock = RLock()

    def set(
        self,
        report_id: str,
        query_params: Mapping[str, Any],
        auth_context: ReportAuthContext,
        value: Any,
    ) -> None:
        key = self._cache_key(report_id, query_params, auth_context)
        with self._lock:
            self._entries[key] = ReportCacheEntry(
                value=copy.deepcopy(value),
                auth_context=auth_context,
                created_at=time.time(),
            )

    def get(
        self,
        report_id: str,
        query_params: Mapping[str, Any],
        auth_context: ReportAuthContext,
    ) -> Optional[Any]:
        key = self._cache_key(report_id, query_params, auth_context)
        with self._lock:
            entry = self._entries.get(key)
            if not entry:
                return None
            if entry.auth_context != auth_context:
                self._entries.pop(key, None)
                return None
            if not self._is_authorized(auth_context):
                self._entries.pop(key, None)
                return None
            return copy.deepcopy(entry.value)

    def invalidate_workspace(self, workspace_id: str) -> int:
        with self._lock:
            keys = [
                key
                for key, entry in self._entries.items()
                if entry.auth_context.workspace_id == workspace_id
            ]
            for key in keys:
                self._entries.pop(key, None)
            return len(keys)

    def invalidate_user(self, user_id: str) -> int:
        with self._lock:
            keys = [
                key
                for key, entry in self._entries.items()
                if entry.auth_context.user_id == user_id
            ]
            for key in keys:
                self._entries.pop(key, None)
            return len(keys)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def _is_authorized(self, auth_context: ReportAuthContext) -> bool:
        if self._access_validator is None:
            return True
        return self._access_validator(auth_context)

    def _cache_key(
        self,
        report_id: str,
        query_params: Mapping[str, Any],
        auth_context: ReportAuthContext,
    ) -> Tuple[str, str, str]:
        return (
            report_id,
            self._stable_query_key(query_params),
            auth_context.fingerprint(),
        )

    def _stable_query_key(self, query_params: Mapping[str, Any]) -> str:
        encoded = json.dumps(query_params, sort_keys=True, default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
