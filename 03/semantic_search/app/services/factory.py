"""Build the services from the settings.

The CLI, the API and the web UI all need the same objects (embedder, cross-encoder,
LLM steps, loaded index); building them here keeps the three interfaces free of
wiring code.
"""

import logging

from app.core.config import Settings
from app.embeddings.base import Embedder
from app.embeddings.transformers_embedder import TransformersEmbedder
from app.llm.client import build_llm
from app.llm.enrichment import Enricher, LLMEnricher
from app.llm.query_rewriter import LLMQueryRewriter, QueryRewriter
from app.reranking.base import Reranker
from app.reranking.cross_encoder import CrossEncoderReranker
from app.services.artifacts import check_model_compatibility, load_artifacts, read_manifest
from app.services.indexing_service import IndexingService
from app.services.search_service import SearchService

logger = logging.getLogger(__name__)


def build_embedder(settings: Settings) -> Embedder:
    """Load the configured embedding model.

    Args:
        settings: Application settings.

    Returns:
        The embedder.
    """
    return TransformersEmbedder(
        model_name=settings.embedding_model_name,
        revision=settings.embedding_model_revision,
        max_tokens=settings.embedding_max_tokens,
        batch_size=settings.embedding_batch_size,
        device=settings.device,
        num_threads=settings.torch_num_threads,
        query_prefix=settings.query_prefix,
        passage_prefix=settings.passage_prefix,
    )


def build_reranker(settings: Settings) -> Reranker | None:
    """Load the configured cross-encoder, unless re-ranking is disabled.

    Args:
        settings: Application settings.

    Returns:
        The re-ranker, or None when `RERANK_ENABLED=false`.
    """
    if not settings.rerank_enabled:
        logger.info("Re-ranking disabled by configuration")
        return None
    return CrossEncoderReranker(
        model_name=settings.reranker_model_name,
        revision=settings.reranker_model_revision,
        max_tokens=settings.reranker_max_tokens,
        batch_size=settings.reranker_batch_size,
        device=settings.device,
        num_threads=settings.torch_num_threads,
    )


def build_enricher(settings: Settings) -> Enricher | None:
    """Create the LLM enricher of the chunks, when it is enabled and has a key.

    Args:
        settings: Application settings.

    Returns:
        The enricher, or None (the chunks are then indexed as they are).
    """
    if not settings.enrichment_enabled:
        logger.info("Chunk enrichment disabled by configuration")
        return None
    if not settings.has_openai_api_key:
        logger.warning("OPENAI_API_KEY is not set: the chunks will be indexed without enrichment")
        return None
    return LLMEnricher(build_llm(settings, settings.enrichment_model))


def build_query_rewriter(settings: Settings) -> QueryRewriter | None:
    """Create the LLM query rewriter, when it is enabled and has a key.

    Args:
        settings: Application settings.

    Returns:
        The rewriter, or None (queries are then searched as typed).
    """
    if not settings.query_rewrite_enabled:
        logger.info("Query rewriting disabled by configuration")
        return None
    if not settings.has_openai_api_key:
        logger.warning("OPENAI_API_KEY is not set: queries will be searched as typed")
        return None
    return LLMQueryRewriter(build_llm(settings, settings.query_rewrite_model))


def build_indexing_service(settings: Settings) -> IndexingService:
    """Create the ingestion service (the model is only loaded if a rebuild is needed).

    Args:
        settings: Application settings.

    Returns:
        The indexing service.
    """
    return IndexingService(
        settings,
        embedder_provider=lambda: build_embedder(settings),
        enricher=build_enricher(settings),
    )


def build_search_service(settings: Settings) -> SearchService:
    """Load the index and the models and create the search service.

    The manifest is checked against the configured model *before* loading anything
    heavy, so a mismatch fails in milliseconds with a clear message.

    Args:
        settings: Application settings.

    Returns:
        A ready-to-use search service.

    Raises:
        IndexNotFoundError: If the ingestion has not run yet.
        IndexCorruptedError: If the index files are inconsistent.
        EmbeddingModelMismatchError: If the index was built with another model.
    """
    manifest = read_manifest(settings.storage_dir)
    if manifest is not None:
        check_model_compatibility(
            manifest, settings.embedding_model_name, settings.embedding_model_revision
        )
    artifacts = load_artifacts(settings.storage_dir)

    embedder = build_embedder(settings)
    check_model_compatibility(
        artifacts.manifest,
        embedder.model_name,
        embedder.model_revision,
        dimension=embedder.dimension,
    )
    return SearchService(
        embedder=embedder,
        artifacts=artifacts,
        settings=settings,
        reranker=build_reranker(settings),
        query_rewriter=build_query_rewriter(settings),
    )
