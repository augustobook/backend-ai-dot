"""Keyword retriever: BM25 over the same chunks indexed in FAISS.

BM25 scores a chunk by how many query terms it contains, weighting rare terms
(high IDF) more than common ones, saturating repeated terms (`k1`) and normalizing
by chunk length (`b`). It has no notion of meaning: "aposentadoria" does not match
"previdência". That is exactly why it complements the dense retriever: it is strong
on exact terms, names and identifiers (`defaultdict`, "regra dos 72"), where an
embedding may blur the term into a broader topic.
"""

import math
import re
import unicodedata
from collections.abc import Collection, Sequence

import numpy as np
from rank_bm25 import BM25Okapi

from app.ingestion.chunker import Chunk
from app.search.base import RetrievedChunk
from app.search.stopwords_pt import STOPWORDS_PT

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


class _PositiveIdfBM25(BM25Okapi):  # type: ignore[misc]
    """BM25 Okapi with the always-positive IDF used by Lucene/Elasticsearch.

    The classic Okapi IDF, `log((N - n + 0.5) / (n + 0.5))`, is zero or negative for
    terms present in half the chunks or more. In a blog whose posts are grouped by
    topic, a term such as "python" appears in most chunks of its category, and a
    query for it would then score those chunks at zero or below. Adding 1 inside the
    logarithm keeps every matching term worth something, rare terms still more.
    """

    def _calc_idf(self, nd: dict[str, int]) -> None:
        """Compute `log(1 + (N - n + 0.5) / (n + 0.5))` for every term.

        Args:
            nd: Term -> number of chunks that contain it.
        """
        for term, frequency in nd.items():
            self.idf[term] = math.log(1 + (self.corpus_size - frequency + 0.5) / (frequency + 0.5))


def normalize_text(text: str) -> str:
    """Lowercase a text and strip its accents.

    NFKD decomposition separates each accented letter into the base letter and a
    combining mark; dropping the marks turns "ação" into "acao". Users often type
    without accents, so both forms must produce the same token.

    Args:
        text: Any text.

    Returns:
        The lowercased text without accents.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return stripped.lower()


def tokenize_pt(text: str) -> list[str]:
    """Tokenize Portuguese text for BM25.

    Lowercase, no accents, alphanumeric tokens, Portuguese stopwords removed, no
    stemming. The same function is applied to chunks and queries, so both sides of
    the comparison are normalized identically.

    Stemming (Snowball) was evaluated and left out: on the evaluation set it lowered
    hit@5 from 0.85 to 0.77 for BM25 and from 0.90 to 0.83 for the hybrid search. In
    a small collection, reducing words to stems ("comer" and "coma" both become
    "com") makes the common words of a query match far too many chunks.

    Args:
        text: Any text.

    Returns:
        The tokens in order.
    """
    return [
        token for token in TOKEN_PATTERN.findall(normalize_text(text)) if token not in STOPWORDS_PT
    ]


class KeywordRetriever:
    """BM25 (Okapi) retriever over in-memory chunks.

    Args:
        chunks: Chunks to index (the same ones stored in FAISS).
        k1: Term-frequency saturation.
        b: Length normalization.
    """

    name = "keyword"

    def __init__(self, chunks: Sequence[Chunk], k1: float = 1.5, b: float = 0.75) -> None:
        self._chunk_ids = [chunk.chunk_id for chunk in chunks]
        # The enrichment (similar terms, questions) is indexed too: it is what brings
        # the users' vocabulary ("prisão de ventre") to an article that never uses it.
        corpus = [tokenize_pt(chunk.search_text) for chunk in chunks]
        # rank-bm25 divides by the corpus size, so an empty corpus gets no model.
        self._bm25 = _PositiveIdfBM25(corpus, k1=k1, b=b) if corpus else None

    def retrieve(
        self, query: str, k: int, allowed_ids: Collection[int] | None = None
    ) -> list[RetrievedChunk]:
        """Return up to `k` chunks that share terms with the query, best first.

        Chunks with score 0 (no query term at all) are not returned: they are not
        keyword matches, and keeping them would add arbitrary chunks to the fusion.

        Args:
            query: The search query.
            k: Maximum number of chunks.
            allowed_ids: When given, only these chunks are considered.

        Returns:
            The matching chunks sorted by decreasing BM25 score.
        """
        tokens = tokenize_pt(query)
        if self._bm25 is None or not tokens or k <= 0:
            return []

        scores = np.asarray(self._bm25.get_scores(tokens), dtype=np.float64)
        if allowed_ids is not None:
            mask = np.fromiter(
                (chunk_id in allowed_ids for chunk_id in self._chunk_ids),
                dtype=bool,
                count=len(self._chunk_ids),
            )
            scores = np.where(mask, scores, 0.0)

        # Stable sort on the negated scores: ties keep the chunk order.
        order = np.argsort(-scores, kind="stable")
        return [
            RetrievedChunk(chunk_id=self._chunk_ids[index], score=float(scores[index]))
            for index in order[:k]
            if scores[index] > 0
        ]
