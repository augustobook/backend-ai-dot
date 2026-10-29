"""Tests of configuration, tracing setup, logging and the OpenAI model factory."""

import logging
import os

import pytest
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_openai import ChatOpenAI

from app.api.dependencies import get_chat_service
from app.core import config
from app.core.config import Settings
from app.core.exceptions import ChatbotError, LLMError, MissingAPIKeyError
from app.core.logging import configure_logging
from app.core.tracing import configure_tracing
from app.llm.chain import (
    approximate_token_counter,
    build_chat_model,
    build_router_model,
    build_token_counter,
)
from app.llm.history import SessionHistoryStore
from app.services import chat_service as chat_service_module
from app.services.chat_service import ChatService, create_chat_service

# --- Settings ---------------------------------------------------------------------


def test_settings_have_sensible_defaults(settings_without_key: Settings) -> None:
    """Defaults use a GPT-4 family model and a low temperature."""
    assert settings_without_key.openai_model.startswith("gpt-4")
    assert settings_without_key.openai_temperature <= 0.5
    assert settings_without_key.langsmith_tracing is False


def test_settings_read_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    """Values come from environment variables; the key is kept secret."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o")
    monkeypatch.setenv("OPENAI_CONTEXT_WINDOW", "32000")

    settings = Settings(_env_file=None)

    assert settings.openai_model == "gpt-4o"
    assert settings.openai_context_window == 32000
    assert "sk-env" not in repr(settings)
    assert settings.has_openai_api_key


def test_conversation_budget_reserves_room_for_the_answer() -> None:
    """The conversation budget is the context window minus the answer size."""
    settings = Settings(_env_file=None, openai_context_window=128_000, openai_max_tokens=4096)

    assert settings.openai_max_tokens == 4096
    assert settings.max_conversation_tokens == 128_000 - 4096


def test_answer_cannot_take_the_whole_context_window() -> None:
    """An answer limit as large as the context window is a configuration error."""
    with pytest.raises(ValueError, match="OPENAI_MAX_TOKENS"):
        Settings(_env_file=None, openai_context_window=4000, openai_max_tokens=4000)


@pytest.mark.parametrize("key", [None, "", "   "])
def test_blank_api_key_is_treated_as_missing(key: str | None) -> None:
    """Blank keys count as not configured."""
    settings = Settings(_env_file=None, openai_api_key=key)

    assert settings.has_openai_api_key is False


# --- Exceptions -------------------------------------------------------------------


def test_domain_errors_expose_user_message_and_status() -> None:
    """Domain errors carry a friendly message and an HTTP status code."""
    assert MissingAPIKeyError().status_code == 503
    assert str(LLMError("custom")) == "custom"
    assert ChatbotError().status_code == 500


# --- Model factory ----------------------------------------------------------------


def test_build_chat_model_requires_api_key(settings_without_key: Settings) -> None:
    """Creating the OpenAI model without a key fails with a clear error."""
    with pytest.raises(MissingAPIKeyError, match="OPENAI_API_KEY"):
        build_chat_model(settings_without_key)


def test_build_chat_model_uses_settings(settings_with_key: Settings) -> None:
    """ChatOpenAI is configured from the settings (no network call is made)."""
    model = build_chat_model(settings_with_key)

    assert isinstance(model, ChatOpenAI)
    assert model.model_name == settings_with_key.openai_model
    assert model.temperature == settings_with_key.openai_temperature
    assert model.max_tokens == settings_with_key.openai_max_tokens
    assert model.max_retries == settings_with_key.openai_max_retries


def test_create_chat_service_returns_a_service(settings_with_key: Settings) -> None:
    """The factory wires ChatOpenAI into a ChatService."""
    assert isinstance(create_chat_service(settings_with_key), ChatService)


def test_router_uses_the_cheap_model_deterministically(settings_with_key: Settings) -> None:
    """The history router uses its own cheap model, temperature 0, tiny output."""
    model = build_router_model(settings_with_key)

    assert model.model_name == "gpt-4.1-nano"
    assert model.temperature == 0
    assert model.max_tokens == 150


def test_router_model_requires_api_key(settings_without_key: Settings) -> None:
    """The router model also needs the OpenAI key."""
    with pytest.raises(MissingAPIKeyError):
        build_router_model(settings_without_key)


@pytest.mark.parametrize("enabled", [True, False])
def test_history_router_can_be_disabled(enabled: bool) -> None:
    """HISTORY_ROUTER_ENABLED turns the router on or off."""
    settings = Settings(_env_file=None, openai_api_key="sk-test", history_router_enabled=enabled)

    service = create_chat_service(settings)

    assert (service._history_router is not None) is enabled


def test_token_counter_uses_the_model_tokenizer(
    monkeypatch: pytest.MonkeyPatch, settings_with_key: Settings
) -> None:
    """Production counts tokens with ChatOpenAI's own (tiktoken) counter."""
    received: list[list[BaseMessage]] = []

    def fake_count(self: ChatOpenAI, messages: list[BaseMessage], tools: object = None) -> int:
        received.append(messages)
        return 42

    # Patched to avoid downloading the tiktoken encoding during tests.
    monkeypatch.setattr(ChatOpenAI, "get_num_tokens_from_messages", fake_count)
    counter = build_token_counter(build_chat_model(settings_with_key))

    assert counter((HumanMessage("hi"),)) == 42
    assert received == [[HumanMessage("hi")]]


def test_approximate_counter_grows_with_text() -> None:
    """The fallback counter estimates more tokens for longer prompts."""
    short = approximate_token_counter([HumanMessage("hi")])
    long = approximate_token_counter([HumanMessage("hi " * 400)])

    assert 0 < short < long


def test_default_service_is_shared_and_exposed_as_dependency(
    monkeypatch: pytest.MonkeyPatch, settings_with_key: Settings
) -> None:
    """The API dependency returns one process-wide service instance."""
    monkeypatch.setattr(chat_service_module, "get_settings", lambda: settings_with_key)
    chat_service_module.get_default_chat_service.cache_clear()
    try:
        assert get_chat_service() is get_chat_service()
    finally:
        chat_service_module.get_default_chat_service.cache_clear()


def test_get_settings_is_cached() -> None:
    """Settings are loaded only once per process."""
    assert config.get_settings() is config.get_settings()


# --- History store ----------------------------------------------------------------


def test_history_store_creates_and_clears_sessions() -> None:
    """The store creates histories on demand and removes them on clear."""
    store = SessionHistoryStore()

    history = store.get("s1")

    assert store.get("s1") is history
    assert "s1" in store
    assert len(store) == 1
    assert store.clear("s1") is True
    assert "s1" not in store


# --- Tracing ----------------------------------------------------------------------


def test_tracing_is_disabled_by_default(settings_without_key: Settings) -> None:
    """Without LANGSMITH_TRACING, tracing stays off."""
    assert configure_tracing(settings_without_key) is False
    assert os.environ["LANGSMITH_TRACING"] == "false"


def test_tracing_without_api_key_is_disabled_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Tracing enabled without a key is turned off instead of failing."""
    settings = Settings(_env_file=None, langsmith_tracing=True, langsmith_api_key=None)

    with caplog.at_level(logging.WARNING):
        assert configure_tracing(settings) is False

    assert os.environ["LANGSMITH_TRACING"] == "false"
    assert "LANGSMITH_API_KEY" in caplog.text


def test_tracing_exports_langsmith_variables() -> None:
    """With tracing and a key, the LangSmith variables are exported."""
    settings = Settings(
        _env_file=None,
        langsmith_tracing=True,
        langsmith_api_key="ls-test",
        langsmith_project="my-project",
    )

    assert configure_tracing(settings) is True
    assert os.environ["LANGSMITH_TRACING"] == "true"
    assert os.environ["LANGSMITH_API_KEY"] == "ls-test"
    assert os.environ["LANGSMITH_PROJECT"] == "my-project"


# --- Logging ----------------------------------------------------------------------


def test_configure_logging_sets_levels() -> None:
    """The root level follows the setting and noisy libraries are quieted."""
    configure_logging("debug")

    assert logging.getLogger().level == logging.DEBUG
    assert logging.getLogger("httpx").level == logging.WARNING
    configure_logging("INFO")
