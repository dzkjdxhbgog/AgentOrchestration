from datetime import date

from src.common.dependency_review import (
    load_manifest,
    render_summary,
    validate_manifest,
    validate_overrides,
)


def write_manifest(tmp_path, text):
    path = tmp_path / ".github" / "dependency-review-exceptions.yml"
    path.parent.mkdir()
    path.write_text(text, encoding="utf-8")
    return load_manifest(path)


def test_valid_manifest_renders_record_link(tmp_path):
    manifest = write_manifest(
        tmp_path,
        """
exceptions:
  - id: GHSA-demo
    ecosystem: pypi
    name: demo-package
    version_range: "<2.0"
    owner: "@platform-security"
    reason: "Waiting for upstream patch."
    expires_on: "2026-06-30"
""",
    )

    assert validate_manifest(manifest, today=date(2026, 5, 22)) == []

    summary = render_summary(
        manifest,
        today=date(2026, 5, 22),
        repository="orchestration-agent/AgentOrchestration",
        ref="abc123",
    )

    assert "pypi:demo-package@<2.0" in summary
    assert ".github/dependency-review-exceptions.yml#L3" in summary


def test_expired_exception_fails_until_removed_or_renewed(tmp_path):
    manifest = write_manifest(
        tmp_path,
        """
exceptions:
  - id: CVE-expired
    coordinate: npm:left-pad@1.0.0
    owner: "@platform-security"
    reason: "Temporary exception."
    expires_on: "2026-05-01"
""",
    )

    errors = validate_manifest(manifest, today=date(2026, 5, 22))

    assert errors == [
        "CVE-expired: expired on 2026-05-01; remove or renew the exception"
    ]


def test_active_exceptions_require_owner_expiration_and_coordinates(tmp_path):
    manifest = write_manifest(
        tmp_path,
        """
exceptions:
  - id: incomplete
    reason: "Needs metadata."
""",
    )

    errors = validate_manifest(manifest, today=date(2026, 5, 22))

    assert "incomplete: owner is required" in errors
    assert (
        "incomplete: dependency coordinate requires ecosystem, name, "
        "version or version_range"
    ) in errors
    assert "incomplete: expires_on is required" in errors


def test_dependency_review_override_requires_active_manifest_match(tmp_path):
    manifest = write_manifest(
        tmp_path,
        """
exceptions:
  - id: GHSA-demo
    ecosystem: pypi
    name: demo-package
    version: "1.2.3"
    owner: "@platform-security"
    reason: "Waiting for upstream patch."
    expires_on: "2026-06-30"
""",
    )

    assert (
        validate_overrides(
            manifest,
            ["pypi:demo-package@1.2.3", "GHSA-demo"],
            today=date(2026, 5, 22),
        )
        == []
    )

    missing_errors = validate_overrides(
        manifest,
        ["pypi:other-package@1.0.0"],
        today=date(2026, 5, 22),
    )
    assert missing_errors == [
        "pypi:other-package@1.0.0: override has no active matching "
        "manifest entry"
    ]


def test_duplicate_exception_ids_are_rejected(tmp_path):
    manifest = write_manifest(
        tmp_path,
        """
exceptions:
  - id: GHSA-dup
    ecosystem: pypi
    name: demo-package
    version: "1.2.3"
    owner: "@platform-security"
    reason: "Needs temporary exception."
    expires_on: "2026-06-30"
  - id: GHSA-dup
    coordinate: npm:left-pad@1.0.0
    owner: "@platform-security"
    reason: "Second duplicate entry."
    expires_on: "2026-06-30"
""",
    )

    assert validate_manifest(manifest, today=date(2026, 5, 22)) == [
        "GHSA-dup: id must be unique"
    ]
