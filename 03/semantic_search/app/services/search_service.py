"""Search service: retrieval, fusion, re-ranking and grouping by document.

Pipeline of `search`:
1. Validate the parameters.
2. Optionally ask the LLM to rewrite the query in the articles' vocabulary and to
   extract its similar terms, categories and content types. When the LLM fails, the
   search goes on with the query as typed.
3. Retrieve `candidates_k` chunks from each retriever of the mode (dense, BM25 or
   both), already restricted to the requested category. The dense retriever runs
   the original query, the rewrite and the alternative formulations (multi-query;
   each chunk keeps its best cosine); BM25 runs all of them plus the similar terms.
4. In hybrid mode, fuse both rankings with Reciprocal Rank Fusion.
5. Boost the candidates whose category or content type matches the query's. It is a
   boost, never a filter: a wrong guess of the LLM must not hide the answer.
6. Optionally re-rank the best candidates with the cross-encoder.
7. Group by document, keeping each document's best chunk, so one long post cannot
   fill the whole result list with its own chunks.
8. Apply `min_score` and keep the `top_k` documents.
9. When re-ranked, flag the documents below `relevance_threshold` as low relevance:
   a small corpus always returns *something*, and the flag lets the interfaces say
   "nothing here really answers the query" instead of presenting noise as an answer.

Why fetch many more chunks than `top_k`: results are documents, but the indexes hold
chunks, and several of the best chunks often belong to the same post. Fetching more
leaves enough distinct documents after grouping, and gives fusion and re-ranking a
pool of candidates to work with.
"""

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TypeVar, cast, get_args

from app.core.config import SearchMode, Settings
from app.core.exceptions import (
    DocumentNotFoundError,
    InvalidQueryError,
    InvalidSearchModeError,
    LLMError,
)
from app.embeddings.base import Embedder
from app.ingestion.chunker import PARAGRAPH_SEPARATOR, Chunk
from app.ingestion.loader import Document
from app.llm.metadata import QueryAnalysis
from app.llm.query_rewriter import QueryRewriter
from app.reranking.base import Reranker
from app.search.base import RetrievedChunk, Retriever
from app.search.dense import DenseRetriever
from app.search.fusion import max_rrf_score, reciprocal_rank_fusion
from app.search.keyword import KeywordRetriever
from app.services.artifacts import IndexArtifacts, IndexManifest
from app.services.results import SearchResponse, SearchResult, StageRanks, StageScores

logger = logging.getLogger(__name__)

SEARCH_MODES: tuple[str, ...] = get_args(SearchMode)
SCORE_DECIMALS = 4

T = TypeVar("T")


@dataclass
class _Candidate:
    """A chunk moving through the pipeline, with what each stage said about it.

    Attributes:
        chunk_id: Id of the chunk.
        score: Score used to order the candidates at the current stage, in [0, 1].
        dense_score: Cosine from FAISS.
        keyword_score: Raw BM25 score.
        rrf_score: RRF score.
        rerank_score: Cross-encoder score.
        dense_rank: Position in the dense ranking.
        keyword_rank: Position in the BM25 ranking.
        matched_question: Generated question that gave the dense score, if any.
        metadata_match: Whether the metadata boost was applied.
    """

    chunk_id: int
    score: float
    dense_score: float | None = None
    keyword_score: float | None = None
    rrf_score: float | None = None
    rerank_score: float | None = None
    dense_rank: int | None = None
    keyword_rank: int | None = None
    matched_question: str | None = None
    metadata_match: bool = False


class SearchService:
    """Hybrid search over the indexed chunks, returning documents.

    Args:
        embedder: Embedding model (must be the one the index was built with).
        artifacts: Loaded index (vectors, questions, chunks, documents, manifest).
        settings: Search parameters (limits, candidates, RRF, BM25, boost).
        reranker: Cross-encoder; None disables re-ranking.
        query_rewriter: LLM that interprets the query; None searches it as typed.
    """

    def __init__(
        self,
        embedder: Embedder,
        artifacts: IndexArtifacts,
        settings: Settings,
        reranker: Reranker | None = None,
        query_rewriter: QueryRewriter | None = None,
    ) -> None:
        self._settings = settings
        self._manifest = artifacts.manifest
        self._embedder = embedder
        self._reranker = reranker
        self._query_rewriter = query_rewriter
        self._dense: Retriever = DenseRetriever(
            embedder, artifacts.store, artifacts.question_store, artifacts.chunks
        )
        self._keyword: Retriever = KeywordRetriever(
            artifacts.chunks, k1=settings.bm25_k1, b=settings.bm25_b
        )
        self._chunks = {chunk.chunk_id: chunk for chunk in artifacts.chunks}
        self._documents = {document.id: document for document in artifacts.documents}
        self._by_position = {
            (chunk.document_id, chunk.position): chunk for chunk in artifacts.chunks
        }

        # Chunk ids per category, so the category filter can be applied inside the
        # retrievers (pre-filter) instead of after them.
        by_category: dict[str, set[int]] = {}
        for chunk in artifacts.chunks:
            category = self._documents[chunk.document_id].category
            by_category.setdefault(category, set()).add(chunk.chunk_id)
        self._chunk_ids_by_category = {
            category: frozenset(ids) for category, ids in by_category.items()
        }

    @property
    def manifest(self) -> IndexManifest:
        """Return the manifest of the loaded index.

        Returns:
            How the index was built.
        """
        return self._manifest

    @property
    def reranker_model(self) -> str | None:
        """Return the cross-encoder in use.

        Returns:
            The model name, or None when re-ranking is disabled.
        """
        return self._reranker.model_name if self._reranker is not None else None

    @property
    def query_rewriter_model(self) -> str | None:
        """Return the LLM that rewrites the queries.

        Returns:
            The model name, or None when the rewrite is disabled.
        """
        return self._query_rewriter.model_name if self._query_rewriter is not None else None

    @property
    def categories(self) -> list[str]:
        """Return the categories present in the index.

        Returns:
            Sorted category slugs.
        """
        return sorted(self._chunk_ids_by_category)

    def get_document(self, document_id: str) -> Document:
        """Return a complete post.

        Args:
            document_id: Id of the post.

        Returns:
            The document.

        Raises:
            DocumentNotFoundError: If no post has this id.
        """
        try:
            return self._documents[document_id]
        except KeyError:
            raise DocumentNotFoundError(f"Document '{document_id}' not found") from None

    @property
    def documents(self) -> list[Document]:
        """Return every indexed post.

        Returns:
            The documents sorted by id.
        """
        return sorted(self._documents.values(), key=lambda document: document.id)

    def get_chunks(self, document_id: str) -> list[Chunk]:
        """Return the indexed chunks of a post, in reading order.

        Args:
            document_id: Id of the post.

        Returns:
            The chunks sorted by position.

        Raises:
            DocumentNotFoundError: If no post has this id.
        """
        self.get_document(document_id)
        return sorted(
            (chunk for chunk in self._chunks.values() if chunk.document_id == document_id),
            key=lambda chunk: chunk.position,
        )

    def chunk_counts(self) -> dict[str, int]:
        """Count the indexed chunks of every post.

        Returns:
            Document id -> number of chunks.
        """
        counts: dict[str, int] = {}
        for chunk in self._chunks.values():
            counts[chunk.document_id] = counts.get(chunk.document_id, 0) + 1
        return counts

    def count_tokens(self, text: str) -> int:
        """Count tokens with the tokenizer of the embedding model.

        Args:
            text: Any text.

        Returns:
            The number of tokens, without special tokens or prefixes.
        """
        return self._embedder.count_tokens(text)

    def search(
        self,
        query: str,
        top_k: int | None = None,
        mode: str | None = None,
        rerank: bool | None = None,
        min_score: float | None = None,
        category: str | None = None,
        rewrite: bool | None = None,
    ) -> SearchResponse:
        """Search the documents most relevant to a query.

        Meaning of the final `score` (always in [0, 1]):
        - with re-ranking: the cross-encoder relevance (the most reliable value for
          thresholds and to spot out-of-domain queries);
        - `semantic` without re-ranking: the cosine similarity (clamped at 0). It is
          not a probability: its typical range depends on the model;
        - `keyword` without re-ranking: BM25 divided by the best BM25 of the query;
        - `hybrid` without re-ranking: RRF divided by the highest RRF possible
          (1.0 = ranked first by both retrievers).

        Args:
            query: Search text.
            top_k: Number of documents (defaults to the configured value).
            mode: "semantic", "keyword" or "hybrid" (defaults to the configured value).
            rerank: Re-rank with the cross-encoder (defaults to on when it is loaded).
            min_score: Drop documents whose final score is below this value.
            category: Only search posts of this category.
            rewrite: Interpret the query with the LLM first (defaults to on when a
                rewriter is configured).

        Returns:
            The documents found, with scores and timings.

        Raises:
            InvalidQueryError: If a parameter is invalid.
            InvalidSearchModeError: If the mode is unknown.
        """
        started = time.perf_counter()
        settings = self._settings
        query = query.strip()
        top_k = settings.default_top_k if top_k is None else top_k
        resolved_mode = self._validate(query, top_k, mode, min_score, category)
        use_rerank = self._reranker is not None and (True if rerank is None else rerank)
        use_rewrite = self._query_rewriter is not None and (True if rewrite is None else rewrite)
        timings: dict[str, float] = {}

        allowed_ids = self._chunk_ids_by_category[category] if category is not None else None

        # Stage 1: the LLM interprets the query (None when off or failed).
        analysis = self._analyze(query, timings) if use_rewrite else None

        # Stage 2: first-stage retrieval (and fusion in hybrid mode), then the soft
        # metadata boost.
        candidates = self._retrieve(query, analysis, resolved_mode, allowed_ids, timings)
        if analysis is not None:
            candidates = self._boost(candidates, analysis)

        # Stage 3: re-ranking of the best candidates by the cross-encoder. It reads
        # the query together with its rewrite, so it also knows the technical terms.
        if use_rerank and candidates:
            rerank_query = query
            if analysis is not None and analysis.rewritten_query.lower() != query.lower():
                rerank_query = f"{query} ({analysis.rewritten_query})"
            candidates = self._rerank(rerank_query, candidates, timings)

        # Stage 4: one result per document, threshold and cut.
        results = self._to_results(candidates, top_k, min_score)

        timings["total"] = _elapsed_ms(started)
        logger.info(
            "Search mode=%s rerank=%s rewrite=%s category=%s -> %d results in %.1fms (%s)",
            resolved_mode,
            use_rerank,
            analysis is not None,
            category,
            len(results),
            timings["total"],
            ", ".join(f"{stage}={value:.1f}ms" for stage, value in timings.items()),
        )
        return SearchResponse(
            query=query,
            mode=resolved_mode,
            reranked=use_rerank,
            top_k=top_k,
            category=category,
            min_score=min_score,
            results=results,
            timings_ms={stage: round(value, 2) for stage, value in timings.items()},
            analysis=analysis,
        )

    def _analyze(self, query: str, timings: dict[str, float]) -> QueryAnalysis | None:
        """Ask the LLM to interpret the query, without letting a failure stop the search.

        Args:
            query: The query.
            timings: Receives the rewrite time.

        Returns:
            The analysis, or None when the LLM failed (the query is then used as typed).
        """
        assert self._query_rewriter is not None
        rewriter = self._query_rewriter
        try:
            return _timed(timings, "rewrite", lambda: rewriter.analyze(query))
        except LLMError as exc:
            logger.warning("Query rewrite failed; searching the query as typed: %s", exc)
            return None

    def _boost(self, candidates: list[_Candidate], analysis: QueryAnalysis) -> list[_Candidate]:
        """Raise the candidates whose category or content type matches the query's.

        Each match adds `metadata_boost` of the remaining headroom
        (`score + boost * (1 - score)`): the score stays in [0, 1], and the order only
        changes between candidates that were already close.

        Args:
            candidates: First-stage candidates.
            analysis: What the LLM extracted from the query.

        Returns:
            The candidates sorted again, best first.
        """
        boost = self._settings.metadata_boost
        wanted_categories = set(analysis.categories)
        wanted_types = set(analysis.content_types)
        if boost == 0 or not (wanted_categories or wanted_types):
            return candidates
        for candidate in candidates:
            chunk = self._chunks[candidate.chunk_id]
            matches = int(self._documents[chunk.document_id].category in wanted_categories)
            if chunk.enrichment is not None and wanted_types & set(chunk.enrichment.content_types):
                matches += 1
            for _ in range(matches):
                candidate.score += boost * (1.0 - candidate.score)
            candidate.metadata_match = matches > 0
        # sorted() is stable: equal scores keep the first-stage order.
        return sorted(candidates, key=lambda candidate: -candidate.score)

    def _validate(
        self,
        query: str,
        top_k: int,
        mode: str | None,
        min_score: float | None,
        category: str | None,
    ) -> SearchMode:
        """Check the search parameters.

        Args:
            query: Stripped query.
            top_k: Requested number of documents.
            mode: Requested mode, or None for the default.
            min_score: Requested threshold.
            category: Requested category.

        Returns:
            The mode to use.

        Raises:
            InvalidQueryError: If a parameter is invalid.
            InvalidSearchModeError: If the mode is unknown.
        """
        settings = self._settings
        if not query:
            raise InvalidQueryError("The query must not be empty.")
        if len(query) > settings.max_query_chars:
            raise InvalidQueryError(
                f"The query must have at most {settings.max_query_chars} characters."
            )
        if not 1 <= top_k <= settings.max_top_k:
            raise InvalidQueryError(f"top_k must be between 1 and {settings.max_top_k}.")
        if min_score is not None and not 0.0 <= min_score <= 1.0:
            raise InvalidQueryError("min_score must be between 0 and 1.")
        if category is not None and category not in self._chunk_ids_by_category:
            raise InvalidQueryError(
                f"Unknown category '{category}'. Available: {', '.join(self.categories)}."
            )
        resolved = settings.default_search_mode if mode is None else mode
        if resolved not in SEARCH_MODES:
            raise InvalidSearchModeError(
                f"Unknown search mode '{resolved}'. Use one of: {', '.join(SEARCH_MODES)}."
            )
        return cast(SearchMode, resolved)

    def _retrieve(
        self,
        query: str,
        analysis: QueryAnalysis | None,
        mode: SearchMode,
        allowed_ids: frozenset[int] | None,
        timings: dict[str, float],
    ) -> list[_Candidate]:
        """Run the first-stage retrievers of the mode.

        With an analysis, the dense retriever also runs the rewritten query (each
        chunk keeps its best cosine), and BM25 searches the query, the rewrite and
        the similar terms together.

        Args:
            query: The query.
            analysis: What the LLM understood from the query, if anything.
            mode: Which retrievers to use.
            allowed_ids: Category pre-filter.
            timings: Receives the time of each retriever and of the fusion.

        Returns:
            Candidates ordered by their first-stage score, best first.
        """
        k = self._settings.candidates_k
        dense_queries = [query]
        keyword_query = query
        if analysis is not None:
            # Multi-query: the rewrite and every alternative formulation are searched;
            # each chunk keeps its best cosine over all of them.
            for variant in (analysis.rewritten_query, *analysis.alternative_queries):
                if variant.lower() not in {text.lower() for text in dense_queries}:
                    dense_queries.append(variant)
            keyword_query = " ".join([*dense_queries, *analysis.similar_terms])

        dense: list[RetrievedChunk] = []
        keyword: list[RetrievedChunk] = []
        if mode in ("semantic", "hybrid"):
            dense = _timed(
                timings,
                "dense",
                lambda: _best_per_chunk(
                    [self._dense.retrieve(text, k, allowed_ids) for text in dense_queries], k
                ),
            )
        if mode in ("keyword", "hybrid"):
            keyword = _timed(
                timings, "keyword", lambda: self._keyword.retrieve(keyword_query, k, allowed_ids)
            )

        if mode == "semantic":
            # Cosine lies in [-1, 1]; negative values mean "unrelated" and become 0.
            return [
                _Candidate(
                    chunk_id=hit.chunk_id,
                    score=min(max(hit.score, 0.0), 1.0),
                    dense_score=hit.score,
                    dense_rank=rank,
                    matched_question=hit.matched_question,
                )
                for rank, hit in enumerate(dense, start=1)
            ]
        if mode == "keyword":
            # BM25 has no upper bound; dividing by the best score of this query maps
            # it to [0, 1] (the best keyword match gets 1.0).
            best = keyword[0].score if keyword else 1.0
            return [
                _Candidate(
                    chunk_id=hit.chunk_id,
                    score=hit.score / best,
                    keyword_score=hit.score,
                    keyword_rank=rank,
                )
                for rank, hit in enumerate(keyword, start=1)
            ]

        started = time.perf_counter()
        settings = self._settings
        weights = {"dense": settings.rrf_dense_weight, "keyword": settings.rrf_keyword_weight}
        fused = reciprocal_rank_fusion(
            {
                "dense": [hit.chunk_id for hit in dense],
                "keyword": [hit.chunk_id for hit in keyword],
            },
            k=settings.rrf_k,
            weights=weights,
        )
        ceiling = max_rrf_score(weights, settings.rrf_k)
        dense_hits = {hit.chunk_id: hit for hit in dense}
        keyword_scores = {hit.chunk_id: hit.score for hit in keyword}
        candidates = [
            _Candidate(
                chunk_id=item.chunk_id,
                score=min(item.score / ceiling, 1.0),
                dense_score=dense_hit.score if dense_hit else None,
                keyword_score=keyword_scores.get(item.chunk_id),
                rrf_score=item.score,
                dense_rank=item.ranks.get("dense"),
                keyword_rank=item.ranks.get("keyword"),
                matched_question=dense_hit.matched_question if dense_hit else None,
            )
            for item in fused
            for dense_hit in [dense_hits.get(item.chunk_id)]
        ]
        timings["fusion"] = _elapsed_ms(started)
        return candidates

    def _rerank(
        self, query: str, candidates: list[_Candidate], timings: dict[str, float]
    ) -> list[_Candidate]:
        """Re-order the best candidates with the cross-encoder.

        Only the first `rerank_candidates` are scored (the cross-encoder costs one
        forward pass per pair); the rest are dropped, since their scores would not be
        comparable with the cross-encoder scores.

        Args:
            query: The query.
            candidates: First-stage candidates, best first.
            timings: Receives the re-ranking time.

        Returns:
            The scored candidates, best first.
        """
        assert self._reranker is not None
        reranker = self._reranker
        pool = candidates[: self._settings.rerank_candidates]
        # The enriched text: its context and questions tell the cross-encoder what a
        # passage is about when the passage alone does not name its subject.
        passages = [self._chunks[candidate.chunk_id].search_text for candidate in pool]
        scores = _timed(timings, "rerank", lambda: reranker.score(query, passages))

        for candidate, score in zip(pool, scores, strict=True):
            candidate.rerank_score = score
            candidate.score = min(max(score, 0.0), 1.0)
        # sorted() is stable: equal scores keep the first-stage order.
        return sorted(pool, key=lambda candidate: -candidate.score)

    def _to_results(
        self, candidates: Sequence[_Candidate], top_k: int, min_score: float | None
    ) -> list[SearchResult]:
        """Group candidates by document and build the results.

        Args:
            candidates: Candidates sorted best first.
            top_k: Maximum number of documents.
            min_score: Score threshold.

        Returns:
            Up to `top_k` results, one per document.
        """
        results: list[SearchResult] = []
        seen: set[str] = set()
        for candidate in candidates:
            chunk: Chunk = self._chunks[candidate.chunk_id]
            # Candidates are sorted, so the first chunk of a document is its best one.
            if chunk.document_id in seen:
                continue
            seen.add(chunk.document_id)
            if min_score is not None and candidate.score < min_score:
                # Sorted by score: every remaining candidate is below the threshold too.
                break
            document = self._documents[chunk.document_id]
            results.append(
                SearchResult(
                    rank=len(results) + 1,
                    document_id=document.id,
                    title=document.title,
                    author=document.author,
                    category=document.category,
                    tags=document.tags,
                    source_url=str(document.source_url),
                    license=document.license,
                    score=round(candidate.score, SCORE_DECIMALS),
                    stage_scores=StageScores(
                        dense=_round(candidate.dense_score),
                        keyword=_round(candidate.keyword_score),
                        rrf=_round(candidate.rrf_score),
                        rerank=_round(candidate.rerank_score),
                    ),
                    stage_ranks=StageRanks(
                        dense=candidate.dense_rank, keyword=candidate.keyword_rank
                    ),
                    relevant=(
                        None
                        if candidate.rerank_score is None
                        else candidate.score >= self._settings.relevance_threshold
                    ),
                    matched_question=candidate.matched_question,
                    metadata_match=candidate.metadata_match,
                    chunk_id=chunk.chunk_id,
                    chunk_position=chunk.position,
                    chunk_text=chunk.text,
                    context_text=self._context_text(chunk),
                    enrichment=chunk.enrichment,
                )
            )
            if len(results) == top_k:
                break
        return results

    def _context_text(self, chunk: Chunk) -> str:
        """Join a chunk with its neighbors in the article (small-to-big).

        The search ranks small chunks, which keeps the match precise; an answer
        generated from the result needs more context than one chunk, so the result
        also carries `context_neighbors` chunks on each side, in order, with the title
        and the repeated overlap removed.

        Args:
            chunk: The matched chunk.

        Returns:
            The passage of the chunk and of its neighbors.
        """
        title = self._documents[chunk.document_id].title
        span = self._settings.context_neighbors
        passages = [
            neighbor.text.removeprefix(f"{title}{PARAGRAPH_SEPARATOR}")
            for position in range(chunk.position - span, chunk.position + span + 1)
            if (neighbor := self._by_position.get((chunk.document_id, position))) is not None
        ]
        text = passages[0]
        for passage in passages[1:]:
            text = _join_without_overlap(text, passage)
        return text


def _join_without_overlap(first: str, second: str) -> str:
    """Join two consecutive passages, dropping the overlap the chunker repeated.

    A chunk that continues a section starts with the last sentences of the previous
    chunk, as a paragraph of its own. The longest opening of `second` that ends at a
    paragraph boundary and that `first` ends with is that overlap.

    Args:
        first: The earlier passage.
        second: The next passage.

    Returns:
        Both passages, separated by a blank line, without the repetition.
    """
    boundaries = [index for index in range(len(second)) if second.startswith("\n\n", index)]
    for end in sorted(boundaries, reverse=True):
        if first.endswith(second[:end]):
            second = second[end:].lstrip("\n")
            break
    return f"{first}{PARAGRAPH_SEPARATOR}{second}" if second else first


def _best_per_chunk(rankings: Sequence[list[RetrievedChunk]], k: int) -> list[RetrievedChunk]:
    """Merge the dense rankings of several query variants, keeping each chunk's best hit.

    Cosines of different queries against the same index are on the same scale, so
    the maximum is a fair "how close is this chunk to any reading of the query".

    Args:
        rankings: One ranking per query variant.
        k: Maximum number of chunks.

    Returns:
        Up to `k` chunks sorted by decreasing best cosine.
    """
    if len(rankings) == 1:
        return rankings[0][:k]
    best: dict[int, RetrievedChunk] = {}
    for ranking in rankings:
        for hit in ranking:
            if hit.chunk_id not in best or hit.score > best[hit.chunk_id].score:
                best[hit.chunk_id] = hit
    return sorted(best.values(), key=lambda hit: -hit.score)[:k]


def _timed[T](timings: dict[str, float], stage: str, func: Callable[[], T]) -> T:
    """Run a function and record how long it took.

    Args:
        timings: Receives the elapsed time under `stage`.
        stage: Name of the stage.
        func: Function to run.

    Returns:
        What the function returned.
    """
    started = time.perf_counter()
    result = func()
    timings[stage] = _elapsed_ms(started)
    return result


def _elapsed_ms(started: float) -> float:
    """Return the milliseconds elapsed since `started`.

    Args:
        started: A `time.perf_counter()` value.

    Returns:
        Elapsed milliseconds.
    """
    return (time.perf_counter() - started) * 1000


def _round(value: float | None) -> float | None:
    """Round an optional score for display.

    Args:
        value: Score or None.

    Returns:
        The rounded score, or None.
    """
    return None if value is None else round(value, SCORE_DECIMALS)
