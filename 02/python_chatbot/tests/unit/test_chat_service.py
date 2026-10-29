"""Tests of `ChatService` (answers, memory per session, limits and errors)."""

from collections.abc import Callable

import openai
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableLambda

from app.core.config import MAX_QUESTION_LENGTH
from app.core.exceptions import (
    ConversationLimitError,
    LLMAuthenticationError,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
    QuestionTooLongError,
)
from app.llm.prompts import SYSTEM_PROMPT
from app.llm.router import HistoryDecision, HistoryRouter
from app.services.chat_service import ChatService, ConversationUsage, to_domain_error
from tests.conftest import (
    RecordingFakeChatModel,
    make_authentication_error,
    make_connection_error,
    make_rate_limit_error,
    make_server_error,
    make_timeout_error,
)

ERROR_CASES = [
    pytest.param(make_authentication_error, LLMAuthenticationError, id="authentication"),
    pytest.param(make_rate_limit_error, LLMRateLimitError, id="rate-limit"),
    pytest.param(make_timeout_error, LLMTimeoutError, id="timeout"),
    pytest.param(make_connection_error, LLMUnavailableError, id="connection"),
    pytest.param(make_server_error, LLMUnavailableError, id="server-error"),
]


# --- Answers ------------------------------------------------------------------------


def test_ask_returns_the_model_answer(chat_service: ChatService) -> None:
    """`ask` returns the text produced by the model."""
    assert chat_service.ask("s1", "How do I create a list?") == "Answer 1"


def test_ask_sends_system_prompt_and_question(
    chat_service: ChatService, fake_model: RecordingFakeChatModel
) -> None:
    """The model receives the system prompt followed by the question."""
    chat_service.ask("s1", "What is a dict?")

    messages = fake_model.received[0]
    assert isinstance(messages[0], SystemMessage)
    assert messages[-1] == HumanMessage("What is a dict?")


def test_stream_yields_chunks_that_form_the_answer(chat_service: ChatService) -> None:
    """`stream` yields several chunks that join into the full answer."""
    chunks = list(chat_service.stream("s1", "How do I create a list?"))

    assert len(chunks) > 1
    assert "".join(chunks) == "Answer 1"


async def test_aask_returns_the_model_answer(chat_service: ChatService) -> None:
    """`aask` is the async version of `ask`."""
    assert await chat_service.aask("s1", "What is a set?") == "Answer 1"


async def test_astream_yields_chunks_that_form_the_answer(chat_service: ChatService) -> None:
    """`astream` yields chunks asynchronously."""
    chunks = [chunk async for chunk in chat_service.astream("s1", "What is a set?")]

    assert len(chunks) > 1
    assert "".join(chunks) == "Answer 1"


# --- Memory -------------------------------------------------------------------------


def test_history_is_kept_within_a_session(
    chat_service: ChatService, fake_model: RecordingFakeChatModel
) -> None:
    """A follow-up question is sent together with the previous turn."""
    chat_service.ask("s1", "How do I create a list?")
    chat_service.ask("s1", "And how do I add an item to it?")

    second_call = fake_model.received[1]
    assert second_call[1:] == [
        HumanMessage("How do I create a list?"),
        AIMessage("Answer 1"),
        HumanMessage("And how do I add an item to it?"),
    ]
    assert len(chat_service.get_history("s1")) == 4


def test_streamed_answers_are_saved_in_the_history(chat_service: ChatService) -> None:
    """Streaming also stores the question and the full answer."""
    list(chat_service.stream("s1", "Question"))

    assert chat_service.get_history("s1") == [HumanMessage("Question"), AIMessage("Answer 1")]


async def test_async_streamed_answers_are_saved_in_the_history(chat_service: ChatService) -> None:
    """Async streaming also stores the question and the full answer."""
    async for _ in chat_service.astream("s1", "Question"):
        pass

    assert chat_service.get_history("s1") == [HumanMessage("Question"), AIMessage("Answer 1")]


def test_histories_are_isolated_between_sessions(
    chat_service: ChatService, fake_model: RecordingFakeChatModel
) -> None:
    """A session never sees messages from another session."""
    chat_service.ask("alice", "Alice's question")
    chat_service.ask("bob", "Bob's question")

    bob_call = fake_model.received[1]
    assert len(bob_call) == 2  # system prompt + Bob's question only
    assert chat_service.get_history("alice")[0] == HumanMessage("Alice's question")
    assert chat_service.get_history("bob")[0] == HumanMessage("Bob's question")


def test_clear_history_forgets_the_conversation(
    chat_service: ChatService, fake_model: RecordingFakeChatModel
) -> None:
    """After `clear_history`, the next question is sent without context."""
    chat_service.ask("s1", "First question")

    assert chat_service.clear_history("s1") is True
    assert chat_service.get_history("s1") == []

    chat_service.ask("s1", "New topic")
    assert len(fake_model.received[-1]) == 2


def test_clear_history_of_unknown_session_returns_false(chat_service: ChatService) -> None:
    """Clearing a session that never existed is harmless."""
    assert chat_service.clear_history("unknown") is False


def test_clear_history_keeps_other_sessions(chat_service: ChatService) -> None:
    """Clearing one session does not affect the others."""
    chat_service.ask("s1", "Question 1")
    chat_service.ask("s2", "Question 2")

    chat_service.clear_history("s1")

    assert len(chat_service.get_history("s2")) == 2


def test_whole_history_is_sent_to_the_model(
    chat_service: ChatService, fake_model: RecordingFakeChatModel
) -> None:
    """Nothing is cut: every previous message reaches the model."""
    for i in range(12):
        chat_service.ask("s1", f"Question {i}")

    last_call = fake_model.received[-1]
    history = last_call[1:-1]
    assert len(history) == 22  # 11 previous questions + 11 answers
    assert history[0] == HumanMessage("Question 0")
    assert last_call[-1] == HumanMessage("Question 11")


# --- History router -----------------------------------------------------------------


def _router(needs_history: bool) -> HistoryRouter:
    """Router that always returns the given decision."""
    decision = HistoryDecision(needs_history=needs_history, reason="test")
    return HistoryRouter(RunnableLambda(lambda _: decision))


def test_self_contained_question_is_sent_without_history(
    fake_model: RecordingFakeChatModel,
) -> None:
    """When the router says no, the model gets only system prompt + question."""
    service = ChatService(model=fake_model, history_router=_router(False))
    service.ask("s1", "Como criar uma lista?")

    service.ask("s1", "O que são decorators?")

    assert len(fake_model.received[1]) == 2
    # The history is still saved, so later follow-ups keep working.
    assert len(service.get_history("s1")) == 4


def test_follow_up_question_is_sent_with_full_history(
    fake_model: RecordingFakeChatModel,
) -> None:
    """When the router says yes, the whole conversation is sent."""
    service = ChatService(model=fake_model, history_router=_router(True))
    service.ask("s1", "Como criar uma lista?")

    service.ask("s1", "E como adiciono itens nela?")

    assert fake_model.received[1][1] == HumanMessage("Como criar uma lista?")
    assert len(fake_model.received[1]) == 4


async def test_router_is_used_by_async_and_streaming_calls(
    fake_model: RecordingFakeChatModel,
) -> None:
    """Every use case applies the router decision."""
    service = ChatService(model=fake_model, history_router=_router(False))
    service.ask("s1", "First")

    list(service.stream("s1", "Second"))
    await service.aask("s1", "Third")
    async for _ in service.astream("s1", "Fourth"):
        pass

    assert [len(call) for call in fake_model.received[1:]] == [2, 2, 2]


def test_routing_decision_is_recorded_for_tracing(fake_model: RecordingFakeChatModel) -> None:
    """The decision goes to the run metadata and tags (visible in LangSmith)."""
    service = ChatService(model=fake_model, history_router=_router(False))
    config = ChatService._build_config("s1", "api")

    chain_input = service._prepare("s1", "Question", config)

    assert chain_input["use_history"] is False
    assert config["metadata"]["history_used"] is False
    assert "history:skipped" in config["tags"]


# --- Usage --------------------------------------------------------------------------


def test_usage_grows_and_warns_near_the_limit(
    make_model: Callable[..., RecordingFakeChatModel],
) -> None:
    """Usage is reported as a percentage and flags 80% or more."""
    service = ChatService(
        model=make_model(["answer"]), max_conversation_tokens=10, token_counter=len
    )

    assert service.get_usage("s1").percent == 20  # system + empty question = 2 of 10
    for i in range(3):
        service.ask("s1", f"Question {i}")
    usage = service.get_usage("s1")

    assert usage.used_tokens == 8
    assert usage.percent == 80
    assert usage.near_limit is True


def test_usage_ratio_is_capped_at_100_percent() -> None:
    """A conversation above its budget is reported as 100%."""
    usage = ConversationUsage(used_tokens=150, max_tokens=100)

    assert usage.ratio == 1.0
    assert usage.percent == 100


# --- Limits -------------------------------------------------------------------------


def test_question_longer_than_the_limit_is_rejected(
    chat_service: ChatService, fake_model: RecordingFakeChatModel
) -> None:
    """A question above MAX_QUESTION_LENGTH characters never reaches the model."""
    with pytest.raises(QuestionTooLongError):
        chat_service.ask("s1", "x" * (MAX_QUESTION_LENGTH + 1))

    assert fake_model.received == []


def test_question_at_the_limit_is_accepted(chat_service: ChatService) -> None:
    """Exactly MAX_QUESTION_LENGTH characters is allowed."""
    assert chat_service.ask("s1", "x" * MAX_QUESTION_LENGTH) == "Answer 1"


def test_conversation_limit_blocks_new_questions(
    make_model: Callable[..., RecordingFakeChatModel],
) -> None:
    """When the prompt no longer fits the token budget, the conversation ends."""
    model = make_model(["a short answer"])
    # Count one token per message to make the budget easy to reason about:
    # system + question = 2 tokens; after one turn: system + 2 history + question = 4.
    service = ChatService(model=model, max_conversation_tokens=3, token_counter=len)

    service.ask("s1", "First question")
    with pytest.raises(ConversationLimitError):
        service.ask("s1", "Second question")

    assert len(model.received) == 1  # the second question was not sent
    assert len(service.get_history("s1")) == 2  # history kept intact


def test_conversation_limit_applies_to_streaming(
    make_model: Callable[..., RecordingFakeChatModel],
) -> None:
    """Streaming checks the same token budget before calling the model."""
    service = ChatService(model=make_model(), max_conversation_tokens=1, token_counter=len)

    with pytest.raises(ConversationLimitError):
        list(service.stream("s1", "Question"))


async def test_conversation_limit_applies_to_async_calls(
    make_model: Callable[..., RecordingFakeChatModel],
) -> None:
    """The async use cases check the same token budget."""
    service = ChatService(model=make_model(), max_conversation_tokens=1, token_counter=len)

    with pytest.raises(ConversationLimitError):
        await service.aask("s1", "Question")
    with pytest.raises(ConversationLimitError):
        async for _ in service.astream("s1", "Question"):
            pass


def test_new_conversation_is_allowed_after_the_limit(
    make_model: Callable[..., RecordingFakeChatModel],
) -> None:
    """Clearing the history (a new conversation) frees the budget again."""
    service = ChatService(model=make_model(), max_conversation_tokens=3, token_counter=len)
    service.ask("s1", "First question")

    service.clear_history("s1")

    assert service.ask("s1", "New topic") == "Fake answer"


def test_count_prompt_tokens_includes_system_history_and_question(
    chat_service: ChatService,
) -> None:
    """The count covers the whole prompt and grows with the conversation."""
    empty = chat_service.count_prompt_tokens("s1", "Question")
    chat_service.ask("s1", "Question")
    after_one_turn = chat_service.count_prompt_tokens("s1", "Question")

    assert empty > len(SYSTEM_PROMPT) // 8  # the system prompt is counted
    assert after_one_turn > empty


# --- Tracing metadata ------------------------------------------------------------


def test_run_config_carries_session_and_interface_metadata() -> None:
    """Runs are tagged with the session id and the interface (for LangSmith)."""
    config = ChatService._build_config("s1", "api")

    assert config["configurable"] == {"session_id": "s1"}
    assert config["metadata"] == {"session_id": "s1", "interface": "api"}
    assert "interface:api" in config["tags"]


# --- Errors -------------------------------------------------------------------------


@pytest.mark.parametrize(("make_error", "expected"), ERROR_CASES)
def test_to_domain_error_maps_openai_errors(
    make_error: Callable[[], openai.OpenAIError], expected: type[LLMError]
) -> None:
    """Each OpenAI exception maps to the matching domain exception."""
    assert type(to_domain_error(make_error())) is expected


@pytest.mark.parametrize(("make_error", "expected"), ERROR_CASES)
def test_ask_converts_llm_errors(
    make_model: Callable[..., RecordingFakeChatModel],
    make_error: Callable[[], openai.OpenAIError],
    expected: type[LLMError],
) -> None:
    """`ask` raises domain exceptions instead of OpenAI ones."""
    service = ChatService(model=make_model(error=make_error()))

    with pytest.raises(expected):
        service.ask("s1", "Question")


@pytest.mark.parametrize(("make_error", "expected"), ERROR_CASES)
def test_stream_converts_llm_errors(
    make_model: Callable[..., RecordingFakeChatModel],
    make_error: Callable[[], openai.OpenAIError],
    expected: type[LLMError],
) -> None:
    """`stream` raises domain exceptions instead of OpenAI ones."""
    service = ChatService(model=make_model(error=make_error()))

    with pytest.raises(expected):
        list(service.stream("s1", "Question"))


async def test_aask_converts_llm_errors(
    make_model: Callable[..., RecordingFakeChatModel],
) -> None:
    """`aask` raises domain exceptions instead of OpenAI ones."""
    service = ChatService(model=make_model(error=make_rate_limit_error()))

    with pytest.raises(LLMRateLimitError):
        await service.aask("s1", "Question")


async def test_astream_converts_llm_errors(
    make_model: Callable[..., RecordingFakeChatModel],
) -> None:
    """`astream` raises domain exceptions instead of OpenAI ones."""
    service = ChatService(model=make_model(error=make_timeout_error()))

    with pytest.raises(LLMTimeoutError):
        async for _ in service.astream("s1", "Question"):
            pass


def test_failed_calls_are_not_saved_in_the_history(
    make_model: Callable[..., RecordingFakeChatModel],
) -> None:
    """A question that failed does not pollute the conversation history."""
    service = ChatService(model=make_model(error=make_connection_error()))

    with pytest.raises(LLMUnavailableError):
        service.ask("s1", "Question")

    assert service.get_history("s1") == []


def test_llm_errors_are_logged(
    make_model: Callable[..., RecordingFakeChatModel], caplog: pytest.LogCaptureFixture
) -> None:
    """The technical error is logged for troubleshooting."""
    service = ChatService(model=make_model(error=make_rate_limit_error()))

    with pytest.raises(LLMRateLimitError):
        service.ask("s1", "Question")

    assert "RateLimitError" in caplog.text
    assert "session=s1" in caplog.text
