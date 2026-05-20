from fastapi.testclient import TestClient

from src.api.server import create_app
from src.common.artifacts import ArtifactRecord, artifact_store


AUTH_HEADERS = {
    "Authorization": "Bearer test-token",
    "X-Workspace-Role": "member",
}


def setup_function():
    artifact_store.clear()


def _client() -> TestClient:
    return TestClient(create_app())


def _seed_artifact() -> None:
    artifact_store.upsert(
        ArtifactRecord(
            artifact_id="artifact-1",
            workspace_id="workspace-1",
            project_id="project-1",
            filename="result.txt",
            content="private build output",
        )
    )


def test_authorized_artifact_download_uses_scoped_lookup():
    _seed_artifact()
    response = _client().get(
        "/api/v2/workspaces/workspace-1/projects/project-1"
        "/artifacts/artifact-1/download",
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    assert response.json() == {
        "artifact_id": "artifact-1",
        "workspace_id": "workspace-1",
        "project_id": "project-1",
        "filename": "result.txt",
        "content": "private build output",
    }
    assert artifact_store.scoped_lookup_count == 1
    assert artifact_store.unsafe_lookup_count == 0


def test_cross_project_artifact_lookup_returns_404_without_unsafe_lookup():
    _seed_artifact()
    response = _client().get(
        "/api/v2/workspaces/workspace-1/projects/project-2"
        "/artifacts/artifact-1/download",
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Artifact not found"
    assert artifact_store.scoped_lookup_count == 1
    assert artifact_store.unsafe_lookup_count == 0


def test_unauthorized_role_returns_403_before_lookup():
    _seed_artifact()
    headers = {"Authorization": "Bearer test-token"}
    response = _client().get(
        "/api/v2/workspaces/workspace-1/projects/project-1"
        "/artifacts/artifact-1/download",
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Workspace role is not allowed"
    assert artifact_store.scoped_lookup_count == 0
    assert artifact_store.unsafe_lookup_count == 0


def test_malformed_artifact_id_returns_400_before_lookup():
    _seed_artifact()
    response = _client().get(
        "/api/v2/workspaces/workspace-1/projects/project-1"
        "/artifacts/bad..artifact/download",
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Malformed artifact_id"
    assert artifact_store.scoped_lookup_count == 0
    assert artifact_store.unsafe_lookup_count == 0
