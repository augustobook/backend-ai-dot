"""Tests for `BooksApiClient`, with HTTP simulated by respx."""

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx

from library_ui.api_client import (
    ApiNotFoundError,
    ApiResponseError,
    ApiUnavailableError,
    ApiValidationError,
    BooksApiClient,
)

BASE_URL = "http://api.test"


def make_book(book_id: int = 1, **overrides: Any) -> dict[str, Any]:
    """Build a book as the API would return it."""
    book: dict[str, Any] = {
        "id": book_id,
        "title": f"Book {book_id}",
        "author": "Author",
        "publication_date": "2000-01-01",
        "summary": "",
        "created_at": "2026-10-28T14:30:00Z",
    }
    book.update(overrides)
    return book


@pytest.fixture
def api() -> Iterator[respx.MockRouter]:
    """Intercept every HTTP request sent to the fake API."""
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as router:
        yield router


@pytest.fixture
def client() -> Iterator[BooksApiClient]:
    """Provide a client pointing at the fake API, with a small page size."""
    books_client = BooksApiClient(BASE_URL, timeout=1, max_page_size=2)
    yield books_client
    books_client.close()


def test_create_book_posts_payload_and_returns_book(
    api: respx.MockRouter, client: BooksApiClient
) -> None:
    """A 201 response returns the created book and the payload is sent as JSON."""
    route = api.post("/books").mock(return_value=httpx.Response(201, json=make_book(7)))
    payload = {"title": "Dune", "author": "Frank Herbert", "publication_date": "1965-08-01"}

    book = client.create_book(payload)

    assert book["id"] == 7
    assert route.called
    assert route.calls.last.request.read() == httpx.Request("POST", BASE_URL, json=payload).read()


def test_create_book_422_raises_validation_error_with_field_errors(
    api: respx.MockRouter, client: BooksApiClient
) -> None:
    """A 422 becomes `ApiValidationError` with readable messages per field."""
    detail = [
        {"loc": ["body", "title"], "msg": "String should have at least 1 character",
         "type": "string_too_short"},
        {"loc": ["body", "publication_date"],
         "msg": "Value error, publication_date cannot be in the future", "type": "value_error"},
    ]  # fmt: skip
    api.post("/books").mock(return_value=httpx.Response(422, json={"detail": detail}))

    with pytest.raises(ApiValidationError) as exc_info:
        client.create_book({"title": ""})

    assert exc_info.value.errors == detail
    assert exc_info.value.field_errors == {
        "title": "Este campo não pode ficar vazio.",
        "publication_date": "Data de publicação não pode estar no futuro.",
    }


def test_search_books_sends_filters_and_pagination(
    api: respx.MockRouter, client: BooksApiClient
) -> None:
    """Filters are stripped and sent with `skip` and `limit`."""
    route = api.get("/books").mock(return_value=httpx.Response(200, json=[make_book()]))

    books = client.search_books(title=" harry ", author="rowling", skip=10, limit=11)

    assert len(books) == 1
    params = route.calls.last.request.url.params
    assert dict(params) == {"title": "harry", "author": "rowling", "skip": "10", "limit": "11"}


def test_search_books_omits_blank_filters(api: respx.MockRouter, client: BooksApiClient) -> None:
    """Empty or whitespace-only filters are not sent to the API."""
    route = api.get("/books").mock(return_value=httpx.Response(200, json=[]))

    assert client.search_books(title="  ", author=None) == []

    params = route.calls.last.request.url.params
    assert "title" not in params
    assert "author" not in params


def test_get_book_returns_book(api: respx.MockRouter, client: BooksApiClient) -> None:
    """`get_book` requests `/books/{id}` and returns the book."""
    api.get("/books/3").mock(return_value=httpx.Response(200, json=make_book(3)))

    assert client.get_book(3)["id"] == 3


def test_get_book_404_raises_not_found(api: respx.MockRouter, client: BooksApiClient) -> None:
    """A 404 becomes `ApiNotFoundError` carrying the API message."""
    api.get("/books/42").mock(
        return_value=httpx.Response(404, json={"detail": "Book with id 42 not found"})
    )

    with pytest.raises(ApiNotFoundError, match="Book with id 42 not found"):
        client.get_book(42)


def test_update_book_patches_payload_and_returns_book(
    api: respx.MockRouter, client: BooksApiClient
) -> None:
    """`update_book` sends a PATCH with only the given fields."""
    route = api.patch("/books/7").mock(
        return_value=httpx.Response(200, json=make_book(7, title="New"))
    )

    book = client.update_book(7, {"title": "New"})

    assert book["title"] == "New"
    assert route.calls.last.request.read() == b'{"title":"New"}'


def test_update_book_404_raises_not_found(api: respx.MockRouter, client: BooksApiClient) -> None:
    """Editing a missing book raises `ApiNotFoundError`."""
    api.patch("/books/9").mock(
        return_value=httpx.Response(404, json={"detail": "Book with id 9 not found"})
    )

    with pytest.raises(ApiNotFoundError):
        client.update_book(9, {"title": "New"})


def test_delete_book_sends_delete(api: respx.MockRouter, client: BooksApiClient) -> None:
    """`delete_book` sends a DELETE and accepts the empty 204 response."""
    route = api.delete("/books/7").mock(return_value=httpx.Response(204))

    client.delete_book(7)

    assert route.called


def test_delete_book_404_raises_not_found(api: respx.MockRouter, client: BooksApiClient) -> None:
    """Deleting a missing book raises `ApiNotFoundError`."""
    api.delete("/books/9").mock(
        return_value=httpx.Response(404, json={"detail": "Book with id 9 not found"})
    )

    with pytest.raises(ApiNotFoundError):
        client.delete_book(9)


@pytest.mark.parametrize(
    "error", [httpx.ConnectError("refused"), httpx.ReadTimeout("slow")], ids=["refused", "timeout"]
)
def test_unreachable_api_raises_unavailable(
    api: respx.MockRouter, client: BooksApiClient, error: Exception
) -> None:
    """Connection failures and timeouts become `ApiUnavailableError`."""
    api.get("/books").mock(side_effect=error)

    with pytest.raises(ApiUnavailableError) as exc_info:
        client.search_books()

    assert exc_info.value.base_url == BASE_URL
    assert str(exc_info.value) == f"Could not connect to the API at {BASE_URL}."


def test_unexpected_status_raises_response_error(
    api: respx.MockRouter, client: BooksApiClient
) -> None:
    """Other error statuses become `ApiResponseError` with the status code."""
    api.get("/books").mock(return_value=httpx.Response(500, text="Internal Server Error"))

    with pytest.raises(ApiResponseError) as exc_info:
        client.search_books()

    assert exc_info.value.status_code == 500


def test_fetch_all_books_pages_until_last_page(
    api: respx.MockRouter, client: BooksApiClient
) -> None:
    """`fetch_all_books` keeps requesting pages until a short page arrives."""
    pages = [
        [make_book(1), make_book(2)],
        [make_book(3), make_book(4)],
        [make_book(5)],
    ]
    route = api.get("/books").mock(side_effect=[httpx.Response(200, json=page) for page in pages])

    books = client.fetch_all_books()

    assert [book["id"] for book in books] == [1, 2, 3, 4, 5]
    skips = [call.request.url.params["skip"] for call in route.calls]
    limits = {call.request.url.params["limit"] for call in route.calls}
    assert skips == ["0", "2", "4"]
    assert limits == {"2"}


def test_fetch_all_books_with_exact_multiple_makes_extra_request(
    api: respx.MockRouter, client: BooksApiClient
) -> None:
    """When the total is a multiple of the page size, an empty page ends the loop."""
    route = api.get("/books").mock(
        side_effect=[
            httpx.Response(200, json=[make_book(1), make_book(2)]),
            httpx.Response(200, json=[]),
        ]
    )

    assert len(client.fetch_all_books()) == 2
    assert route.call_count == 2


def test_fetch_all_books_on_empty_library(api: respx.MockRouter, client: BooksApiClient) -> None:
    """An empty library returns an empty list after a single request."""
    route = api.get("/books").mock(return_value=httpx.Response(200, json=[]))

    assert client.fetch_all_books() == []
    assert route.call_count == 1


def test_api_key_is_sent_when_configured(api: respx.MockRouter) -> None:
    """A configured API key goes in the `X-API-Key` header of every request."""
    route = api.get("/books").mock(return_value=httpx.Response(200, json=[]))
    client = BooksApiClient(BASE_URL, api_key="s3cret")

    client.search_books()

    assert route.calls.last.request.headers["X-API-Key"] == "s3cret"
    client.close()


def test_api_key_header_is_omitted_by_default(
    api: respx.MockRouter, client: BooksApiClient
) -> None:
    """Without an API key, no `X-API-Key` header is sent."""
    route = api.get("/books").mock(return_value=httpx.Response(200, json=[]))

    client.search_books()

    assert "X-API-Key" not in route.calls.last.request.headers


@pytest.mark.parametrize("status_code", [401, 413, 429])
def test_security_statuses_raise_response_error(
    api: respx.MockRouter, client: BooksApiClient, status_code: int
) -> None:
    """401, 413 and 429 from the API's security layer become `ApiResponseError`."""
    api.get("/books").mock(return_value=httpx.Response(status_code, json={"detail": "x"}))

    with pytest.raises(ApiResponseError) as exc_info:
        client.search_books()

    assert exc_info.value.status_code == status_code


def test_base_url_trailing_slash_is_ignored(api: respx.MockRouter) -> None:
    """A trailing slash in the base URL does not break request paths."""
    api.get("/books/1").mock(return_value=httpx.Response(200, json=make_book(1)))

    client = BooksApiClient(f"{BASE_URL}/")

    assert client.get_book(1)["id"] == 1
    client.close()
