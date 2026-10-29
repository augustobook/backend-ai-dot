"""Alembic environment: runs the migrations against the application's database.

Two ways in:

* From the application (`app.db.migrate.migrate_db`), which passes an open
  connection in `config.attributes["connection"]`. The tests use this path with
  their in-memory database.
* From the `alembic` command line (e.g. `uv run alembic revision --autogenerate`),
  which builds an engine from the same `Settings` as the application.
"""

from alembic import context
from sqlalchemy.engine import Connection

import app.models  # noqa: F401  (registers the models in Base.metadata)
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import create_db_engine

target_metadata = Base.metadata


def run_migrations(connection: Connection) -> None:
    """Run the pending migrations on an open connection.

    Args:
        connection: The connection to migrate.
    """
    # SQLite cannot ALTER most column properties; batch mode rebuilds the table
    # instead, so future migrations work on SQLite and on other databases alike.
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    """Print the migration SQL instead of running it (`alembic upgrade --sql`)."""
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run the migrations on the given connection, or on a new one from the settings."""
    connection = context.config.attributes.get("connection")
    if connection is not None:
        run_migrations(connection)
        return

    engine = create_db_engine(get_settings())
    try:
        with engine.begin() as new_connection:
            run_migrations(new_connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
