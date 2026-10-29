"""Unit tests for `BookService`, using an in-memory fake repository."""

import logging
from datetime import UTC, date, datetime

import pytest

from app.core.exceptions import BookNotFoundError
from app.models.book import Book
from app.repositories.book_repository import BookRepositoryProtocol
from app.schemas.book import BookCreate, BookUpdate
from app.services.book_service import BookService, utc_now
from tests.factories import make_book

FIXED_NOW = datetime(2025, 1, 15, 12, 0, tzinfo=UTC)


class InMemoryBookRepository:
    """Fake repository implementing `BookRepositoryProtocol` with a dict."""

    def __init__(self) -> None:
        """Start with an empty store."""
        self.books: dict[int, Book] = {}
        self.last_search: dict[str, object] = {}
        self._next_id = 1

    def add(self, book: Book) -> Book:
        """Store the book and assign it the next id."""
        book.id = self._next_id
        self.books[book.id] = book
        self._next_id += 1
        return book

    def get_by_id(self, book_id: int) -> Book | None:
        """Return the stored book or `None`."""
        return self.books.get(book_id)

    def update(self, book: Book) -> Book:
        """Objects are stored by reference, so changes are already kept."""
        return book

    def delete(self, book: Book) -> None:
        """Remove the book from the store."""
        del self.books[book.id]

    def _matches(self, title: str | None, author: str | None) -> list[Book]:
        """Return the stored books matching the filters, by case-insensitive containment."""
        return [
            book
            for book in self.books.values()
            if (title is None or title.casefold() in book.title.casefold())
            and (author is None or author.casefold() in book.author.casefold())
        ]

    def search(self, *, title: str | None, author: str | None, skip: int, limit: int) -> list[Book]:
        """Return one page of the matching books."""
        self.last_search = {"title": title, "author": author, "skip": skip, "limit": limit}
        return self._matches(title, author)[skip : skip + limit]

    def count(self, *, title: str | None, author: str | None) -> int:
        """Count the matching books."""
        self.last_search = {"title": title, "author": author}
        return len(self._matches(title, author))


@pytest.fixture
def repository() -> InMemoryBookRepository:
    """Provide an empty fake repository."""
    return InMemoryBookRepository()


@pytest.fixture
def service(repository: InMemoryBookRepository) -> BookService:
    """Provide a service with the fake repository and a frozen clock."""
    return BookService(repository, clock=lambda: FIXED_NOW)


def test_fake_repository_satisfies_protocol(repository: InMemoryBookRepository) -> None:
    """The fake repository can be used wherever the protocol is expected."""
    typed: BookRepositoryProtocol = repository
    assert typed is repository


def test_create_book_stores_and_returns_book_with_id(
    service: BookService, repository: InMemoryBookRepository
) -> None:
    """Creating a book persists it and returns it with a generated id."""
    data = BookCreate(
        title="Dune", author="Frank Herbert", publication_date=date(1965, 8, 1), summary="Spice."
    )

    book = service.create_book(data)

    assert book.id == 1
    assert book.title == "Dune"
    assert book.author == "Frank Herbert"
    assert book.summary == "Spice."
    assert repository.books[1] is book


def test_create_book_without_created_at_uses_clock(service: BookService) -> None:
    """A missing `created_at` is filled with the current UTC time."""
    data = BookCreate(title="Dune", author="Frank Herbert", publication_date=date(1965, 8, 1))

    book = service.create_book(data)

    assert book.created_at == FIXED_NOW


def test_create_book_keeps_provided_created_at(service: BookService) -> None:
    """A provided `created_at` is stored as-is instead of the current time."""
    provided = datetime(2020, 3, 1, 9, 0, tzinfo=UTC)
    data = BookCreate(
        title="Dune", author="Frank Herbert", publication_date=date(1965, 8, 1), created_at=provided
    )

    book = service.create_book(data)

    assert book.created_at == provided


def test_create_book_logs_creation(service: BookService, caplog: pytest.LogCaptureFixture) -> None:
    """Creating a book writes an info log entry."""
    data = BookCreate(title="Dune", author="Frank Herbert", publication_date=date(1965, 8, 1))

    with caplog.at_level(logging.INFO, logger="app"):
        service.create_book(data)

    assert "Book created" in caplog.text


def test_get_book_returns_existing_book(
    service: BookService, repository: InMemoryBookRepository
) -> None:
    """An existing book is returned by id."""
    stored = repository.add(make_book())

    assert service.get_book(stored.id) is stored


def test_get_book_raises_not_found_for_missing_id(
    service: BookService, caplog: pytest.LogCaptureFixture
) -> None:
    """A missing id raises `BookNotFoundError` with a descriptive message and logs it."""
    with caplog.at_level(logging.WARNING, logger="app"), pytest.raises(BookNotFoundError) as exc:
        service.get_book(42)

    assert exc.value.book_id == 42
    assert str(exc.value) == "Book with id 42 not found"
    assert "Book not found" in caplog.text


def test_update_book_changes_only_sent_fields(
    service: BookService, repository: InMemoryBookRepository
) -> None:
    """Fields left out of the payload keep their stored value."""
    stored = repository.add(make_book(title="Old", author="Author", summary="Keep me"))

    updated = service.update_book(stored.id, BookUpdate(title="New"))

    assert updated is stored
    assert updated.title == "New"
    assert updated.author == "Author"
    assert updated.summary == "Keep me"


def test_update_book_logs_changed_fields(
    service: BookService, repository: InMemoryBookRepository, caplog: pytest.LogCaptureFixture
) -> None:
    """Editing a book writes an info log entry naming the changed fields."""
    stored = repository.add(make_book())

    with caplog.at_level(logging.INFO, logger="app"):
        service.update_book(stored.id, BookUpdate(author="Someone", summary=""))

    assert "Book updated" in caplog.text
    assert "['author', 'summary']" in caplog.text


def test_update_book_raises_not_found_for_missing_id(service: BookService) -> None:
    """Editing an unknown id raises `BookNotFoundError`."""
    with pytest.raises(BookNotFoundError):
        service.update_book(42, BookUpdate(title="New"))


def test_delete_book_removes_it(service: BookService, repository: InMemoryBookRepository) -> None:
    """A deleted book can no longer be found."""
    stored = repository.add(make_book())

    service.delete_book(stored.id)

    assert stored.id not in repository.books
    with pytest.raises(BookNotFoundError):
        service.get_book(stored.id)


def test_delete_book_raises_not_found_for_missing_id(service: BookService) -> None:
    """Deleting an unknown id raises `BookNotFoundError`."""
    with pytest.raises(BookNotFoundError):
        service.delete_book(42)


def test_search_books_filters_by_title_and_author(
    service: BookService, repository: InMemoryBookRepository
) -> None:
    """Search applies both filters when given."""
    repository.add(make_book(title="Harry Potter", author="J. K. Rowling"))
    repository.add(make_book(title="Harry Potter Fan Guide", author="Someone Else"))

    result = service.search_books(title="harry", author="rowling")

    assert [book.title for book in result] == ["Harry Potter"]


def test_search_books_strips_terms_and_ignores_blank_ones(
    service: BookService, repository: InMemoryBookRepository
) -> None:
    """Search terms are stripped and blank terms are treated as no filter."""
    service.search_books(title="  harry  ", author="   ", skip=5, limit=10)

    assert repository.last_search == {"title": "harry", "author": None, "skip": 5, "limit": 10}


def test_search_books_without_filters_returns_all(
    service: BookService, repository: InMemoryBookRepository
) -> None:
    """Without filters, every book is returned."""
    repository.add(make_book(title="A"))
    repository.add(make_book(title="B"))

    assert len(service.search_books()) == 2


def test_utc_now_returns_timezone_aware_utc_datetime() -> None:
    """The default clock returns an aware datetime in UTC."""
    now = utc_now()

    assert now.tzinfo is UTC
