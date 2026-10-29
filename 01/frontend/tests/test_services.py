"""Tests for the pure functions in `library_ui.services`."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from library_ui import services
from library_ui.config import Settings, read_env_file
from library_ui.services import BookForm, SearchState

NOW = datetime(2026, 10, 28, 15, 0, tzinfo=UTC)


def make_book(book_id: int, **overrides: Any) -> dict[str, Any]:
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


def valid_form(**overrides: Any) -> BookForm:
    """Build a valid Register form, with optional overrides."""
    fields: dict[str, Any] = {
        "title": "Dune",
        "author": "Frank Herbert",
        "publication_date": "1965-08-01",
        "summary": "Spice.",
    }
    fields.update(overrides)
    return BookForm(**fields)


# --- Formatting ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2020-01-15", "15/01/2020"),
        ("1997-06-26", "26/06/1997"),
        ("2020-12-05T00:00:00", "05/12/2020"),
        (None, "—"),
        ("", "—"),
        ("not-a-date", "—"),
    ],
)
def test_format_date(value: str | None, expected: str) -> None:
    """ISO dates are shown as `15/01/2020`; bad values become a dash."""
    assert services.format_date(value) == expected


def test_format_datetime_in_utc_by_default() -> None:
    """Without a timezone, API datetimes are shown in UTC."""
    assert services.format_datetime("2026-10-28T14:30:00Z") == "28/10/2026 14:30"


def test_format_datetime_converts_to_user_timezone() -> None:
    """Datetimes are shown in the user's timezone."""
    assert services.format_datetime("2026-10-28T14:30:00Z", "America/Sao_Paulo") == (
        "28/10/2026 11:30"
    )


@pytest.mark.parametrize("value", [None, "", "garbage"])
def test_format_datetime_invalid_values(value: str | None) -> None:
    """Missing or invalid datetimes become a dash."""
    assert services.format_datetime(value) == "—"


def test_resolve_timezone_falls_back_to_utc() -> None:
    """Unknown or missing timezone names fall back to UTC."""
    assert services.resolve_timezone(None) is UTC
    assert services.resolve_timezone("Not/AZone") is UTC
    assert str(services.resolve_timezone("Europe/Lisbon")) == "Europe/Lisbon"


def test_parse_api_datetime_assumes_utc_for_naive_values() -> None:
    """Naive datetimes from the API are treated as UTC."""
    assert services.parse_api_datetime("2026-01-01T10:00:00") == datetime(
        2026, 1, 1, 10, tzinfo=UTC
    )


# --- Local to UTC conversion ------------------------------------------------


def test_local_to_utc_iso_converts_from_user_timezone() -> None:
    """A local time in São Paulo (UTC-3) becomes the matching UTC instant."""
    assert services.local_to_utc_iso("2026-10-28", "11:30", "America/Sao_Paulo") == (
        "2026-10-28T14:30:00Z"
    )


def test_local_to_utc_iso_handles_daylight_saving_time() -> None:
    """The offset in effect on that date is used (New York is UTC-4 in July)."""
    assert services.local_to_utc_iso("2026-07-01", "08:00", "America/New_York") == (
        "2026-07-01T12:00:00Z"
    )


def test_local_to_utc_iso_can_cross_the_date_line() -> None:
    """Converting to UTC may change the calendar day."""
    assert services.local_to_utc_iso("2026-10-28", "23:30", "America/Sao_Paulo") == (
        "2026-10-29T02:30:00Z"
    )


def test_local_to_utc_iso_without_time_uses_midnight() -> None:
    """An empty time means midnight in the user's timezone."""
    assert services.local_to_utc_iso("2026-10-28", None, "UTC") == "2026-10-28T00:00:00Z"


# --- Payload ------------------------------------------------------------------


def test_build_payload_without_created_at_omits_field() -> None:
    """When Created At is empty, the field is not sent so the API fills it."""
    payload = services.build_book_payload(valid_form(title="  Dune  "), "UTC")

    assert payload == {
        "title": "Dune",
        "author": "Frank Herbert",
        "publication_date": "1965-08-01",
        "summary": "Spice.",
    }


def test_build_payload_with_created_at_sends_utc_iso() -> None:
    """When Created At is filled, it is sent as an ISO 8601 UTC string."""
    form = valid_form(created_date="2024-05-10", created_time="11:30")

    payload = services.build_book_payload(form, "America/Sao_Paulo")

    assert payload["created_at"] == "2024-05-10T14:30:00Z"


def test_build_payload_handles_missing_summary() -> None:
    """A missing summary is sent as an empty string."""
    assert services.build_book_payload(valid_form(summary=None), None)["summary"] == ""


# --- Validation ---------------------------------------------------------------


def test_validate_valid_form_has_no_errors() -> None:
    """A complete form passes validation."""
    assert services.validate_book_form(valid_form(), "UTC", now=NOW) == {}


def test_validate_required_fields() -> None:
    """Blank title/author and a missing publication date are reported."""
    errors = services.validate_book_form(
        BookForm(title="  ", author=None, publication_date=None), "UTC", now=NOW
    )

    assert set(errors) == {"title", "author", "publication_date"}


def test_validate_future_publication_date() -> None:
    """A publication date after today (UTC) is rejected."""
    errors = services.validate_book_form(valid_form(publication_date="2026-10-29"), "UTC", now=NOW)

    assert errors == {"publication_date": "A data de publicação não pode estar no futuro."}


def test_validate_invalid_publication_date() -> None:
    """A malformed publication date is rejected."""
    errors = services.validate_book_form(valid_form(publication_date="2026-13-40"), "UTC", now=NOW)

    assert errors == {"publication_date": "Informe uma data válida."}


def test_validate_future_created_at() -> None:
    """A Created At later than now is rejected."""
    form = valid_form(created_date="2026-10-28", created_time="16:00")

    assert services.validate_book_form(form, "UTC", now=NOW) == {
        "created_at": "A data de cadastro não pode estar no futuro."
    }


def test_validate_created_at_uses_user_timezone() -> None:
    """12:30 in São Paulo is 15:30 UTC, which is after `NOW` (15:00 UTC)."""
    form = valid_form(created_date="2026-10-28", created_time="12:30")

    assert "created_at" in services.validate_book_form(form, "America/Sao_Paulo", now=NOW)
    assert services.validate_book_form(form, "UTC", now=NOW) == {}


def test_validate_time_without_date() -> None:
    """A Created At time without a date is ambiguous and rejected."""
    errors = services.validate_book_form(valid_form(created_time="10:00"), "UTC", now=NOW)

    assert errors == {"created_at": "Escolha uma data para o horário informado."}


def test_validate_invalid_created_time() -> None:
    """A malformed Created At time is rejected."""
    form = valid_form(created_date="2026-10-01", created_time="25:99")

    assert services.validate_book_form(form, "UTC", now=NOW) == {
        "created_at": "Informe uma data e hora válidas."
    }


# --- Truncation ---------------------------------------------------------------


def test_truncate_text_keeps_short_text() -> None:
    """Text within the limit is returned unchanged."""
    assert services.truncate_text("Short summary", 80) == "Short summary"


def test_truncate_text_cuts_on_word_boundary() -> None:
    """Long text is cut on a word boundary and ends with an ellipsis."""
    result = services.truncate_text("The quick brown fox jumps over the lazy dog", 20)

    assert result == "The quick brown fox…"
    assert len(result) <= 20


def test_truncate_text_without_spaces() -> None:
    """A single long word is hard-cut."""
    assert services.truncate_text("a" * 30, 10) == "a" * 9 + "…"


@pytest.mark.parametrize("value", [None, ""])
def test_truncate_text_empty(value: str | None) -> None:
    """Missing text becomes an empty string."""
    assert services.truncate_text(value) == ""


# --- 422 parsing --------------------------------------------------------------


def test_parse_validation_errors_maps_fields_and_messages() -> None:
    """Each FastAPI error is mapped to its field with a friendly message."""
    detail = [
        {"loc": ["body", "author"], "msg": "Field required", "type": "missing"},
        {"loc": ["body", "publication_date"], "msg": "Input should be a valid date",
         "type": "date_from_datetime_parsing"},
        {"loc": ["body", "created_at"], "msg": "Value error, created_at cannot be in the future",
         "type": "value_error"},
        {"loc": ["body", "title"], "msg": "String should have at most 255 characters",
         "type": "string_too_long"},
    ]  # fmt: skip

    assert services.parse_validation_errors(detail) == {
        "author": "Campo obrigatório.",
        "publication_date": "Informe uma data válida.",
        "created_at": "Data de cadastro não pode estar no futuro.",
        "title": "Texto longo demais.",
    }


def test_parse_validation_errors_joins_errors_of_same_field() -> None:
    """Several errors on one field are combined into a single message."""
    detail = [
        {"loc": ["body", "title"], "msg": "first", "type": "x"},
        {"loc": ["body", "title"], "msg": "second.", "type": "y"},
    ]

    assert services.parse_validation_errors(detail) == {"title": "Valor inválido. Valor inválido."}


def test_parse_validation_errors_without_field_goes_to_form() -> None:
    """Errors on the whole body (or non-dict items) are grouped as form errors."""
    detail = [{"loc": ["body"], "msg": "JSON decode error", "type": "json_invalid"}, "junk"]

    assert services.parse_validation_errors(detail) == {services.FORM_ERROR_KEY: "Valor inválido."}


def test_parse_validation_errors_with_non_list_detail() -> None:
    """A non-list detail becomes a generic form-level error."""
    expected = {services.FORM_ERROR_KEY: "A API recusou os dados enviados."}
    assert services.parse_validation_errors("Bad input") == expected
    assert services.parse_validation_errors(None) == expected


@pytest.mark.parametrize(
    ("status_code", "fragment"),
    [
        (401, "chave de acesso"),
        (413, "grandes demais"),
        (429, "Muitas requisições"),
        (503, "HTTP 503"),
    ],
)
def test_http_error_message(status_code: int, fragment: str) -> None:
    """Security statuses get specific Portuguese messages; others a generic one."""
    assert fragment in services.http_error_message(status_code)


# --- Search -------------------------------------------------------------------


def test_next_search_state_actions() -> None:
    """Search resets the page, Clear resets everything, Next/Previous move pages."""
    current = SearchState("harry", "", 2)

    assert services.next_search_state(current, "search", " dune ", None) == SearchState(
        "dune", "", 0
    )
    assert services.next_search_state(current, "clear", "x", "y") == SearchState()
    assert services.next_search_state(current, "next", None, None).page == 3
    assert services.next_search_state(current, "previous", None, None).page == 1
    assert services.next_search_state(SearchState(), "previous", None, None).page == 0
    assert services.next_search_state(current, "reload", "ignored", None) == current


def test_search_state_round_trips_through_store() -> None:
    """The state survives serialization to a `dcc.Store`."""
    state = SearchState("a", "b", 4)

    assert SearchState.from_dict(state.to_dict()) == state
    assert SearchState.from_dict(None) == SearchState()
    assert SearchState.from_dict({"page": -3}).page == 0


def test_page_request_over_fetches_one_row() -> None:
    """One extra row is requested to detect whether a next page exists."""
    assert services.page_request(SearchState(page=2), 10) == (20, 11)


def test_build_page_result_detects_next_page_and_summary() -> None:
    """An over-fetched response yields a full page and `has_next`."""
    books = [make_book(i) for i in range(1, 12)]

    page = services.build_page_result(books, SearchState(page=1), 10)

    assert len(page.books) == 10
    assert page.has_next
    assert page.has_previous
    assert page.summary == "Exibindo livros 11–20"


def test_build_page_result_last_and_empty_pages() -> None:
    """A short page has no next page; an empty one says "Nenhum livro encontrado"."""
    single = services.build_page_result([make_book(1)], SearchState(), 10)
    empty = services.build_page_result([], SearchState(), 10)

    assert not single.has_next
    assert single.summary == "Exibindo livro 1"
    assert empty.summary == "Nenhum livro encontrado"
    assert not empty.has_previous


def test_book_to_row_formats_values() -> None:
    """Table rows carry formatted dates and a truncated summary."""
    book = make_book(
        5, publication_date="2020-01-15", created_at="2026-10-28T14:30:00Z", summary="x" * 200
    )

    row = services.book_to_row(book, "UTC")

    assert row["id"] == 5
    assert row["publication_date"] == "15/01/2020"
    assert row["created_at"] == "28/10/2026 14:30"
    assert len(row["summary"]) <= services.SUMMARY_PREVIEW_LENGTH


def test_sort_books_uses_raw_values() -> None:
    """Dates are sorted chronologically, not alphabetically by formatted text."""
    books = [
        make_book(1, publication_date="2020-04-01"),  # "01/04/2020"
        make_book(2, publication_date="2020-01-01"),  # "01/01/2020"
        make_book(3, publication_date="2019-12-01"),  # "01/12/2019" sorts last as text
    ]

    ascending = services.sort_books(books, [{"column_id": "publication_date", "direction": "asc"}])
    descending = services.sort_books(books, [{"column_id": "title", "direction": "desc"}])

    assert [b["id"] for b in ascending] == [3, 2, 1]
    assert [b["id"] for b in descending] == [3, 2, 1]
    assert services.sort_books(books, None) == books


# --- Dashboard ----------------------------------------------------------------


def test_compute_summary() -> None:
    """Totals count distinct authors case-insensitively and find oldest/newest."""
    books = [
        make_book(1, author="J. K. Rowling", publication_date="1997-06-26"),
        make_book(2, author="j. k.  rowling", publication_date="2007-07-21"),
        make_book(3, author="Frank Herbert", publication_date="1965-08-01"),
    ]

    summary = services.compute_summary(books)

    assert summary.total_books == 3
    assert summary.total_authors == 2
    assert summary.oldest_book is not None and summary.oldest_book["id"] == 3
    assert summary.newest_book is not None and summary.newest_book["id"] == 2


def test_compute_summary_empty() -> None:
    """An empty library has zero totals and no oldest/newest book."""
    assert services.compute_summary([]) == services.LibrarySummary(0, 0, None, None)


def test_books_per_year() -> None:
    """Books are counted per publication year in ascending order."""
    books = [
        make_book(1, publication_date="2001-05-01"),
        make_book(2, publication_date="1999-01-01"),
        make_book(3, publication_date="2001-12-31"),
        make_book(4, publication_date="bad"),
    ]

    assert services.books_per_year(books) == ([1999, 2001], [1, 2])
    assert services.books_per_year([]) == ([], [])


def test_top_authors_ranks_and_limits() -> None:
    """Authors are ranked by count, ties by name, and limited."""
    books = [
        make_book(1, author="B Author"),
        make_book(2, author="A Author"),
        make_book(3, author="b author"),
        make_book(4, author="C Author"),
        make_book(5, author=""),
    ]

    assert services.top_authors(books, limit=2) == [("B Author", 2), ("A Author", 1)]
    assert services.top_authors([]) == []


def test_chart_figures_contain_data() -> None:
    """Figures carry the prepared data; the top author is drawn on top."""
    per_year = services.build_books_per_year_figure([1999, 2001], [1, 2])
    authors = services.build_top_authors_figure([("A", 3), ("B", 1)])
    empty = services.build_books_per_year_figure([], [])

    assert list(per_year.data[0].x) == ["1999", "2001"]
    assert list(per_year.data[0].y) == [1, 2]
    assert list(authors.data[0].y) == ["B", "A"]
    assert len(empty.data) == 1


# --- Config -------------------------------------------------------------------


def test_read_env_file(tmp_path: Path) -> None:
    """`.env` files are parsed, skipping comments and stripping quotes."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        '# comment\nAPI_KEY="abc"\nDASH_PORT=9000\n\nnot a pair\n', encoding="utf-8"
    )

    assert read_env_file(env_file) == {"API_KEY": "abc", "DASH_PORT": "9000"}
    assert read_env_file(tmp_path / "missing.env") == {}


def test_settings_from_env() -> None:
    """Settings are read from environment variables, with defaults."""
    settings = Settings.from_env(
        {"API_BASE_URL": "http://api:8000/", "DASH_DEBUG": "true", "SEARCH_PAGE_SIZE": "5"}
    )

    assert settings.api_base_url == "http://api:8000"
    assert settings.api_key is None
    assert Settings.from_env({"API_KEY": " s3cret "}).api_key == "s3cret"
    assert "s3cret" not in repr(Settings.from_env({"API_KEY": "s3cret"}))
    assert settings.debug is True
    assert settings.search_page_size == 5
    assert Settings.from_env({}) == Settings()
