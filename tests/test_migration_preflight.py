from datetime import datetime, timedelta, timezone

from src.common.migration_preflight import (
    BackupStatus,
    MigrationMetadata,
    MigrationPreflight,
)


NOW = datetime(2026, 5, 21, 10, 0, tzinfo=timezone.utc)


def _destructive_migration():
    return MigrationMetadata(
        migration_id="20260521_drop_legacy_columns",
        description="drop legacy reporting columns",
        destructive=True,
    )


def test_destructive_migration_fails_without_backup():
    result = MigrationPreflight().check(
        _destructive_migration(),
        None,
        now=NOW,
    )

    assert not result.allowed
    assert result.reason == "missing_backup"
    assert result.backup_timestamp is None
    assert result.restore_check_status == "missing"


def test_destructive_migration_fails_without_restore_verification():
    backup = BackupStatus(
        backup_id="backup-1",
        created_at=NOW - timedelta(hours=1),
        restore_verified=False,
    )

    result = MigrationPreflight().check(
        _destructive_migration(),
        backup,
        now=NOW,
    )

    assert not result.allowed
    assert result.reason == "restore_not_verified"
    assert result.backup_timestamp == backup.created_at
    assert result.restore_check_status == "failed"


def test_destructive_migration_fails_with_stale_verified_backup():
    backup = BackupStatus(
        backup_id="backup-1",
        created_at=NOW - timedelta(hours=25),
        restore_verified=True,
        restore_checked_at=NOW - timedelta(hours=24),
    )

    result = MigrationPreflight().check(
        _destructive_migration(),
        backup,
        now=NOW,
    )

    assert not result.allowed
    assert result.reason == "backup_stale"
    assert result.backup_timestamp == backup.created_at
    assert result.restore_check_status.startswith("verified_at:")


def test_destructive_migration_accepts_recent_verified_backup():
    backup = BackupStatus(
        backup_id="backup-1",
        created_at=NOW - timedelta(hours=2),
        restore_verified=True,
        restore_checked_at=NOW - timedelta(hours=1),
    )

    result = MigrationPreflight().check(
        _destructive_migration(),
        backup,
        now=NOW,
    )

    assert result.allowed
    assert result.reason == "recent restore-verified backup available"
    assert result.backup_timestamp == backup.created_at
    assert result.restore_check_status.startswith("verified_at:")


def test_irreversible_migration_requires_backup_even_if_not_destructive():
    metadata = MigrationMetadata(
        migration_id="20260521_rewrite_ids",
        description="rewrite primary ids",
        destructive=False,
        irreversible=True,
    )

    result = MigrationPreflight().check(metadata, None, now=NOW)

    assert not result.allowed
    assert result.destructive
    assert result.reason == "missing_backup"


def test_non_destructive_migration_reports_backup_without_requiring_it():
    metadata = MigrationMetadata(
        migration_id="20260521_add_index",
        description="add reporting index",
        destructive=False,
    )

    result = MigrationPreflight().check(metadata, None, now=NOW)

    assert result.allowed
    assert not result.destructive
    assert result.reason == "migration is non-destructive"
    assert result.restore_check_status == "missing"
