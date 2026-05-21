"""Deployment preflight checks for database migrations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional


@dataclass(frozen=True)
class MigrationMetadata:
    migration_id: str
    description: str
    destructive: bool = False
    irreversible: bool = False


@dataclass(frozen=True)
class BackupStatus:
    backup_id: str
    created_at: datetime
    restore_verified: bool
    restore_checked_at: Optional[datetime] = None


@dataclass(frozen=True)
class MigrationPreflightResult:
    allowed: bool
    reason: str
    migration_id: str
    destructive: bool
    backup_timestamp: Optional[datetime]
    restore_check_status: str


class MigrationPreflight:
    """Requires recent restorable backups before destructive migrations."""

    def __init__(self, max_backup_age: timedelta = timedelta(hours=24)):
        self.max_backup_age = max_backup_age

    def check(
        self,
        metadata: MigrationMetadata,
        backup: Optional[BackupStatus],
        now: Optional[datetime] = None,
    ) -> MigrationPreflightResult:
        current_time = now or datetime.now(timezone.utc)
        destructive = metadata.destructive or metadata.irreversible

        if not destructive:
            return MigrationPreflightResult(
                allowed=True,
                reason="migration is non-destructive",
                migration_id=metadata.migration_id,
                destructive=False,
                backup_timestamp=backup.created_at if backup else None,
                restore_check_status=self._restore_status(backup),
            )

        if backup is None:
            return self._deny(metadata, None, "missing_backup")

        if not backup.restore_verified:
            return self._deny(metadata, backup, "restore_not_verified")

        if backup.created_at > current_time:
            return self._deny(metadata, backup, "backup_timestamp_in_future")

        if current_time - backup.created_at > self.max_backup_age:
            return self._deny(metadata, backup, "backup_stale")

        return MigrationPreflightResult(
            allowed=True,
            reason="recent restore-verified backup available",
            migration_id=metadata.migration_id,
            destructive=True,
            backup_timestamp=backup.created_at,
            restore_check_status=self._restore_status(backup),
        )

    def _deny(
        self,
        metadata: MigrationMetadata,
        backup: Optional[BackupStatus],
        reason: str,
    ) -> MigrationPreflightResult:
        return MigrationPreflightResult(
            allowed=False,
            reason=reason,
            migration_id=metadata.migration_id,
            destructive=True,
            backup_timestamp=backup.created_at if backup else None,
            restore_check_status=self._restore_status(backup),
        )

    def _restore_status(self, backup: Optional[BackupStatus]) -> str:
        if backup is None:
            return "missing"
        if not backup.restore_verified:
            return "failed"
        if backup.restore_checked_at is None:
            return "verified"
        return f"verified_at:{backup.restore_checked_at.isoformat()}"
