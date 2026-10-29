"""Smoke tests of the Dash app: layout rendering and callbacks over HTTP.

Callbacks are exercised through Dash's own `/_dash-update-component`
endpoint (the same request the browser sends), with the API mocked by respx.
"""

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx
from dash import Dash
from flask.testing import FlaskClient

from library_ui.api_client import BooksApiClient
from library_ui.app import create_app
from library_ui.config import Settings
from library_ui.layout import Ids

BASE_URL = "http://api.test"
BOOK: dict[str, Any] = {
    "id": 1,
    "title": "Dune",
    "author": "Frank Herbert",
    "publication_date": "1965-08-01",
    "summary": "Spice.",
    "created_at": "2026-10-28T14:30:00Z",
}


@pytest.fixture
def api() -> Iterator[respx.MockRouter]:
    """Intercept every HTTP request sent to the fake API."""
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as router:
        yield router


@pytest.fixture
def dash_app() -> Dash:
    """Build the app against the fake API."""
    settings = Settings(api_base_url=BASE_URL, search_page_size=2, api_max_page_size=100)
    return create_app(settings, BooksApiClient(BASE_URL, max_page_size=100))


@pytest.fixture
def http(dash_app: Dash) -> FlaskClient:
    """Provide a Flask test client for the Dash server."""
    return dash_app.server.test_client()


def call_callback(
    dash_app: Dash,
    http: FlaskClient,
    first_output: str,
    inputs: list[dict[str, Any]],
    state: list[dict[str, Any]] | None = None,
    changed: str | None = None,
) -> dict[str, Any]:
    """Invoke a server callback exactly as the browser would.

    Args:
        dash_app: The app (used to look up the callback's output spec).
        http: Flask test client.
        first_output: `id.prop` of the callback's first output. Outputs shared
            with another callback carry an `@<hash>` suffix; end with `@` to pick
            that callback instead of the one owning the plain output.
        inputs: Input values (`id`, `property`, `value`).
        state: State values.
        changed: `id.prop` that triggered the callback.

    Returns:
        The `response` section of Dash's answer, keyed by component id.
    """
    output_key = next(
        key for key in dash_app.callback_map if key.lstrip(".").startswith(first_output)
    )
    parts = [
        {"id": part.rsplit(".", 1)[0], "property": part.rsplit(".", 1)[1]}
        for part in output_key.strip(".").split("...")
    ]
    # Multi-output keys look like `..a.x...b.y..`; a single output is sent unwrapped.
    outputs: list[dict[str, str]] | dict[str, str] = (
        parts if output_key.startswith("..") else parts[0]
    )
    response = http.post(
        "/_dash-update-component",
        json={
            "output": output_key,
            "outputs": outputs,
            "inputs": inputs,
            "state": state or [],
            "changedPropIds": [changed] if changed else [],
        },
    )
    assert response.status_code == 200, response.data
    body: dict[str, Any] = response.get_json()["response"]
    return body


def test_index_and_layout_render(http: FlaskClient) -> None:
    """The page and its layout are served, branded and in Portuguese."""
    assert http.get("/").status_code == 200
    layout = http.get("/_dash-layout")

    assert layout.status_code == 200
    assert b"Biblioteca Virtual" in layout.data
    assert b"DOT Digital Group" in layout.data
    # The API address must never be shown to end users.
    assert BASE_URL.encode() not in layout.data
    assert Ids.RESULTS_TABLE.encode() in layout.data


def test_dashboard_callback_renders_cards(
    dash_app: Dash, http: FlaskClient, api: respx.MockRouter
) -> None:
    """The dashboard callback loads every book and renders the summary."""
    api.get("/books").mock(return_value=httpx.Response(200, json=[BOOK]))

    result = call_callback(
        dash_app,
        http,
        f"{Ids.DASHBOARD_CARDS}.children",
        inputs=[
            {"id": Ids.REFRESH_BUTTON, "property": "n_clicks", "value": 1},
            {"id": Ids.BOOKS_VERSION, "property": "data", "value": 0},
        ],
        changed=f"{Ids.REFRESH_BUTTON}.n_clicks",
    )

    assert "Dune" in str(result[Ids.DASHBOARD_CARDS])
    assert result[Ids.DASHBOARD_ALERT]["children"] is None


def test_dashboard_callback_shows_alert_when_api_is_down(
    dash_app: Dash, http: FlaskClient, api: respx.MockRouter
) -> None:
    """When the API is unreachable, the dashboard shows a connection alert."""
    api.get("/books").mock(side_effect=httpx.ConnectError("refused"))

    result = call_callback(
        dash_app,
        http,
        f"{Ids.DASHBOARD_CARDS}.children",
        inputs=[
            {"id": Ids.REFRESH_BUTTON, "property": "n_clicks", "value": 0},
            {"id": Ids.BOOKS_VERSION, "property": "data", "value": 0},
        ],
    )

    alert = str(result[Ids.DASHBOARD_ALERT])
    assert "Não foi possível conectar à API" in alert
    assert BASE_URL not in alert


def _search_inputs(**values: Any) -> list[dict[str, Any]]:
    """Build the inputs of the search callback with sensible defaults."""
    defaults: dict[str, tuple[str, str, Any]] = {
        "search": (Ids.SEARCH_BUTTON, "n_clicks", 0),
        "title_submit": (Ids.SEARCH_TITLE, "n_submit", 0),
        "author_submit": (Ids.SEARCH_AUTHOR, "n_submit", 0),
        "clear": (Ids.CLEAR_BUTTON, "n_clicks", 0),
        "previous": (Ids.PREVIOUS_PAGE, "n_clicks", 0),
        "next": (Ids.NEXT_PAGE, "n_clicks", 0),
        "tz": (Ids.BROWSER_TZ, "data", "UTC"),
        "version": (Ids.BOOKS_VERSION, "data", 0),
    }
    return [
        {"id": cid, "property": prop, "value": values.get(key, default)}
        for key, (cid, prop, default) in defaults.items()
    ]


def test_search_callback_requests_page_and_detects_next(
    dash_app: Dash, http: FlaskClient, api: respx.MockRouter
) -> None:
    """Searching sends the filters, over-fetches by one and enables "Next"."""
    route = api.get("/books").mock(
        return_value=httpx.Response(200, json=[BOOK, {**BOOK, "id": 2}, {**BOOK, "id": 3}])
    )

    result = call_callback(
        dash_app,
        http,
        f"{Ids.SEARCH_STATE}.data",
        inputs=_search_inputs(search=1),
        state=[
            {"id": Ids.SEARCH_TITLE, "property": "value", "value": "dune"},
            {"id": Ids.SEARCH_AUTHOR, "property": "value", "value": ""},
            {"id": Ids.SEARCH_STATE, "property": "data", "value": None},
        ],
        changed=f"{Ids.SEARCH_BUTTON}.n_clicks",
    )

    params = route.calls.last.request.url.params
    assert params["title"] == "dune"
    assert params["limit"] == "3"
    assert len(result[Ids.SEARCH_BOOKS]["data"]) == 2
    assert result[Ids.NEXT_PAGE]["disabled"] is False
    assert result[Ids.RESULT_COUNT]["children"] == "Exibindo livros 1–2"


def test_register_callback_validates_before_calling_api(
    dash_app: Dash, http: FlaskClient, api: respx.MockRouter
) -> None:
    """An empty form is rejected client-side and the API is never called."""
    route = api.post("/books")

    result = call_callback(
        dash_app,
        http,
        f"{Ids.REGISTER_ALERT}.children",
        inputs=[{"id": Ids.SUBMIT, "property": "n_clicks", "value": 1}],
        state=[
            {"id": Ids.TITLE, "property": "value", "value": ""},
            {"id": Ids.AUTHOR, "property": "value", "value": ""},
            {"id": Ids.PUBLICATION_DATE, "property": "value", "value": None},
            {"id": Ids.SUMMARY, "property": "value", "value": ""},
            {"id": Ids.CREATED_DATE, "property": "value", "value": None},
            {"id": Ids.CREATED_TIME, "property": "value", "value": None},
            {"id": Ids.BROWSER_TZ, "property": "data", "value": "UTC"},
            {"id": Ids.BOOKS_VERSION, "property": "data", "value": 0},
        ],
        changed=f"{Ids.SUBMIT}.n_clicks",
    )

    assert not route.called
    assert result[Ids.TITLE]["invalid"] is True
    assert result[Ids.TITLE_FEEDBACK]["children"] == "Informe o título."
    # The date field also gets the red border, not only the message.
    assert result[Ids.PUBLICATION_DATE]["invalid"] is True


def test_register_callback_accepts_typed_date(
    dash_app: Dash, http: FlaskClient, api: respx.MockRouter
) -> None:
    """A date typed in the native date input (sent as ISO) is accepted and submitted."""
    route = api.post("/books").mock(return_value=httpx.Response(201, json=BOOK))

    result = call_callback(
        dash_app,
        http,
        f"{Ids.REGISTER_ALERT}.children",
        inputs=[{"id": Ids.SUBMIT, "property": "n_clicks", "value": 1}],
        state=[
            {"id": Ids.TITLE, "property": "value", "value": "Dune"},
            {"id": Ids.AUTHOR, "property": "value", "value": "Frank Herbert"},
            {"id": Ids.PUBLICATION_DATE, "property": "value", "value": "2020-10-15"},
            {"id": Ids.SUMMARY, "property": "value", "value": ""},
            {"id": Ids.CREATED_DATE, "property": "value", "value": ""},
            {"id": Ids.CREATED_TIME, "property": "value", "value": ""},
            {"id": Ids.BROWSER_TZ, "property": "data", "value": "America/Sao_Paulo"},
            {"id": Ids.BOOKS_VERSION, "property": "data", "value": 0},
        ],
        changed=f"{Ids.SUBMIT}.n_clicks",
    )

    assert route.called
    assert b'"publication_date":"2020-10-15"' in route.calls.last.request.read().replace(b" ", b"")
    assert result[Ids.PUBLICATION_DATE]["value"] == ""  # form cleared after success
    assert "cadastrado com sucesso" in str(result[Ids.REGISTER_ALERT])


def _edit_state(book: dict[str, Any] | None, **values: Any) -> list[dict[str, Any]]:
    """Build the state of the save callback: the edit form plus context."""
    fields = {
        Ids.EDIT_TITLE: "Dune",
        Ids.EDIT_AUTHOR: "Frank Herbert",
        Ids.EDIT_PUBLICATION_DATE: "1965-08-01",
        Ids.EDIT_SUMMARY: "Spice.",
        Ids.EDIT_CREATED_DATE: "2026-10-28",
        Ids.EDIT_CREATED_TIME: "14:30",
    }
    fields.update(values)
    return [
        *({"id": cid, "property": "value", "value": value} for cid, value in fields.items()),
        {"id": Ids.CURRENT_BOOK, "property": "data", "value": book},
        {"id": Ids.BROWSER_TZ, "property": "data", "value": "UTC"},
        {"id": Ids.BOOKS_VERSION, "property": "data", "value": 3},
    ]


def test_details_enable_edit_and_delete_once_loaded(
    dash_app: Dash, http: FlaskClient, api: respx.MockRouter
) -> None:
    """Clicking a row loads the book and enables its Edit and Delete buttons."""
    api.get("/books/1").mock(return_value=httpx.Response(200, json=BOOK))

    result = call_callback(
        dash_app,
        http,
        f"{Ids.DETAILS_MODAL}.is_open",
        inputs=[
            {"id": Ids.RESULTS_TABLE, "property": "active_cell", "value": {"row_id": 1}},
            {"id": Ids.DETAILS_CLOSE, "property": "n_clicks", "value": 0},
        ],
        state=[{"id": Ids.BROWSER_TZ, "property": "data", "value": "UTC"}],
        changed=f"{Ids.RESULTS_TABLE}.active_cell",
    )

    assert result[Ids.CURRENT_BOOK]["data"] == BOOK
    assert result[Ids.DETAILS_EDIT]["disabled"] is False
    assert result[Ids.DETAILS_DELETE]["disabled"] is False


def test_edit_button_opens_form_filled_with_book(dash_app: Dash, http: FlaskClient) -> None:
    """Edit swaps the details modal for the edit form, pre-filled in local time."""
    result = call_callback(
        dash_app,
        http,
        f"{Ids.EDIT_MODAL}.is_open",
        inputs=[
            {"id": Ids.DETAILS_EDIT, "property": "n_clicks", "value": 1},
            {"id": Ids.EDIT_CANCEL, "property": "n_clicks", "value": 0},
        ],
        state=[
            {"id": Ids.CURRENT_BOOK, "property": "data", "value": BOOK},
            {"id": Ids.BROWSER_TZ, "property": "data", "value": "America/Sao_Paulo"},
        ],
        changed=f"{Ids.DETAILS_EDIT}.n_clicks",
    )

    assert result[Ids.EDIT_MODAL]["is_open"] is True
    assert result[Ids.DETAILS_MODAL]["is_open"] is False
    assert result[Ids.EDIT_TITLE]["value"] == "Dune"
    assert result[Ids.EDIT_CREATED_DATE]["value"] == "2026-10-28"
    assert result[Ids.EDIT_CREATED_TIME]["value"] == "11:30"


def test_save_edit_sends_changed_fields_and_refreshes(
    dash_app: Dash, http: FlaskClient, api: respx.MockRouter
) -> None:
    """Saving PATCHes only what changed, closes the modal and bumps `books_version`."""
    route = api.patch("/books/1").mock(
        return_value=httpx.Response(200, json={**BOOK, "title": "Dune Messiah"})
    )

    result = call_callback(
        dash_app,
        http,
        f"{Ids.EDIT_ALERT}.children",
        inputs=[{"id": Ids.EDIT_SAVE, "property": "n_clicks", "value": 1}],
        state=_edit_state(BOOK, **{Ids.EDIT_TITLE: "Dune Messiah"}),
        changed=f"{Ids.EDIT_SAVE}.n_clicks",
    )

    assert route.calls.last.request.read() == b'{"title":"Dune Messiah"}'
    assert result[Ids.EDIT_MODAL]["is_open"] is False
    assert result[Ids.BOOKS_VERSION]["data"] == 4
    assert "atualizado com sucesso" in str(result[Ids.BOOK_ACTION_ALERT])


def test_save_edit_validates_before_calling_api(
    dash_app: Dash, http: FlaskClient, api: respx.MockRouter
) -> None:
    """A blank title is flagged on the edit form and the API is not called."""
    route = api.patch("/books/1")

    result = call_callback(
        dash_app,
        http,
        f"{Ids.EDIT_ALERT}.children",
        inputs=[{"id": Ids.EDIT_SAVE, "property": "n_clicks", "value": 1}],
        state=_edit_state(BOOK, **{Ids.EDIT_TITLE: "  "}),
        changed=f"{Ids.EDIT_SAVE}.n_clicks",
    )

    assert not route.called
    assert result[Ids.EDIT_TITLE]["invalid"] is True
    assert Ids.EDIT_MODAL not in result  # stays open


def test_delete_asks_for_confirmation(dash_app: Dash, http: FlaskClient) -> None:
    """Delete opens a confirmation naming the book instead of deleting right away."""
    result = call_callback(
        dash_app,
        http,
        f"{Ids.DELETE_MODAL}.is_open",
        inputs=[
            {"id": Ids.DETAILS_DELETE, "property": "n_clicks", "value": 1},
            {"id": Ids.DELETE_CANCEL, "property": "n_clicks", "value": 0},
        ],
        state=[{"id": Ids.CURRENT_BOOK, "property": "data", "value": BOOK}],
        changed=f"{Ids.DETAILS_DELETE}.n_clicks",
    )

    assert result[Ids.DELETE_MODAL]["is_open"] is True
    assert result[Ids.DETAILS_MODAL]["is_open"] is False
    assert "Dune" in str(result[Ids.DELETE_MESSAGE])


def test_confirm_delete_removes_book_and_refreshes(
    dash_app: Dash, http: FlaskClient, api: respx.MockRouter
) -> None:
    """Confirming sends DELETE, closes the modal and bumps `books_version`."""
    route = api.delete("/books/1").mock(return_value=httpx.Response(204))

    result = call_callback(
        dash_app,
        http,
        f"{Ids.DELETE_MODAL}.is_open@",
        inputs=[{"id": Ids.DELETE_CONFIRM, "property": "n_clicks", "value": 1}],
        state=[
            {"id": Ids.CURRENT_BOOK, "property": "data", "value": BOOK},
            {"id": Ids.BOOKS_VERSION, "property": "data", "value": 3},
        ],
        changed=f"{Ids.DELETE_CONFIRM}.n_clicks",
    )

    assert route.called
    assert result[Ids.DELETE_MODAL]["is_open"] is False
    assert result[Ids.BOOKS_VERSION]["data"] == 4
    assert result[Ids.CURRENT_BOOK]["data"] is None
    assert "foi excluído" in str(result[Ids.BOOK_ACTION_ALERT])


def test_form_feedback_uses_invalid_style(http: FlaskClient) -> None:
    """Inline errors use Bootstrap's red "invalid" style and dates are native inputs."""
    layout = http.get("/_dash-layout").get_json()
    text = str(layout)

    assert "'type': 'invalid'" in text
    assert "'type': 'date'" in text


def test_postman_button_downloads_collection(http: FlaskClient) -> None:
    """The navbar button returns the collection pointed at the configured API."""
    dash_app = create_app(
        Settings(
            api_base_url="http://api:8000",
            api_key="demo-key",
            public_api_url="https://api.example",
            postman_include_api_key=True,
        ),
        BooksApiClient(BASE_URL),
    )

    result = call_callback(
        dash_app,
        dash_app.server.test_client(),
        f"{Ids.POSTMAN_DOWNLOAD}.data",
        inputs=[{"id": Ids.POSTMAN_BUTTON, "property": "n_clicks", "value": 1}],
        changed=f"{Ids.POSTMAN_BUTTON}.n_clicks",
    )

    download = result[Ids.POSTMAN_DOWNLOAD]["data"]
    assert download["filename"] == "library-api.postman_collection.json"
    assert '"value": "https://api.example"' in download["content"]
    assert '"value": "demo-key"' in download["content"]
