"""Tests of the HTTP security layer: keys, limits, origins, hosts and headers."""

from collections.abc import Iterator

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.dependencies import get_book_service
from app.api.middleware import RateLimiter
from tests.conftest import AppFactory
from tests.factories import make_book_payload

# --- API key ------------------------------------------------------------------


def test_api_key_disabled_by_default(client: TestClient) -> None:
    """Without `API_KEY` configured, requests need no key."""
    assert client.get("/books").status_code == 200


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}], ids=["missing", "wrong"])
def test_api_key_rejects_missing_or_wrong_key(
    make_client: AppFactory, headers: dict[str, str]
) -> None:
    """With `API_KEY` set, a missing or wrong key gets 401."""
    client = make_client(api_key="s3cret")

    response = client.get("/books", headers=headers)

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing API key"}
    assert response.headers["WWW-Authenticate"] == "ApiKey"


def test_api_key_accepts_correct_key(make_client: AppFactory) -> None:
    """With the correct key, reads and writes work."""
    client = make_client(api_key="s3cret")
    headers = {"X-API-Key": "s3cret"}

    assert client.post("/books", json=make_book_payload(), headers=headers).status_code == 201
    assert client.get("/books", headers=headers).status_code == 200


def test_health_does_not_require_api_key(make_client: AppFactory) -> None:
    """The health check stays public so orchestrators can probe it."""
    assert make_client(api_key="s3cret").get("/health").status_code == 200


# --- Input hardening ------------------------------------------------------------


def test_unknown_fields_are_rejected(client: TestClient) -> None:
    """Server-controlled fields such as `id` cannot be sent by the client."""
    response = client.post("/books", json=make_book_payload(id=999))

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "extra_forbidden"


def test_summary_longer_than_limit_is_rejected(client: TestClient) -> None:
    """Summaries are capped to keep rows (and responses) bounded."""
    response = client.post("/books", json=make_book_payload(summary="x" * 5001))

    assert response.status_code == 422


def test_body_larger_than_limit_returns_413(make_client: AppFactory) -> None:
    """A declared Content-Length above the limit is rejected before parsing."""
    client = make_client(max_request_body_bytes=1024)

    response = client.post(
        "/books", content=b"{" + b" " * 2048 + b"}", headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 413
    assert "too large" in response.json()["detail"]


def test_streamed_body_larger_than_limit_returns_413(make_client: AppFactory) -> None:
    """Bodies without Content-Length (chunked) are counted while streaming."""
    client = make_client(max_request_body_bytes=1024)

    def chunks() -> Iterator[bytes]:
        for _ in range(4):
            yield b" " * 512

    response = client.post("/books", content=chunks(), headers={"Content-Type": "application/json"})

    assert response.status_code == 413


# --- Rate limiting -------------------------------------------------------------


def test_rate_limit_returns_429_with_retry_after(make_client: AppFactory) -> None:
    """Requests above the per-client limit get 429 and a Retry-After header."""
    client = make_client(rate_limit_requests=2, rate_limit_window_seconds=60)

    first = client.get("/books")
    client.get("/books")
    blocked = client.get("/books")

    assert first.headers["X-RateLimit-Limit"] == "2"
    assert first.headers["X-RateLimit-Remaining"] == "1"
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0


def test_health_is_exempt_from_rate_limit(make_client: AppFactory) -> None:
    """The health check is never rate limited."""
    client = make_client(rate_limit_requests=1)

    assert all(client.get("/health").status_code == 200 for _ in range(3))


def test_rate_limit_can_be_disabled(make_client: AppFactory) -> None:
    """`RATE_LIMIT_REQUESTS=0` turns rate limiting off."""
    client = make_client(rate_limit_requests=0)

    responses = [client.get("/books") for _ in range(5)]

    assert all(response.status_code == 200 for response in responses)
    assert "X-RateLimit-Limit" not in responses[0].headers


def test_rate_limiter_resets_after_window() -> None:
    """The counter starts over once the window has passed."""
    now = [0.0]
    limiter = RateLimiter(max_requests=1, window_seconds=10, clock=lambda: now[0])

    assert limiter.hit("1.2.3.4")[0] is True
    assert limiter.hit("1.2.3.4")[0] is False
    assert limiter.hit("5.6.7.8")[0] is True
    now[0] = 10.0
    assert limiter.hit("1.2.3.4")[0] is True


def test_rate_limiter_purges_expired_clients() -> None:
    """Expired windows are dropped so memory does not grow without bound."""
    now = [0.0]
    limiter = RateLimiter(max_requests=1, window_seconds=1, clock=lambda: now[0])
    limiter._PURGE_THRESHOLD = 2
    for ip in ("a", "b", "c"):
        limiter.hit(ip)

    now[0] = 5.0
    limiter.hit("d")

    assert set(limiter._windows) == {"d"}


# --- Origins, hosts and headers ----------------------------------------------------


def test_cors_allows_configured_origin(make_client: AppFactory) -> None:
    """A preflight from an allowed origin is accepted."""
    client = make_client(cors_origins=["http://localhost:8050"])

    response = client.options(
        "/books",
        headers={
            "Origin": "http://localhost:8050",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type, X-API-Key",
        },
    )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:8050"


def test_cors_rejects_unknown_origin(make_client: AppFactory) -> None:
    """Browsers on other origins do not get CORS permission."""
    client = make_client(cors_origins=["http://localhost:8050"])

    response = client.get("/books", headers={"Origin": "http://evil.example"})

    assert "Access-Control-Allow-Origin" not in response.headers


def test_untrusted_host_is_rejected(make_client: AppFactory) -> None:
    """Requests with an unexpected Host header get 400."""
    client = make_client(allowed_hosts=["api.example.com"])

    assert client.get("/books").status_code == 400


def test_security_headers_are_present(client: TestClient) -> None:
    """Every response carries the defensive headers."""
    headers = client.get("/books").headers

    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert headers["Content-Security-Policy"].startswith("default-src 'none'")


def test_docs_page_has_no_strict_csp(client: TestClient) -> None:
    """The Swagger page keeps working (it loads assets from a CDN)."""
    response = client.get("/docs")

    assert response.status_code == 200
    assert "Content-Security-Policy" not in response.headers


def test_docs_can_be_disabled(make_client: AppFactory) -> None:
    """With `ENABLE_DOCS=false`, the docs and the schema are not served."""
    client = make_client(enable_docs=False)

    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_docs_hide_api_key_by_default(make_client: AppFactory) -> None:
    """The key never appears in the API schema unless explicitly allowed."""
    client = make_client(api_key="s3cret")

    assert "s3cret" not in client.get("/openapi.json").text


def test_docs_show_api_key_when_enabled(make_client: AppFactory) -> None:
    """With `DOCS_SHOW_API_KEY=true`, a public demo prints its key in the docs."""
    client = make_client(api_key="s3cret", docs_show_api_key=True)

    description = client.get("/openapi.json").json()["info"]["description"]

    assert "`s3cret`" in description


# --- Error handling -----------------------------------------------------------


def test_unexpected_error_returns_generic_500(make_client: AppFactory) -> None:
    """Unexpected exceptions never leak details to the client."""
    client = make_client(raise_server_exceptions=False)

    def broken_service() -> None:
        raise RuntimeError("database password is hunter2")

    client.app.dependency_overrides[get_book_service] = broken_service  # type: ignore[attr-defined]
    response = client.get("/books")

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert "hunter2" not in response.text


def test_http_exceptions_keep_their_status(make_client: AppFactory) -> None:
    """HTTP errors raised on purpose are not turned into 500s."""
    client = make_client(raise_server_exceptions=False)

    def forbidden_service() -> None:
        raise HTTPException(status_code=403, detail="Forbidden")

    client.app.dependency_overrides[get_book_service] = forbidden_service  # type: ignore[attr-defined]

    assert client.get("/books").status_code == 403
