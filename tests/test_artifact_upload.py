from fastapi.testclient import TestClient

from src.api.server import create_app
from src.orchestrator.artifacts import artifact_store


AUTH_HEADERS = {"Authorization": "Bearer test-token"}


def setup_function():
    artifact_store.clear()


def test_authorized_artifact_upload_is_stored():
    client = TestClient(create_app())

    response = client.post(
        "/api/v2/artifacts",
        content=b"artifact-bytes",
        headers={**AUTH_HEADERS, "content-type": "application/octet-stream"},
    )

    assert response.status_code == 201
    assert response.json()["size"] == len(b"artifact-bytes")
    assert response.json()["content_type"] == "application/octet-stream"
    assert artifact_store.count() == 1


def test_unauthorized_artifact_upload_does_not_store():
    client = TestClient(create_app())

    response = client.post("/api/v2/artifacts", content=b"artifact-bytes")

    assert response.status_code == 401
    assert artifact_store.count() == 0


def test_empty_artifact_upload_is_rejected_before_store():
    client = TestClient(create_app())

    response = client.post("/api/v2/artifacts", content=b"", headers=AUTH_HEADERS)

    assert response.status_code == 400
    assert artifact_store.count() == 0


def test_oversized_artifact_upload_is_rejected_before_store(monkeypatch):
    monkeypatch.setattr(
        "src.orchestrator.artifacts.DEFAULT_MAX_ARTIFACT_UPLOAD_BYTES",
        4,
    )
    client = TestClient(create_app())

    response = client.post("/api/v2/artifacts", content=b"12345", headers=AUTH_HEADERS)

    assert response.status_code == 413
    assert artifact_store.count() == 0
