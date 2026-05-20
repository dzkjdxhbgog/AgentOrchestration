import time

import pytest
from fastapi.testclient import TestClient

from src.api.server import create_app
from src.common.auth import AuthorizationError, Principal, require_webhook_management


def _headers(**overrides):
    headers = {
        "Authorization": "Bearer integration-token",
        "X-Principal-Id": "user-1",
        "X-Principal-Workspace": "workspace-1",
        "X-Principal-Roles": "operator",
        "X-Principal-Scopes": "webhooks:manage",
        "X-Principal-Expires-At": str(time.time() + 300),
    }
    headers.update(overrides)
    return headers


@pytest.mark.parametrize(
    "principal",
    [
        Principal(subject="anonymous", workspace_id="workspace-1"),
        Principal(subject="user-1", workspace_id="workspace-1", roles={"operator"}, scopes={"webhooks:manage"}, revoked=True),
        Principal(subject="user-1", workspace_id="workspace-1", roles={"operator"}, scopes={"webhooks:manage"}, disabled=True),
        Principal(
            subject="user-1",
            workspace_id="workspace-1",
            roles={"operator"},
            scopes={"webhooks:manage"},
            expires_at=99,
        ),
        Principal(subject="user-1", workspace_id="workspace-1", roles={"viewer"}, scopes={"webhooks:manage"}),
        Principal(subject="user-1", workspace_id="workspace-1", roles={"operator"}, scopes={"agents:read"}),
    ],
)
def test_webhook_management_denies_stale_and_insufficient_principals(principal):
    with pytest.raises(AuthorizationError):
        require_webhook_management(principal, "workspace-1", now=100)


def test_webhook_management_allows_workspace_operator():
    principal = Principal(
        subject="user-1",
        workspace_id="workspace-1",
        roles={"operator"},
        scopes={"webhooks:manage"},
        expires_at=101,
    )

    require_webhook_management(principal, "workspace-1", now=100)


def test_disabled_token_client_cannot_manage_webhooks():
    client = TestClient(create_app())

    response = client.post(
        "/api/v2/workspaces/workspace-1/webhooks",
        json={"url": "https://example.test/hook"},
        headers=_headers(**{"X-Principal-Disabled": "true"}),
    )

    assert response.status_code == 403
    assert "disabled" in response.json()["detail"]


@pytest.mark.parametrize(
    ("overrides", "expected_detail"),
    [
        ({"X-Principal-Id": "anonymous"}, "anonymous"),
        ({"X-Principal-Revoked": "true"}, "revoked"),
        ({"X-Principal-Expires-At": str(time.time() - 1)}, "expired"),
        ({"X-Principal-Roles": "viewer"}, "operator or admin"),
        ({"X-Principal-Scopes": "agents:read"}, "webhooks:manage"),
        ({"X-Principal-Workspace": "workspace-2"}, "not authorized"),
        ({"X-Principal-Expires-At": "not-a-timestamp"}, "malformed"),
    ],
)
def test_token_clients_with_stale_or_insufficient_state_cannot_manage_webhooks(overrides, expected_detail):
    client = TestClient(create_app())

    response = client.post(
        "/api/v2/workspaces/workspace-1/webhooks",
        json={"url": "https://example.test/hook"},
        headers=_headers(**overrides),
    )

    assert response.status_code == 403
    assert expected_detail in response.json()["detail"]


def test_anonymous_request_cannot_manage_webhooks():
    client = TestClient(create_app())

    response = client.post(
        "/api/v2/workspaces/workspace-1/webhooks",
        json={"url": "https://example.test/hook"},
    )

    assert response.status_code == 401


def test_authorized_token_client_can_manage_webhooks():
    client = TestClient(create_app())

    response = client.post(
        "/api/v2/workspaces/workspace-1/webhooks",
        json={"url": "https://example.test/hook"},
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.json()["actor"] == "user-1"


def test_browser_session_with_correct_role_can_manage_webhooks():
    client = TestClient(create_app())
    client.cookies.set("ao_session", "session-id")

    response = client.post(
        "/api/v2/workspaces/workspace-1/webhooks",
        json={"url": "https://example.test/hook"},
        headers={key: value for key, value in _headers().items() if key != "Authorization"},
    )

    assert response.status_code == 200
    assert response.json()["actor"] == "user-1"
