"""Task Scheduler — Priority-based task queuing and dispatch."""

import asyncio
import heapq
import random
import time
from typing import Any, Dict, Optional
from uuid import uuid4


class PriorityQueue:
    def __init__(self):
        self._queue = []
        self._counter = 0

    def push(self, item: Any, priority: int = 0) -> None:
        heapq.heappush(self._queue, (-priority, self._counter, item))
        self._counter += 1

    def pop(self) -> Optional[Any]:
        if self._queue:
            return heapq.heappop(self._queue)[2]
        return None

    def peek(self) -> Optional[Any]:
        if self._queue:
            return self._queue[0][2]
        return None

    def __len__(self) -> int:
        return len(self._queue)


class TaskScheduler:
    _TERMINAL_STATES = {"completed", "failed", "cancelled"}

    def __init__(
        self,
        max_retries: int = 3,
        retry_base_delay: float = 0.1,
        retry_jitter: float = 0.05,
    ):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, Dict] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._states: Dict[str, str] = {}
        self._terminal_outcomes: Dict[str, Dict] = {}
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._retry_jitter = retry_jitter

    def enqueue(self, task: Dict, queue: str = "default", priority: int = 0) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task["retries"] = 0
        task["priority"] = priority
        task["queue"] = queue
        task.pop("lease_id", None)

        self._states[task_id] = "queued"
        self._push_queue(task, queue, priority)
        return task_id

    def _push_queue(self, task: Dict, queue: str, priority: int) -> bool:
        task_id = task["id"]
        if self._states.get(task_id) in self._TERMINAL_STATES:
            return False
        task["queue"] = queue
        task["priority"] = priority
        task["enqueued_at"] = time.time()
        self._states[task_id] = "queued"
        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)
        return True

    def schedule(self, task: Dict, delay: float, queue: str = "default", priority: int = 0) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        task["retries"] = 0
        task["priority"] = priority
        task["queue"] = queue
        task.pop("lease_id", None)
        self._states[task_id] = "scheduled"
        self._scheduled[task_id] = {
            "run_at": time.time() + delay,
            "task": task,
            "queue": queue,
            "priority": priority,
        }
        return task_id

    async def dequeue(self, queue: str = "default", timeout: float = 1.0) -> Optional[Dict]:
        now = time.time()
        expired = [tid for tid, entry in self._scheduled.items() if entry["run_at"] <= now]
        for tid in expired:
            entry = self._scheduled.pop(tid)
            if self._states.get(tid) not in self._TERMINAL_STATES:
                self._push_queue(entry["task"], entry["queue"], entry["priority"])

        if queue in self._queues and len(self._queues[queue]) > 0:
            while len(self._queues[queue]) > 0:
                task = self._queues[queue].pop()
                if not task:
                    continue
                task_id = task["id"]
                if self._states.get(task_id) != "queued":
                    continue
                lease_id = str(uuid4())
                task["lease_id"] = lease_id
                task["attempt"] = task.get("retries", 0) + 1
                self._states[task_id] = "in_flight"
                self._in_flight[task_id] = task
                return task
        return None

    def complete(self, task_id: str, lease_id: Optional[str] = None, result: Any = None) -> bool:
        if task_id in self._terminal_outcomes:
            return self._terminal_outcomes[task_id]["status"] == "completed"

        task = self._in_flight.get(task_id)
        if not task or not self._lease_matches(task, lease_id):
            return False

        outcome = {
            "status": "completed",
            "completed_at": time.time(),
            "result": result,
            "attempt": task.get("attempt", 1),
        }
        self._terminal_outcomes[task_id] = outcome
        self._states[task_id] = "completed"
        self._in_flight.pop(task_id, None)
        return True

    def fail(
        self,
        task_id: str,
        queue: str = "default",
        transient: bool = True,
        lease_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> bool:
        if task_id in self._terminal_outcomes:
            return self._terminal_outcomes[task_id]["status"] == "failed"

        task = self._in_flight.get(task_id)
        if not task or not self._lease_matches(task, lease_id):
            return False

        next_retry = task.get("retries", 0) + 1
        task["retries"] = next_retry

        if transient and next_retry < self._max_retries:
            retry_queue = task.get("queue", queue)
            priority = task.get("priority", 0)
            task.pop("lease_id", None)
            self._states[task_id] = "retry_scheduled"
            self._scheduled[task_id] = {
                "run_at": time.time() + self._retry_delay(next_retry),
                "task": task,
                "queue": retry_queue,
                "priority": priority,
            }
            self._in_flight.pop(task_id, None)
            return True

        outcome = {
            "status": "failed",
            "failed_at": time.time(),
            "reason": reason,
            "attempt": task.get("attempt", next_retry),
            "retries": next_retry,
        }
        self._terminal_outcomes[task_id] = outcome
        self._states[task_id] = "failed"
        self._in_flight.pop(task_id, None)
        return True

    def cancel(self, task_id: str, reason: Optional[str] = None, lease_id: Optional[str] = None) -> bool:
        if task_id in self._terminal_outcomes:
            return self._terminal_outcomes[task_id]["status"] == "cancelled"

        task = self._in_flight.get(task_id)
        if task and not self._lease_matches(task, lease_id):
            return False

        self._terminal_outcomes[task_id] = {
            "status": "cancelled",
            "cancelled_at": time.time(),
            "reason": reason,
        }
        self._states[task_id] = "cancelled"
        self._in_flight.pop(task_id, None)
        self._scheduled.pop(task_id, None)
        return True

    def get_state(self, task_id: str) -> Optional[str]:
        return self._states.get(task_id)

    def get_terminal_outcome(self, task_id: str) -> Optional[Dict]:
        return self._terminal_outcomes.get(task_id)

    def _retry_delay(self, retry_number: int) -> float:
        base_delay = self._retry_base_delay * (2 ** max(retry_number - 1, 0))
        jitter = random.uniform(0, self._retry_jitter) if self._retry_jitter > 0 else 0
        return base_delay + jitter

    def _lease_matches(self, task: Dict, lease_id: Optional[str]) -> bool:
        return lease_id is None or task.get("lease_id") == lease_id

# 2019-04-25T08:37:12 update

# 2019-06-04T16:40:00 update

# 2019-07-11T12:01:28 update

# 2019-08-02T12:20:21 update

# 2019-08-23T10:38:50 update

# 2019-10-31T13:55:52 update

# 2019-11-04T20:12:32 update

# 2019-12-13T12:22:36 update

# 2020-02-01T10:32:37 update

# 2020-02-26T09:44:38 update

# 2020-03-09T19:00:55 update

# 2020-05-01T18:40:34 update

# 2020-05-12T15:10:31 update

# 2020-06-30T13:24:19 update

# 2020-09-22T16:00:45 update

# 2020-10-20T10:52:48 update

# 2020-10-21T12:18:08 update

# 2020-11-06T12:35:01 update

# 2020-12-09T08:09:33 update

# 2021-01-07T08:20:36 update

# 2021-10-02T15:23:16 update

# 2021-10-06T16:14:57 update

# 2021-10-06T09:27:41 update

# 2021-11-19T08:37:40 update

# 2022-03-01T16:39:54 update

# 2022-05-26T13:43:07 update

# 2022-06-02T10:50:58 update

# 2022-06-14T10:46:48 update

# 2022-07-31T16:44:34 update

# 2022-08-30T18:20:12 update

# 2022-11-04T14:47:03 update

# 2022-12-06T10:36:49 update

# 2022-12-22T13:21:12 update

# 2022-12-26T12:24:50 update

# 2023-03-09T08:09:55 update

# 2023-05-01T10:07:37 update

# 2023-06-08T14:32:15 update

# 2023-07-14T17:24:18 update

# 2023-12-14T08:38:31 update

# 2024-02-20T13:43:58 update

# 2024-03-24T08:52:42 update

# 2024-03-28T15:27:17 update

# 2024-03-29T18:10:33 update

# 2024-04-15T20:18:31 update

# 2024-05-27T13:11:52 update

# 2024-05-27T16:42:56 update

# 2024-06-20T13:03:45 update

# 2024-06-28T12:32:58 update

# 2024-07-10T14:10:16 update

# 2024-07-26T14:18:59 update

# 2024-08-12T08:21:05 update

# 2024-08-21T16:58:40 update

# 2024-09-27T19:54:30 update

# 2024-10-21T13:47:42 update

# 2024-11-11T09:19:27 update

# 2024-12-24T08:23:41 update

# 2025-02-14T10:35:15 update

# 2025-03-31T18:09:40 update

# 2025-06-21T17:32:49 update

# 2025-07-21T16:52:28 update

# 2025-08-20T19:45:16 update

# 2025-11-04T18:54:24 update

# 2025-12-09T20:17:36 update

# 2026-01-12T15:42:32 update

# 2026-01-23T14:41:20 update

# 2026-03-18T14:43:07 update

# 2026-04-13T11:43:19 update
