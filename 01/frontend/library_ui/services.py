"""Pure functions behind the UI: formatting, validation, error parsing and chart data.

Nothing here touches Dash components or the network, so every function can be
unit-tested in isolation (the only I/O is reading the bundled Postman file).
Callbacks stay thin by delegating to this module.
"""

import copy
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, tzinfo
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import plotly.graph_objects as go

# Field names match the API contract so 422 errors map straight onto the form.
FIELD_TITLE = "title"
FIELD_AUTHOR = "author"
FIELD_PUBLICATION_DATE = "publication_date"
FIELD_SUMMARY = "summary"
FIELD_CREATED_AT = "created_at"
FORM_ERROR_KEY = "__form__"

EMPTY_VALUE = "—"
SUMMARY_PREVIEW_LENGTH = 80
# Mirrors the API limits on text fields.
MAX_SUMMARY_LENGTH = 5000
TOP_AUTHORS_LIMIT = 10

# User-facing text is Brazilian Portuguese. Dates use the DD/MM/YYYY pattern and
# are formatted by hand so the output does not depend on the server locale.
DATE_FORMAT = "%d/%m/%Y"
DATETIME_FORMAT = "%d/%m/%Y %H:%M"

# Field names as shown to the user, used to build readable error messages.
FIELD_LABELS = {
    FIELD_TITLE: "Título",
    FIELD_AUTHOR: "Autor",
    FIELD_PUBLICATION_DATE: "Data de publicação",
    FIELD_SUMMARY: "Resumo",
    FIELD_CREATED_AT: "Data de cadastro",
}

# Locations FastAPI prefixes to `loc`; they are not field names.
_LOC_SECTIONS = {"body", "query", "path", "header", "cookie"}

SearchAction = Literal["search", "clear", "next", "previous", "reload"]


# --- Dates and times ---------------------------------------------------------


def resolve_timezone(name: str | None) -> tzinfo:
    """Return the timezone with the given IANA name, falling back to UTC.

    Args:
        name: IANA timezone name reported by the browser (e.g. `America/Sao_Paulo`).

    Returns:
        The matching timezone, or UTC if the name is missing or unknown.
    """
    if not name:
        return UTC
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return UTC


def utc_today() -> date:
    """Return today's date in UTC, which is the reference the API validates against.

    Returns:
        The current UTC date.
    """
    return datetime.now(UTC).date()


def format_date(value: str | None) -> str:
    """Format an ISO date (`YYYY-MM-DD`) as `15/01/2020`.

    Args:
        value: The ISO date string.

    Returns:
        The formatted date, or a dash when the value is missing or invalid.
    """
    if not value:
        return EMPTY_VALUE
    try:
        parsed = date.fromisoformat(value[:10])
    except ValueError:
        return EMPTY_VALUE
    return parsed.strftime(DATE_FORMAT)


def parse_api_datetime(value: str) -> datetime:
    """Parse an ISO 8601 datetime returned by the API into an aware UTC datetime.

    Args:
        value: ISO 8601 string such as `2026-10-28T14:30:00Z`.

    Returns:
        The datetime in UTC. Naive values are assumed to already be UTC.

    Raises:
        ValueError: If the value is not a valid ISO 8601 datetime.
    """
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def format_datetime(value: str | None, tz_name: str | None = None) -> str:
    """Format an API datetime as `28/10/2026 14:30` in the user's timezone.

    The API always answers in UTC; converting to the browser timezone shows the
    user the same wall-clock time they typed when registering the book.

    Args:
        value: ISO 8601 datetime from the API.
        tz_name: IANA timezone of the user. Defaults to UTC.

    Returns:
        The formatted datetime, or a dash when the value is missing or invalid.
    """
    if not value:
        return EMPTY_VALUE
    try:
        local = parse_api_datetime(value).astimezone(resolve_timezone(tz_name))
    except ValueError:
        return EMPTY_VALUE
    return local.strftime(DATETIME_FORMAT)


def format_count(value: int) -> str:
    """Format an integer with Brazilian thousands separators (`1.234`).

    Args:
        value: The number to format.

    Returns:
        The formatted number.
    """
    return f"{value:,}".replace(",", ".")


def local_to_utc_iso(date_value: str, time_value: str | None, tz_name: str | None) -> str:
    """Convert a local date and time typed by the user into an ISO 8601 UTC string.

    The API stores every `created_at` in UTC. The user, however, thinks in their
    own timezone, so the local wall-clock time is interpreted in the browser's
    timezone first and only then converted to UTC.

    Args:
        date_value: Local date in `YYYY-MM-DD` format.
        time_value: Local time in `HH:MM` or `HH:MM:SS` format. Empty means midnight.
        tz_name: IANA timezone of the user. Defaults to UTC.

    Returns:
        The instant in UTC, formatted as `YYYY-MM-DDTHH:MM:SSZ`.

    Raises:
        ValueError: If the date or time cannot be parsed.
    """
    local_date = date.fromisoformat(date_value[:10])
    local_time = time.fromisoformat(time_value) if time_value else time(0, 0)
    # Attach the user's timezone to the naive wall-clock time, then convert.
    local_dt = datetime.combine(local_date, local_time, tzinfo=resolve_timezone(tz_name))
    return local_dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def truncate_text(text: str | None, max_length: int = SUMMARY_PREVIEW_LENGTH) -> str:
    """Shorten text to at most `max_length` characters, adding an ellipsis.

    Args:
        text: The text to shorten.
        max_length: Maximum length of the result, ellipsis included.

    Returns:
        The original text if short enough, otherwise a truncated version.
    """
    if not text:
        return ""
    text = " ".join(text.split())
    if len(text) <= max_length:
        return text
    # Cut on a word boundary when possible so the preview does not end mid-word.
    cut = text[: max_length - 1]
    if text[len(cut)] != " " and " " in cut:
        cut = cut[: cut.rfind(" ")]
    return f"{cut.rstrip(' ,.;:')}…"


# --- Register form ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BookForm:
    """Raw values of the Register Book form, exactly as Dash provides them.

    Attributes:
        title: Title input value.
        author: Author input value.
        publication_date: Date picker value (`YYYY-MM-DD`).
        summary: Summary textarea value.
        created_date: Optional "Created At" date picker value.
        created_time: Optional "Created At" time input value (`HH:MM`).
    """

    title: str | None = None
    author: str | None = None
    publication_date: str | None = None
    summary: str | None = None
    created_date: str | None = None
    created_time: str | None = None


def validate_book_form(
    form: BookForm,
    tz_name: str | None,
    now: datetime | None = None,
    *,
    require_created_at: bool = False,
) -> dict[str, str]:
    """Validate the form with the same rules the API enforces.

    Checking in the browser first gives instant feedback without a round trip;
    the API still validates again, and its 422 errors are shown the same way.

    Args:
        form: The raw form values.
        tz_name: IANA timezone of the user, used to interpret "Created At".
        now: Current UTC time. Injectable for tests.
        require_created_at: Whether "Created At" must be filled. Optional when
            registering (the API stamps the current time), required when editing
            (an empty value cannot be stored).

    Returns:
        A mapping of field name to error message. Empty when the form is valid.
    """
    now = now or datetime.now(UTC)
    errors: dict[str, str] = {}

    # Title and author are required and cannot be only whitespace.
    if not (form.title or "").strip():
        errors[FIELD_TITLE] = "Informe o título."
    if not (form.author or "").strip():
        errors[FIELD_AUTHOR] = "Informe o autor."

    # The API compares the publication date with today's date in UTC.
    if not form.publication_date:
        errors[FIELD_PUBLICATION_DATE] = "Informe a data de publicação."
    else:
        try:
            if date.fromisoformat(form.publication_date[:10]) > now.date():
                errors[FIELD_PUBLICATION_DATE] = "A data de publicação não pode estar no futuro."
        except ValueError:
            errors[FIELD_PUBLICATION_DATE] = "Informe uma data válida."

    # "Created At" is optional on registration, but a time without a date is ambiguous.
    if require_created_at and not form.created_date:
        errors[FIELD_CREATED_AT] = "Informe a data de cadastro."
    elif form.created_time and not form.created_date:
        errors[FIELD_CREATED_AT] = "Escolha uma data para o horário informado."
    elif form.created_date:
        try:
            created = parse_api_datetime(
                local_to_utc_iso(form.created_date, form.created_time, tz_name)
            )
        except ValueError:
            errors[FIELD_CREATED_AT] = "Informe uma data e hora válidas."
        else:
            if created > now:
                errors[FIELD_CREATED_AT] = "A data de cadastro não pode estar no futuro."

    return errors


def build_book_payload(form: BookForm, tz_name: str | None) -> dict[str, Any]:
    """Build the JSON body for `POST /books` from the form values.

    `created_at` is only sent when the user filled it in; omitting it lets the
    API stamp the current date and time itself.

    Args:
        form: The raw form values (assumed to be valid).
        tz_name: IANA timezone of the user, used to convert "Created At" to UTC.

    Returns:
        The request payload.
    """
    payload: dict[str, Any] = {
        FIELD_TITLE: (form.title or "").strip(),
        FIELD_AUTHOR: (form.author or "").strip(),
        FIELD_PUBLICATION_DATE: (form.publication_date or "")[:10],
        FIELD_SUMMARY: (form.summary or "").strip(),
    }
    if form.created_date:
        payload[FIELD_CREATED_AT] = local_to_utc_iso(form.created_date, form.created_time, tz_name)
    return payload


# --- Edit form -------------------------------------------------------------


def utc_to_local_parts(value: str | None, tz_name: str | None) -> tuple[str, str]:
    """Split an API datetime into the local date and time shown in the edit form.

    The inverse of `local_to_utc_iso`: the stored UTC instant is converted to
    the user's timezone so the inputs show the wall-clock time they expect.

    Args:
        value: ISO 8601 datetime from the API.
        tz_name: IANA timezone of the user.

    Returns:
        `(YYYY-MM-DD, HH:MM)`, or two empty strings when the value is missing or invalid.
    """
    if not value:
        return "", ""
    try:
        local = parse_api_datetime(value).astimezone(resolve_timezone(tz_name))
    except ValueError:
        return "", ""
    return local.date().isoformat(), local.strftime("%H:%M")


def book_to_form(book: Mapping[str, Any], tz_name: str | None) -> BookForm:
    """Fill the edit form with a stored book.

    Args:
        book: The book returned by the API.
        tz_name: IANA timezone of the user.

    Returns:
        The form values.
    """
    created_date, created_time = utc_to_local_parts(book.get(FIELD_CREATED_AT), tz_name)
    return BookForm(
        title=str(book.get(FIELD_TITLE) or ""),
        author=str(book.get(FIELD_AUTHOR) or ""),
        publication_date=str(book.get(FIELD_PUBLICATION_DATE) or "")[:10],
        summary=str(book.get(FIELD_SUMMARY) or ""),
        created_date=created_date,
        created_time=created_time,
    )


def build_update_payload(
    form: BookForm, tz_name: str | None, original: Mapping[str, Any]
) -> dict[str, Any]:
    """Build the JSON body for `PATCH /books/{id}` with only the changed fields.

    Sending only what changed keeps the request minimal and, above all, keeps
    the stored `created_at` intact (seconds included) when the user did not touch
    it, since the form only shows hours and minutes.

    Args:
        form: The raw edit form values (assumed to be valid).
        tz_name: IANA timezone of the user.
        original: The book as it was when the form was opened.

    Returns:
        The fields that differ from `original`; empty when nothing changed.
    """
    payload = build_book_payload(form, tz_name)
    # "Created At" is compared in the form's own terms (local date + HH:MM).
    shown = utc_to_local_parts(original.get(FIELD_CREATED_AT), tz_name)
    if (form.created_date or "", (form.created_time or "")[:5]) == shown:
        payload.pop(FIELD_CREATED_AT, None)
    return {
        field: value
        for field, value in payload.items()
        if field == FIELD_CREATED_AT or value != original.get(field)
    }


# --- Postman collection ----------------------------------------------------


POSTMAN_COLLECTION_FILE = Path(__file__).parent / "postman" / "library-api.postman_collection.json"
POSTMAN_DOWNLOAD_NAME = "library-api.postman_collection.json"


def build_postman_collection(
    template: Mapping[str, Any], base_url: str, api_key: str | None
) -> dict[str, Any]:
    """Return the Postman collection ready to run against the given API.

    `baseUrl` and `apiKey` are stored as collection variables, so the file works
    right after import, without creating an environment. A selected Postman
    environment still overrides them.

    Args:
        template: The collection as stored in the repository.
        base_url: API URL reachable from the user's machine.
        api_key: Key to embed, or `None` to leave it for the user to fill in.

    Returns:
        A new collection; `template` is not modified.
    """
    collection = copy.deepcopy(dict(template))
    filled = {"baseUrl": base_url, "apiKey": api_key or ""}
    variables = [
        variable for variable in collection.get("variable", []) if variable.get("key") not in filled
    ]
    collection["variable"] = [
        {"key": "baseUrl", "value": base_url, "type": "string"},
        {"key": "apiKey", "value": api_key or "", "type": "secret"},
        *variables,
    ]
    return collection


def load_postman_collection(base_url: str, api_key: str | None) -> str:
    """Read the bundled collection and fill in the API URL and key.

    Args:
        base_url: API URL reachable from the user's machine.
        api_key: Key to embed, or `None`.

    Returns:
        The collection as JSON text.
    """
    template = json.loads(POSTMAN_COLLECTION_FILE.read_text(encoding="utf-8"))
    collection = build_postman_collection(template, base_url, api_key)
    return json.dumps(collection, indent=2, ensure_ascii=False)


# --- API error parsing -----------------------------------------------------


def _friendly_message(error: Mapping[str, Any], field: str) -> str:
    """Turn one FastAPI validation error into a Portuguese sentence for end users.

    The API answers in English, so messages are rebuilt from the error `type`
    (stable across Pydantic versions) instead of translating the raw text.

    Args:
        error: One item of the 422 `detail` list.
        field: Field the error belongs to.

    Returns:
        A readable message.
    """
    error_type = str(error.get("type", ""))
    if error_type == "missing":
        return "Campo obrigatório."
    if error_type == "string_too_short":
        return "Este campo não pode ficar vazio."
    if error_type == "string_too_long":
        return "Texto longo demais."
    if error_type.startswith(("date_", "datetime_")):
        return "Informe uma data válida."
    # Custom validators come as "Value error, publication_date cannot be in the future".
    if error_type == "value_error" and "future" in str(error.get("msg", "")):
        label = FIELD_LABELS.get(field, "A data")
        return f"{label} não pode estar no futuro."
    return "Valor inválido."


_HTTP_ERROR_MESSAGES = {
    401: "Acesso negado pela API. Verifique a chave de acesso (API_KEY) do frontend.",
    413: "Os dados enviados são grandes demais para a API.",
    429: "Muitas requisições em pouco tempo. Aguarde alguns segundos e tente novamente.",
}


def http_error_message(status_code: int) -> str:
    """Return the message shown for an unexpected API status code.

    The API's security layer answers 401 (API key), 413 (body too large) and
    429 (rate limit); each gets an explanation the user can act on.

    Args:
        status_code: HTTP status returned by the API.

    Returns:
        A Portuguese message for the user.
    """
    return _HTTP_ERROR_MESSAGES.get(
        status_code,
        f"A API retornou uma resposta inesperada (HTTP {status_code}). Tente novamente.",
    )


def parse_validation_errors(detail: Any) -> dict[str, str]:
    """Map a FastAPI 422 `detail` onto form fields.

    Each error's `loc` looks like `["body", "title"]`; the last element that is
    not a location section (`body`, `query`, ...) is the field name. Errors that
    cannot be tied to a field are grouped under `FORM_ERROR_KEY`.

    Args:
        detail: The `detail` value of a 422 response.

    Returns:
        A mapping of field name to a readable message. Several errors on the
        same field are joined in a single message.
    """
    if not isinstance(detail, list):
        return {FORM_ERROR_KEY: "A API recusou os dados enviados."}

    errors: dict[str, str] = {}
    for error in detail:
        if not isinstance(error, Mapping):
            continue
        loc = error.get("loc") or []
        field = next(
            (str(part) for part in reversed(loc) if isinstance(part, str)
             and part not in _LOC_SECTIONS),
            FORM_ERROR_KEY,
        )  # fmt: skip
        message = _friendly_message(error, field)
        errors[field] = f"{errors[field]} {message}" if field in errors else message
    return errors


# --- Search ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SearchState:
    """Current filters and page of the Search screen.

    Attributes:
        title: Title filter applied to the results.
        author: Author filter applied to the results.
        page: Zero-based page index.
    """

    title: str = ""
    author: str = ""
    page: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize the state for a `dcc.Store`.

        Returns:
            A JSON-compatible dict.
        """
        return {"title": self.title, "author": self.author, "page": self.page}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "SearchState":
        """Rebuild the state from a `dcc.Store` value.

        Args:
            data: The stored dict, or `None` on first load.

        Returns:
            The state, or the default state when nothing is stored.
        """
        if not data:
            return cls()
        return cls(
            title=str(data.get("title") or ""),
            author=str(data.get("author") or ""),
            page=max(int(data.get("page") or 0), 0),
        )


def next_search_state(
    current: SearchState, action: SearchAction, title: str | None, author: str | None
) -> SearchState:
    """Compute the new search state after a user action.

    Args:
        current: The state before the action.
        action: What the user did.
        title: Current value of the title input.
        author: Current value of the author input.

    Returns:
        The state to load.
    """
    if action == "search":
        # New filters always start from the first page.
        return SearchState((title or "").strip(), (author or "").strip(), 0)
    if action == "clear":
        return SearchState()
    if action == "next":
        return SearchState(current.title, current.author, current.page + 1)
    if action == "previous":
        return SearchState(current.title, current.author, max(current.page - 1, 0))
    return current


def page_request(state: SearchState, page_size: int) -> tuple[int, int]:
    """Return the `skip` and `limit` to request for a page.

    One extra row is requested: if it comes back, there is a next page. This
    avoids a separate "count" request, which the API does not offer.

    Args:
        state: The search state.
        page_size: Rows per page.

    Returns:
        The `(skip, limit)` pair.
    """
    return state.page * page_size, page_size + 1


@dataclass(frozen=True, slots=True)
class PageResult:
    """One page of search results.

    Attributes:
        books: The books on this page.
        page: Zero-based page index.
        page_size: Rows per page.
        has_previous: Whether a previous page exists.
        has_next: Whether a next page exists.
    """

    books: list[dict[str, Any]]
    page: int
    page_size: int
    has_previous: bool
    has_next: bool

    @property
    def summary(self) -> str:
        """Human-readable result counter, e.g. `Exibindo livros 11–20`."""
        if not self.books:
            return "Nenhum livro encontrado"
        first = self.page * self.page_size + 1
        last = first + len(self.books) - 1
        return f"Exibindo livro {first}" if first == last else f"Exibindo livros {first}–{last}"


def build_page_result(
    books: Sequence[Mapping[str, Any]], state: SearchState, page_size: int
) -> PageResult:
    """Split an over-fetched API response into a page and a "has next" flag.

    Args:
        books: Books returned by the API (up to `page_size + 1`).
        state: The search state that produced them.
        page_size: Rows per page.

    Returns:
        The page result.
    """
    return PageResult(
        books=[dict(book) for book in books[:page_size]],
        page=state.page,
        page_size=page_size,
        has_previous=state.page > 0,
        has_next=len(books) > page_size,
    )


def book_to_row(book: Mapping[str, Any], tz_name: str | None) -> dict[str, Any]:
    """Convert an API book into a DataTable row with display-ready values.

    Args:
        book: The book returned by the API.
        tz_name: IANA timezone of the user.

    Returns:
        The table row. `id` is kept so clicked rows can be resolved.
    """
    return {
        "id": book.get("id"),
        FIELD_TITLE: book.get(FIELD_TITLE, ""),
        FIELD_AUTHOR: book.get(FIELD_AUTHOR, ""),
        FIELD_PUBLICATION_DATE: format_date(book.get(FIELD_PUBLICATION_DATE)),
        FIELD_CREATED_AT: format_datetime(book.get(FIELD_CREATED_AT), tz_name),
        FIELD_SUMMARY: truncate_text(book.get(FIELD_SUMMARY)),
    }


def sort_books(
    books: Sequence[Mapping[str, Any]], sort_by: Sequence[Mapping[str, Any]] | None
) -> list[dict[str, Any]]:
    """Sort books by the DataTable `sort_by` specification.

    Sorting happens on the raw API values (ISO dates) rather than on the
    formatted text, where `Apr` would wrongly come before `Jan`.

    Args:
        books: Books returned by the API.
        sort_by: DataTable `sort_by` entries (`column_id`, `direction`).

    Returns:
        A sorted copy of the books.
    """
    result = [dict(book) for book in books]
    # Python's sort is stable, so applying keys from last to first gives a
    # multi-column sort where the first entry has the highest priority.
    for spec in reversed(sort_by or []):
        column = str(spec.get("column_id", ""))
        result.sort(
            key=lambda book: str(book.get(column) or "").casefold(),
            reverse=spec.get("direction") == "desc",
        )
    return result


# --- Dashboard -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LibrarySummary:
    """Figures shown in the dashboard summary cards.

    Attributes:
        total_books: Number of books.
        total_authors: Number of distinct authors (case-insensitive).
        oldest_book: Book with the earliest publication date, if any.
        newest_book: Book with the latest publication date, if any.
    """

    total_books: int
    total_authors: int
    oldest_book: dict[str, Any] | None
    newest_book: dict[str, Any] | None


def _author_key(author: Any) -> str:
    """Normalize an author name so `J. K. Rowling` and `j. k. rowling` match.

    Args:
        author: The raw author value.

    Returns:
        The normalized key.
    """
    return " ".join(str(author or "").split()).casefold()


def compute_summary(books: Sequence[Mapping[str, Any]]) -> LibrarySummary:
    """Compute the dashboard summary cards.

    Args:
        books: All books in the library.

    Returns:
        The summary. Oldest/newest are `None` for an empty library.
    """
    if not books:
        return LibrarySummary(0, 0, None, None)
    # ISO dates sort chronologically as strings; the id breaks ties deterministically.
    ordered = sorted(books, key=lambda b: (str(b.get(FIELD_PUBLICATION_DATE)), b.get("id") or 0))
    return LibrarySummary(
        total_books=len(books),
        total_authors=len({_author_key(book.get(FIELD_AUTHOR)) for book in books}),
        oldest_book=dict(ordered[0]),
        newest_book=dict(ordered[-1]),
    )


def books_per_year(books: Sequence[Mapping[str, Any]]) -> tuple[list[int], list[int]]:
    """Count books per publication year.

    Args:
        books: All books in the library.

    Returns:
        Years in ascending order and the number of books in each.
    """
    counts: Counter[int] = Counter()
    for book in books:
        try:
            counts[date.fromisoformat(str(book.get(FIELD_PUBLICATION_DATE))[:10]).year] += 1
        except ValueError:
            continue
    years = sorted(counts)
    return years, [counts[year] for year in years]


def top_authors(
    books: Sequence[Mapping[str, Any]], limit: int = TOP_AUTHORS_LIMIT
) -> list[tuple[str, int]]:
    """Rank authors by number of books.

    Args:
        books: All books in the library.
        limit: Maximum number of authors returned.

    Returns:
        `(author, count)` pairs, most books first, ties ordered by name.
    """
    counts: Counter[str] = Counter()
    display_names: dict[str, str] = {}
    for book in books:
        key = _author_key(book.get(FIELD_AUTHOR))
        if not key:
            continue
        counts[key] += 1
        # Keep the first spelling seen as the label shown in the chart.
        display_names.setdefault(key, " ".join(str(book.get(FIELD_AUTHOR)).split()))
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [(display_names[key], count) for key, count in ranked[:limit]]


_CHART_LAYOUT: dict[str, Any] = {
    "template": "plotly_white",
    "margin": {"l": 16, "r": 16, "t": 16, "b": 16},
    "font": {"family": "Lato, -apple-system, 'Segoe UI', sans-serif", "size": 13},
    "hoverlabel": {"bgcolor": "white"},
}
_CHART_COLOR = "#2c3e50"
_CHART_ACCENT = "#18bc9c"


def build_books_per_year_figure(years: Sequence[int], counts: Sequence[int]) -> go.Figure:
    """Build the "books per publication year" bar chart.

    Args:
        years: Publication years.
        counts: Number of books in each year.

    Returns:
        The Plotly figure.
    """
    figure = go.Figure(
        go.Bar(
            x=[str(year) for year in years],
            y=list(counts),
            marker_color=_CHART_ACCENT,
            hovertemplate="%{x}: %{y} livro(s)<extra></extra>",
        )
    )
    figure.update_layout(**_CHART_LAYOUT)
    # Years are categories here, so gaps between years do not create empty space.
    figure.update_xaxes(type="category", title_text="Ano de publicação")
    figure.update_yaxes(
        title_text="Livros", rangemode="tozero", dtick=1 if max(counts, default=0) <= 10 else None
    )
    return figure


def build_top_authors_figure(authors: Sequence[tuple[str, int]]) -> go.Figure:
    """Build the horizontal "top authors" bar chart.

    Args:
        authors: `(author, count)` pairs, most books first.

    Returns:
        The Plotly figure.
    """
    # Plotly draws horizontal bars bottom-up; reverse so the top author is on top.
    names = [name for name, _ in reversed(authors)]
    values = [count for _, count in reversed(authors)]
    figure = go.Figure(
        go.Bar(
            x=values,
            y=names,
            orientation="h",
            marker_color=_CHART_COLOR,
            hovertemplate="%{y}: %{x} livro(s)<extra></extra>",
        )
    )
    figure.update_layout(**_CHART_LAYOUT)
    figure.update_xaxes(
        title_text="Livros", rangemode="tozero", dtick=1 if max(values, default=0) <= 10 else None
    )
    figure.update_yaxes(automargin=True)
    return figure
