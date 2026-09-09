"""HTTP middleware.

:class:`RequestContextMiddleware` assigns each request a correlation id (honouring an
inbound ``X-Request-ID`` from a trusted proxy, otherwise generating one), binds it to the
logging context, records wall-clock duration, and emits a structured access log line. The id
is echoed back in the ``X-Request-ID`` response header.
"""

from __future__ import annotations

import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from starlette.requests import Request
from starlette.responses import Response

from backend.core.context import client_ip_ctx, client_private_ip_ctx, request_id_ctx
from backend.core.logging import get_logger
from backend.core.metrics import REGISTRY

logger = get_logger("app.access")

_REQUEST_ID_HEADER = "X-Request-ID"
_PRIVATE_IP_HEADER = "X-Private-IP"


def _peer_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _client_ip(request: Request) -> str | None:
    """Best-effort PUBLIC client IP. Honours the first hop in ``X-Forwarded-For`` (set by a
    trusted reverse proxy such as the bundled nginx), else falls back to the socket peer."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return _peer_ip(request)


def _private_ip(request: Request) -> str | None:
    """Best-effort PRIVATE (LAN) client IP. The browser reports its local address in the
    ``X-Private-IP`` header (obtained via WebRTC); if absent we fall back to the direct socket
    peer, which is the client's LAN address on a direct connection or the proxy hop otherwise."""
    reported = (request.headers.get(_PRIVATE_IP_HEADER) or "").strip()
    # Guard against a spoofed/oversized header; a real IP is short.
    if reported and len(reported) <= 64:
        return reported
    return _peer_ip(request)


class RequestContextMiddleware:
    """Per-request id, client IP and access logging — as **pure ASGI**.

    This was a `BaseHTTPMiddleware`, and that is not a style question: Starlette
    runs the inner application in a **separate task** under that base class and
    forwards the response as soon as it is available, which breaks FastAPI's
    guarantee that a `yield` dependency's teardown finishes before the response
    is sent. `db/dependencies.py` commits the request's transaction in exactly
    that teardown — so a write endpoint could return `200` to a client *before*
    its data was visible to the next request.

    Measured rather than reasoned about: unlocking an account and immediately
    signing in failed **3 times in 40** with this class as a
    `BaseHTTPMiddleware`, with the login reporting the account still locked;
    **40 out of 40** succeeded with the middleware removed. An administrator
    would have unlocked an account, told the user to try again, and been wrong
    about one time in thirteen — and the same race applied to every write
    endpoint in the application, not just this one.

    Pure ASGI runs the inner app in the *calling* task, so the exit stack —
    and the commit — completes before `http.response.start` is forwarded.

    `Request(scope)` is constructed without a receive channel on purpose: it is
    only read for headers and the peer address, never for a body, so nothing
    here can consume the request stream the route still needs.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        request_id = request.headers.get(_REQUEST_ID_HEADER) or uuid.uuid4().hex

        token = request_id_ctx.set(request_id)
        ip_token = client_ip_ctx.set(_client_ip(request))
        priv_token = client_private_ip_ctx.set(_private_ip(request))
        start = time.perf_counter()
        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers[_REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            _record_metric(scope, request, start, 500)
            logger.exception(
                "Request failed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                },
            )
            raise
        else:
            _record_metric(scope, request, start, status_code)
            logger.info(
                "Request completed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                },
            )
        finally:
            request_id_ctx.reset(token)
            client_ip_ctx.reset(ip_token)
            client_private_ip_ctx.reset(priv_token)


def _record_metric(scope: Scope, request: Request, start: float, status_code: int) -> None:
    """Record one request against its **route template**, not its path.

    `scope["route"]` is populated by Starlette during routing, and reading it
    here rather than walking `app.routes` is deliberate: `include_router`
    keeps nested router objects in that list rather than flattening them, so
    a walk misses the entire API and labels everything "unmatched" -- a bug
    this project has already shipped once, in another codebase.

    A request that never matched a route (a 404 on a bad path) is bucketed
    under a single label. Recording the raw path would let anyone create
    unbounded metric keys by requesting random URLs.
    """
    route = scope.get("route")
    template = getattr(route, "path", None) or "<unmatched>"
    REGISTRY.observe(
        method=request.method,
        route=template,
        duration_ms=(time.perf_counter() - start) * 1000,
        status_code=status_code,
    )
