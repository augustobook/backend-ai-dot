"""Tests of the history router (decides whether a question needs the history)."""

from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableLambda

from app.llm.router import (
    ROUTER_SYSTEM_PROMPT,
    HistoryDecision,
    HistoryRouter,
    build_llm_history_router,
    build_router_prompt,
    format_recent_history,
)
from tests.conftest import RecordingFakeChatModel, make_connection_error

HISTORY: list[BaseMessage] = [
    HumanMessage("Como criar uma lista em Python?"),
    AIMessage("Use colchetes: frutas = ['maçã']"),
]


def make_router(decision: Any, calls: list[dict[str, Any]] | None = None) -> HistoryRouter:
    """Build a router whose decider returns `decision` (or raises it)."""

    def decide(router_input: dict[str, Any]) -> Any:
        if calls is not None:
            calls.append(router_input)
        if isinstance(decision, Exception):
            raise decision
        return decision

    return HistoryRouter(RunnableLambda(decide))


# --- Prompt and formatting --------------------------------------------------------


def test_router_prompt_explains_when_history_is_needed() -> None:
    """The router instructions cover follow-ups and default to sending history."""
    assert "needs_history = true" in ROUTER_SYSTEM_PROMPT
    assert "When in doubt, answer true" in ROUTER_SYSTEM_PROMPT
    messages = build_router_prompt().format_messages(recent_history="User: hi", question="Q?")
    assert "User: hi" in messages[1].text
    assert "Q?" in messages[1].text


def test_format_recent_history_keeps_last_messages_truncated() -> None:
    """Only the latest messages are shown, with long texts truncated."""
    history: list[BaseMessage] = [HumanMessage(f"question {i}") for i in range(10)]
    history.append(AIMessage("x" * 1000))

    text = format_recent_history(history, max_messages=3, max_chars=50)

    assert text.splitlines()[0] == "User: question 8"
    assert text.splitlines()[-1] == "Assistant: " + "x" * 50 + " [...]"
    assert "question 7" not in text


# --- Decisions ----------------------------------------------------------------------


@pytest.mark.parametrize("needs", [True, False])
def test_router_returns_the_model_decision(needs: bool) -> None:
    """The structured decision of the model is returned as a boolean."""
    calls: list[dict[str, Any]] = []
    router = make_router(HistoryDecision(needs_history=needs, reason="test"), calls)

    assert router.needs_history(HISTORY, "E como adiciono itens?") is needs
    assert calls[0]["question"] == "E como adiciono itens?"
    assert "Como criar uma lista" in calls[0]["recent_history"]


def test_router_is_not_called_without_history() -> None:
    """The first question of a conversation needs no decision (no extra cost)."""
    calls: list[dict[str, Any]] = []
    router = make_router(HistoryDecision(needs_history=True, reason="x"), calls)

    assert router.needs_history([], "O que são decorators?") is False
    assert calls == []


@pytest.mark.parametrize(
    "decision",
    [pytest.param(make_connection_error(), id="error"), pytest.param("yes", id="bad-output")],
)
def test_router_failure_falls_back_to_sending_history(decision: Any) -> None:
    """If the router fails or answers nonsense, the history is sent (safe default)."""
    assert make_router(decision).needs_history(HISTORY, "Question") is True


async def test_async_router_returns_the_model_decision() -> None:
    """The async version behaves like the sync one."""
    router = make_router(HistoryDecision(needs_history=False, reason="standalone"))

    assert await router.aneeds_history(HISTORY, "O que são decorators?") is False
    assert await router.aneeds_history([], "Question") is False


async def test_async_router_failure_falls_back_to_sending_history() -> None:
    """Async failures also fall back to sending the history."""
    router = make_router(make_connection_error())

    assert await router.aneeds_history(HISTORY, "Question") is True


def test_llm_router_requires_structured_output_support(
    fake_model: RecordingFakeChatModel,
) -> None:
    """The LLM router relies on `with_structured_output` (ChatOpenAI supports it)."""
    with pytest.raises(NotImplementedError):
        build_llm_history_router(fake_model)
