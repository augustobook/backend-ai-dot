"""Tests of the pure helpers of the Chainlit interface (no server needed)."""

from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.core.exceptions import (
    ChatbotError,
    ConversationLimitError,
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
    MissingAPIKeyError,
    QuestionTooLongError,
)
from app.services.chat_service import ChatService
from app.ui.helpers import (
    SESSION_ID_PREFIX,
    StarterSpec,
    build_session_id,
    format_error_message,
    format_usage_warning,
    get_starter_specs,
    steps_to_messages,
    translate_error,
)
from tests.conftest import RecordingFakeChatModel

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_starters_contain_the_suggested_questions() -> None:
    """The welcome screen suggests the four expected Python questions."""
    messages = [starter.message for starter in get_starter_specs()]

    assert messages == [
        "Como criar uma lista em Python?",
        "Qual a diferença entre lista e tupla?",
        "O que são decorators?",
        "Como tratar exceções em Python?",
    ]


def test_every_starter_has_a_label_and_an_existing_icon() -> None:
    """Each starter has a label and an icon file served from `public/`."""
    for starter in get_starter_specs():
        assert starter.label
        assert starter.icon.startswith("/public/")
        assert (PROJECT_ROOT / starter.icon.lstrip("/")).is_file()


def test_starter_labels_are_in_portuguese() -> None:
    """The starter buttons are labeled in Portuguese, like the rest of the UI."""
    labels = [starter.label for starter in get_starter_specs()]

    assert labels == ["Criar uma lista", "Lista vs. tupla", "Decorators", "Tratar exceções"]


def test_portuguese_translation_and_branding_files_exist() -> None:
    """The pt-BR translation, the logos and the assistant avatar are present."""
    assert (PROJECT_ROOT / ".chainlit" / "translations" / "pt-BR.json").is_file()
    assert (PROJECT_ROOT / "public" / "logo_dark.svg").is_file()
    assert (PROJECT_ROOT / "public" / "logo_light.svg").is_file()
    assert (PROJECT_ROOT / "public" / "avatars" / "chatbot_de_python_dot_group.svg").is_file()


def test_get_starter_specs_returns_a_new_list() -> None:
    """Callers cannot change the starters by mutating the returned list."""
    starters = get_starter_specs()
    starters.append(StarterSpec(label="x", message="y", icon="z"))

    assert len(get_starter_specs()) == 4


def test_build_session_id_maps_chainlit_session() -> None:
    """The Chainlit session id becomes a prefixed chat session id."""
    assert build_session_id("abc-123") == f"{SESSION_ID_PREFIX}abc-123"


def test_build_session_id_is_stable_and_unique_per_session() -> None:
    """The same Chainlit session always maps to the same id; others differ."""
    assert build_session_id("a") == build_session_id(" a ")
    assert build_session_id("a") != build_session_id("b")


@pytest.mark.parametrize("session_id", ["", "   "])
def test_build_session_id_rejects_empty_ids(session_id: str) -> None:
    """An empty Chainlit thread id is a programming error."""
    with pytest.raises(ValueError, match="must not be empty"):
        build_session_id(session_id)


def test_steps_to_messages_keeps_only_the_conversation() -> None:
    """User and assistant messages are rebuilt in order; other steps are skipped."""
    steps: list[dict[str, Any]] = [
        {"type": "user_message", "output": "Como criar uma lista?"},
        {"type": "run", "output": "internal LangChain step"},
        {"type": "assistant_message", "output": "Use colchetes."},
        {"type": "assistant_message", "output": "   "},
        {"type": "user_message", "output": None},
    ]

    messages = steps_to_messages(steps)

    assert messages == [HumanMessage("Como criar uma lista?"), AIMessage("Use colchetes.")]


def test_restored_history_is_used_by_the_next_question(
    chat_service: ChatService, fake_model: RecordingFakeChatModel
) -> None:
    """A reopened conversation continues with its previous context."""
    saved = [HumanMessage("Como criar uma lista?"), AIMessage("Use colchetes.")]

    chat_service.restore_history("web-t1", saved)
    chat_service.ask("web-t1", "E como adiciono itens?")

    assert fake_model.received[0][1:3] == saved


@pytest.mark.parametrize(
    ("error", "expected_text"),
    [
        pytest.param(MissingAPIKeyError(), "OPENAI_API_KEY", id="missing-key"),
        pytest.param(QuestionTooLongError(), "5000 caracteres", id="question-too-long"),
        pytest.param(ConversationLimitError(), "Novo chat", id="conversation-limit"),
        pytest.param(LLMAuthenticationError(), "recusou a chave", id="authentication"),
        pytest.param(LLMRateLimitError(), "muitas requisições", id="rate-limit"),
        pytest.param(LLMTimeoutError(), "demorou demais", id="timeout"),
        pytest.param(LLMUnavailableError(), "indisponível", id="unavailable"),
        pytest.param(ChatbotError(), "erro inesperado", id="generic"),
    ],
)
def test_errors_are_translated_to_portuguese(error: ChatbotError, expected_text: str) -> None:
    """Each domain error has a Portuguese explanation (subclasses fall back to parents)."""
    assert expected_text in translate_error(error)


def test_usage_warning_shows_percentage_in_portuguese() -> None:
    """The near-limit toast tells how full the conversation is."""
    message = format_usage_warning(85)

    assert "85%" in message
    assert "Novo chat" in message


def test_format_error_message_is_friendly() -> None:
    """Errors are shown with an apology in Portuguese and the explanation."""
    error = LLMRateLimitError()

    message = format_error_message(error)

    assert message.startswith("⚠️ **Desculpe")
    assert translate_error(error) in message
    assert error.user_message not in message  # the English text is not shown
