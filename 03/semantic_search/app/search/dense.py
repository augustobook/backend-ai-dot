"""Dense retriever: query embedding + k-NN search in the vector store.

It finds chunks by meaning: paraphrases, synonyms and even queries in another
language land close to the passage in the embedding space, with no word in common.

When the chunks were enriched, a second index holds the questions the LLM wrote for
each chunk. The query is searched in both, and each chunk keeps its best cosine:
its own vector or the closest of its questions. A user question is much closer to
"O que comer para soltar o intestino?" than to an encyclopedic paragraph about
dietary fiber, so the questions catch what the passage vector misses.
"""

from collections.abc import Collection, Sequence

from app.embeddings.base import Embedder
from app.ingestion.chunker import Chunk
from app.search.base import RetrievedChunk
from app.vector_store.base import VectorStore

# Questions fetched per requested chunk: each chunk has several questions, and the
# best ones of a few chunks would otherwise fill the whole list.
QUESTION_FANOUT = 3


class DenseRetriever:
    """Semantic retriever backed by an `Embedder` and a `VectorStore`.

    Args:
        embedder: Model that embeds the query (the same one used at indexing).
        store: Vector store with the chunk embeddings.
        question_store: Vector store with the generated questions, if any.
        chunks: The indexed chunks (to map each question back to its chunk).
    """

    name = "dense"

    def __init__(
        self,
        embedder: Embedder,
        store: VectorStore,
        question_store: VectorStore | None = None,
        chunks: Sequence[Chunk] = (),
    ) -> None:
        self._embedder = embedder
        self._store = store
        self._question_store = question_store
        # Question id -> (chunk id, question text).
        self._questions = {
            question_id: (chunk.chunk_id, text)
            for chunk in chunks
            for question_id, text in chunk.question_ids()
        }

    def retrieve(
        self, query: str, k: int, allowed_ids: Collection[int] | None = None
    ) -> list[RetrievedChunk]:
        """Return the `k` chunks closest to the query, best first.

        Args:
            query: The search query.
            k: Maximum number of chunks.
            allowed_ids: When given, only these chunks are considered.

        Returns:
            The nearest chunks with their cosine similarity (the best of the chunk
            vector and its question vectors).
        """
        vector = self._embedder.embed_query(query)
        best = {
            chunk_id: RetrievedChunk(chunk_id=chunk_id, score=score)
            for chunk_id, score in self._store.search(vector, k, allowed_ids)
        }
        if self._question_store is not None and self._questions:
            allowed_questions = (
                None
                if allowed_ids is None
                else [
                    question_id
                    for question_id, (chunk_id, _) in self._questions.items()
                    if chunk_id in allowed_ids
                ]
            )
            hits = self._question_store.search(vector, k * QUESTION_FANOUT, allowed_questions)
            for question_id, score in hits:
                chunk_id, text = self._questions[question_id]
                current = best.get(chunk_id)
                if current is None or score > current.score:
                    best[chunk_id] = RetrievedChunk(
                        chunk_id=chunk_id, score=score, matched_question=text
                    )
        return sorted(best.values(), key=lambda hit: -hit.score)[:k]
