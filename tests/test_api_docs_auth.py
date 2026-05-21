from fastapi.testclient import TestClient

from src.api.server import create_app


AUTH_CONFIG = {
    "auth_tokens": {
        "docs-token": {
            "scopes": ["docs:read"],
            "roles": ["workspace:reader"],
        },
        "session-token": {
            "scopes": ["docs:read"],
            "roles": ["workspace:reader"],
        },
        "stale-token": {
            "scopes": ["docs:read"],
            "roles": ["workspace:reader"],
            "fresh": False,
        },
        "revoked-token": {
            "scopes": ["docs:read"],
            "roles": ["workspace:reader"],
            "revoked": True,
        },
        "missing-scope": {
            "scopes": [],
            "roles": ["workspace:reader"],
        },
        "missing-role": {
            "scopes": ["docs:read"],
            "roles": [],
        },
    },
}


def client():
    return TestClient(create_app(AUTH_CONFIG))


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_openapi_schema_rejects_anonymous_request():
    response = client().get("/api/openapi.json")

    assert response.status_code == 401
    assert "paths" not in response.text


def test_openapi_schema_rejects_malformed_bearer_token():
    response = client().get(
        "/api/openapi.json",
        headers={"Authorization": "Token docs-token"},
    )

    assert response.status_code == 401
    assert "paths" not in response.text


def test_openapi_schema_rejects_stale_and_revoked_credentials():
    stale = client().get("/api/openapi.json", headers=bearer("stale-token"))
    revoked = client().get(
        "/api/openapi.json",
        headers=bearer("revoked-token"),
    )

    assert stale.status_code == 401
    assert revoked.status_code == 401


def test_openapi_schema_rejects_insufficient_scope_or_role():
    no_scope = client().get(
        "/api/openapi.json",
        headers=bearer("missing-scope"),
    )
    no_role = client().get("/api/openapi.json", headers=bearer("missing-role"))

    assert no_scope.status_code == 403
    assert no_role.status_code == 403


def test_authorized_bearer_token_can_read_internal_schema():
    response = client().get("/api/openapi.json", headers=bearer("docs-token"))

    assert response.status_code == 200
    assert "/api/v2/agents" in response.json()["paths"]
    assert "/api/openapi.json" not in response.json()["paths"]


def test_authorized_session_cookie_can_read_docs_page():
    test_client = client()
    test_client.cookies.set("ao_session", "session-token")
    response = test_client.get("/api/docs")

    assert response.status_code == 200
    assert "/api/openapi.json" in response.text


def test_public_health_remains_available_without_docs_credentials():
    response = client().get("/health")

    assert response.status_code == 200
