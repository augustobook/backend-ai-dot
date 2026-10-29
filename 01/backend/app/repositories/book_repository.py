"""Repository for persisting and querying books.

`BookRepositoryProtocol` is the abstraction the service layer depends on;
`BookRepository` is its SQLAlchemy implementation.
"""

from typing import Protocol

from sqlalchemy import select
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
        statement = select(Book)
        if title:
            statement = statement.where(
                Book.title.ilike(_contains_pattern(title), escape=LIKE_ESCAPE_CHAR)
            )
        if author:
            statement = statement.where(
                Book.author.ilike(_contains_pattern(author), escape=LIKE_ESCAPE_CHAR)
            )
        statement = statement.order_by(Book.id).offset(skip).limit(limit)
        return list(self._session.scalars(statement))
