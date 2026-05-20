import importlib.util
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient


_MIDDLEWARE_PATH = Path(__file__).resolve().parents[1] / "src" / "api" / "middleware.py"
_SPEC = importlib.util.spec_from_file_location("api_middleware", _MIDDLEWARE_PATH)
_MIDDLEWARE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MIDDLEWARE)
AuthMiddleware = _MIDDLEWARE.AuthMiddleware


def build_client(raise_server_exceptions=True):
    app = FastAPI()

    @app.get("/api/v2/protected")
    async def protected(request: Request):
        auth_context = getattr(request.state, "auth_context", {})
        return {"authenticated": auth_context.get("authenticated", False)}

    @app.get("/api/v2/fails")
    async def fails():
        raise RuntimeError("boom")

    app.add_middleware(AuthMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://client.example"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def test_cors_preflight_reaches_cors_without_auth():
    client = build_client()

    response = client.options(
        "/api/v2/protected",
        headers={
            "Origin": "https://client.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://client.example"


def test_real_cors_request_still_requires_auth():
    client = build_client()

    response = client.get(
        "/api/v2/protected",
        headers={"Origin": "https://client.example"},
    )

    assert response.status_code == 401
    assert response.text == "Unauthorized"
    assert response.headers["access-control-allow-origin"] == "https://client.example"


def test_plain_options_is_not_treated_as_preflight():
    client = build_client()

    response = client.options(
        "/api/v2/protected",
        headers={"Origin": "https://client.example"},
    )

    assert response.status_code == 401


def test_authenticated_request_sets_request_local_auth_context():
    client = build_client()

    response = client.get(
        "/api/v2/protected",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    assert response.json() == {"authenticated": True}


def test_auth_context_is_cleared_after_exception_path():
    client = build_client(raise_server_exceptions=False)

    response = client.get(
        "/api/v2/fails",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 500

    response = client.get("/api/v2/protected")
    assert response.status_code == 401
