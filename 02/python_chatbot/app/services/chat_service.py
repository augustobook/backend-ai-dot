"""Chat use cases (`ask`, `stream`, `aask`, `astream`, `clear_history`) and limits.

`ChatService` is the only entry point the interfaces use. It hides LangChain and
OpenAI details: interfaces send a session id and a question, and receive text or
domain exceptions (`app.core.exceptions`).
"""

import logging
from collections.abc import AsyncIterator, Iterator, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal

import openai
from langchain_core.callbacks import Callbacks
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig

from app.core.config import MAX_QUESTION_LENGTH, Settings, get_settings
from app.core.exceptions import (
    ConversationLimitError,
    LLMAuthenticationError,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
    QuestionTooLongError,
)
from app.core.redaction import redact_secrets
from app.llm.chain import (
    USE_HISTORY_KEY,
    TokenCounter,
    approximate_token_counter,
    build_chat_chain,
    build_chat_model,
    build_router_model,
    build_token_counter,
)
from app.llm.history import SessionHistoryStore
from app.llm.prompts import QUESTION_KEY, build_chat_prompt
from app.llm.router import HistoryRouter, build_llm_history_router

logger = logging.getLogger(__name__)

# Which interface triggered a run; recorded as LangSmith metadata/tag.
Interface = Literal["cli", "api", "web", "script"]

RUN_NAME = "python_tutor_chat"

# Same default as `Settings.max_conversation_tokens` (half of gpt-4o-mini's window).
DEFAULT_MAX_CONVERSATION_TOKENS = 64_000

# From this fraction of the token budget on, interfaces warn the user.
USAGE_WARNING_RATIO = 0.8


def to_domain_error(exc: openai.OpenAIError) -> LLMError:
    """Translate an OpenAI SDK exception into a domain exception.

    Args:
        exc: Exception raised by the OpenAI client.

    Returns:
        The matching `LLMError` subclass instance.
    """
    # Order matters: APITimeoutError is a subclass of APIConnectionError.
    if isinstance(exc, openai.AuthenticationError | openai.PermissionDeniedError):
        return LLMAuthenticationError()
    if isinstance(exc, openai.RateLimitError):
        return LLMRateLimitError()
    if isinstance(exc, openai.APITimeoutError):
        return LLMTimeoutError()
    return LLMUnavailableError()


@dataclass(frozen=True, slots=True)
class ConversationUsage:
    """How much of its token budget a conversation already uses.

    Attributes:
        used_tokens: Tokens of the system prompt + full history.
        max_tokens: Token budget of the conversation.
    """

    used_tokens: int
    max_tokens: int

    @property
    def ratio(self) -> float:
        """Fraction of the budget in use (0.0 to 1.0)."""
        return min(self.used_tokens / self.max_tokens, 1.0)

    @property
    def percent(self) -> int:
        """Percentage of the budget in use (0 to 100)."""
        return round(self.ratio * 100)

    @property
    def near_limit(self) -> bool:
        """True once the conversation reaches the warning threshold (80%)."""
        return self.ratio >= USAGE_WARNING_RATIO


class ChatService:
    """Conversational Python tutor with one memory per session.

    The whole conversation is stored and, when needed, sent to the model in full
    (nothing is cut). Before each question:

    1. the question size and the conversation token budget are checked;
    2. an optional history router decides whether the question needs the
       conversation (follow-up) or can be answered on its own (self-contained).

    Args:
        model: Chat model used to answer (injected so tests can use a fake model).
        max_conversation_tokens: Token budget of the prompt (system prompt + full
            history + question). Defaults to 64k tokens.
        token_counter: Counts the tokens of a prompt. Defaults to an approximation;
            production injects the model's exact tokenizer.
        history_router: Decides per question whether to send the history. Without
            it, the history is always sent.
        history_store: Optional history storage (a new in-memory store by default).
    """

    def __init__(
        self,
        model: BaseChatModel,
        max_conversation_tokens: int = DEFAULT_MAX_CONVERSATION_TOKENS,
        token_counter: TokenCounter = approximate_token_counter,
        history_router: HistoryRouter | None = None,
        history_store: SessionHistoryStore | None = None,
    ) -> None:
        """Build the service and its conversational chain."""
        self._history_store = history_store or SessionHistoryStore()
        self._chain = build_chat_chain(model, self._history_store)
        self._prompt = build_chat_prompt()
        self._max_conversation_tokens = max_conversation_tokens
        self._token_counter = token_counter
        self._history_router = history_router

    # --- Limits -------------------------------------------------------------------

    def get_usage(self, session_id: str) -> ConversationUsage:
        """Report how much of the token budget a conversation already uses.

        Interfaces use it to warn the user before the limit is reached.

        Args:
            session_id: Identifier of the conversation.

        Returns:
            Tokens in use and the budget.
        """
        return ConversationUsage(
            used_tokens=self.count_prompt_tokens(session_id, ""),
            max_tokens=self._max_conversation_tokens,
        )

    def count_prompt_tokens(self, session_id: str, question: str) -> int:
        """Count the tokens the model would receive for this question.

        Args:
            session_id: Identifier of the conversation.
            question: The new question.

        Returns:
            Tokens of the system prompt + full history + question.
        """
        messages = self._prompt.format_messages(
            history=self.get_history(session_id), question=question
        )
        return self._token_counter(messages)

    def _check_limits(self, session_id: str, question: str) -> None:
        """Validate the question size and the conversation token budget.

        Args:
            session_id: Identifier of the conversation.
            question: The new question.

        Raises:
            QuestionTooLongError: If the question exceeds `MAX_QUESTION_LENGTH`.
            ConversationLimitError: If the conversation would exceed its token budget.
        """
        # Characters are checked first: cheap, and gives the user a precise limit.
        if len(question) > MAX_QUESTION_LENGTH:
            raise QuestionTooLongError()

        # Tokens decide whether the whole conversation still fits in the model.
        used = self.count_prompt_tokens(session_id, question)
        if used > self._max_conversation_tokens:
            logger.warning(
                "Conversation limit reached (session=%s, tokens=%d, limit=%d).",
                session_id,
                used,
                self._max_conversation_tokens,
            )
            raise ConversationLimitError()

    # --- Helpers ------------------------------------------------------------------

    @staticmethod
    def _build_config(
        session_id: str, interface: Interface, callbacks: Callbacks = None
    ) -> RunnableConfig:
        """Build the runnable config for one call.

        `session_id` selects the history; the metadata and tags make LangSmith traces
        easy to filter by session and interface.

        Args:
            session_id: Identifier of the conversation.
            interface: Interface that triggered the call.
            callbacks: Extra LangChain callbacks (e.g. Chainlit's step viewer).

        Returns:
            The config passed to the chain.
        """
        return {
            "configurable": {"session_id": session_id},
            "run_name": RUN_NAME,
            "metadata": {"session_id": session_id, "interface": interface},
            "tags": ["python-tutor", f"interface:{interface}"],
            "callbacks": callbacks,
        }

    @staticmethod
    def _input(question: str, use_history: bool, config: RunnableConfig) -> dict[str, Any]:
        """Build the chain input and record the routing decision in the trace.

        Args:
            question: The new question.
            use_history: Whether the history is sent to the model.
            config: Config of the call (metadata/tags are updated in place).

        Returns:
            The input dict expected by the chain.
        """
        config.setdefault("metadata", {})["history_used"] = use_history
        config.setdefault("tags", []).append(f"history:{'used' if use_history else 'skipped'}")
        return {QUESTION_KEY: question, USE_HISTORY_KEY: use_history}

    @staticmethod
    def _redact(session_id: str, question: str) -> str:
        """Replace pasted secrets before the question goes anywhere.

        The redacted text is what the router, the model, the history and the
        traces see, so a pasted key never leaves the process.

        Args:
            session_id: Identifier of the conversation (for the log).
            question: The question as typed.

        Returns:
            The question with secrets replaced by a placeholder.
        """
        redacted, count = redact_secrets(question)
        if count:
            logger.warning("Redacted %d secret(s) from a question (session=%s).", count, session_id)
        return redacted

    def _prepare(self, session_id: str, question: str, config: RunnableConfig) -> dict[str, Any]:
        """Redact secrets, check the limits and decide whether to send the history (sync).

        Args:
            session_id: Identifier of the conversation.
            question: The new question.
            config: Config of the call.

        Returns:
            The chain input.
        """
        question = self._redact(session_id, question)
        self._check_limits(session_id, question)
        use_history = True
        if self._history_router is not None:
            use_history = self._history_router.needs_history(
                self.get_history(session_id), question, config
            )
        return self._input(question, use_history, config)

    async def _aprepare(
        self, session_id: str, question: str, config: RunnableConfig
    ) -> dict[str, Any]:
        """Asynchronous version of `_prepare`."""
        question = self._redact(session_id, question)
        self._check_limits(session_id, question)
        use_history = True
        if self._history_router is not None:
            use_history = await self._history_router.aneeds_history(
                self.get_history(session_id), question, config
            )
        return self._input(question, use_history, config)

    @staticmethod
    def _handle_error(exc: openai.OpenAIError, session_id: str) -> LLMError:
        """Log the technical error and return the user-facing domain error.

        Args:
            exc: Exception raised by the OpenAI client.
            session_id: Session in which the error happened.

        Returns:
            The domain error to raise.
        """
        error = to_domain_error(exc)
        logger.error(
            "LLM call failed (session=%s, error=%s): %s",
            session_id,
            type(exc).__name__,
            exc,
        )
        return error

    # --- Use cases ----------------------------------------------------------------

    def ask(self, session_id: str, question: str, interface: Interface = "cli") -> str:
        """Answer a question, keeping the session context.

        Args:
            session_id: Identifier of the conversation.
            question: User question.
            interface: Interface that triggered the call (for tracing).

        Returns:
            The full answer.

        Raises:
            QuestionTooLongError: If the question is too long.
            ConversationLimitError: If the conversation reached its token budget.
            LLMError: If the language model call fails.
        """
        config = self._build_config(session_id, interface)
        chain_input = self._prepare(session_id, question, config)
        try:
            answer: str = self._chain.invoke(chain_input, config=config)
        except openai.OpenAIError as exc:
            raise self._handle_error(exc, session_id) from exc
        return answer

    def stream(self, session_id: str, question: str, interface: Interface = "cli") -> Iterator[str]:
        """Answer a question, yielding the text as the model generates it.

        Args:
            session_id: Identifier of the conversation.
            question: User question.
            interface: Interface that triggered the call (for tracing).

        Yields:
            Chunks of the answer.

        Raises:
            QuestionTooLongError: If the question is too long.
            ConversationLimitError: If the conversation reached its token budget.
            LLMError: If the language model call fails.
        """
        config = self._build_config(session_id, interface)
        chain_input = self._prepare(session_id, question, config)
        try:
            yield from self._chain.stream(chain_input, config=config)
        except openai.OpenAIError as exc:
            raise self._handle_error(exc, session_id) from exc

    async def aask(self, session_id: str, question: str, interface: Interface = "api") -> str:
        """Asynchronous version of `ask` (does not block the event loop).

        Args:
            session_id: Identifier of the conversation.
            question: User question.
            interface: Interface that triggered the call (for tracing).

        Returns:
            The full answer.

        Raises:
            QuestionTooLongError: If the question is too long.
            ConversationLimitError: If the conversation reached its token budget.
            LLMError: If the language model call fails.
        """
        config = self._build_config(session_id, interface)
        chain_input = await self._aprepare(session_id, question, config)
        try:
            answer: str = await self._chain.ainvoke(chain_input, config=config)
        except openai.OpenAIError as exc:
            raise self._handle_error(exc, session_id) from exc
        return answer

    async def astream(
        self,
        session_id: str,
        question: str,
        interface: Interface = "web",
        callbacks: Callbacks = None,
    ) -> AsyncIterator[str]:
        """Asynchronous version of `stream`, used by the web UI.

        Args:
            session_id: Identifier of the conversation.
            question: User question.
            interface: Interface that triggered the call (for tracing).
            callbacks: Extra LangChain callbacks (e.g. Chainlit's step viewer).

        Yields:
            Chunks of the answer.

        Raises:
            QuestionTooLongError: If the question is too long.
            ConversationLimitError: If the conversation reached its token budget.
            LLMError: If the language model call fails.
        """
        config = self._build_config(session_id, interface, callbacks)
        chain_input = await self._aprepare(session_id, question, config)
        try:
            async for chunk in self._chain.astream(chain_input, config=config):
                yield chunk
        except openai.OpenAIError as exc:
            raise self._handle_error(exc, session_id) from exc

    def clear_history(self, session_id: str) -> bool:
        """Forget the conversation of a session.

        Args:
            session_id: Identifier of the conversation.

        Returns:
            True if the session had a history, False otherwise.
        """
        cleared = self._history_store.clear(session_id)
        logger.info("History cleared (session=%s, existed=%s).", session_id, cleared)
        return cleared

    def restore_history(self, session_id: str, messages: Sequence[BaseMessage]) -> None:
        """Load a saved conversation into the memory of a session.

        Args:
            session_id: Identifier of the conversation.
            messages: Previous messages of the conversation, oldest first.
        """
        self._history_store.replace(session_id, messages)
        logger.info("History restored (session=%s, messages=%d).", session_id, len(messages))

    def get_history(self, session_id: str) -> list[BaseMessage]:
        """Return a copy of the messages stored for a session.

        Args:
            session_id: Identifier of the conversation.

        Returns:
            The stored messages (empty for unknown sessions).
        """
        if session_id not in self._history_store:
            return []
        return list(self._history_store.get(session_id).messages)


def create_chat_service(settings: Settings) -> ChatService:
    """Create a `ChatService` backed by OpenAI.

    Args:
        settings: Application settings.

    Returns:
        A ready-to-use service.

    Raises:
        MissingAPIKeyError: If `OPENAI_API_KEY` is not configured.
    """
    model = build_chat_model(settings)
    router = (
        build_llm_history_router(build_router_model(settings))
        if settings.history_router_enabled
        else None
    )
    logger.info(
        "Chat service ready (model=%s, conversation limit=%d tokens, history router=%s).",
        settings.openai_model,
        settings.max_conversation_tokens,
        settings.history_router_model if router else "off",
    )
    return ChatService(
        model=model,
        max_conversation_tokens=settings.max_conversation_tokens,
        # Exact counting with the model's own tokenizer (tiktoken).
        token_counter=build_token_counter(model),
        history_router=router,
    )


@lru_cache
def get_default_chat_service() -> ChatService:
    """Return the process-wide `ChatService` (shared by the API and the web UI).

    A single instance is required so all requests share the same history store.
    Failures (such as a missing API key) are not cached, so fixing the
    configuration and retrying works.

    Returns:
        The shared service.

    Raises:
        MissingAPIKeyError: If `OPENAI_API_KEY` is not configured.
    """
    return create_chat_service(get_settings())
