"""Compressed artifact backup validation helpers."""

import gzip
import hashlib
from dataclasses import dataclass, field
from typing import Iterable, List, Mapping, Optional


@dataclass(frozen=True)
class CompressedArtifactBackup:
    """Metadata needed to restore-check one compressed artifact."""

    artifact_id: str
    compressed_data: bytes
    digest: str
    digest_algorithm: str = "sha256"


@dataclass(frozen=True)
class ArtifactBackupValidationResult:
    ok: bool
    checked: int
    failures: List[str] = field(default_factory=list)


def validate_compressed_artifact_backups(
    artifacts: Iterable[CompressedArtifactBackup],
    sample_size: Optional[int] = None,
) -> ArtifactBackupValidationResult:
    """Decompress sampled artifact backups and compare their digests."""

    failures: List[str] = []
    checked = 0

    for artifact in _sample(artifacts, sample_size):
        checked += 1
        try:
            restored = gzip.decompress(artifact.compressed_data)
        except OSError as exc:
            failures.append(f"{artifact.artifact_id}: decompression failed: {exc}")
            continue

        actual_digest = _digest(restored, artifact.digest_algorithm)
        if actual_digest != artifact.digest:
            failures.append(
                f"{artifact.artifact_id}: digest mismatch "
                f"(expected {artifact.digest}, got {actual_digest})"
            )

    return ArtifactBackupValidationResult(
        ok=not failures,
        checked=checked,
        failures=failures,
    )


def validate_compressed_artifact_backup_records(
    records: Iterable[Mapping[str, object]],
    sample_size: Optional[int] = None,
) -> ArtifactBackupValidationResult:
    """Validate artifact records that store digests in metadata."""

    artifacts = (
        CompressedArtifactBackup(
            artifact_id=str(record.get("id", record.get("artifact_id", ""))),
            compressed_data=record["compressed_data"],  # type: ignore[arg-type]
            digest=_metadata_digest(record),
            digest_algorithm=str(record.get("digest_algorithm", "sha256")),
        )
        for record in records
    )
    return validate_compressed_artifact_backups(artifacts, sample_size=sample_size)


def _sample(
    artifacts: Iterable[CompressedArtifactBackup],
    sample_size: Optional[int],
) -> Iterable[CompressedArtifactBackup]:
    if sample_size is None:
        return artifacts
    if sample_size < 0:
        raise ValueError("sample_size must not be negative")
    return list(artifacts)[:sample_size]


def _digest(data: bytes, algorithm: str) -> str:
    hasher = hashlib.new(algorithm)
    hasher.update(data)
    return hasher.hexdigest()


def _metadata_digest(record: Mapping[str, object]) -> str:
    metadata = record.get("metadata")
    if isinstance(metadata, Mapping):
        digest = metadata.get("digest") or metadata.get("sha256")
        if digest:
            return str(digest)
    digest = record.get("digest")
    if digest:
        return str(digest)
    raise ValueError("artifact record is missing metadata digest")
