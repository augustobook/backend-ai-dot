"""Tests of the retrieval metrics and of the evaluation set file."""

from pathlib import Path

import pytest

from app.evaluation import (
    EvalQuery,
    EvalReport,
    QueryOutcome,
    evaluate,
    first_relevant_rank,
    load_eval_set,
    markdown_table,
)
from app.ingestion.loader import list_document_files
from app.services.search_service import SearchService


def outcome(rank: int | None, top_relevant: bool | None = None) -> QueryOutcome:
    """Build an in-scope outcome with a given rank."""
    query = EvalQuery(id="q", kind="lay", query="x", relevant=["a"])
    return QueryOutcome(
        query=query, rank=rank, returned=[], latency_ms=10.0, top_relevant=top_relevant
    )


def out_of_scope(top_relevant: bool | None) -> QueryOutcome:
    """Build an out-of-scope outcome (nothing in the collection answers it)."""
    query = EvalQuery(id="o", kind="ood-far", query="y", relevant=[])
    return QueryOutcome(
        query=query, rank=None, returned=["b"], latency_ms=10.0, top_relevant=top_relevant
    )


def test_first_relevant_rank_takes_any_expected_article() -> None:
    """The first expected article counts, whichever it is."""
    assert first_relevant_rank(["x", "b", "a"], ["a", "b"]) == 2
    assert first_relevant_rank(["x", "y"], ["a"]) is None


def test_hit_rates_and_mrr() -> None:
    """hit@k counts ranks up to k; MRR averages 1/rank with 0 for misses."""
    report = EvalReport("test", [outcome(1), outcome(3), outcome(None), outcome(6)])

    assert report.hit_at(1) == 0.25
    assert report.hit_at(5) == 0.5
    assert report.mrr == pytest.approx((1 + 1 / 3 + 0 + 1 / 6) / 4)
    assert [o.rank for o in report.misses(5)] == [None, 6]
    assert report.mean_latency_ms == 10.0
    assert EvalReport("empty").hit_at(5) == 0.0


def test_out_of_scope_queries_stay_out_of_the_ranking_metrics() -> None:
    """Questions with no expected article measure the threshold, not hit@k or MRR."""
    report = EvalReport(
        "test",
        [
            outcome(1, top_relevant=True),
            outcome(1, top_relevant=False),
            outcome(2, top_relevant=True),
            out_of_scope(top_relevant=False),
            out_of_scope(top_relevant=False),
            out_of_scope(top_relevant=True),
        ],
    )

    assert report.hit_at(1) == pytest.approx(2 / 3)
    assert report.mrr == pytest.approx((1 + 1 + 0.5) / 3)
    assert report.misses(1) == [report.outcomes[2]]
    # Right first results: 2, one of them flagged as relevant.
    assert report.answers_shown == 0.5
    assert report.out_of_scope_blocked == pytest.approx(2 / 3)
    assert report.leaks() == [report.outcomes[5]]
    assert "| 50% | 67% |" in markdown_table([report])


def test_threshold_metrics_need_a_reranked_search() -> None:
    """Without the cross-encoder there is no relevance flag to measure."""
    report = EvalReport("test", [outcome(1), out_of_scope(None)])

    assert report.answers_shown is None
    assert report.out_of_scope_blocked is None
    assert markdown_table([report]).endswith("| — | — |")


def test_evaluate_runs_every_query(search_service: SearchService) -> None:
    """Each query goes through the search and its rank is recorded."""
    queries = [
        EvalQuery(id="q1", kind="exact", query="mosquito febre", relevant=["inf-01"]),
        EvalQuery(id="q2", kind="lay", query="xyzabc", relevant=["inf-01"]),
    ]

    report = evaluate(
        "keyword", queries, lambda query: search_service.search(query, mode="keyword")
    )

    assert [o.rank for o in report.outcomes] == [1, None]
    assert "| keyword | 0.50 | 0.50 | 0.500 |" in markdown_table([report])


def test_the_evaluation_set_points_to_existing_articles() -> None:
    """Every expected id is an article of the dataset, and ids are unique."""
    queries = load_eval_set(Path("data/eval/queries.json"))
    articles = {path.name[:6] for path in list_document_files(Path("data/documents"))}

    assert len(queries) >= 50
    assert len({query.id for query in queries}) == len(queries)
    assert all(query.relevant and set(query.relevant) <= articles for query in queries)


def test_the_holdout_set_is_valid_and_new() -> None:
    """The held-out set points to real articles and repeats no development question."""
    holdout = load_eval_set(Path("data/eval/holdout.json"))
    development = load_eval_set(Path("data/eval/queries.json"))
    articles = {path.name[:6] for path in list_document_files(Path("data/documents"))}

    assert len({query.id for query in holdout}) == len(holdout)
    assert all(set(query.relevant) <= articles for query in holdout)
    assert any(not query.in_scope for query in holdout)
    assert not {q.query.lower() for q in holdout} & {q.query.lower() for q in development}
