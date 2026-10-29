"""Database engine, session factory and the `get_db` dependency.

Connection limits (pool size, overflow, wait timeout, recycling) come from
`Settings`, so the number of simultaneous database connections is bounded and
a burst of requests waits briefly instead of exhausting the database.
"""

from collections.abc import Iterator
from typing import Any

from sqlalchemy import URL, Engine, create_engine, event, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.db.base import Base


def _is_in_memory_sqlite(url: URL) -> bool:
    """Tell whether the URL points to an in-memory SQLite database.

    Args:
        url: The parsed database URL.

    Returns:
        True for `sqlite://` and `sqlite:///:memory:`.
    """
    return url.get_backend_name() == "sqlite" and url.database in (None, "", ":memory:")


def _configure_sqlite(engine: Engine, *, use_wal: bool) -> None:
    """Apply SQLite PRAGMAs to every new connection.

    Args:
        engine: The SQLite engine.
        use_wal: Whether to enable write-ahead logging (file databases only).
    """

    @event.listens_for(engine, "connect")
    def set_sqlite_pragmas(dbapi_connection: Any, connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        # SQLite ignores foreign keys unless asked; enforce integrity by default.
        cursor.execute("PRAGMA foreign_keys=ON")
        if use_wal:
            # WAL lets readers keep working while a write is in progress.
            cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


def create_db_engine(settings: Settings) -> Engine:
    """Create a SQLAlchemy engine with bounded connections.

    Args:
        settings: Settings providing the URL and the connection limits.

    Returns:
        A configured `Engine`.
    """
    url = make_url(settings.database_url)
    # pre_ping discards dead connections instead of failing the request.
    options: dict[str, Any] = {"pool_pre_ping": True}

    if url.get_backend_name() == "sqlite":
        options["connect_args"] = {
            # FastAPI runs sync endpoints in a thread pool, so a SQLite connection
            # may be used by a different thread than the one that created it.
            "check_same_thread": False,
            # Wait for a lock held by another connection instead of failing at once.
            "timeout": settings.sqlite_busy_timeout_seconds,
        }

    # In-memory SQLite uses a single shared connection, so pool limits do not apply.
    if not _is_in_memory_sqlite(url):
        options.update(
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout_seconds,
            pool_recycle=settings.db_pool_recycle_seconds,
        )

    engine = create_engine(url, **options)
    if url.get_backend_name() == "sqlite":
        _configure_sqlite(engine, use_wal=not _is_in_memory_sqlite(url))
    return engine


def create_session_factory(bind: Engine) -> sessionmaker[Session]:
    """Create a session factory bound to an engine.

    Args:
        bind: The engine the sessions will use.

    Returns:
        A `sessionmaker` producing `Session` objects.
    """
    return sessionmaker(bind=bind, autoflush=False, expire_on_commit=False)


engine = create_db_engine(get_settings())
SessionLocal = create_session_factory(engine)


def init_db(bind: Engine) -> None:
    """Create all tables that do not exist yet.

    Args:
        bind: The engine where the tables will be created.
    """
    # Importing the models registers them in Base.metadata.
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=bind)


def get_db() -> Iterator[Session]:
    """Provide a database session for the duration of a request.

    Tests override this dependency through `app.dependency_overrides`.

    Yields:
        An open `Session` that is closed (returning its connection to the pool)
        when the request finishes.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
