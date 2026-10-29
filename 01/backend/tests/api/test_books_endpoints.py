"""End-to-end tests of the HTTP endpoints using FastAPI's TestClient."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from tests.conftest import AppFactory
from tests.factories import make_book_payload

CreateBook = Callable[..., dict[str, Any]]


def _parse(value: str) -> datetime:
    """Parse an ISO 8601 datetime returned by the API."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# --- Health -----------------------------------------------------------------


def test_health_check_returns_ok(client: TestClient) -> None:
    """`GET /health` reports that the application is up."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# --- Create ---------------------------------------------------------------


def test_create_book_returns_201_and_body(client: TestClient) -> None:
    """A valid payload creates the book and returns it with an id."""
    payload = make_book_payload()

    response = client.post("/books", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert isinstance(body["id"], int)
    assert body["title"] == payload["title"]
    assert body["author"] == payload["author"]
    assert body["publication_date"] == payload["publication_date"]
    assert body["summary"] == payload["summary"]
    assert "created_at" in body


def test_create_book_strips_surrounding_whitespace(client: TestClient) -> None:
    """Leading and trailing spaces in title and author are removed."""
    response = client.post("/books", json=make_book_payload(title="  Dune  ", author=" Herbert "))

    assert response.status_code == 201
    assert response.json()["title"] == "Dune"
    assert response.json()["author"] == "Herbert"


@pytest.mark.parametrize("missing_field", ["title", "author", "publication_date"])
def test_create_book_missing_required_field_returns_422(
    client: TestClient, missing_field: str
) -> None:
    """Omitting a required field is a validation error."""
    payload = make_book_payload()
    del payload[missing_field]

    response = client.post("/books", json=payload)

    assert response.status_code == 422
    assert any(error["loc"][-1] == missing_field for error in response.json()["detail"])


@pytest.mark.parametrize("field", ["title", "author"])
@pytest.mark.parametrize("value", ["", "   "])
def test_create_book_blank_text_returns_422(client: TestClient, field: str, value: str) -> None:
    """Empty or whitespace-only title/author is a validation error."""
    response = client.post("/books", json=make_book_payload(**{field: value}))

    assert response.status_code == 422


@pytest.mark.parametrize("bad_date", ["26/06/1997", "1997-13-01", "not-a-date"])
def test_create_book_invalid_date_format_returns_422(client: TestClient, bad_date: str) -> None:
    """A publication date that is not a valid ISO date is a validation error."""
    response = client.post("/books", json=make_book_payload(publication_date=bad_date))

    assert response.status_code == 422


def test_create_book_future_publication_date_returns_422(client: TestClient) -> None:
    """A publication date in the future is a validation error."""
    tomorrow = (datetime.now(UTC).date() + timedelta(days=1)).isoformat()

    response = client.post("/books", json=make_book_payload(publication_date=tomorrow))

    assert response.status_code == 422
    assert "future" in response.text


def test_create_book_with_created_at_stores_and_returns_it(client: TestClient) -> None:
    """A provided `created_at` is saved and returned in UTC."""
    response = client.post("/books", json=make_book_payload(created_at="2024-05-10T11:30:00-03:00"))

    assert response.status_code == 201
    created_at = _parse(response.json()["created_at"])
    assert created_at == datetime(2024, 5, 10, 14, 30, tzinfo=UTC)
    assert created_at.utcoffset() == timedelta(0)

    fetched = client.get(f"/books/{response.json()['id']}")
    assert _parse(fetched.json()["created_at"]) == datetime(2024, 5, 10, 14, 30, tzinfo=UTC)


def test_create_book_with_naive_created_at_assumes_utc(client: TestClient) -> None:
    """A `created_at` without timezone is interpreted as UTC."""
    response = client.post("/books", json=make_book_payload(created_at="2024-05-10T14:30:00"))

    assert response.status_code == 201
    assert _parse(response.json()["created_at"]) == datetime(2024, 5, 10, 14, 30, tzinfo=UTC)


def test_create_book_without_created_at_uses_current_time(client: TestClient) -> None:
    """An omitted `created_at` is filled with the current UTC date and time."""
    before = datetime.now(UTC)

    response = client.post("/books", json=make_book_payload())

    after = datetime.now(UTC)
    assert response.status_code == 201
    created_at = _parse(response.json()["created_at"])
    assert created_at.utcoffset() == timedelta(0)
    assert before <= created_at <= after


def test_create_book_future_created_at_returns_422(client: TestClient) -> None:
    """A `created_at` in the future is a validation error."""
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()

    response = client.post("/books", json=make_book_payload(created_at=future))

    assert response.status_code == 422
    assert "future" in response.text


# --- Search ---------------------------------------------------------------


@pytest.fixture
def library(create_book: CreateBook) -> list[dict[str, Any]]:
    """Register a small catalog through the API."""
    return [
        create_book(title="Harry Potter and the Philosopher's Stone", author="J. K. Rowling"),
        create_book(title="Harry Potter and the Chamber of Secrets", author="J. K. Rowling"),
        create_book(title="The Casual Vacancy", author="J. K. Rowling"),
        create_book(title="The Hobbit", author="J. R. R. Tolkien"),
    ]


def test_search_by_partial_title_is_case_insensitive(
    client: TestClient, library: list[dict[str, Any]]
) -> None:
    """`?title=harry` finds every book with "Harry" in the title."""
    response = client.get("/books", params={"title": "harry"})

    assert response.status_code == 200
    titles = [book["title"] for book in response.json()]
    assert titles == [
        "Harry Potter and the Philosopher's Stone",
        "Harry Potter and the Chamber of Secrets",
    ]


def test_search_by_author(client: TestClient, library: list[dict[str, Any]]) -> None:
    """`?author=` filters by partial, case-insensitive author name."""
    response = client.get("/books", params={"author": "TOLKIEN"})

    assert response.status_code == 200
    assert [book["title"] for book in response.json()] == ["The Hobbit"]


def test_search_by_title_and_author(client: TestClient, library: list[dict[str, Any]]) -> None:
    """When both filters are given, books must match both."""
    response = client.get("/books", params={"title": "the", "author": "rowling"})

    assert response.status_code == 200
    titles = {book["title"] for book in response.json()}
    assert titles == {
        "Harry Potter and the Philosopher's Stone",
        "Harry Potter and the Chamber of Secrets",
        "The Casual Vacancy",
    }


def test_search_without_results_returns_empty_list(
    client: TestClient, library: list[dict[str, Any]]
) -> None:
    """A search with no matches returns 200 and an empty list."""
    response = client.get("/books", params={"title": "silmarillion"})

    assert response.status_code == 200
    assert response.json() == []


def test_list_without_filters_returns_all_books(
    client: TestClient, library: list[dict[str, Any]]
) -> None:
    """Without filters, every book is returned ordered by id."""
    response = client.get("/books")

    assert response.status_code == 200
    assert [book["id"] for book in response.json()] == [book["id"] for book in library]


def test_list_paginates_with_skip_and_limit(
    client: TestClient, library: list[dict[str, Any]]
) -> None:
    """`skip` and `limit` return the requested window of books."""
    response = client.get("/books", params={"skip": 1, "limit": 2})

    assert response.status_code == 200
    assert [book["id"] for book in response.json()] == [book["id"] for book in library[1:3]]


@pytest.mark.parametrize(
    "params",
    [
        {"skip": -1},
        {"limit": 0},
        {"limit": Settings.model_fields["max_page_size"].default + 1},
    ],
)
def test_list_invalid_pagination_returns_422(client: TestClient, params: dict[str, int]) -> None:
    """Negative `skip`, zero `limit` or `limit` above the maximum are rejected."""
    response = client.get("/books", params=params)

    assert response.status_code == 422


def test_list_sends_total_of_matching_books_in_header(
    client: TestClient, library: list[dict[str, Any]]
) -> None:
    """`X-Total-Count` counts every match, not just the books in the page."""
    everything = client.get("/books", params={"limit": 1})
    filtered = client.get("/books", params={"author": "rowling", "limit": 1})
    nothing = client.get("/books", params={"title": "no such book"})

    assert everything.headers["X-Total-Count"] == str(len(library))
    assert len(everything.json()) == 1
    assert filtered.headers["X-Total-Count"] == "3"
    assert nothing.headers["X-Total-Count"] == "0"


def test_total_header_is_exposed_to_browsers(client: TestClient) -> None:
    """CORS exposes `X-Total-Count`, so frontend scripts on other origins can read it."""
    response = client.get("/books", headers={"Origin": "http://localhost:8050"})

    assert "x-total-count" in response.headers["access-control-expose-headers"].lower()


def test_page_size_limits_follow_the_app_settings(make_client: AppFactory) -> None:
    """The maximum and default `limit` come from the settings given to `create_app`."""
    client = make_client(max_page_size=3, default_page_size=2)
    for index in range(4):
        client.post("/books", json=make_book_payload(title=f"Book {index}"))

    assert client.get("/books", params={"limit": 4}).status_code == 422
    assert len(client.get("/books", params={"limit": 3}).json()) == 3
    assert len(client.get("/books").json()) == 2


# --- Get by id ------------------------------------------------------------


def test_get_book_by_id_returns_book(client: TestClient, create_book: CreateBook) -> None:
    """An existing id returns 200 and the book."""
    created = create_book()

    response = client.get(f"/books/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_get_book_by_unknown_id_returns_404(client: TestClient) -> None:
    """An unknown id returns 404 with the standard error body."""
    response = client.get("/books/42")

    assert response.status_code == 404
    assert response.json() == {"detail": "Book with id 42 not found"}


@pytest.mark.parametrize("bad_id", ["0", "abc"])
def test_get_book_with_invalid_id_returns_422(client: TestClient, bad_id: str) -> None:
    """A non-positive or non-integer id is a validation error."""
    response = client.get(f"/books/{bad_id}")

    assert response.status_code == 422


# --- Update ---------------------------------------------------------------


def test_update_book_changes_sent_fields_only(client: TestClient, create_book: CreateBook) -> None:
    """PATCH changes the given fields, keeps the others and persists the result."""
    created = create_book(title="Old title", summary="Keep me")

    response = client.patch(
        f"/books/{created['id']}",
        json={"title": "  New title  ", "publication_date": "2001-02-03"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "New title"
    assert body["publication_date"] == "2001-02-03"
    assert body["author"] == created["author"]
    assert body["summary"] == "Keep me"
    assert body["created_at"] == created["created_at"]
    assert client.get(f"/books/{created['id']}").json() == body


def test_update_book_created_at_is_stored_in_utc(
    client: TestClient, create_book: CreateBook
) -> None:
    """An edited `created_at` is converted to UTC like on registration."""
    created = create_book()

    response = client.patch(
        f"/books/{created['id']}", json={"created_at": "2024-05-10T11:30:00-03:00"}
    )

    assert response.status_code == 200
    assert _parse(response.json()["created_at"]) == datetime(2024, 5, 10, 14, 30, tzinfo=UTC)


def test_update_book_with_empty_payload_changes_nothing(
    client: TestClient, create_book: CreateBook
) -> None:
    """An empty PATCH is accepted and returns the book unchanged."""
    created = create_book()

    response = client.patch(f"/books/{created['id']}", json={})

    assert response.status_code == 200
    assert response.json() == created


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "   "},
        {"author": ""},
        {"title": None},
        {"summary": None},
        {"publication_date": "not-a-date"},
        {"id": 99},
    ],
)
def test_update_book_invalid_payload_returns_422(
    client: TestClient, create_book: CreateBook, payload: dict[str, Any]
) -> None:
    """Blank text, `null`, bad dates and unknown fields are rejected."""
    created = create_book()

    response = client.patch(f"/books/{created['id']}", json=payload)

    assert response.status_code == 422
    assert client.get(f"/books/{created['id']}").json() == created


@pytest.mark.parametrize("field", ["publication_date", "created_at"])
def test_update_book_future_dates_return_422(
    client: TestClient, create_book: CreateBook, field: str
) -> None:
    """Dates in the future are rejected on edit as on registration."""
    created = create_book()
    future = datetime.now(UTC) + timedelta(days=1)
    value = future.date().isoformat() if field == "publication_date" else future.isoformat()

    response = client.patch(f"/books/{created['id']}", json={field: value})

    assert response.status_code == 422
    assert "future" in response.text


def test_update_book_by_unknown_id_returns_404(client: TestClient) -> None:
    """Editing an unknown id returns 404."""
    response = client.patch("/books/42", json={"title": "New"})

    assert response.status_code == 404
    assert response.json() == {"detail": "Book with id 42 not found"}


# --- Delete ---------------------------------------------------------------


def test_delete_book_returns_204_and_removes_it(
    client: TestClient, create_book: CreateBook
) -> None:
    """DELETE removes the book; it then disappears from lookups and searches."""
    kept = create_book(title="Kept")
    deleted = create_book(title="Deleted")

    response = client.delete(f"/books/{deleted['id']}")

    assert response.status_code == 204
    assert response.content == b""
    assert client.get(f"/books/{deleted['id']}").status_code == 404
    assert client.get("/books").json() == [kept]


def test_delete_book_by_unknown_id_returns_404(client: TestClient) -> None:
    """Deleting an unknown id returns 404."""
    response = client.delete("/books/42")

    assert response.status_code == 404
    assert response.json() == {"detail": "Book with id 42 not found"}


# --- Documentation --------------------------------------------------------


def test_openapi_documents_endpoints_and_404(client: TestClient) -> None:
    """The OpenAPI schema lists every endpoint and documents the 404 response."""
    schema = client.get("/openapi.json").json()

    assert {"/books", "/books/{book_id}", "/health"} <= set(schema["paths"])
    for method in ("get", "patch", "delete"):
        assert "404" in schema["paths"]["/books/{book_id}"][method]["responses"]
