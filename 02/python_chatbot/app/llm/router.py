"""History router: decides, for each question, whether the conversation is needed.

A self-contained question ("What are decorators?") does not need the previous
messages; a follow-up ("And how do I remove items from it?") does. Sending the
history only when it matters reduces cost, latency and noise in the prompt.

The decision is made by a small LLM classifier with structured output:

    recent history (truncated) + new question
        -> ChatPromptTemplate (router instructions)
        -> chat model with structured output -> HistoryDecision

Design choices:
- Only the last few messages, truncated, are shown to the router: follow-up
  references almost always point to the recent turns, and it keeps the extra
  call small and cheap.
- Any failure falls back to "send the history": answering with too much context
  is safe, answering a follow-up without context is not.
"""

import logging
from collections.abc import Sequence
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnableConfig
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

ROUTER_RUN_NAME = "history_router"

ROUTER_SYSTEM_PROMPT = """\
You are a routing component of a Python tutoring chatbot. Decide whether the \
assistant needs the previous conversation to answer the user's NEW question.

Answer needs_history = true when the new question:
- refers to something said before (e.g. "it", "that", "this list", "the code \
above", "e como adiciono itens nela?", "and what about tuples?");
- asks to continue, expand, fix, change or explain a previous answer or example \
("explain more", "why?", "give another example", "and in Python 3.8?");
- is ambiguous or incomplete without the earlier messages.

Answer needs_history = false when the new question is self-contained and can be \
fully understood on its own, even if it is about a related topic.

When in doubt, answer true.
"""

ROUTER_HUMAN_TEMPLATE = """\
Recent conversation:
{recent_history}

New question:
{question}
"""


class HistoryDecision(BaseModel):
    """Structured output of the router."""

    needs_history: bool = Field(
        description="True if the new question depends on the previous conversation."
    )
    reason: str = Field(description="One short sentence explaining the decision.")


def build_router_prompt() -> ChatPromptTemplate:
    """Build the prompt of the history router.

    Returns:
        A template expecting `recent_history` (text) and `question`.
    """
    return ChatPromptTemplate.from_messages(
        [("system", ROUTER_SYSTEM_PROMPT), ("human", ROUTER_HUMAN_TEMPLATE)]
    )


def format_recent_history(
    history: Sequence[BaseMessage], max_messages: int = 6, max_chars: int = 600
) -> str:
    """Render the last messages of a conversation as short plain text.

    Args:
        history: Full conversation, oldest first.
        max_messages: How many of the latest messages to include.
        max_chars: Maximum characters kept from each message.

    Returns:
        Lines such as "User: ..." / "Assistant: ...".
    """
    lines = []
    for message in history[-max_messages:]:
        role = "User" if isinstance(message, HumanMessage) else "Assistant"
        text = message.text.strip()
        if len(text) > max_chars:
            text = text[:max_chars] + " [...]"
        lines.append(f"{role}: {text}")
    return "\n".join(lines)


class HistoryRouter:
    """Decides whether a question needs the conversation history.

    Args:
        decider: Runnable that maps `{"recent_history", "question"}` to a
            `HistoryDecision` (an LLM with structured output in production).
        max_messages: How many recent messages the router sees.
        max_chars: Maximum characters of each message shown to the router.
    """

    def __init__(
        self,
        decider: Runnable[dict[str, Any], Any],
        max_messages: int = 6,
        max_chars: int = 600,
    ) -> None:
        """Create the router."""
        self._decider = decider
        self._max_messages = max_messages
        self._max_chars = max_chars

    def _input(self, history: Sequence[BaseMessage], question: str) -> dict[str, Any]:
        """Build the router input from the conversation and the new question."""
        return {
            "recent_history": format_recent_history(history, self._max_messages, self._max_chars),
            "question": question,
        }

    @staticmethod
    def _config(config: RunnableConfig | None) -> RunnableConfig:
        """Name the router run so it is easy to find in LangSmith."""
        return {**(config or {}), "run_name": ROUTER_RUN_NAME}

    @staticmethod
    def _interpret(decision: Any) -> bool:
        """Turn the decider output into a boolean (invalid output -> True)."""
        if isinstance(decision, HistoryDecision):
            logger.info(
                "History router: needs_history=%s (%s)", decision.needs_history, decision.reason
            )
            return decision.needs_history
        logger.warning("History router returned an unexpected value; sending the history.")
        return True

    def needs_history(
        self,
        history: Sequence[BaseMessage],
        question: str,
        config: RunnableConfig | None = None,
    ) -> bool:
        """Tell whether the question needs the previous conversation.

        Args:
            history: Full conversation, oldest first.
            question: The new question.
            config: Runnable config (callbacks/metadata for tracing).

        Returns:
            True to send the history, False to answer the question on its own.
        """
        if not history:
            return False  # Nothing to send: no need to ask the model.
        try:
            decision = self._decider.invoke(self._input(history, question), self._config(config))
        except Exception as exc:
            # Safe fallback: a follow-up answered without context would be wrong.
            logger.warning("History router failed (%s); sending the history.", exc)
            return True
        return self._interpret(decision)

    async def aneeds_history(
        self,
        history: Sequence[BaseMessage],
        question: str,
        config: RunnableConfig | None = None,
    ) -> bool:
        """Asynchronous version of `needs_history`.

        Args:
            history: Full conversation, oldest first.
            question: The new question.
            config: Runnable config (callbacks/metadata for tracing).

        Returns:
            True to send the history, False to answer the question on its own.
        """
        if not history:
            return False
        try:
            decision = await self._decider.ainvoke(
                self._input(history, question), self._config(config)
            )
        except Exception as exc:
            logger.warning("History router failed (%s); sending the history.", exc)
            return True
        return self._interpret(decision)


def build_llm_history_router(model: BaseChatModel) -> HistoryRouter:
    """Create a router backed by a chat model with structured output.

    Args:
        model: Chat model that supports `with_structured_output` (e.g. ChatOpenAI).

    Returns:
        The history router.
    """
    decider = build_router_prompt() | model.with_structured_output(HistoryDecision)
    return HistoryRouter(decider)
