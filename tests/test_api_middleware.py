import asyncio
import sys
import types

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import Response

try:
    import resource  # noqa: F401
except ModuleNotFoundError:
    sys.modules["resource"] = types.SimpleNamespace(
        RLIMIT_AS=0,
        RLIMIT_CPU=1,
        error=Exception,
        setrlimit=lambda *args, **kwargs: None,
    )

from src.api.middleware import AuthMiddleware
from src.api.server import create_app


def test_cors_preflight_is_allowed_without_auth():
    client = TestClient(create_app())

    response = client.options(
        "/api/v2/agents",
        headers={
            "Origin": "https://client.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://client.example"


def test_real_cors_request_without_auth_is_rejected():
    client = TestClient(create_app())

    response = client.get(
        "/api/v2/agents",
        headers={"Origin": "https://client.example"},
    )

    assert response.status_code == 401
    assert response.text == "Unauthorized"
    assert response.headers["access-control-allow-origin"] == "https://client.example"


def test_real_cors_request_with_auth_reaches_handler():
    client = TestClient(create_app())

    response = client.get(
        "/api/v2/agents",
        headers={
            "Origin": "https://client.example",
            "Authorization": "Bearer test-token",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://client.example"


def test_real_request_with_preflight_headers_does_not_bypass_auth():
    client = TestClient(create_app())

    response = client.get(
        "/api/v2/agents",
        headers={
            "Origin": "https://client.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 401


def test_auth_context_is_cleared_after_success():
    asyncio.run(_assert_auth_context_is_cleared_after_success())


async def _assert_auth_context_is_cleared_after_success():
    middleware = AuthMiddleware(app=None)
    request = _request("/api/v2/agents", authorization="Bearer test-token")

    async def call_next(received_request):
        assert received_request.state.auth_context == {"authenticated": True}
        return Response("ok")

    response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200
    assert not hasattr(request.state, "auth_context")


def test_auth_context_is_cleared_after_exception():
    asyncio.run(_assert_auth_context_is_cleared_after_exception())


async def _assert_auth_context_is_cleared_after_exception():
    middleware = AuthMiddleware(app=None)
    request = _request("/api/v2/agents", authorization="Bearer test-token")

    async def call_next(received_request):
        assert received_request.state.auth_context == {"authenticated": True}
        raise RuntimeError("handler failed")

    with pytest.raises(RuntimeError, match="handler failed"):
        await middleware.dispatch(request, call_next)

    assert not hasattr(request.state, "auth_context")


def _request(path, authorization=None):
    headers = []
    if authorization:
        headers.append((b"authorization", authorization.encode()))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "headers": headers,
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "scheme": "http",
        }
    )
