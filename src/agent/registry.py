"""Agent Registry — Manages agent lifecycle and metadata."""

import time
import uuid
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional


class AgentStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    FAILED = "failed"
    TERMINATED = "terminated"


TERMINAL_STATUSES = {
    AgentStatus.STOPPED.value,
    AgentStatus.FAILED.value,
    AgentStatus.TERMINATED.value,
}


class AgentRegistry:
    def __init__(self, storage_backend: str = "memory"):
        self.storage_backend = storage_backend
        self._agents: Dict[str, Dict[str, Any]] = {}
        self._index: Dict[str, List[str]] = {}
        self._capability_aliases: Dict[str, str] = {}
        self._alias_cache: Dict[str, Optional[Dict[str, Any]]] = {}
        self._audit_events: List[Dict[str, Any]] = []

    def register(
        self,
        name: str,
        agent_type: str,
        config: Optional[Dict] = None,
    ) -> str:
        config = config or {}
        aliases = self._extract_aliases(config)
        normalized_aliases = self._normalize_aliases_for_registration(aliases)

        agent_id = str(uuid.uuid4())
        timestamp = time.time()
        self._agents[agent_id] = {
            "id": agent_id,
            "name": name,
            "type": agent_type,
            "status": AgentStatus.PENDING.value,
            "config": config,
            "capability_aliases": list(aliases),
            "created_at": timestamp,
            "updated_at": timestamp,
            "version": "1.0.0",
            "metrics": {"tasks_completed": 0, "errors": 0, "uptime": 0},
        }
        group = agent_type.split(".")[0]
        if group not in self._index:
            self._index[group] = []
        self._index[group].append(agent_id)

        for normalized_alias in normalized_aliases:
            self._capability_aliases[normalized_alias] = agent_id
            self._invalidate_alias_cache(normalized_alias)
        return agent_id

    def get(self, agent_id: str) -> Optional[Dict[str, Any]]:
        return self._agents.get(agent_id)

    def list(
        self,
        status: Optional[AgentStatus] = None,
        group: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        agents = self._agents.values()
        if status:
            agents = [a for a in agents if a["status"] == status.value]
        if group:
            agent_ids = self._index.get(group, [])
            agents = [a for a in agents if a["id"] in agent_ids]
        return list(agents)

    def update_status(self, agent_id: str, status: AgentStatus) -> bool:
        if agent_id not in self._agents:
            return False
        previous_status = self._agents[agent_id]["status"]
        self._agents[agent_id]["status"] = status.value
        self._agents[agent_id]["updated_at"] = time.time()
        self._invalidate_agent_alias_cache(agent_id)
        if (
            status.value in TERMINAL_STATUSES
            and previous_status != status.value
        ):
            self._remove_agent_aliases(agent_id, reason="terminal_status")
        return True

    def delete(self, agent_id: str) -> bool:
        if agent_id not in self._agents:
            return False
        agent = self._agents.pop(agent_id)
        group = agent["type"].split(".")[0]
        if group in self._index and agent_id in self._index[group]:
            self._index[group].remove(agent_id)
        self._remove_agent_aliases(agent_id, reason="delete")
        return True

    def count(self) -> int:
        return len(self._agents)

    def resolve_capability_alias(self, alias: str) -> Optional[Dict[str, Any]]:
        normalized_alias = self._normalize_alias(alias)
        if normalized_alias in self._alias_cache:
            return self._alias_cache[normalized_alias]

        agent_id = self._capability_aliases.get(normalized_alias)
        if not agent_id:
            self._audit_alias_decision(normalized_alias, "miss", None)
            self._alias_cache[normalized_alias] = None
            return None

        agent = self._agents.get(agent_id)
        if agent is None or agent["status"] in TERMINAL_STATUSES:
            self._capability_aliases.pop(normalized_alias, None)
            self._audit_alias_decision(normalized_alias, "stale", agent_id)
            self._alias_cache[normalized_alias] = None
            return None

        self._audit_alias_decision(normalized_alias, "resolved", agent_id)
        self._alias_cache[normalized_alias] = agent
        return agent

    def alias_audit_events(self) -> List[Dict[str, Any]]:
        return list(self._audit_events)

    def _extract_aliases(self, config: Dict[str, Any]) -> List[str]:
        aliases = config.get("capability_aliases", [])
        if aliases is None:
            return []
        if isinstance(aliases, str):
            return [aliases]
        return list(aliases)

    def _normalize_aliases_for_registration(
        self,
        aliases: Iterable[str],
    ) -> List[str]:
        normalized_aliases = [
            self._normalize_alias(alias)
            for alias in aliases
        ]
        duplicates = {
            alias
            for alias in normalized_aliases
            if normalized_aliases.count(alias) > 1
        }
        if duplicates:
            duplicate = sorted(duplicates)[0]
            self._audit_alias_decision(duplicate, "duplicate_in_request", None)
            raise ValueError(f"Duplicate capability alias: {duplicate}")

        for normalized_alias in normalized_aliases:
            if normalized_alias in self._capability_aliases:
                agent_id = self._capability_aliases[normalized_alias]
                agent = self._agents.get(agent_id)
                if agent and agent["status"] not in TERMINAL_STATUSES:
                    self._audit_alias_decision(
                        normalized_alias,
                        "duplicate_active",
                        agent_id,
                    )
                    raise ValueError(
                        f"Capability alias already registered: "
                        f"{normalized_alias}"
                    )
                self._capability_aliases.pop(normalized_alias, None)
                self._invalidate_alias_cache(normalized_alias)

        return normalized_aliases

    def _normalize_alias(self, alias: str) -> str:
        if not isinstance(alias, str):
            raise ValueError("Capability alias must be a string")
        normalized = alias.strip().casefold()
        if not normalized:
            raise ValueError("Capability alias cannot be blank")
        return normalized

    def _remove_agent_aliases(self, agent_id: str, reason: str) -> None:
        aliases = [
            alias
            for alias, mapped_agent_id in self._capability_aliases.items()
            if mapped_agent_id == agent_id
        ]
        for alias in aliases:
            self._capability_aliases.pop(alias, None)
            self._invalidate_alias_cache(alias)
            self._audit_alias_decision(alias, reason, agent_id)

    def _invalidate_agent_alias_cache(self, agent_id: str) -> None:
        for alias, mapped_agent_id in list(self._capability_aliases.items()):
            if mapped_agent_id == agent_id:
                self._invalidate_alias_cache(alias)

    def _invalidate_alias_cache(self, alias: str) -> None:
        self._alias_cache.pop(alias, None)

    def _audit_alias_decision(
        self,
        alias: str,
        decision: str,
        agent_id: Optional[str],
    ) -> None:
        self._audit_events.append({
            "event": "capability_alias",
            "alias": alias,
            "decision": decision,
            "agent_id": agent_id,
            "timestamp": time.time(),
        })

# 2019-01-29T11:24:49 update

# 2019-04-09T13:38:38 update

# 2019-04-11T11:24:12 update

# 2019-06-26T17:03:48 update

# 2019-07-03T14:55:48 update

# 2019-07-18T18:18:47 update

# 2019-11-05T11:27:19 update

# 2019-11-20T11:35:05 update

# 2019-11-23T15:28:54 update

# 2020-03-13T09:23:07 update

# 2020-03-30T19:31:18 update

# 2020-04-22T15:03:30 update

# 2020-07-21T10:00:48 update

# 2020-09-10T09:02:08 update

# 2020-09-10T13:39:12 update

# 2020-09-22T16:27:52 update

# 2020-10-15T10:33:14 update

# 2021-05-13T11:15:56 update

# 2021-07-07T14:57:13 update

# 2021-07-13T15:15:19 update

# 2021-07-27T10:18:16 update

# 2022-03-11T15:24:11 update

# 2022-09-22T13:24:20 update

# 2022-11-01T12:20:40 update

# 2023-01-30T12:32:27 update

# 2023-03-10T09:43:50 update

# 2023-05-10T14:28:01 update

# 2023-05-11T20:04:46 update

# 2023-05-30T17:00:59 update

# 2023-07-13T17:54:32 update

# 2023-07-20T19:04:20 update

# 2023-07-31T17:00:02 update

# 2023-09-05T19:42:07 update

# 2024-01-02T10:29:47 update

# 2024-09-17T12:45:29 update

# 2024-09-17T11:51:01 update

# 2024-11-06T18:20:15 update

# 2025-01-12T15:13:14 update

# 2025-01-14T20:24:39 update

# 2025-03-26T20:21:27 update

# 2025-04-10T18:27:06 update

# 2025-06-19T20:34:58 update

# 2025-06-21T20:23:53 update

# 2025-06-24T20:30:30 update

# 2025-07-03T13:28:03 update

# 2025-07-24T17:42:21 update

# 2025-08-19T17:42:23 update

# 2025-08-21T11:06:52 update

# 2025-10-24T09:10:08 update

# 2025-12-18T19:34:38 update

# 2026-02-06T11:22:22 update

# 2026-02-13T15:42:04 update

# 2026-04-10T08:16:30 update

# 2026-04-29T18:16:11 update
