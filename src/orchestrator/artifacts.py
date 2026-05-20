"""Artifact ingestion service."""

import hashlib
import os
import re
from dataclasses import dataclass
from typing import Dict, Optional

from fastapi import HTTPException, Request, status


DEFAULT_MAX_ARTIFACT_UPLOAD_BYTES = int(
    os.getenv("MAX_ARTIFACT_UPLOAD_BYTES", str(5 * 1024 * 1024))
)
ARTIFACT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


@dataclass(frozen=True)
class StoredArtifact:
    artifact_id: str
    size: int
    content_type: str
    digest: str


class InMemoryArtifactStore:
    def __init__(self):
        self._artifacts: Dict[str, bytes] = {}

    def save(self, artifact_id: str, body: bytes, content_type: str) -> StoredArtifact:
        digest = hashlib.sha256(body).hexdigest()
        self._artifacts[artifact_id] = body
        return StoredArtifact(artifact_id, len(body), content_type, digest)

    def count(self) -> int:
        return len(self._artifacts)

    def clear(self) -> None:
        self._artifacts.clear()


artifact_store = InMemoryArtifactStore()


async def ingest_artifact_upload(
    request: Request,
    artifact_id: Optional[str] = None,
    *,
    workspace_id: Optional[str] = None,
    max_body_size: Optional[int] = None,
    store: Optional[InMemoryArtifactStore] = None,
) -> StoredArtifact:
    if max_body_size is None:
        max_body_size = DEFAULT_MAX_ARTIFACT_UPLOAD_BYTES
    if artifact_id is None:
        artifact_id = "default"

    _validate_identifier("artifact_id", artifact_id)
    if workspace_id is not None:
        _validate_identifier("workspace_id", workspace_id)

    body = await _read_limited_body(request, max_body_size)
    if not body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Artifact body is required",
        )

    active_store = store or artifact_store
    content_type = request.headers.get("content-type", "application/octet-stream")
    storage_id = artifact_id if workspace_id is None else f"{workspace_id}/{artifact_id}"
    return active_store.save(storage_id, body, content_type)


def _validate_identifier(field_name: str, value: str) -> None:
    if not ARTIFACT_ID_PATTERN.fullmatch(value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {field_name}",
        )


async def _read_limited_body(request: Request, max_body_size: int) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_size = int(content_length)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid Content-Length",
            ) from exc

        if declared_size < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid Content-Length",
            )
        if declared_size > max_body_size:
            raise HTTPException(status_code=413, detail="Artifact body too large")

    chunks = []
    total_size = 0
    async for chunk in request.stream():
        total_size += len(chunk)
        if total_size > max_body_size:
            raise HTTPException(status_code=413, detail="Artifact body too large")
        chunks.append(chunk)

    return b"".join(chunks)
