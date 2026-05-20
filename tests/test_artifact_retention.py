from datetime import datetime, timedelta, timezone

from src.storage.artifact_retention import (
    ArtifactRetentionRecord,
    RetentionCleanupService,
)


NOW = datetime(2026, 5, 20, tzinfo=timezone.utc)


def expired_artifact(artifact_id, **overrides):
    data = {
        "artifact_id": artifact_id,
        "retention_expires_at": NOW - timedelta(days=1),
    }
    data.update(overrides)
    return ArtifactRetentionRecord(**data)


def test_cleanup_deletes_expired_artifacts_without_holds():
    plan = RetentionCleanupService().plan_cleanup(
        [
            expired_artifact("delete-me"),
            ArtifactRetentionRecord(
                artifact_id="retain-unexpired",
                retention_expires_at=NOW + timedelta(days=1),
            ),
        ],
        now=NOW,
    )

    assert plan.artifact_ids_to_delete == ["delete-me"]
    assert plan.held_expired_artifacts == []


def test_cleanup_skips_legal_hold_and_reports_it():
    plan = RetentionCleanupService().plan_cleanup(
        [
            expired_artifact(
                "legal-hold",
                legal_hold=True,
                legal_hold_reason="litigation request",
            )
        ],
        now=NOW,
    )

    assert plan.artifact_ids_to_delete == []
    assert len(plan.held_expired_artifacts) == 1
    report = plan.held_expired_artifacts[0]
    assert report.artifact_id == "legal-hold"
    assert report.hold_type == "legal"
    assert report.hold_reasons == ("litigation request",)


def test_cleanup_skips_investigation_hold_and_reports_it():
    plan = RetentionCleanupService().plan_cleanup(
        [
            expired_artifact(
                "investigation-hold",
                investigation_hold=True,
                investigation_hold_reason="audit incident",
            )
        ],
        now=NOW,
    )

    assert plan.artifact_ids_to_delete == []
    assert len(plan.held_expired_artifacts) == 1
    report = plan.held_expired_artifacts[0]
    assert report.artifact_id == "investigation-hold"
    assert report.hold_type == "investigation"
    assert report.hold_reasons == ("audit incident",)


def test_cleanup_reports_both_hold_types():
    plan = RetentionCleanupService().plan_cleanup(
        [
            expired_artifact(
                "both-holds",
                legal_hold=True,
                investigation_hold=True,
                legal_hold_reason="legal review",
                investigation_hold_reason="security investigation",
            )
        ],
        now=NOW,
    )

    assert plan.artifact_ids_to_delete == []
    report = plan.held_expired_artifacts[0]
    assert report.hold_type == "legal+investigation"
    assert report.hold_reasons == ("legal review", "security investigation")


def test_cleanup_separates_deletable_and_held_expired_artifacts():
    plan = RetentionCleanupService().plan_cleanup(
        [
            expired_artifact("delete-a"),
            expired_artifact("legal-hold", legal_hold=True),
            expired_artifact("delete-b"),
            expired_artifact("investigation-hold", investigation_hold=True),
        ],
        now=NOW,
    )

    assert plan.artifact_ids_to_delete == ["delete-a", "delete-b"]
    assert [entry.artifact_id for entry in plan.held_expired_artifacts] == [
        "legal-hold",
        "investigation-hold",
    ]
