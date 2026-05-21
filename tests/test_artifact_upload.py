from fastapi.testclient import TestClient

from src.api.artifact_ingestion import artifact_ingestion_service
from src.api.server import create_app


def setup_function():
    artifact_ingestion_service.reset()
    artifact_ingestion_service.max_upload_bytes = 8


def test_authorized_artifact_upload_stores_record():
    client = TestClient(create_app())

    response = client.post(
        "/api/v2/workspaces/ws-1/artifacts/artifact-1/upload",
        content=b"payload",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "artifact_id": "artifact-1",
        "workspace_id": "ws-1",
        "size": 7,
        "status": "stored",
    }
    assert artifact_ingestion_service.lookup_count == 1
    assert artifact_ingestion_service.mutation_count == 1


def test_unauthorized_artifact_upload_never_reaches_ingestion_service():
    client = TestClient(create_app())

    response = client.post(
        "/api/v2/workspaces/ws-1/artifacts/artifact-1/upload",
        content=b"payload",
    )

    assert response.status_code == 401
    assert artifact_ingestion_service.lookup_count == 0
    assert artifact_ingestion_service.mutation_count == 0


def test_oversized_artifact_upload_fails_before_lookup_or_mutation():
    client = TestClient(create_app())

    response = client.post(
        "/api/v2/workspaces/ws-1/artifacts/artifact-1/upload",
        content=b"payload-is-too-large",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "Artifact upload exceeds 8 bytes"
    assert artifact_ingestion_service.lookup_count == 0
    assert artifact_ingestion_service.mutation_count == 0


def test_malformed_artifact_upload_content_length_fails_before_lookup_or_mutation():
    client = TestClient(create_app())

    response = client.post(
        "/api/v2/workspaces/ws-1/artifacts/artifact-1/upload",
        content=b"payload",
        headers={"Authorization": "Bearer token", "content-length": "not-an-int"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Content-Length header must be an integer"
    assert artifact_ingestion_service.lookup_count == 0
    assert artifact_ingestion_service.mutation_count == 0
