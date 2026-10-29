"""Bring the database schema up to date with the Alembic migrations.

The schema is defined by the migrations in `app/db/migrations/versions`, not by
`Base.metadata.create_all`: `create_all` only creates missing tables and never
changes an existing one, so a new column or index would never reach a database
that already has data.
"""

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# The migration that matches the schema the API created before Alembic was adopted.
BASELINE_REVISION = "0001"


def _alembic_config() -> Config:
    """Build the Alembic configuration without needing a config file.

    Returns:
        A configuration pointing to the migrations folder.
    """
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return config


def migrate_db(bind: Engine) -> None:
    """Apply every pending migration.

    A database created by earlier versions of the API (with `create_all`) already
    has the `books` table but no `alembic_version` table. It is marked as being at
    the baseline revision first, so the upgrade does not try to create the table
    again and the stored books are kept.

    Args:
        bind: The engine of the database to migrate.
    """
    config = _alembic_config()
    with bind.begin() as connection:
        config.attributes["connection"] = connection
        tables = set(inspect(connection).get_table_names())
        if "books" in tables and "alembic_version" not in tables:
            logger.info("Existing database without migrations: stamping %s", BASELINE_REVISION)
            command.stamp(config, BASELINE_REVISION)
        command.upgrade(config, "head")
