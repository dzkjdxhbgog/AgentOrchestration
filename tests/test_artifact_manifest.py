import hashlib

import pytest

from src.storage.artifact_manifest import (
    ArtifactIntegrityError,
    ArtifactManifest,
    ArtifactManifestReader,
    BlobQuarantine,
    IntegrityAlertSink,
)


def sha256(blob):
    return hashlib.sha256(blob).hexdigest()


def test_manifest_reader_returns_blob_when_digest_matches():
    blob = b"artifact payload"
    manifest = ArtifactManifest(
        artifact_id="artifact-1",
        blob_key="cache/artifact-1",
        digest=f"sha256:{sha256(blob)}",
    )
    alerts = IntegrityAlertSink()
    quarantine = BlobQuarantine()

    assert ArtifactManifestReader(alerts, quarantine).read(manifest, blob) == blob
    assert alerts.alerts == []
    assert not quarantine.is_blocked("cache/artifact-1")


def test_digest_mismatch_emits_integrity_alert_and_quarantines_blob():
    manifest = ArtifactManifest(
        artifact_id="artifact-1",
        blob_key="cache/artifact-1",
        digest=sha256(b"expected payload"),
    )
    alerts = IntegrityAlertSink()
    quarantine = BlobQuarantine()

    with pytest.raises(ArtifactIntegrityError, match="digest mismatch"):
        ArtifactManifestReader(alerts, quarantine).read(manifest, b"corrupt payload")

    assert len(alerts.alerts) == 1
    alert = alerts.alerts[0]
    assert alert.reason == "manifest_digest_mismatch"
    assert alert.severity == "critical"
    assert alert.artifact_id == "artifact-1"
    assert alert.blob_key == "cache/artifact-1"
    assert alert.expected_digest == sha256(b"expected payload")
    assert alert.actual_digest == sha256(b"corrupt payload")
    assert quarantine.is_blocked("cache/artifact-1")
    assert quarantine.get_alert("cache/artifact-1") == alert


def test_quarantined_blob_is_blocked_from_cache_reuse():
    quarantine = BlobQuarantine()
    alerts = IntegrityAlertSink()
    reader = ArtifactManifestReader(alerts, quarantine)
    blob = b"correct payload"
    manifest = ArtifactManifest(
        artifact_id="artifact-1",
        blob_key="cache/artifact-1",
        digest=sha256(blob),
    )

    with pytest.raises(ArtifactIntegrityError):
        reader.read(
            ArtifactManifest("artifact-1", "cache/artifact-1", sha256(b"other")),
            blob,
        )

    with pytest.raises(ArtifactIntegrityError, match="quarantined"):
        reader.read(manifest, blob)
