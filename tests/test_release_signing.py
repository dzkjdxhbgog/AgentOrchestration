import importlib.util
import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_release_signing.py"

spec = importlib.util.spec_from_file_location(
    "check_release_signing",
    SCRIPT_PATH,
)
check_release_signing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_release_signing)


def write_manifest(tmp_path, artifacts):
    manifest = tmp_path / "signing-manifest.json"
    manifest.write_text(
        json.dumps({"artifacts": artifacts}),
        encoding="utf-8",
    )
    return manifest


def test_validate_release_signing_summary_accepts_signed_manifest(tmp_path):
    manifest = write_manifest(
        tmp_path,
        [
            {
                "name": "dist/agent.whl",
                "status": "signed",
                "digest": "abc123",
                "signature": "sig-abc123",
            },
            {
                "name": "dist/agent.tar.gz",
                "status": "signed",
                "digest": "def456",
                "signature": "sig-def456",
            },
        ],
    )

    signed_count = check_release_signing.validate_release_signing_summary(
        manifest
    )
    assert signed_count == 2


def test_validate_release_signing_summary_rejects_partial_state(tmp_path):
    manifest = write_manifest(
        tmp_path,
        [
            {
                "name": "dist/agent.whl",
                "status": "signed",
                "digest": "abc123",
                "signature": "sig-abc123",
            },
            {
                "name": "dist/agent.tar.gz",
                "status": "partial",
                "digest": "def456",
                "signature": "sig-def456",
            },
        ],
    )

    with pytest.raises(check_release_signing.ReleaseSigningError):
        check_release_signing.validate_release_signing_summary(manifest)


def test_validate_release_signing_summary_rejects_missing_signature(tmp_path):
    manifest = write_manifest(
        tmp_path,
        [
            {
                "name": "dist/agent.whl",
                "status": "signed",
                "digest": "abc123",
                "signature": "",
            }
        ],
    )

    with pytest.raises(check_release_signing.ReleaseSigningError):
        check_release_signing.validate_release_signing_summary(manifest)


def test_validate_release_signing_summary_rejects_empty_manifest(tmp_path):
    manifest = write_manifest(tmp_path, [])

    with pytest.raises(check_release_signing.ReleaseSigningError):
        check_release_signing.validate_release_signing_summary(manifest)
