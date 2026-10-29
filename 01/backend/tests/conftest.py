"""Shared pytest fixtures.

Every test gets a brand-new in-memory SQLite database, so tests are isolated
from each other and never touch the real database file.
"""

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.db.session import create_session_factory, get_db, init_db
from app.main import create_app
from tests.factories import make_book_payload


@pytest.fixture
def engine() -> Iterator[Engine]:
    """Provide an engine for a fresh in-memory SQLite database with all tables.

    `StaticPool` keeps a single connection, so every session (and the
    TestClient's worker thread) sees the same in-memory database.

    Yields:
        The test engine.
    """
    test_engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(test_engine)
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def db_session(engine: Engine) -> Iterator[Session]:
    """Provide a session bound to the test database.

    Args:
        engine: The test engine.

    Yields:
        An open session, closed after the test.
    """
    session = create_session_factory(engine)()
    try:
        yield session
    finally:
        session.close()


def make_settings(**overrides: Any) -> Settings:
    """Build settings for tests, ignoring any local `.env` file.

    Security features keep their defaults unless overridden, except that the
    TestClient host (`testserver`) is allowed and no API key is required.

    Args:
        **overrides: Settings to change.

    Returns:
        The test settings.
    """
    values: dict[str, Any] = {
        "database_url": "sqlite://",
        "allowed_hosts": ["testserver"],
        "api_key": None,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


AppFactory = Callable[..., TestClient]


@pytest.fixture
def make_client(engine: Engine) -> Iterator[AppFactory]:
    """Provide a factory of TestClients using the test database.

    Args:
        engine: The test engine.

    Yields:
        A function accepting settings overrides (plus `raise_server_exceptions`)
        and returning a started TestClient.
    """
    session_factory = create_session_factory(engine)
    clients: list[TestClient] = []

    def override_get_db() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    def factory(raise_server_exceptions: bool = True, **overrides: Any) -> TestClient:
        app = create_app(settings=make_settings(**overrides), db_engine=engine)
        app.dependency_overrides[get_db] = override_get_db
        test_client = TestClient(app, raise_server_exceptions=raise_server_exceptions)
        test_client.__enter__()
        clients.append(test_client)
        return test_client

    yield factory
    for test_client in clients:
        test_client.__exit__(None, None, None)


@pytest.fixture
def client(make_client: AppFactory) -> TestClient:
    """Provide a TestClient with the default (test) settings.

    Args:
        make_client: The client factory.

    Returns:
        A started TestClient.
    """
    return make_client()


@pytest.fixture
def create_book(client: TestClient) -> Callable[..., dict[str, Any]]:
    """Provide a helper that registers a book through the API.

    Args:
        client: The test client.

    Returns:
        A function accepting payload overrides and returning the created book.
    """

    def _create(**overrides: Any) -> dict[str, Any]:
        response = client.post("/books", json=make_book_payload(**overrides))
        assert response.status_code == 201, response.text
        body: dict[str, Any] = response.json()
        return body

    return _create
