"""In-memory storage of the conversation history, one history per session.

Each `session_id` (a CLI run, an API client, a Chainlit tab) gets its own
`InMemoryChatMessageHistory`, so conversations never leak into each other.
"""

import threading
from collections.abc import Sequence

from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_core.messages import BaseMessage


class SessionHistoryStore:
    """Thread-safe registry of chat histories keyed by session id.

    The store is in memory: histories are lost when the process stops. That is
    enough for this project; swapping it for Redis/SQL-backed histories would only
    require changing this class.
    """

    def __init__(self) -> None:
        """Create an empty store."""
        self._histories: dict[str, InMemoryChatMessageHistory] = {}
        # FastAPI runs requests concurrently, so access to the dict is guarded.
        self._lock = threading.Lock()

    def get(self, session_id: str) -> InMemoryChatMessageHistory:
        """Return the history of a session, creating it on first use.

        This is the `get_session_history` factory used by `RunnableWithMessageHistory`.

        Args:
            session_id: Identifier of the conversation.

        Returns:
            The (possibly new) history for the session.
        """
        with self._lock:
            if session_id not in self._histories:
                self._histories[session_id] = InMemoryChatMessageHistory()
            return self._histories[session_id]

    def replace(self, session_id: str, messages: Sequence[BaseMessage]) -> None:
        """Overwrite the history of a session with the given messages.

        Used to rebuild the memory of a conversation reopened from persistent
        storage (e.g. the web UI's conversation list).

        Args:
            session_id: Identifier of the conversation.
            messages: Messages of the conversation, oldest first.
        """
        history = InMemoryChatMessageHistory()
        history.add_messages(messages)
        with self._lock:
            self._histories[session_id] = history

    def clear(self, session_id: str) -> bool:
        """Delete the history of a session.

        Args:
            session_id: Identifier of the conversation.

        Returns:
            True if a history existed and was removed, False otherwise.
        """
        with self._lock:
            return self._histories.pop(session_id, None) is not None

    def __contains__(self, session_id: object) -> bool:
        """Tell whether a session already has a history.

        Args:
            session_id: Identifier of the conversation.

        Returns:
            True if the session is known.
        """
        with self._lock:
            return session_id in self._histories

    def __len__(self) -> int:
        """Return the number of sessions currently stored."""
        with self._lock:
            return len(self._histories)
