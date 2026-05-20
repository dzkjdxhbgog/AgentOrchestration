"""Deployment migration execution with retry-safe locking."""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, Iterable, List, Optional
from uuid import uuid4

from src.common.metrics import metrics


logger = logging.getLogger(__name__)


class MigrationBehavior(Enum):
    IDEMPOTENT = "idempotent"
    SINGLE_RUN = "single-run"


class MigrationStatus(Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class MigrationScript:
    migration_id: str
    handler: Callable[[], None]
    behavior: MigrationBehavior


@dataclass
class MigrationRecord:
    migration_id: str
    status: MigrationStatus
    behavior: MigrationBehavior
    lock_owner: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    error: Optional[str] = None
    run_count: int = 0


class MigrationLockError(RuntimeError):
    pass


class MigrationStateStore:
    """Atomic migration state store interface for database-backed adapters."""

    def acquire_lock(self, migration_id: str, owner: str, behavior: MigrationBehavior) -> bool:
        raise NotImplementedError

    def release_lock(self, migration_id: str, owner: str) -> None:
        raise NotImplementedError

    def get_record(self, migration_id: str) -> Optional[MigrationRecord]:
        raise NotImplementedError

    def mark_completed(self, migration_id: str, owner: str) -> MigrationRecord:
        raise NotImplementedError

    def mark_failed(self, migration_id: str, owner: str, error: str) -> MigrationRecord:
        raise NotImplementedError

    def list_records(self) -> List[MigrationRecord]:
        raise NotImplementedError


class SQLiteMigrationStateStore(MigrationStateStore):
    """SQLite-backed migration state store with atomic lock acquisition."""

    def __init__(self, database_path: str = ":memory:"):
        self._mutex = threading.RLock()
        self._connection = sqlite3.connect(database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._initialize()

    def acquire_lock(self, migration_id: str, owner: str, behavior: MigrationBehavior) -> bool:
        with self._mutex:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._fetch_row(migration_id)
                if row and row["status"] in {MigrationStatus.RUNNING.value, MigrationStatus.COMPLETED.value}:
                    self._connection.rollback()
                    return False

                now = time.time()
                if row:
                    self._connection.execute(
                        """
                        UPDATE migration_state
                           SET status = ?, behavior = ?, lock_owner = ?, started_at = ?,
                               completed_at = NULL, error = NULL
                         WHERE migration_id = ?
                        """,
                        (MigrationStatus.RUNNING.value, behavior.value, owner, now, migration_id),
                    )
                else:
                    self._connection.execute(
                        """
                        INSERT INTO migration_state (
                            migration_id, status, behavior, lock_owner, started_at, run_count
                        ) VALUES (?, ?, ?, ?, ?, 0)
                        """,
                        (migration_id, MigrationStatus.RUNNING.value, behavior.value, owner, now),
                    )
                self._connection.commit()
                return True
            except Exception:
                self._connection.rollback()
                raise

    def release_lock(self, migration_id: str, owner: str) -> None:
        with self._mutex:
            row = self._fetch_row(migration_id)
            if row and row["lock_owner"] == owner and row["status"] == MigrationStatus.RUNNING.value:
                self._connection.execute(
                    "UPDATE migration_state SET lock_owner = NULL WHERE migration_id = ?",
                    (migration_id,),
                )
                self._connection.commit()

    def get_record(self, migration_id: str) -> Optional[MigrationRecord]:
        with self._mutex:
            return self._row_to_record(self._fetch_row(migration_id))

    def mark_completed(self, migration_id: str, owner: str) -> MigrationRecord:
        with self._mutex:
            self._require_owner(migration_id, owner)
            now = time.time()
            self._connection.execute(
                """
                UPDATE migration_state
                   SET status = ?, completed_at = ?, error = NULL, run_count = run_count + 1
                 WHERE migration_id = ?
                """,
                (MigrationStatus.COMPLETED.value, now, migration_id),
            )
            self._connection.commit()
            return self.get_record(migration_id)

    def mark_failed(self, migration_id: str, owner: str, error: str) -> MigrationRecord:
        with self._mutex:
            self._require_owner(migration_id, owner)
            now = time.time()
            self._connection.execute(
                """
                UPDATE migration_state
                   SET status = ?, completed_at = ?, error = ?, run_count = run_count + 1
                 WHERE migration_id = ?
                """,
                (MigrationStatus.FAILED.value, now, error, migration_id),
            )
            self._connection.commit()
            return self.get_record(migration_id)

    def list_records(self) -> List[MigrationRecord]:
        with self._mutex:
            rows = self._connection.execute("SELECT * FROM migration_state").fetchall()
            return [self._row_to_record(row) for row in rows]

    def _initialize(self) -> None:
        with self._mutex:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS migration_state (
                    migration_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    behavior TEXT NOT NULL,
                    lock_owner TEXT,
                    started_at REAL NOT NULL,
                    completed_at REAL,
                    error TEXT,
                    run_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            self._connection.commit()

    def _fetch_row(self, migration_id: str) -> Optional[sqlite3.Row]:
        return self._connection.execute(
            "SELECT * FROM migration_state WHERE migration_id = ?",
            (migration_id,),
        ).fetchone()

    def _require_owner(self, migration_id: str, owner: str) -> None:
        row = self._fetch_row(migration_id)
        if not row or row["lock_owner"] != owner:
            raise MigrationLockError(f"Migration {migration_id} is not locked by {owner}")

    def _row_to_record(self, row: Optional[sqlite3.Row]) -> Optional[MigrationRecord]:
        if row is None:
            return None
        return MigrationRecord(
            migration_id=row["migration_id"],
            status=MigrationStatus(row["status"]),
            behavior=MigrationBehavior(row["behavior"]),
            lock_owner=row["lock_owner"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            error=row["error"],
            run_count=row["run_count"],
        )


class InMemoryMigrationStateStore(MigrationStateStore):
    """Thread-safe store matching the atomic contract expected from a DB row lock."""

    def __init__(self):
        self._mutex = threading.RLock()
        self._records: Dict[str, MigrationRecord] = {}

    def acquire_lock(self, migration_id: str, owner: str, behavior: MigrationBehavior) -> bool:
        with self._mutex:
            record = self._records.get(migration_id)
            if record and record.status == MigrationStatus.COMPLETED:
                return False
            if record and record.status == MigrationStatus.RUNNING:
                return False

            run_count = record.run_count if record else 0
            self._records[migration_id] = MigrationRecord(
                migration_id=migration_id,
                status=MigrationStatus.RUNNING,
                behavior=behavior,
                lock_owner=owner,
                run_count=run_count,
            )
            return True

    def release_lock(self, migration_id: str, owner: str) -> None:
        with self._mutex:
            record = self._records.get(migration_id)
            if record and record.lock_owner == owner and record.status != MigrationStatus.RUNNING:
                record.lock_owner = None

    def get_record(self, migration_id: str) -> Optional[MigrationRecord]:
        with self._mutex:
            return self._records.get(migration_id)

    def mark_completed(self, migration_id: str, owner: str) -> MigrationRecord:
        with self._mutex:
            record = self._require_owner(migration_id, owner)
            record.status = MigrationStatus.COMPLETED
            record.completed_at = time.time()
            record.error = None
            record.run_count += 1
            return record

    def mark_failed(self, migration_id: str, owner: str, error: str) -> MigrationRecord:
        with self._mutex:
            record = self._require_owner(migration_id, owner)
            record.status = MigrationStatus.FAILED
            record.completed_at = time.time()
            record.error = error
            record.run_count += 1
            return record

    def list_records(self) -> List[MigrationRecord]:
        with self._mutex:
            return list(self._records.values())

    def _require_owner(self, migration_id: str, owner: str) -> MigrationRecord:
        record = self._records.get(migration_id)
        if not record or record.lock_owner != owner:
            raise MigrationLockError(f"Migration {migration_id} is not locked by {owner}")
        return record


class MigrationRunner:
    def __init__(self, state_store: Optional[MigrationStateStore] = None):
        self.state_store = state_store or SQLiteMigrationStateStore()
        self.audit_log: List[Dict[str, object]] = []

    def run(self, migrations: Iterable[MigrationScript], owner: Optional[str] = None) -> bool:
        owner = owner or f"deployment-{uuid4()}"
        for migration in migrations:
            self._validate(migration)

            record = self.state_store.get_record(migration.migration_id)
            if record and record.status == MigrationStatus.COMPLETED:
                self._audit(migration.migration_id, MigrationStatus.SKIPPED, owner, "already completed")
                continue

            if not self.state_store.acquire_lock(migration.migration_id, owner, migration.behavior):
                metrics.increment("deployment.migration_lock_conflicts")
                self._audit(migration.migration_id, MigrationStatus.SKIPPED, owner, "lock unavailable")
                return False

            try:
                migration.handler()
            except Exception as exc:
                record = self.state_store.mark_failed(migration.migration_id, owner, str(exc))
                self._audit(migration.migration_id, record.status, owner, record.error)
                self.state_store.release_lock(migration.migration_id, owner)
                metrics.increment("deployment.migration_failures")
                return False

            record = self.state_store.mark_completed(migration.migration_id, owner)
            self._audit(migration.migration_id, record.status, owner, "completed")
            self.state_store.release_lock(migration.migration_id, owner)
            metrics.increment("deployment.migrations_completed")

        return True

    def _validate(self, migration: MigrationScript) -> None:
        if not migration.migration_id:
            raise ValueError("Migration scripts must declare a migration_id")
        if not isinstance(migration.behavior, MigrationBehavior):
            raise ValueError("Migration scripts must declare idempotent or single-run behavior")

    def _audit(
        self,
        migration_id: str,
        status: MigrationStatus,
        owner: str,
        detail: Optional[str] = None,
    ) -> None:
        entry = {
            "migration_id": migration_id,
            "status": status.value,
            "lock_owner": owner,
            "detail": detail,
            "timestamp": time.time(),
        }
        self.audit_log.append(entry)
        logger.info(
            "migration %s %s",
            migration_id,
            status.value,
            extra={"migration_id": migration_id, "lock_owner": owner, "status": status.value},
        )
