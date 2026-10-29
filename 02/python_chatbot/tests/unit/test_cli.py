"""Tests of the command-line interface (commands, input handling, errors)."""

from collections.abc import Callable, Iterator
from io import StringIO

import pytest
from rich.console import Console

from app import cli
from app.cli import ChatCLI
from app.core.config import Settings
from app.services.chat_service import ChatService
from tests.conftest import RecordingFakeChatModel, make_connection_error


@pytest.fixture
def chat_cli(chat_service: ChatService, console: Console) -> ChatCLI:
    """CLI bound to the fake-model service and the test console."""
    return ChatCLI(chat_service, console=console, session_id="cli-test")


def scripted_input(*lines: str | BaseException) -> Callable[[str], str]:
    """Build an input function that returns (or raises) the given items in order."""
    items: Iterator[str | BaseException] = iter(lines)

    def _read(prompt: str) -> str:
        item = next(items)
        if isinstance(item, BaseException):
            raise item
        return item

    return _read


# --- Commands -------------------------------------------------------------------


def test_help_command_lists_all_commands(chat_cli: ChatCLI, console_output: StringIO) -> None:
    """/help prints every available command and keeps the chat running."""
    assert chat_cli.process_input("/help") is True

    output = console_output.getvalue()
    for command in cli.COMMANDS:
        assert command in output


def test_clear_command_clears_the_session_history(
    chat_cli: ChatCLI, chat_service: ChatService, console_output: StringIO
) -> None:
    """/clear removes the conversation history of the current session."""
    chat_cli.process_input("How do I create a list?")
    assert chat_service.get_history("cli-test")

    assert chat_cli.process_input("/clear") is True

    assert chat_service.get_history("cli-test") == []
    assert "history cleared" in console_output.getvalue()


@pytest.mark.parametrize("command", ["/exit", "/quit", "/EXIT", "  /exit  "])
def test_exit_command_ends_the_chat(
    chat_cli: ChatCLI, console_output: StringIO, command: str
) -> None:
    """/exit (and its variations) stops the loop with a goodbye message."""
    assert chat_cli.process_input(command) is False
    assert "Goodbye" in console_output.getvalue()


def test_unknown_command_shows_a_hint(chat_cli: ChatCLI, console_output: StringIO) -> None:
    """Unknown commands are reported without calling the model."""
    assert chat_cli.process_input("/foo") is True
    assert "Unknown command" in console_output.getvalue()


# --- Input handling -------------------------------------------------------------


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_empty_input_does_not_call_the_model(
    chat_cli: ChatCLI, fake_model: RecordingFakeChatModel, console_output: StringIO, text: str
) -> None:
    """Blank input only shows a hint; no API call is made."""
    assert chat_cli.process_input(text) is True

    assert fake_model.received == []
    assert "Please type a question" in console_output.getvalue()


def test_question_is_answered_and_rendered(
    chat_cli: ChatCLI, fake_model: RecordingFakeChatModel, console_output: StringIO
) -> None:
    """A question is sent to the service and the answer is printed."""
    assert chat_cli.process_input("How do I create a list?") is True

    output = console_output.getvalue()
    assert "Python Tutor" in output
    assert "Answer 1" in output
    assert len(fake_model.received) == 1


def test_llm_error_shows_a_friendly_message(
    make_model: Callable[..., RecordingFakeChatModel],
    console: Console,
    console_output: StringIO,
) -> None:
    """LLM failures are shown as a friendly message and the chat continues."""
    service = ChatService(model=make_model(error=make_connection_error()))
    chat_cli = ChatCLI(service, console=console)

    assert chat_cli.process_input("How do I create a list?") is True

    output = console_output.getvalue()
    assert "unavailable" in output
    assert "Traceback" not in output


def test_too_long_question_shows_the_limit(
    chat_cli: ChatCLI, fake_model: RecordingFakeChatModel, console_output: StringIO
) -> None:
    """Questions above 5000 characters are refused with a clear message."""
    assert chat_cli.process_input("x" * 5001) is True

    assert "5000 characters" in console_output.getvalue()
    assert fake_model.received == []


def test_warning_is_shown_near_the_conversation_limit(
    make_model: Callable[..., RecordingFakeChatModel],
    console: Console,
    console_output: StringIO,
) -> None:
    """From 80% of the budget on, the CLI suggests starting a new conversation."""
    service = ChatService(model=make_model(["a"]), max_conversation_tokens=5, token_counter=len)
    chat_cli = ChatCLI(service, console=console)

    chat_cli.process_input("First question")  # 4 of 5 tokens after the answer

    assert "80% of its maximum size" in console_output.getvalue()


def test_no_warning_far_from_the_limit(chat_cli: ChatCLI, console_output: StringIO) -> None:
    """Short conversations show no warning."""
    chat_cli.process_input("What is a list?")

    assert "maximum size" not in console_output.getvalue()


def test_session_id_is_generated_when_missing(chat_service: ChatService) -> None:
    """Each CLI run gets its own unique session id."""
    first = ChatCLI(chat_service)
    second = ChatCLI(chat_service)

    assert first.session_id.startswith("cli-")
    assert first.session_id != second.session_id


# --- Main loop ------------------------------------------------------------------


def test_run_shows_welcome_and_stops_on_exit(
    chat_cli: ChatCLI, fake_model: RecordingFakeChatModel, console_output: StringIO
) -> None:
    """The loop greets the user, answers questions and stops on /exit."""
    chat_cli.run(scripted_input("", "What is a list?", "/exit"))

    output = console_output.getvalue()
    assert "How do I create a list in Python?" in output  # suggested question
    assert "Answer 1" in output
    assert len(fake_model.received) == 1


@pytest.mark.parametrize("interruption", [KeyboardInterrupt(), EOFError()])
def test_run_exits_cleanly_on_ctrl_c(
    chat_cli: ChatCLI, console_output: StringIO, interruption: BaseException
) -> None:
    """Ctrl+C / Ctrl+D end the loop without a traceback."""
    chat_cli.run(scripted_input(interruption))

    assert "Goodbye" in console_output.getvalue()


# --- Entry point ----------------------------------------------------------------


def test_main_reports_missing_api_key(
    monkeypatch: pytest.MonkeyPatch,
    settings_without_key: Settings,
    console: Console,
    console_output: StringIO,
) -> None:
    """Without OPENAI_API_KEY, main exits with code 1 and explains how to fix it."""
    monkeypatch.setattr(cli, "get_settings", lambda: settings_without_key)

    exit_code = cli.main(console=console)

    output = console_output.getvalue()
    assert exit_code == 1
    assert "OPENAI_API_KEY" in output
    assert ".env" in output
    assert "Traceback" not in output


def test_main_runs_the_chat_loop(
    monkeypatch: pytest.MonkeyPatch,
    settings_with_key: Settings,
    chat_service: ChatService,
    console: Console,
    console_output: StringIO,
) -> None:
    """With a valid configuration, main runs the loop and exits with code 0."""
    monkeypatch.setattr(cli, "get_settings", lambda: settings_with_key)
    monkeypatch.setattr(cli, "create_chat_service", lambda settings: chat_service)
    monkeypatch.setattr(console, "input", scripted_input("/exit"))

    assert cli.main(console=console) == 0
    assert "Goodbye" in console_output.getvalue()
