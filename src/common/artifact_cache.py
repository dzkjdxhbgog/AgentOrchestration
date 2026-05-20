"""Artifact download cache with digest-verified cache hits."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Callable, Optional


class ArtifactCacheError(Exception):
    """Raised when artifact cache metadata or digest input is invalid."""


@dataclass(frozen=True)
class CachedArtifact:
    key: str
    path: Path
    digest: str
    algorithm: str
    cache_hit: bool


Downloader = Callable[[Path], None]


class ArtifactDownloadCache:
    def __init__(self, cache_dir: str | Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_or_download(
        self,
        key: str,
        expected_digest: str,
        downloader: Downloader,
        *,
        algorithm: str = "sha256",
    ) -> CachedArtifact:
        algorithm = self._normalize_algorithm(algorithm)
        expected_digest = self._normalize_digest(expected_digest)
        artifact_path = self._artifact_path(key)
        metadata_path = self._metadata_path(key)

        if self._is_valid_cache_hit(artifact_path, metadata_path, expected_digest, algorithm):
            return CachedArtifact(key, artifact_path, expected_digest, algorithm, True)

        self._evict(artifact_path, metadata_path)
        self._download_atomically(artifact_path, downloader)
        actual_digest = self._file_digest(artifact_path, algorithm)
        if actual_digest != expected_digest:
            self._evict(artifact_path, metadata_path)
            raise ArtifactCacheError("downloaded artifact digest does not match metadata")

        self._write_metadata(metadata_path, expected_digest, algorithm)
        return CachedArtifact(key, artifact_path, expected_digest, algorithm, False)

    def _is_valid_cache_hit(
        self,
        artifact_path: Path,
        metadata_path: Path,
        expected_digest: str,
        algorithm: str,
    ) -> bool:
        if not artifact_path.exists() or not metadata_path.exists():
            return False
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if metadata.get("algorithm") != algorithm or metadata.get("digest") != expected_digest:
            return False
        try:
            return self._file_digest(artifact_path, algorithm) == expected_digest
        except OSError:
            return False

    def _download_atomically(self, artifact_path: Path, downloader: Downloader) -> None:
        with NamedTemporaryFile(dir=self.cache_dir, delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            downloader(tmp_path)
            if not tmp_path.exists() or tmp_path.stat().st_size == 0:
                raise ArtifactCacheError("downloaded artifact is empty or missing")
            tmp_path.replace(artifact_path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def _write_metadata(self, metadata_path: Path, digest: str, algorithm: str) -> None:
        metadata_path.write_text(
            json.dumps({"algorithm": algorithm, "digest": digest}, sort_keys=True),
            encoding="utf-8",
        )

    def _artifact_path(self, key: str) -> Path:
        return self.cache_dir / self._safe_key(key)

    def _metadata_path(self, key: str) -> Path:
        return self.cache_dir / f"{self._safe_key(key)}.json"

    def _safe_key(self, key: str) -> str:
        if not key or "/" in key or "\\" in key or key in {".", ".."}:
            raise ArtifactCacheError("cache key must be a non-path filename")
        return key

    def _evict(self, artifact_path: Path, metadata_path: Path) -> None:
        for path in (artifact_path, metadata_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def _file_digest(self, artifact_path: Path, algorithm: str) -> str:
        hasher = hashlib.new(algorithm)
        with artifact_path.open("rb") as artifact:
            for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _normalize_algorithm(self, algorithm: str) -> str:
        try:
            hashlib.new(algorithm)
        except ValueError as exc:
            raise ArtifactCacheError("unsupported digest algorithm") from exc
        return algorithm.lower()

    def _normalize_digest(self, digest: str) -> str:
        normalized = digest.strip().lower()
        if not normalized:
            raise ArtifactCacheError("expected digest is required")
        return normalized
