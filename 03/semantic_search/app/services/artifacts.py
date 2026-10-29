"""Index artifacts on disk: FAISS index, chunks, documents and the manifest.

Layout of the storage folder:
- `index.faiss`: the vectors, keyed by chunk id;
- `questions.faiss`: the questions generated for the chunks, keyed by question id
  (only when the chunks were enriched by the LLM);
- `chunks.json`: chunk id, document id, text, position and enrichment of every chunk (the BM25
  index is rebuilt from it in memory when loading, which is fast for this volume
  and avoids persisting Python objects with pickle);
- `documents.json`: metadata and body of every post (results and `GET /documents`);
- `manifest.json`: how the index was built (model, revision, dimension, metric,
  chunking parameters, counts, dataset hash, creation date).

The manifest exists because vectors from different models (or revisions) live in
different spaces: comparing a query embedded by model B with an index built by
model A returns plausible-looking but meaningless scores. Loading refuses that.
"""

import json
import logging
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ValidationError

from app.core.exceptions import (
    EmbeddingModelMismatchError,
    IndexCorruptedError,
    IndexNotFoundError,
)
from app.ingestion.chunker import Chunk
from app.ingestion.loader import Document
from app.vector_store.faiss_store import (
    INDEX_FILE_NAME,
    QUESTIONS_INDEX_FILE_NAME,
    FaissVectorStore,
)

logger = logging.getLogger(__name__)

MANIFEST_FILE_NAME = "manifest.json"
CHUNKS_FILE_NAME = "chunks.json"
DOCUMENTS_FILE_NAME = "documents.json"
ARTIFACT_FILE_NAMES = (INDEX_FILE_NAME, CHUNKS_FILE_NAME, DOCUMENTS_FILE_NAME, MANIFEST_FILE_NAME)
BUILD_DIR_NAME = ".building"


class IndexManifest(BaseModel):
    """Description of how an index was built.

    Attributes:
        embedding_model: Hugging Face id of the embedding model.
        embedding_model_revision: Pinned revision of the model, if any.
        dimension: Size of the vectors.
        metric: Similarity used by the index.
        index_type: FAISS index structure.
        document_count: Indexed posts.
        chunk_count: Indexed chunks.
        chunk_max_tokens: Chunk budget used.
        chunk_overlap_tokens: Overlap used.
        chunk_min_tokens: Minimum section size used (None: built before it existed).
        chunker_version: Version of the chunking logic (None: before versioning).
        dataset_hash: SHA-256 of the dataset files.
        created_at: When the index was built (UTC).
        enrichment_model: LLM that enriched the chunks; None when they were not.
        enrichment_prompt_version: Version of the enrichment prompt used.
        question_count: Generated questions embedded in the question index.
    """

    embedding_model: str
    embedding_model_revision: str | None
    dimension: int
    metric: str = "cosine (inner product of L2-normalized vectors)"
    index_type: str = "IndexIDMap2(IndexFlatIP)"
    document_count: int
    chunk_count: int
    chunk_max_tokens: int
    chunk_overlap_tokens: int
    chunk_min_tokens: int | None = None
    chunker_version: str | None = None
    dataset_hash: str
    created_at: datetime
    enrichment_model: str | None = None
    enrichment_prompt_version: str | None = None
    question_count: int = 0


@dataclass(frozen=True)
class IndexArtifacts:
    """Everything a search needs, loaded from (or about to be written to) disk.

    Attributes:
        manifest: How the index was built.
        store: Vector store with the chunk embeddings.
        chunks: Indexed chunks.
        documents: Indexed posts.
        question_store: Vector store with the generated questions, keyed by
            question id (see `Chunk.question_ids`); None without enrichment.
    """

    manifest: IndexManifest
    store: FaissVectorStore
    chunks: list[Chunk]
    documents: list[Document]
    question_store: FaissVectorStore | None = None


def save_artifacts(directory: Path, artifacts: IndexArtifacts) -> None:
    """Write the artifacts, replacing the previous ones.

    Files are first written to a temporary sub-folder and then moved into place, so
    an interrupted ingestion never leaves a half-written index next to a manifest
    that describes a complete one.

    Args:
        directory: Storage folder (created if needed).
        artifacts: The index to persist.
    """
    directory.mkdir(parents=True, exist_ok=True)
    build_dir = directory / BUILD_DIR_NAME
    shutil.rmtree(build_dir, ignore_errors=True)
    build_dir.mkdir()

    artifacts.store.save(build_dir)
    if artifacts.question_store is not None:
        artifacts.question_store.save(build_dir, QUESTIONS_INDEX_FILE_NAME)
    _write_json(build_dir / CHUNKS_FILE_NAME, [chunk.model_dump() for chunk in artifacts.chunks])
    _write_json(
        build_dir / DOCUMENTS_FILE_NAME,
        [document.model_dump(mode="json") for document in artifacts.documents],
    )
    # The manifest is moved last: its presence means the other files are complete.
    _write_json(build_dir / MANIFEST_FILE_NAME, artifacts.manifest.model_dump(mode="json"))

    # Removing the old manifest first means a reader never sees an old manifest next
    # to new files; the manifest is the last file moved in (see ARTIFACT_FILE_NAMES).
    (directory / MANIFEST_FILE_NAME).unlink(missing_ok=True)
    # The question index is optional: a stale one from an enriched build must not
    # survive a build without enrichment.
    if artifacts.question_store is None:
        (directory / QUESTIONS_INDEX_FILE_NAME).unlink(missing_ok=True)
    else:
        os.replace(build_dir / QUESTIONS_INDEX_FILE_NAME, directory / QUESTIONS_INDEX_FILE_NAME)
    for name in ARTIFACT_FILE_NAMES:
        os.replace(build_dir / name, directory / name)
    build_dir.rmdir()
    logger.info("Index artifacts written to %s", directory)


def read_manifest(directory: Path) -> IndexManifest | None:
    """Read the manifest, if an index exists.

    Args:
        directory: Storage folder.

    Returns:
        The manifest, or None when no index was built yet.

    Raises:
        IndexCorruptedError: If the manifest exists but is invalid.
    """
    path = directory / MANIFEST_FILE_NAME
    if not path.is_file():
        return None
    try:
        return IndexManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as exc:
        raise IndexCorruptedError(f"Invalid manifest {path}: {exc}") from exc


def load_artifacts(directory: Path) -> IndexArtifacts:
    """Load and cross-check every artifact.

    Args:
        directory: Storage folder.

    Returns:
        The loaded index.

    Raises:
        IndexNotFoundError: If the index was not built yet.
        IndexCorruptedError: If a file is invalid or the files disagree.
    """
    manifest = read_manifest(directory)
    if manifest is None:
        raise IndexNotFoundError(
            f"No index found in {directory}. Run the ingestion first: "
            "`uv run python -m app.cli ingest`."
        )
    store = FaissVectorStore.load(directory)
    try:
        chunks = [Chunk(**item) for item in _read_json(directory / CHUNKS_FILE_NAME)]
        documents = [Document(**item) for item in _read_json(directory / DOCUMENTS_FILE_NAME)]
    except (ValidationError, TypeError) as exc:
        raise IndexCorruptedError(
            f"Invalid chunks or documents file in {directory}: {exc}"
        ) from exc

    # The three sources must describe the same index, or ids would not resolve.
    if not store.count() == len(chunks) == manifest.chunk_count:
        raise IndexCorruptedError(
            f"Inconsistent index: {store.count()} vectors, {len(chunks)} chunks, "
            f"manifest says {manifest.chunk_count}. Run the ingestion with --force."
        )
    if store.dimension != manifest.dimension or len(documents) != manifest.document_count:
        raise IndexCorruptedError(
            "The FAISS index or documents.json do not match the manifest. "
            "Run the ingestion with --force."
        )

    question_store = None
    if manifest.question_count:
        question_store = FaissVectorStore.load(directory, QUESTIONS_INDEX_FILE_NAME)
        questions = sum(len(chunk.question_ids()) for chunk in chunks)
        if not question_store.count() == questions == manifest.question_count:
            raise IndexCorruptedError(
                f"Inconsistent question index: {question_store.count()} vectors, "
                f"{questions} questions in the chunks, manifest says "
                f"{manifest.question_count}. Run the ingestion with --force."
            )
    return IndexArtifacts(
        manifest=manifest,
        store=store,
        chunks=chunks,
        documents=documents,
        question_store=question_store,
    )


def check_model_compatibility(
    manifest: IndexManifest,
    model_name: str,
    model_revision: str | None,
    dimension: int | None = None,
) -> None:
    """Refuse to search an index built with another embedding model.

    Args:
        manifest: Manifest of the stored index.
        model_name: Configured embedding model.
        model_revision: Configured revision (compared only when both are pinned).
        dimension: Dimension of the loaded model, when already known.

    Raises:
        EmbeddingModelMismatchError: If the model, the revision or the dimension differ.
    """
    hint = "Embeddings from different models are not comparable; re-run the ingestion with --force."
    if manifest.embedding_model != model_name:
        raise EmbeddingModelMismatchError(
            f"The index was built with '{manifest.embedding_model}', but the configured "
            f"model is '{model_name}'. {hint}"
        )
    if (
        manifest.embedding_model_revision is not None
        and model_revision is not None
        and manifest.embedding_model_revision != model_revision
    ):
        raise EmbeddingModelMismatchError(
            f"The index was built with revision {manifest.embedding_model_revision} of "
            f"'{model_name}', but revision {model_revision} is configured. {hint}"
        )
    if dimension is not None and manifest.dimension != dimension:
        raise EmbeddingModelMismatchError(
            f"The index has {manifest.dimension}-dimensional vectors, but the model "
            f"produces {dimension}. {hint}"
        )


def _write_json(path: Path, payload: object) -> None:
    """Write UTF-8 JSON, keeping Portuguese characters readable.

    Args:
        path: Target file.
        payload: JSON-serializable data.
    """
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path) -> list[dict[str, object]]:
    """Read a JSON list of objects.

    Args:
        path: Source file.

    Returns:
        The decoded list.

    Raises:
        IndexNotFoundError: If the file does not exist.
        IndexCorruptedError: If the file is not a JSON list.
    """
    if not path.is_file():
        raise IndexNotFoundError(f"Index file not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IndexCorruptedError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, list):
        raise IndexCorruptedError(f"{path} must contain a JSON list")
    return payload
