"""Artifact manifest reads with digest integrity alerts."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


class ArtifactIntegrityError(RuntimeError):
    """Raised when an artifact blob fails manifest integrity checks."""


@dataclass(frozen=True)
class ArtifactManifest:
    artifact_id: str
    blob_key: str
    digest: str
    digest_algorithm: str = "sha256"


@dataclass(frozen=True)
class ArtifactIntegrityAlert:
    artifact_id: str
    blob_key: str
    expected_digest: str
    actual_digest: str
    reason: str
    severity: str = "critical"
    created_at: float = field(default_factory=time.time)


class IntegrityAlertSink:
    def __init__(self):
        self.alerts: List[ArtifactIntegrityAlert] = []

    def emit(self, alert: ArtifactIntegrityAlert) -> None:
        self.alerts.append(alert)


class BlobQuarantine:
    def __init__(self):
        self._blocked: Dict[str, ArtifactIntegrityAlert] = {}

    def block(self, blob_key: str, alert: ArtifactIntegrityAlert) -> None:
        self._blocked[blob_key] = alert

    def is_blocked(self, blob_key: str) -> bool:
        return blob_key in self._blocked

    def get_alert(self, blob_key: str) -> Optional[ArtifactIntegrityAlert]:
        return self._blocked.get(blob_key)


class ArtifactManifestReader:
    def __init__(
        self,
        alert_sink: Optional[IntegrityAlertSink] = None,
        quarantine: Optional[BlobQuarantine] = None,
    ):
        self.alert_sink = alert_sink or IntegrityAlertSink()
        self.quarantine = quarantine or BlobQuarantine()

    def read(self, manifest: ArtifactManifest, blob: bytes) -> bytes:
        if self.quarantine.is_blocked(manifest.blob_key):
            raise ArtifactIntegrityError(
                f"artifact blob is quarantined and cannot be reused: {manifest.blob_key}"
            )

        actual_digest = self._digest(manifest.digest_algorithm, blob)
        expected_digest = self._normalize_digest(manifest.digest, manifest.digest_algorithm)
        if actual_digest != expected_digest:
            alert = ArtifactIntegrityAlert(
                artifact_id=manifest.artifact_id,
                blob_key=manifest.blob_key,
                expected_digest=expected_digest,
                actual_digest=actual_digest,
                reason="manifest_digest_mismatch",
            )
            self.alert_sink.emit(alert)
            self.quarantine.block(manifest.blob_key, alert)
            raise ArtifactIntegrityError(
                f"artifact digest mismatch for {manifest.artifact_id}: expected "
                f"{expected_digest}, got {actual_digest}"
            )

        return blob

    @staticmethod
    def _digest(algorithm: str, blob: bytes) -> str:
        if algorithm != "sha256":
            raise ValueError(f"unsupported artifact digest algorithm: {algorithm}")
        return hashlib.sha256(blob).hexdigest()

    @staticmethod
    def _normalize_digest(digest: str, algorithm: str) -> str:
        prefix = f"{algorithm}:"
        return digest[len(prefix):] if digest.startswith(prefix) else digest
