import asyncio

import pytest

from src.api.middleware import RateLimitMiddleware
from src.api.server import create_app


def run(coro):
    return asyncio.run(coro)


def base_scope():
    return {
        "type": "http",
        "method": "POST",
        "path": "/api/v2/agents",
        "headers": [],
        "client": ("203.0.113.10", 51992),
        "state": {},
    }


async def request(middleware, scope, receive=None):
    messages = []

    async def default_receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    await middleware(scope, receive or default_receive, send)
    return messages


def response_start(messages):
    return next(message for message in messages if message["type"] == "http.response.start")


def headers_from(message):
    return {key.decode(): value.decode() for key, value in message["headers"]}


def test_rate_limit_allows_request_and_adds_headers():
    async def app(scope, receive, send):
        assert scope["state"][RateLimitMiddleware._STATE_KEY]["client"] == "203.0.113.10"
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = RateLimitMiddleware(app, max_requests=2, window=30)
    scope = base_scope()

    messages = run(request(middleware, scope))

    start = response_start(messages)
    assert start["status"] == 204
    headers = headers_from(start)
    assert headers["x-ratelimit-limit"] == "2"
    assert headers["x-ratelimit-remaining"] == "1"
    assert "retry-after" not in headers
    assert RateLimitMiddleware._STATE_KEY not in scope["state"]


def test_rate_limit_rejects_before_reading_request_body():
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = RateLimitMiddleware(app, max_requests=1, window=30)
    run(request(middleware, base_scope()))

    async def body_receive():
        raise AssertionError("rejected requests must not consume the request body")

    rejected_scope = base_scope()
    messages = run(request(middleware, rejected_scope, body_receive))

    start = response_start(messages)
    body = next(message for message in messages if message["type"] == "http.response.body")
    headers = headers_from(start)
    assert start["status"] == 429
    assert body["body"] == b"Too many requests"
    assert headers["retry-after"] == "30"
    assert headers["x-ratelimit-remaining"] == "0"
    assert RateLimitMiddleware._STATE_KEY not in rejected_scope["state"]


def test_rate_limit_clears_state_when_downstream_raises():
    async def app(scope, receive, send):
        assert RateLimitMiddleware._STATE_KEY in scope["state"]
        raise RuntimeError("downstream failed")

    middleware = RateLimitMiddleware(app, max_requests=10, window=30)
    scope = base_scope()

    with pytest.raises(RuntimeError):
        run(request(middleware, scope))

    assert RateLimitMiddleware._STATE_KEY not in scope["state"]


def test_rate_limit_is_outermost_application_middleware():
    app = create_app()

    assert app.user_middleware[0].cls is RateLimitMiddleware
