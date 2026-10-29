"""The `Embedder` protocol.

The services depend on this interface instead of on `transformers`, so the real model
can be swapped (another library, a remote API) and the tests can use a fast,
deterministic fake.
"""

from collections.abc import Callable, Sequence
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

Vector = NDArray[np.float32]
"""A 1-D float32 embedding."""

Matrix = NDArray[np.float32]
"""A 2-D float32 array with one embedding per row."""

ProgressCallback = Callable[[int], None]
"""Called with the number of texts encoded since the previous call."""


class Embedder(Protocol):
    """Turns texts into L2-normalized vectors that live in the same space.

    Attributes:
        model_name: Identifier of the model (stored in the index manifest).
        model_revision: Pinned model revision, if any (stored in the manifest).
        dimension: Size of each vector.
        max_tokens: Token window used when encoding.
    """

    model_name: str
    model_revision: str | None
    dimension: int
    max_tokens: int

    def embed_documents(
        self, texts: Sequence[str], progress: ProgressCallback | None = None
    ) -> Matrix:
        """Embed passages for indexing.

        Args:
            texts: Passages to embed.
            progress: Optional callback receiving how many texts each batch encoded.

        Returns:
            A `(len(texts), dimension)` float32 matrix of unit vectors.
        """
        ...

    def embed_queries(
        self, texts: Sequence[str], progress: ProgressCallback | None = None
    ) -> Matrix:
        """Embed query-like texts in batches (the questions generated for each chunk).

        Args:
            texts: Questions to embed.
            progress: Optional callback receiving how many texts each batch encoded.

        Returns:
            A `(len(texts), dimension)` float32 matrix of unit vectors.
        """
        ...

    def embed_query(self, text: str) -> Vector:
        """Embed a search query.

        Args:
            text: The query.

        Returns:
            A `(dimension,)` float32 unit vector.
        """
        ...

    def count_tokens(self, text: str) -> int:
        """Count the tokens of a text with the model's tokenizer (no special tokens).

        Args:
            text: Any text.

        Returns:
            The number of tokens.
        """
        ...
