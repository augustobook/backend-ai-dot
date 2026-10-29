"""HTTP client for the Library API.

`BooksApiClient` is the only place in the frontend that talks to the backend.
HTTP failures are translated into the exceptions below so the UI can react to
each case (show field errors, "not found", "API offline") without knowing
anything about status codes.
"""

from collections.abc import Mapping
from typing import Any, TypedDict, cast

import httpx

from library_ui.services import parse_validation_errors

API_KEY_HEADER = "X-API-Key"


class Book(TypedDict):
    """A book as returned by the API."""

    id: int
    title: str
    author: str
    publication_date: str
    summary: str
    created_at: str


class ApiError(Exception):
    """Base class for every error raised by `BooksApiClient`."""


class ApiUnavailableError(ApiError):
    """Raised when the API cannot be reached (connection refused, DNS, timeout).

    Attributes:
        base_url: The API URL that could not be reached.
    """

    def __init__(self, base_url: str) -> None:
        """Initialize the error.

        Args:
            base_url: The API URL that could not be reached.
        """
        self.base_url = base_url
        super().__init__(f"Could not connect to the API at {base_url}.")


class ApiNotFoundError(ApiError):
    """Raised when the API answers 404 Not Found.

    Attributes:
        detail: The `detail` message sent by the API.
    """

    def __init__(self, detail: str) -> None:
        """Initialize the error.

        Args:
            detail: The `detail` message sent by the API.
        """
        self.detail = detail
        super().__init__(detail)


class ApiValidationError(ApiError):
    """Raised when the API answers 422 Unprocessable Entity.

    Attributes:
        errors: The raw `detail` list sent by FastAPI.
        field_errors: Readable messages keyed by field name.
    """

    def __init__(self, errors: Any) -> None:
        """Initialize the error.

        Args:
            errors: The raw `detail` value of the 422 response.
        """
        self.errors = errors
        self.field_errors = parse_validation_errors(errors)
        super().__init__("; ".join(f"{k}: {v}" for k, v in self.field_errors.items()))


class ApiResponseError(ApiError):
    """Raised for any other unexpected error response (e.g. HTTP 500).

    Attributes:
        status_code: The HTTP status code received.
    """

    def __init__(self, status_code: int) -> None:
        """Initialize the error.

        Args:
            status_code: The HTTP status code received.
        """
        self.status_code = status_code
        super().__init__(f"The API returned an unexpected response (HTTP {status_code}).")


def _detail(response: httpx.Response) -> Any:
    """Extract the FastAPI `detail` field from an error response.

    Args:
        response: The error response.

    Returns:
        The `detail` value, or the raw text when the body is not JSON.
    """
    try:
        body = response.json()
    except ValueError:
        return response.text
    return body.get("detail", body) if isinstance(body, dict) else body


class BooksApiClient:
    """Synchronous client for the `/books` endpoints of the Library API."""

    def __init__(
        self,
        base_url: str,
        timeout: float = 5.0,
        max_page_size: int = 100,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """Initialize the client.

        Args:
            base_url: Base URL of the API, e.g. `http://localhost:8000`.
            timeout: Timeout in seconds for each request.
            max_page_size: Highest `limit` accepted by the API; used by
                `fetch_all_books` to page through every record.
            api_key: Sent in the `X-API-Key` header when the API requires a key.
            transport: Optional custom httpx transport (useful in tests).
        """
        self.base_url = base_url.rstrip("/")
        self.max_page_size = max_page_size
        headers = {API_KEY_HEADER: api_key} if api_key else {}
        # One pooled client is reused across requests (and Dash worker threads).
        self._client = httpx.Client(
            base_url=self.base_url, timeout=timeout, headers=headers, transport=transport
        )

    def close(self) -> None:
        """Close the underlying connection pool."""
        self._client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Send a request and translate failures into `ApiError` subclasses.

        Args:
            method: HTTP method.
            path: Path relative to the base URL.
            **kwargs: Extra arguments for `httpx.Client.request` (`json`, `params`).

        Returns:
            The successful response.

        Raises:
            ApiUnavailableError: If the API cannot be reached or times out.
            ApiNotFoundError: On HTTP 404.
            ApiValidationError: On HTTP 422.
            ApiResponseError: On any other 4xx/5xx response.
        """
        # Network-level failures (refused, DNS, timeout) all mean "API offline".
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.TransportError as exc:
            raise ApiUnavailableError(self.base_url) from exc

        # Map the status codes the API documents to dedicated exceptions.
        if response.status_code == httpx.codes.NOT_FOUND:
            raise ApiNotFoundError(str(_detail(response)))
        if response.status_code == httpx.codes.UNPROCESSABLE_ENTITY:
            raise ApiValidationError(_detail(response))
        if response.is_error:
            raise ApiResponseError(response.status_code)
        return response

    def create_book(self, payload: Mapping[str, Any]) -> Book:
        """Register a book (`POST /books`).

        Args:
            payload: Book fields, without `id`. `created_at` is optional.

        Returns:
            The created book.

        Raises:
            ApiValidationError: If the API rejects the payload.
            ApiUnavailableError: If the API cannot be reached.
            ApiResponseError: On unexpected errors.
        """
        response = self._request("POST", "/books", json=dict(payload))
        return cast(Book, response.json())

    def search_books(
        self,
        *,
        title: str | None = None,
        author: str | None = None,
        skip: int = 0,
        limit: int = 20,
    ) -> list[Book]:
        """Search books by partial title and/or author (`GET /books`).

        Args:
            title: Text contained in the title. Blank values are not sent.
            author: Text contained in the author. Blank values are not sent.
            skip: Number of books to skip.
            limit: Maximum number of books to return.

        Returns:
            The matching books.

        Raises:
            ApiValidationError: If the query parameters are rejected.
            ApiUnavailableError: If the API cannot be reached.
            ApiResponseError: On unexpected errors.
        """
        # Only send filters that have content; an empty `title=` is pointless.
        params: dict[str, str | int] = {"skip": skip, "limit": limit}
        if title and title.strip():
            params["title"] = title.strip()
        if author and author.strip():
            params["author"] = author.strip()
        response = self._request("GET", "/books", params=params)
        return cast(list[Book], response.json())

    def get_book(self, book_id: int) -> Book:
        """Return a single book (`GET /books/{book_id}`).

        Args:
            book_id: Id of the book.

        Returns:
            The book.

        Raises:
            ApiNotFoundError: If the book does not exist.
            ApiUnavailableError: If the API cannot be reached.
            ApiResponseError: On unexpected errors.
        """
        response = self._request("GET", f"/books/{book_id}")
        return cast(Book, response.json())

    def fetch_all_books(self, *, title: str | None = None, author: str | None = None) -> list[Book]:
        """Return every book, following the API pagination.

        The API caps `limit`, so a single request cannot return the whole
        catalog. Pages of `max_page_size` are requested until a page comes back
        smaller than that, which means the last page was reached.

        Args:
            title: Optional title filter.
            author: Optional author filter.

        Returns:
            All matching books.

        Raises:
            ApiUnavailableError: If the API cannot be reached.
            ApiResponseError: On unexpected errors.
        """
        books: list[Book] = []
        skip = 0
        while True:
            page = self.search_books(
                title=title, author=author, skip=skip, limit=self.max_page_size
            )
            books.extend(page)
            if len(page) < self.max_page_size:
                return books
            skip += self.max_page_size
