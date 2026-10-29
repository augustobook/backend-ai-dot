"""Ingestion pipeline: load -> chunk -> enrich -> embed -> index -> persist.

The pipeline is idempotent: every run rebuilds the index from scratch, so the
result only depends on the dataset and the settings. When neither changed since the
last run (same dataset hash, model, revision, chunking parameters and version, and
enrichment),
the run is skipped; `force=True` rebuilds anyway. The LLM enrichment is cached on
disk, so a rebuild only pays for chunks it has never seen.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from app.core.config import Settings
from app.core.exceptions import IndexCorruptedError
from app.embeddings.base import Embedder
from app.ingestion.chunker import CHUNKER_VERSION, MarkdownChunker
from app.ingestion.loader import compute_dataset_hash, load_documents
from app.llm.enrichment import Enricher, EnrichmentCache, enrich_chunks
from app.services.artifacts import IndexArtifacts, IndexManifest, read_manifest, save_artifacts
from app.vector_store.faiss_store import INDEX_FILE_NAME, FaissVectorStore

logger = logging.getLogger(__name__)

# Bump when what goes into the indexes changes (not the chunking itself).
# v2: chunk vectors embed the original passage only, without the LLM enrichment.
INDEX_VERSION = "2"

IngestionStage = Literal["enrich", "embed", "questions"]
"""Stages that report progress: LLM enrichment, chunk embedding, question embedding."""

IngestionProgress = Callable[[IngestionStage, int, int], None]
"""Called with (stage, items done so far, total items of the stage)."""


@dataclass(frozen=True)
class IngestionReport:
    """Outcome of an ingestion run.

    Attributes:
        skipped: True when the index was already up to date.
        manifest: Manifest of the index now on disk.
        duration_seconds: Wall-clock time of the run.
    """

    skipped: bool
    manifest: IndexManifest
    duration_seconds: float


class IndexingService:
    """Builds the search index from the Markdown posts.

    Args:
        settings: Application settings (paths, chunking, model).
        embedder_provider: Returns the embedder. It is only called when the index
            really has to be rebuilt, so a skipped run does not load the model.
        enricher: LLM enricher of the chunks; None indexes the plain chunks.
    """

    def __init__(
        self,
        settings: Settings,
        embedder_provider: Callable[[], Embedder],
        enricher: Enricher | None = None,
    ) -> None:
        self._settings = settings
        self._embedder_provider = embedder_provider
        self._enricher = enricher

    def ingest(
        self, force: bool = False, progress: IngestionProgress | None = None
    ) -> IngestionReport:
        """Run the ingestion pipeline.

        Args:
            force: Rebuild even when the index is up to date.
            progress: Optional callback for a progress bar.

        Returns:
            What happened and the resulting manifest.

        Raises:
            DatasetError: If the dataset folder is empty or has duplicated ids.
            InvalidDocumentError: If a post is invalid.
            LLMError: If some chunks could not be enriched (the rest is cached).
        """
        started = time.perf_counter()
        settings = self._settings
        dataset_hash = compute_dataset_hash(settings.documents_dir)

        existing = self._read_existing_manifest()
        if not force and existing is not None and self._is_up_to_date(existing, dataset_hash):
            logger.info("Index is up to date (dataset hash %s); skipping", dataset_hash[:12])
            return IngestionReport(
                skipped=True, manifest=existing, duration_seconds=time.perf_counter() - started
            )

        # 1. Load and validate the posts.
        documents = load_documents(settings.documents_dir)

        # 2. Chunk them with the embedding model's own tokenizer, so the token budget
        #    is measured exactly as the model will see the text.
        step = time.perf_counter()
        embedder = self._embedder_provider()
        chunker = MarkdownChunker(
            count_tokens=embedder.count_tokens,
            max_tokens=settings.chunk_max_tokens,
            overlap_tokens=settings.chunk_overlap_tokens,
            min_tokens=settings.chunk_min_tokens,
        )
        chunks = [chunk for document in documents for chunk in chunker.chunk(document)]
        logger.info(
            "Split %d documents into %d chunks in %.2fs",
            len(documents),
            len(chunks),
            time.perf_counter() - step,
        )

        # 3. Ask the LLM for each chunk's context, questions, similar terms and content
        #    types (cached on disk), within a token budget that keeps chunk +
        #    enrichment inside the embedding window.
        enricher = self._enricher
        if enricher is not None:
            step = time.perf_counter()
            chunks = enrich_chunks(
                chunks,
                titles={document.id: document.title for document in documents},
                enricher=enricher,
                cache=EnrichmentCache(settings.enrichment_cache_path),
                count_tokens=embedder.count_tokens,
                max_tokens=settings.enrichment_max_tokens,
                concurrency=settings.enrichment_concurrency,
                progress=_counter("enrich", len(chunks), progress),
            )
            logger.info(
                "Enriched %d chunks with %s in %.2fs",
                len(chunks),
                enricher.model_name,
                time.perf_counter() - step,
            )

        # 4. Embed the chunks in batches: title + passage only. The enrichment is kept
        #    apart: its questions get vectors of their own (step 6) and its similar
        #    terms go to BM25. Document metadata (URL, license...) is never embedded.
        step = time.perf_counter()
        vectors = embedder.embed_documents(
            [chunk.text for chunk in chunks],
            progress=_counter("embed", len(chunks), progress),
        )
        logger.info("Embedded %d chunks in %.2fs", len(chunks), time.perf_counter() - step)

        # 5. Index the vectors under the chunk ids.
        store = FaissVectorStore(embedder.dimension)
        store.add([chunk.chunk_id for chunk in chunks], vectors)

        # 6. Embed every generated question on its own, in a second index: a query is
        #    then also compared with questions, which is much closer than a question
        #    vs. a paragraph.
        questions = [pair for chunk in chunks for pair in chunk.question_ids()]
        question_store = None
        if questions:
            step = time.perf_counter()
            question_vectors = embedder.embed_queries(
                [text for _, text in questions],
                progress=_counter("questions", len(questions), progress),
            )
            question_store = FaissVectorStore(embedder.dimension)
            question_store.add([question_id for question_id, _ in questions], question_vectors)
            logger.info(
                "Embedded %d questions in %.2fs", len(questions), time.perf_counter() - step
            )

        # 7. Persist the indexes, the chunks, the documents and the manifest.
        manifest = IndexManifest(
            embedding_model=embedder.model_name,
            embedding_model_revision=embedder.model_revision,
            dimension=embedder.dimension,
            document_count=len(documents),
            chunk_count=len(chunks),
            chunk_max_tokens=settings.chunk_max_tokens,
            chunk_overlap_tokens=settings.chunk_overlap_tokens,
            chunk_min_tokens=settings.chunk_min_tokens,
            chunker_version=CHUNKER_VERSION,
            index_version=INDEX_VERSION,
            dataset_hash=dataset_hash,
            created_at=datetime.now(UTC),
            enrichment_model=enricher.model_name if enricher is not None else None,
            enrichment_prompt_version=enricher.prompt_version if enricher is not None else None,
            question_count=len(questions),
        )
        save_artifacts(
            settings.storage_dir,
            IndexArtifacts(
                manifest=manifest,
                store=store,
                chunks=chunks,
                documents=documents,
                question_store=question_store,
            ),
        )

        duration = time.perf_counter() - started
        logger.info("Ingestion finished in %.2fs", duration)
        return IngestionReport(skipped=False, manifest=manifest, duration_seconds=duration)

    def _read_existing_manifest(self) -> IndexManifest | None:
        """Read the current manifest, treating a broken one as missing.

        Returns:
            The manifest, or None when there is no usable index.
        """
        try:
            return read_manifest(self._settings.storage_dir)
        except IndexCorruptedError:
            logger.warning("Existing manifest is invalid; the index will be rebuilt")
            return None

    def _is_up_to_date(self, manifest: IndexManifest, dataset_hash: str) -> bool:
        """Tell whether the stored index matches the dataset and the settings.

        Args:
            manifest: Manifest of the stored index.
            dataset_hash: Hash of the current dataset.

        Returns:
            True when rebuilding would produce the same index.
        """
        settings = self._settings
        enricher = self._enricher
        return (
            manifest.dataset_hash == dataset_hash
            and manifest.enrichment_model == (enricher.model_name if enricher else None)
            and manifest.enrichment_prompt_version
            == (enricher.prompt_version if enricher else None)
            and manifest.embedding_model == settings.embedding_model_name
            and manifest.embedding_model_revision == settings.embedding_model_revision
            and manifest.chunk_max_tokens == settings.chunk_max_tokens
            and manifest.chunk_overlap_tokens == settings.chunk_overlap_tokens
            and manifest.chunk_min_tokens == settings.chunk_min_tokens
            and manifest.chunker_version == CHUNKER_VERSION
            and manifest.index_version == INDEX_VERSION
            and (settings.storage_dir / INDEX_FILE_NAME).is_file()
        )


def _counter(
    stage: IngestionStage, total: int, progress: IngestionProgress | None
) -> Callable[[int], None]:
    """Turn per-batch increments into the (stage, done, total) progress calls.

    Args:
        stage: Stage being reported.
        total: Items of the stage.
        progress: The ingestion progress callback, if any.

    Returns:
        A callback receiving how many items each batch processed.
    """
    done = 0

    def on_batch(count: int) -> None:
        nonlocal done
        done += count
        if progress is not None:
            progress(stage, done, total)

    return on_batch
