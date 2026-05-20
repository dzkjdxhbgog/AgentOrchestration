"""API middleware components."""

import logging
import math
import time
from typing import Callable, List, Tuple
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path.startswith("/api/v2") and request.url.path != "/api/v2/auth/token":
            token = request.headers.get("Authorization", "")
            if not token.startswith("Bearer "):
                return Response(status_code=401, content="Unauthorized")
        return await call_next(request)


class RateLimitMiddleware:
    _STATE_KEY = "_rate_limit"

    def __init__(self, app, max_requests: int = 100, window: int = 60):
        self.app = app
        self.max_requests = max_requests
        self.window = window
        self._requests = {}

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        now = time.time()
        client_ip = self._client_ip(scope)
        requests = self._requests.setdefault(client_ip, [])
        requests[:] = [t for t in requests if now - t < self.window]
        state = scope.setdefault("state", {})
        state[self._STATE_KEY] = {"client": client_ip}

        try:
            if len(requests) >= self.max_requests:
                await self._send_rejection(send, self._reset_after(requests, now))
                return

            requests.append(now)
            remaining = max(self.max_requests - len(requests), 0)

            async def send_with_rate_headers(message) -> None:
                if message["type"] == "http.response.start":
                    headers = list(message.get("headers") or [])
                    headers.extend(self._raw_headers(remaining, self._reset_after(requests, time.time())))
                    message = {**message, "headers": headers}
                await send(message)

            await self.app(scope, receive, send_with_rate_headers)
        finally:
            state.pop(self._STATE_KEY, None)

    def _client_ip(self, scope) -> str:
        client = scope.get("client")
        return client[0] if client else "unknown"

    def _reset_after(self, requests: List[float], now: float) -> int:
        if not requests:
            return self.window
        return max(0, math.ceil(self.window - (now - requests[0])))

    def _raw_headers(self, remaining: int, reset_after: int) -> List[Tuple[bytes, bytes]]:
        return [
            (b"x-ratelimit-limit", str(self.max_requests).encode()),
            (b"x-ratelimit-remaining", str(remaining).encode()),
            (b"x-ratelimit-reset", str(reset_after).encode()),
        ]

    async def _send_rejection(self, send, reset_after: int) -> None:
        headers = [
            (b"content-type", b"text/plain; charset=utf-8"),
            (b"retry-after", str(reset_after).encode()),
            *self._raw_headers(0, reset_after),
        ]
        await send({"type": "http.response.start", "status": 429, "headers": headers})
        await send({"type": "http.response.body", "body": b"Too many requests"})


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.time()
        response = None
        try:
            response = await call_next(request)
            return response
        except Exception:
            duration = time.time() - start
            logger.exception(f"{request.method} {request.url.path} failed {duration:.3f}s")
            raise
        finally:
            if response is not None:
                duration = time.time() - start
                logger.info(f"{request.method} {request.url.path} {response.status_code} {duration:.3f}s")

# 2019-03-01T18:35:19 update

# 2019-04-03T13:22:05 update

# 2019-04-30T17:18:49 update

# 2019-08-20T09:29:03 update

# 2019-08-30T15:52:06 update

# 2019-11-23T16:58:42 update

# 2020-02-18T10:04:07 update

# 2020-04-21T17:35:30 update

# 2020-05-22T11:10:34 update

# 2020-07-02T12:31:26 update

# 2020-07-05T13:52:59 update

# 2020-08-21T20:36:45 update

# 2021-01-19T09:17:15 update

# 2021-01-29T11:34:24 update

# 2021-02-04T15:21:21 update

# 2021-04-19T19:23:15 update

# 2021-05-20T16:50:15 update

# 2021-06-22T19:23:44 update

# 2021-09-09T13:44:55 update

# 2021-09-16T09:30:20 update

# 2021-10-14T20:42:33 update

# 2021-12-28T16:39:14 update

# 2022-01-26T19:07:27 update

# 2022-01-28T08:03:41 update

# 2022-03-23T12:17:02 update

# 2022-04-06T12:12:27 update

# 2022-04-21T14:53:01 update

# 2022-06-30T08:37:32 update

# 2022-07-06T10:44:45 update

# 2022-11-02T11:12:47 update

# 2022-11-15T20:54:21 update

# 2022-11-23T14:13:34 update

# 2023-01-26T10:03:44 update

# 2023-02-09T17:08:10 update

# 2023-02-16T10:04:00 update

# 2023-03-14T11:52:03 update

# 2023-04-10T12:42:07 update

# 2023-04-26T10:43:39 update

# 2023-06-27T08:18:07 update

# 2023-08-30T15:30:40 update

# 2023-08-30T14:10:05 update

# 2023-10-09T18:32:46 update

# 2023-11-21T20:35:55 update

# 2024-03-07T19:17:39 update

# 2024-04-01T18:06:19 update

# 2024-07-18T15:37:34 update

# 2024-07-25T09:21:53 update

# 2024-08-12T14:24:22 update

# 2024-11-18T08:50:54 update

# 2025-04-08T12:43:05 update

# 2025-06-03T08:10:47 update

# 2025-06-12T08:37:52 update

# 2025-06-17T08:36:56 update

# 2025-07-02T18:09:42 update

# 2025-07-22T12:39:21 update

# 2025-10-13T12:13:46 update

# 2025-12-05T09:44:22 update

# 2025-12-22T18:34:47 update

# 2026-01-26T15:36:23 update

# 2026-02-13T12:36:40 update

# 2026-02-26T11:07:15 update

# 2026-03-19T11:00:17 update

# 2026-03-27T12:58:53 update

# 2026-05-12T17:19:36 update
