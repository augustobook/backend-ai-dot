"""Dash components of the web interface, built from the search service's results.

Everything here is a pure function of its arguments, except `render_search`, which
only calls the search service. The callbacks in `dash_app.py` stay thin, and the
whole visual logic can be tested with the fake models, without a browser.

The interface is in Portuguese, the language of the articles and of its users; the
code, as the rest of the project, stays in English.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

import dash_bootstrap_components as dbc
from dash import dcc, html
from dash.development.base_component import Component

from app.core.config import SearchMode
from app.core.exceptions import InvalidQueryError
from app.ingestion.chunker import PARAGRAPH_SEPARATOR
from app.ingestion.loader import Document
from app.llm.metadata import QueryAnalysis
from app.search.keyword import normalize_text, tokenize_pt
from app.services.artifacts import IndexManifest
from app.services.results import SearchResponse, SearchResult
from app.services.search_service import SearchService

# Clickable examples. Each one found its article in 1st place at every stage of the
# evaluation (BM25, semantic, hybrid and cross-encoder; see docs/EVALUATION.md), and
# together they show what the search handles:
# - lay terms the articles do not use ("pressão alta", "cobreiro", "ranger os dentes"),
#   found through the meaning and the LLM enrichment;
# - lay descriptions of a disease (zika in pregnancy, microcephaly; bread and gluten);
# - an exact scientific name, where BM25 is strong;
# - a question outside the collection, which must end in "no confident result"
#   instead of presenting the closest articles as an answer.
EXAMPLE_QUERIES: tuple[str, ...] = (
    "como controlar a pressão alta",
    "cobreiro",
    "ranger os dentes dormindo",
    "zika na gravidez e bebê com cabeça pequena",
    "não posso comer pão por causa do glúten",
    "Aedes aegypti",
    "como trocar o pneu do carro",
)

# Portuguese names of the category slugs (the same names used in data/README.md)
# and the Bootstrap color of each badge.
CATEGORY_LABELS: dict[str, str] = {
    "nutrition": "Nutrição",
    "mental-health": "Saúde mental",
    "sleep-exercise": "Sono e atividade física",
    "chronic-diseases": "Doenças crônicas",
    "infectious-diseases": "Doenças infecciosas e prevenção",
}
CATEGORY_COLORS: dict[str, str] = {
    "nutrition": "success",
    "mental-health": "info",
    "sleep-exercise": "primary",
    "chronic-diseases": "danger",
    "infectious-diseases": "warning",
}

MODE_LABELS: dict[str, str] = {
    "hybrid": "Híbrida",
    "semantic": "Semântica",
    "keyword": "Palavras-chave (BM25)",
}

CONTENT_TYPE_LABELS: dict[str, str] = {
    "definition": "definição",
    "symptoms": "sintomas",
    "causes": "causas",
    "risk-factors": "fatores de risco",
    "diagnosis": "diagnóstico",
    "treatment": "tratamento",
    "prevention": "prevenção",
    "diet": "alimentação",
    "epidemiology": "epidemiologia",
    "history": "história",
    "other": "outros",
}

MISSING = "—"

# What each stage of the score details measures, in a sentence a non-specialist can
# follow. Shown under the stage name in the "Detalhes da pontuação" table.
STAGE_DESCRIPTIONS: dict[str, str] = {
    "Cosseno (FAISS)": (
        "Proximidade de significado entre a pergunta e o trecho (ou uma das perguntas "
        "geradas para ele), de 0 a 1. Acha paráfrases e sinônimos, mesmo sem palavras "
        "em comum."
    ),
    "BM25": (
        "Busca por palavras: conta os termos da pergunta presentes no trecho, valendo "
        "mais os termos raros. Não tem teto; só serve para comparar trechos entre si."
    ),
    "Fusão RRF": (
        "Junta as duas listas acima pela posição de cada trecho, não pela nota: "
        "1/(60 + posição no cosseno) + 1/(60 + posição no BM25). Ganha quem aparece "
        "bem colocado nas duas."
    ),
    "Cross-encoder": (
        "Um modelo lê a pergunta junto com o trecho e estima a relevância, de 0 a 1. "
        "É a etapa mais precisa e a que decide a ordem final."
    ),
}

# Pattern-matching id type of the components that open an article in the reader.
OPEN_DOCUMENT_TYPE = "open-document"

# A word of the chunk, accents included; compared with the query terms after the
# same normalization BM25 uses, so "Fibras" matches the query "fibras".
WORD_PATTERN = re.compile(r"[^\W_]+")


@dataclass(frozen=True)
class Pipeline:
    """One of the search configurations shown side by side in the comparison.

    Attributes:
        label: Column title.
        mode: Retrievers used.
        rerank: Whether the cross-encoder re-orders the candidates.
    """

    label: str
    mode: SearchMode
    rerank: bool


PIPELINES: tuple[Pipeline, ...] = (
    Pipeline("Palavras-chave (BM25)", "keyword", rerank=False),
    Pipeline("Semântica", "semantic", rerank=False),
    Pipeline("Híbrida", "hybrid", rerank=False),
    Pipeline("Híbrida + reordenação", "hybrid", rerank=True),
)


def category_label(slug: str) -> str:
    """Return the Portuguese name of a category.

    Args:
        slug: Category slug, e.g. `sleep-exercise`.

    Returns:
        The name, e.g. "Sono e atividade física"; unknown slugs are made readable.
    """
    return CATEGORY_LABELS.get(slug, slug.replace("-", " ").capitalize())


def format_decimal(value: float, decimals: int = 2) -> str:
    """Format a number with the Brazilian decimal comma.

    Args:
        value: The number.
        decimals: Digits after the comma.

    Returns:
        The formatted number, e.g. "0,87".
    """
    return f"{value:.{decimals}f}".replace(".", ",")


def highlight(text: str, query: str) -> list[str | Component]:
    """Mark the words of a text that are query terms.

    The parts are built as components (`html.Mark`) instead of an HTML string, so a
    chunk is never injected into the page as raw HTML.

    Args:
        text: Text to display.
        query: The query; its stopwords are ignored, like in BM25.

    Returns:
        Plain strings interleaved with highlighted words.
    """
    terms = set(tokenize_pt(query))
    if not terms:
        return [text]

    parts: list[str | Component] = []
    last = 0
    for match in WORD_PATTERN.finditer(text):
        if normalize_text(match.group()) not in terms:
            continue
        if match.start() > last:
            parts.append(text[last : match.start()])
        parts.append(html.Mark(match.group()))
        last = match.end()
    if last < len(text):
        parts.append(text[last:])
    return parts


def passage_text(result: SearchResult) -> str:
    """Return the matched chunk without the title the chunker prepended to it.

    The card already shows the title, so repeating it above the passage is noise.

    Args:
        result: A search result.

    Returns:
        The passage of the chunk.
    """
    return result.chunk_text.removeprefix(f"{result.title}{PARAGRAPH_SEPARATOR}")


def pipeline_label(response: SearchResponse) -> str:
    """Name the pipeline that produced a response.

    Args:
        response: A search response.

    Returns:
        E.g. "Híbrida + reordenação".
    """
    return MODE_LABELS[response.mode] + (" + reordenação" if response.reranked else "")


def score_meaning(response: SearchResponse) -> str:
    """Explain what the final score of a response measures.

    Args:
        response: A search response.

    Returns:
        A short description of the score.
    """
    if response.reranked:
        return "relevância estimada pelo cross-encoder"
    if response.mode == "semantic":
        return "similaridade de cosseno"
    if response.mode == "keyword":
        return "BM25 dividido pelo melhor BM25 da consulta"
    return "RRF dividido pelo maior RRF possível"


def _format(value: float | int | None) -> str:
    """Format an optional score or rank for the details table.

    Args:
        value: Score, rank or None.

    Returns:
        The formatted value, or a dash when the stage did not score the chunk.
    """
    if value is None:
        return MISSING
    return format_decimal(value, 4) if isinstance(value, float) else f"{value}º"


def stage_details(result: SearchResult) -> Component:
    """Build the table with the score and rank of the chunk at each stage.

    Args:
        result: A search result.

    Returns:
        A table component.
    """
    scores, ranks = result.stage_scores, result.stage_ranks
    rows = [
        ("Cosseno (FAISS)", scores.dense, ranks.dense),
        ("BM25", scores.keyword, ranks.keyword),
        ("Fusão RRF", scores.rrf, None),
        ("Cross-encoder", scores.rerank, None),
    ]

    def stage_cell(stage: str) -> Component:
        cell: Component = html.Td(
            [html.Div(stage), html.Div(STAGE_DESCRIPTIONS[stage], className="ss-stage-help")]
        )
        return cell

    return html.Div(
        [
            dbc.Table(
                [
                    html.Thead(
                        html.Tr([html.Th("Etapa"), html.Th("Pontuação"), html.Th("Posição")])
                    ),
                    html.Tbody(
                        [
                            html.Tr(
                                [stage_cell(stage), html.Td(_format(score)), html.Td(_format(rank))]
                            )
                            for stage, score, rank in rows
                        ]
                    ),
                ],
                size="sm",
                borderless=True,
                className="mb-1",
            ),
            html.Small(
                f"Trecho {result.chunk_position + 1} do artigo {result.document_id}",
                className="text-muted",
            ),
            *enrichment_details(result),
        ]
    )


def enrichment_details(result: SearchResult) -> list[Component]:
    """Show what the LLM wrote about the chunk and how it helped this result.

    Args:
        result: A search result.

    Returns:
        The components (empty when the chunk was not enriched).
    """
    parts: list[Component] = []
    if result.matched_question:
        parts.append(
            html.Div(
                [html.Strong("Pergunta que casou: "), result.matched_question],
                className="ss-enrichment-line",
            )
        )
    if result.metadata_match:
        parts.append(
            html.Div(
                "Categoria ou tipo de conteúdo combina com a pergunta (reforço aplicado).",
                className="ss-enrichment-line",
            )
        )
    enrichment = result.enrichment
    if enrichment is not None:
        lines: list[tuple[str, str]] = [
            ("Contexto: ", enrichment.context),
            ("Termos semelhantes: ", "; ".join(enrichment.similar_terms)),
            (
                "Tipo de conteúdo: ",
                ", ".join(CONTENT_TYPE_LABELS.get(kind, kind) for kind in enrichment.content_types),
            ),
        ]
        parts += [
            html.Div([html.Strong(label), value], className="ss-enrichment-line")
            for label, value in lines
            if value
        ]
        if enrichment.questions:
            parts.append(
                html.Div(
                    [
                        html.Strong("Perguntas que o trecho responde:"),
                        html.Ul([html.Li(question) for question in enrichment.questions]),
                    ],
                    className="ss-enrichment-line",
                )
            )
    if not parts:
        return []
    return [html.Div(parts, className="ss-enrichment")]


def analysis_view(analysis: QueryAnalysis | None) -> list[Component]:
    """Show how the LLM interpreted the query.

    Args:
        analysis: The query analysis, or None when the query was searched as typed.

    Returns:
        The components (empty without analysis).
    """
    if analysis is None:
        return []
    chips: list[Component] = [
        html.Span(term, className="ss-tag") for term in analysis.similar_terms
    ]
    chips += [
        html.Span(category_label(category), className="ss-tag ss-tag-meta")
        for category in analysis.categories
    ]
    chips += [
        html.Span(CONTENT_TYPE_LABELS.get(kind, kind), className="ss-tag ss-tag-meta")
        for kind in analysis.content_types
    ]
    lines: list[Component] = [
        html.Div(
            [html.Strong("Pergunta interpretada como: "), analysis.rewritten_query],
            className="mb-1",
        )
    ]
    if analysis.alternative_queries:
        lines.append(
            html.Div(
                [
                    html.Strong("Também buscado como: "),
                    "; ".join(analysis.alternative_queries),
                ],
                className="mb-1",
            )
        )
    block: Component = html.Div(
        [*lines, html.Div(chips, className="d-flex flex-wrap")],
        className="ss-analysis",
    )
    return [block]


def open_document_id(result: SearchResult, scope: str, part: str) -> dict[str, str]:
    """Build the id of a component that opens a result's article in the reader.

    The same article can appear in several comparison columns, and each card has two
    such components (title and button); `scope` and `part` keep every id unique.

    Args:
        result: The result the component belongs to.
        scope: Which list holds the card ("list" or the comparison column).
        part: Which component of the card ("title" or "button").

    Returns:
        A pattern-matching id carrying the document id.
    """
    return {
        "type": OPEN_DOCUMENT_TYPE,
        "document": result.document_id,
        "key": f"{scope}-{result.rank}-{part}",
    }


def result_card(
    result: SearchResult, query: str, compact: bool = False, scope: str = "list"
) -> Component:
    """Build the card of one result.

    Args:
        result: A search result.
        query: The query, whose terms are highlighted in the passage.
        compact: Leave out the tags, the passage and the attribution (used in the
            narrow comparison columns, where only the ranking matters).
        scope: Which list holds the card (keeps the component ids unique).

    Returns:
        A card component.
    """
    category = dbc.Badge(
        category_label(result.category),
        color=CATEGORY_COLORS.get(result.category, "secondary"),
        className="ss-category me-2",
    )
    meta: list[Component] = [category]
    if result.relevant is False:
        meta.append(html.Span("baixa relevância", className="ss-low-badge"))
    if not compact:
        meta += [html.Span(tag, className="ss-tag") for tag in result.tags]

    header = html.Div(
        [
            html.Div(str(result.rank), className="ss-rank me-3"),
            html.Div(
                [
                    html.H3(
                        html.Button(
                            result.title,
                            id=open_document_id(result, scope, "title"),
                            n_clicks=0,
                            className="ss-title-link",
                            title="Ler o artigo completo",
                        ),
                        className="ss-result-title mb-1",
                    ),
                    html.Div(meta, className="d-flex flex-wrap align-items-center"),
                ],
                className="flex-grow-1 me-3",
            ),
            html.Div(
                [
                    html.Div(format_decimal(result.score), className="ss-score-value"),
                    html.Div("pontuação", className="ss-score-label"),
                    dbc.Progress(value=result.score * 100, className="ss-score-bar"),
                ],
                className="ss-score",
            ),
        ],
        className="d-flex align-items-start",
    )

    body: list[Component] = [header]
    if not compact:
        body.append(html.P(highlight(passage_text(result), query), className="ss-passage"))
    body.append(
        dbc.Accordion(
            [dbc.AccordionItem(stage_details(result), title="Detalhes da pontuação")],
            start_collapsed=True,
            flush=True,
            className="ss-details",
        )
    )
    actions: list[Component] = [
        html.Button(
            "Ler artigo completo",
            id=open_document_id(result, scope, "button"),
            n_clicks=0,
            className="ss-read-button me-3",
        ),
        html.A(
            "Wikipédia ↗",
            href=result.source_url,
            target="_blank",
            rel="noopener noreferrer",
            className="ss-external-link",
        ),
    ]
    if not compact:
        actions.append(html.Span(f"{result.author} · {result.license}", className="ms-auto"))
    body.append(
        html.Div(actions, className="ss-footer-line d-flex flex-wrap align-items-center mt-2")
    )

    # dash-bootstrap-components ships no type hints, hence the annotated variables
    # (here and below) instead of returning its components directly.
    low = " ss-result-low" if result.relevant is False else ""
    card: Component = html.Div(body, className=f"ss-card ss-result{low}")
    return card


def results_view(
    response: SearchResponse, compact: bool = False, scope: str = "list"
) -> list[Component]:
    """Build the summary line and the cards of a response.

    Args:
        response: A search response.
        compact: Use the compact cards (see `result_card`).
        scope: Which list holds the cards (keeps the component ids unique).

    Returns:
        The components to display, in order.
    """
    count = len(response.results)
    noun = "artigo encontrado" if count == 1 else "artigos encontrados"
    elapsed = response.timings_ms.get("total", 0.0)
    low = [result for result in response.results if result.relevant is False]
    summary_parts = [f"{count} {noun}", f"{elapsed / 1000:.1f} s".replace(".", ",")]
    if low:
        summary_parts.insert(1, f"{len(low)} com baixa relevância")
    if not compact:
        summary_parts.insert(1, pipeline_label(response))
        summary_parts.append(f"pontuação = {score_meaning(response)}")
    summary = html.Div(" · ".join(summary_parts), className="ss-summary")

    if not response.results:
        return [
            summary,
            dbc.Alert(
                "Nenhum artigo corresponde à consulta. Tente outras palavras ou remova o "
                "filtro de categoria.",
                color="light",
                className="border",
            ),
        ]
    # The comparison columns keep every card in place (the ranking is what they
    # compare); the badge on each card is enough there.
    if compact:
        return [
            summary,
            *(
                result_card(result, response.query, compact=True, scope=scope)
                for result in response.results
            ),
        ]

    relevant = [result for result in response.results if result.relevant is not False]
    view: list[Component] = [summary, *analysis_view(response.analysis)]
    if not relevant:
        view.append(no_confident_result_alert())
    view += [result_card(result, response.query) for result in relevant]
    if low:
        view.append(low_relevance_group(low, response.query, expanded=not relevant))
    return view


def no_confident_result_alert() -> Component:
    """Say that no result reached the relevance threshold.

    A small collection always returns its closest articles, even when none of them
    is about the subject; showing them as answers would mislead the user.

    Returns:
        A warning alert.
    """
    alert: Component = dbc.Alert(
        [
            html.Strong("Nenhum resultado confiável. "),
            "Os artigos mais próximos têm relevância baixa: o acervo talvez não trate "
            "desse assunto. Tente outras palavras, como o nome médico do problema.",
        ],
        color="warning",
        className="ss-no-confident",
    )
    return alert


def low_relevance_group(results: Sequence[SearchResult], query: str, expanded: bool) -> Component:
    """Gather the low-relevance results in a collapsible section.

    Args:
        results: Results below the relevance threshold.
        query: The query, whose terms are highlighted.
        expanded: Open the section (used when there is nothing above it).

    Returns:
        An accordion with the cards.
    """
    noun = "resultado" if len(results) == 1 else "resultados"
    group: Component = dbc.Accordion(
        [
            dbc.AccordionItem(
                [result_card(result, query) for result in results],
                title=f"{len(results)} {noun} com baixa relevância",
                item_id="low",
            )
        ],
        start_collapsed=not expanded,
        active_item="low" if expanded else None,
        flush=True,
        className="ss-low-group",
    )
    return group


def comparison_view(responses: Sequence[tuple[Pipeline, SearchResponse]]) -> Component:
    """Show the results of several pipelines side by side.

    Args:
        responses: Each pipeline with the response it produced for the same query.

    Returns:
        A row with one column per pipeline.
    """
    row: Component = dbc.Row(
        [
            dbc.Col(
                [
                    html.Div(pipeline.label, className="ss-column-title"),
                    *results_view(response, compact=True, scope=f"column{index}"),
                ],
                md=6,
                xxl=3,
            )
            for index, (pipeline, response) in enumerate(responses)
        ],
        className="ss-compare",
    )
    return row


def document_view(document: Document) -> Component:
    """Build the reader with the complete article.

    The body is rendered as Markdown (it keeps the `##` sections of the article),
    without raw HTML: the text comes from an external source.

    Args:
        document: The complete article.

    Returns:
        The content of the reader.
    """
    revision = f", revisão {document.source_revision}" if document.source_revision else ""
    attribution: list[str | Component] = [
        "Fonte: ",
        html.A(
            f"“{document.title}”, Wikipédia",
            href=str(document.source_url),
            target="_blank",
            rel="noopener noreferrer",
        ),
        f"{revision}, obtido em {document.retrieved_at:%d/%m/%Y}. {document.author}. Licença ",
        html.A(document.license, href=str(document.license_url), target="_blank", rel="noopener"),
        ".",
    ]
    if document.adapted:
        attribution.append(f" Alterações: {document.adapted}.")

    return html.Div(
        [
            html.Div(
                [
                    dbc.Badge(
                        category_label(document.category),
                        color=CATEGORY_COLORS.get(document.category, "secondary"),
                        className="ss-category me-2",
                    ),
                    *(html.Span(tag, className="ss-tag") for tag in document.tags),
                ],
                className="d-flex flex-wrap align-items-center mb-3",
            ),
            dcc.Markdown(document.body, className="ss-document", link_target="_blank"),
            html.P(attribution, className="ss-attribution"),
        ]
    )


def document_not_found(document_id: str) -> Component:
    """Say that an article is not in the index anymore.

    Args:
        document_id: The requested id.

    Returns:
        A warning alert.
    """
    alert: Component = dbc.Alert(
        f"O artigo {document_id} não está no índice carregado. Refaça a busca.",
        color="warning",
    )
    return alert


def empty_state() -> Component:
    """Show what the results area holds before the first search.

    Returns:
        A short invitation to search.
    """
    return html.Div(
        [
            html.H5("Faça uma pergunta sobre saúde"),
            html.P(
                "Escreva com suas palavras, em português ou em inglês, ou clique em um "
                "dos exemplos acima. A busca entende o significado da pergunta, mesmo "
                "quando os termos são diferentes dos usados nos artigos.",
                className="mb-0 mx-auto",
                style={"maxWidth": "560px"},
            ),
        ],
        className="ss-card ss-empty",
    )


def _stat(label: str, value: str) -> Component:
    """Build one line of the index panel.

    Args:
        label: Name of the value.
        value: The value.

    Returns:
        The line.
    """
    return html.Div(
        [html.Span(label, className="ss-stat-label"), html.Span(value, className="ss-stat-value")],
        className="ss-stat",
    )


def stats_panel(
    manifest: IndexManifest | None,
    reranker_model: str | None,
    query_rewriter_model: str | None = None,
) -> Component:
    """Build the panel with the information of the loaded index.

    Args:
        manifest: Manifest of the index, or None when no index is loaded.
        reranker_model: Cross-encoder in use, or None when re-ranking is disabled.
        query_rewriter_model: LLM that rewrites the queries, or None when disabled.

    Returns:
        The panel.
    """
    title = html.Div("Sobre o índice", className="ss-section-title")
    if manifest is None:
        return html.Div(
            [title, html.P("Nenhum índice carregado.", className="text-muted small mb-0")],
            className="ss-card p-3 mb-3",
        )

    return html.Div(
        [
            title,
            _stat("Artigos", str(manifest.document_count)),
            _stat("Trechos (chunks)", str(manifest.chunk_count)),
            _stat("Modelo de embeddings", manifest.embedding_model.split("/")[-1]),
            _stat("Dimensão dos vetores", str(manifest.dimension)),
            _stat(
                "Tamanho do trecho",
                f"{manifest.chunk_max_tokens} tokens ({manifest.chunk_overlap_tokens} de "
                "sobreposição)",
            ),
            _stat(
                "Reordenação",
                reranker_model.split("/")[-1] if reranker_model else "desativada",
            ),
            _stat("Enriquecimento (LLM)", manifest.enrichment_model or "desativado"),
            _stat("Perguntas indexadas", str(manifest.question_count)),
            _stat("Reescrita da pergunta", query_rewriter_model or "desativada"),
        ],
        className="ss-card p-3 mb-3",
    )


def how_it_works_panel() -> Component:
    """Explain the search pipeline in a few steps.

    Returns:
        The panel.
    """
    steps = [
        (
            "Enriquecimento: ",
            "na indexação, uma LLM escreveu para cada trecho o contexto, termos "
            "semelhantes e as perguntas que ele responde.",
        ),
        (
            "Interpretação: ",
            "a LLM reescreve a pergunta com termos técnicos e identifica categoria e "
            "tipo de informação pedida.",
        ),
        (
            "Busca semântica: ",
            "a pergunta vira um vetor e o FAISS acha os trechos, e as perguntas geradas, "
            "de significado mais próximo.",
        ),
        ("Palavras-chave: ", "o BM25 acha os trechos que contêm os termos exatos."),
        ("Fusão: ", "o RRF combina as duas listas pelas posições, não pelas pontuações."),
        (
            "Reforço: ",
            "trechos da categoria ou do tipo de informação pedidos sobem um pouco.",
        ),
        (
            "Reordenação: ",
            "um cross-encoder lê a pergunta junto com cada trecho candidato e reordena.",
        ),
        ("Agrupamento: ", "cada artigo aparece uma vez, com o seu melhor trecho."),
    ]
    return html.Div(
        [
            html.Div("Como funciona", className="ss-section-title"),
            html.Ol(
                [html.Li([html.Strong(name), text]) for name, text in steps], className="ss-steps"
            ),
        ],
        className="ss-card p-3 mb-3",
    )


def index_missing_alert(message: str) -> Component:
    """Explain that there is no index to search and how to build it.

    Args:
        message: Error raised while loading the index (shown as a technical detail).

    Returns:
        A warning alert.
    """
    alert: Component = dbc.Alert(
        [
            html.H5("O índice de busca ainda não está disponível", className="alert-heading"),
            html.P(
                [
                    "Crie o índice com ",
                    html.Code("uv run python -m app.cli ingest"),
                    " (ou ",
                    html.Code("docker compose run --rm ingest"),
                    ") e reinicie a interface.",
                ]
            ),
            html.Small(f"Detalhe técnico: {message}", className="text-muted"),
        ],
        color="warning",
    )
    return alert


def error_alert(message: str) -> Component:
    """Show an invalid search without a stack trace.

    Args:
        message: Message to show.

    Returns:
        A danger alert.
    """
    alert: Component = dbc.Alert(message, color="danger")
    return alert


def render_search(
    service: SearchService,
    query: str,
    top_k: int,
    mode: str,
    rerank: bool,
    category: str | None,
    compare: bool,
    rewrite: bool = True,
) -> Component:
    """Run a search and build what the results area shows.

    Args:
        service: The search service.
        query: The query.
        top_k: Documents per pipeline.
        mode: Retrievers to use (ignored when comparing).
        rerank: Re-rank with the cross-encoder (ignored when comparing).
        category: Only search this category; None searches all.
        compare: Run every pipeline of `PIPELINES` and show them side by side.
        rewrite: Interpret the query with the LLM first (when one is configured).

    Returns:
        The results, or an alert when the parameters are invalid.
    """
    # The service validates too, but its messages are in English; the most common
    # mistake gets a Portuguese message here.
    if not query.strip():
        return error_alert("Digite uma pergunta para buscar.")
    try:
        if compare:
            # Without a loaded cross-encoder the "+ reordenação" column would just
            # repeat the hybrid one, so it is left out.
            pipelines = [
                pipeline
                for pipeline in PIPELINES
                if not pipeline.rerank or service.reranker_model is not None
            ]
            # The rewrite is cached by the service's rewriter, so the four pipelines
            # share one LLM call.
            responses = [
                (
                    pipeline,
                    service.search(
                        query,
                        top_k=top_k,
                        mode=pipeline.mode,
                        rerank=pipeline.rerank,
                        category=category,
                        rewrite=rewrite,
                    ),
                )
                for pipeline in pipelines
            ]
            return html.Div([*analysis_view(responses[0][1].analysis), comparison_view(responses)])
        response = service.search(
            query, top_k=top_k, mode=mode, rerank=rerank, category=category, rewrite=rewrite
        )
        return html.Div(results_view(response))
    except InvalidQueryError as exc:
        return error_alert(f"Não foi possível fazer a busca: {exc}")
