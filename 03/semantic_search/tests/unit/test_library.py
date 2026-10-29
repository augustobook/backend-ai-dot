"""Tests of the "Acervo" tab and of the read accessors it uses in the search service."""

from typing import Any

import dash_ag_grid as dag
import pytest
from dash import html
from dash.development.base_component import Component

from app.core.config import Settings
from app.core.exceptions import DocumentNotFoundError
from app.ingestion.chunker import Chunk
from app.llm.metadata import ChunkEnrichment
from app.services.search_service import SearchService
from app.ui import dash_app, library


def collect_text(node: Any) -> str:
    """Concatenate every string inside a component tree."""
    if isinstance(node, str):
        return node
    if isinstance(node, list | tuple):
        return " ".join(collect_text(child) for child in node)
    if isinstance(node, Component):
        return collect_text(getattr(node, "children", None))
    return ""


def find_by_class(node: Any, class_name: str) -> list[Component]:
    """Return every component whose className contains `class_name`."""
    found: list[Component] = []
    if isinstance(node, list | tuple):
        for child in node:
            found += find_by_class(child, class_name)
    elif isinstance(node, Component):
        if class_name in (getattr(node, "className", None) or "").split():
            found.append(node)
        found += find_by_class(getattr(node, "children", None), class_name)
    return found


def test_service_lists_documents_and_chunks_in_order(search_service: SearchService) -> None:
    """Documents come sorted by id and chunks in reading order."""
    ids = [document.id for document in search_service.documents]
    assert ids == sorted(ids) == ["act-01", "inf-01", "nut-01", "nut-02"]

    chunks = search_service.get_chunks("nut-01")
    assert [chunk.position for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.document_id == "nut-01" for chunk in chunks)
    assert sum(search_service.chunk_counts().values()) == search_service.manifest.chunk_count


def test_service_get_chunks_of_unknown_document_raises(search_service: SearchService) -> None:
    """An unknown id is a domain error, not an empty list."""
    with pytest.raises(DocumentNotFoundError):
        search_service.get_chunks("xyz-99")


def test_service_counts_tokens_with_the_embedder(search_service: SearchService) -> None:
    """Token counts come from the embedding model's tokenizer (words, for the fake)."""
    assert search_service.count_tokens("três palavras aqui") == 3


def test_document_rows_have_metadata_and_chunk_counts(search_service: SearchService) -> None:
    """Each row carries the metadata shown in the table."""
    rows = {row["id"]: row for row in library.document_rows(search_service)}

    row = rows["nut-01"]
    assert row["title"] == "Fibras na alimentação"
    assert row["category"] == "Nutrição"
    assert row["tags"] == "fibras, alimentação, intestino"
    assert row["chunks"] == len(search_service.get_chunks("nut-01"))
    assert row["retrieved"] == "29/10/2026"
    assert row["revision"] == "123"


def test_filter_rows_by_text_without_accents_and_by_category(
    search_service: SearchService,
) -> None:
    """The text filter ignores accents and case; the category filter is exact."""
    rows = library.document_rows(search_service)

    assert [row["id"] for row in library.filter_rows(rows, "HIDRATACAO", None)] == ["nut-02"]
    assert [row["id"] for row in library.filter_rows(rows, "mosquito", None)] == ["inf-01"]
    assert {row["id"] for row in library.filter_rows(rows, None, "nutrition")} == {
        "nut-01",
        "nut-02",
    }
    assert library.filter_rows(rows, "sono", "nutrition") == []
    assert len(library.filter_rows(rows, "  ", None)) == len(rows)


def test_document_detail_shows_metadata_and_every_chunk(search_service: SearchService) -> None:
    """The detail lists the front matter and one card per chunk, with its tokens."""
    detail = library.document_detail(search_service, "nut-01")
    text = collect_text(detail)
    chunks = search_service.get_chunks("nut-01")

    assert "nut-01-fibras-na-alimentacao.md" in text
    assert "CC BY-SA 4.0" in text
    assert "Plain-text extraction" in text
    cards = find_by_class(detail, "ss-chunk")
    assert len(cards) == len(chunks)
    assert f"Trecho 1 de {len(chunks)}" in collect_text(cards[0])
    assert f"{search_service.count_tokens(chunks[0].text)} tokens" in collect_text(cards[0])


def test_document_detail_of_unknown_document_warns(search_service: SearchService) -> None:
    """A stale id shows a warning instead of failing."""
    assert "xyz-99" in collect_text(library.document_detail(search_service, "xyz-99"))


def make_facts(search_service: SearchService, chunk: Chunk) -> library.ChunkFacts:
    """Build the metadata of a hand-made chunk of the article nut-01."""
    document = search_service.get_document("nut-01")
    prefix = f"{document.title}\n\n"
    return library.ChunkFacts(
        chunk=chunk,
        document=document,
        total=1,
        passage=chunk.text.removeprefix(prefix),
        has_title_prefix=chunk.text.startswith(prefix),
        tokens=5,
        indexed_tokens=9,
        token_budget=40,
        overlap_tokens=0,
    )


TEXT = "Fibras na alimentação\n\nO trecho."


def test_chunk_card_separates_the_title_prefix_from_the_passage(
    search_service: SearchService,
) -> None:
    """The title added by the chunker is shown apart from the article's text."""
    chunk = Chunk(chunk_id=1, document_id="nut-01", position=0, text=TEXT)

    card = library.chunk_card(make_facts(search_service, chunk))

    assert collect_text(find_by_class(card, "ss-chunk-prefix")) == "Fibras na alimentação"
    assert collect_text(find_by_class(card, "ss-chunk-text")) == "O trecho."
    assert not find_by_class(card, "ss-enrichment")


def test_chunk_card_lists_the_chunk_metadata(search_service: SearchService) -> None:
    """Every chunk shows its own and its inherited metadata."""
    chunk = Chunk(chunk_id=123, document_id="nut-01", position=0, text=TEXT)

    meta = collect_text(library.chunk_metadata(make_facts(search_service, chunk)))

    for expected in (
        "ID do trecho 123",
        "Artigo nut-01",
        "Posição 1 de 1",
        "Tokens 5 de 40 (12%)",
        "Tokens indexados 9",
        "Caracteres 9",
        "Palavras 2",
        "Título prefixado sim",
        "Categoria Nutrição",
        "Tags fibras, alimentação, intestino",
        "Enriquecido por LLM não",
        "Perguntas indexadas 0",
    ):
        assert expected in meta


def test_overlap_text_finds_the_repeated_start() -> None:
    """The overlap is the end of the previous passage repeated at the start."""
    previous = "Primeira frase do trecho. Esta frase se repete no próximo."
    current = "Esta frase se repete no próximo. E segue com texto novo."

    assert library.overlap_text(previous, current) == "Esta frase se repete no próximo."
    assert library.overlap_text("Texto sem relação nenhuma.", current) == ""
    # A repeat shorter than MIN_OVERLAP_CHARS is a coincidence, not an overlap.
    assert library.overlap_text("termina com Esta", "Esta frase") == ""


def test_chunk_facts_cover_every_chunk_in_order(search_service: SearchService) -> None:
    """Facts follow the reading order, the first chunk has no overlap."""
    document = search_service.get_document("nut-01")
    facts = library.chunk_facts(search_service, document)

    assert [fact.chunk.position for fact in facts] == list(range(len(facts)))
    assert facts[0].overlap_tokens == 0
    assert all(fact.has_title_prefix for fact in facts)
    assert all(fact.token_budget == search_service.manifest.chunk_max_tokens for fact in facts)
    assert all(fact.tokens == search_service.count_tokens(fact.chunk.text) for fact in facts)


def test_chunk_card_shows_the_llm_enrichment(search_service: SearchService) -> None:
    """An enriched chunk shows its context, content types, questions and terms."""
    enrichment = ChunkEnrichment(
        context="Trecho sobre o papel das fibras.",
        questions=["Para que servem as fibras?"],
        similar_terms=["prisão de ventre"],
        content_types=["diet", "prevention"],
    )
    chunk = Chunk(
        chunk_id=1,
        document_id="nut-01",
        position=0,
        text=TEXT,
        enrichment=enrichment,
    )

    text = collect_text(library.chunk_card(make_facts(search_service, chunk)))

    assert "Trecho sobre o papel das fibras." in text
    assert "Alimentação" in text and "Prevenção" in text
    assert "Para que servem as fibras?" in text
    assert "prisão de ventre" in text


def test_library_tab_has_table_and_warns_when_not_enriched(
    search_service: SearchService,
) -> None:
    """The tab shows every article in the table and says the chunks were not enriched."""
    tab = library.library_tab(search_service)

    grids = [node for node in _walk(tab) if isinstance(node, dag.AgGrid)]
    assert len(grids) == 1
    assert len(grids[0].to_plotly_json()["props"]["rowData"]) == len(search_service.documents)
    assert "não foram enriquecidos" in collect_text(tab)


def test_detail_for_selection_follows_the_selected_row(search_service: SearchService) -> None:
    """Selecting a row shows its article; an empty selection shows the hint."""
    detail = library.detail_for_selection(search_service, [{"id": "act-01"}])
    assert "Sono" in collect_text(detail)

    empty_selections: list[list[dict[str, Any]] | None] = [None, []]
    for selection in empty_selections:
        hint = library.detail_for_selection(search_service, selection)
        assert "Nenhum artigo selecionado" in collect_text(hint)


def test_app_has_tabs_and_library_callbacks(
    indexed_settings: Settings, search_service: SearchService
) -> None:
    """The page has both sections and the library callbacks are registered."""
    app = dash_app.create_app(indexed_settings, search_service)
    callbacks = " ".join(app.callback_map)

    assert "library-table.rowData" in callbacks
    assert "library-detail.children" in callbacks
    assert "search-section.hidden" in callbacks
    assert any(
        getattr(node, "id", None) == "library-section" and getattr(node, "hidden", False)
        for node in _walk(app.layout)
        if isinstance(node, html.Div)
    )


def _walk(node: Any) -> list[Component]:
    """Flatten a component tree."""
    found: list[Component] = []
    if isinstance(node, list | tuple):
        for child in node:
            found += _walk(child)
    elif isinstance(node, Component):
        found.append(node)
        found += _walk(getattr(node, "children", None))
    return found
