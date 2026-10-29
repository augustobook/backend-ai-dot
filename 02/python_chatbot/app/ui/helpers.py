"""Pure helper functions of the Chainlit interface.

They do not import Chainlit, so they can be unit tested without a running server;
`chainlit_app.py` only glues them to the Chainlit decorators.

The web interface is shown in Brazilian Portuguese, so the user-facing texts
defined here (starters, error messages) are in Portuguese.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.core.config import MAX_QUESTION_LENGTH
from app.core.exceptions import (
    ChatbotError,
    ConversationLimitError,
    LLMAuthenticationError,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
    MissingAPIKeyError,
    QuestionTooLongError,
)

# Key under which the `ChatService` session id is stored in `cl.user_session`.
SESSION_ID_KEY = "chat_session_id"

# Prefix that identifies web sessions in logs and LangSmith traces.
SESSION_ID_PREFIX = "web-"

# The chat is open to everyone: all visitors share this automatic user, which is
# what lets Chainlit show the (shared) conversation list without a login screen.
PUBLIC_USER_IDENTIFIER = "public"
PUBLIC_USER_DISPLAY_NAME = "Visitante"

# Chainlit step types of the messages typed by the user and answered by the bot.
USER_MESSAGE_STEP = "user_message"
ASSISTANT_MESSAGE_STEP = "assistant_message"


@dataclass(frozen=True, slots=True)
class StarterSpec:
    """A suggested question shown on the Chainlit welcome screen.

    Attributes:
        label: Short text displayed on the button.
        message: Question sent when the button is clicked.
        icon: Icon URL (served from the `public/` folder).
    """

    label: str
    message: str
    icon: str


STARTERS: tuple[StarterSpec, ...] = (
    StarterSpec(
        label="Criar uma lista",
        message="Como criar uma lista em Python?",
        icon="/public/icons/list.svg",
    ),
    StarterSpec(
        label="Lista vs. tupla",
        message="Qual a diferença entre lista e tupla?",
        icon="/public/icons/compare.svg",
    ),
    StarterSpec(
        label="Decorators",
        message="O que são decorators?",
        icon="/public/icons/decorator.svg",
    ),
    StarterSpec(
        label="Tratar exceções",
        message="Como tratar exceções em Python?",
        icon="/public/icons/shield.svg",
    ),
)

# Portuguese texts for each domain error. The exceptions keep their English
# messages for the CLI/API; lookup follows the class hierarchy (most specific first).
ERROR_MESSAGES: dict[type[ChatbotError], str] = {
    QuestionTooLongError: (
        f"Sua pergunta é longa demais. Reduza para no máximo {MAX_QUESTION_LENGTH} "
        "caracteres e tente novamente."
    ),
    ConversationLimitError: (
        "Esta conversa atingiu o tamanho máximo que o modelo consegue processar. "
        "Clique em **Novo chat** para continuar com uma nova conversa."
    ),
    MissingAPIKeyError: (
        "A chave da API da OpenAI não está configurada. Copie o arquivo `.env.example` "
        "para `.env`, preencha `OPENAI_API_KEY` e reinicie a aplicação."
    ),
    LLMAuthenticationError: (
        "O serviço de IA recusou a chave de API configurada. "
        "Verifique se a `OPENAI_API_KEY` é válida."
    ),
    LLMRateLimitError: (
        "O serviço de IA está recebendo muitas requisições (ou a cota foi excedida). "
        "Aguarde alguns segundos e tente novamente."
    ),
    LLMTimeoutError: "O serviço de IA demorou demais para responder. Tente novamente.",
    LLMError: (
        "O serviço de IA está indisponível no momento. Verifique sua conexão "
        "e tente novamente em instantes."
    ),
    ChatbotError: "Ocorreu um erro inesperado. Tente novamente.",
}


def get_starter_specs() -> list[StarterSpec]:
    """Return the suggested questions of the welcome screen.

    Returns:
        A new list with the starters, in display order.
    """
    return list(STARTERS)


def build_session_id(chainlit_thread_id: str) -> str:
    """Map a Chainlit thread (conversation) id to the `ChatService` session id.

    The thread id is used (not the websocket session id) because it stays the same
    when a conversation is reopened from the conversation list.

    Args:
        chainlit_thread_id: `cl.context.session.thread_id` or a saved thread's id.

    Returns:
        The id used for the conversation history.

    Raises:
        ValueError: If the thread id is empty.
    """
    cleaned = chainlit_thread_id.strip()
    if not cleaned:
        raise ValueError("The Chainlit thread id must not be empty.")
    return f"{SESSION_ID_PREFIX}{cleaned}"


def steps_to_messages(steps: Iterable[Mapping[str, Any]]) -> list[BaseMessage]:
    """Rebuild the chat history of a saved conversation from its Chainlit steps.

    Only user questions and assistant answers matter to the model; other steps
    (e.g. LangChain runs shown in the UI) and empty messages are skipped.

    Args:
        steps: Steps of a saved thread, oldest first.

    Returns:
        The conversation as LangChain messages.
    """
    messages: list[BaseMessage] = []
    for step in steps:
        text = (step.get("output") or "").strip()
        if not text:
            continue
        if step.get("type") == USER_MESSAGE_STEP:
            messages.append(HumanMessage(text))
        elif step.get("type") == ASSISTANT_MESSAGE_STEP:
            messages.append(AIMessage(text))
    return messages


def format_usage_warning(percent: int) -> str:
    """Build the warning shown when a conversation is close to its size limit.

    Args:
        percent: Share of the conversation token budget already in use (0-100).

    Returns:
        A short Portuguese message for a toast notification.
    """
    return (
        f"Esta conversa já usa {percent}% do tamanho máximo. "
        "Em breve será preciso iniciar um Novo chat."
    )


def translate_error(error: ChatbotError) -> str:
    """Return the Portuguese explanation of a domain error.

    Args:
        error: Domain error raised by the service.

    Returns:
        The message of the closest error class in `ERROR_MESSAGES`.
    """
    # Walk the class hierarchy so subclasses without their own text (e.g.
    # LLMUnavailableError) fall back to their parent's message.
    # `ChatbotError` is always in the hierarchy, so a message is always found.
    return next(ERROR_MESSAGES[cls] for cls in type(error).__mro__ if cls in ERROR_MESSAGES)


def format_error_message(error: ChatbotError) -> str:
    """Build the friendly chat message shown when the chatbot fails.

    Args:
        error: Domain error raised by the service.

    Returns:
        A Markdown message for the chat, in Portuguese.
    """
    return f"⚠️ **Desculpe, não consegui responder.**\n\n{translate_error(error)}"
