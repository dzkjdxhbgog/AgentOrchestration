import time

import pytest
from fastapi.testclient import TestClient

from src.api.server import create_app
from src.common.auth import (
    AGENT_WORKER_AUDIENCE,
    Principal,
    auth_service,
)


WORKSPACE_ID = "workspace-a"


@pytest.fixture(autouse=True)
def reset_auth_service():
    auth_service.reset()
    yield
    auth_service.reset()


@pytest.fixture
def client():
    return TestClient(create_app())


def issue_token(
    *,
    audience=None,
    scopes=None,
    roles=None,
    ttl_seconds=300,
    token_id=None,
):
    return auth_service.issue_token(
        subject="worker-1",
        audience=audience or [AGENT_WORKER_AUDIENCE],
        scopes=scopes or ["agents:read", "agents:write"],
        workspace_roles=roles or {WORKSPACE_ID: ["worker"]},
        ttl_seconds=ttl_seconds,
        token_id=token_id,
    )


def auth_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "X-Workspace-ID": WORKSPACE_ID,
    }


def test_agent_worker_rejects_anonymous_request(client):
    response = client.get("/api/v2/agents", headers={
        "X-Workspace-ID": WORKSPACE_ID,
    })

    assert response.status_code == 401


def test_agent_worker_rejects_malformed_bearer_token(client):
    response = client.get(
        "/api/v2/agents",
        headers=auth_headers("not-a-jwt"),
    )

    assert response.status_code == 401


def test_agent_worker_rejects_stale_credentials(client):
    token = issue_token(ttl_seconds=-1)

    response = client.get("/api/v2/agents", headers=auth_headers(token))

    assert response.status_code == 401


def test_agent_worker_rejects_revoked_credentials(client):
    token = issue_token(token_id="revoked-token")
    auth_service.revoke_token("revoked-token")

    response = client.get("/api/v2/agents", headers=auth_headers(token))

    assert response.status_code == 401


def test_agent_worker_rejects_wrong_jwt_audience(client):
    token = issue_token(audience=["public-api"])

    response = client.get("/api/v2/agents", headers=auth_headers(token))

    assert response.status_code == 403


def test_agent_worker_rejects_insufficient_scope(client):
    token = issue_token(scopes=["agents:read"])

    response = client.post(
        "/api/v2/agents?name=worker&agent_type=worker.processor",
        headers=auth_headers(token),
    )

    assert response.status_code == 403


def test_agent_worker_rejects_insufficient_workspace_role(client):
    token = issue_token(roles={WORKSPACE_ID: ["viewer"]})

    response = client.get("/api/v2/agents", headers=auth_headers(token))

    assert response.status_code == 403


def test_authorized_worker_token_can_register_agent(client):
    token = issue_token()

    response = client.post(
        "/api/v2/agents?name=worker&agent_type=worker.processor",
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "registered"


def test_authorized_browser_session_can_read_agents(client):
    principal = Principal(
        subject="browser-user",
        audience=[AGENT_WORKER_AUDIENCE],
        scopes=["agents:read"],
        workspace_roles={WORKSPACE_ID: ["operator"]},
        expires_at=int(time.time()) + 300,
        token_id="session-token",
    )
    auth_service.register_session("session-1", principal)
    client.cookies.set("ao_session", "session-1")

    response = client.get(
        "/api/v2/agents",
        headers={"X-Workspace-ID": WORKSPACE_ID},
    )

    assert response.status_code == 200
    assert isinstance(response.json()["agents"], list)
