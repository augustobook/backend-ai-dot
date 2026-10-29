"""Endpoints for registering, searching, editing and deleting books.

Routes only translate HTTP into service calls; business rules live in
`BookService` and domain errors are turned into HTTP responses by the
exception handlers registered in `app.main`.

The router is built by `build_router(settings)` instead of at import time: the
pagination limits are part of the route declaration (they become the `maximum`
shown in the docs), so each app gets a router that follows its own settings.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Response, status

from app.api.dependencies import BookServiceDep
from app.core.config import Settings
from app.schemas.book import BookCreate, BookRead, BookUpdate
from app.schemas.common import ErrorResponse

# Total of books matching a search, ignoring pagination. A header (not an
# envelope around the list) keeps the response body a plain list of books.
TOTAL_COUNT_HEADER = "X-Total-Count"

# Errors that any /books endpoint may return because of the security layer.
SECURITY_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_401_UNAUTHORIZED: {
        "model": ErrorResponse,
        "description": "Missing or invalid `X-API-Key` (only when the server sets `API_KEY`).",
    },
    status.HTTP_413_CONTENT_TOO_LARGE: {
        "model": ErrorResponse,
        "description": "Request body larger than `MAX_REQUEST_BODY_BYTES`.",
    },
    status.HTTP_429_TOO_MANY_REQUESTS: {
        "model": ErrorResponse,
        "description": "Rate limit exceeded; retry after the `Retry-After` seconds.",
    },
}

NOT_FOUND_RESPONSE: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponse,
        "description": "No book exists with the given id.",
        "content": {"application/json": {"example": {"detail": "Book with id 42 not found"}}},
    }
}

BookId = Annotated[int, Path(ge=1, description="Id of the book.", examples=[1])]


def build_router(settings: Settings) -> APIRouter:
    """Create the `/books` router.

    Args:
        settings: Settings providing the default and maximum page sizes.

    Returns:
        The router with every book endpoint.
    """
    router = APIRouter(prefix="/books", tags=["books"], responses=SECURITY_RESPONSES)
    max_page = settings.max_page_size

    @router.post(
        "",
        response_model=BookRead,
        status_code=status.HTTP_201_CREATED,
        summary="Register a book",
        description=(
            "Register a new book in the library. `title` and `author` are required and "
            "cannot be blank. `publication_date` and `created_at` cannot be in the future. "
            "When `created_at` is omitted, the current UTC date and time is used."
        ),
        response_description="The newly registered book.",
    )
    def create_book(payload: BookCreate, service: BookServiceDep) -> BookRead:
        """Register a new book.

        Args:
            payload: The validated book data.
            service: The book service.

        Returns:
            The stored book.
        """
        return BookRead.model_validate(service.create_book(payload))

    @router.get(
        "",
        response_model=list[BookRead],
        status_code=status.HTTP_200_OK,
        summary="Search books",
        description=(
            "List books, optionally filtered by `title` and/or `author`. Filters match "
            "partially and ignore case (e.g. `?title=harry` finds *Harry Potter*). When both "
            "are given, a book must match both. Without filters, all books are returned. "
            "Results are ordered by id and paginated with `skip` and `limit`; the "
            f"`{TOTAL_COUNT_HEADER}` header carries the total of matching books."
        ),
        response_description="The books matching the filters (possibly an empty list).",
        responses={
            status.HTTP_200_OK: {
                "headers": {
                    TOTAL_COUNT_HEADER: {
                        "description": "Total of matching books, ignoring `skip` and `limit`.",
                        "schema": {"type": "integer"},
                    }
                }
            }
        },
    )
    def search_books(
        response: Response,
        service: BookServiceDep,
        title: Annotated[
            str | None,
            Query(
                max_length=255,
                description="Text contained in the book title (case-insensitive).",
                examples=["harry"],
            ),
        ] = None,
        author: Annotated[
            str | None,
            Query(
                max_length=255,
                description="Text contained in the author name (case-insensitive).",
                examples=["rowling"],
            ),
        ] = None,
        skip: Annotated[int, Query(ge=0, description="Number of books to skip.", examples=[0])] = 0,
        limit: Annotated[
            int,
            Query(
                ge=1,
                le=max_page,
                description=f"Maximum number of books to return (at most {max_page}).",
                examples=[settings.default_page_size],
            ),
        ] = settings.default_page_size,
    ) -> list[BookRead]:
        """Search books by title and/or author.

        Args:
            response: The outgoing response, used to set the total header.
            service: The book service.
            title: Text contained in the book title.
            author: Text contained in the author name.
            skip: Number of books to skip.
            limit: Maximum number of books to return.

        Returns:
            The matching books.
        """
        books = service.search_books(title=title, author=author, skip=skip, limit=limit)
        response.headers[TOTAL_COUNT_HEADER] = str(service.count_books(title=title, author=author))
        return [BookRead.model_validate(book) for book in books]

    @router.get(
        "/{book_id}",
        response_model=BookRead,
        status_code=status.HTTP_200_OK,
        summary="Get a book by id",
        description="Return a single book by its id, or 404 if it does not exist.",
        response_description="The requested book.",
        responses=NOT_FOUND_RESPONSE,
    )
    def get_book(book_id: BookId, service: BookServiceDep) -> BookRead:
        """Return a book by its id.

        Args:
            book_id: Id of the book.
            service: The book service.

        Returns:
            The requested book.

        Raises:
            BookNotFoundError: If the book does not exist (converted to HTTP 404).
        """
        return BookRead.model_validate(service.get_book(book_id))

    @router.patch(
        "/{book_id}",
        response_model=BookRead,
        status_code=status.HTTP_200_OK,
        summary="Edit a book",
        description=(
            "Change one or more fields of an existing book. Only the fields sent are "
            "changed; omitted fields keep their current value. The same rules as "
            "registration apply: `title` and `author` cannot be blank, and "
            "`publication_date` and `created_at` cannot be in the future. `null` values "
            "and unknown fields are rejected."
        ),
        response_description="The book with its updated fields.",
        responses=NOT_FOUND_RESPONSE,
    )
    def update_book(book_id: BookId, payload: BookUpdate, service: BookServiceDep) -> BookRead:
        """Edit an existing book.

        Args:
            book_id: Id of the book.
            payload: The validated fields to change.
            service: The book service.

        Returns:
            The updated book.

        Raises:
            BookNotFoundError: If the book does not exist (converted to HTTP 404).
        """
        return BookRead.model_validate(service.update_book(book_id, payload))

    @router.delete(
        "/{book_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Delete a book",
        description="Permanently remove a book from the library, or 404 if it does not exist.",
        response_description="The book was deleted (no body).",
        responses=NOT_FOUND_RESPONSE,
    )
    def delete_book(book_id: BookId, service: BookServiceDep) -> None:
        """Delete a book.

        Args:
            book_id: Id of the book.
            service: The book service.

        Raises:
            BookNotFoundError: If the book does not exist (converted to HTTP 404).
        """
        service.delete_book(book_id)

    return router
