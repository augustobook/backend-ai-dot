"""Centralized application settings loaded from environment variables and `.env`.

Every tunable value (models, chunking, retrieval and re-ranking parameters, paths,
device) lives here, so the rest of the code never reads `os.environ` directly.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SearchMode = Literal["semantic", "keyword", "hybrid"]
"""Which retrievers a search uses: dense only, BM25 only, or both fused with RRF."""

# Tokens reserved inside the model window for the special tokens ([CLS]/[SEP] or
# <s>/</s>) and the "passage: " prefix that the E5 family expects. The chunker never
# fills this margin, so a chunk is never silently truncated by the tokenizer.
EMBEDDING_TOKEN_MARGIN = 16


class Settings(BaseSettings):
    """Application settings.

    Values are read (case-insensitively) from environment variables first and then
    from a local `.env` file. See `.env.example` for the full list.

    Attributes:
        embedding_model_name: Hugging Face id of the bi-encoder that produces embeddings.
        embedding_model_revision: Pinned commit of the embedding model (reproducibility).
        embedding_max_tokens: Token window used when encoding (must fit the model).
        embedding_batch_size: Texts encoded per forward pass during ingestion.
        query_prefix: Prefix for queries. `None` picks the model family default.
        passage_prefix: Prefix for passages. `None` picks the model family default.
        reranker_model_name: Hugging Face id of the cross-encoder used for re-ranking.
        reranker_model_revision: Pinned commit of the cross-encoder.
        reranker_max_tokens: Token window for each (query, passage) pair.
        reranker_batch_size: Pairs scored per forward pass.
        rerank_enabled: Whether the cross-encoder is loaded and used by default.
        relevance_threshold: Cross-encoder score below which a result is flagged as
            low relevance (only re-ranked scores are calibrated enough for this).
        device: "auto" (GPU when available), "cpu" or "cuda".
        torch_num_threads: CPU threads for PyTorch (`None` keeps the library default).
        documents_dir: Folder with the Markdown posts.
        storage_dir: Folder where the index artifacts are written.
        chunk_max_tokens: Maximum tokens per chunk, title included.
        chunk_overlap_tokens: Tokens repeated from the previous chunk of the same section.
        chunk_min_tokens: Sections smaller than this are joined to a neighbor section
            when both fit the chunk budget (0 never joins sections).
        default_top_k: Documents returned when the caller does not choose.
        max_top_k: Upper bound accepted for `top_k`.
        max_query_chars: Longest query accepted.
        default_search_mode: Mode used when the caller does not choose.
        candidates_k: Chunks requested from each retriever before fusion.
        rerank_candidates: Best fused chunks sent to the cross-encoder.
        rrf_k: Reciprocal Rank Fusion constant (dampens the weight of the top ranks).
        rrf_dense_weight: Weight of the dense ranking in the fusion.
        rrf_keyword_weight: Weight of the BM25 ranking in the fusion.
        bm25_k1: BM25 term-frequency saturation.
        bm25_b: BM25 document-length normalization.
        context_neighbors: Chunks taken on each side of a result to build its
            `context_text` (small-to-big: search small, hand a larger passage to RAG).
        openai_api_key: OpenAI key. Without it, the LLM steps are skipped and the
            search works as before (plain chunks, original query).
        llm_timeout: Seconds before an OpenAI request is aborted.
        llm_max_retries: Automatic retries on transient OpenAI errors (rate limit...).
        enrichment_enabled: Ask the LLM, at ingestion, for each chunk's context,
            questions, similar terms and content types.
        enrichment_model: OpenAI model of the enrichment (runs once per chunk, so the
            cheapest per token wins; latency does not matter offline).
        llm_reasoning_effort: Effort sent to reasoning models (gpt-5, o-series);
            "minimal" keeps their hidden reasoning tokens, cost and latency low.
        enrichment_concurrency: Parallel enrichment requests.
        enrichment_max_tokens: Token budget of the enrichment appended to a chunk.
        enrichment_cache_path: JSON file with the enrichments already paid for.
        query_rewrite_enabled: Ask the LLM, at search time, to rewrite the query and
            extract its similar terms, categories and content types.
        query_rewrite_model: OpenAI model of the rewrite (runs on every new query).
        metadata_boost: Share of the remaining score headroom added to a candidate
            whose category or content type matches the ones extracted from the query.
        log_level: Root logging level.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Embedding model (bi-encoder) ------------------------------------------------
    embedding_model_name: str = "intfloat/multilingual-e5-small"
    embedding_model_revision: str | None = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
    embedding_max_tokens: int = Field(default=512, gt=EMBEDDING_TOKEN_MARGIN)
    embedding_batch_size: int = Field(default=32, gt=0)
    query_prefix: str | None = None
    passage_prefix: str | None = None

    # --- Re-ranking model (cross-encoder) ----------------------------------------------
    reranker_model_name: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    reranker_model_revision: str | None = "1427fd652930e4ba29e8149678df786c240d8825"
    reranker_max_tokens: int = Field(default=512, gt=0)
    reranker_batch_size: int = Field(default=16, gt=0)
    rerank_enabled: bool = True
    relevance_threshold: float = Field(default=0.3, ge=0.0, le=1.0)

    # --- Runtime -----------------------------------------------------------------------
    device: Literal["auto", "cpu", "cuda"] = "auto"
    torch_num_threads: int | None = Field(default=None, gt=0)

    # --- Paths ---------------------------------------------------------------------------
    documents_dir: Path = Path("data/documents")
    storage_dir: Path = Path("storage")

    # --- Chunking --------------------------------------------------------------------------
    chunk_max_tokens: int = Field(default=256, gt=0)
    chunk_overlap_tokens: int = Field(default=48, ge=0)
    chunk_min_tokens: int = Field(default=40, ge=0)

    # --- Search ------------------------------------------------------------------------------
    default_top_k: int = Field(default=5, gt=0)
    max_top_k: int = Field(default=20, gt=0)
    max_query_chars: int = Field(default=500, gt=0)
    default_search_mode: SearchMode = "hybrid"
    candidates_k: int = Field(default=50, gt=0)
    rerank_candidates: int = Field(default=20, gt=0)
    rrf_k: int = Field(default=60, gt=0)
    rrf_dense_weight: float = Field(default=1.0, ge=0.0)
    rrf_keyword_weight: float = Field(default=1.0, ge=0.0)
    bm25_k1: float = Field(default=1.5, gt=0.0)
    bm25_b: float = Field(default=0.75, ge=0.0, le=1.0)
    context_neighbors: int = Field(default=1, ge=0)

    # --- LLM (OpenAI): chunk enrichment and query rewriting -----------------------------------
    openai_api_key: SecretStr | None = None
    llm_timeout: float = Field(default=30.0, gt=0)
    llm_max_retries: int = Field(default=3, ge=0)
    enrichment_enabled: bool = True
    enrichment_model: str = "gpt-5-nano"
    llm_reasoning_effort: str = "minimal"
    enrichment_concurrency: int = Field(default=8, gt=0)
    enrichment_max_tokens: int = Field(default=160, gt=0)
    enrichment_cache_path: Path = Path("data/enrichment_cache.json")
    query_rewrite_enabled: bool = True
    query_rewrite_model: str = "gpt-5-nano"
    metadata_boost: float = Field(default=0.15, ge=0.0, le=1.0)

    # --- Logging -------------------------------------------------------------------------------
    log_level: str = "INFO"

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        """Reject combinations of values that would break the pipeline silently.

        Returns:
            The validated settings.

        Raises:
            ValueError: If the chunk does not fit the model window, the overlap is not
                smaller than the chunk, the defaults exceed their limits, or both RRF
                weights are zero.
        """
        # A chunk larger than the model window would be truncated by the tokenizer
        # without any warning, and the cut-off text would never be searchable.
        if self.chunk_max_tokens + EMBEDDING_TOKEN_MARGIN > self.embedding_max_tokens:
            raise ValueError(
                f"chunk_max_tokens ({self.chunk_max_tokens}) plus a margin of "
                f"{EMBEDDING_TOKEN_MARGIN} tokens must fit embedding_max_tokens "
                f"({self.embedding_max_tokens})."
            )
        if self.chunk_overlap_tokens >= self.chunk_max_tokens:
            raise ValueError("chunk_overlap_tokens must be smaller than chunk_max_tokens.")
        if self.chunk_min_tokens >= self.chunk_max_tokens:
            raise ValueError("chunk_min_tokens must be smaller than chunk_max_tokens.")
        if self.default_top_k > self.max_top_k:
            raise ValueError("default_top_k must not exceed max_top_k.")
        if self.rrf_dense_weight == 0 and self.rrf_keyword_weight == 0:
            raise ValueError("At least one RRF weight must be greater than zero.")
        # The enrichment is appended to the chunk before embedding, so both must fit.
        if (
            self.chunk_max_tokens + self.enrichment_max_tokens + EMBEDDING_TOKEN_MARGIN
            > self.embedding_max_tokens
        ):
            raise ValueError(
                f"chunk_max_tokens ({self.chunk_max_tokens}) plus enrichment_max_tokens "
                f"({self.enrichment_max_tokens}) plus a margin of {EMBEDDING_TOKEN_MARGIN} "
                f"tokens must fit embedding_max_tokens ({self.embedding_max_tokens})."
            )
        return self

    @property
    def has_openai_api_key(self) -> bool:
        """Tell whether a non-blank OpenAI key is configured.

        Returns:
            True when the LLM steps can run.
        """
        return bool(self.openai_api_key and self.openai_api_key.get_secret_value().strip())


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance.

    Cached so `.env` is parsed only once; tests can call `get_settings.cache_clear()`.

    Returns:
        The loaded `Settings`.
    """
    return Settings()
