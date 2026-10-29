"""Dependency injection wiring and request-level security.

* `get_db` -> `get_book_repository` -> `get_book_service` builds the use cases.
* `require_api_key` protects routes when an API key is configured.
"""

import logging
import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import get_db
from app.repositories.book_repository import BookRepository, BookRepositoryProtocol
from app.services.book_service import BookService

logger = logging.getLogger(__name__)

API_KEY_HEADER = "X-API-Key"

api_key_header = APIKeyHeader(
    name=API_KEY_HEADER,
    auto_error=False,
    description="API key. Only required when the server is configured with `API_KEY`.",
)


def get_book_repository(db: Annotated[Session, Depends(get_db)]) -> BookRepositoryProtocol:
    """Build the book repository for the current request.

    Args:
        db: The request-scoped database session.

    Returns:
        A repository bound to the session.
    """
    return BookRepository(db)


def get_book_service(
    repository: Annotated[BookRepositoryProtocol, Depends(get_book_repository)],
) -> BookService:
    """Build the book service for the current request.

    Args:
        repository: The book repository.

    Returns:
        A service using the given repository.
    """
    return BookService(repository)


def require_api_key(
    request: Request, api_key: Annotated[str | None, Security(api_key_header)]
) -> None:
    """Reject the request unless it carries the configured API key.

    When `API_KEY` is not configured, every request is accepted, which keeps
    local development friction-free.

    Args:
        request: The current request (used to read the app settings).
        api_key: Value of the `X-API-Key` header, if any.

    Raises:
        HTTPException: 401 when an API key is configured and the header is
            missing or wrong.
    """
    settings: Settings = request.app.state.settings
    if settings.api_key is None:
        return
    expected = settings.api_key.get_secret_value().encode()
    # compare_digest takes the same time whatever the input, so the key
    # cannot be guessed character by character from response times.
    if api_key is None or not secrets.compare_digest(api_key.encode(), expected):
        logger.warning(
            "Rejected request with missing or invalid API key: path=%s", request.url.path
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )


BookServiceDep = Annotated[BookService, Depends(get_book_service)]
