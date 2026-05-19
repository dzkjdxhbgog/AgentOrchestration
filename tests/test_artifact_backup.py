import gzip
import hashlib

import pytest

from src.common.artifact_backup import (
    CompressedArtifactBackup,
    validate_compressed_artifact_backup_records,
    validate_compressed_artifact_backups,
)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class TestArtifactBackupValidation:
    def test_restore_validation_decompresses_sampled_artifacts(self):
        payload = b"artifact contents"
        result = validate_compressed_artifact_backups(
            [
                CompressedArtifactBackup(
                    artifact_id="artifact-1",
                    compressed_data=gzip.compress(payload),
                    digest=_digest(payload),
                )
            ]
        )

        assert result.ok
        assert result.checked == 1
        assert result.failures == []

    def test_decompression_failure_marks_validation_failed(self):
        result = validate_compressed_artifact_backups(
            [
                CompressedArtifactBackup(
                    artifact_id="artifact-1",
                    compressed_data=b"not gzip data",
                    digest=_digest(b"artifact contents"),
                )
            ]
        )

        assert not result.ok
        assert result.checked == 1
        assert "decompression failed" in result.failures[0]

    def test_digest_mismatch_marks_validation_failed(self):
        result = validate_compressed_artifact_backups(
            [
                CompressedArtifactBackup(
                    artifact_id="artifact-1",
                    compressed_data=gzip.compress(b"restored contents"),
                    digest=_digest(b"metadata contents"),
                )
            ]
        )

        assert not result.ok
        assert result.checked == 1
        assert "digest mismatch" in result.failures[0]

    def test_sample_size_limits_restore_work(self):
        first = b"first"
        second = b"second"

        result = validate_compressed_artifact_backups(
            [
                CompressedArtifactBackup(
                    artifact_id="artifact-1",
                    compressed_data=gzip.compress(first),
                    digest=_digest(first),
                ),
                CompressedArtifactBackup(
                    artifact_id="artifact-2",
                    compressed_data=gzip.compress(second),
                    digest=_digest(b"stale metadata"),
                ),
            ],
            sample_size=1,
        )

        assert result.ok
        assert result.checked == 1

    def test_records_compare_content_digest_with_metadata(self):
        payload = b"record payload"

        result = validate_compressed_artifact_backup_records(
            [
                {
                    "id": "artifact-1",
                    "compressed_data": gzip.compress(payload),
                    "metadata": {"sha256": _digest(payload)},
                }
            ]
        )

        assert result.ok
        assert result.checked == 1

    def test_records_require_metadata_digest(self):
        with pytest.raises(ValueError, match="missing metadata digest"):
            validate_compressed_artifact_backup_records(
                [{"id": "artifact-1", "compressed_data": gzip.compress(b"payload")}]
            )
