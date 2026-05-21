"""Artifact ingestion service with fail-closed upload size validation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Optional


DEFAULT_MAX_ARTIFACT_UPLOAD_BYTES = 1024 * 1024


class ArtifactIngestionError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class ArtifactUploadTooLarge(ArtifactIngestionError):
    def __init__(self, max_size: int):
        super().__init__(f"Artifact upload exceeds {max_size} bytes", status_code=413)


@dataclass
class ArtifactRecord:
    artifact_id: str
    workspace_id: str
    size: int


class ArtifactIngestionService:
    def __init__(self, max_upload_bytes: Optional[int] = None):
        self.max_upload_bytes = max_upload_bytes or _max_upload_bytes_from_env()
        self._artifacts: Dict[str, ArtifactRecord] = {}
        self.lookup_count = 0
        self.mutation_count = 0

    def validate_upload_size(self, content_length: Optional[str], actual_size: Optional[int] = None) -> int:
        if content_length is None:
            raise ArtifactIngestionError("Content-Length header is required", status_code=411)

        try:
            declared_size = int(content_length)
        except (TypeError, ValueError):
            raise ArtifactIngestionError("Content-Length header must be an integer", status_code=400)

        if declared_size < 0:
            raise ArtifactIngestionError("Content-Length header must be non-negative", status_code=400)

        if declared_size > self.max_upload_bytes:
            raise ArtifactUploadTooLarge(self.max_upload_bytes)

        if actual_size is not None and actual_size > self.max_upload_bytes:
            raise ArtifactUploadTooLarge(self.max_upload_bytes)

        return declared_size

    def ingest(self, workspace_id: str, artifact_id: str, payload: bytes, content_length: str) -> ArtifactRecord:
        self.validate_upload_size(content_length, len(payload))
        record_key = f"{workspace_id}:{artifact_id}"

        self.lookup_count += 1
        existing = self._artifacts.get(record_key)
        if existing:
            return existing

        record = ArtifactRecord(
            artifact_id=artifact_id,
            workspace_id=workspace_id,
            size=len(payload),
        )
        self._artifacts[record_key] = record
        self.mutation_count += 1
        return record

    def reset(self) -> None:
        self._artifacts.clear()
        self.lookup_count = 0
        self.mutation_count = 0


def _max_upload_bytes_from_env() -> int:
    raw_value = os.getenv("AO_MAX_ARTIFACT_UPLOAD_BYTES")
    if raw_value is None:
        return DEFAULT_MAX_ARTIFACT_UPLOAD_BYTES

    try:
        value = int(raw_value)
    except ValueError:
        return DEFAULT_MAX_ARTIFACT_UPLOAD_BYTES

    return value if value > 0 else DEFAULT_MAX_ARTIFACT_UPLOAD_BYTES


artifact_ingestion_service = ArtifactIngestionService()
