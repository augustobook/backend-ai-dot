"""Tests for the search service: modes, re-ranking, grouping, filters and validation."""

import pytest

from app.core.config import Settings
from app.core.exceptions import DocumentNotFoundError, InvalidQueryError, InvalidSearchModeError
from app.services.artifacts import IndexArtifacts, IndexManifest, load_artifacts
from app.services.search_service import SearchService
from app.vector_store.faiss_store import FaissVectorStore
from tests.fakes import FAKE_DIMENSION, FakeEmbedder, FakeReranker


@pytest.mark.parametrize("mode", ["semantic", "keyword", "hybrid"])
@pytest.mark.parametrize("rerank", [True, False])
def test_every_mode_finds_the_relevant_post(
    search_service: SearchService, mode: str, rerank: bool
) -> None:
    """All modes, with and without re-ranking, put the matching document first."""
    response = search_service.search("mosquito febre", mode=mode, rerank=rerank)

    assert response.results[0].document_id == "inf-01"
    assert response.mode == mode
    assert response.reranked is rerank
    assert all(0.0 <= result.score <= 1.0 for result in response.results)


def test_results_are_grouped_by_document(search_service: SearchService) -> None:
    """A document with several matching chunks appears only once."""
    response = search_service.search("fibras intestino saciedade", top_k=10, rerank=False)

    ids = [result.document_id for result in response.results]
    assert len(ids) == len(set(ids))
    assert [result.rank for result in response.results] == list(range(1, len(ids) + 1))


def test_hybrid_reports_stage_scores_and_ranks(search_service: SearchService) -> None:
    """Hybrid results carry dense, BM25 and RRF scores and both ranks."""
    result = search_service.search("eletrólitos", mode="hybrid", rerank=False).results[0]

    assert result.document_id == "nut-02"
    assert result.stage_scores.rrf is not None
    assert result.stage_scores.keyword is not None
    assert result.stage_ranks.keyword == 1
    assert result.stage_scores.rerank is None
    assert result.chunk_text.startswith("Hidratação")


def test_rerank_scores_only_the_configured_number_of_candidates(
    search_service: SearchService, reranker: FakeReranker, indexed_settings: Settings
) -> None:
    """The cross-encoder sees at most `rerank_candidates` passages."""
    result = search_service.search("sono", mode="semantic").results[0]

    assert reranker.calls and max(reranker.calls) <= indexed_settings.rerank_candidates
    assert result.stage_scores.rerank == result.score


def test_reranked_results_are_flagged_by_the_relevance_threshold(
    search_service: SearchService, indexed_settings: Settings
) -> None:
    """Only re-ranked results are judged; the others keep `relevant=None`."""
    reranked = search_service.search("mosquito febre", top_k=4, rerank=True).results
    plain = search_service.search("mosquito febre", top_k=4, rerank=False).results

    threshold = indexed_settings.relevance_threshold
    assert reranked[0].document_id == "inf-01"
    assert reranked[0].relevant is True
    assert [result.relevant for result in reranked] == [
        result.score >= threshold for result in reranked
    ]
    assert any(result.relevant is False for result in reranked)
    assert all(result.relevant is None for result in plain)


def test_category_filter_is_applied_before_ranking(search_service: SearchService) -> None:
    """Only documents of the category are returned, even for an off-topic query."""
    response = search_service.search("mosquito febre", category="nutrition", mode="semantic")

    assert response.results
    assert {result.category for result in response.results} == {"nutrition"}


def test_min_score_and_top_k_limit_the_results(search_service: SearchService) -> None:
    """Results below min_score are dropped and at most top_k are returned."""
    everything = search_service.search(
        "fibras alimentação", top_k=10, rerank=False, mode="semantic"
    )
    assert len(everything.results) > 1

    limited = search_service.search("fibras alimentação", top_k=1, rerank=False, mode="semantic")
    assert len(limited.results) == 1

    threshold = everything.results[0].score
    filtered = search_service.search(
        "fibras alimentação", top_k=10, rerank=False, mode="semantic", min_score=threshold
    )
    assert all(result.score >= threshold for result in filtered.results)
    assert len(filtered.results) < len(everything.results)


def test_keyword_scores_are_normalized_by_the_best_match(search_service: SearchService) -> None:
    """In keyword mode the best match has score 1.0."""
    response = search_service.search("mosquito", mode="keyword", rerank=False)

    assert response.results[0].score == 1.0
    assert response.results[0].stage_ranks.keyword == 1


def test_query_without_keyword_matches_returns_nothing_in_keyword_mode(
    search_service: SearchService,
) -> None:
    """BM25 finds nothing when no query term appears in the corpus."""
    assert search_service.search("xyzzy", mode="keyword").results == []


def test_defaults_come_from_the_settings(
    search_service: SearchService, indexed_settings: Settings
) -> None:
    """Without arguments, the configured mode, top_k and re-ranking are used."""
    response = search_service.search("  mosquito  ")

    assert response.query == "mosquito"
    assert response.mode == indexed_settings.default_search_mode
    assert response.top_k == indexed_settings.default_top_k
    assert response.reranked is True
    assert {"total", "dense", "keyword", "fusion", "rerank"} <= set(response.timings_ms)


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"query": "   "}, InvalidQueryError),
        ({"query": "x" * 501}, InvalidQueryError),
        ({"query": "mosquito", "top_k": 0}, InvalidQueryError),
        ({"query": "mosquito", "top_k": 11}, InvalidQueryError),
        ({"query": "mosquito", "min_score": 1.5}, InvalidQueryError),
        ({"query": "mosquito", "category": "astronomy"}, InvalidQueryError),
        ({"query": "mosquito", "mode": "fuzzy"}, InvalidSearchModeError),
    ],
)
def test_invalid_parameters_are_rejected(
    search_service: SearchService, kwargs: dict[str, object], error: type[Exception]
) -> None:
    """Empty or long queries, out-of-range values and unknown names are refused."""
    with pytest.raises(error):
        search_service.search(**kwargs)  # type: ignore[arg-type]


def test_documents_metadata_and_categories(search_service: SearchService) -> None:
    """The service exposes documents, categories, the manifest and the re-ranker."""
    assert search_service.get_document("nut-01").title == "Fibras na alimentação"
    with pytest.raises(DocumentNotFoundError):
        search_service.get_document("nope-01")
    assert search_service.categories == ["infectious-diseases", "nutrition", "sleep-exercise"]
    assert search_service.manifest.document_count == 4
    assert search_service.reranker_model == "fake-reranker"


def test_without_reranker_rerank_is_ignored(indexed_settings: Settings) -> None:
    """When no cross-encoder is loaded, re-ranking is reported as off."""
    service = SearchService(
        FakeEmbedder(), load_artifacts(indexed_settings.storage_dir), indexed_settings
    )

    response = service.search("mosquito", rerank=True)

    assert response.reranked is False
    assert service.reranker_model is None


def test_empty_index_returns_no_results(indexed_settings: Settings) -> None:
    """An index without chunks answers every search with an empty list."""
    loaded = load_artifacts(indexed_settings.storage_dir)
    manifest: IndexManifest = loaded.manifest.model_copy(
        update={"chunk_count": 0, "document_count": 0}
    )
    empty = IndexArtifacts(
        manifest=manifest, store=FaissVectorStore(FAKE_DIMENSION), chunks=[], documents=[]
    )
    service = SearchService(FakeEmbedder(), empty, indexed_settings, FakeReranker())

    for mode in ("semantic", "keyword", "hybrid"):
        assert service.search("mosquito", mode=mode).results == []
