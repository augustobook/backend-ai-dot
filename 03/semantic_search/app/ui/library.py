"""The "Acervo" tab: every indexed article with its metadata and its chunks.

It shows exactly what the search works with: the documents loaded from the index
and the chunks as they were embedded, so a result can be traced back to its source
and the chunking can be inspected. Nothing here touches the models, except the
tokenizer used to count the tokens of each chunk.
"""

from dataclasses import dataclass
from typing import Any

import dash_ag_grid as dag
import dash_bootstrap_components as dbc
from dash import Dash, Input, Output, dcc, html
from dash.development.base_component import Component

from app.core.exceptions import DocumentNotFoundError
from app.ingestion.chunker import PARAGRAPH_SEPARATOR, Chunk
from app.ingestion.loader import Document
from app.search.keyword import normalize_text
from app.services.search_service import SearchService
from app.ui import components

PAGE_SIZE = 15
# Shorter repeats between consecutive chunks are coincidences, not the chunker's overlap.
MIN_OVERLAP_CHARS = 20
PRIMARY_COLOR = "#0f6e8c"  # Same as --ss-primary in assets/style.css.

# Portuguese names of the content types the LLM assigns to an enriched chunk.
CONTENT_TYPE_LABELS: dict[str, str] = {
    "definition": "Definição",
    "symptoms": "Sintomas",
    "causes": "Causas",
    "risk-factors": "Fatores de risco",
    "diagnosis": "Diagnóstico",
    "treatment": "Tratamento",
    "prevention": "Prevenção",
    "diet": "Alimentação",
    "epidemiology": "Epidemiologia",
    "history": "História",
    "other": "Outro",
}

COLUMN_DEFS: list[dict[str, Any]] = [
    {"field": "id", "headerName": "ID", "width": 95, "pinned": "left"},
    {"field": "title", "headerName": "Título", "flex": 2, "minWidth": 200},
    {"field": "category", "headerName": "Categoria", "flex": 1, "minWidth": 160},
    {"field": "tags", "headerName": "Tags", "flex": 2, "minWidth": 180},
    {"field": "words", "headerName": "Palavras", "type": "numericColumn", "width": 115},
    {"field": "chunks", "headerName": "Trechos", "type": "numericColumn", "width": 110},
    {"field": "revision", "headerName": "Revisão", "width": 120},
    {"field": "retrieved", "headerName": "Obtido em", "width": 125},
]

# Texts of the grid's own controls (pagination, empty table) in Portuguese.
GRID_LOCALE_PT: dict[str, str] = {
    "page": "Página",
    "of": "de",
    "to": "a",
    "more": "mais",
    "firstPage": "Primeira página",
    "previousPage": "Página anterior",
    "nextPage": "Próxima página",
    "lastPage": "Última página",
    "noRowsToShow": "Nenhum artigo corresponde ao filtro",
    "loadingOoo": "Carregando...",
}


def document_rows(service: SearchService) -> list[dict[str, Any]]:
    """Build one table row per indexed article.

    Args:
        service: The search service holding the index.

    Returns:
        Rows keyed by the table column ids; `id` is also the row id of the table.
    """
    counts = service.chunk_counts()
    return [
        {
            "id": document.id,
            "title": document.title,
            "category": components.category_label(document.category),
            "category_slug": document.category,
            "tags": ", ".join(document.tags),
            "words": len(document.body.split()),
            "chunks": counts.get(document.id, 0),
            "revision": str(document.source_revision or components.MISSING),
            "retrieved": f"{document.retrieved_at:%d/%m/%Y}",
        }
        for document in service.documents
    ]


def filter_rows(
    rows: list[dict[str, Any]], text: str | None, category: str | None
) -> list[dict[str, Any]]:
    """Keep the rows that match the text filter and the category.

    The text is compared without accents or case, against the id, the title and
    the tags, so "acucar" finds "Açúcar".

    Args:
        rows: Rows built by `document_rows`.
        text: Free text typed by the user, or None.
        category: Category slug, or None for all.

    Returns:
        The matching rows, in the original order.
    """
    needle = normalize_text(text or "").strip()
    return [
        row
        for row in rows
        if (category is None or row["category_slug"] == category)
        and (not needle or needle in normalize_text(f"{row['id']} {row['title']} {row['tags']}"))
    ]


def _stat_tile(label: str, value: str) -> Component:
    """Build one of the summary tiles at the top of the tab.

    Args:
        label: What the number counts.
        value: The number.

    Returns:
        The tile.
    """
    return html.Div(
        [html.Div(value, className="ss-tile-value"), html.Div(label, className="ss-tile-label")],
        className="ss-card ss-tile",
    )


def library_tab(service: SearchService) -> Component:
    """Build the whole "Acervo" tab.

    Args:
        service: The search service holding the index.

    Returns:
        The tab content.
    """
    rows = document_rows(service)
    enriched = sum(
        1
        for document in service.documents
        for chunk in service.get_chunks(document.id)
        if chunk.enrichment is not None
    )
    tiles = dbc.Row(
        [
            dbc.Col(_stat_tile("artigos", str(len(rows))), xs=6, md=3),
            dbc.Col(_stat_tile("trechos", str(service.manifest.chunk_count)), xs=6, md=3),
            dbc.Col(_stat_tile("categorias", str(len(service.categories))), xs=6, md=3),
            dbc.Col(_stat_tile("trechos enriquecidos", str(enriched)), xs=6, md=3),
        ],
        className="g-3 mb-3",
    )

    notice: list[Component] = []
    if enriched == 0:
        notice.append(
            dbc.Alert(
                "Os trechos deste índice não foram enriquecidos por LLM: não há contexto, "
                "perguntas, termos similares nem tipo de conteúdo. Eles aparecem aqui depois "
                "de uma ingestão com o enriquecimento ligado (requer OPENAI_API_KEY).",
                color="light",
                className="border small",
            )
        )

    table_card = html.Div(
        [
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Input(
                            id="library-filter",
                            type="search",
                            placeholder="Filtrar por título, ID ou tag",
                            debounce=0.3,
                        ),
                        md=7,
                        className="mb-2",
                    ),
                    dbc.Col(
                        dcc.Dropdown(
                            id="library-category",
                            options=[
                                {"label": components.category_label(slug), "value": slug}
                                for slug in service.categories
                            ],
                            placeholder="Todas as categorias",
                            clearable=True,
                            searchable=False,
                        ),
                        md=5,
                        className="mb-2",
                    ),
                ]
            ),
            dag.AgGrid(
                id="library-table",
                rowData=rows,
                columnDefs=COLUMN_DEFS,
                defaultColDef={"sortable": True, "resizable": True},
                # The row id is the document id, so a selection maps straight to it.
                getRowId="params.data.id",
                dashGridOptions={
                    "domLayout": "autoHeight",
                    "pagination": True,
                    "paginationPageSize": PAGE_SIZE,
                    "paginationPageSizeSelector": False,
                    "rowSelection": {
                        "mode": "singleRow",
                        "checkboxes": False,
                        "enableClickSelection": True,
                    },
                    "localeText": GRID_LOCALE_PT,
                },
                className="ss-grid",
                style={"width": "100%"},
            ),
            html.Div(
                "Clique em uma linha para ver os metadados e os trechos do artigo.",
                className="ss-summary mt-2 mb-0",
            ),
        ],
        className="ss-card p-3 mb-4",
    )

    return html.Div(
        [
            *notice,
            tiles,
            table_card,
            dcc.Loading(
                html.Div(_detail_placeholder(), id="library-detail"),
                type="circle",
                color=PRIMARY_COLOR,
            ),
        ]
    )


def _detail_placeholder() -> Component:
    """Show what the detail area holds before an article is selected.

    Returns:
        A short hint.
    """
    return html.Div(
        [
            html.H5("Nenhum artigo selecionado"),
            html.P(
                "Escolha um artigo na tabela para ver o front matter completo e cada "
                "trecho exatamente como foi indexado.",
                className="mb-0",
            ),
        ],
        className="ss-card ss-empty",
    )


def _meta_row(label: str, value: str | Component) -> Component:
    """Build one line of the metadata list.

    Args:
        label: Name of the field.
        value: Its value.

    Returns:
        The line.
    """
    return html.Div(
        [html.Span(label, className="ss-stat-label"), html.Span(value, className="ss-stat-value")],
        className="ss-stat",
    )


def metadata_panel(document: Document, chunk_count: int) -> Component:
    """List every front matter field of an article.

    Args:
        document: The article.
        chunk_count: How many chunks it was split into.

    Returns:
        The metadata card.
    """
    link = html.A(
        "pt.wikipedia.org ↗", href=str(document.source_url), target="_blank", rel="noopener"
    )
    license_link = html.A(
        document.license, href=str(document.license_url), target="_blank", rel="noopener"
    )
    rows = [
        _meta_row("ID", document.id),
        _meta_row("Arquivo", document.file_name),
        _meta_row("Categoria", components.category_label(document.category)),
        _meta_row("Tags", ", ".join(document.tags)),
        _meta_row("Autoria", document.author),
        _meta_row("Fonte", link),
        _meta_row("Revisão", str(document.source_revision or components.MISSING)),
        _meta_row("Obtido em", f"{document.retrieved_at:%d/%m/%Y}"),
        _meta_row("Licença", license_link),
        _meta_row("Alterações", document.adapted or components.MISSING),
        _meta_row("Palavras", str(len(document.body.split()))),
        _meta_row("Trechos", str(chunk_count)),
    ]
    return html.Div(
        [
            html.Div("Metadados", className="ss-section-title"),
            *rows,
            html.Button(
                "Ler artigo completo",
                id={
                    "type": components.OPEN_DOCUMENT_TYPE,
                    "document": document.id,
                    "key": "library-button",
                },
                n_clicks=0,
                className="ss-read-button mt-3",
            ),
        ],
        className="ss-card p-3",
    )


def enrichment_block(chunk: Chunk) -> list[Component]:
    """Show what the LLM wrote about a chunk, when it was enriched.

    Args:
        chunk: The chunk.

    Returns:
        The enrichment components, empty for a plain chunk.
    """
    enrichment = chunk.enrichment
    if enrichment is None:
        return []
    return [
        html.Div(
            [
                html.Div("Enriquecimento (LLM)", className="ss-label mt-2"),
                html.P(enrichment.context, className="small mb-2"),
                html.Div(
                    [
                        dbc.Badge(
                            CONTENT_TYPE_LABELS.get(kind, kind),
                            color="secondary",
                            className="me-1",
                        )
                        for kind in enrichment.content_types
                    ],
                    className="mb-2",
                ),
                html.Div("Perguntas que o trecho responde", className="ss-label"),
                html.Ul(
                    [html.Li(question) for question in enrichment.questions], className="small"
                ),
                html.Div("Termos similares", className="ss-label"),
                html.Div(
                    [html.Span(term, className="ss-tag") for term in enrichment.similar_terms]
                ),
            ],
            className="ss-enrichment",
        )
    ]


@dataclass(frozen=True)
class ChunkFacts:
    """Metadata of one chunk, stored or derived, as shown in its card.

    Attributes:
        chunk: The chunk itself (id, document, position, text, enrichment).
        document: The article it belongs to (its category and tags are the chunk's).
        total: Number of chunks of the article.
        passage: The text of the article in the chunk, without the title prefix.
        has_title_prefix: Whether the chunker prepended the title.
        tokens: Tokens of `chunk.text` (title + passage).
        indexed_tokens: Tokens of `chunk.search_text` (with the enrichment, if any).
        token_budget: `chunk_max_tokens` used at ingestion.
        overlap_tokens: Tokens repeated from the end of the previous chunk.
    """

    chunk: Chunk
    document: Document
    total: int
    passage: str
    has_title_prefix: bool
    tokens: int
    indexed_tokens: int
    token_budget: int
    overlap_tokens: int


def overlap_text(previous: str, current: str) -> str:
    """Find the text the chunker repeated from the previous chunk.

    The overlap is the longest end of the previous passage that the current passage
    starts with. Very short matches (a word that happens to repeat) are ignored.

    Args:
        previous: Passage of the previous chunk.
        current: Passage of this chunk.

    Returns:
        The repeated text, or "" when there is none.
    """
    for size in range(min(len(previous), len(current)), MIN_OVERLAP_CHARS - 1, -1):
        if previous.endswith(current[:size]):
            return current[:size]
    return ""


def chunk_facts(service: SearchService, document: Document) -> list[ChunkFacts]:
    """Gather the metadata of every chunk of an article.

    Args:
        service: The search service holding the index.
        document: The article.

    Returns:
        One entry per chunk, in reading order.
    """
    chunks = service.get_chunks(document.id)
    prefix = f"{document.title}{PARAGRAPH_SEPARATOR}"
    passages = [chunk.text.removeprefix(prefix) for chunk in chunks]
    facts = []
    for index, chunk in enumerate(chunks):
        repeated = overlap_text(passages[index - 1], passages[index]) if index else ""
        facts.append(
            ChunkFacts(
                chunk=chunk,
                document=document,
                total=len(chunks),
                passage=passages[index],
                has_title_prefix=chunk.text.startswith(prefix),
                tokens=service.count_tokens(chunk.text),
                indexed_tokens=service.count_tokens(chunk.search_text),
                token_budget=service.manifest.chunk_max_tokens,
                overlap_tokens=service.count_tokens(repeated) if repeated else 0,
            )
        )
    return facts


def chunk_metadata(facts: ChunkFacts) -> Component:
    """Build the metadata grid of one chunk.

    Args:
        facts: Metadata of the chunk.

    Returns:
        A grid of label/value pairs.
    """
    chunk, enrichment = facts.chunk, facts.chunk.enrichment
    usage = round(100 * facts.tokens / facts.token_budget) if facts.token_budget else 0
    items = [
        ("ID do trecho", str(chunk.chunk_id)),
        ("Artigo", chunk.document_id),
        ("Posição", f"{chunk.position + 1} de {facts.total}"),
        ("Tokens", f"{facts.tokens} de {facts.token_budget} ({usage}%)"),
        ("Tokens indexados", str(facts.indexed_tokens)),
        ("Caracteres", str(len(facts.passage))),
        ("Palavras", str(len(facts.passage.split()))),
        (
            "Sobreposição",
            f"{facts.overlap_tokens} tokens do trecho anterior"
            if facts.overlap_tokens
            else components.MISSING,
        ),
        ("Título prefixado", "sim" if facts.has_title_prefix else "não"),
        ("Categoria", components.category_label(facts.document.category)),
        ("Tags", ", ".join(facts.document.tags)),
        ("Enriquecido por LLM", "sim" if enrichment else "não"),
        ("Perguntas indexadas", str(len(enrichment.questions)) if enrichment else "0"),
        ("Termos similares", str(len(enrichment.similar_terms)) if enrichment else "0"),
    ]
    return html.Dl(
        [
            html.Div([html.Dt(label), html.Dd(value)], className="ss-chunk-meta-item")
            for label, value in items
        ],
        className="ss-chunk-meta",
    )


def chunk_card(facts: ChunkFacts) -> Component:
    """Show one chunk exactly as it was indexed, with its metadata.

    The title the chunker prepends to every chunk is shown apart from the passage,
    so it is clear which part comes from the article and which part was added.

    Args:
        facts: Metadata of the chunk.

    Returns:
        The chunk card.
    """
    chunk = facts.chunk
    return html.Div(
        [
            html.Div(
                [
                    html.Span(
                        f"Trecho {chunk.position + 1} de {facts.total}", className="fw-semibold"
                    ),
                    html.Span(f"{facts.tokens} tokens", className="ss-tag ms-2"),
                    html.Span(f"ID {chunk.chunk_id}", className="ss-chunk-id ms-auto"),
                ],
                className="d-flex align-items-center flex-wrap mb-2",
            ),
            chunk_metadata(facts),
            html.Div(
                [
                    html.Span(facts.document.title, className="ss-chunk-prefix")
                    if facts.has_title_prefix
                    else None,
                    html.Div(facts.passage, className="ss-chunk-text"),
                ]
            ),
            *enrichment_block(chunk),
        ],
        className="ss-card ss-chunk",
    )


def document_detail(service: SearchService, document_id: str) -> Component:
    """Build the detail of an article: metadata on the left, chunks on the right.

    Args:
        service: The search service holding the index.
        document_id: Id of the article.

    Returns:
        The detail, or a warning when the article is not in the index.
    """
    try:
        document = service.get_document(document_id)
    except DocumentNotFoundError:
        return components.document_not_found(document_id)

    facts = chunk_facts(service, document)
    chunks = [fact.chunk for fact in facts]
    cards = [chunk_card(fact) for fact in facts]
    detail: Component = html.Div(
        [
            html.H4(document.title, className="ss-detail-title mb-3"),
            dbc.Row(
                [
                    dbc.Col(metadata_panel(document, len(chunks)), lg=4, className="mb-3"),
                    dbc.Col(
                        [html.Div("Trechos indexados", className="ss-section-title"), *cards],
                        lg=8,
                    ),
                ]
            ),
        ]
    )
    return detail


def register_library_callbacks(app: Dash, service: SearchService) -> None:
    """Wire the filters and the table of the tab.

    Args:
        app: The Dash application.
        service: The search service holding the index.
    """
    rows = document_rows(service)

    @app.callback(
        Output("library-table", "rowData"),
        Input("library-filter", "value"),
        Input("library-category", "value"),
        prevent_initial_call=True,
    )
    def filter_table(text: str | None, category: str | None) -> list[dict[str, Any]]:
        """Apply the text and category filters to the table.

        Returns:
            The rows to show.
        """
        return filter_rows(rows, text, category)

    @app.callback(
        Output("library-detail", "children"),
        Input("library-table", "selectedRows"),
        prevent_initial_call=True,
    )
    def show_detail(selected_rows: list[dict[str, Any]] | None) -> Component:
        """Show the article of the clicked row.

        Returns:
            The detail of the article, or the hint when nothing is selected.
        """
        return detail_for_selection(service, selected_rows)


def detail_for_selection(
    service: SearchService, selected_rows: list[dict[str, Any]] | None
) -> Component:
    """Build the detail area for the rows selected in the grid.

    Args:
        service: The search service holding the index.
        selected_rows: Rows selected in the grid (at most one), or None.

    Returns:
        The detail of the selected article, or the hint when nothing is selected
        (e.g. after a filter hid the selected row).
    """
    if not selected_rows:
        return _detail_placeholder()
    return document_detail(service, str(selected_rows[0]["id"]))
