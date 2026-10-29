"""Page layout and reusable UI components.

Component ids live in `Ids` so layout and callbacks reference the same
constants, and a typo becomes an `AttributeError` instead of a silent bug.
"""

from collections.abc import Mapping
from typing import Any

import dash_bootstrap_components as dbc
from dash import dash_table, dcc, html
from dash.development.base_component import Component

from library_ui import services


class Ids:
    """Ids of every Dash component referenced by a callback."""

    ROOT = "app-root"
    BROWSER_TZ = "browser-timezone"
    BOOKS_VERSION = "books-version"
    TABS = "main-tabs"

    # Register Book
    REGISTER_ALERT = "register-alert"
    TITLE = "register-title"
    TITLE_FEEDBACK = "register-title-feedback"
    AUTHOR = "register-author"
    AUTHOR_FEEDBACK = "register-author-feedback"
    PUBLICATION_DATE = "register-publication-date"
    PUBLICATION_DATE_FEEDBACK = "register-publication-date-feedback"
    SUMMARY = "register-summary"
    SUMMARY_FEEDBACK = "register-summary-feedback"
    CREATED_DATE = "register-created-date"
    CREATED_TIME = "register-created-time"
    CREATED_AT_FEEDBACK = "register-created-at-feedback"
    SUBMIT = "register-submit"
    SUBMIT_SPINNER = "register-submit-spinner"

    # Search Books
    SEARCH_TITLE = "search-title"
    SEARCH_AUTHOR = "search-author"
    SEARCH_BUTTON = "search-button"
    CLEAR_BUTTON = "search-clear"
    SEARCH_ALERT = "search-alert"
    SEARCH_STATE = "search-state"
    SEARCH_BOOKS = "search-books"
    SEARCH_RESULTS = "search-results"
    RESULT_COUNT = "search-result-count"
    RESULTS_TABLE = "search-results-table"
    EMPTY_RESULTS = "search-empty"
    PREVIOUS_PAGE = "search-previous"
    NEXT_PAGE = "search-next"
    PAGE_LABEL = "search-page-label"

    # Book details modal
    DETAILS_MODAL = "details-modal"
    DETAILS_TITLE = "details-title"
    DETAILS_BODY = "details-body"
    DETAILS_CLOSE = "details-close"

    # Dashboard
    REFRESH_BUTTON = "dashboard-refresh"
    DASHBOARD_ALERT = "dashboard-alert"
    DASHBOARD_CARDS = "dashboard-cards"
    DASHBOARD_CHARTS = "dashboard-charts"


TAB_REGISTER = "tab-register"
TAB_SEARCH = "tab-search"
TAB_DASHBOARD = "tab-dashboard"

SPINNER_VISIBLE: dict[str, str] = {"display": "inline-block"}
SPINNER_HIDDEN: dict[str, str] = {"display": "none"}

APP_NAME = "Biblioteca Virtual"
CLIENT_NAME = "DOT Digital Group"


def icon(name: str, class_name: str = "me-2") -> html.I:
    """Return a Bootstrap Icons glyph.

    Args:
        name: Icon name without the `bi-` prefix (e.g. `search`).
        class_name: Extra CSS classes, spacing by default.

    Returns:
        The icon element.
    """
    # Icons are decorative: every one sits next to a text label.
    attributes: dict[str, Any] = {"aria-hidden": "true"}
    return html.I(className=f"bi bi-{name} {class_name}".strip(), **attributes)


# --- Alerts and small building blocks ---------------------------------------


def alert(
    message: str, color: str = "danger", icon_name: str = "exclamation-triangle"
) -> dbc.Alert:
    """Build a dismissable alert.

    Args:
        message: Text shown to the user.
        color: Bootstrap color (`success`, `danger`, `warning`, ...).
        icon_name: Bootstrap Icons name shown before the text.

    Returns:
        The alert component.
    """
    return dbc.Alert(
        [icon(icon_name), message], color=color, dismissable=True, className="shadow-sm mb-3"
    )


def empty_state(title: str, message: str, icon_name: str = "inbox") -> html.Div:
    """Build a friendly placeholder for screens without data.

    Args:
        title: Headline.
        message: Supporting text.
        icon_name: Bootstrap Icons name.

    Returns:
        The empty state component.
    """
    return html.Div(
        [
            icon(icon_name, "empty-state-icon"),
            html.H5(title, className="mt-3 mb-1"),
            html.P(message, className="text-muted mb-0"),
        ],
        className="empty-state text-center",
    )


def _form_field(
    label: str, control: Component, feedback_id: str, help_text: str | None = None
) -> html.Div:
    """Wrap a form control with its label, help text and inline error.

    Args:
        label: Field label.
        control: The input component.
        feedback_id: Id of the inline error element.
        help_text: Optional help text under the control.

    Returns:
        The field group.
    """
    children: list[Component] = [dbc.Label(label, className="fw-semibold"), control]
    if help_text:
        children.append(dbc.FormText(help_text))
    # `type="invalid"` gives the red error style (without it dbc renders the green
    # "valid" style). `d-block` keeps the message visible even when it is not a
    # direct sibling of the invalid input (e.g. the date + time pair); an empty
    # message simply renders nothing.
    children.append(dbc.FormFeedback(id=feedback_id, type="invalid", className="d-block"))
    return html.Div(children, className="mb-3")


# --- Register Book ------------------------------------------------------------


def register_tab() -> dbc.Container:
    """Build the Register Book screen.

    Returns:
        The tab content.
    """
    today = services.utc_today().isoformat()
    form = dbc.Form(
        [
            dbc.Row(
                [
                    dbc.Col(
                        _form_field(
                            "Título",
                            dbc.Input(id=Ids.TITLE, placeholder="Ex.: Duna", maxLength=255),
                            Ids.TITLE_FEEDBACK,
                        ),
                        xs=12,
                        md=6,
                    ),
                    dbc.Col(
                        _form_field(
                            "Autor",
                            dbc.Input(
                                id=Ids.AUTHOR, placeholder="Ex.: Frank Herbert", maxLength=255
                            ),
                            Ids.AUTHOR_FEEDBACK,
                        ),
                        xs=12,
                        md=6,
                    ),
                ]
            ),
            dbc.Row(
                [
                    dbc.Col(
                        _form_field(
                            "Data de publicação",
                            # Native date input instead of dcc.DatePickerSingle: the user
                            # can type the date directly (DD/MM/AAAA in a pt-BR browser),
                            # the calendar follows the browser language and the value is
                            # always ISO (YYYY-MM-DD). `max` blocks future dates in the
                            # calendar; typed dates are validated again on submit.
                            dbc.Input(
                                id=Ids.PUBLICATION_DATE,
                                type="date",
                                max=today,
                                className="date-input",
                            ),
                            Ids.PUBLICATION_DATE_FEEDBACK,
                        ),
                        xs=12,
                        md=6,
                    ),
                    dbc.Col(
                        _form_field(
                            "Data de cadastro (opcional)",
                            html.Div(
                                [
                                    dbc.Input(
                                        id=Ids.CREATED_DATE,
                                        type="date",
                                        max=today,
                                        className="date-input",
                                    ),
                                    dbc.Input(
                                        id=Ids.CREATED_TIME, type="time", className="time-input"
                                    ),
                                ],
                                className="d-flex gap-2",
                            ),
                            Ids.CREATED_AT_FEEDBACK,
                            help_text="Deixe em branco para usar a data e hora atuais",
                        ),
                        xs=12,
                        md=6,
                    ),
                ]
            ),
            _form_field(
                "Resumo",
                dbc.Textarea(
                    id=Ids.SUMMARY,
                    placeholder="Sobre o que é este livro?",
                    # Same cap as the API, so the user cannot type more than it accepts.
                    maxLength=services.MAX_SUMMARY_LENGTH,
                    rows=5,
                    style={"resize": "vertical"},
                ),
                Ids.SUMMARY_FEEDBACK,
            ),
            html.Div(
                dbc.Button(
                    [
                        html.Span(
                            id=Ids.SUBMIT_SPINNER,
                            className="spinner-border spinner-border-sm me-2",
                            style=SPINNER_HIDDEN,
                        ),
                        icon("plus-circle"),
                        "Cadastrar livro",
                    ],
                    id=Ids.SUBMIT,
                    color="primary",
                    n_clicks=0,
                    className="px-4",
                ),
                className="d-flex justify-content-end",
            ),
        ]
    )
    return dbc.Container(
        [
            html.Div(id=Ids.REGISTER_ALERT),
            dbc.Card(
                dbc.CardBody(
                    [
                        html.H4(
                            [icon("journal-plus"), "Cadastrar um novo livro"], className="mb-1"
                        ),
                        html.P(
                            "Preencha os dados abaixo para adicionar um livro à biblioteca.",
                            className="text-muted mb-4",
                        ),
                        form,
                    ]
                ),
                className="shadow-sm border-0",
            ),
        ],
        fluid=True,
        className="px-0",
    )


# --- Search Books -------------------------------------------------------------


TABLE_COLUMNS = [
    {"name": "Título", "id": services.FIELD_TITLE},
    {"name": "Autor", "id": services.FIELD_AUTHOR},
    {"name": "Publicação", "id": services.FIELD_PUBLICATION_DATE},
    {"name": "Cadastro", "id": services.FIELD_CREATED_AT},
    {"name": "Resumo", "id": services.FIELD_SUMMARY},
]


def search_tab() -> dbc.Container:
    """Build the Search Books screen.

    Returns:
        The tab content.
    """
    filters = dbc.Card(
        dbc.CardBody(
            dbc.Row(
                [
                    dbc.Col(
                        dbc.InputGroup(
                            [
                                dbc.InputGroupText(icon("type", "")),
                                dbc.Input(
                                    id=Ids.SEARCH_TITLE,
                                    placeholder="Título contém…",
                                    debounce=True,
                                    n_submit=0,
                                ),
                            ]
                        ),
                        xs=12,
                        md=5,
                    ),
                    dbc.Col(
                        dbc.InputGroup(
                            [
                                dbc.InputGroupText(icon("person", "")),
                                dbc.Input(
                                    id=Ids.SEARCH_AUTHOR,
                                    placeholder="Autor contém…",
                                    debounce=True,
                                    n_submit=0,
                                ),
                            ]
                        ),
                        xs=12,
                        md=4,
                    ),
                    dbc.Col(
                        html.Div(
                            [
                                dbc.Button(
                                    [icon("search"), "Buscar"],
                                    id=Ids.SEARCH_BUTTON,
                                    color="primary",
                                    n_clicks=0,
                                    className="flex-fill",
                                ),
                                dbc.Button(
                                    [icon("x-circle"), "Limpar"],
                                    id=Ids.CLEAR_BUTTON,
                                    color="secondary",
                                    outline=True,
                                    n_clicks=0,
                                    className="flex-fill",
                                ),
                            ],
                            className="d-flex gap-2",
                        ),
                        xs=12,
                        md=3,
                    ),
                ],
                className="g-2",
            )
        ),
        className="shadow-sm border-0 mb-3",
    )

    table = dash_table.DataTable(  # type: ignore[attr-defined]
        id=Ids.RESULTS_TABLE,
        columns=TABLE_COLUMNS,
        data=[],
        # Custom sorting: rows are sorted on raw ISO values in a callback,
        # because sorting formatted dates as text would be wrong.
        sort_action="custom",
        sort_mode="single",
        sort_by=[],
        cell_selectable=True,
        style_as_list_view=True,
        style_table={"overflowX": "auto"},
        style_header={
            "backgroundColor": "#f8f9fa",
            "fontWeight": "700",
            "borderBottom": "2px solid #dee2e6",
            "textTransform": "uppercase",
            "fontSize": "0.75rem",
            "letterSpacing": "0.04em",
        },
        style_cell={
            "textAlign": "left",
            "padding": "12px 14px",
            "fontFamily": "inherit",
            "fontSize": "0.95rem",
            "whiteSpace": "normal",
            "height": "auto",
            "cursor": "pointer",
            "border": "none",
            "borderBottom": "1px solid #eef0f2",
        },
        style_cell_conditional=[
            {"if": {"column_id": services.FIELD_TITLE}, "fontWeight": "600", "minWidth": "180px"},
            {"if": {"column_id": services.FIELD_SUMMARY}, "minWidth": "240px", "color": "#6c757d"},
            {"if": {"column_id": services.FIELD_PUBLICATION_DATE}, "whiteSpace": "nowrap"},
            {"if": {"column_id": services.FIELD_CREATED_AT}, "whiteSpace": "nowrap"},
        ],
        style_data_conditional=[
            {"if": {"state": "active"}, "backgroundColor": "#e8f6f3", "border": "none"},
            {"if": {"state": "selected"}, "backgroundColor": "#e8f6f3", "border": "none"},
        ],
    )

    results = dbc.Card(
        dbc.CardBody(
            [
                html.Div(
                    [
                        html.Span(id=Ids.RESULT_COUNT, className="fw-semibold"),
                        html.Small(
                            [
                                icon("hand-index", "me-1"),
                                "Clique em uma linha para ver os detalhes",
                            ],
                            className="text-muted d-none d-md-inline",
                        ),
                    ],
                    className="d-flex justify-content-between align-items-center mb-2",
                ),
                html.Div(table, id=Ids.SEARCH_RESULTS),
                html.Div(
                    empty_state(
                        "Nenhum livro encontrado",
                        "Tente outro título ou autor, ou limpe os filtros.",
                        "search",
                    ),
                    id=Ids.EMPTY_RESULTS,
                    style={"display": "none"},
                ),
                html.Div(
                    [
                        dbc.Button(
                            [icon("chevron-left", "me-1"), "Anterior"],
                            id=Ids.PREVIOUS_PAGE,
                            color="secondary",
                            outline=True,
                            size="sm",
                            n_clicks=0,
                            disabled=True,
                        ),
                        html.Span(id=Ids.PAGE_LABEL, className="text-muted small"),
                        dbc.Button(
                            ["Próxima", icon("chevron-right", "ms-1")],
                            id=Ids.NEXT_PAGE,
                            color="secondary",
                            outline=True,
                            size="sm",
                            n_clicks=0,
                            disabled=True,
                        ),
                    ],
                    className="d-flex justify-content-between align-items-center mt-3",
                ),
            ]
        ),
        className="shadow-sm border-0",
    )

    return dbc.Container(
        [
            filters,
            html.Div(id=Ids.SEARCH_ALERT),
            dcc.Loading(results, type="default", delay_show=150),
        ],
        fluid=True,
        className="px-0",
    )


def book_details(book: Mapping[str, Any], tz_name: str | None) -> list[Component]:
    """Build the body of the book details modal.

    Args:
        book: The book returned by `GET /books/{id}`.
        tz_name: IANA timezone of the user.

    Returns:
        The modal body children.
    """

    def item(label: str, value: str, icon_name: str) -> dbc.Col:
        return dbc.Col(
            html.Div(
                [
                    html.Div([icon(icon_name, "me-1"), label], className="detail-label"),
                    html.Div(value, className="detail-value"),
                ]
            ),
            xs=12,
            sm=6,
            className="mb-3",
        )

    summary = book.get(services.FIELD_SUMMARY) or ""
    return [
        dbc.Row(
            [
                item("Autor", str(book.get(services.FIELD_AUTHOR, "")), "person"),
                item(
                    "Data de publicação",
                    services.format_date(book.get(services.FIELD_PUBLICATION_DATE)),
                    "calendar-event",
                ),
                item(
                    "Data de cadastro",
                    services.format_datetime(book.get(services.FIELD_CREATED_AT), tz_name),
                    "clock-history",
                ),
                item("ID do livro", f"#{book.get('id')}", "hash"),
            ]
        ),
        html.Div([icon("card-text", "me-1"), "Resumo"], className="detail-label"),
        html.P(
            summary or "Nenhum resumo informado.",
            className="detail-summary" if summary else "detail-summary text-muted fst-italic",
        ),
    ]


def details_modal() -> dbc.Modal:
    """Build the (initially closed) book details modal.

    Returns:
        The modal component.
    """
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle(id=Ids.DETAILS_TITLE)),
            dbc.ModalBody(dcc.Loading(html.Div(id=Ids.DETAILS_BODY), type="dot")),
            dbc.ModalFooter(
                dbc.Button("Fechar", id=Ids.DETAILS_CLOSE, color="secondary", n_clicks=0)
            ),
        ],
        id=Ids.DETAILS_MODAL,
        is_open=False,
        centered=True,
        scrollable=True,
        size="lg",
    )


# --- Dashboard ----------------------------------------------------------------


def _stat_card(label: str, value: str, caption: str, icon_name: str) -> dbc.Col:
    """Build one summary card.

    Args:
        label: Card label.
        value: Main value.
        caption: Secondary text below the value.
        icon_name: Bootstrap Icons name.

    Returns:
        The card in a responsive column.
    """
    return dbc.Col(
        dbc.Card(
            dbc.CardBody(
                [
                    html.Div(
                        [html.Span(label, className="stat-label"), icon(icon_name, "stat-icon")],
                        className="d-flex justify-content-between align-items-start",
                    ),
                    html.Div(value, className="stat-value", title=value),
                    html.Div(caption, className="text-muted small"),
                ]
            ),
            className="shadow-sm border-0 h-100",
        ),
        xs=12,
        sm=6,
        xl=3,
        className="mb-3",
    )


def summary_cards(summary: services.LibrarySummary) -> dbc.Row:
    """Build the dashboard summary cards.

    Args:
        summary: Figures computed by `services.compute_summary`.

    Returns:
        A row with four cards.
    """

    def book_card(label: str, book: Mapping[str, Any] | None, icon_name: str) -> dbc.Col:
        if book is None:
            return _stat_card(label, services.EMPTY_VALUE, "", icon_name)
        caption = (
            f"{book.get(services.FIELD_AUTHOR)} · "
            f"{services.format_date(book.get(services.FIELD_PUBLICATION_DATE))}"
        )
        return _stat_card(label, str(book.get(services.FIELD_TITLE)), caption, icon_name)

    return dbc.Row(
        [
            _stat_card(
                "Total de livros",
                services.format_count(summary.total_books),
                "Na biblioteca",
                "book",
            ),
            _stat_card(
                "Autores distintos",
                services.format_count(summary.total_authors),
                "Nomes únicos",
                "people",
            ),
            book_card("Livro mais antigo", summary.oldest_book, "hourglass-bottom"),
            book_card("Livro mais recente", summary.newest_book, "stars"),
        ]
    )


def chart_cards(books_per_year: Any, top_authors: Any) -> dbc.Row:
    """Build the two dashboard chart cards.

    Args:
        books_per_year: Plotly figure of books per publication year.
        top_authors: Plotly figure of the top authors.

    Returns:
        A row with both charts.
    """

    def chart(title: str, figure: Any) -> dbc.Col:
        return dbc.Col(
            dbc.Card(
                dbc.CardBody(
                    [
                        html.H6(title, className="mb-3 fw-bold"),
                        dcc.Graph(
                            figure=figure,
                            config={"displayModeBar": False, "responsive": True},
                            style={"height": "360px"},
                        ),
                    ]
                ),
                className="shadow-sm border-0 h-100",
            ),
            xs=12,
            lg=6,
            className="mb-3",
        )

    return dbc.Row(
        [
            chart("Livros por ano de publicação", books_per_year),
            chart("Top 10 autores", top_authors),
        ]
    )


def dashboard_tab() -> dbc.Container:
    """Build the Dashboard screen.

    Returns:
        The tab content.
    """
    return dbc.Container(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.H4(
                                [icon("bar-chart-line"), "Visão geral da biblioteca"],
                                className="mb-0",
                            ),
                            html.Small(
                                "Estatísticas calculadas com todos os livros cadastrados.",
                                className="text-muted",
                            ),
                        ]
                    ),
                    dbc.Button(
                        [icon("arrow-clockwise"), "Atualizar"],
                        id=Ids.REFRESH_BUTTON,
                        color="primary",
                        outline=True,
                        n_clicks=0,
                    ),
                ],
                className="d-flex flex-wrap gap-2 justify-content-between align-items-center mb-3",
            ),
            html.Div(id=Ids.DASHBOARD_ALERT),
            dcc.Loading(
                html.Div([html.Div(id=Ids.DASHBOARD_CARDS), html.Div(id=Ids.DASHBOARD_CHARTS)]),
                type="default",
                delay_show=150,
            ),
        ],
        fluid=True,
        className="px-0",
    )


# --- Page ---------------------------------------------------------------------


def navbar() -> dbc.Navbar:
    """Build the top navigation bar with the app and client names.

    The API URL is intentionally not shown to end users.

    Returns:
        The navbar.
    """
    return dbc.Navbar(
        dbc.Container(
            [
                dbc.NavbarBrand(
                    [
                        icon("book-half"),
                        html.Span(APP_NAME, className="fw-bold"),
                        html.Span(f"para {CLIENT_NAME}", className="brand-client"),
                    ],
                    className="d-flex align-items-center fs-4",
                ),
            ],
            fluid="lg",
        ),
        color="primary",
        dark=True,
        className="mb-4 shadow-sm",
    )


def build_layout() -> html.Div:
    """Build the whole page.

    The layout is rebuilt on every page load (see `app.py`), so the date
    pickers' `max_date_allowed` always reflects the current day.

    Returns:
        The root component.
    """
    return html.Div(
        [
            # Client-side state shared between callbacks.
            dcc.Store(id=Ids.BROWSER_TZ),
            dcc.Store(id=Ids.BOOKS_VERSION, data=0),
            dcc.Store(id=Ids.SEARCH_STATE, data=services.SearchState().to_dict()),
            dcc.Store(id=Ids.SEARCH_BOOKS, data=[]),
            navbar(),
            dbc.Container(
                [
                    dbc.Tabs(
                        [
                            dbc.Tab(register_tab(), label="Cadastrar livro", tab_id=TAB_REGISTER),
                            dbc.Tab(search_tab(), label="Buscar livros", tab_id=TAB_SEARCH),
                            dbc.Tab(dashboard_tab(), label="Painel", tab_id=TAB_DASHBOARD),
                        ],
                        id=Ids.TABS,
                        active_tab=TAB_REGISTER,
                        className="mb-4 nav-tabs-modern",
                    ),
                    details_modal(),
                    html.Footer(
                        [
                            html.Div(
                                [
                                    f"{APP_NAME} · desenvolvido para a ",
                                    html.Strong(CLIENT_NAME),
                                ]
                            ),
                            html.Div(
                                "Interface em Plotly Dash integrada à Library API (FastAPI)",
                                className="mt-1",
                            ),
                        ],
                        className="text-center text-muted small py-4",
                    ),
                ],
                fluid="lg",
            ),
        ],
        id=Ids.ROOT,
    )
