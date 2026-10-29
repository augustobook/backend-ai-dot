"""Result models returned by the search service (and reused by the API)."""

from pydantic import BaseModel, Field

from app.core.config import SearchMode
from app.llm.metadata import ChunkEnrichment, QueryAnalysis


class StageScores(BaseModel):
    """Score of the matched chunk at each stage of the pipeline.

    A stage that did not run, or that did not retrieve the chunk, is `None`.

    Attributes:
        dense: Cosine similarity from FAISS.
        keyword: Raw BM25 score.
        rrf: Reciprocal Rank Fusion score.
        rerank: Cross-encoder relevance in [0, 1].
    """

    dense: float | None = None
    keyword: float | None = None
    rrf: float | None = None
    rerank: float | None = None


class StageRanks(BaseModel):
    """1-based position of the matched chunk in each first-stage ranking.

    Attributes:
        dense: Position in the FAISS ranking.
        keyword: Position in the BM25 ranking.
    """

    dense: int | None = None
    keyword: int | None = None


class SearchResult(BaseModel):
    """A document returned by a search, with the chunk that matched best.

    Attributes:
        rank: 1-based position in the results.
        document_id: Id of the document.
        title: Document title.
        author: Author of the text.
        category: Category slug.
        tags: Document tags.
        source_url: Page the text was taken from (attribution).
        license: License of the text.
        score: Final score in [0, 1] (see `SearchService.search` for its meaning).
        stage_scores: Scores of the matched chunk at each stage.
        stage_ranks: Positions of the matched chunk in the first-stage rankings.
        relevant: Whether the cross-encoder score reaches `relevance_threshold`;
            None when the search was not re-ranked (the other scores are only
            relative, so they cannot say whether a result answers the query).
        matched_question: Generated question of the chunk that matched the query
            best in the dense search, when it beat the chunk's own vector.
        metadata_match: Whether the chunk's category or content type matched the
            ones extracted from the query (and got the metadata boost).
        chunk_id: Id of the matched chunk.
        chunk_position: 0-based position of the chunk in the document.
        chunk_text: Text of the matched chunk.
        context_text: The chunk's passage joined with its neighbors in the article
            (`context_neighbors` on each side), for answers generated from the result.
        enrichment: What the LLM wrote about the chunk at ingestion, if anything.
    """

    rank: int
    document_id: str
    title: str
    author: str
    category: str
    tags: list[str]
    source_url: str
    license: str
    score: float = Field(ge=0.0, le=1.0)
    stage_scores: StageScores
    stage_ranks: StageRanks
    relevant: bool | None = None
    matched_question: str | None = None
    metadata_match: bool = False
    chunk_id: int
    chunk_position: int
    chunk_text: str
    context_text: str = ""
    enrichment: ChunkEnrichment | None = None


class SearchResponse(BaseModel):
    """Outcome of a search.

    Attributes:
        query: The query, stripped.
        mode: Retrievers used.
        reranked: Whether the cross-encoder re-ordered the candidates.
        top_k: Maximum number of documents requested.
        category: Category filter, if any.
        min_score: Score threshold, if any.
        results: Documents found, best first.
        timings_ms: Time spent in each stage, in milliseconds.
        analysis: How the LLM rewrote and understood the query; None when the
            rewrite was off or failed (the search then used the query as typed).
    """

    query: str
    mode: SearchMode
    reranked: bool
    top_k: int
    category: str | None
    min_score: float | None
    results: list[SearchResult]
    timings_ms: dict[str, float]
    analysis: QueryAnalysis | None = None
