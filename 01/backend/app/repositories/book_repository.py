"""Repository for persisting and querying books.

`BookRepositoryProtocol` is the abstraction the service layer depends on;
`BookRepository` is its SQLAlchemy implementation.

`search` returns one page and `count` the total for the same filters; the API
sends the total in the `X-Total-Count` header.

Why a protocol: the service only needs "add, get, update, delete, search", not
SQLAlchemy. Depending on the protocol keeps the business rules free of database
details and lets the unit tests run the service against an in-memory fake.

Why each write commits: every request gets its own session (`get_db`) and each
use case performs a single write, so one operation = one transaction. Committing
here keeps transaction handling out of the service.
"""

from typing import Any, Protocol

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models.book import Book

LIKE_ESCAPE_CHAR = "\\"


def _contains_pattern(term: str) -> str:
    """Build a LIKE pattern that matches `term` anywhere in the column.

    Wildcards typed by the user (`%` and `_`) are escaped so they are matched
    literally instead of acting as wildcards.

    Args:
        term: The raw search term.

    Returns:
        The escaped pattern wrapped in `%` wildcards.
    """
    # Without escaping, searching "100%" would match "100 anything" and "_" would
    # match any single character. The escape character itself is escaped first;
    # doing it last would double the backslashes added for `%` and `_`.
    escaped = (
        term.replace(LIKE_ESCAPE_CHAR, LIKE_ESCAPE_CHAR * 2)
        .replace("%", f"{LIKE_ESCAPE_CHAR}%")
        .replace("_", f"{LIKE_ESCAPE_CHAR}_")
    )
    return f"%{escaped}%"


class BookRepositoryProtocol(Protocol):
    """Interface for book persistence used by the service layer."""

    def add(self, book: Book) -> Book:
        """Persist a new book.

        Args:
            book: The book to store.

        Returns:
            The stored book, with its generated id.
        """
        ...

    def get_by_id(self, book_id: int) -> Book | None:
        """Find a book by its id.

        Args:
            book_id: The id of the book.

        Returns:
            The book, or `None` if it does not exist.
        """
        ...

    def update(self, book: Book) -> Book:
        """Persist the changes made to a stored book.

        Args:
            book: A book previously returned by this repository, already modified.

        Returns:
            The updated book.
        """
        ...

    def delete(self, book: Book) -> None:
        """Remove a stored book.

        Args:
            book: A book previously returned by this repository.
        """
        ...

    def search(self, *, title: str | None, author: str | None, skip: int, limit: int) -> list[Book]:
        """Search books by partial, case-insensitive title and/or author.

        Args:
            title: Text that must be contained in the title, or `None` to ignore it.
            author: Text that must be contained in the author, or `None` to ignore it.
            skip: Number of matching books to skip.
            limit: Maximum number of books to return.

        Returns:
            The matching books ordered by id.
        """
        ...

    def count(self, *, title: str | None, author: str | None) -> int:
        """Count the books matching the same filters as `search`.

        Args:
            title: Text that must be contained in the title, or `None` to ignore it.
            author: Text that must be contained in the author, or `None` to ignore it.

        Returns:
            The number of matching books, ignoring pagination.
        """
        ...


def _apply_filters[S: Select[Any]](statement: S, *, title: str | None, author: str | None) -> S:
    """Add the optional title and author conditions to a query.

    Shared by `search` and `count`, so the total always matches the listing.

    Args:
        statement: The query to filter.
        title: Text that must be contained in the title, or `None` to ignore it.
        author: Text that must be contained in the author, or `None` to ignore it.

    Returns:
        The filtered query.
    """
    # Filters are optional, so the query is built step by step; each `where`
    # adds an AND condition. `ilike` makes the match case-insensitive.
    if title:
        statement = statement.where(
            Book.title.ilike(_contains_pattern(title), escape=LIKE_ESCAPE_CHAR)
        )
    if author:
        statement = statement.where(
            Book.author.ilike(_contains_pattern(author), escape=LIKE_ESCAPE_CHAR)
        )
    return statement


class BookRepository:
    """SQLAlchemy implementation of `BookRepositoryProtocol`."""

    def __init__(self, session: Session) -> None:
        """Initialize the repository.

        Args:
            session: The SQLAlchemy session used for all queries.
        """
        self._session = session

    def add(self, book: Book) -> Book:
        """Persist a new book and commit the transaction.

        Args:
            book: The book to store.

        Returns:
            The stored book, refreshed with its generated id.
        """
        self._session.add(book)
        self._session.commit()
        # Reload the row so the returned object carries what the database
        # generated (the id) exactly as it was stored.
        self._session.refresh(book)
        return book

    def get_by_id(self, book_id: int) -> Book | None:
        """Find a book by its id.

        Args:
            book_id: The id of the book.

        Returns:
            The book, or `None` if it does not exist.
        """
        return self._session.get(Book, book_id)

    def update(self, book: Book) -> Book:
        """Commit the changes made to a stored book.

        Args:
            book: A book loaded by this repository, already modified.

        Returns:
            The book, refreshed from the database.
        """
        # No `add` needed: the book was loaded by this session, which tracks its
        # attributes and emits an UPDATE with only the changed columns on commit.
        self._session.commit()
        self._session.refresh(book)
        return book

    def delete(self, book: Book) -> None:
        """Delete a stored book and commit the transaction.

        Args:
            book: A book loaded by this repository.
        """
        self._session.delete(book)
        self._session.commit()

    def search(self, *, title: str | None, author: str | None, skip: int, limit: int) -> list[Book]:
        """Search books by partial, case-insensitive title and/or author.

        Args:
            title: Text that must be contained in the title, or `None` to ignore it.
            author: Text that must be contained in the author, or `None` to ignore it.
            skip: Number of matching books to skip.
            limit: Maximum number of books to return.

        Returns:
            The matching books ordered by id.
        """
        statement = _apply_filters(select(Book), title=title, author=author)
        # Offset pagination needs a stable order: without ORDER BY the database may
        # return rows in any order, and pages could repeat or skip books.
        statement = statement.order_by(Book.id).offset(skip).limit(limit)
        return list(self._session.scalars(statement))

    def count(self, *, title: str | None, author: str | None) -> int:
        """Count the books matching the filters, ignoring pagination.

        Args:
            title: Text that must be contained in the title, or `None` to ignore it.
            author: Text that must be contained in the author, or `None` to ignore it.

        Returns:
            The number of matching books.
        """
        statement = _apply_filters(
            select(func.count()).select_from(Book), title=title, author=author
        )
        return self._session.scalar(statement) or 0
