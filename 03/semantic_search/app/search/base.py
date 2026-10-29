"""The `Retriever` protocol and the ranked hit it returns.

The search service combines retrievers without knowing how each one works: the
dense retriever (embeddings + FAISS) and the keyword retriever (BM25) expose the
same interface and are fused by rank.
"""

from collections.abc import Collection
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RetrievedChunk:
    """A chunk returned by a retriever.

    Attributes:
        chunk_id: Id of the chunk.
        score: Retriever-specific score (cosine for dense, BM25 for keyword).
        matched_question: Generated question whose vector gave the dense score, when
            it beat the chunk's own vector.
    """

    chunk_id: int
    score: float
    matched_question: str | None = None


class Retriever(Protocol):
    """Finds the chunks that best match a query.

    Attributes:
        name: Short identifier used in rankings and logs ("dense", "keyword").
    """

    name: str

    def retrieve(
        self, query: str, k: int, allowed_ids: Collection[int] | None = None
    ) -> list[RetrievedChunk]:
        """Return up to `k` chunks, best first.

        Args:
            query: The search query.
            k: Maximum number of chunks.
            allowed_ids: When given, only these chunks are considered (pre-filter).

        Returns:
            The retrieved chunks sorted by decreasing score.
        """
        ...
