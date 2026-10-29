"""Tests for Reciprocal Rank Fusion."""

import pytest

from app.search.fusion import max_rrf_score, reciprocal_rank_fusion


def test_rrf_formula_with_known_rankings() -> None:
    """Scores follow sum(weight / (k + rank))."""
    fused = reciprocal_rank_fusion({"dense": [1, 2], "keyword": [2, 3]}, k=60)

    scores = {item.chunk_id: item.score for item in fused}
    assert scores[1] == pytest.approx(1 / 61)
    assert scores[2] == pytest.approx(1 / 62 + 1 / 61)
    assert scores[3] == pytest.approx(1 / 62)


def test_chunk_ranked_by_both_retrievers_wins() -> None:
    """Agreement between retrievers beats a single first place."""
    fused = reciprocal_rank_fusion({"dense": [1, 2], "keyword": [2, 3]}, k=60)

    assert fused[0].chunk_id == 2
    assert fused[0].ranks == {"dense": 2, "keyword": 1}


def test_chunk_present_in_only_one_ranking_is_kept() -> None:
    """A chunk found by one retriever only still appears, with one rank."""
    fused = reciprocal_rank_fusion({"dense": [5], "keyword": []}, k=60)

    assert len(fused) == 1
    assert fused[0].ranks == {"dense": 1}


def test_weights_change_the_order() -> None:
    """A heavier retriever pulls its first place to the top."""
    rankings = {"dense": [1], "keyword": [2]}

    fused = reciprocal_rank_fusion(rankings, k=60, weights={"dense": 1.0, "keyword": 2.0})

    assert [item.chunk_id for item in fused] == [2, 1]


def test_ties_are_broken_deterministically() -> None:
    """Equal scores are ordered by best rank, then by chunk id."""
    fused = reciprocal_rank_fusion({"dense": [9], "keyword": [4]}, k=60)

    assert [item.chunk_id for item in fused] == [4, 9]


def test_invalid_k_and_max_score() -> None:
    """k must be positive; the ceiling is first place everywhere."""
    with pytest.raises(ValueError):
        reciprocal_rank_fusion({"dense": [1]}, k=0)
    assert max_rrf_score({"dense": 1.0, "keyword": 1.0}, k=60) == pytest.approx(2 / 61)
