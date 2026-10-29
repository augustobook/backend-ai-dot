"""FastAPI application factory and domain exception handlers.

Run with:  uv run uvicorn app.api.main:app --reload
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app import __version__
from app.api.routes import chat, health
from app.core.config import get_settings
from app.core.exceptions import ChatbotError, RateLimitExceededError
from app.core.logging import configure_logging
from app.core.tracing import configure_tracing

logger = logging.getLogger(__name__)

DESCRIPTION = """\
REST API of the **Python Tutor**, a chatbot that answers questions about Python
programming using LangChain and an OpenAI GPT-4 family model.

* Keeps the context of each conversation through `session_id`.
* Answers in the language of the question.
* Declines questions that are not about Python.
"""


async def chatbot_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Convert domain exceptions into JSON error responses.

    Each `ChatbotError` defines its own status code (e.g. 503 when the LLM is
    unavailable) and a message that is safe to expose to clients.

    Args:
        request: Request that failed.
        exc: The raised exception (always a `ChatbotError`).

    Returns:
        A JSON response `{"detail": "..."}` with the error's status code.
    """
    # Starlette types handlers with a generic `Exception`; anything else re-raises.
    if not isinstance(exc, ChatbotError):
        raise exc
    logger.warning(
        "%s %s failed with %s (%s).",
        request.method,
        request.url.path,
        type(exc).__name__,
        exc.status_code,
    )
    # Tell rate-limited clients when they may ask again (standard HTTP header).
    headers = (
        {"Retry-After": str(exc.retry_after)} if isinstance(exc, RateLimitExceededError) else None
    )
    return JSONResponse(
        status_code=exc.status_code, content={"detail": exc.user_message}, headers=headers
    )


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        The application, with routers and exception handlers registered.
    """
    settings = get_settings()
    configure_logging(settings.log_level)
    configure_tracing(settings)

    app = FastAPI(title="Python Tutor API", description=DESCRIPTION, version=__version__)
    app.include_router(health.router)
    app.include_router(chat.router)
    # A single handler covers every domain error (missing key, LLM failures...).
    app.add_exception_handler(ChatbotError, chatbot_error_handler)
    return app


app = create_app()
