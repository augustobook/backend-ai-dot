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


def form_feedback_outputs(ids: layout.BookFormIds) -> dict[str, Output]:
    """Return the feedback outputs of a book form, keyed like `form_feedback`.

    Args:
        ids: Component ids of the form (Register or Edit).

    Returns:
        The `invalid` flags and inline messages of every field.
    """
    return {
        "title_invalid": Output(ids.title, "invalid"),
        "title_feedback": Output(ids.title_feedback, "children"),
        "author_invalid": Output(ids.author, "invalid"),
        "author_feedback": Output(ids.author_feedback, "children"),
        "publication_date_invalid": Output(ids.publication_date, "invalid"),
        "publication_date_feedback": Output(ids.publication_date_feedback, "children"),
        "summary_invalid": Output(ids.summary, "invalid"),
        "summary_feedback": Output(ids.summary_feedback, "children"),
        "created_date_invalid": Output(ids.created_date, "invalid"),
        "created_time_invalid": Output(ids.created_time, "invalid"),
        "created_at_feedback": Output(ids.created_at_feedback, "children"),
    }


def form_value_outputs(ids: layout.BookFormIds) -> dict[str, Output]:
    """Return the value outputs of a book form, keyed by `BookForm` field.

    Args:
        ids: Component ids of the form.

    Returns:
        One output per input value.
    """
    return {
        "title": Output(ids.title, "value"),
        "author": Output(ids.author, "value"),
        "publication_date": Output(ids.publication_date, "value"),
        "summary": Output(ids.summary, "value"),
        "created_date": Output(ids.created_date, "value"),
        "created_time": Output(ids.created_time, "value"),
    }


def form_value_states(ids: layout.BookFormIds) -> dict[str, State]:
    """Return the value states of a book form, keyed by `BookForm` field.

    Args:
        ids: Component ids of the form.

    Returns:
        One state per input value.
    """
    return {
        key: State(output.component_id, "value") for key, output in form_value_outputs(ids).items()
    }


def form_feedback(errors: dict[str, str]) -> dict[str, Any]:
    """Map field errors onto a book form's `invalid` flags and messages.

    Args:
        errors: Field name to message, from client-side validation or a 422.

    Returns:
        Values for every output of `form_feedback_outputs`.
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

    @app.callback(
        Output(Ids.POSTMAN_DOWNLOAD, "data"),
        Input(Ids.POSTMAN_BUTTON, "n_clicks"),
        prevent_initial_call=True,
    )
    def download_postman_collection(n_clicks: int) -> dict[str, Any]:
        """Send the Postman collection, pointed at the public API URL.

        Args:
            n_clicks: Clicks on the download button (only used as a trigger).

        Returns:
            The file for `dcc.Download`.
        """
        api_key = settings.api_key if settings.postman_include_api_key else None
        return {
            "content": services.load_postman_collection(settings.postman_base_url, api_key),
            "filename": services.POSTMAN_DOWNLOAD_NAME,
            "type": "application/json",
        }

    # --- Register Book --------------------------------------------------------

    @app.callback(
        output={
            "alert": Output(Ids.REGISTER_ALERT, "children"),
            **form_feedback_outputs(layout.REGISTER_FORM),
            **form_value_outputs(layout.REGISTER_FORM),
            "books_version": Output(Ids.BOOKS_VERSION, "data"),
        },
        inputs={"n_clicks": Input(Ids.SUBMIT, "n_clicks")},
        state={
            **form_value_states(layout.REGISTER_FORM),
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
            "current_book": Output(Ids.CURRENT_BOOK, "data"),
            "edit_disabled": Output(Ids.DETAILS_EDIT, "disabled"),
            "delete_disabled": Output(Ids.DETAILS_DELETE, "disabled"),
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
            Modal state and content, plus the loaded book for Edit/Delete.
        """
        unchanged = {
            "is_open": no_update,
            "title": no_update,
            "body": no_update,
            "active_cell": no_update,
            "current_book": no_update,
            "edit_disabled": no_update,
            "delete_disabled": no_update,
        }
        if ctx.triggered_id == Ids.DETAILS_CLOSE:
            return {**unchanged, "is_open": False}
        # Resetting `active_cell` below re-triggers this callback with None.
        if not active_cell or active_cell.get("row_id") is None:
            return unchanged

        # Always fetch the full record: the table only holds a truncated summary.
        book: dict[str, Any] | None = None
        try:
            book = dict(client.get_book(int(active_cell["row_id"])))
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
        # Edit and Delete only make sense once the book was actually loaded.
        return {
            "is_open": True,
            "title": title,
            "body": body,
            "active_cell": None,
            "current_book": book,
            "edit_disabled": book is None,
            "delete_disabled": book is None,
        }

    # --- Edit Book ------------------------------------------------------------

    @app.callback(
        output={
            "edit_open": Output(Ids.EDIT_MODAL, "is_open"),
            "details_open": Output(Ids.DETAILS_MODAL, "is_open", allow_duplicate=True),
            "alert": Output(Ids.EDIT_ALERT, "children"),
            **form_feedback_outputs(layout.EDIT_FORM),
            **form_value_outputs(layout.EDIT_FORM),
        },
        inputs={
            "edit_clicks": Input(Ids.DETAILS_EDIT, "n_clicks"),
            "cancel_clicks": Input(Ids.EDIT_CANCEL, "n_clicks"),
        },
        state={
            "book": State(Ids.CURRENT_BOOK, "data"),
            "tz_name": State(Ids.BROWSER_TZ, "data"),
        },
        prevent_initial_call=True,
    )
    def toggle_edit_form(
        edit_clicks: int,
        cancel_clicks: int,
        book: dict[str, Any] | None,
        tz_name: str | None,
    ) -> dict[str, Any]:
        """Open the Edit modal filled with the current book, or cancel back to details.

        Args:
            edit_clicks: Clicks on Edit in the details modal.
            cancel_clicks: Clicks on Cancel in the Edit modal.
            book: The book shown in the details modal.
            tz_name: Browser timezone, used to show "Created At" in local time.

        Returns:
            Modal states and, when opening, the form values with no errors.
        """
        keep_form = {key: no_update for key in form_value_outputs(layout.EDIT_FORM)}
        if ctx.triggered_id == Ids.EDIT_CANCEL or not book:
            # Cancelling returns to the details of the same book.
            return {
                "edit_open": False,
                "details_open": bool(book),
                "alert": no_update,
                **form_feedback({}),
                **keep_form,
            }

        form = services.book_to_form(book, tz_name)
        return {
            "edit_open": True,
            "details_open": False,
            "alert": None,
            **form_feedback({}),
            "title": form.title,
            "author": form.author,
            "publication_date": form.publication_date,
            "summary": form.summary,
            "created_date": form.created_date,
            "created_time": form.created_time,
        }

    @app.callback(
        output={
            "alert": Output(Ids.EDIT_ALERT, "children", allow_duplicate=True),
            **{
                key: Output(output.component_id, output.component_property, allow_duplicate=True)
                for key, output in form_feedback_outputs(layout.EDIT_FORM).items()
            },
            "edit_open": Output(Ids.EDIT_MODAL, "is_open", allow_duplicate=True),
            "action_alert": Output(Ids.BOOK_ACTION_ALERT, "children"),
            "current_book": Output(Ids.CURRENT_BOOK, "data", allow_duplicate=True),
            "books_version": Output(Ids.BOOKS_VERSION, "data", allow_duplicate=True),
        },
        inputs={"n_clicks": Input(Ids.EDIT_SAVE, "n_clicks")},
        state={
            **form_value_states(layout.EDIT_FORM),
            "book": State(Ids.CURRENT_BOOK, "data"),
            "tz_name": State(Ids.BROWSER_TZ, "data"),
            "books_version": State(Ids.BOOKS_VERSION, "data"),
        },
        running=[
            (Output(Ids.EDIT_SAVE, "disabled"), True, False),
            (Output(Ids.EDIT_SAVE_SPINNER, "style"), layout.SPINNER_VISIBLE, layout.SPINNER_HIDDEN),
        ],
        prevent_initial_call=True,
    )
    def save_book(
        n_clicks: int,
        title: str | None,
        author: str | None,
        publication_date: str | None,
        summary: str | None,
        created_date: str | None,
        created_time: str | None,
        book: dict[str, Any] | None,
        tz_name: str | None,
        books_version: int | None,
    ) -> dict[str, Any]:
        """Validate the Edit form and send only the changed fields to the API.

        Args:
            n_clicks: Clicks on Save (only used as a trigger).
            title: Title input value.
            author: Author input value.
            publication_date: Publication date input value.
            summary: Summary textarea value.
            created_date: "Created At" date (required when editing).
            created_time: "Created At" time.
            book: The book as it was when the form was opened.
            tz_name: Browser timezone, used to convert "Created At" to UTC.
            books_version: Counter bumped so the other screens reload.

        Returns:
            Values for every output: form feedback while editing; on success,
            the modal closes, a confirmation appears above the results and
            `books_version` is bumped.
        """
        stay_open: dict[str, Any] = {
            "edit_open": no_update,
            "action_alert": no_update,
            "current_book": no_update,
            "books_version": no_update,
        }
        if not book:
            return {
                "alert": layout.alert("Nenhum livro selecionado para edição."),
                **form_feedback({}),
                **stay_open,
            }

        form = services.BookForm(
            title, author, publication_date, summary, created_date, created_time
        )
        errors = services.validate_book_form(form, tz_name, require_created_at=True)
        if errors:
            return {
                "alert": layout.alert(
                    "Corrija os campos destacados.", "warning", "exclamation-circle"
                ),
                **form_feedback(errors),
                **stay_open,
            }

        payload = services.build_update_payload(form, tz_name, book)
        if not payload:
            return {
                "alert": None,
                **form_feedback({}),
                **stay_open,
                "edit_open": False,
                "action_alert": layout.alert(
                    "Nenhuma alteração para salvar.", "info", "info-circle"
                ),
            }

        try:
            updated = client.update_book(int(book["id"]), payload)
        except ApiValidationError as exc:
            logger.info("API rejected the edit: %s", exc.field_errors)
            extra = unmapped_errors(exc.field_errors)
            message = " ".join(["A API recusou alguns campos.", *extra])
            return {
                "alert": layout.alert(message, "warning", "exclamation-circle"),
                **form_feedback(exc.field_errors),
                **stay_open,
            }
        except ApiNotFoundError:
            # Someone else deleted it meanwhile: close and refresh the lists.
            return {
                "alert": None,
                **form_feedback({}),
                "edit_open": False,
                "action_alert": layout.alert(
                    "Este livro não existe mais.", "warning", "question-circle"
                ),
                "current_book": None,
                "books_version": (books_version or 0) + 1,
            }
        except ApiError as exc:
            logger.warning("Could not update book %s: %s", book.get("id"), exc)
            return {"alert": error_alert(exc), **form_feedback({}), **stay_open}

        return {
            "alert": None,
            **form_feedback({}),
            "edit_open": False,
            "action_alert": layout.alert(
                f'"{updated["title"]}" foi atualizado com sucesso.', "success", "check-circle"
            ),
            "current_book": dict(updated),
            "books_version": (books_version or 0) + 1,
        }

    # --- Delete Book ----------------------------------------------------------

    @app.callback(
        output={
            "delete_open": Output(Ids.DELETE_MODAL, "is_open"),
            "details_open": Output(Ids.DETAILS_MODAL, "is_open", allow_duplicate=True),
            "message": Output(Ids.DELETE_MESSAGE, "children"),
            "alert": Output(Ids.DELETE_ALERT, "children"),
        },
        inputs={
            "delete_clicks": Input(Ids.DETAILS_DELETE, "n_clicks"),
            "cancel_clicks": Input(Ids.DELETE_CANCEL, "n_clicks"),
        },
        state={"book": State(Ids.CURRENT_BOOK, "data")},
        prevent_initial_call=True,
    )
    def toggle_delete_confirmation(
        delete_clicks: int, cancel_clicks: int, book: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Ask for confirmation before deleting, or cancel back to details.

        Args:
            delete_clicks: Clicks on Delete in the details modal.
            cancel_clicks: Clicks on Cancel in the confirmation modal.
            book: The book shown in the details modal.

        Returns:
            Modal states and the confirmation text.
        """
        if ctx.triggered_id == Ids.DELETE_CANCEL or not book:
            return {
                "delete_open": False,
                "details_open": bool(book),
                "message": no_update,
                "alert": no_update,
            }
        return {
            "delete_open": True,
            "details_open": False,
            "message": layout.delete_message(book),
            "alert": None,
        }

    @app.callback(
        output={
            "delete_open": Output(Ids.DELETE_MODAL, "is_open", allow_duplicate=True),
            "alert": Output(Ids.DELETE_ALERT, "children", allow_duplicate=True),
            "action_alert": Output(Ids.BOOK_ACTION_ALERT, "children", allow_duplicate=True),
            "current_book": Output(Ids.CURRENT_BOOK, "data", allow_duplicate=True),
            "books_version": Output(Ids.BOOKS_VERSION, "data", allow_duplicate=True),
        },
        inputs={"n_clicks": Input(Ids.DELETE_CONFIRM, "n_clicks")},
        state={
            "book": State(Ids.CURRENT_BOOK, "data"),
            "books_version": State(Ids.BOOKS_VERSION, "data"),
        },
        running=[
            (Output(Ids.DELETE_CONFIRM, "disabled"), True, False),
            (Output(Ids.DELETE_SPINNER, "style"), layout.SPINNER_VISIBLE, layout.SPINNER_HIDDEN),
        ],
        prevent_initial_call=True,
    )
    def delete_book(
        n_clicks: int, book: dict[str, Any] | None, books_version: int | None
    ) -> dict[str, Any]:
        """Delete the current book after the user confirmed.

        Args:
            n_clicks: Clicks on the confirm button (only used as a trigger).
            book: The book to delete.
            books_version: Counter bumped so the other screens reload.

        Returns:
            Modal state, alerts and, on success, a bumped `books_version`.
        """
        if not book:
            return {
                "delete_open": False,
                "alert": no_update,
                "action_alert": no_update,
                "current_book": no_update,
                "books_version": no_update,
            }

        try:
            client.delete_book(int(book["id"]))
        except ApiNotFoundError:
            # Already gone: the outcome the user wanted, so just say so and refresh.
            message = layout.alert("Este livro já havia sido excluído.", "info", "info-circle")
        except ApiError as exc:
            logger.warning("Could not delete book %s: %s", book.get("id"), exc)
            return {
                "delete_open": no_update,
                "alert": error_alert(exc),
                "action_alert": no_update,
                "current_book": no_update,
                "books_version": no_update,
            }
        else:
            message = layout.alert(
                f'"{book.get("title")}" foi excluído.', "success", "check-circle"
            )

        return {
            "delete_open": False,
            "alert": None,
            "action_alert": message,
            "current_book": None,
            "books_version": (books_version or 0) + 1,
        }

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
