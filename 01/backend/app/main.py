"""Application factory: wires settings, lifespan, security, routers and exception handlers."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import Engine

from app.api.dependencies import API_KEY_HEADER, require_api_key
from app.api.middleware import (
    BodySizeLimitMiddleware,
    RateLimiter,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)
from app.api.routes import books, health
from app.core.config import Settings, get_settings
from app.core.exceptions import BookNotFoundError
from app.core.logging import configure_logging
from app.db.session import engine as default_engine
from app.db.session import init_db

logger = logging.getLogger(__name__)

API_DESCRIPTION = """
REST API for a virtual library.

* **Register books** with title, author, publication date, summary and registration time.
* **Search books** by partial, case-insensitive title and/or author, with pagination.
* **Get a book** by its id.

Security: requests are rate limited per client, bodies are size limited and, when the
server sets `API_KEY`, every `/books` request must send it in the `X-API-Key` header.
"""

TAGS_METADATA = [
    {"name": "books", "description": "Register, search and retrieve books."},
    {"name": "health", "description": "Operational endpoints."},
]

# The health check must keep answering under load so orchestrators do not
# restart a healthy container.
RATE_LIMIT_EXEMPT_PATHS = ("/health",)


async def book_not_found_handler(request: Request, exc: Exception) -> JSONResponse:
    """Convert `BookNotFoundError` into an HTTP 404 response.

    Args:
        request: The request that raised the error.
        exc: The raised `BookNotFoundError`.

    Returns:
        A 404 response with the standard `{"detail": ...}` body.
    """
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Hide unexpected errors behind a generic 500 response.

    The full traceback goes to the server log only; clients never see stack
    traces, SQL or file paths.

    Args:
        request: The request that raised the error.
        exc: The unexpected exception.

    Returns:
        A 500 response with a generic `{"detail": ...}` body.
    """
    logger.exception("Unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


def configure_security(app: FastAPI, settings: Settings) -> None:
    """Register the HTTP protection middleware.

    Starlette runs the middleware added last first, so the resulting order for
    an incoming request is: security headers -> trusted hosts -> CORS ->
    rate limit -> body size limit -> application. Headers are therefore added
    even to responses rejected by the inner layers.

    Args:
        app: The application to configure.
        settings: Security settings (origins, hosts, limits).
    """
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_body_bytes)
    if settings.rate_limit_requests > 0:
        app.add_middleware(
            RateLimitMiddleware,
            limiter=RateLimiter(settings.rate_limit_requests, settings.rate_limit_window_seconds),
            exempt_paths=RATE_LIMIT_EXEMPT_PATHS,
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        # The API is read/create only and uses no cookies, so nothing else is needed.
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", API_KEY_HEADER],
        allow_credentials=False,
        max_age=600,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    app.add_middleware(SecurityHeadersMiddleware)


def create_app(settings: Settings | None = None, db_engine: Engine | None = None) -> FastAPI:
    """Build and configure the FastAPI application.

    Args:
        settings: Settings to use. Defaults to the cached environment settings.
        db_engine: Engine where tables are created on startup. Defaults to the
            engine built from the environment settings.

    Returns:
        The configured application.
    """
    settings = settings or get_settings()
    bind = db_engine or default_engine
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Create the database tables before the application starts serving.

        Args:
            app: The application being started.

        Yields:
            Control to the running application.
        """
        init_db(bind)
        if settings.api_key is None:
            logger.warning("API_KEY is not set: /books endpoints accept unauthenticated requests")
        yield

    # Docs can be switched off in production to avoid publishing the API surface.
    docs_enabled = settings.enable_docs
    app = FastAPI(
        title=settings.app_name,
        description=API_DESCRIPTION,
        version=settings.app_version,
        openapi_tags=TAGS_METADATA,
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    # Request-time dependencies (such as the API key check) read settings from here.
    app.state.settings = settings

    configure_security(app, settings)
    app.include_router(health.router)
    app.include_router(books.router, dependencies=[Depends(require_api_key)])
    app.add_exception_handler(BookNotFoundError, book_not_found_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
    return app


app = create_app()
