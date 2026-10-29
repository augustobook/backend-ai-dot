"""Dash callbacks.

Callbacks are intentionally thin: they read component values, delegate the
logic to `services` (pure functions) and the HTTP calls to `BooksApiClient`,
and map the result back onto components.
"""

import logging
from typing import Any

from dash import Dash, Input, Output, State, ctx, no_update

from library_ui import layout, services
from library_ui.api_client import (
    ApiError,
    ApiNotFoundError,
    ApiResponseError,
    ApiUnavailableError,
    ApiValidationError,
    BooksApiClient,
)
from library_ui.config import Settings
from library_ui.layout import Ids

logger = logging.getLogger(__name__)

# Runs in the browser: Dash callbacks execute on the server, which has no idea
# of the user's timezone, so the browser reports its IANA timezone name once.
BROWSER_TIMEZONE_JS = """
function(_) {
    try {
        return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    } catch (e) {
        return "UTC";
    }
}
"""

# Which search action each triggering component stands for.
SEARCH_ACTIONS: dict[str, services.SearchAction] = {
    Ids.SEARCH_BUTTON: "search",
    Ids.SEARCH_TITLE: "search",
    Ids.SEARCH_AUTHOR: "search",
    Ids.CLEAR_BUTTON: "clear",
    Ids.NEXT_PAGE: "next",
    Ids.PREVIOUS_PAGE: "previous",
}

VISIBLE: dict[str, str] = {}
HIDDEN: dict[str, str] = {"display": "none"}


def error_alert(exc: ApiError) -> Any:
    """Build the alert shown when an API call fails.

    Args:
        exc: The error raised by the API client.

    Returns:
        A danger alert; connection problems get a dedicated icon.
    """
    # The API address stays in the server logs only; end users never see it.
    if isinstance(exc, ApiUnavailableError):
        return layout.alert(
            "Não foi possível conectar à API. Verifique se o backend está rodando.",
            icon_name="wifi-off",
        )
    # Exception messages are English (they belong to the code); the UI gets Portuguese.
    if isinstance(exc, ApiResponseError):
        return layout.alert(services.http_error_message(exc.status_code))
    return layout.alert("Ocorreu um erro ao se comunicar com a API. Tente novamente.")


def form_feedback(errors: dict[str, str]) -> dict[str, Any]:
    """Map field errors onto the Register form's `invalid` flags and messages.

    Args:
        errors: Field name to message, from client-side validation or a 422.

    Returns:
        Values for every feedback-related output of `submit_book`.
    """
    return {
        "title_invalid": services.FIELD_TITLE in errors,
        "title_feedback": errors.get(services.FIELD_TITLE, ""),
        "author_invalid": services.FIELD_AUTHOR in errors,
        "author_feedback": errors.get(services.FIELD_AUTHOR, ""),
        "publication_date_invalid": services.FIELD_PUBLICATION_DATE in errors,
        "publication_date_feedback": errors.get(services.FIELD_PUBLICATION_DATE, ""),
        "summary_invalid": services.FIELD_SUMMARY in errors,
        "summary_feedback": errors.get(services.FIELD_SUMMARY, ""),
        # "Created At" is a date + time pair; both get the red border.
        "created_date_invalid": services.FIELD_CREATED_AT in errors,
        "created_time_invalid": services.FIELD_CREATED_AT in errors,
        "created_at_feedback": errors.get(services.FIELD_CREATED_AT, ""),
    }


def unmapped_errors(errors: dict[str, str]) -> list[str]:
    """Return messages that do not belong to any form field.

    Args:
        errors: Field name to message.

    Returns:
        Messages to show in the form-level alert.
    """
    known = {
        services.FIELD_TITLE,
        services.FIELD_AUTHOR,
        services.FIELD_PUBLICATION_DATE,
        services.FIELD_SUMMARY,
        services.FIELD_CREATED_AT,
    }
    return [message for field, message in errors.items() if field not in known]


def register_callbacks(app: Dash, client: BooksApiClient, settings: Settings) -> None:
    """Register every callback of the application.

    Args:
        app: The Dash application.
        client: Client used for all API calls.
        settings: Frontend settings.
    """
    app.clientside_callback(  # type: ignore[no-untyped-call]
        BROWSER_TIMEZONE_JS,
        Output(Ids.BROWSER_TZ, "data"),
        Input(Ids.ROOT, "id"),
    )

    # --- Register Book --------------------------------------------------------

    @app.callback(
        output={
            "alert": Output(Ids.REGISTER_ALERT, "children"),
            "title_invalid": Output(Ids.TITLE, "invalid"),
            "title_feedback": Output(Ids.TITLE_FEEDBACK, "children"),
            "author_invalid": Output(Ids.AUTHOR, "invalid"),
            "author_feedback": Output(Ids.AUTHOR_FEEDBACK, "children"),
            "publication_date_invalid": Output(Ids.PUBLICATION_DATE, "invalid"),
            "publication_date_feedback": Output(Ids.PUBLICATION_DATE_FEEDBACK, "children"),
            "summary_invalid": Output(Ids.SUMMARY, "invalid"),
            "summary_feedback": Output(Ids.SUMMARY_FEEDBACK, "children"),
            "created_date_invalid": Output(Ids.CREATED_DATE, "invalid"),
            "created_time_invalid": Output(Ids.CREATED_TIME, "invalid"),
            "created_at_feedback": Output(Ids.CREATED_AT_FEEDBACK, "children"),
            "title": Output(Ids.TITLE, "value"),
            "author": Output(Ids.AUTHOR, "value"),
            "publication_date": Output(Ids.PUBLICATION_DATE, "value"),
            "summary": Output(Ids.SUMMARY, "value"),
            "created_date": Output(Ids.CREATED_DATE, "value"),
            "created_time": Output(Ids.CREATED_TIME, "value"),
            "books_version": Output(Ids.BOOKS_VERSION, "data"),
        },
        inputs={"n_clicks": Input(Ids.SUBMIT, "n_clicks")},
        state={
            "title": State(Ids.TITLE, "value"),
            "author": State(Ids.AUTHOR, "value"),
            "publication_date": State(Ids.PUBLICATION_DATE, "value"),
            "summary": State(Ids.SUMMARY, "value"),
            "created_date": State(Ids.CREATED_DATE, "value"),
            "created_time": State(Ids.CREATED_TIME, "value"),
            "tz_name": State(Ids.BROWSER_TZ, "data"),
            "books_version": State(Ids.BOOKS_VERSION, "data"),
        },
        # Disable the button and show its spinner while the request is running,
        # which also prevents double submissions.
        running=[
            (Output(Ids.SUBMIT, "disabled"), True, False),
            (Output(Ids.SUBMIT_SPINNER, "style"), layout.SPINNER_VISIBLE, layout.SPINNER_HIDDEN),
        ],
        prevent_initial_call=True,
    )
    def submit_book(
        n_clicks: int,
        title: str | None,
        author: str | None,
        publication_date: str | None,
        summary: str | None,
        created_date: str | None,
        created_time: str | None,
        tz_name: str | None,
        books_version: int | None,
    ) -> dict[str, Any]:
        """Validate the Register form and send it to the API.

        Args:
            n_clicks: Clicks on the submit button (only used as a trigger).
            title: Title input value.
            author: Author input value.
            publication_date: Publication date picker value.
            summary: Summary textarea value.
            created_date: Optional "Created At" date.
            created_time: Optional "Created At" time.
            tz_name: Browser timezone, used to convert "Created At" to UTC.
            books_version: Counter bumped on every successful registration.

        Returns:
            Values for every output: alert, field feedback and, on success,
            cleared form values plus a bumped `books_version`.
        """
        form = services.BookForm(
            title, author, publication_date, summary, created_date, created_time
        )
        # By default the form keeps what the user typed.
        keep_values: dict[str, Any] = {
            "title": no_update,
            "author": no_update,
            "publication_date": no_update,
            "summary": no_update,
            "created_date": no_update,
            "created_time": no_update,
            "books_version": no_update,
        }

        # 1. Client-side validation: instant feedback without calling the API.
        errors = services.validate_book_form(form, tz_name)
        if errors:
            return {
                "alert": layout.alert(
                    "Corrija os campos destacados.", "warning", "exclamation-circle"
                ),
                **form_feedback(errors),
                **keep_values,
            }

        # 2. Send to the API; its own 422 errors are mapped onto the same fields.
        try:
            book = client.create_book(services.build_book_payload(form, tz_name))
        except ApiValidationError as exc:
            logger.info("API rejected the book: %s", exc.field_errors)
            extra = unmapped_errors(exc.field_errors)
            message = " ".join(["A API recusou alguns campos.", *extra])
            return {
                "alert": layout.alert(message, "warning", "exclamation-circle"),
                **form_feedback(exc.field_errors),
                **keep_values,
            }
        except ApiError as exc:
            logger.warning("Could not register book: %s", exc)
            return {"alert": error_alert(exc), **form_feedback({}), **keep_values}

        # 3. Success: confirm, clear the form and tell other screens to reload.
        return {
            "alert": layout.alert(
                f'"{book["title"]}" foi cadastrado com sucesso.', "success", "check-circle"
            ),
            **form_feedback({}),
            "title": "",
            "author": "",
            "publication_date": "",
            "summary": "",
            "created_date": "",
            "created_time": "",
            "books_version": (books_version or 0) + 1,
        }

    # --- Search Books -----------------------------------------------------------

    @app.callback(
        output={
            "state": Output(Ids.SEARCH_STATE, "data"),
            "books": Output(Ids.SEARCH_BOOKS, "data"),
            "count": Output(Ids.RESULT_COUNT, "children"),
            "page_label": Output(Ids.PAGE_LABEL, "children"),
            "previous_disabled": Output(Ids.PREVIOUS_PAGE, "disabled"),
            "next_disabled": Output(Ids.NEXT_PAGE, "disabled"),
            "alert": Output(Ids.SEARCH_ALERT, "children"),
            "title": Output(Ids.SEARCH_TITLE, "value"),
            "author": Output(Ids.SEARCH_AUTHOR, "value"),
            "table_style": Output(Ids.SEARCH_RESULTS, "style"),
            "empty_style": Output(Ids.EMPTY_RESULTS, "style"),
        },
        inputs={
            "search_clicks": Input(Ids.SEARCH_BUTTON, "n_clicks"),
            "title_submit": Input(Ids.SEARCH_TITLE, "n_submit"),
            "author_submit": Input(Ids.SEARCH_AUTHOR, "n_submit"),
            "clear_clicks": Input(Ids.CLEAR_BUTTON, "n_clicks"),
            "previous_clicks": Input(Ids.PREVIOUS_PAGE, "n_clicks"),
            "next_clicks": Input(Ids.NEXT_PAGE, "n_clicks"),
            "tz_name": Input(Ids.BROWSER_TZ, "data"),
            "books_version": Input(Ids.BOOKS_VERSION, "data"),
        },
        state={
            "title": State(Ids.SEARCH_TITLE, "value"),
            "author": State(Ids.SEARCH_AUTHOR, "value"),
            "stored_state": State(Ids.SEARCH_STATE, "data"),
        },
    )
    def search_books(
        search_clicks: int,
        title_submit: int,
        author_submit: int,
        clear_clicks: int,
        previous_clicks: int,
        next_clicks: int,
        tz_name: str | None,
        books_version: int | None,
        title: str | None,
        author: str | None,
        stored_state: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Load a page of search results.

        Triggered by Search/Enter, Clear, Previous/Next, on page load (when the
        browser timezone arrives) and after a book is registered.

        Args:
            search_clicks: Clicks on Search.
            title_submit: Enter presses in the title filter.
            author_submit: Enter presses in the author filter.
            clear_clicks: Clicks on Clear.
            previous_clicks: Clicks on Previous.
            next_clicks: Clicks on Next.
            tz_name: Browser timezone.
            books_version: Counter bumped when a book is registered.
            title: Title filter input value.
            author: Author filter input value.
            stored_state: Current search state.

        Returns:
            Values for every output of the search area.
        """
        # Work out what the user did and which page/filters to load.
        action = SEARCH_ACTIONS.get(str(ctx.triggered_id), "reload")
        current = services.SearchState.from_dict(stored_state)
        state = services.next_search_state(current, action, title, author)
        clear_inputs = action == "clear"
        inputs_update = {
            "title": "" if clear_inputs else no_update,
            "author": "" if clear_inputs else no_update,
        }

        # Request one row more than a page to know whether "Next" is possible.
        skip, limit = services.page_request(state, settings.search_page_size)
        try:
            books = client.search_books(
                title=state.title, author=state.author, skip=skip, limit=limit
            )
        except ApiError as exc:
            logger.warning("Search failed: %s", exc)
            return {
                "state": current.to_dict(),
                "books": [],
                "count": "",
                "page_label": "",
                "previous_disabled": True,
                "next_disabled": True,
                "alert": error_alert(exc),
                "table_style": HIDDEN,
                "empty_style": HIDDEN,
                **inputs_update,
            }

        page = services.build_page_result(books, state, settings.search_page_size)
        has_rows = bool(page.books)
        return {
            "state": state.to_dict(),
            "books": page.books,
            "count": page.summary,
            "page_label": f"Página {page.page + 1}" if has_rows or page.has_previous else "",
            "previous_disabled": not page.has_previous,
            "next_disabled": not page.has_next,
            "alert": None,
            "table_style": VISIBLE if has_rows else HIDDEN,
            "empty_style": HIDDEN if has_rows else VISIBLE,
            **inputs_update,
        }

    @app.callback(
        Output(Ids.RESULTS_TABLE, "data"),
        Input(Ids.SEARCH_BOOKS, "data"),
        Input(Ids.RESULTS_TABLE, "sort_by"),
        State(Ids.BROWSER_TZ, "data"),
    )
    def render_results_table(
        books: list[dict[str, Any]] | None,
        sort_by: list[dict[str, Any]] | None,
        tz_name: str | None,
    ) -> list[dict[str, Any]]:
        """Sort the current page and turn it into display-ready table rows.

        Args:
            books: Raw books of the current page.
            sort_by: DataTable sort specification.
            tz_name: Browser timezone, used to format "Created At".

        Returns:
            Table rows.
        """
        return [
            services.book_to_row(book, tz_name)
            for book in services.sort_books(books or [], sort_by)
        ]

    @app.callback(
        output={
            "is_open": Output(Ids.DETAILS_MODAL, "is_open"),
            "title": Output(Ids.DETAILS_TITLE, "children"),
            "body": Output(Ids.DETAILS_BODY, "children"),
            "active_cell": Output(Ids.RESULTS_TABLE, "active_cell"),
        },
        inputs={
            "active_cell": Input(Ids.RESULTS_TABLE, "active_cell"),
            "close_clicks": Input(Ids.DETAILS_CLOSE, "n_clicks"),
        },
        state={"tz_name": State(Ids.BROWSER_TZ, "data")},
        prevent_initial_call=True,
    )
    def show_book_details(
        active_cell: dict[str, Any] | None, close_clicks: int, tz_name: str | None
    ) -> dict[str, Any]:
        """Open the details modal for the clicked row, or close it.

        Args:
            active_cell: Cell clicked in the results table.
            close_clicks: Clicks on the modal's Close button.
            tz_name: Browser timezone.

        Returns:
            Modal state and content.
        """
        unchanged = {"is_open": no_update, "title": no_update, "body": no_update}
        if ctx.triggered_id == Ids.DETAILS_CLOSE:
            return {**unchanged, "is_open": False, "active_cell": no_update}
        # Resetting `active_cell` below re-triggers this callback with None.
        if not active_cell or active_cell.get("row_id") is None:
            return {**unchanged, "active_cell": no_update}

        # Always fetch the full record: the table only holds a truncated summary.
        try:
            book = client.get_book(int(active_cell["row_id"]))
        except ApiNotFoundError:
            title, body = (
                "Livro não encontrado",
                layout.alert("Este livro não existe mais.", "warning", "question-circle"),
            )
        except ApiError as exc:
            title, body = "Não foi possível carregar o livro", error_alert(exc)
        else:
            title, body = book["title"], layout.book_details(book, tz_name)

        # Clearing the active cell lets the same row be clicked again later.
        return {"is_open": True, "title": title, "body": body, "active_cell": None}

    # --- Dashboard ----------------------------------------------------------------

    @app.callback(
        Output(Ids.DASHBOARD_CARDS, "children"),
        Output(Ids.DASHBOARD_CHARTS, "children"),
        Output(Ids.DASHBOARD_ALERT, "children"),
        Input(Ids.REFRESH_BUTTON, "n_clicks"),
        Input(Ids.BOOKS_VERSION, "data"),
    )
    def refresh_dashboard(n_clicks: int, books_version: int | None) -> tuple[Any, Any, Any]:
        """Load every book and rebuild the dashboard.

        Runs on page load, on "Refresh" and after a book is registered.

        Args:
            n_clicks: Clicks on Refresh.
            books_version: Counter bumped when a book is registered.

        Returns:
            Summary cards, charts and an alert (if the API failed).
        """
        # The dashboard needs the whole catalog, which takes several pages.
        try:
            books = client.fetch_all_books()
        except ApiError as exc:
            logger.warning("Dashboard refresh failed: %s", exc)
            return None, None, error_alert(exc)

        if not books:
            return (
                layout.empty_state(
                    "Nenhum livro ainda",
                    "Cadastre o primeiro livro para ver as estatísticas da biblioteca.",
                    "journal-bookmark",
                ),
                None,
                None,
            )

        # Aggregations are pure functions; the layout only renders them.
        summary = services.compute_summary(books)
        years, counts = services.books_per_year(books)
        cards = layout.summary_cards(summary)
        charts = layout.chart_cards(
            services.build_books_per_year_figure(years, counts),
            services.build_top_authors_figure(services.top_authors(books)),
        )
        return cards, charts, None
