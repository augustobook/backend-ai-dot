"""Fast, deterministic stand-ins for the real models.

They implement the `Embedder` and `Reranker` protocols, so the services run end to
end in the tests without downloading anything.
"""

import hashlib
from collections.abc import Sequence
from typing import Any, TypeVar

import numpy as np
from pydantic import BaseModel

from app.core.exceptions import LLMError
from app.embeddings.base import Matrix, ProgressCallback, Vector
from app.llm.metadata import ChunkEnrichment, ContentType, QueryAnalysis
from app.search.keyword import tokenize_pt

FAKE_DIMENSION = 64

T = TypeVar("T", bound=BaseModel)

# Popular vocabulary the fake enricher "knows" for each article of the mini dataset.
# None of these words appear in the articles, so only the enrichment can find them.
LAY_TERMS: dict[str, list[str]] = {
    "Fibras na alimentação": ["prisão de ventre", "intestino preso"],
    "Dengue": ["virose transmitida por pernilongo"],
}
LAY_QUESTIONS: dict[str, list[str]] = {
    "Fibras na alimentação": ["como soltar o intestino preso?"],
    "Dengue": ["quais os sinais da virose do pernilongo?"],
}
CONTENT_TYPES: dict[str, list[ContentType]] = {
    "Fibras na alimentação": ["diet"],
    "Dengue": ["symptoms"],
}


class FakeEmbedder:
    """Bag-of-words hashed into a fixed number of dimensions, then L2-normalized.

    Texts that share words get similar vectors, which is enough to test ranking,
    grouping and filtering. Tokens are counted as whitespace-separated words.
    """

    def __init__(self, model_name: str = "fake-embedder", batch_size: int = 4) -> None:
        self.model_name = model_name
        self.model_revision: str | None = None
        self.dimension = FAKE_DIMENSION
        self.max_tokens = 512
        self._batch_size = batch_size
        self.query_calls = 0

    def embed_documents(
        self, texts: Sequence[str], progress: ProgressCallback | None = None
    ) -> Matrix:
        """Embed passages, reporting progress per batch.

        Args:
            texts: Passages.
            progress: Optional per-batch callback.

        Returns:
            One unit vector per text.
        """
        vectors = np.zeros((len(texts), self.dimension), dtype=np.float32)
        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            for offset, text in enumerate(batch):
                vectors[start + offset] = self._vector(text)
            if progress is not None:
                progress(len(batch))
        return vectors

    def embed_queries(
        self, texts: Sequence[str], progress: ProgressCallback | None = None
    ) -> Matrix:
        """Embed questions the same way as passages (the fake has no prefixes).

        Args:
            texts: Questions.
            progress: Optional per-batch callback.

        Returns:
            One unit vector per text.
        """
        return self.embed_documents(texts, progress)

    def embed_query(self, text: str) -> Vector:
        """Embed a query.

        Args:
            text: The query.

        Returns:
            A unit vector.
        """
        self.query_calls += 1
        return self._vector(text)

    def count_tokens(self, text: str) -> int:
        """Count whitespace-separated words.

        Args:
            text: Any text.

        Returns:
            The number of words.
        """
        return len(text.split())

    def _vector(self, text: str) -> Vector:
        """Hash each token into a bucket and normalize.

        Args:
            text: Any text.

        Returns:
            A unit vector (the first axis when the text has no tokens).
        """
        vector = np.zeros(self.dimension, dtype=np.float32)
        for token in tokenize_pt(text):
            bucket = int(hashlib.sha1(token.encode()).hexdigest(), 16) % self.dimension
            vector[bucket] += 1.0
        norm = float(np.linalg.norm(vector))
        if norm == 0.0:
            vector[0] = 1.0
            return vector
        return vector / norm


class FakeEnricher:
    """Deterministic enrichment: lay terms and questions from `LAY_TERMS`/`LAY_QUESTIONS`.

    Args:
        model_name: Name stored in the manifest (change it to test rebuilds).
        fail_on: Titles whose chunks raise `LLMError`.
    """

    prompt_version = "1"

    def __init__(self, model_name: str = "fake-enricher", fail_on: set[str] | None = None) -> None:
        self.model_name = model_name
        self.calls: list[str] = []
        self._fail_on = fail_on or set()

    def enrich(self, title: str, passage: str) -> ChunkEnrichment:
        """Enrich a passage from the fixed vocabulary of its article.

        Args:
            title: Article title.
            passage: Passage text.

        Returns:
            The enrichment.

        Raises:
            LLMError: When the title is in `fail_on`.
        """
        self.calls.append(title)
        if title in self._fail_on:
            raise LLMError(f"fake failure for {title}")
        return ChunkEnrichment(
            context=f"Trecho do artigo {title}.",
            questions=[f"o que diz o artigo {title.lower()}?", *LAY_QUESTIONS.get(title, [])],
            similar_terms=LAY_TERMS.get(title, []),
            content_types=CONTENT_TYPES.get(title, ["other"]),
        )


class FakeQueryRewriter:
    """Returns a fixed analysis per query (the query itself when unknown).

    Args:
        analyses: Query -> analysis.
        fail: Raise `LLMError` on every call.
    """

    model_name = "fake-rewriter"

    def __init__(
        self, analyses: dict[str, QueryAnalysis] | None = None, fail: bool = False
    ) -> None:
        self._analyses = analyses or {}
        self._fail = fail
        self.calls: list[str] = []

    def analyze(self, query: str) -> QueryAnalysis:
        """Return the analysis registered for the query.

        Args:
            query: The query.

        Returns:
            The analysis.

        Raises:
            LLMError: When built with `fail=True`.
        """
        self.calls.append(query)
        if self._fail:
            raise LLMError("fake rewrite failure")
        return self._analyses.get(
            query,
            QueryAnalysis(
                rewritten_query=query,
                alternative_queries=[],
                similar_terms=[],
                categories=[],
                content_types=[],
            ),
        )


class FakeStructuredLLM:
    """`StructuredLLM` that returns a prepared answer and records the prompts.

    Args:
        answer: What `complete` returns (validated against the requested schema).
    """

    def __init__(self, answer: dict[str, Any], model_name: str = "fake-llm") -> None:
        self.model_name = model_name
        self._answer = answer
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, schema: type[T]) -> T:
        """Return the prepared answer as the requested schema.

        Args:
            system: Instructions.
            user: Input.
            schema: Pydantic model of the answer.

        Returns:
            The parsed answer.
        """
        self.calls.append((system, user))
        return schema.model_validate(self._answer)


class FakeReranker:
    """Scores a passage by the share of query tokens it contains."""

    model_name = "fake-reranker"

    def __init__(self) -> None:
        self.calls: list[int] = []

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        """Score passages by token overlap with the query.

        Args:
            query: The query.
            passages: Candidate passages.

        Returns:
            One score in [0, 1] per passage.
        """
        self.calls.append(len(passages))
        query_tokens = set(tokenize_pt(query))
        if not query_tokens:
            return [0.0 for _ in passages]
        return [
            len(query_tokens & set(tokenize_pt(passage))) / len(query_tokens)
            for passage in passages
        ]
