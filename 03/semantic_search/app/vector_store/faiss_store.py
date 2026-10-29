"""FAISS vector store: exact cosine search with an `IndexIDMap2(IndexFlatIP)`.

Choices:
- `IndexFlatIP` compares the query with every vector (exact k-NN) using the inner
  product. The embeddings are L2-normalized, and for unit vectors the inner product
  *is* the cosine similarity, so the scores are cosines in [-1, 1].
- Exact search is the right call for a few hundred or thousand chunks: it is fast
  enough, needs no training and has perfect recall. Approximate indexes
  (`IndexHNSWFlat`, `IndexIVFFlat`) only pay off with hundreds of thousands of
  vectors, at the price of tuning (`efSearch`, `nprobe`) and some lost recall.
- `IndexIDMap2` stores our own 64-bit chunk ids instead of FAISS's sequential
  positions, so a hit maps straight to its chunk, and vectors can later be removed
  by id (`remove_ids`) or read back (`reconstruct`).
"""

import logging
from collections.abc import Collection, Sequence
from pathlib import Path
from typing import Self

import faiss
import numpy as np

from app.core.exceptions import IndexCorruptedError, IndexNotFoundError
from app.embeddings.base import Matrix, Vector

logger = logging.getLogger(__name__)

INDEX_FILE_NAME = "index.faiss"
QUESTIONS_INDEX_FILE_NAME = "questions.faiss"


class FaissVectorStore:
    """Exact inner-product (cosine) search over L2-normalized vectors.

    Args:
        dimension: Size of the vectors.
        index: An existing FAISS index (used by `load`); a new empty one when None.

    Raises:
        ValueError: If the dimension is not positive or does not match the index.
    """

    def __init__(self, dimension: int, index: faiss.Index | None = None) -> None:
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        if index is not None and index.d != dimension:
            raise ValueError(f"index dimension {index.d} does not match {dimension}")
        self.dimension = dimension
        self._index = (
            index if index is not None else faiss.IndexIDMap2(faiss.IndexFlatIP(dimension))
        )

    def add(self, ids: Sequence[int], vectors: Matrix) -> None:
        """Add vectors under the given ids.

        Args:
            ids: One unique id per vector (the chunk ids).
            vectors: `(len(ids), dimension)` float32 matrix.

        Raises:
            ValueError: If the shapes do not match or an id is repeated.
        """
        if vectors.ndim != 2 or vectors.shape[1] != self.dimension:
            raise ValueError(f"vectors must have shape (n, {self.dimension}), got {vectors.shape}")
        if len(ids) != vectors.shape[0]:
            raise ValueError("ids and vectors must have the same length")
        if len(set(ids)) != len(ids):
            raise ValueError("ids must be unique")
        # FAISS reads raw C memory: it needs contiguous float32 and int64 arrays.
        matrix = np.ascontiguousarray(vectors, dtype=np.float32)
        id_array = np.asarray(ids, dtype=np.int64)
        self._index.add_with_ids(matrix, id_array)

    def search(
        self, query: Vector, k: int, allowed_ids: Collection[int] | None = None
    ) -> list[tuple[int, float]]:
        """Return the `k` most similar vectors to the query.

        The optional `allowed_ids` filter is applied *inside* the search (an
        `IDSelectorBatch`), not afterwards. Filtering after fetching `k` neighbors
        could leave fewer than `k` results, or none, when most neighbors belong to
        other categories.

        Args:
            query: `(dimension,)` query vector.
            k: Number of neighbors to return.
            allowed_ids: When given, only these ids are considered.

        Returns:
            `(id, cosine)` pairs sorted from most to least similar.

        Raises:
            ValueError: If the query has the wrong dimension.
        """
        if query.shape != (self.dimension,):
            raise ValueError(f"query must have shape ({self.dimension},), got {query.shape}")
        if k <= 0 or self.count() == 0:
            return []

        params = None
        limit = self.count()
        if allowed_ids is not None:
            if not allowed_ids:
                return []
            selector = faiss.IDSelectorBatch(np.asarray(sorted(allowed_ids), dtype=np.int64))
            params = faiss.SearchParameters()
            params.sel = selector
            limit = min(limit, len(allowed_ids))

        matrix = np.ascontiguousarray(query.reshape(1, -1), dtype=np.float32)
        scores, ids = self._index.search(matrix, min(k, limit), params=params)
        # FAISS pads with id -1 when fewer than k vectors pass the filter.
        return [
            (int(chunk_id), float(score))
            for chunk_id, score in zip(ids[0], scores[0], strict=True)
            if chunk_id != -1
        ]

    def save(self, directory: Path, file_name: str = INDEX_FILE_NAME) -> None:
        """Persist the index as a file inside a directory.

        The index is serialized to bytes and written by Python, which avoids
        problems of the C++ writer with some file system paths.

        Args:
            directory: Target folder (must exist).
            file_name: Name of the file (`index.faiss` for the chunks).
        """
        path = directory / file_name
        path.write_bytes(faiss.serialize_index(self._index).tobytes())
        logger.info("Saved FAISS index with %d vectors to %s", self.count(), path)

    @classmethod
    def load(cls, directory: Path, file_name: str = INDEX_FILE_NAME) -> Self:
        """Load an index written by `save`.

        Args:
            directory: Folder with the index file.
            file_name: Name of the file (`index.faiss` for the chunks).

        Returns:
            The loaded store.

        Raises:
            IndexNotFoundError: If the file does not exist.
            IndexCorruptedError: If the file cannot be deserialized.
        """
        path = directory / file_name
        if not path.is_file():
            raise IndexNotFoundError(f"FAISS index not found: {path}")
        try:
            index = faiss.deserialize_index(np.frombuffer(path.read_bytes(), dtype=np.uint8))
        except RuntimeError as exc:
            raise IndexCorruptedError(f"Could not read the FAISS index {path}: {exc}") from exc
        return cls(dimension=int(index.d), index=index)

    def count(self) -> int:
        """Return how many vectors are stored.

        Returns:
            The number of vectors.
        """
        return int(self._index.ntotal)
