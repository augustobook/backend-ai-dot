"""FastAPI dependencies.

Endpoints receive `ChatService` through `Depends(get_chat_service)`, so tests can
replace it with a fake-model service via `app.dependency_overrides`.
"""

from app.services.chat_service import ChatService, get_default_chat_service


def get_chat_service() -> ChatService:
    """Provide the shared chat service.

    Returns:
        The process-wide `ChatService`.

    Raises:
        MissingAPIKeyError: If `OPENAI_API_KEY` is not configured (answered as 503).
    """
    return get_default_chat_service()
