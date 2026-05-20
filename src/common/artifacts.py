"""Artifact download access controls."""

from dataclasses import dataclass
import re
from typing import Dict, Optional, Tuple


SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
ALLOWED_ROLES = {"viewer", "member", "admin"}


class ArtifactAccessError(Exception):
    """HTTP-facing artifact access failure."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    workspace_id: str
    project_id: str
    filename: str
    content: str


class ArtifactStore:
    def __init__(self):
        self._records: Dict[Tuple[str, str, str], ArtifactRecord] = {}
        self.scoped_lookup_count = 0
        self.unsafe_lookup_count = 0

    def clear(self) -> None:
        self._records.clear()
        self.scoped_lookup_count = 0
        self.unsafe_lookup_count = 0

    def upsert(self, record: ArtifactRecord) -> None:
        key = (record.workspace_id, record.project_id, record.artifact_id)
        self._records[key] = record

    def get_scoped(
        self,
        workspace_id: str,
        project_id: str,
        artifact_id: str,
    ) -> Optional[ArtifactRecord]:
        self.scoped_lookup_count += 1
        return self._records.get((workspace_id, project_id, artifact_id))

    def get_unscoped(self, artifact_id: str) -> Optional[ArtifactRecord]:
        self.unsafe_lookup_count += 1
        for record in self._records.values():
            if record.artifact_id == artifact_id:
                return record
        return None


artifact_store = ArtifactStore()


def _validate_identifier(name: str, value: str) -> None:
    if not value or not SAFE_IDENTIFIER.fullmatch(value) or ".." in value:
        raise ArtifactAccessError(400, f"Malformed {name}")


def _validate_role(role: Optional[str]) -> str:
    if role not in ALLOWED_ROLES:
        raise ArtifactAccessError(403, "Workspace role is not allowed")
    return role


def download_artifact(
    *,
    workspace_id: str,
    project_id: str,
    artifact_id: str,
    role: Optional[str],
    store: ArtifactStore = artifact_store,
) -> ArtifactRecord:
    """Return an artifact only after workspace, project, and role checks."""

    _validate_identifier("workspace_id", workspace_id)
    _validate_identifier("project_id", project_id)
    _validate_identifier("artifact_id", artifact_id)
    _validate_role(role)

    record = store.get_scoped(workspace_id, project_id, artifact_id)
    if record is None:
        raise ArtifactAccessError(404, "Artifact not found")
    return record
