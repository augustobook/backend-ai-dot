"""Dash web interface: search box, filters, result cards and pipeline comparison.

The models and the index are loaded once per process, when the server is created
(`create_server`), and never inside a callback: loading takes seconds and hundreds
of MB, while a search only needs the objects already in memory. Nothing is loaded
at import time, so the tests can build the app with the fake models.

Run locally with `uv run python -m app.ui.dash_app`. In Docker, gunicorn calls the
`create_server()` factory with one worker: each worker is a separate process that
would load its own copy of both models, so concurrency comes from threads instead.
"""

import logging
from collections.abc import Mapping
from typing import Any

import dash_bootstrap_components as dbc
from dash import ALL, Dash, Input, Output, State, ctx, dcc, html, no_update
from dash.development.base_component import Component
from flask import Flask

from app.core.config import Settings, get_settings
from app.core.exceptions import (
    DocumentNotFoundError,
    EmbeddingModelMismatchError,
    IndexCorruptedError,
    IndexNotFoundError,
)
from app.core.logging import configure_logging
from app.services.factory import build_search_service
from app.services.search_service import SearchService
from app.ui import components, library

logger = logging.getLogger(__name__)

EXAMPLE_BUTTON_TYPE = "example-query"
SEARCH_TAB = "search"
LIBRARY_TAB = "library"
# Components whose events mean "search now", even with an empty query (which then
# shows the validation message). A change of any other control only re-runs a
# search that already has a query.
EXPLICIT_TRIGGERS = ("search-button", "query")
MODE_OPTIONS = [
    {"label": "Híbrida", "value": "hybrid"},
    {"label": "Semântica", "value": "semantic"},
    {"label": "Palavras-chave", "value": "keyword"},
]
LOCAL_PORT = 8065
PRIMARY_COLOR = "#0f6e8c"  # Same as --ss-primary in assets/style.css.

# Dash's default page, with the document language set to Portuguese (screen readers
# and the browser's spell checker use it).
INDEX_STRING = """<!DOCTYPE html>
<html lang="pt-BR">
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>"""


def load_search_service(settings: Settings) -> tuple[SearchService | None, str | None]:
    """Load the index and the models, without failing when the index is missing.

    The interface must start even before the ingestion ran, to tell the user how to
    build the index instead of crashing with a stack trace.

    Args:
        settings: Application settings.

    Returns:
        The search service and None, or None and the reason it could not be loaded.
    """
    try:
        service = build_search_service(settings)
    except (IndexNotFoundError, IndexCorruptedError, EmbeddingModelMismatchError) as exc:
        logger.warning("Search interface started without an index: %s", exc)
        return None, str(exc)

    # Warm-up: the first forward pass of a model is much slower than the next ones
    # (lazy allocations, thread pools), so it is paid here instead of by the first user.
    service.search("warm-up", top_k=1)
    logger.info("Search service loaded and warmed up")
    return service, None


def resolve_query(triggered_id: str | Mapping[str, Any] | None, typed: str | None) -> str | None:
    """Decide which query a callback should run, given what triggered it.

    Args:
        triggered_id: Id of the component that fired the callback (a dict for the
            pattern-matching example buttons).
        typed: Current text of the search box.

    Returns:
        The query to run, or None when nothing should be searched.
    """
    if isinstance(triggered_id, Mapping) and triggered_id.get("type") == EXAMPLE_BUTTON_TYPE:
        return components.EXAMPLE_QUERIES[int(triggered_id["index"])]
    if triggered_id in EXPLICIT_TRIGGERS:
        return typed or ""
    # A filter or toggle changed: refresh the results only if there is a query.
    if typed and typed.strip():
        return typed
    return None


def create_app(
    settings: Settings, service: SearchService | None, load_error: str | None = None
) -> Dash:
    """Build the Dash application around an already loaded search service.

    Args:
        settings: Application settings (defaults and limits of the controls).
        service: The search service, or None when the index could not be loaded.
        load_error: Why the service could not be loaded.

    Returns:
        The Dash application.
    """
    app = Dash(
        __name__,
        external_stylesheets=[dbc.themes.BOOTSTRAP],
        title="Busca Semântica em Saúde",
        # The results area and the controls only exist when an index is loaded.
        suppress_callback_exceptions=True,
    )
    app.index_string = INDEX_STRING
    app.layout = _layout(settings, service, load_error)
    if service is not None:
        _register_callbacks(app, service)
    return app


def _layout(settings: Settings, service: SearchService | None, load_error: str | None) -> Component:
    """Build the page: header, search and results, and a side panel about the index.

    Args:
        settings: Application settings.
        service: The search service, or None.
        load_error: Why the service could not be loaded.

    Returns:
        The root component.
    """
    if service is None:
        main: list[Component] = [
            components.index_missing_alert(load_error or "O índice não pôde ser carregado.")
        ]
        side = [components.stats_panel(None, None), components.how_it_works_panel()]
    else:
        main = [
            _controls(settings, service),
            dcc.Loading(
                html.Div(components.empty_state(), id="results"),
                type="circle",
                color=PRIMARY_COLOR,
                # Keep the previous results visible under the spinner while searching.
                overlay_style={"visibility": "visible", "opacity": 0.5},
            ),
        ]
        side = [
            components.stats_panel(
                service.manifest, service.reranker_model, service.query_rewriter_model
            ),
            components.how_it_works_panel(),
        ]

    disclaimer = html.P(
        "Artigos da Wikipédia em português, licença CC BY-SA 4.0. Conteúdo enciclopédico "
        "usado para demonstrar busca de informação; não é orientação médica.",
        className="ss-disclaimer",
    )
    search_section = dbc.Row(
        [
            dbc.Col(main, lg=8, xl=9, className="mb-4"),
            dbc.Col([*side, disclaimer], lg=4, xl=3),
        ]
    )
    if service is None:
        body: list[Component] = [search_section]
    else:
        # The tabs only navigate: both sections stay in the page and are shown or
        # hidden, so switching tabs never discards the search results.
        body = [
            dbc.Tabs(
                [
                    dbc.Tab(label="Busca", tab_id=SEARCH_TAB),
                    dbc.Tab(label="Acervo", tab_id=LIBRARY_TAB),
                ],
                id="main-tabs",
                active_tab=SEARCH_TAB,
                className="ss-tabs mb-4",
            ),
            html.Div(search_section, id="search-section"),
            html.Div(library.library_tab(service), id="library-section", hidden=True),
            _document_reader(),
        ]
    page: Component = html.Div(
        [_header(service), dbc.Container(body, fluid="xl", className="py-4")]
    )
    return page


def _header(service: SearchService | None) -> Component:
    """Build the top bar with the name of the application.

    Args:
        service: The search service, or None.

    Returns:
        The header.
    """
    badge: list[Component] = []
    if service is not None:
        badge = [
            dbc.Badge(
                f"{service.manifest.document_count} artigos indexados",
                color="light",
                text_color="dark",
                className="border d-none d-md-inline-block",
            )
        ]
    header: Component = html.Header(
        dbc.Container(
            html.Div(
                [
                    html.Div("BS", className="ss-logo me-3"),
                    html.Div(
                        [
                            html.H1("Busca Semântica em Saúde", className="ss-title"),
                            html.P(
                                "Busca híbrida (FAISS + BM25 + cross-encoder) em artigos de "
                                "saúde da Wikipédia",
                                className="ss-subtitle",
                            ),
                        ],
                        className="flex-grow-1",
                    ),
                    *badge,
                ],
                className="d-flex align-items-center py-3",
            ),
            fluid="xl",
        ),
        className="ss-header",
    )
    return header


def _controls(settings: Settings, service: SearchService) -> Component:
    """Build the search box, the example queries and the search options.

    Args:
        settings: Application settings.
        service: The search service.

    Returns:
        The controls block.
    """
    has_reranker = service.reranker_model is not None
    has_rewriter = service.query_rewriter_model is not None
    examples = [
        html.Button(
            query,
            id={"type": EXAMPLE_BUTTON_TYPE, "index": index},
            className="ss-chip",
            n_clicks=0,
        )
        for index, query in enumerate(components.EXAMPLE_QUERIES)
    ]
    # Marks at 1 and every 5 results: readable, and no floating tooltip covering the
    # controls below the slider.
    marks = {value: str(value) for value in [1, *range(5, settings.max_top_k + 1, 5)]}

    search_card = html.Div(
        [
            dbc.InputGroup(
                [
                    dbc.Input(
                        id="query",
                        type="search",
                        placeholder="Ex.: como controlar a pressão alta",
                        maxLength=settings.max_query_chars,
                        autoFocus=True,
                    ),
                    dbc.Button("Buscar", id="search-button", color="primary"),
                ],
                className="ss-search mb-3",
            ),
            html.Div("Experimente", className="ss-label"),
            html.Div(examples, className="d-flex flex-wrap"),
            html.Hr(className="my-3"),
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.Span("Modo de busca", className="ss-label"),
                            dbc.RadioItems(
                                id="mode",
                                options=MODE_OPTIONS,
                                value=settings.default_search_mode,
                                className="ss-segmented",
                                inputClassName="btn-check",
                                labelClassName="btn",
                                labelCheckedClassName="active",
                            ),
                        ],
                        md=12,
                        xl=5,
                        className="mb-3",
                    ),
                    dbc.Col(
                        [
                            html.Span("Categoria", className="ss-label"),
                            dcc.Dropdown(
                                id="category",
                                options=[
                                    {"label": components.category_label(slug), "value": slug}
                                    for slug in service.categories
                                ],
                                placeholder="Todas as categorias",
                                clearable=True,
                                searchable=False,
                            ),
                        ],
                        md=6,
                        xl=4,
                        className="mb-3",
                    ),
                    dbc.Col(
                        [
                            html.Span("Quantidade de resultados", className="ss-label"),
                            dcc.Slider(
                                id="top-k",
                                min=1,
                                max=settings.max_top_k,
                                step=1,
                                value=settings.default_top_k,
                                marks=marks,
                                tooltip={"placement": "top", "always_visible": False},
                            ),
                        ],
                        md=6,
                        xl=3,
                        className="mb-3",
                    ),
                ]
            ),
            html.Div(
                [
                    dbc.Switch(
                        id="rerank",
                        label="Reordenar com cross-encoder"
                        + ("" if has_reranker else " (desativado na configuração)"),
                        value=has_reranker,
                        disabled=not has_reranker,
                        className="me-4",
                    ),
                    dbc.Switch(
                        id="rewrite",
                        label="Interpretar a pergunta com IA"
                        + _rewrite_unavailable_hint(settings, has_rewriter),
                        value=has_rewriter,
                        disabled=not has_rewriter,
                        className="me-4",
                    ),
                    dbc.Switch(
                        id="compare",
                        label="Comparar os quatro métodos lado a lado",
                        value=False,
                    ),
                ],
                className="d-flex flex-wrap",
            ),
        ],
        className="ss-card p-3 p-md-4 mb-4",
    )
    return search_card


def _document_reader() -> Component:
    """Build the window that shows a complete article over the results.

    A modal keeps the results (and the scroll position) in place: closing it goes
    back exactly where the user was.

    Returns:
        The modal, closed and empty until a result is opened.
    """
    reader: Component = dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle(id="document-title")),
            dbc.ModalBody(id="document-body"),
            dbc.ModalFooter(
                [
                    html.A(
                        "Abrir na Wikipédia ↗",
                        id="document-link",
                        href="#",
                        target="_blank",
                        rel="noopener noreferrer",
                        className="btn btn-outline-secondary",
                    ),
                    dbc.Button("Fechar", id="document-close", color="primary", n_clicks=0),
                ]
            ),
        ],
        id="document-modal",
        is_open=False,
        size="xl",
        scrollable=True,
    )
    return reader


def _rewrite_unavailable_hint(settings: Settings, has_rewriter: bool) -> str:
    """Explain, next to the switch, why the query rewrite cannot be used.

    Args:
        settings: Application settings.
        has_rewriter: Whether the LLM rewriter was loaded.

    Returns:
        An empty string when it is available, otherwise the reason in parentheses.
    """
    if has_rewriter:
        return ""
    if not settings.query_rewrite_enabled:
        return " (desativado na configuração)"
    return " (requer OPENAI_API_KEY no .env)"


def _register_callbacks(app: Dash, service: SearchService) -> None:
    """Wire the controls to the search service.

    Args:
        app: The Dash application.
        service: The search service.
    """
    library.register_library_callbacks(app, service)

    @app.callback(
        Output("search-section", "hidden"),
        Output("library-section", "hidden"),
        Input("main-tabs", "active_tab"),
    )
    def switch_tab(active_tab: str) -> tuple[bool, bool]:
        """Show the section of the selected tab.

        Returns:
            Whether the search and the library sections are hidden.
        """
        return active_tab != SEARCH_TAB, active_tab != LIBRARY_TAB

    @app.callback(
        Output("document-modal", "is_open"),
        Output("document-title", "children"),
        Output("document-body", "children"),
        Output("document-link", "href"),
        Input({"type": components.OPEN_DOCUMENT_TYPE, "document": ALL, "key": ALL}, "n_clicks"),
        Input("document-close", "n_clicks"),
        prevent_initial_call=True,
    )
    def open_document(_opened: list[int | None], _closed: int | None) -> tuple[Any, ...]:
        """Open the clicked article in the reader, or close the reader.

        Returns:
            Whether the reader is open, its title, its body and the source link.
        """
        clicked = any(item.get("value") for item in ctx.triggered)
        return handle_document(service, ctx.triggered_id, clicked)

    # A plain `def`: Dash runs callbacks in the server's worker threads, which suits
    # the blocking model inference; there is no event loop to keep free here.
    @app.callback(
        Output("results", "children"),
        Output("query", "value"),
        Input("search-button", "n_clicks"),
        Input("query", "n_submit"),
        Input({"type": EXAMPLE_BUTTON_TYPE, "index": ALL}, "n_clicks"),
        Input("top-k", "value"),
        Input("mode", "value"),
        Input("rerank", "value"),
        Input("category", "value"),
        Input("compare", "value"),
        Input("rewrite", "value"),
        State("query", "value"),
        prevent_initial_call=True,
    )
    def search(
        _clicks: int | None,
        _submits: int | None,
        _examples: list[int | None],
        top_k: int,
        mode: str,
        rerank: bool,
        category: str | None,
        compare: bool,
        rewrite: bool,
        typed: str | None,
    ) -> tuple[Any, Any]:
        """Run the search for whatever triggered the callback.

        Returns:
            The results area and the text of the search box.
        """
        return handle_search(
            service, ctx.triggered_id, typed, top_k, mode, rerank, category, compare, rewrite
        )


def handle_search(
    service: SearchService,
    triggered_id: str | Mapping[str, Any] | None,
    typed: str | None,
    top_k: int,
    mode: str,
    rerank: bool,
    category: str | None,
    compare: bool,
    rewrite: bool = True,
) -> tuple[Any, Any]:
    """Body of the search callback, kept outside Dash so it can be tested directly.

    Args:
        service: The search service.
        triggered_id: Id of the component that fired the callback.
        typed: Current text of the search box.
        top_k: Documents per pipeline.
        mode: Retrievers to use.
        rerank: Re-rank with the cross-encoder.
        category: Category filter, or None.
        compare: Show every pipeline side by side.
        rewrite: Interpret the query with the LLM first.

    Returns:
        The results area and the text of the search box (filled in when an example
        query was clicked), or `no_update` for both when nothing should be searched.
    """
    query = resolve_query(triggered_id, typed)
    if query is None:
        return no_update, no_update
    return (
        components.render_search(service, query, top_k, mode, rerank, category, compare, rewrite),
        query,
    )


def handle_document(
    service: SearchService, triggered_id: str | Mapping[str, Any] | None, clicked: bool
) -> tuple[Any, ...]:
    """Body of the reader callback, kept outside Dash so it can be tested directly.

    Args:
        service: The search service.
        triggered_id: Id of the component that fired the callback.
        clicked: Whether the trigger was a real click. Each new list of results adds
            buttons with zero clicks, which also fires the callback; those must not
            open the reader.

    Returns:
        Whether the reader is open, its title, its body and the source link
        (`no_update` for what does not change).
    """
    if triggered_id == "document-close":
        return False, no_update, no_update, no_update
    if not clicked or not isinstance(triggered_id, Mapping):
        return no_update, no_update, no_update, no_update

    document_id = str(triggered_id["document"])
    try:
        document = service.get_document(document_id)
    except DocumentNotFoundError:
        return True, "Artigo não encontrado", components.document_not_found(document_id), "#"
    return True, document.title, components.document_view(document), str(document.source_url)


def build_app_from_settings() -> Dash:
    """Read the settings, load the service once and build the application.

    Returns:
        The Dash application.
    """
    settings = get_settings()
    configure_logging(settings.log_level)
    service, load_error = load_search_service(settings)
    return create_app(settings, service, load_error)


def create_server() -> Flask:
    """Return the WSGI server (gunicorn factory: `app.ui.dash_app:create_server()`).

    Returns:
        The Flask server behind the Dash application.
    """
    server: Flask = build_app_from_settings().server
    return server


def main() -> None:
    """Run the interface with the development server, at http://127.0.0.1:8065."""
    build_app_from_settings().run(host="127.0.0.1", port=LOCAL_PORT, debug=False)


if __name__ == "__main__":
    main()
