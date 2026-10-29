"""The `VectorStore` protocol.

The services only talk to this interface, so FAISS could be replaced by Milvus (or
any other vector database) by writing a new implementation, without touching the
indexing or search services.
"""

from collections.abc import Collection, Sequence
from pathlib import Path
from typing import Protocol, Self

from app.embeddings.base import Matrix, Vector


class VectorStore(Protocol):
    """Stores vectors under integer ids and finds the nearest ones to a query.

    Attributes:
        dimension: Size of the stored vectors.
    """

    dimension: int

    def add(self, ids: Sequence[int], vectors: Matrix) -> None:
        """Add vectors under the given ids.

        Args:
            ids: One unique id per vector (the chunk ids).
            vectors: `(len(ids), dimension)` float32 matrix.
        """
        ...

    def search(
        self, query: Vector, k: int, allowed_ids: Collection[int] | None = None
    ) -> list[tuple[int, float]]:
        """Return the `k` most similar vectors to the query.

        Args:
            query: `(dimension,)` query vector.
            k: Number of neighbors to return.
            allowed_ids: When given, only these ids are considered (pre-filter).

        Returns:
            `(id, score)` pairs sorted from most to least similar.
        """
        ...

    def save(self, directory: Path) -> None:
        """Persist the store into a directory.

        Args:
            directory: Target folder (must exist).
        """
        ...

    @classmethod
    def load(cls, directory: Path) -> Self:
        """Load a store previously written by `save`.

        Args:
            directory: Folder with the persisted store.

        Returns:
            The loaded store.
        """
        ...

    def count(self) -> int:
        """Return how many vectors are stored.

        Returns:
            The number of vectors.
        """
        ...
