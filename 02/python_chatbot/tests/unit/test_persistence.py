"""Tests of the web UI persistence (SQLite data layer and auth secret)."""

import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from chainlit.data.sql_alchemy import SQLAlchemyDataLayer
from chainlit.user import User

from app.ui.helpers import PUBLIC_USER_IDENTIFIER, steps_to_messages
from app.ui.persistence import (
    AUTH_SECRET_ENV,
    SQLiteDataLayer,
    ensure_auth_secret,
    ensure_schema,
    to_sqlite_value,
)


def _step(step_id: str, step_type: str, output: str, thread_id: str = "t1") -> dict[str, Any]:
    """Build a step dict shaped like the ones Chainlit saves for messages."""
    return {
        "id": step_id,
        "name": "Python Tutor" if step_type == "assistant_message" else "Visitante",
        "type": step_type,
        "threadId": thread_id,
        "streaming": False,
        "metadata": {},
        "tags": ["web"],
        "output": output,
        "createdAt": f"2026-10-28T12:00:0{step_id[-1]}Z",
        "showInput": False,
    }


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    """Path of a fresh SQLite database (in a folder that does not exist yet)."""
    return tmp_path / "data" / "chat.db"


# --- Schema -----------------------------------------------------------------------


def test_ensure_schema_creates_chainlit_tables(database_path: Path) -> None:
    """The database file and every table used by Chainlit are created."""
    ensure_schema(database_path)
    ensure_schema(database_path)  # idempotent

    with sqlite3.connect(database_path) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
    assert {"users", "threads", "steps", "elements", "feedbacks"} <= tables


@pytest.mark.parametrize(
    ("value", "expected"),
    [(["a", "b"], '["a", "b"]'), ({"k": 1}, '{"k": 1}'), ("text", "text"), (3, 3), (None, None)],
)
def test_to_sqlite_value_serializes_lists_and_dicts(value: Any, expected: Any) -> None:
    """Lists and dicts become JSON text; other values pass through."""
    assert to_sqlite_value(value) == expected


# --- Data layer (end to end on SQLite) --------------------------------------------


async def test_conversation_is_saved_listed_and_restored(database_path: Path) -> None:
    """A conversation is saved for the public user and its messages can be rebuilt."""
    layer = SQLiteDataLayer(database_path)
    user = await layer.create_user(User(identifier=PUBLIC_USER_IDENTIFIER))
    assert user is not None

    await layer.update_thread("t1", name="Listas", user_id=user.id, tags=["web"])
    # `create_step` queues writes inside a live Chainlit session; call it directly.
    create_step = SQLAlchemyDataLayer.create_step.__wrapped__
    await create_step(layer, _step("s1", "user_message", "Como criar uma lista?"))
    await create_step(layer, _step("s2", "assistant_message", "Use colchetes: []"))

    threads = await layer.get_all_user_threads(user_id=user.id)
    assert threads is not None
    assert [thread["name"] for thread in threads] == ["Listas"]

    thread = await layer.get_thread("t1")
    assert thread is not None
    messages = steps_to_messages(thread["steps"])
    assert [message.content for message in messages] == [
        "Como criar uma lista?",
        "Use colchetes: []",
    ]
    await layer.engine.dispose()


async def test_public_user_is_reused(database_path: Path) -> None:
    """Every visitor maps to the same persisted user (shared conversation list)."""
    layer = SQLiteDataLayer(database_path)

    first = await layer.create_user(User(identifier=PUBLIC_USER_IDENTIFIER))
    second = await layer.create_user(User(identifier=PUBLIC_USER_IDENTIFIER))

    assert first is not None and second is not None
    assert first.id == second.id
    await layer.engine.dispose()


# --- Auth secret --------------------------------------------------------------------


def test_auth_secret_from_environment_is_kept(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A secret configured in the environment wins and nothing is written."""
    monkeypatch.setenv(AUTH_SECRET_ENV, "from-env")
    secret_path = tmp_path / ".secret"

    assert ensure_auth_secret(secret_path) == "from-env"
    assert not secret_path.exists()


def test_auth_secret_is_generated_once_and_reused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Without configuration, a secret is generated, saved and reused on restart."""
    monkeypatch.setenv(AUTH_SECRET_ENV, "")
    secret_path = tmp_path / "data" / ".secret"

    first = ensure_auth_secret(secret_path)
    monkeypatch.setenv(AUTH_SECRET_ENV, "")  # simulate a new process
    second = ensure_auth_secret(secret_path)

    assert len(first) >= 32
    assert first == second == secret_path.read_text(encoding="utf-8")
    assert os.environ[AUTH_SECRET_ENV] == first
