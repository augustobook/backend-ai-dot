"""FastAPI dependencies.

Endpoints receive `ChatService` through `Depends(get_chat_service)` and the rate
limiter through `Depends(get_rate_limiter)`, so tests can replace them via
`app.dependency_overrides`.
"""

from typing import Annotated

from fastapi import Depends, Request

from app.core.rate_limit import RateLimiter, get_default_rate_limiter, resolve_client_ip
from app.services.chat_service import ChatService, get_default_chat_service


def get_chat_service() -> ChatService:
    """Provide the shared chat service.

    Returns:
        The process-wide `ChatService`.

    Raises:
        MissingAPIKeyError: If `OPENAI_API_KEY` is not configured (answered as 503).
    """
    return get_default_chat_service()


def get_rate_limiter() -> RateLimiter:
    """Provide the shared rate limiter.

    Returns:
        The process-wide `RateLimiter`.
    """
    return get_default_rate_limiter()


def enforce_rate_limit(
    request: Request, limiter: Annotated[RateLimiter, Depends(get_rate_limiter)]
) -> None:
    """Count one question of the calling client, refusing it over the limit.

    Args:
        request: Incoming request (its peer and `X-Forwarded-For` identify the client).
        limiter: The shared rate limiter.

    Raises:
        RateLimitExceededError: If the client used up its limit (answered as 429).
    """
    peer = request.client.host if request.client else None
    limiter.check(resolve_client_ip(peer, request.headers.get("x-forwarded-for")))
