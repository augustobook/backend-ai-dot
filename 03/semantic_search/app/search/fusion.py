"""Reciprocal Rank Fusion (RRF): merge rankings from different retrievers.

    score(chunk) = sum over retrievers of  weight_r / (k + rank_r(chunk))

Why ranks and not scores: a BM25 score has no upper bound and depends on the query
length, while a cosine lies in [-1, 1]. Adding them, or even min-max normalizing
them, lets one retriever dominate arbitrarily. RRF only looks at positions, so it
needs no calibration. The constant `k` (60 in the original paper) flattens the
curve: being 1st instead of 2nd matters, but a chunk ranked well by *both*
retrievers beats one ranked first by only one of them.

Worked example with k=60: a chunk 1st in dense and 3rd in BM25 gets
1/61 + 1/63 = 0.0323; a chunk 1st in dense and absent from BM25 gets 0.0164.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True)
class FusedChunk:
    """A chunk after fusion.

    Attributes:
        chunk_id: Id of the chunk.
        score: RRF score.
        ranks: 1-based rank of the chunk in each ranking where it appears.
    """

    chunk_id: int
    score: float
    ranks: dict[str, int] = field(default_factory=dict)


def reciprocal_rank_fusion(
    rankings: Mapping[str, Sequence[int]],
    k: int = 60,
    weights: Mapping[str, float] | None = None,
) -> list[FusedChunk]:
    """Fuse ranked lists of chunk ids with RRF.

    Args:
        rankings: Retriever name -> chunk ids sorted best first.
        k: RRF constant (must be positive).
        weights: Retriever name -> weight (1.0 for retrievers not listed).

    Returns:
        The fused chunks sorted by decreasing score. Ties are broken by the best
        individual rank and then by chunk id, so the order is deterministic.

    Raises:
        ValueError: If `k` is not positive.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    weights = weights or {}

    scores: dict[int, float] = {}
    ranks: dict[int, dict[str, int]] = {}
    for name, ranking in rankings.items():
        weight = weights.get(name, 1.0)
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + weight / (k + rank)
            ranks.setdefault(chunk_id, {})[name] = rank

    fused = [
        FusedChunk(chunk_id=chunk_id, score=score, ranks=ranks[chunk_id])
        for chunk_id, score in scores.items()
    ]
    fused.sort(key=lambda item: (-item.score, min(item.ranks.values()), item.chunk_id))
    return fused


def max_rrf_score(weights: Mapping[str, float], k: int = 60) -> float:
    """Return the highest RRF score possible: first place in every ranking.

    Dividing by this value maps RRF scores into [0, 1] with a meaning that holds
    across queries (1.0 = ranked first by every retriever).

    Args:
        weights: Weight of each retriever taking part in the fusion.
        k: RRF constant.

    Returns:
        The maximum attainable score.
    """
    return sum(weight / (k + 1) for weight in weights.values())
