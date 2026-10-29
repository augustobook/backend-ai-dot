"""HTTP protection middleware: body size limit, rate limiting and security headers.

They are plain ASGI middleware (no `BaseHTTPMiddleware`), so they can inspect
the request body as it streams in and add headers to any response, including
error responses produced by other middleware.
"""

import logging
import math
import time
from collections.abc import Callable, Collection

from fastapi.responses import JSONResponse
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

# Interactive docs load scripts and styles from a CDN, so they cannot use the
# strict Content-Security-Policy applied to the JSON endpoints.
DOCS_PATHS = ("/docs", "/redoc")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Resource-Policy": "same-site",
}
API_CSP = "default-src 'none'; frame-ancestors 'none'"


class BodySizeLimitMiddleware:
    """Reject request bodies larger than `max_bytes` with HTTP 413.

    The `Content-Length` header is checked first; bodies sent without it
    (chunked transfer) are counted while they stream in, so the limit cannot
    be bypassed by omitting the header.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        """Initialize the middleware.

        Args:
            app: The wrapped ASGI application.
            max_bytes: Largest body accepted, in bytes.
        """
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process one ASGI call.

        Args:
            scope: The ASGI connection scope.
            receive: Channel to receive request messages.
            send: Channel to send response messages.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Fast path: a declared length above the limit is rejected before reading.
        content_length = dict(scope["headers"]).get(b"content-length")
        if (
            content_length is not None
            and content_length.isdigit()
            and int(content_length) > self.max_bytes
        ):
            await self._reject(scope, receive, send)
            return

        received = 0
        response_started = False
        rejected = False

        async def limited_receive() -> Message:
            nonlocal received, rejected
            if rejected:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes and not response_started:
                    # Answer 413 right away and tell the app the client left,
                    # so it stops reading; whatever it sends next is dropped.
                    rejected = True
                    await self._reject(scope, receive, send)
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal response_started
            if rejected:
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except Exception:
            # The app may raise because the "client disconnected"; the 413
            # has already been sent, so that error is expected and harmless.
            if not rejected:
                raise

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Send the 413 response.

        Args:
            scope: The ASGI connection scope.
            receive: Channel to receive request messages.
            send: Channel to send response messages.
        """
        logger.warning("Request body too large: path=%s", scope.get("path"))
        response = JSONResponse(
            {"detail": f"Request body too large (max {self.max_bytes} bytes)"},
            status_code=413,
        )
        await response(scope, receive, send)


class RateLimiter:
    """Fixed-window request counter per client.

    State lives in memory, so each process counts separately and counters reset
    on restart. For several workers or servers, enforce limits at a shared
    layer (reverse proxy, API gateway or Redis).
    """

    # Above this many tracked clients, expired windows are purged.
    _PURGE_THRESHOLD = 10_000

    def __init__(
        self,
        max_requests: int,
        window_seconds: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Initialize the limiter.

        Args:
            max_requests: Requests allowed per client in each window.
            window_seconds: Window length in seconds.
            clock: Monotonic clock, injectable for tests.
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._clock = clock
        self._windows: dict[str, tuple[float, int]] = {}

    def hit(self, key: str) -> tuple[bool, int, float]:
        """Register one request from a client.

        Args:
            key: Client identifier (its IP address).

        Returns:
            Whether the request is allowed, how many requests remain in the
            window and how many seconds until the window resets.
        """
        now = self._clock()
        if len(self._windows) > self._PURGE_THRESHOLD:
            self._purge(now)

        start, count = self._windows.get(key, (now, 0))
        if now - start >= self.window_seconds:
            start, count = now, 0
        count += 1
        self._windows[key] = (start, count)

        reset_in = max(start + self.window_seconds - now, 0.0)
        return count <= self.max_requests, max(self.max_requests - count, 0), reset_in

    def _purge(self, now: float) -> None:
        """Forget clients whose window has already expired.

        Args:
            now: Current clock value.
        """
        self._windows = {
            key: (start, count)
            for key, (start, count) in self._windows.items()
            if now - start < self.window_seconds
        }


class RateLimitMiddleware:
    """Answer HTTP 429 when a client exceeds the request rate."""

    def __init__(
        self, app: ASGIApp, limiter: RateLimiter, exempt_paths: Collection[str] = ()
    ) -> None:
        """Initialize the middleware.

        Args:
            app: The wrapped ASGI application.
            limiter: The shared request counter.
            exempt_paths: Paths never limited (e.g. the health check).
        """
        self.app = app
        self.limiter = limiter
        self.exempt_paths = set(exempt_paths)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process one ASGI call.

        Args:
            scope: The ASGI connection scope.
            receive: Channel to receive request messages.
            send: Channel to send response messages.
        """
        if scope["type"] != "http" or scope["path"] in self.exempt_paths:
            await self.app(scope, receive, send)
            return

        # Behind a reverse proxy this is the proxy's IP unless uvicorn runs
        # with --proxy-headers and a trusted --forwarded-allow-ips.
        client = scope.get("client")
        key = client[0] if client else "unknown"
        allowed, remaining, reset_in = self.limiter.hit(key)
        limit_headers = {
            "X-RateLimit-Limit": str(self.limiter.max_requests),
            "X-RateLimit-Remaining": str(remaining),
        }

        if not allowed:
            logger.warning("Rate limit exceeded: client=%s path=%s", key, scope["path"])
            response = JSONResponse(
                {"detail": "Too many requests. Try again later."},
                status_code=429,
                headers={**limit_headers, "Retry-After": str(math.ceil(reset_in))},
            )
            await response(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in limit_headers.items():
                    headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)


class SecurityHeadersMiddleware:
    """Add defensive HTTP headers to every response."""

    def __init__(self, app: ASGIApp) -> None:
        """Initialize the middleware.

        Args:
            app: The wrapped ASGI application.
        """
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process one ASGI call.

        Args:
            scope: The ASGI connection scope.
            receive: Channel to receive request messages.
            send: Channel to send response messages.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        is_docs = str(scope["path"]).startswith(DOCS_PATHS)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
                if not is_docs:
                    headers.setdefault("Content-Security-Policy", API_CSP)
            await send(message)

        await self.app(scope, receive, send_with_headers)
