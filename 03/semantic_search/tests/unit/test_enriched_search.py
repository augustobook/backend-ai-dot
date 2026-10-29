"""Tests of the search over an enriched index, with and without the query rewrite."""

from collections.abc import Sequence

import pytest

from app.core.config import Settings
from app.ingestion.chunker import PARAGRAPH_SEPARATOR
from app.llm.metadata import QueryAnalysis
from app.services.artifacts import load_artifacts
from tests.conftest import build_enriched_service
from tests.fakes import FakeEmbedder, FakeQueryRewriter, FakeReranker


class RecordingReranker(FakeReranker):
    """Fake cross-encoder that keeps the passages it was asked to score."""

    def __init__(self) -> None:
        super().__init__()
        self.passages: list[str] = []

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        """Record the passages, then score them like the fake."""
        self.passages.extend(passages)
        return super().score(query, passages)


def analysis(
    rewritten: str,
    terms: list[str] | None = None,
    alternatives: list[str] | None = None,
    categories: list[str] | None = None,
    content_types: list[str] | None = None,
) -> QueryAnalysis:
    """Build a query analysis for the fake rewriter."""
    return QueryAnalysis.model_validate(
        {
            "rewritten_query": rewritten,
            "alternative_queries": alternatives or [],
            "similar_terms": terms or [],
            "categories": categories or [],
            "content_types": content_types or [],
        }
    )


def test_lay_terms_of_the_enrichment_are_found_by_bm25(
    indexed_settings: Settings, enriched_settings: Settings, embedder: FakeEmbedder
) -> None:
    """ "prisão de ventre" is in no article, only in the enrichment of Fibras."""
    enriched = build_enriched_service(enriched_settings, embedder)

    response = enriched.search("prisão de ventre", mode="keyword", rerank=False)

    assert response.results[0].document_id == "nut-01"
    assert response.results[0].enrichment is not None


def test_plain_index_does_not_know_the_lay_terms(
    indexed_settings: Settings, embedder: FakeEmbedder
) -> None:
    """Without enrichment the same keyword search finds nothing."""
    plain = build_enriched_service(indexed_settings, embedder)

    assert plain.search("prisão de ventre", mode="keyword", rerank=False).results == []


def test_dense_search_matches_generated_questions(
    enriched_settings: Settings, embedder: FakeEmbedder
) -> None:
    """A query equal to a generated question wins through the question index."""
    service = build_enriched_service(enriched_settings, embedder)

    result = service.search(
        "como soltar o intestino preso?", mode="semantic", rerank=False
    ).results[0]

    assert result.document_id == "nut-01"
    assert result.matched_question == "como soltar o intestino preso?"
    assert result.stage_scores.dense == pytest.approx(1.0, abs=1e-4)


def test_category_filter_also_applies_to_the_question_index(
    enriched_settings: Settings, embedder: FakeEmbedder
) -> None:
    """Questions of other categories are never searched."""
    service = build_enriched_service(enriched_settings, embedder)

    response = service.search(
        "como soltar o intestino preso?", mode="semantic", rerank=False, category="sleep-exercise"
    )

    assert {result.category for result in response.results} == {"sleep-exercise"}


def test_rewritten_query_and_similar_terms_are_searched(
    enriched_settings: Settings, embedder: FakeEmbedder
) -> None:
    """A query with no useful word is found through its rewrite."""
    rewriter = FakeQueryRewriter({"zzz": analysis("mosquito febre", terms=["aedes"])})
    service = build_enriched_service(enriched_settings, embedder, rewriter=rewriter)

    for mode in ("semantic", "keyword", "hybrid"):
        response = service.search("zzz", mode=mode, rerank=False)
        assert response.results[0].document_id == "inf-01", mode
        assert response.analysis is not None
        assert response.analysis.rewritten_query == "mosquito febre"
    assert "rewrite" in response.timings_ms


def test_rewrite_can_be_turned_off_per_search(
    enriched_settings: Settings, embedder: FakeEmbedder
) -> None:
    """rewrite=False searches the query as typed and does not call the LLM."""
    rewriter = FakeQueryRewriter()
    service = build_enriched_service(enriched_settings, embedder, rewriter=rewriter)

    response = service.search("dengue", rewrite=False, rerank=False)

    assert response.analysis is None
    assert rewriter.calls == []
    assert service.query_rewriter_model == "fake-rewriter"


def test_a_failing_rewrite_does_not_stop_the_search(
    enriched_settings: Settings, embedder: FakeEmbedder
) -> None:
    """When the LLM fails, the query is searched as typed."""
    service = build_enriched_service(
        enriched_settings, embedder, rewriter=FakeQueryRewriter(fail=True)
    )

    response = service.search("mosquito febre", mode="semantic", rerank=False)

    assert response.analysis is None
    assert response.results[0].document_id == "inf-01"


def test_metadata_boost_raises_matching_candidates_only(
    enriched_settings: Settings, embedder: FakeEmbedder
) -> None:
    """Matching category and content type each add a share of the headroom."""
    rewriter = FakeQueryRewriter(
        {"febre": analysis("febre", categories=["infectious-diseases"], content_types=["symptoms"])}
    )
    service = build_enriched_service(enriched_settings, embedder, rewriter=rewriter)

    plain = {
        result.document_id: result
        for result in service.search("febre", mode="semantic", rerank=False, rewrite=False).results
    }
    boosted = {
        result.document_id: result
        for result in service.search("febre", mode="semantic", rerank=False).results
    }

    boost = enriched_settings.metadata_boost
    expected = plain["inf-01"].score
    for _ in range(2):  # category and content type both match
        expected += boost * (1 - expected)
    assert boosted["inf-01"].metadata_match is True
    assert boosted["inf-01"].score == pytest.approx(expected, abs=1e-3)
    others = [result for doc_id, result in boosted.items() if doc_id != "inf-01"]
    assert others and not any(result.metadata_match for result in others)
    assert all(result.score == plain[result.document_id].score for result in others)


def test_reranker_reads_the_original_passage_only(
    enriched_settings: Settings, embedder: FakeEmbedder
) -> None:
    """The cross-encoder never sees the LLM block appended for BM25.

    "prisão de ventre" only exists in the enrichment of Fibras: BM25 still finds the
    chunk, but the cross-encoder, reading the original passage, gives it no credit.
    """
    reranker = RecordingReranker()
    service = build_enriched_service(enriched_settings, embedder, reranker=reranker)

    result = service.search("prisão de ventre", mode="keyword", rerank=True).results[0]

    assert result.document_id == "nut-01"
    assert result.stage_scores.rerank == 0.0
    assert reranker.passages
    assert not any("Termos semelhantes:" in passage for passage in reranker.passages)


def test_chunk_vectors_embed_the_original_passage_only(
    enriched_settings: Settings, embedder: FakeEmbedder
) -> None:
    """The enrichment stays out of the chunk vector; its questions have their own."""
    artifacts = load_artifacts(enriched_settings.storage_dir)
    chunk = next(c for c in artifacts.chunks if c.document_id == "nut-01")

    def cosine_with_stored(text: str) -> float:
        vector = embedder.embed_documents([text])[0]
        hits = dict(artifacts.store.search(vector, len(artifacts.chunks)))
        return hits[chunk.chunk_id]

    assert cosine_with_stored(chunk.text) == pytest.approx(1.0, abs=1e-5)
    assert cosine_with_stored(chunk.search_text) < 0.999


def test_alternative_queries_are_searched_too(
    enriched_settings: Settings, embedder: FakeEmbedder
) -> None:
    """Multi-query: a useless rewrite is rescued by one of the alternatives."""
    rewriter = FakeQueryRewriter(
        {"zzz": analysis("yyy", alternatives=["xxx", "mosquito febre dengue"])}
    )
    service = build_enriched_service(enriched_settings, embedder, rewriter=rewriter)

    for mode in ("semantic", "keyword"):
        assert service.search("zzz", mode=mode, rerank=False).results[0].document_id == "inf-01"


def test_results_carry_the_neighbouring_chunks_without_repeating_the_overlap(
    enriched_settings: Settings, embedder: FakeEmbedder
) -> None:
    """context_text joins the chunk with its neighbors, title and overlap removed."""
    service = build_enriched_service(enriched_settings, embedder)
    chunks = [c for c in service._chunks.values() if c.document_id == "nut-01"]
    assert len(chunks) >= 3

    middle = sorted(chunks, key=lambda chunk: chunk.position)[1]
    context = service._context_text(middle)

    passages = [
        chunk.text.removeprefix(f"Fibras na alimentação{PARAGRAPH_SEPARATOR}")
        for chunk in sorted(chunks, key=lambda chunk: chunk.position)[:3]
    ]
    assert not context.startswith("Fibras na alimentação")
    for passage in passages:
        for paragraph in passage.split(PARAGRAPH_SEPARATOR):
            assert paragraph in context
            # Every paragraph appears once: the overlap was not repeated.
            assert context.count(paragraph) == 1


def test_context_neighbors_zero_keeps_only_the_chunk(
    enriched_settings: Settings, embedder: FakeEmbedder
) -> None:
    """With context_neighbors=0 the context is just the passage."""
    settings = enriched_settings.model_copy(update={"context_neighbors": 0})
    service = build_enriched_service(settings, embedder)

    result = service.search("dengue", mode="keyword", rerank=False).results[0]

    assert result.context_text == result.chunk_text.removeprefix(
        f"{result.title}{PARAGRAPH_SEPARATOR}"
    )
