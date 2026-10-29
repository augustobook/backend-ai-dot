"""Unit tests for infrastructure pieces: settings, custom column types and sessions."""

from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import sqlite
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool

from app.core.config import Settings, get_settings
from app.db.session import create_db_engine, get_db
from app.db.types import UTCDateTime
from app.schemas.book import BookCreate
from tests.factories import make_book

DIALECT = sqlite.dialect()


def test_settings_reject_default_page_size_above_max() -> None:
    """`default_page_size` greater than `max_page_size` is a configuration error."""
    with pytest.raises(ValidationError):
        Settings(default_page_size=50, max_page_size=10)


def test_settings_can_be_overridden_by_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Environment variables override the default settings."""
    monkeypatch.setenv("MAX_PAGE_SIZE", "500")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    settings = Settings()

    assert settings.max_page_size == 500
    assert settings.log_level == "DEBUG"


def test_get_settings_is_cached() -> None:
    """`get_settings` returns the same instance on every call."""
    assert get_settings() is get_settings()


def test_utc_datetime_bind_converts_to_utc() -> None:
    """Aware values are converted to UTC and naive values are assumed to be UTC."""
    column_type = UTCDateTime()
    brazil = timezone(timedelta(hours=-3))

    aware = column_type.process_bind_param(datetime(2024, 1, 1, 9, 0, tzinfo=brazil), DIALECT)
    naive = column_type.process_bind_param(datetime(2024, 1, 1, 9, 0), DIALECT)

    assert aware == datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
    assert naive == datetime(2024, 1, 1, 9, 0, tzinfo=UTC)
    assert column_type.process_bind_param(None, DIALECT) is None


def test_utc_datetime_result_is_always_aware_utc() -> None:
    """Values read from the database are returned as aware UTC datetimes."""
    column_type = UTCDateTime()
    brazil = timezone(timedelta(hours=-3))

    from_naive = column_type.process_result_value(datetime(2024, 1, 1, 12, 0), DIALECT)
    from_aware = column_type.process_result_value(
        datetime(2024, 1, 1, 9, 0, tzinfo=brazil), DIALECT
    )

    assert from_naive == datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
    assert from_aware == datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
    assert column_type.process_result_value(None, DIALECT) is None


def test_book_create_with_null_created_at_is_allowed() -> None:
    """An explicit `null` for `created_at` behaves like an omitted value."""
    data = BookCreate(
        title="Dune", author="Frank Herbert", publication_date=date(1965, 8, 1), created_at=None
    )

    assert data.created_at is None


def test_create_db_engine_for_in_memory_sqlite() -> None:
    """An in-memory SQLite URL produces a working SQLite engine with foreign keys on."""
    engine = create_db_engine(Settings(_env_file=None, database_url="sqlite://"))

    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    assert engine.dialect.name == "sqlite"
    engine.dispose()


def test_create_db_engine_applies_pool_limits_and_wal(tmp_path: Path) -> None:
    """A file database gets the configured pool limits and WAL journaling."""
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{(tmp_path / 'pool.db').as_posix()}",
        db_pool_size=3,
        db_max_overflow=2,
        db_pool_timeout_seconds=7,
    )
    engine = create_db_engine(settings)

    pool = engine.pool
    assert isinstance(pool, QueuePool)
    assert pool.size() == 3
    assert pool._max_overflow == 2
    assert pool._timeout == 7
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
    engine.dispose()


def test_settings_parse_comma_separated_lists_and_blank_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """List settings accept comma-separated values; a blank API key disables it."""
    monkeypatch.setenv("CORS_ORIGINS", "http://a.com, http://b.com")
    monkeypatch.setenv("ALLOWED_HOSTS", "example.com")
    monkeypatch.setenv("API_KEY", "  ")

    settings = Settings(_env_file=None)

    assert settings.cors_origins == ["http://a.com", "http://b.com"]
    assert settings.allowed_hosts == ["example.com"]
    assert settings.api_key is None


def test_get_db_yields_session_and_closes_it() -> None:
    """`get_db` yields a session and finishes cleanly when the request ends.

    No query is run, so the real database is never opened.
    """
    generator = get_db()

    session = next(generator)

    assert isinstance(session, Session)
    with pytest.raises(StopIteration):
        next(generator)


def test_book_repr_includes_identifying_fields() -> None:
    """The ORM model's repr shows id, title and author."""
    book = make_book(title="Dune", author="Frank Herbert")

    assert repr(book) == "Book(id=None, title='Dune', author='Frank Herbert')"
