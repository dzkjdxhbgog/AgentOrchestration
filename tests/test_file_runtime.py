import asyncio

import pytest

from src.agent.executor import AgentExecutor
from src.agent.file_runtime import RunFileRuntime, RunFileRuntimeError


def test_file_runtime_persists_outcome_before_cleanup(tmp_path):
    runtime = RunFileRuntime(str(tmp_path))

    runtime.begin("exec-1", "agent-1", "task-1")
    outcome = runtime.finalize(
        "exec-1",
        "agent-1",
        "task-1",
        "completed",
        result={"ok": True},
    )

    assert outcome["status"] == "completed"
    assert runtime.get_outcome("exec-1")["result"] == {"ok": True}
    assert not runtime.has_run_files("exec-1")
    assert not runtime.has_stale_lock("exec-1")


def test_file_runtime_finalize_is_idempotent(tmp_path):
    runtime = RunFileRuntime(str(tmp_path))

    runtime.begin("exec-2", "agent-1", "task-1")
    first = runtime.finalize("exec-2", "agent-1", "task-1", "failed", error="boom")
    second = runtime.finalize("exec-2", "agent-1", "task-1", "completed")

    assert second == first
    assert runtime.get_outcome("exec-2")["status"] == "failed"
    assert runtime.get_outcome("exec-2")["error"] == "boom"
    assert not runtime.has_stale_lock("exec-2")


def test_file_runtime_rejects_unbounded_retry_entry(tmp_path):
    runtime = RunFileRuntime(str(tmp_path))

    with pytest.raises(RunFileRuntimeError):
        runtime.begin("exec-3", "agent-1", "task-1", attempt=3, max_retries=3)

    outcome = runtime.get_outcome("exec-3")
    assert outcome["status"] == "failed"
    assert outcome["attempt"] == 3
    assert not runtime.has_run_files("exec-3")


def test_executor_records_failure_outcome_and_cleans_temp_files(tmp_path):
    runtime = RunFileRuntime(str(tmp_path))
    executor = AgentExecutor(file_runtime=runtime)

    async def failing_handler(agent_id, task):
        raise ValueError("handler failed")

    with pytest.raises(ValueError):
        asyncio.run(
            executor._run_execution(
                "exec-4",
                "agent-1",
                {"id": "task-1"},
                failing_handler,
            )
        )

    outcome = runtime.get_outcome("exec-4")
    assert outcome["status"] == "failed"
    assert outcome["error"] == "handler failed"
    assert not runtime.has_run_files("exec-4")


def test_executor_records_cancellation_outcome_and_cleans_temp_files(tmp_path):
    runtime = RunFileRuntime(str(tmp_path))
    executor = AgentExecutor(file_runtime=runtime)

    async def slow_handler(agent_id, task):
        await asyncio.sleep(10)

    async def run_and_cancel():
        task = asyncio.create_task(
            executor._run_execution(
                "exec-5",
                "agent-1",
                {"id": "task-1"},
                slow_handler,
            )
        )
        await asyncio.sleep(0)
        task.cancel()
        await task

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_and_cancel())

    outcome = runtime.get_outcome("exec-5")
    assert outcome["status"] == "cancelled"
    assert outcome["error"] == "execution cancelled"
    assert not runtime.has_run_files("exec-5")


def test_executor_does_not_dispatch_side_effects_for_terminal_outcome(tmp_path):
    runtime = RunFileRuntime(str(tmp_path))
    executor = AgentExecutor(file_runtime=runtime)
    runtime.finalize(
        "exec-6",
        "agent-1",
        "task-1",
        "completed",
        result={"cached": True},
    )

    async def handler(agent_id, task):
        raise AssertionError("handler should not run for a terminal outcome")

    result = asyncio.run(
        executor._run_execution(
            "exec-6",
            "agent-1",
            {"id": "task-1"},
            handler,
        )
    )

    assert result == {"cached": True}
    assert runtime.get_outcome("exec-6")["status"] == "completed"
    assert not runtime.has_stale_lock("exec-6")
