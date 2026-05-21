"""Healthcheck helpers for scheduler container deployments."""

from __future__ import annotations

import os
import socket
import sys
from dataclasses import dataclass
from typing import Iterable, Optional
from urllib.parse import urlparse


DEFAULT_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True)
class DependencyCheck:
    name: str
    host: str
    port: int


def scheduler_dependency_checks() -> list[DependencyCheck]:
    checks: list[DependencyCheck] = []
    queue_url = os.getenv("SCHEDULER_QUEUE_URL") or os.getenv("REDIS_URL")
    storage_url = os.getenv("SCHEDULER_STORAGE_DSN") or os.getenv("DATABASE_URL")

    queue_check = _check_from_url("queue", queue_url)
    storage_check = _check_from_url("storage", storage_url)

    if queue_check:
        checks.append(queue_check)
    if storage_check:
        checks.append(storage_check)
    return checks


def scheduler_is_healthy(timeout: float = DEFAULT_TIMEOUT_SECONDS) -> tuple[bool, list[str]]:
    checks = scheduler_dependency_checks()
    if not checks:
        return False, ["no scheduler dependency URLs configured"]

    failures: list[str] = []
    for check in checks:
        try:
            with socket.create_connection((check.host, check.port), timeout=timeout):
                pass
        except OSError as exc:
            failures.append(f"{check.name} unavailable at {check.host}:{check.port}: {exc}")

    return not failures, failures


def main(argv: Optional[Iterable[str]] = None) -> int:
    healthy, failures = scheduler_is_healthy()
    if healthy:
        print("scheduler dependencies healthy")
        return 0

    for failure in failures:
        print(failure, file=sys.stderr)
    return 1


def _check_from_url(name: str, url: Optional[str]) -> Optional[DependencyCheck]:
    if not url:
        return None

    parsed = urlparse(url)
    if not parsed.hostname:
        return None

    port = parsed.port or _default_port(parsed.scheme)
    if port is None:
        return None

    return DependencyCheck(name=name, host=parsed.hostname, port=port)


def _default_port(scheme: str) -> Optional[int]:
    defaults = {
        "postgres": 5432,
        "postgresql": 5432,
        "redis": 6379,
        "rediss": 6379,
    }
    return defaults.get(scheme)


if __name__ == "__main__":
    raise SystemExit(main())
