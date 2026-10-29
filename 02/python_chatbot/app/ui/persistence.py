"""Persistence of the web UI conversations (Chainlit data layer on SQLite).

Chainlit only shows the conversation list when a data layer is configured and a
user is logged in. This module provides:

- the SQLite schema expected by Chainlit's `SQLAlchemyDataLayer`;
- `SQLiteDataLayer`, which adapts that layer to SQLite;
- `ensure_auth_secret`, the JWT secret Chainlit requires once a login callback
  exists (even the automatic, password-less one used here).
"""

import json
import logging
import os
import secrets
import sqlite3
from pathlib import Path
from typing import Any

from chainlit.data.sql_alchemy import SQLAlchemyDataLayer

logger = logging.getLogger(__name__)

AUTH_SECRET_ENV = "CHAINLIT_AUTH_SECRET"

# Tables and columns used by Chainlit's SQLAlchemyDataLayer (Chainlit 2.x).
# Column names are camelCase and quoted because the data layer writes the keys of
# Chainlit's dicts (StepDict, ElementDict...) directly as column names.
SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS users (
        "id" TEXT PRIMARY KEY,
        "identifier" TEXT NOT NULL UNIQUE,
        "metadata" TEXT NOT NULL,
        "createdAt" TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS threads (
        "id" TEXT PRIMARY KEY,
        "createdAt" TEXT,
        "name" TEXT,
        "userId" TEXT,
        "userIdentifier" TEXT,
        "tags" TEXT,
        "metadata" TEXT,
        FOREIGN KEY ("userId") REFERENCES users("id") ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS steps (
        "id" TEXT PRIMARY KEY,
        "name" TEXT NOT NULL,
        "type" TEXT NOT NULL,
        "threadId" TEXT NOT NULL,
        "parentId" TEXT,
        "command" TEXT,
        "modes" TEXT,
        "streaming" BOOLEAN NOT NULL,
        "waitForAnswer" BOOLEAN,
        "isError" BOOLEAN,
        "metadata" TEXT,
        "tags" TEXT,
        "input" TEXT,
        "output" TEXT,
        "createdAt" TEXT,
        "start" TEXT,
        "end" TEXT,
        "generation" TEXT,
        "showInput" TEXT,
        "defaultOpen" BOOLEAN,
        "autoCollapse" BOOLEAN,
        "language" TEXT,
        "icon" TEXT,
        "feedback" TEXT,
        FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS elements (
        "id" TEXT PRIMARY KEY,
        "threadId" TEXT,
        "type" TEXT,
        "chainlitKey" TEXT,
        "path" TEXT,
        "url" TEXT,
        "objectKey" TEXT,
        "name" TEXT NOT NULL,
        "display" TEXT,
        "size" TEXT,
        "language" TEXT,
        "page" INTEGER,
        "props" TEXT,
        "autoPlay" BOOLEAN,
        "playerConfig" TEXT,
        "forId" TEXT,
        "mime" TEXT,
        FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS feedbacks (
        "id" TEXT PRIMARY KEY,
        "forId" TEXT NOT NULL,
        "threadId" TEXT NOT NULL,
        "value" INTEGER NOT NULL,
        "comment" TEXT,
        FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
    )
    """,
)


def ensure_schema(database_path: Path) -> None:
    """Create the database file and the Chainlit tables if they do not exist.

    Args:
        database_path: Path of the SQLite file.
    """
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as connection:
        for statement in SCHEMA:
            connection.execute(statement)


def to_sqlite_value(value: Any) -> Any:
    """Convert a parameter into a type SQLite can store.

    Chainlit passes lists (e.g. tags) and dicts that PostgreSQL stores as arrays/JSON;
    SQLite cannot bind them, so they are serialized as JSON text.

    Args:
        value: Parameter value.

    Returns:
        The value itself, or its JSON text for lists and dicts.
    """
    if isinstance(value, list | dict):
        return json.dumps(value)
    return value


class SQLiteDataLayer(SQLAlchemyDataLayer):
    """Chainlit's SQLAlchemy data layer adapted to a local SQLite file.

    Args:
        database_path: Path of the SQLite file (created with its tables if missing).
    """

    def __init__(self, database_path: Path) -> None:
        """Create the tables and connect through the async `aiosqlite` driver."""
        ensure_schema(database_path)
        super().__init__(conninfo=f"sqlite+aiosqlite:///{database_path.as_posix()}")

    async def execute_sql(self, query: str, parameters: dict[str, Any]) -> Any:
        """Run a query after converting parameters to SQLite-compatible values.

        Args:
            query: SQL with named parameters.
            parameters: Values of the parameters.

        Returns:
            The rows (list of dicts), the affected row count, or None on error.
        """
        converted = {key: to_sqlite_value(value) for key, value in parameters.items()}
        return await super().execute_sql(query, converted)


def ensure_auth_secret(secret_path: Path) -> str:
    """Make sure Chainlit has a JWT secret to sign the session cookie.

    Order of precedence: the `CHAINLIT_AUTH_SECRET` variable (e.g. from `.env`), a
    secret previously saved in `secret_path`, or a new random secret saved there,
    so sessions survive restarts without manual setup.

    Args:
        secret_path: File used to persist the generated secret.

    Returns:
        The secret in use (also exported to the environment).
    """
    secret = os.environ.get(AUTH_SECRET_ENV, "").strip()
    if not secret:
        if secret_path.is_file():
            secret = secret_path.read_text(encoding="utf-8").strip()
        if not secret:
            secret = secrets.token_urlsafe(48)
            secret_path.parent.mkdir(parents=True, exist_ok=True)
            secret_path.write_text(secret, encoding="utf-8")
            logger.info("Generated a Chainlit auth secret at %s.", secret_path)
        os.environ[AUTH_SECRET_ENV] = secret
    return secret
