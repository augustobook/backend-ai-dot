"""Chat endpoints: ask a question and clear a conversation."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Response, status

from app.api.dependencies import get_chat_service
from app.api.schemas import MAX_SESSION_ID_LENGTH, ChatRequest, ChatResponse, ErrorResponse
from app.services.chat_service import ChatService

router = APIRouter(prefix="/chat", tags=["chat"])

ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]

# Documented in Swagger: errors raised by the LLM and mapped by the exception handlers.
LLM_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_409_CONFLICT: {
        "model": ErrorResponse,
        "description": (
            "The conversation reached its token limit (it no longer fits in the "
            "model's context window). Start a new conversation."
        ),
    },
    status.HTTP_429_TOO_MANY_REQUESTS: {
        "model": ErrorResponse,
        "description": "OpenAI rate limit or quota exceeded.",
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": ErrorResponse,
        "description": "LLM unavailable, invalid API key or API key not configured.",
    },
    status.HTTP_504_GATEWAY_TIMEOUT: {
        "model": ErrorResponse,
        "description": "OpenAI took too long to answer.",
    },
}


@router.post(
    "",
    summary="Ask the Python Tutor",
    description=(
        "Sends a question to the Python Tutor and returns the full answer (Markdown).\n\n"
        "- Send the same `session_id` to keep the conversation context (follow-up questions).\n"
        "- Omit `session_id` to start a new conversation; a new UUID is returned.\n"
        "- Questions outside Python programming are politely declined.\n"
        "- The answer is written in the same language as the question.\n"
        "- `message` accepts up to 5000 characters. The whole conversation is sent to "
        "the model; when it no longer fits in the context window, `409` is returned."
    ),
    responses=LLM_ERROR_RESPONSES,
)
async def chat(request: ChatRequest, service: ChatServiceDep) -> ChatResponse:
    """Answer a question within a conversation.

    Args:
        request: Session id (optional) and the question.
        service: Injected chat service.

    Returns:
        The session id (generated when missing) and the answer.

    Raises:
        ConversationLimitError: Converted to 409 by the exception handlers.
        LLMError: Converted to 429/503/504 by the exception handlers.
    """
    session_id = request.session_id or str(uuid.uuid4())
    answer = await service.aask(session_id, request.message, interface="api")
    usage = service.get_usage(session_id)
    return ChatResponse(
        session_id=session_id,
        answer=answer,
        conversation_usage_percent=usage.percent,
        near_conversation_limit=usage.near_limit,
    )


@router.delete(
    "/{session_id}",
    summary="Clear a conversation",
    description=(
        "Deletes the history of a conversation. The operation is idempotent: unknown "
        "sessions also return 204."
    ),
    status_code=status.HTTP_204_NO_CONTENT,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: LLM_ERROR_RESPONSES[503]},
)
async def clear_chat(
    session_id: Annotated[
        str, Path(min_length=1, max_length=MAX_SESSION_ID_LENGTH, description="Conversation id.")
    ],
    service: ChatServiceDep,
) -> Response:
    """Forget the history of a conversation.

    Args:
        session_id: Conversation to clear.
        service: Injected chat service.

    Returns:
        An empty 204 response.
    """
    service.clear_history(session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
