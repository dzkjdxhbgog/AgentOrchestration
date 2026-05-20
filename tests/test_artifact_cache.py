import hashlib

import pytest

from src.common.artifact_cache import ArtifactCacheError, ArtifactDownloadCache


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_cache_hit_verifies_digest_before_reuse(tmp_path):
    payload = b"artifact-v1"
    cache = ArtifactDownloadCache(tmp_path)
    calls = []

    def download(path):
        calls.append(path)
        path.write_bytes(payload)

    first = cache.get_or_download("artifact.bin", digest(payload), download)
    second = cache.get_or_download("artifact.bin", digest(payload), download)

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.path.read_bytes() == payload
    assert len(calls) == 1


def test_digest_mismatch_evicts_and_redownloads(tmp_path):
    old_payload = b"stale"
    new_payload = b"fresh"
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(old_payload)
    (tmp_path / "artifact.bin.json").write_text(
        '{"algorithm": "sha256", "digest": "' + digest(new_payload) + '"}',
        encoding="utf-8",
    )
    cache = ArtifactDownloadCache(tmp_path)

    result = cache.get_or_download(
        "artifact.bin",
        digest(new_payload),
        lambda path: path.write_bytes(new_payload),
    )

    assert result.cache_hit is False
    assert artifact.read_bytes() == new_payload


def test_partial_file_is_evicted_and_redownloaded(tmp_path):
    expected = b"complete artifact bytes"
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"partial")
    (tmp_path / "artifact.bin.json").write_text(
        '{"algorithm": "sha256", "digest": "' + digest(expected) + '"}',
        encoding="utf-8",
    )
    cache = ArtifactDownloadCache(tmp_path)

    result = cache.get_or_download(
        "artifact.bin",
        digest(expected),
        lambda path: path.write_bytes(expected),
    )

    assert result.cache_hit is False
    assert artifact.read_bytes() == expected


def test_download_digest_mismatch_removes_bad_cache_entry(tmp_path):
    cache = ArtifactDownloadCache(tmp_path)

    with pytest.raises(ArtifactCacheError, match="digest does not match"):
        cache.get_or_download(
            "artifact.bin",
            digest(b"expected"),
            lambda path: path.write_bytes(b"corrupt"),
        )

    assert not (tmp_path / "artifact.bin").exists()
    assert not (tmp_path / "artifact.bin.json").exists()
