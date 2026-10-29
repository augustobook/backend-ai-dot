"""Shared fixtures.

No test talks to OpenAI: the chain receives `RecordingFakeChatModel`, a subclass of
LangChain's `FakeListChatModel` that also records the messages it receives (to
assert history handling) and can simulate OpenAI errors.
"""

from collections.abc import AsyncIterator, Callable, Iterator
from io import StringIO
from typing import Any

# The OpenAI SDK (v3) builds its errors on `httpx2` objects, not `httpx`.
import httpx2
import openai
import pytest
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGenerationChunk
from pydantic import Field
from rich.console import Console

from app.core.config import Settings
from app.services.chat_service import ChatService

OPENAI_URL = "https://api.openai.com/v1/chat/completions"


class RecordingFakeChatModel(FakeListChatModel):
    """Fake chat model that records its inputs and can raise a given error.

    Attributes:
        received: Messages received on each call, in order.
        error: Exception raised on every call when set.
    """

    received: list[list[BaseMessage]] = Field(default_factory=list)
    error: Exception | None = None

    def _record(self, messages: list[BaseMessage]) -> None:
        """Store the messages and raise the configured error, if any."""
        self.received.append(list(messages))
        if self.error is not None:
            raise self.error

    def _call(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> str:
        """Record the call and return the next fake response."""
        self._record(messages)
        return super()._call(messages, stop, run_manager, **kwargs)

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        """Record the call and stream the next fake response char by char."""
        self._record(messages)
        yield from super()._stream(messages, stop, run_manager, **kwargs)

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Async version of `_stream`."""
        self._record(messages)
        async for chunk in super()._astream(messages, stop, run_manager, **kwargs):
            yield chunk


# --- OpenAI error factories ------------------------------------------------------


def _request() -> httpx2.Request:
    """Build a dummy request to the OpenAI endpoint."""
    return httpx2.Request("POST", OPENAI_URL)


def _response(status_code: int) -> httpx2.Response:
    """Build a dummy OpenAI response with the given status code."""
    return httpx2.Response(status_code, request=_request())


def make_authentication_error() -> openai.OpenAIError:
    """Simulate an invalid API key (401)."""
    return openai.AuthenticationError("Invalid API key", response=_response(401), body=None)


def make_rate_limit_error() -> openai.OpenAIError:
    """Simulate a rate limit / quota error (429)."""
    return openai.RateLimitError("Rate limit reached", response=_response(429), body=None)


def make_timeout_error() -> openai.OpenAIError:
    """Simulate a request timeout."""
    return openai.APITimeoutError(request=_request())


def make_connection_error() -> openai.OpenAIError:
    """Simulate a network failure."""
    return openai.APIConnectionError(request=_request())


def make_server_error() -> openai.OpenAIError:
    """Simulate an OpenAI internal error (500)."""
    return openai.InternalServerError("Server error", response=_response(500), body=None)


# --- Fixtures ----------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_langsmith_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep LangSmith env vars set by `configure_tracing` from leaking between tests."""
    # setenv records the original state, so pytest restores it after each test.
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    for name in ("LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_ENDPOINT"):
        monkeypatch.setenv(name, "")


@pytest.fixture
def make_model() -> Callable[..., RecordingFakeChatModel]:
    """Factory of fake models with custom responses or errors."""

    def _make(
        responses: list[str] | None = None, error: Exception | None = None
    ) -> RecordingFakeChatModel:
        return RecordingFakeChatModel(responses=responses or ["Fake answer"], error=error)

    return _make


@pytest.fixture
def fake_model(make_model: Callable[..., RecordingFakeChatModel]) -> RecordingFakeChatModel:
    """Fake model that answers "Answer 1", "Answer 2", ... in order."""
    return make_model([f"Answer {i}" for i in range(1, 11)])


@pytest.fixture
def chat_service(fake_model: RecordingFakeChatModel) -> ChatService:
    """Chat service backed by the fake model (default limits, approximate tokens)."""
    return ChatService(model=fake_model)


@pytest.fixture
def settings_without_key() -> Settings:
    """Settings that ignore `.env` and the environment for the API key."""
    return Settings(_env_file=None, openai_api_key=None)


@pytest.fixture
def settings_with_key() -> Settings:
    """Settings with a dummy (never used) API key."""
    return Settings(_env_file=None, openai_api_key="sk-test-not-a-real-key")


@pytest.fixture
def console_output() -> StringIO:
    """Buffer that receives everything printed by the test console."""
    return StringIO()


@pytest.fixture
def console(console_output: StringIO) -> Console:
    """Non-interactive rich console writing to `console_output`."""
    return Console(file=console_output, width=120, force_terminal=False, color_system=None)
