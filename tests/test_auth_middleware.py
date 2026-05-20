import time
import importlib.util
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

middleware_path = Path(__file__).resolve().parents[1] / "src" / "api" / "middleware.py"
middleware_spec = importlib.util.spec_from_file_location("api_middleware", middleware_path)
api_middleware = importlib.util.module_from_spec(middleware_spec)
middleware_spec.loader.exec_module(api_middleware)

AuthMiddleware = api_middleware.AuthMiddleware
PermissionService = api_middleware.PermissionService


def build_client(permission_service):
    app = FastAPI()
    app.add_middleware(AuthMiddleware, permission_service=permission_service)

    @app.get("/api/v2/task-monitor/poll")
    async def poll_task_monitor(request: Request):
        return {"subject": request.state.principal.subject}

    @app.get("/api/v2/agents")
    async def list_agents(request: Request):
        return {"subject": request.state.principal.subject}

    return TestClient(app)


def test_task_monitor_revalidates_revoked_api_key_on_each_poll():
    service = PermissionService(allow_legacy_bearer=False)
    service.register_credential(
        "valid-token",
        subject="agent-operator",
        scopes={"task_monitor:read"},
        workspace_role="operator",
    )
    client = build_client(service)

    assert client.get("/api/v2/task-monitor/poll", headers={"Authorization": "Bearer valid-token"}).status_code == 200

    service.revoke_credential("valid-token")
    response = client.get("/api/v2/task-monitor/poll", headers={"Authorization": "Bearer valid-token"})

    assert response.status_code == 401


def test_task_monitor_rejects_anonymous_expired_disabled_and_insufficient_scope_principals():
    service = PermissionService(allow_legacy_bearer=False)
    service.register_credential(
        "expired-token",
        subject="expired",
        scopes={"task_monitor:read"},
        workspace_role="operator",
        expires_at=time.time() - 1,
    )
    service.register_credential(
        "disabled-token",
        subject="disabled",
        scopes={"task_monitor:read"},
        workspace_role="operator",
        disabled=True,
    )
    service.register_credential(
        "wrong-scope-token",
        subject="viewer",
        scopes={"agents:read"},
        workspace_role="operator",
    )
    client = build_client(service)

    assert client.get("/api/v2/task-monitor/poll").status_code == 401
    assert client.get("/api/v2/task-monitor/poll", headers={"Authorization": "Bearer expired-token"}).status_code == 401
    assert client.get("/api/v2/task-monitor/poll", headers={"Authorization": "Bearer disabled-token"}).status_code == 401
    assert client.get("/api/v2/task-monitor/poll", headers={"Authorization": "Bearer wrong-scope-token"}).status_code == 403


def test_task_monitor_rejects_user_without_workspace_role():
    service = PermissionService(allow_legacy_bearer=False)
    service.register_credential(
        "member-token",
        subject="workspace-member",
        scopes={"task_monitor:read"},
        workspace_role="viewer",
    )
    client = build_client(service)

    response = client.get("/api/v2/task-monitor/poll", headers={"Authorization": "Bearer member-token"})

    assert response.status_code == 403


def test_task_monitor_accepts_authorized_browser_session():
    service = PermissionService(allow_legacy_bearer=False)
    service.register_credential(
        "session-token",
        subject="browser-user",
        scopes={"task_monitor:read"},
        workspace_role="admin",
        client_type="browser",
    )
    client = build_client(service)
    client.cookies.set("ao_session", "session-token")

    response = client.get("/api/v2/task-monitor/poll")

    assert response.status_code == 200
    assert response.json() == {"subject": "browser-user"}


def test_regular_api_still_accepts_authorized_token_without_task_monitor_scope():
    service = PermissionService(allow_legacy_bearer=False)
    service.register_credential(
        "agent-token",
        subject="api-client",
        scopes={"agents:read"},
        workspace_role="viewer",
    )
    client = build_client(service)

    response = client.get("/api/v2/agents", headers={"Authorization": "Bearer agent-token"})

    assert response.status_code == 200
    assert response.json() == {"subject": "api-client"}
