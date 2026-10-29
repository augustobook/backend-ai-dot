"""Tests of the Alembic migrations against real SQLite databases."""

from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

import app.models  # noqa: F401  (registers the models in Base.metadata)
from app.db.base import Base
from app.db.migrate import BASELINE_REVISION, migrate_db


def test_migrations_match_the_models(tmp_path: Path) -> None:
    """After every migration, the schema is exactly what the ORM models declare.

    Catches a model change committed without its migration.
    """
    engine = create_engine(f"sqlite:///{tmp_path / 'library.db'}")
    migrate_db(engine)

    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)

    assert differences == []
    engine.dispose()


def test_migrate_db_is_idempotent(tmp_path: Path) -> None:
    """Running the migrations twice (two app restarts) changes nothing."""
    engine = create_engine(f"sqlite:///{tmp_path / 'library.db'}")

    migrate_db(engine)
    migrate_db(engine)

    with engine.connect() as connection:
        assert MigrationContext.configure(connection).get_current_revision() is not None
    engine.dispose()


def test_database_created_before_alembic_is_adopted_with_its_data(tmp_path: Path) -> None:
    """A database made by `create_all` is stamped at the baseline and keeps its books."""
    engine = create_engine(f"sqlite:///{tmp_path / 'library.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO books (title, author, publication_date, summary, created_at) "
                "VALUES ('Dune', 'Frank Herbert', '1965-08-01', '', '2024-01-01 00:00:00')"
            )
        )

    migrate_db(engine)

    with engine.connect() as connection:
        assert "alembic_version" in inspect(connection).get_table_names()
        assert MigrationContext.configure(connection).get_current_revision() is not None
        assert connection.execute(text("SELECT title FROM books")).scalars().all() == ["Dune"]
    assert BASELINE_REVISION == "0001"
    engine.dispose()
