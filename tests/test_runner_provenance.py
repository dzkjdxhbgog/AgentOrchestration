from datetime import datetime, timezone

from tools.validate_runner_provenance import validate_provenance, write_summary


VALID_DIGEST = "sha256:" + "a" * 64
NOW = datetime(2026, 5, 20, 12, 0, tzinfo=timezone.utc)


def test_strict_preflight_accepts_approved_runner_image():
    ok, errors, details = validate_provenance(
        {
            "AO_STRICT_RUNNER_PREFLIGHT": "true",
            "AO_RUNNER_IMAGE_DIGEST": VALID_DIGEST,
            "AO_APPROVED_RUNNER_DIGESTS": VALID_DIGEST,
            "AO_RUNNER_IMAGE_BUILT_AT": "2026-05-20T10:00:00Z",
            "AO_RUNNER_LABELS": "self-hosted,linux,x64,release",
            "AO_APPROVED_RUNNER_LABELS": "self-hosted,linux,release",
        },
        now=NOW,
    )

    assert ok
    assert errors == []
    assert any(detail.startswith("runner_image_age_hours=") for detail in details)


def test_strict_preflight_rejects_unapproved_digest():
    bad_digest = "sha256:" + "b" * 64

    ok, errors, _ = validate_provenance(
        {
            "AO_STRICT_RUNNER_PREFLIGHT": "true",
            "AO_RUNNER_IMAGE_DIGEST": bad_digest,
            "AO_APPROVED_RUNNER_DIGESTS": VALID_DIGEST,
            "AO_RUNNER_IMAGE_BUILT_AT": "2026-05-20T10:00:00Z",
            "AO_RUNNER_LABELS": "self-hosted,linux,x64,release",
            "AO_APPROVED_RUNNER_LABELS": "self-hosted,linux,release",
        },
        now=NOW,
    )

    assert not ok
    assert "runner image digest is not in the approved list" in errors


def test_strict_preflight_rejects_stale_image():
    ok, errors, _ = validate_provenance(
        {
            "AO_STRICT_RUNNER_PREFLIGHT": "true",
            "AO_RUNNER_IMAGE_DIGEST": VALID_DIGEST,
            "AO_APPROVED_RUNNER_DIGESTS": VALID_DIGEST,
            "AO_RUNNER_IMAGE_BUILT_AT": "2026-05-01T00:00:00Z",
            "AO_RUNNER_MAX_IMAGE_AGE_HOURS": "24",
            "AO_RUNNER_LABELS": "self-hosted,linux,x64,release",
            "AO_APPROVED_RUNNER_LABELS": "self-hosted,linux,release",
        },
        now=NOW,
    )

    assert not ok
    assert "runner image is older than the approved max age" in errors


def test_strict_preflight_rejects_missing_approved_label():
    ok, errors, _ = validate_provenance(
        {
            "AO_STRICT_RUNNER_PREFLIGHT": "true",
            "AO_RUNNER_IMAGE_DIGEST": VALID_DIGEST,
            "AO_APPROVED_RUNNER_DIGESTS": VALID_DIGEST,
            "AO_RUNNER_IMAGE_BUILT_AT": "2026-05-20T10:00:00Z",
            "AO_RUNNER_LABELS": "self-hosted,linux,x64",
            "AO_APPROVED_RUNNER_LABELS": "self-hosted,linux,release",
        },
        now=NOW,
    )

    assert not ok
    assert "runner labels missing approved labels: release" in errors


def test_non_strict_hosted_runner_writes_safe_summary(tmp_path):
    summary = tmp_path / "summary.md"

    ok, errors, details = validate_provenance(
        {"AO_RUNNER_LABELS": "linux,x64"},
        now=NOW,
    )
    write_summary(str(summary), ok, errors, details)

    assert ok
    assert "GitHub-hosted runner preflight" in summary.read_text()
