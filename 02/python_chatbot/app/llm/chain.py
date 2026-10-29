"""Construction of the conversational LCEL chain and of the OpenAI chat model.

Flow of one turn:

    {"question", "use_history"} --RunnableWithMessageHistory--> + {"history"}
        -> keep the FULL history, or none if the router said it is not needed
        -> ChatPromptTemplate (system + history + question)
        -> chat model (ChatOpenAI in production, a fake model in tests)
        -> StrOutputParser (plain text, also when streaming)
    and the question/answer pair is appended to the session history.

The history is never cut: the size of a conversation is controlled by a token
budget checked in `ChatService` before each call (see `count_prompt_tokens`).
"""

from collections.abc import Callable, Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.messages.utils import count_tokens_approximately
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_openai import ChatOpenAI

from app.core.config import Settings
from app.core.exceptions import MissingAPIKeyError
from app.llm.history import SessionHistoryStore
from app.llm.prompts import HISTORY_KEY, QUESTION_KEY, build_chat_prompt

# Counts the tokens of a list of messages (the prompt sent to the model).
TokenCounter = Callable[[Sequence[BaseMessage]], int]

# Input flag telling the chain whether to send the history (set by the router).
USE_HISTORY_KEY = "use_history"


def approximate_token_counter(messages: Sequence[BaseMessage]) -> int:
    """Estimate the tokens of a prompt without a tokenizer (~4 characters per token).

    Used when the model has no tokenizer of its own (e.g. the fake models in tests).

    Args:
        messages: Messages to count.

    Returns:
        The estimated number of tokens.
    """
    return count_tokens_approximately(messages)


def build_token_counter(model: ChatOpenAI) -> TokenCounter:
    """Build an exact token counter for an OpenAI model.

    `ChatOpenAI.get_num_tokens_from_messages` uses `tiktoken` with the model's own
    encoding and adds the per-message overhead of the chat format.

    Args:
        model: The OpenAI chat model.

    Returns:
        A function that counts the tokens of a list of messages.
    """

    def count(messages: Sequence[BaseMessage]) -> int:
        return model.get_num_tokens_from_messages(list(messages))

    return count


def build_chat_chain(
    model: BaseChatModel, history_store: SessionHistoryStore
) -> RunnableWithMessageHistory:
    """Build the conversational chain with per-session memory.

    The model is received as a parameter (dependency injection) instead of being
    created here: production passes `ChatOpenAI`, while tests pass a fake chat
    model, so the whole flow is tested without calling the OpenAI API.

    Args:
        model: Any LangChain chat model.
        history_store: Where the histories of each session are kept.

    Returns:
        A runnable that expects `{"question": str, "use_history": bool}` and a config
        with `{"configurable": {"session_id": ...}}`, and outputs the answer as `str`.
    """
    # The history router may decide that a question is self-contained: then the
    # prompt gets no history (it is still saved, so later follow-ups keep working).
    select_history = RunnablePassthrough.assign(
        **{HISTORY_KEY: lambda x: x[HISTORY_KEY] if x.get(USE_HISTORY_KEY, True) else []}
    )

    # LCEL pipeline: render the prompt (with the full history or none), call the
    # model and extract the text of the answer.
    core_chain = select_history | build_chat_prompt() | model | StrOutputParser()

    # The wrapper loads the session history before each call (into `history`) and
    # stores the new question and answer after it (also when streaming).
    return RunnableWithMessageHistory(
        core_chain,
        get_session_history=history_store.get,
        input_messages_key=QUESTION_KEY,
        history_messages_key=HISTORY_KEY,
    )


def build_chat_model(settings: Settings) -> ChatOpenAI:
    """Create the OpenAI chat model from the settings.

    Args:
        settings: Application settings.

    Returns:
        A configured `ChatOpenAI` instance.

    Raises:
        MissingAPIKeyError: If `OPENAI_API_KEY` is not configured.
    """
    # Fail fast with an actionable message instead of an obscure OpenAI error later.
    if not settings.has_openai_api_key or settings.openai_api_key is None:
        raise MissingAPIKeyError()

    return ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        temperature=settings.openai_temperature,
        max_tokens=settings.openai_max_tokens,
        timeout=settings.openai_timeout,
        max_retries=settings.openai_max_retries,
    )


def build_router_model(settings: Settings) -> ChatOpenAI:
    """Create the model used by the history router.

    A separate, cheap and fast model (`HISTORY_ROUTER_MODEL`, default
    gpt-4.1-nano), deterministic (temperature 0) and with a tiny answer budget:
    it only returns a yes/no decision and a short reason.

    Args:
        settings: Application settings.

    Returns:
        A configured `ChatOpenAI` instance.

    Raises:
        MissingAPIKeyError: If `OPENAI_API_KEY` is not configured.
    """
    if not settings.has_openai_api_key or settings.openai_api_key is None:
        raise MissingAPIKeyError()

    return ChatOpenAI(
        model=settings.history_router_model,
        api_key=settings.openai_api_key,
        temperature=0,
        max_tokens=150,
        timeout=settings.openai_timeout,
        max_retries=settings.openai_max_retries,
    )
