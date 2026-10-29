"""Use cases for registering, searching, editing and deleting books.

The service holds the business rules and knows nothing about HTTP or SQL: it
receives already validated schemas, talks to a `BookRepositoryProtocol` and
signals "not found" with a domain exception that the API turns into a 404.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from app.core.exceptions import BookNotFoundError
from app.models.book import Book
from app.repositories.book_repository import BookRepositoryProtocol
from app.schemas.book import BookCreate, BookUpdate

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    """Return the current date and time in UTC.

    Timestamps are always UTC so they do not depend on the server's timezone;
    clients convert them to local time for display.

    Returns:
        A timezone-aware UTC datetime.
    """
    return datetime.now(UTC)


def _normalize_term(term: str | None) -> str | None:
    """Strip a search term, treating blank terms as no filter.

    Forms often send an empty field as `?title=` or `?title=%20`. Without this,
    `"  "` would become the pattern `%  %` and only match titles containing two
    spaces, instead of meaning "no title filter".

    Args:
        term: The raw search term.

    Returns:
        The stripped term, or `None` if it is missing or blank.
    """
    if term is None:
        return None
    return term.strip() or None


class BookService:
    """Business rules for the book catalog."""

    def __init__(
        self, repository: BookRepositoryProtocol, clock: Callable[[], datetime] = utc_now
    ) -> None:
        """Initialize the service.

        Args:
            repository: Persistence used to store and query books.
            clock: Function returning the current UTC datetime. Injectable so
                tests can control time.
        """
        self._repository = repository
        self._clock = clock

    def create_book(self, data: BookCreate) -> Book:
        """Register a new book.

        When `created_at` is not provided, it is set to the current UTC time.

        Args:
            data: The validated book payload.

        Returns:
            The stored book, with its generated id.
        """
        book = Book(
            title=data.title,
            author=data.author,
            publication_date=data.publication_date,
            summary=data.summary,
            # Decided here (not by the column default) so tests can fix the time
            # through the injected clock.
            created_at=data.created_at or self._clock(),
        )
        saved = self._repository.add(book)
        logger.info("Book created: id=%s title=%r author=%r", saved.id, saved.title, saved.author)
        return saved

    def get_book(self, book_id: int) -> Book:
        """Return a book by its id.

        Args:
            book_id: The id of the book.

        Returns:
            The requested book.

        Raises:
            BookNotFoundError: If no book has the given id.
        """
        book = self._repository.get_by_id(book_id)
        if book is None:
            logger.warning("Book not found: id=%s", book_id)
            raise BookNotFoundError(book_id)
        return book

    def update_book(self, book_id: int, data: BookUpdate) -> Book:
        """Change the fields of an existing book.

        Only the fields present in the payload are changed.

        Args:
            book_id: The id of the book.
            data: The validated partial payload.

        Returns:
            The updated book.

        Raises:
            BookNotFoundError: If no book has the given id.
        """
        book = self.get_book(book_id)
        # `exclude_unset` keeps only the fields the client actually sent. Every
        # field of `BookUpdate` defaults to None, so a plain dump would overwrite
        # the omitted ones with None. Copying fields by name is safe because the
        # schema forbids unknown fields: `id` can never get here.
        changes = data.model_dump(exclude_unset=True)
        for field, value in changes.items():
            setattr(book, field, value)
        updated = self._repository.update(book)
        logger.info("Book updated: id=%s fields=%s", updated.id, sorted(changes))
        return updated

    def delete_book(self, book_id: int) -> None:
        """Remove a book from the library.

        Args:
            book_id: The id of the book.

        Raises:
            BookNotFoundError: If no book has the given id.
        """
        # Load first so a missing id raises 404 instead of silently "deleting"
        # nothing, and so the title is available for the log.
        book = self.get_book(book_id)
        self._repository.delete(book)
        logger.info("Book deleted: id=%s title=%r", book_id, book.title)

    def search_books(
        self,
        *,
        title: str | None = None,
        author: str | None = None,
        skip: int = 0,
        limit: int = 20,
    ) -> list[Book]:
        """Search books by partial, case-insensitive title and/or author.

        Blank terms are ignored, so searching without filters lists all books.

        Args:
            title: Text that must be contained in the title.
            author: Text that must be contained in the author.
            skip: Number of matching books to skip.
            limit: Maximum number of books to return.

        Returns:
            The matching books ordered by id.
        """
        return self._repository.search(
            title=_normalize_term(title),
            author=_normalize_term(author),
            skip=skip,
            limit=limit,
        )
