from fastapi.testclient import TestClient

from src.api.integration_endpoints import integration_endpoint_service
from src.api.server import create_app


def auth_headers():
    return {"Authorization": "Bearer test-token"}


def test_register_integration_endpoint_accepts_authorized_https_callback():
    app = create_app()
    client = TestClient(app)

    before = integration_endpoint_service.endpoint_count
    response = client.post(
        "/api/v2/integrations/endpoints",
        headers=auth_headers(),
        json={"name": "billing", "callback_url": "https://example.com/hooks/billing"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "registered"
    assert body["callback_url"] == "https://example.com/hooks/billing"
    assert integration_endpoint_service.endpoint_count == before + 1


def test_register_integration_endpoint_requires_authorization_before_service_mutation():
    app = create_app()
    client = TestClient(app)

    before = integration_endpoint_service.endpoint_count
    response = client.post(
        "/api/v2/integrations/endpoints",
        json={"name": "billing", "callback_url": "https://example.com/hooks/billing"},
    )

    assert response.status_code == 401
    assert integration_endpoint_service.endpoint_count == before


def test_register_integration_endpoint_rejects_malformed_callback_before_mutation():
    app = create_app()
    client = TestClient(app)

    before = integration_endpoint_service.endpoint_count
    response = client.post(
        "/api/v2/integrations/endpoints",
        headers=auth_headers(),
        json={"name": "billing", "callback_url": "http://127.0.0.1/internal"},
    )

    assert response.status_code == 422
    assert "https" in response.json()["detail"]
    assert integration_endpoint_service.endpoint_count == before


def test_register_integration_endpoint_rejects_private_ip_callback_before_mutation():
    app = create_app()
    client = TestClient(app)

    before = integration_endpoint_service.endpoint_count
    response = client.post(
        "/api/v2/integrations/endpoints",
        headers=auth_headers(),
        json={"name": "billing", "callback_url": "https://127.0.0.1/internal"},
    )

    assert response.status_code == 422
    assert "IP range" in response.json()["detail"]
    assert integration_endpoint_service.endpoint_count == before


def test_register_integration_endpoint_rejects_localhost_callback_before_mutation():
    app = create_app()
    client = TestClient(app)

    before = integration_endpoint_service.endpoint_count
    response = client.post(
        "/api/v2/integrations/endpoints",
        headers=auth_headers(),
        json={"name": "billing", "callback_url": "https://localhost/internal"},
    )

    assert response.status_code == 422
    assert integration_endpoint_service.endpoint_count == before


def test_register_integration_endpoint_rejects_private_ip_callback_before_mutation():
    app = create_app()
    client = TestClient(app)

    before = integration_endpoint_service.endpoint_count
    response = client.post(
        "/api/v2/integrations/endpoints",
        headers=auth_headers(),
        json={"name": "billing", "callback_url": "https://10.1.2.3/internal"},
    )

    assert response.status_code == 422
    assert integration_endpoint_service.endpoint_count == before
