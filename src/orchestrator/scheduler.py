"""Task Scheduler — Priority-based task queuing and dispatch."""

import asyncio
import heapq
import time
from typing import Any, Dict, Iterable, List, Optional, Set
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
        self._worker_capabilities: Dict[str, Dict] = {}
        self._audit_log: List[Dict] = []
        self._max_retries = 3

    def enqueue(
        self,
        task: Dict,
        queue: str = "default",
        priority: int = 0,
        required_capabilities: Optional[Iterable[str]] = None,
    ) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task["retries"] = 0
        task["queue"] = queue
        task["priority"] = priority
        if required_capabilities is not None:
            task["required_capabilities"] = sorted(
                self._normalize_capabilities(required_capabilities)
            )

        self._push_existing(task, queue, priority)
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
        worker_capabilities: Optional[Iterable[str]] = None,
        reconnect_id: Optional[str] = None,
    ) -> Optional[Dict]:
        if worker_id and worker_capabilities is not None:
            normalized = self._normalize_capabilities(worker_capabilities)
            current = self._worker_capabilities.get(worker_id)
            if (
                reconnect_id
                or not current
                or current["capabilities"] != normalized
            ):
                self.refresh_worker_capabilities(
                    worker_id,
                    normalized,
                    reconnect_id=reconnect_id,
                )

        now = time.time()
        expired = [tid for tid, t in self._scheduled.items() if t <= now]
        for tid in expired:
            task = self._scheduled.pop(tid)
            if task:
                self.enqueue(task, queue)

        if queue in self._queues and len(self._queues[queue]) > 0:
            task = self._queues[queue].pop()
            if task:
                if worker_id and not self._worker_can_run(worker_id, task):
                    self._clear_claim(task)
                    self._push_existing(task, queue, task.get("priority", 0))
                    self._audit(
                        "defer_capability_mismatch",
                        task_id=task["id"],
                        worker_id=worker_id,
                    )
                    return None
                if worker_id:
                    worker = self._worker_capabilities[worker_id]
                    task["claimed_by"] = worker_id
                    task["worker_capability_version"] = worker["version"]
                    task["claim_id"] = str(uuid4())
                    self._audit(
                        "claim",
                        task_id=task["id"],
                        worker_id=worker_id,
                        version=worker["version"],
                    )
                self._in_flight[task["id"]] = task
                return task
        return None

    def complete(
        self,
        task_id: str,
        worker_id: Optional[str] = None,
        capability_version: Optional[int] = None,
    ) -> bool:
        task = self._in_flight.get(task_id)
        if not task:
            return False
        if not self._claim_matches(task, worker_id, capability_version):
            self._audit(
                "reject_stale_ack",
                task_id=task_id,
                worker_id=worker_id,
                version=capability_version,
            )
            return False
        self._in_flight.pop(task_id, None)
        self._audit("complete", task_id=task_id, worker_id=worker_id)
        return True

    def fail(
        self,
        task_id: str,
        queue: str = "default",
        worker_id: Optional[str] = None,
        capability_version: Optional[int] = None,
    ) -> bool:
        task = self._in_flight.get(task_id)
        if task and not self._claim_matches(
            task,
            worker_id,
            capability_version,
        ):
            self._audit(
                "reject_stale_nack",
                task_id=task_id,
                worker_id=worker_id,
                version=capability_version,
            )
            return False
        task = self._in_flight.pop(task_id, None)
        if task:
            task["retries"] += 1
            if task["retries"] < self._max_retries:
                self._clear_claim(task)
                self._push_existing(
                    task,
                    queue,
                    priority=task.get("priority", 0),
                )
                self._audit("retry", task_id=task_id, worker_id=worker_id)
                return True
        return False

    def refresh_worker_capabilities(
        self,
        worker_id: str,
        capabilities: Iterable[str],
        reconnect_id: Optional[str] = None,
    ) -> int:
        previous = self._worker_capabilities.get(worker_id, {})
        version = previous.get("version", 0) + 1
        normalized = self._normalize_capabilities(capabilities)
        self._worker_capabilities[worker_id] = {
            "capabilities": normalized,
            "version": version,
            "reconnect_id": reconnect_id,
            "updated_at": time.time(),
        }
        self._audit(
            "refresh_worker_capabilities",
            worker_id=worker_id,
            version=version,
            reconnect_id=reconnect_id,
        )
        self._defer_worker_claims(worker_id)
        return version

    @property
    def audit_log(self) -> List[Dict]:
        return list(self._audit_log)

    def _push_existing(
        self,
        task: Dict,
        queue: str,
        priority: int = 0,
    ) -> None:
        task["queue"] = queue
        task["priority"] = priority
        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)

    def _defer_worker_claims(self, worker_id: str) -> None:
        for task_id, task in list(self._in_flight.items()):
            if task.get("claimed_by") != worker_id:
                continue
            self._in_flight.pop(task_id, None)
            self._clear_claim(task)
            self._push_existing(
                task,
                task.get("queue", "default"),
                priority=task.get("priority", 0),
            )
            self._audit(
                "defer_reconnected_worker_claim",
                task_id=task_id,
                worker_id=worker_id,
            )

    def _worker_can_run(self, worker_id: str, task: Dict) -> bool:
        worker = self._worker_capabilities.get(worker_id)
        if not worker:
            return False
        return self._required_capabilities(task).issubset(
            worker["capabilities"]
        )

    def _claim_matches(
        self,
        task: Dict,
        worker_id: Optional[str],
        capability_version: Optional[int],
    ) -> bool:
        if worker_id is not None and task.get("claimed_by") != worker_id:
            return False
        if (
            capability_version is not None
            and task.get("worker_capability_version") != capability_version
        ):
            return False
        current = self._worker_capabilities.get(task.get("claimed_by"))
        if (
            current
            and task.get("worker_capability_version") != current["version"]
        ):
            return False
        return True

    def _required_capabilities(self, task: Dict) -> Set[str]:
        return self._normalize_capabilities(
            task.get("required_capabilities", [])
        )

    def _normalize_capabilities(self, capabilities: Iterable[str]) -> Set[str]:
        normalized = set()
        for capability in capabilities:
            capability = str(capability).strip().lower()
            if capability:
                normalized.add(capability)
        return normalized

    def _clear_claim(self, task: Dict) -> None:
        task.pop("claimed_by", None)
        task.pop("worker_capability_version", None)
        task.pop("claim_id", None)

    def _audit(self, event: str, **fields: Any) -> None:
        record = {"event": event, "timestamp": time.time()}
        record.update(
            {key: value for key, value in fields.items() if value is not None}
        )
        self._audit_log.append(record)

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
