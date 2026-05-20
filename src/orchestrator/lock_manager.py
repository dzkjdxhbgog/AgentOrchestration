"""Advisory lock guard for runtime state transitions."""

import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional, TypeVar

from src.common.metrics import metrics


T = TypeVar("T")


class LockAcquireError(RuntimeError):
    """Raised when a guarded transition cannot acquire its advisory lock."""


@dataclass
class AdvisoryLock:
    key: str
    owner: str
    attempt: int
    acquired_at: float


@dataclass
class TerminalOutcome:
    key: str
    status: str
    owner: str
    detail: Optional[str]
    result: Optional[Any]
    attempts: int
    recorded_at: float


class AdvisoryLockManager:
    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries
        self._locks: Dict[str, AdvisoryLock] = {}
        self._attempts: Dict[str, int] = {}
        self._outcomes: Dict[str, TerminalOutcome] = {}

    def acquire(self, key: str, owner: str) -> AdvisoryLock:
        if key in self._outcomes:
            raise LockAcquireError(f"{key} already has a terminal outcome")
        if key in self._locks:
            lock_owner = self._locks[key].owner
            raise LockAcquireError(f"{key} is locked by {lock_owner}")

        attempt = self._attempts.get(key, 0) + 1
        self._attempts[key] = attempt
        if attempt > self.max_retries:
            self.record_terminal(
                key,
                "failed",
                owner,
                "retry_limit_exceeded",
            )
            raise LockAcquireError(f"{key} exceeded retry limit")

        lock = AdvisoryLock(
            key=key,
            owner=owner,
            attempt=attempt,
            acquired_at=time.time(),
        )
        self._locks[key] = lock
        metrics.increment("runtime.advisory_lock.acquired")
        return lock

    def release(self, key: str, owner: Optional[str] = None) -> bool:
        lock = self._locks.get(key)
        if not lock:
            return False
        if owner is not None and lock.owner != owner:
            return False
        self._locks.pop(key, None)
        metrics.increment("runtime.advisory_lock.released")
        return True

    def record_terminal(
        self,
        key: str,
        status: str,
        owner: str,
        detail: Optional[str] = None,
        result: Optional[Any] = None,
    ) -> TerminalOutcome:
        existing = self._outcomes.get(key)
        if existing:
            return existing

        outcome = TerminalOutcome(
            key=key,
            status=status,
            owner=owner,
            detail=detail,
            result=result,
            attempts=self._attempts.get(key, 0),
            recorded_at=time.time(),
        )
        self._outcomes[key] = outcome
        metrics.increment(f"runtime.terminal_outcome.{status}")
        return outcome

    async def run_guarded(
        self,
        key: str,
        owner: str,
        transition: Callable[[], Awaitable[T]],
    ) -> T:
        self.acquire(key, owner)
        try:
            result = await transition()
            self.record_terminal(key, "completed", owner, result=result)
            return result
        except Exception as exc:
            self.record_terminal(key, "failed", owner, detail=str(exc))
            raise
        finally:
            self.release(key, owner)

    def is_locked(self, key: str) -> bool:
        return key in self._locks

    def get_outcome(self, key: str) -> Optional[TerminalOutcome]:
        return self._outcomes.get(key)
