"""Endpoints for registering, searching, editing and deleting books.

Routes only translate HTTP into service calls; business rules live in
`BookService` and domain errors are turned into HTTP responses by the
exception handlers registered in `app.main`.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, status

from app.api.dependencies import BookServiceDep
from app.core.config import get_settings
from app.schemas.book import BookCreate, BookRead, BookUpdate
from app.schemas.common import ErrorResponse

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

router = APIRouter(prefix="/books", tags=["books"], responses=SECURITY_RESPONSES)

# Query constraints are evaluated when the route is declared, so pagination
# limits come from the settings available at import time.
_settings = get_settings()

NOT_FOUND_RESPONSE: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponse,
        "description": "No book exists with the given id.",
        "content": {"application/json": {"example": {"detail": "Book with id 42 not found"}}},
    }
}


@router.post(
    "",
    response_model=BookRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a book",
    description=(
        "Register a new book in the library. `title` and `author` are required and cannot "
        "be blank. `publication_date` and `created_at` cannot be in the future. When "
        "`created_at` is omitted, the current UTC date and time is used."
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
        "List books, optionally filtered by `title` and/or `author`. Filters match partially "
        "and ignore case (e.g. `?title=harry` finds *Harry Potter*). When both are given, a "
        "book must match both. Without filters, all books are returned. Results are ordered "
        "by id and paginated with `skip` and `limit`."
    ),
    response_description="The books matching the filters (possibly an empty list).",
)
def search_books(
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
            le=_settings.max_page_size,
            description=f"Maximum number of books to return (at most {_settings.max_page_size}).",
            examples=[_settings.default_page_size],
        ),
    ] = _settings.default_page_size,
) -> list[BookRead]:
    """Search books by title and/or author.

    Args:
        service: The book service.
        title: Text contained in the book title.
        author: Text contained in the author name.
        skip: Number of books to skip.
        limit: Maximum number of books to return.

    Returns:
        The matching books.
    """
    books = service.search_books(title=title, author=author, skip=skip, limit=limit)
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
def get_book(
    book_id: Annotated[int, Path(ge=1, description="Id of the book.", examples=[1])],
    service: BookServiceDep,
) -> BookRead:
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
        "Change one or more fields of an existing book. Only the fields sent are changed; "
        "omitted fields keep their current value. The same rules as registration apply: "
        "`title` and `author` cannot be blank, and `publication_date` and `created_at` "
        "cannot be in the future. `null` values and unknown fields are rejected."
    ),
    response_description="The book with its updated fields.",
    responses=NOT_FOUND_RESPONSE,
)
def update_book(
    book_id: Annotated[int, Path(ge=1, description="Id of the book.", examples=[1])],
    payload: BookUpdate,
    service: BookServiceDep,
) -> BookRead:
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
def delete_book(
    book_id: Annotated[int, Path(ge=1, description="Id of the book.", examples=[1])],
    service: BookServiceDep,
) -> None:
    """Delete a book.

    Args:
        book_id: Id of the book.
        service: The book service.

    Raises:
        BookNotFoundError: If the book does not exist (converted to HTTP 404).
    """
    service.delete_book(book_id)
