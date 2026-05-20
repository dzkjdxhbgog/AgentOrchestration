import pytest

from src.deploy.migrations import (
    MigrationRolloutGate,
    MigrationSpec,
    load_migration_manifest,
)


def test_migrations_complete_before_traffic_shift():
    events = []
    migrations = [
        MigrationSpec("001_add_task_state_column", "platform", True),
        MigrationSpec("002_backfill_task_state", "platform", True),
    ]
    handlers = {
        "001_add_task_state_column": lambda: events.append("migration:001"),
        "002_backfill_task_state": lambda: events.append("migration:002"),
    }

    result = MigrationRolloutGate(migrations, handlers).run_before_traffic_shift(
        traffic_shift=lambda: events.append("traffic")
    )

    assert result.rollout_allowed
    assert not result.prior_version_serving
    assert result.traffic_shift_started
    assert events == ["migration:001", "migration:002", "traffic"]


def test_migration_failure_blocks_rollout_and_keeps_prior_version_serving():
    events = []

    def fail_migration():
        events.append("migration")
        raise RuntimeError("database unavailable")

    gate = MigrationRolloutGate(
        [MigrationSpec("001_add_required_index", "database", True)],
        {"001_add_required_index": fail_migration},
    )

    result = gate.run_before_traffic_shift(
        traffic_shift=lambda: events.append("traffic")
    )

    assert not result.rollout_allowed
    assert result.prior_version_serving
    assert not result.traffic_shift_started
    assert events == ["migration"]
    assert result.migration_results[0].status == "failed"
    assert result.migration_results[0].error == "RuntimeError"


def test_release_check_identifies_forward_only_migration():
    gate = MigrationRolloutGate(
        [MigrationSpec("001_drop_legacy_column", "database", False)],
        {"001_drop_legacy_column": lambda: True},
    )

    result = gate.run_before_traffic_shift()

    assert not result.rollout_allowed
    assert result.prior_version_serving
    assert result.compatibility_errors == [
        "001_drop_legacy_column: not backward compatible"
    ]


def test_migration_without_handler_blocks_traffic():
    result = MigrationRolloutGate(
        [MigrationSpec("001_missing_handler", "database", True)]
    ).run_before_traffic_shift()

    assert not result.rollout_allowed
    assert result.prior_version_serving
    assert result.migration_results[0].status == "failed"
    assert result.migration_results[0].error == "missing migration handler"


def test_manifest_requires_owner_and_compatibility_metadata(tmp_path):
    manifest = tmp_path / "migrations.json"
    manifest.write_text(
        '{"migrations": [{"name": "001_add_column", "backward_compatible": true}]}'
    )

    with pytest.raises(ValueError, match="must declare an owner"):
        load_migration_manifest(str(manifest))


def test_load_manifest_builds_rollout_specs(tmp_path):
    manifest = tmp_path / "migrations.json"
    manifest.write_text(
        """
        {
          "migrations": [
            {
              "name": "001_add_nullable_column",
              "owner": "database",
              "backward_compatible": true,
              "required_before_traffic": true
            }
          ]
        }
        """
    )

    specs = load_migration_manifest(str(manifest))

    assert specs == [MigrationSpec("001_add_nullable_column", "database", True, True)]
