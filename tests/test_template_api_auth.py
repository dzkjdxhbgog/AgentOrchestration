from fastapi.testclient import TestClient

from src.api import routes
from src.api.server import create_app


def client():
    routes.registry = routes.AgentRegistry()
    return TestClient(create_app())


def token_headers(**overrides):
    headers = {
        "Authorization": "Bearer active-token",
        "X-Workspace-ID": "workspace-1",
        "X-Role": "admin",
        "X-Token-Scopes": "template:clone",
        "X-User-ID": "user-1",
    }
    headers.update(overrides)
    return headers


def test_template_clone_denies_anonymous_principal_before_mutation():
    app_client = client()
    response = app_client.post("/api/v2/templates/starter/clone")

    assert response.status_code == 401
    assert routes.registry.count() == 0


def test_template_clone_denies_revoked_principal_before_mutation():
    app_client = client()
    response = app_client.post(
        "/api/v2/templates/starter/clone",
        headers=token_headers(**{"X-Credential-State": "revoked"}),
    )

    assert response.status_code == 401
    assert routes.registry.count() == 0


def test_template_clone_denies_stale_principal_before_mutation():
    app_client = client()
    response = app_client.post(
        "/api/v2/templates/starter/clone",
        headers=token_headers(**{"X-Credential-State": "stale"}),
    )

    assert response.status_code == 401
    assert routes.registry.count() == 0


def test_template_clone_denies_insufficient_scope_before_mutation():
    app_client = client()
    response = app_client.post(
        "/api/v2/templates/starter/clone",
        headers=token_headers(**{"X-Token-Scopes": "agents:read"}),
    )

    assert response.status_code == 403
    assert routes.registry.count() == 0


def test_template_clone_denies_insufficient_workspace_role_before_mutation():
    app_client = client()
    response = app_client.post(
        "/api/v2/templates/starter/clone",
        headers=token_headers(**{"X-Role": "viewer"}),
    )

    assert response.status_code == 403
    assert routes.registry.count() == 0


def test_template_clone_allows_authorized_token_principal():
    app_client = client()
    response = app_client.post(
        "/api/v2/templates/starter/clone?name=agent-from-template",
        headers=token_headers(),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "cloned"
    assert routes.registry.count() == 1
    cloned_agent = routes.registry.list()[0]
    assert cloned_agent["name"] == "agent-from-template"
    assert cloned_agent["config"]["workspace_id"] == "workspace-1"
    assert cloned_agent["config"]["auth_source"] == "token"


def test_template_clone_allows_authorized_browser_session():
    app_client = client()
    response = app_client.post(
        "/api/v2/templates/starter/clone",
        headers={
            "X-Session-ID": "session-1",
            "X-Workspace-ID": "workspace-1",
            "X-Role": "operator",
            "X-User-ID": "user-1",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "cloned"
    assert routes.registry.count() == 1
    assert routes.registry.list()[0]["config"]["auth_source"] == "browser"
