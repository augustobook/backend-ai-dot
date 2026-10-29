"""Chainlit web chat of the Python Tutor.

Run with:  uv run chainlit run app/ui/chainlit_app.py -w --port 8001

The handlers are intentionally thin: they map Chainlit events to `ChatService`
calls and render the result. Pure logic lives in `app/ui/helpers.py` and the
conversation storage in `app/ui/persistence.py`.
"""

import logging

import chainlit as cl
from chainlit.types import ThreadDict
from langchain_core.callbacks import BaseCallbackHandler
from starlette.datastructures import Headers

from app.core.config import get_settings
from app.core.exceptions import ChatbotError
from app.core.logging import configure_logging
from app.core.rate_limit import get_default_rate_limiter
from app.core.tracing import configure_tracing
from app.services.chat_service import get_default_chat_service
from app.ui.helpers import (
    PUBLIC_USER_DISPLAY_NAME,
    PUBLIC_USER_IDENTIFIER,
    SESSION_ID_KEY,
    build_session_id,
    client_ip_from_environ,
    format_error_message,
    format_usage_warning,
    get_starter_specs,
    steps_to_messages,
)
from app.ui.persistence import SQLiteDataLayer, ensure_auth_secret

logger = logging.getLogger(__name__)

settings = get_settings()
configure_logging(settings.log_level)
configure_tracing(settings)

# Chainlit requires a JWT secret as soon as a login callback exists. It is read
# from CHAINLIT_AUTH_SECRET or generated once next to the database.
ensure_auth_secret(settings.chainlit_database_path.with_name(".chainlit_auth_secret"))


def _current_session_id() -> str:
    """Return the conversation id of the current Chainlit session."""
    session_id: str | None = cl.user_session.get(SESSION_ID_KEY)
    return session_id or build_session_id(cl.context.session.thread_id)


# --- Conversation list (persistence + automatic login) ---------------------------


@cl.data_layer
def get_data_layer() -> SQLiteDataLayer:
    """Store the conversations in SQLite so they appear in the side list."""
    return SQLiteDataLayer(settings.chainlit_database_path)


@cl.header_auth_callback
async def header_auth_callback(headers: Headers) -> cl.User:
    """Log every visitor in automatically as the shared public user.

    The chat is open to everyone (no login screen); Chainlit still needs a user
    to own the conversations, so all of them belong to this single user.

    Args:
        headers: Request headers (unused).

    Returns:
        The shared public user.
    """
    return cl.User(
        identifier=PUBLIC_USER_IDENTIFIER,
        display_name=PUBLIC_USER_DISPLAY_NAME,
        metadata={"role": "guest", "provider": "header"},
    )


# --- Chat lifecycle ---------------------------------------------------------------


@cl.set_starters
async def set_starters(
    user: cl.User | None = None, language: str | None = None
) -> list[cl.Starter]:
    """Provide the suggested questions of the welcome screen.

    Args:
        user: Logged-in user (unused: starters are the same for everyone).
        language: Browser language (unused: starters are fixed).

    Returns:
        The Chainlit starters.
    """
    return [
        cl.Starter(label=spec.label, message=spec.message, icon=spec.icon)
        for spec in get_starter_specs()
    ]


@cl.on_chat_start
async def on_chat_start() -> None:
    """Start a conversation: bind the Chainlit thread to a chat session id."""
    session_id = build_session_id(cl.context.session.thread_id)
    cl.user_session.set(SESSION_ID_KEY, session_id)
    logger.info("Web chat started (session=%s).", session_id)


@cl.on_chat_resume
async def on_chat_resume(thread: ThreadDict) -> None:
    """Reopen a saved conversation and restore the model's memory of it.

    Args:
        thread: The saved conversation, with its steps (messages).
    """
    session_id = build_session_id(thread["id"])
    cl.user_session.set(SESSION_ID_KEY, session_id)
    try:
        get_default_chat_service().restore_history(session_id, steps_to_messages(thread["steps"]))
    except ChatbotError as exc:
        await cl.ErrorMessage(content=format_error_message(exc)).send()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    """Answer a user message, streaming the response token by token.

    Args:
        message: Message typed by the user (or sent by a starter).
    """
    session_id = _current_session_id()
    reply = cl.Message(content="")

    # Optionally show the LangChain steps (prompt, model call) in the UI.
    callbacks: list[BaseCallbackHandler] | None = (
        [cl.LangchainCallbackHandler()] if settings.chainlit_show_chain_steps else None
    )

    try:
        # Checked first, so a refused question never reaches OpenAI.
        get_default_rate_limiter().check(client_ip_from_environ(cl.context.session.environ))
        service = get_default_chat_service()
        async for token in service.astream(
            session_id, message.content, interface="web", callbacks=callbacks
        ):
            await reply.stream_token(token)
    except ChatbotError as exc:
        # Too many questions, missing key, invalid key, timeout, conversation full...: show
        # it in the chat instead of breaking the interface.
        await cl.ErrorMessage(content=format_error_message(exc)).send()
        if reply.content:
            await reply.send()
        return

    # Finalize the streamed message.
    if reply.content:
        await reply.send()

    # Warn (with a toast, which is not saved in the history) when the conversation
    # is close to its size limit.
    usage = service.get_usage(session_id)
    if usage.near_limit:
        await cl.context.emitter.send_toast(format_usage_warning(usage.percent), "warning")


@cl.on_chat_end
async def on_chat_end() -> None:
    """Free the in-memory history; it is restored from the database on resume."""
    session_id = _current_session_id()
    try:
        get_default_chat_service().clear_history(session_id)
    except ChatbotError:
        # Without a configured service there is no history to clear.
        logger.debug("No chat service available; nothing to clear for %s.", session_id)
