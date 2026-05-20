import pytest

from src.orchestrator.deployment import (
    InMemoryMigrationStateStore,
    MigrationBehavior,
    MigrationRunner,
    MigrationScript,
    MigrationStatus,
    SQLiteMigrationStateStore,
)


def test_retry_skips_completed_single_run_migration():
    calls = []
    runner = MigrationRunner()
    migration = MigrationScript(
        migration_id="20260520_add_accounts",
        handler=lambda: calls.append("run"),
        behavior=MigrationBehavior.SINGLE_RUN,
    )

    assert runner.run([migration], owner="deploy-a")
    assert runner.run([migration], owner="deploy-retry")

    record = runner.state_store.get_record("20260520_add_accounts")
    assert calls == ["run"]
    assert record.status == MigrationStatus.COMPLETED
    assert record.run_count == 1
    assert runner.audit_log[-1]["status"] == "skipped"
    assert runner.audit_log[-1]["lock_owner"] == "deploy-retry"


def test_concurrent_migration_with_existing_lock_does_not_execute():
    calls = []
    store = InMemoryMigrationStateStore()
    assert store.acquire_lock(
        "20260520_backfill_users",
        "deploy-a",
        MigrationBehavior.IDEMPOTENT,
    )

    runner = MigrationRunner(store)
    migration = MigrationScript(
        migration_id="20260520_backfill_users",
        handler=lambda: calls.append("run"),
        behavior=MigrationBehavior.IDEMPOTENT,
    )

    assert not runner.run([migration], owner="deploy-b")
    assert calls == []
    assert runner.audit_log[-1]["detail"] == "lock unavailable"


def test_retry_resumes_after_last_completed_migration():
    calls = []
    runner = MigrationRunner()

    first = MigrationScript(
        migration_id="001_create_table",
        handler=lambda: calls.append("first"),
        behavior=MigrationBehavior.SINGLE_RUN,
    )

    attempts = {"second": 0}

    def flaky_second():
        attempts["second"] += 1
        calls.append("second")
        if attempts["second"] == 1:
            raise RuntimeError("database timeout")

    second = MigrationScript(
        migration_id="002_backfill_table",
        handler=flaky_second,
        behavior=MigrationBehavior.IDEMPOTENT,
    )

    assert not runner.run([first, second], owner="deploy-a")
    assert runner.run([first, second], owner="deploy-retry")

    assert calls == ["first", "second", "second"]
    assert runner.state_store.get_record("001_create_table").run_count == 1
    assert runner.state_store.get_record("002_backfill_table").status == MigrationStatus.COMPLETED


def test_migration_requires_declared_behavior():
    runner = MigrationRunner()
    migration = MigrationScript(
        migration_id="003_missing_behavior",
        handler=lambda: None,
        behavior="unknown",
    )

    with pytest.raises(ValueError, match="idempotent or single-run"):
        runner.run([migration])


def test_sqlite_store_persists_completion_state_across_runners(tmp_path):
    database_path = tmp_path / "migrations.sqlite"
    first_store = SQLiteMigrationStateStore(str(database_path))
    calls = []
    migration = MigrationScript(
        migration_id="004_shared_database_state",
        handler=lambda: calls.append("run"),
        behavior=MigrationBehavior.SINGLE_RUN,
    )

    assert MigrationRunner(first_store).run([migration], owner="deploy-a")

    second_store = SQLiteMigrationStateStore(str(database_path))
    second_runner = MigrationRunner(second_store)
    assert second_runner.run([migration], owner="deploy-retry")

    assert calls == ["run"]
    assert second_store.get_record("004_shared_database_state").status == MigrationStatus.COMPLETED
    assert second_runner.audit_log[-1]["status"] == "skipped"
