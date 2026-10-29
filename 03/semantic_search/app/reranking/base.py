"""The `Reranker` protocol.

The search service only needs "how relevant is this passage to this query", so the
cross-encoder can be swapped, and the tests use a fake based on word overlap.
"""

from collections.abc import Sequence
from typing import Protocol


class Reranker(Protocol):
    """Scores (query, passage) pairs by relevance.

    Attributes:
        model_name: Identifier of the model (shown in the stats).
    """

    model_name: str

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        """Score each passage against the query.

        Args:
            query: The search query.
            passages: Candidate passages.

        Returns:
            One relevance score in [0, 1] per passage, in the same order.
        """
        ...
