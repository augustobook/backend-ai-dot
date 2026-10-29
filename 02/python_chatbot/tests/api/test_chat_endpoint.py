"""Tests of the HTTP API (`/chat` and `/health`)."""

import uuid
from collections.abc import Callable, Iterator

import openai
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage

from app.api.dependencies import get_chat_service
from app.api.main import create_app
from app.api.schemas import MAX_MESSAGE_LENGTH
from app.core.exceptions import MissingAPIKeyError
from app.services.chat_service import ChatService
from tests.conftest import (
    RecordingFakeChatModel,
    make_authentication_error,
    make_connection_error,
    make_rate_limit_error,
    make_timeout_error,
)


@pytest.fixture
def app(chat_service: ChatService) -> Iterator[FastAPI]:
    """Application whose ChatService uses the fake model."""
    application = create_app()
    application.dependency_overrides[get_chat_service] = lambda: chat_service
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """HTTP client for the application."""
    return TestClient(app)


# --- POST /chat -----------------------------------------------------------------


def test_chat_with_session_id_returns_answer(client: TestClient) -> None:
    """The answer is returned with the same session id."""
    response = client.post("/chat", json={"session_id": "abc-1", "message": "What is a list?"})

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "abc-1"
    assert body["answer"] == "Answer 1"
    assert 0 <= body["conversation_usage_percent"] < 80
    assert body["near_conversation_limit"] is False


def test_chat_reports_when_conversation_is_near_the_limit(
    app: FastAPI, make_model: Callable[..., RecordingFakeChatModel]
) -> None:
    """The response flags conversations at 80% or more of their size."""
    service = ChatService(model=make_model(["a"]), max_conversation_tokens=5, token_counter=len)
    app.dependency_overrides[get_chat_service] = lambda: service

    body = TestClient(app).post("/chat", json={"message": "First question"}).json()

    assert body["conversation_usage_percent"] == 80
    assert body["near_conversation_limit"] is True


def test_chat_without_session_id_generates_a_uuid(client: TestClient) -> None:
    """A new conversation gets a freshly generated UUID."""
    response = client.post("/chat", json={"message": "What is a list?"})

    assert response.status_code == 200
    session_id = response.json()["session_id"]
    assert str(uuid.UUID(session_id)) == session_id


def test_chat_keeps_context_for_the_same_session(
    client: TestClient, fake_model: RecordingFakeChatModel
) -> None:
    """A follow-up question is sent with the previous turn of the session."""
    first = client.post("/chat", json={"message": "How do I create a list?"}).json()
    client.post(
        "/chat", json={"session_id": first["session_id"], "message": "And how do I add items?"}
    )

    assert HumanMessage("How do I create a list?") in fake_model.received[1]


def test_chat_strips_message_whitespace(
    client: TestClient, fake_model: RecordingFakeChatModel
) -> None:
    """Leading/trailing whitespace is removed before reaching the model."""
    client.post("/chat", json={"message": "  What is a tuple?  "})

    assert fake_model.received[0][-1] == HumanMessage("What is a tuple?")


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"message": ""}, id="empty"),
        pytest.param({"message": "   "}, id="blank"),
        pytest.param({}, id="missing"),
        pytest.param({"message": "x" * (MAX_MESSAGE_LENGTH + 1)}, id="too-long"),
        pytest.param({"session_id": "has spaces", "message": "Hi"}, id="bad-session-id"),
    ],
)
def test_chat_rejects_invalid_bodies(
    client: TestClient, fake_model: RecordingFakeChatModel, body: dict[str, str]
) -> None:
    """Invalid requests return 422 and never reach the model."""
    response = client.post("/chat", json=body)

    assert response.status_code == 422
    assert fake_model.received == []


@pytest.mark.parametrize(
    ("make_error", "status_code"),
    [
        pytest.param(make_connection_error, 503, id="connection"),
        pytest.param(make_authentication_error, 503, id="authentication"),
        pytest.param(make_rate_limit_error, 429, id="rate-limit"),
        pytest.param(make_timeout_error, 504, id="timeout"),
    ],
)
def test_chat_converts_llm_failures_into_http_errors(
    app: FastAPI,
    make_model: Callable[..., RecordingFakeChatModel],
    make_error: Callable[[], openai.OpenAIError],
    status_code: int,
) -> None:
    """LLM failures become HTTP errors with a friendly `detail`."""
    failing_service = ChatService(model=make_model(error=make_error()))
    app.dependency_overrides[get_chat_service] = lambda: failing_service

    response = TestClient(app).post("/chat", json={"message": "What is a list?"})

    assert response.status_code == status_code
    assert response.json()["detail"]
    assert "Traceback" not in response.text


def test_chat_accepts_questions_up_to_5000_characters(client: TestClient) -> None:
    """The maximum question size is 5000 characters."""
    assert MAX_MESSAGE_LENGTH == 5000
    response = client.post("/chat", json={"message": "x" * 5000})

    assert response.status_code == 200


def test_chat_returns_409_when_conversation_is_full(
    app: FastAPI, make_model: Callable[..., RecordingFakeChatModel]
) -> None:
    """A conversation above its token budget is refused with 409."""
    full_service = ChatService(model=make_model(), max_conversation_tokens=3, token_counter=len)
    app.dependency_overrides[get_chat_service] = lambda: full_service
    client = TestClient(app)

    first = client.post("/chat", json={"session_id": "s1", "message": "First question"})
    second = client.post("/chat", json={"session_id": "s1", "message": "Second question"})

    assert first.status_code == 200
    assert second.status_code == 409
    assert "new conversation" in second.json()["detail"]


def test_chat_returns_503_when_api_key_is_missing(app: FastAPI) -> None:
    """A missing OPENAI_API_KEY is reported as 503 with setup instructions."""

    def _missing_key() -> ChatService:
        raise MissingAPIKeyError()

    app.dependency_overrides[get_chat_service] = _missing_key

    response = TestClient(app).post("/chat", json={"message": "What is a list?"})

    assert response.status_code == 503
    assert "OPENAI_API_KEY" in response.json()["detail"]


# --- DELETE /chat/{session_id} ----------------------------------------------------


def test_delete_chat_clears_the_history(client: TestClient, chat_service: ChatService) -> None:
    """DELETE removes the history of the session and returns 204."""
    client.post("/chat", json={"session_id": "abc-1", "message": "What is a list?"})

    response = client.delete("/chat/abc-1")

    assert response.status_code == 204
    assert response.content == b""
    assert chat_service.get_history("abc-1") == []


def test_delete_unknown_session_is_idempotent(client: TestClient) -> None:
    """Deleting a session that does not exist also returns 204."""
    assert client.delete("/chat/never-used").status_code == 204


# --- GET /health and docs ---------------------------------------------------------


def test_health_returns_ok(client: TestClient) -> None:
    """The health check answers without calling the LLM."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_documents_the_endpoints(client: TestClient) -> None:
    """Swagger exposes the endpoints with summaries and error responses."""
    paths = client.get("/openapi.json").json()["paths"]

    assert paths["/chat"]["post"]["summary"] == "Ask the Python Tutor"
    assert {"409", "429", "503", "504"} <= set(paths["/chat"]["post"]["responses"])
    assert paths["/chat/{session_id}"]["delete"]["summary"] == "Clear a conversation"
    assert paths["/health"]["get"]["summary"] == "Health check"
