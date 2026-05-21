import pytest
from src.orchestrator.scheduler import TaskScheduler


class TestTaskScheduler:
    def setup_method(self):
        self.scheduler = TaskScheduler(retry_base_delay=0, retry_jitter=0)

    def test_enqueue_task(self):
        task_id = self.scheduler.enqueue({"type": "test", "payload": {}})
        assert task_id is not None

    def test_dequeue_task(self):
        self.scheduler.enqueue({"type": "test", "payload": {"data": 1}})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert task is not None
        assert task["type"] == "test"

    def test_enqueue_multiple_priorities(self):
        self.scheduler.enqueue({"type": "low"}, priority=1)
        self.scheduler.enqueue({"type": "high"}, priority=10)
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert task["type"] == "high"

    def test_complete_task(self):
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.complete(task["id"])

    def test_fail_task_with_retry(self):
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.fail(task["id"])

    def test_transient_failure_retries_same_task_id_with_new_lease(self):
        task_id = self.scheduler.enqueue({"type": "test"})

        import asyncio
        first = asyncio.run(self.scheduler.dequeue())
        first_lease = first["lease_id"]

        assert self.scheduler.fail(task_id, lease_id=first_lease)
        second = asyncio.run(self.scheduler.dequeue())

        assert second["id"] == task_id
        assert second["lease_id"] != first_lease
        assert second["retries"] == 1
        assert second["attempt"] == 2

    def test_stale_lease_cannot_complete_retry_attempt(self):
        task_id = self.scheduler.enqueue({"type": "test"})

        import asyncio
        first = asyncio.run(self.scheduler.dequeue())
        first_lease = first["lease_id"]
        assert self.scheduler.fail(task_id, lease_id=first_lease)

        second = asyncio.run(self.scheduler.dequeue())
        assert not self.scheduler.complete(task_id, lease_id=first_lease)
        assert self.scheduler.get_state(task_id) == "in_flight"

        assert self.scheduler.complete(task_id, lease_id=second["lease_id"], result={"ok": True})
        outcome = self.scheduler.get_terminal_outcome(task_id)
        assert outcome["status"] == "completed"
        assert outcome["result"] == {"ok": True}

    def test_terminal_failure_is_recorded_once(self):
        scheduler = TaskScheduler(max_retries=1, retry_base_delay=0, retry_jitter=0)
        task_id = scheduler.enqueue({"type": "test"})

        import asyncio
        task = asyncio.run(scheduler.dequeue())
        assert scheduler.fail(task_id, lease_id=task["lease_id"], reason="boom")
        assert scheduler.get_state(task_id) == "failed"

        outcome = scheduler.get_terminal_outcome(task_id)
        assert outcome["status"] == "failed"
        assert outcome["reason"] == "boom"
        assert not scheduler.complete(task_id, lease_id=task["lease_id"])

    def test_terminal_completion_is_not_overwritten_by_stale_failure(self):
        task_id = self.scheduler.enqueue({"type": "test"})

        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.complete(task_id, lease_id=task["lease_id"], result={"ok": True})
        assert not self.scheduler.fail(task_id, lease_id=task["lease_id"], reason="late error")

        outcome = self.scheduler.get_terminal_outcome(task_id)
        assert outcome["status"] == "completed"
        assert outcome["result"] == {"ok": True}

    def test_cancelled_task_is_not_dispatched_from_queue(self):
        task_id = self.scheduler.enqueue({"type": "test"})
        assert self.scheduler.cancel(task_id, reason="user cancelled")

        import asyncio
        assert asyncio.run(self.scheduler.dequeue()) is None
        assert self.scheduler.get_terminal_outcome(task_id)["status"] == "cancelled"

# 2019-01-09T19:07:03 update

# 2019-02-18T12:30:02 update

# 2019-04-11T16:04:51 update

# 2019-04-17T16:25:46 update

# 2019-05-24T19:32:13 update

# 2019-07-02T12:54:25 update

# 2019-07-03T20:37:00 update

# 2019-08-21T19:37:17 update

# 2019-10-18T10:30:31 update

# 2019-10-25T09:01:38 update

# 2019-10-29T12:59:34 update

# 2019-11-05T10:07:06 update

# 2019-11-11T10:43:52 update

# 2020-01-17T13:40:02 update

# 2020-02-07T14:06:34 update

# 2020-04-03T08:53:40 update

# 2020-04-06T19:36:29 update

# 2020-05-12T11:51:05 update

# 2020-08-17T08:37:15 update

# 2020-09-15T10:39:38 update

# 2020-10-06T11:26:19 update

# 2020-10-21T13:32:43 update

# 2020-12-14T18:18:36 update

# 2020-12-23T17:15:03 update

# 2021-01-25T16:29:00 update

# 2021-02-23T11:23:50 update

# 2021-03-19T12:21:19 update

# 2021-07-29T18:48:25 update

# 2021-08-25T12:46:58 update

# 2021-09-09T16:27:13 update

# 2021-12-16T12:05:30 update

# 2022-05-07T14:05:12 update

# 2022-07-18T20:52:29 update

# 2022-07-31T18:42:26 update

# 2022-09-09T13:10:08 update

# 2023-01-04T15:16:57 update

# 2023-01-17T14:49:04 update

# 2023-02-15T13:51:30 update

# 2023-03-08T09:15:53 update

# 2023-03-23T16:32:20 update

# 2023-03-28T09:32:01 update

# 2023-05-05T17:28:22 update

# 2023-06-01T08:13:52 update

# 2023-06-20T09:58:10 update

# 2023-07-04T16:14:34 update

# 2023-07-17T20:49:40 update

# 2023-12-26T11:49:18 update

# 2024-05-27T11:00:06 update

# 2024-07-04T08:53:03 update

# 2024-07-18T16:19:02 update

# 2024-08-07T09:35:35 update

# 2024-08-22T14:32:14 update

# 2025-05-20T14:19:23 update

# 2025-07-17T17:54:48 update

# 2025-07-28T13:06:30 update

# 2025-12-22T19:05:25 update

# 2026-01-08T18:43:02 update

# 2026-01-12T16:53:28 update

# 2026-04-16T16:58:23 update
