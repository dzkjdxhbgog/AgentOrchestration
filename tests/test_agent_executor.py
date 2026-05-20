import asyncio

import pytest

from src.agent.executor import AgentExecutor


@pytest.mark.asyncio
async def test_cancelled_execution_stores_terminal_result():
    executor = AgentExecutor()
    handler_started = asyncio.Event()

    async def handler(agent_id, task):
        handler_started.set()
        await asyncio.sleep(60)

    execution_task = asyncio.create_task(
        executor.execute("agent-1", {"id": "task-1"}, handler)
    )
    await handler_started.wait()

    execution_id = next(iter(executor._active_tasks))
    assert executor.cancel(execution_id) is True

    assert await execution_task == execution_id
    assert executor.get_result(execution_id) == {
        "execution_id": execution_id,
        "agent_id": "agent-1",
        "task_id": "task-1",
        "status": "cancelled",
        "timestamp": pytest.approx(executor.get_result(execution_id)["timestamp"]),
    }
    assert execution_id not in executor._active_tasks
