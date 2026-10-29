"""Tests of the web interface: components, query resolution and app wiring."""

from typing import Any

import dash_bootstrap_components as dbc
import pytest
from dash import dcc, html, no_update
from dash.development.base_component import Component
from flask import Flask

from app.core.config import Settings
from app.llm.metadata import QueryAnalysis
from app.services.artifacts import read_manifest
from app.services.search_service import SearchService
from app.ui import components, dash_app
from tests.conftest import build_enriched_service
from tests.fakes import FakeEmbedder, FakeQueryRewriter


def collect_text(node: Any) -> str:
    """Concatenate every string inside a component tree."""
    if isinstance(node, str):
        return node
    if isinstance(node, list | tuple):
        return " ".join(collect_text(child) for child in node)
    if isinstance(node, Component):
        texts = [collect_text(getattr(node, "children", None))]
        for prop in ("label", "title"):
            value = getattr(node, prop, None)
            if isinstance(value, str):
                texts.append(value)
        return " ".join(texts)
    return ""


def find_all(node: Any, kind: type[Component]) -> list[Component]:
    """Return every component of a given type inside a tree."""
    found: list[Component] = []
    if isinstance(node, list | tuple):
        for child in node:
            found += find_all(child, kind)
    elif isinstance(node, Component):
        if isinstance(node, kind):
            found.append(node)
        found += find_all(getattr(node, "children", None), kind)
    return found


def find_cards(node: Any) -> list[Component]:
    """Return the result cards inside a tree."""
    return [
        div
        for div in find_all(node, html.Div)
        if "ss-result" in (getattr(div, "className", None) or "")
    ]


def test_highlight_marks_query_terms_ignoring_accents_and_case() -> None:
    """Query terms are marked whatever their accents or case; stopwords are not."""
    parts = components.highlight("A Alimentação rica em fibras ajuda.", "alimentacao de FIBRAS")

    marked = [part.children for part in parts if isinstance(part, html.Mark)]
    assert marked == ["Alimentação", "fibras"]
    assert "".join(part if isinstance(part, str) else part.children for part in parts) == (
        "A Alimentação rica em fibras ajuda."
    )


def test_highlight_with_only_stopwords_returns_the_text() -> None:
    """A query without content words highlights nothing."""
    assert components.highlight("O sono é importante.", "de o a") == ["O sono é importante."]


def test_result_card_shows_title_category_tags_score_and_passage(
    search_service: SearchService,
) -> None:
    """The card carries every field the user needs to judge a result."""
    response = search_service.search("fibras intestino", top_k=1)
    result = response.results[0]

    card = components.result_card(result, response.query)
    text = collect_text(card)

    assert result.title in text
    assert "Nutrição" in text
    assert all(tag in text for tag in result.tags)
    assert components.format_decimal(result.score) in text
    assert find_all(card, html.Mark)
    # The passage leaves out the title the chunker prepended to the chunk.
    paragraph = find_all(card, html.P)[0]
    assert not collect_text(paragraph).startswith(result.title)


def test_compact_card_leaves_out_passage_and_tags(search_service: SearchService) -> None:
    """The comparison columns only show what matters for the ranking."""
    response = search_service.search("fibras intestino", top_k=1)
    card = components.result_card(response.results[0], response.query, compact=True)

    assert not find_all(card, html.P)
    assert len(find_all(card, dbc.Badge)) == 1


def test_stage_details_shows_dash_for_stages_that_did_not_run(
    search_service: SearchService,
) -> None:
    """A keyword search has no cosine, RRF or cross-encoder score."""
    response = search_service.search("dengue", top_k=1, mode="keyword", rerank=False)
    text = collect_text(components.stage_details(response.results[0]))

    # Three missing scores (cosine, RRF, cross-encoder) and three missing ranks.
    assert text.count(components.MISSING) == 6
    assert "Trecho 1 do artigo inf-01" in text
    # Each stage carries a short explanation of what its number means.
    assert all(description in text for description in components.STAGE_DESCRIPTIONS.values())


def test_results_view_with_no_results_shows_an_alert(search_service: SearchService) -> None:
    """An empty response says so instead of showing an empty area."""
    response = search_service.search("xyzabc", mode="keyword", rerank=False)
    view = components.results_view(response)

    assert find_all(view, dbc.Alert)
    assert "0 artigos encontrados" in collect_text(view)


def test_results_view_moves_low_relevance_results_to_a_collapsed_group(
    search_service: SearchService,
) -> None:
    """Confident results stay on top; the weak ones are gathered below, closed."""
    response = search_service.search("mosquito febre", top_k=4, rerank=True)
    view = components.results_view(response)

    groups = find_all(view, dbc.Accordion)
    low_group = [group for group in groups if getattr(group, "className", None) == "ss-low-group"]
    assert len(low_group) == 1
    assert getattr(low_group[0], "start_collapsed", None) is True
    assert not [alert for alert in find_all(view, dbc.Alert) if "confiável" in collect_text(alert)]
    # The confident card comes first, outside the group, without the badge.
    first = find_cards(view)[0]
    assert "Dengue" in collect_text(first)
    assert "baixa relevância" not in collect_text(first)
    assert "com baixa relevância" in collect_text(view)


def test_results_view_without_confident_results_warns_and_opens_the_group(
    search_service: SearchService,
) -> None:
    """When nothing reaches the threshold, the page says so before the weak results."""
    response = search_service.search("xyzabc", top_k=3, mode="semantic", rerank=True)
    assert response.results and all(result.relevant is False for result in response.results)

    view = components.results_view(response)

    assert "Nenhum resultado confiável" in collect_text(view)
    low_group = [
        group
        for group in find_all(view, dbc.Accordion)
        if getattr(group, "className", None) == "ss-low-group"
    ]
    assert getattr(low_group[0], "start_collapsed", None) is False
    assert all("ss-result-low" in getattr(card, "className", "") for card in find_cards(low_group))


def test_compact_view_keeps_the_ranking_and_marks_low_results(
    search_service: SearchService,
) -> None:
    """The comparison columns keep every card in order, flagging the weak ones."""
    response = search_service.search("mosquito febre", top_k=4, rerank=True)
    cards = find_cards(components.results_view(response, compact=True))

    assert len(cards) == len(response.results)
    flagged = ["ss-result-low" in getattr(card, "className", "") for card in cards]
    assert flagged == [result.relevant is False for result in response.results]


def test_score_meaning_depends_on_mode_and_rerank(search_service: SearchService) -> None:
    """The summary explains what the final score measures."""
    meanings = {
        components.score_meaning(search_service.search("sono", mode=mode, rerank=rerank))
        for mode, rerank in [
            ("semantic", False),
            ("keyword", False),
            ("hybrid", False),
            ("hybrid", True),
        ]
    }
    assert len(meanings) == 4


def test_render_search_compare_shows_one_column_per_pipeline(
    search_service: SearchService,
) -> None:
    """The comparison runs the four pipelines side by side."""
    view = components.render_search(search_service, "sono noite", 3, "hybrid", True, None, True)

    columns = find_all(view, dbc.Col)
    assert [collect_text(column.children[0]) for column in columns] == [
        pipeline.label for pipeline in components.PIPELINES
    ]


def test_render_search_compare_without_reranker_skips_rerank_column(
    indexed_settings: Settings, search_service: SearchService
) -> None:
    """Without a cross-encoder the "+ rerank" column would repeat the hybrid one."""
    search_service._reranker = None

    view = components.render_search(search_service, "sono", 3, "hybrid", True, None, True)

    assert len(find_all(view, dbc.Col)) == len(components.PIPELINES) - 1


def test_render_search_respects_category_and_top_k(search_service: SearchService) -> None:
    """The category filter and top_k reach the search service."""
    view = components.render_search(
        search_service, "fibras água sono dengue", 1, "hybrid", False, "nutrition", False
    )

    cards = find_cards(view)
    assert len(cards) == 1
    assert "Nutrição" in collect_text(cards[0])


def test_render_search_with_empty_query_asks_for_a_query(search_service: SearchService) -> None:
    """An empty query gets a Portuguese message, not a stack trace."""
    view = components.render_search(search_service, "  ", 5, "hybrid", True, None, False)

    assert isinstance(view, dbc.Alert)
    assert "Digite uma pergunta" in collect_text(view)


def test_render_search_turns_service_errors_into_an_alert(search_service: SearchService) -> None:
    """Any other validation error of the service is shown as an alert."""
    view = components.render_search(search_service, "sono", 5, "hybrid", True, "unknown", False)

    assert isinstance(view, dbc.Alert)
    assert "Não foi possível fazer a busca" in collect_text(view)


def test_category_label_and_decimal_formatting() -> None:
    """Categories get Portuguese names and numbers use the decimal comma."""
    assert components.category_label("chronic-diseases") == "Doenças crônicas"
    assert components.category_label("new-category") == "New category"
    assert components.format_decimal(0.8765) == "0,88"


def test_stats_panel_shows_manifest_information(indexed_settings: Settings) -> None:
    """The sidebar lists the model, the counts and the re-ranker."""
    manifest = read_manifest(indexed_settings.storage_dir)
    assert manifest is not None

    text = collect_text(components.stats_panel(manifest, "fake-reranker"))

    assert "fake-embedder" in text
    assert str(manifest.chunk_count) in text
    assert "fake-reranker" in text
    for hidden in ("Revisão", "Índice vetorial", "Criado em"):
        assert hidden not in text


def test_stats_panel_without_index() -> None:
    """Without an index the sidebar says so."""
    assert "Nenhum índice carregado" in collect_text(components.stats_panel(None, None))


def test_index_missing_alert_explains_how_to_ingest() -> None:
    """The alert shows the error and the ingestion command."""
    text = collect_text(components.index_missing_alert("No index found in storage."))

    assert "No index found in storage." in text
    assert "app.cli ingest" in text


def test_resolve_query_for_each_trigger() -> None:
    """Examples fill the query, explicit triggers always search, filters only refresh."""
    example = {"type": dash_app.EXAMPLE_BUTTON_TYPE, "index": 1}

    assert dash_app.resolve_query(example, "anything") == components.EXAMPLE_QUERIES[1]
    assert dash_app.resolve_query("search-button", None) == ""
    assert dash_app.resolve_query("query", "sono") == "sono"
    assert dash_app.resolve_query("mode", "sono") == "sono"
    assert dash_app.resolve_query("mode", "   ") is None
    assert dash_app.resolve_query("compare", None) is None


def test_create_app_with_service_has_controls_and_stats(
    indexed_settings: Settings, search_service: SearchService
) -> None:
    """The page has the search box, the category options and a search callback."""
    app = dash_app.create_app(indexed_settings, search_service)
    text = collect_text(app.layout)

    assert "Buscar" in text
    assert "Faça uma pergunta sobre saúde" in text
    assert "fake-embedder" in text
    assert "results.children" in " ".join(app.callback_map)


def test_create_app_without_index_shows_the_alert(settings: Settings) -> None:
    """Without an index the page starts and explains how to build it."""
    service, error = dash_app.load_search_service(settings)
    assert service is None
    assert error is not None

    app = dash_app.create_app(settings, None, error)

    assert find_all(app.layout, dbc.Alert)
    assert not app.callback_map


def test_handle_search_with_example_fills_the_query_and_shows_results(
    search_service: SearchService,
) -> None:
    """Clicking an example runs it and writes it into the search box."""
    example = {"type": dash_app.EXAMPLE_BUTTON_TYPE, "index": 0}

    view, query = dash_app.handle_search(
        search_service, example, None, 3, "hybrid", True, None, False
    )

    assert query == components.EXAMPLE_QUERIES[0]
    assert isinstance(view, html.Div)


def test_handle_search_ignores_filter_change_without_query(
    search_service: SearchService,
) -> None:
    """Moving a filter before typing anything does not search."""
    assert dash_app.handle_search(
        search_service, "top-k", None, 3, "hybrid", True, None, False
    ) == (no_update, no_update)


def test_create_server_loads_and_warms_up_the_service(
    monkeypatch: pytest.MonkeyPatch,
    indexed_settings: Settings,
    search_service: SearchService,
    embedder: FakeEmbedder,
) -> None:
    """The gunicorn factory loads the service once and runs the warm-up search."""
    calls: list[Settings] = []

    def fake_build(settings: Settings) -> SearchService:
        calls.append(settings)
        return search_service

    monkeypatch.setattr(dash_app, "get_settings", lambda: indexed_settings)
    monkeypatch.setattr(dash_app, "build_search_service", fake_build)

    server = dash_app.create_server()

    assert isinstance(server, Flask)
    assert calls == [indexed_settings]
    # The warm-up search embedded a query before any user did.
    assert embedder.query_calls == 1


def test_document_view_shows_the_full_body_and_attribution(search_service: SearchService) -> None:
    """The reader shows the whole article and the attribution the license requires."""
    document = search_service.get_document("nut-01")

    view = components.document_view(document)
    markdown = find_all(view, dcc.Markdown)

    assert markdown[0].children == document.body
    text = collect_text(view)
    assert "Nutrição" in text
    assert "CC BY-SA 4.0" in text
    assert "29/10/2026" in text


def test_handle_document_opens_the_clicked_article(search_service: SearchService) -> None:
    """A click on a title or button opens the reader with that article."""
    trigger = {"type": components.OPEN_DOCUMENT_TYPE, "document": "act-01", "key": "list-1-title"}

    is_open, title, body, link = dash_app.handle_document(search_service, trigger, clicked=True)

    assert is_open is True
    assert title == "Sono"
    assert find_all(body, dcc.Markdown)
    assert link == "https://pt.wikipedia.org/wiki/Sono"


def test_handle_document_ignores_new_buttons_without_clicks(search_service: SearchService) -> None:
    """Rendering a new list of results must not open the reader by itself."""
    trigger = {"type": components.OPEN_DOCUMENT_TYPE, "document": "act-01", "key": "list-1-title"}

    assert dash_app.handle_document(search_service, trigger, clicked=False) == (
        no_update,
        no_update,
        no_update,
        no_update,
    )


def test_handle_document_closes_and_handles_unknown_ids(search_service: SearchService) -> None:
    """The close button closes the reader; an unknown article shows a warning."""
    assert dash_app.handle_document(search_service, "document-close", clicked=True)[0] is False

    trigger = {"type": components.OPEN_DOCUMENT_TYPE, "document": "xyz-99", "key": "list-1-title"}
    is_open, title, body, _ = dash_app.handle_document(search_service, trigger, clicked=True)

    assert is_open is True
    assert title == "Artigo não encontrado"
    assert isinstance(body, dbc.Alert)


def test_open_document_ids_are_unique_in_the_comparison(search_service: SearchService) -> None:
    """The same article in several columns still gets distinct component ids."""
    view = components.render_search(search_service, "sono noite", 3, "hybrid", True, None, True)

    raw_ids = [getattr(button, "id", None) for button in find_all(view, html.Button)]
    ids = [str(sorted(raw.items())) for raw in raw_ids if isinstance(raw, dict)]
    assert ids
    assert len(ids) == len(set(ids))


def test_results_view_shows_how_the_query_was_interpreted(
    enriched_settings: Settings, embedder: FakeEmbedder
) -> None:
    """The rewrite, the similar terms and the metadata appear above the results."""
    rewriter = FakeQueryRewriter(
        {
            "zzz": QueryAnalysis(
                rewritten_query="mosquito febre",
                alternative_queries=["como pega a febre do mosquito"],
                similar_terms=["aedes"],
                categories=["infectious-diseases"],
                content_types=["symptoms"],
            )
        }
    )
    service = build_enriched_service(enriched_settings, embedder, rewriter=rewriter)

    text = collect_text(components.results_view(service.search("zzz", rerank=False)))

    assert "Pergunta interpretada como:" in text
    assert "Também buscado como:" in text and "como pega a febre do mosquito" in text
    for expected in ("mosquito febre", "aedes", "Doenças infecciosas e prevenção", "sintomas"):
        assert expected in text


def test_stage_details_show_the_enrichment_and_the_matched_question(
    enriched_settings: Settings, embedder: FakeEmbedder
) -> None:
    """The details explain why an enriched chunk was found."""
    service = build_enriched_service(enriched_settings, embedder)
    result = service.search(
        "como soltar o intestino preso?", mode="semantic", rerank=False
    ).results[0]

    text = collect_text(components.stage_details(result))

    assert "Pergunta que casou:" in text
    assert "prisão de ventre" in text
    assert "Perguntas que o trecho responde:" in text
    assert "alimentação" in text


def test_stats_panel_shows_the_llm_steps(enriched_settings: Settings) -> None:
    """The panel names the enrichment model, the questions and the rewriter."""
    manifest = read_manifest(enriched_settings.storage_dir)

    text = collect_text(components.stats_panel(manifest, None, "gpt-5-nano"))

    assert "fake-enricher" in text
    assert "Perguntas indexadas" in text
    assert "gpt-5-nano" in text
