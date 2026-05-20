import asyncio

from src.orchestrator.engine import OrchestrationEngine


def test_execute_task_persists_terminal_outcome_before_completion_hooks():
    engine = OrchestrationEngine()
    agent_id = engine.registry.register("test-agent", "worker.processor")
    task_id = engine.scheduler.enqueue({"type": "test", "target_agent": agent_id})
    task = asyncio.run(engine.scheduler.dequeue())
    observed = []

    async def post_execute(task, result):
        observed.append(
            (
                "post_execute",
                engine.scheduler.get_terminal_outcome(task["id"]) is not None,
                engine.scheduler.is_in_flight(task["id"]),
            )
        )

    async def on_complete(task, result):
        observed.append(
            (
                "on_complete",
                engine.scheduler.get_terminal_outcome(task["id"]) is not None,
                engine.scheduler.is_in_flight(task["id"]),
            )
        )

    try:
        engine.register_hook("post_execute", post_execute)
        engine.register_hook("on_complete", on_complete)

        asyncio.run(engine._execute_task(task))
    finally:
        engine.executor.shutdown(wait=True)

    outcome = engine.scheduler.get_terminal_outcome(task_id)
    assert outcome["state"] == "completed"
    assert observed == [
        ("post_execute", True, False),
        ("on_complete", True, False),
    ]
