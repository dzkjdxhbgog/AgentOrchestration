"""Task Scheduler — Priority-based task queuing and dispatch."""

import asyncio
import heapq
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union
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
    def __init__(self):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, float] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._acknowledged: Dict[Tuple[str, Optional[str], str], Dict] = {}
        self._max_retries = 3

    def enqueue(self, task: Dict, queue: str = "default", priority: int = 0) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task["retries"] = 0
        task["queue"] = queue
        task["priority"] = priority
        task.pop("claimed_by", None)
        task.pop("claimed_at", None)
        task.pop("claim_id", None)

        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)
        return task_id

    def schedule(self, task: Dict, delay: float, queue: str = "default", priority: int = 0) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        self._scheduled[task_id] = time.time() + delay
        return task_id

    async def dequeue(
        self,
        queue: str = "default",
        timeout: float = 1.0,
        worker_id: Optional[str] = None,
    ) -> Optional[Dict]:
        now = time.time()
        expired = [tid for tid, t in self._scheduled.items() if t <= now]
        for tid in expired:
            task = self._scheduled.pop(tid)
            if task:
                self.enqueue(task, queue)

        if queue in self._queues and len(self._queues[queue]) > 0:
            task = self._queues[queue].pop()
            if task:
                task["queue"] = queue
                task["claimed_by"] = worker_id
                task["claimed_at"] = time.time()
                task["claim_id"] = str(uuid4())
                self._in_flight[task["id"]] = task
                return task
        return None

    def complete(self, task_id: str) -> bool:
        return self._in_flight.pop(task_id, None) is not None

    def fail(self, task_id: str, queue: str = "default") -> bool:
        task = self._in_flight.pop(task_id, None)
        if task:
            task["retries"] += 1
            if task["retries"] < self._max_retries:
                self.enqueue(task, queue, priority=task.get("priority", 0))
                return True
        return False

    def acknowledge_batch(
        self,
        worker_id: str,
        acknowledgements: Iterable[Union[str, Dict[str, str]]],
        action: str = "complete",
        queue: str = "default",
    ) -> Dict[str, Any]:
        if not worker_id:
            return self._ack_result(False, errors=[{"reason": "missing_worker_id"}])
        if action not in {"complete", "fail"}:
            return self._ack_result(False, errors=[{"reason": "invalid_action", "action": action}])

        normalized = self._normalize_acknowledgements(acknowledgements)
        errors: List[Dict[str, Any]] = []
        seen = set()
        to_commit = []
        idempotent = []

        for task_id, claim_id in normalized:
            current = self._in_flight.get(task_id)
            effective_claim_id = claim_id or (current or {}).get("claim_id")
            ack_key = (task_id, effective_claim_id, action)

            if ack_key in seen:
                errors.append({"task_id": task_id, "reason": "duplicate_in_batch"})
                continue
            seen.add(ack_key)

            previous = self._acknowledged.get(ack_key)
            if previous:
                if previous["worker_id"] == worker_id:
                    idempotent.append(task_id)
                    continue
                errors.append({"task_id": task_id, "reason": "acknowledged_by_other_worker"})
                continue

            if not current:
                previous = self._find_acknowledgement(task_id, claim_id, action)
                if previous:
                    if previous["worker_id"] == worker_id:
                        idempotent.append(task_id)
                        continue
                    errors.append({"task_id": task_id, "reason": "acknowledged_by_other_worker"})
                    continue
                errors.append({"task_id": task_id, "reason": "not_in_flight"})
                continue
            if current.get("claimed_by") != worker_id:
                errors.append({"task_id": task_id, "reason": "wrong_worker"})
                continue
            if claim_id is not None and current.get("claim_id") != claim_id:
                errors.append({"task_id": task_id, "reason": "stale_claim"})
                continue

            to_commit.append((task_id, current, ack_key))

        if errors:
            return self._ack_result(False, idempotent=idempotent, errors=errors)

        acked = []
        retried = []
        for task_id, task, ack_key in to_commit:
            self._in_flight.pop(task_id, None)
            self._acknowledged[ack_key] = {
                "worker_id": worker_id,
                "action": action,
                "acknowledged_at": time.time(),
            }
            acked.append(task_id)

            if action == "fail":
                task["retries"] += 1
                if task["retries"] < self._max_retries:
                    retry_id = self.enqueue(dict(task), queue, priority=task.get("priority", 0))
                    retried.append(retry_id)

        return self._ack_result(True, acked=acked, idempotent=idempotent, retried=retried)

    def _normalize_acknowledgements(
        self,
        acknowledgements: Iterable[Union[str, Dict[str, str]]],
    ) -> List[Tuple[str, Optional[str]]]:
        normalized = []
        for ack in acknowledgements:
            if isinstance(ack, dict):
                task_id = ack.get("task_id") or ack.get("id")
                claim_id = ack.get("claim_id")
            else:
                task_id = str(ack)
                claim_id = None
            normalized.append((task_id, claim_id))
        return normalized

    def _find_acknowledgement(
        self,
        task_id: str,
        claim_id: Optional[str],
        action: str,
    ) -> Optional[Dict]:
        if claim_id is not None:
            return self._acknowledged.get((task_id, claim_id, action))

        for (acked_task_id, _acked_claim_id, acked_action), record in self._acknowledged.items():
            if acked_task_id == task_id and acked_action == action:
                return record
        return None

    def _ack_result(
        self,
        ok: bool,
        acked: Optional[List[str]] = None,
        idempotent: Optional[List[str]] = None,
        retried: Optional[List[str]] = None,
        errors: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        return {
            "ok": ok,
            "acked": acked or [],
            "idempotent": idempotent or [],
            "retried": retried or [],
            "errors": errors or [],
        }

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
