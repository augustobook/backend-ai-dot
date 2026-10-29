"""Request and response models of the API (validated by Pydantic)."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core.config import MAX_QUESTION_LENGTH

MAX_MESSAGE_LENGTH = MAX_QUESTION_LENGTH
MAX_SESSION_ID_LENGTH = 100

# Whitespace is stripped before validation, so "   " is rejected as empty (422).
Message = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_MESSAGE_LENGTH)
]
SessionId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=MAX_SESSION_ID_LENGTH,
        pattern=r"^[A-Za-z0-9_\-:.]+$",
    ),
]


class ChatRequest(BaseModel):
    """Body of `POST /chat`."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "session_id": "3f1c2a9e-5b7d-4c1e-9f0a-1b2c3d4e5f60",
                    "message": "How do I create a list in Python?",
                },
                {"message": "Como criar uma lista em Python?"},
            ]
        }
    )

    session_id: SessionId | None = Field(
        default=None,
        description="Conversation id. Omit it to start a new conversation (a UUID is generated).",
    )
    message: Message = Field(description="The user's question about Python.")


class ChatResponse(BaseModel):
    """Body returned by `POST /chat`."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "session_id": "3f1c2a9e-5b7d-4c1e-9f0a-1b2c3d4e5f60",
                    "answer": "A list is created with square brackets: `numbers = [1, 2, 3]`...",
                    "conversation_usage_percent": 3,
                    "near_conversation_limit": False,
                }
            ]
        }
    )

    session_id: str = Field(description="Conversation id; send it again to keep the context.")
    answer: str = Field(description="The tutor's answer, in Markdown.")
    conversation_usage_percent: int = Field(
        description="Share of the conversation's maximum size already in use (0-100)."
    )
    near_conversation_limit: bool = Field(
        description="True from 80% on: the client should suggest a new conversation soon."
    )


class HealthResponse(BaseModel):
    """Body returned by `GET /health`."""

    model_config = ConfigDict(json_schema_extra={"examples": [{"status": "ok"}]})

    status: str = Field(description="Always 'ok' when the API is running.")


class ErrorResponse(BaseModel):
    """Body of error responses produced by the domain exception handlers."""

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"detail": "The AI service is unavailable right now."}]}
    )

    detail: str = Field(description="Human-readable error message.")
