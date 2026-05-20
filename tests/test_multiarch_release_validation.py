import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "scripts"
    / "validate_multiarch_release.py"
)
SPEC = importlib.util.spec_from_file_location("validate_multiarch_release", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
validate_multiarch_release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validate_multiarch_release)


VALID_AMD64_DIGEST = "sha256:" + "a" * 64
VALID_ARM64_DIGEST = "sha256:" + "b" * 64


def valid_manifest():
    return {
        "architectures": [
            {
                "platform": "linux/amd64",
                "digest": VALID_AMD64_DIGEST,
                "test_status": "passed",
                "scan_status": "passed",
            },
            {
                "platform": "linux/arm64",
                "digest": VALID_ARM64_DIGEST,
                "tests": True,
                "scan": "success",
            },
        ]
    }


def test_validate_manifest_returns_only_validated_architecture_digests():
    entries = validate_multiarch_release.validate_digest_manifest(valid_manifest())

    assert entries == [
        {
            "platform": "linux/amd64",
            "digest": VALID_AMD64_DIGEST,
            "test_status": "passed",
            "scan_status": "passed",
        },
        {
            "platform": "linux/arm64",
            "digest": VALID_ARM64_DIGEST,
            "test_status": "passed",
            "scan_status": "passed",
        },
    ]


def test_missing_architecture_fails_release_validation():
    manifest = valid_manifest()
    manifest["architectures"] = manifest["architectures"][:1]

    with pytest.raises(validate_multiarch_release.ReleaseValidationError, match="linux/arm64"):
        validate_multiarch_release.validate_digest_manifest(manifest)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("test_status", "failed", "passing tests"),
        ("scan_status", "missing", "passing scan"),
        ("digest", "latest", "invalid image digest"),
    ],
)
def test_failed_architecture_validation_blocks_manifest_push(field, value, message):
    manifest = valid_manifest()
    manifest["architectures"][0][field] = value

    with pytest.raises(validate_multiarch_release.ReleaseValidationError, match=message):
        validate_multiarch_release.validate_digest_manifest(manifest)


def test_unexpected_architecture_fails_closed():
    manifest = valid_manifest()
    manifest["architectures"].append(
        {
            "platform": "linux/s390x",
            "digest": "sha256:" + "c" * 64,
            "test_status": "passed",
            "scan_status": "passed",
        }
    )

    with pytest.raises(validate_multiarch_release.ReleaseValidationError, match="not part"):
        validate_multiarch_release.validate_digest_manifest(manifest)


def test_cli_writes_validated_manifest_and_github_summary(tmp_path, monkeypatch, capsys):
    manifest_path = tmp_path / "digests.json"
    output_path = tmp_path / "validated.json"
    summary_path = tmp_path / "summary.md"
    manifest_path.write_text(json.dumps(valid_manifest()), encoding="utf-8")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))

    result = validate_multiarch_release.main(
        [str(manifest_path), "--output", str(output_path)]
    )

    assert result == 0
    assert "linux/amd64" in capsys.readouterr().out
    assert (
        json.loads(output_path.read_text())["architectures"][1]["platform"]
        == "linux/arm64"
    )
    assert VALID_ARM64_DIGEST in summary_path.read_text(encoding="utf-8")
