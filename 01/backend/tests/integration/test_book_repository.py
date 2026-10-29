"""Integration tests for `BookRepository` against an in-memory SQLite database."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.repositories.book_repository import BookRepository
from tests.factories import make_book


@pytest.fixture
def repository(db_session: Session) -> BookRepository:
    """Provide a repository bound to the test session."""
    return BookRepository(db_session)


@pytest.fixture
def seeded_repository(repository: BookRepository) -> BookRepository:
    """Provide a repository pre-populated with a few books."""
    repository.add(make_book(title="Harry Potter and the Philosopher's Stone"))
    repository.add(make_book(title="Harry Potter and the Chamber of Secrets"))
    repository.add(make_book(title="The Hobbit", author="J. R. R. Tolkien"))
    repository.add(make_book(title="100% Effective", author="Percent_Author"))
    return repository


def test_add_assigns_id_and_persists(repository: BookRepository, db_session: Session) -> None:
    """Adding a book generates an id and stores it in the database."""
    book = repository.add(make_book())

    assert book.id is not None
    db_session.expire_all()
    assert repository.get_by_id(book.id) is not None


def test_get_by_id_returns_none_for_missing_book(repository: BookRepository) -> None:
    """Looking up an unknown id returns `None`."""
    assert repository.get_by_id(999) is None


def test_created_at_round_trips_as_utc(repository: BookRepository, db_session: Session) -> None:
    """Datetimes in other timezones are stored and read back as UTC."""
    brazil = timezone(timedelta(hours=-3))
    book = repository.add(make_book(created_at=datetime(2024, 1, 1, 9, 0, tzinfo=brazil)))

    db_session.expire_all()
    loaded = repository.get_by_id(book.id)

    assert loaded is not None
    assert loaded.created_at == datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
    assert loaded.created_at.tzinfo == UTC


def test_search_by_partial_title_is_case_insensitive(seeded_repository: BookRepository) -> None:
    """Title search matches partial text regardless of case."""
    result = seeded_repository.search(title="hArRy", author=None, skip=0, limit=10)

    assert len(result) == 2
    assert all("Harry" in book.title for book in result)


def test_search_by_partial_author(seeded_repository: BookRepository) -> None:
    """Author search matches partial text regardless of case."""
    result = seeded_repository.search(title=None, author="tolkien", skip=0, limit=10)

    assert [book.title for book in result] == ["The Hobbit"]


def test_search_combines_title_and_author(seeded_repository: BookRepository) -> None:
    """When both filters are given, a book must match both."""
    result = seeded_repository.search(title="chamber", author="rowling", skip=0, limit=10)
    no_match = seeded_repository.search(title="hobbit", author="rowling", skip=0, limit=10)

    assert [book.title for book in result] == ["Harry Potter and the Chamber of Secrets"]
    assert no_match == []


def test_search_treats_like_wildcards_literally(seeded_repository: BookRepository) -> None:
    """`%` and `_` in search terms are matched literally, not as wildcards."""
    by_title = seeded_repository.search(title="0%", author=None, skip=0, limit=10)
    by_author = seeded_repository.search(title=None, author="t_a", skip=0, limit=10)

    assert [book.title for book in by_title] == ["100% Effective"]
    assert [book.author for book in by_author] == ["Percent_Author"]
    assert seeded_repository.search(title="%", author=None, skip=0, limit=10) == by_title


def test_search_without_filters_returns_all_ordered_by_id(
    seeded_repository: BookRepository,
) -> None:
    """Without filters, every book is returned in insertion order."""
    result = seeded_repository.search(title=None, author=None, skip=0, limit=10)

    assert len(result) == 4
    assert [book.id for book in result] == sorted(book.id for book in result)


def test_search_paginates_with_skip_and_limit(seeded_repository: BookRepository) -> None:
    """`skip` and `limit` select a window of the ordered results."""
    all_books = seeded_repository.search(title=None, author=None, skip=0, limit=10)

    page = seeded_repository.search(title=None, author=None, skip=1, limit=2)

    assert [book.id for book in page] == [book.id for book in all_books[1:3]]
