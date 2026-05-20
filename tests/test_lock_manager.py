import pytest

from src.orchestrator.lock_manager import AdvisoryLockManager, LockAcquireError


async def fail_transition():
    raise RuntimeError("worker crashed while holding lock")


async def complete_transition():
    return {"ok": True}


@pytest.mark.asyncio
async def test_advisory_lock_released_and_terminal_outcome_on_exception():
    manager = AdvisoryLockManager()

    with pytest.raises(RuntimeError, match="worker crashed"):
        await manager.run_guarded("run-1", "worker-1", fail_transition)

    assert not manager.is_locked("run-1")
    outcome = manager.get_outcome("run-1")
    assert outcome is not None
    assert outcome.status == "failed"
    assert outcome.detail == "worker crashed while holding lock"
    assert outcome.attempts == 1


@pytest.mark.asyncio
async def test_terminal_outcome_is_durable_and_blocks_duplicate_retry():
    manager = AdvisoryLockManager()

    result = await manager.run_guarded(
        "run-2",
        "worker-1",
        complete_transition,
    )

    assert result == {"ok": True}
    assert not manager.is_locked("run-2")
    outcome = manager.get_outcome("run-2")
    assert outcome.status == "completed"
    assert outcome.result == {"ok": True}

    with pytest.raises(LockAcquireError, match="terminal outcome"):
        await manager.run_guarded("run-2", "worker-2", complete_transition)

    assert manager.get_outcome("run-2") is outcome


def test_retry_limit_records_terminal_failure_and_leaves_no_lock():
    manager = AdvisoryLockManager(max_retries=1)
    manager.acquire("run-3", "worker-1")
    assert manager.release("run-3", "worker-1")

    with pytest.raises(LockAcquireError, match="retry limit"):
        manager.acquire("run-3", "worker-1")

    assert not manager.is_locked("run-3")
    outcome = manager.get_outcome("run-3")
    assert outcome.status == "failed"
    assert outcome.detail == "retry_limit_exceeded"
