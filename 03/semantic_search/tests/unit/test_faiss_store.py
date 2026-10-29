"""Tests for the FAISS vector store and the index artifacts."""

from pathlib import Path

import numpy as np
import pytest

from app.core.config import Settings
from app.core.exceptions import (
    EmbeddingModelMismatchError,
    IndexCorruptedError,
    IndexNotFoundError,
)
from app.services.artifacts import (
    CHUNKS_FILE_NAME,
    MANIFEST_FILE_NAME,
    check_model_compatibility,
    load_artifacts,
    read_manifest,
)
from app.vector_store.faiss_store import INDEX_FILE_NAME, FaissVectorStore


def unit(*values: float) -> np.ndarray:
    """Build a normalized float32 vector."""
    vector = np.asarray(values, dtype=np.float32)
    return vector / np.linalg.norm(vector)


@pytest.fixture
def store() -> FaissVectorStore:
    """Store with four vectors at known angles from the x axis."""
    store = FaissVectorStore(dimension=2)
    store.add([10, 20, 30, 40], np.stack([unit(1, 0), unit(1, 1), unit(0, 1), unit(-1, 0)]))
    return store


def test_search_orders_results_by_cosine(store: FaissVectorStore) -> None:
    """The closest vector comes first and scores are cosines."""
    results = store.search(unit(1, 0), k=4)

    assert [chunk_id for chunk_id, _ in results] == [10, 20, 30, 40]
    assert results[0][1] == pytest.approx(1.0)
    assert results[1][1] == pytest.approx(np.sqrt(2) / 2)
    assert results[3][1] == pytest.approx(-1.0)


def test_search_pre_filters_by_allowed_ids(store: FaissVectorStore) -> None:
    """Only allowed ids are returned, even if better vectors exist."""
    results = store.search(unit(1, 0), k=3, allowed_ids={30, 40})

    assert [chunk_id for chunk_id, _ in results] == [30, 40]


def test_search_edge_cases(store: FaissVectorStore) -> None:
    """Empty filter, k <= 0 and an empty store return nothing; k is capped."""
    assert store.search(unit(1, 0), k=3, allowed_ids=set()) == []
    assert store.search(unit(1, 0), k=0) == []
    assert FaissVectorStore(2).search(unit(1, 0), k=3) == []
    assert len(store.search(unit(1, 0), k=100)) == 4


def test_add_and_search_validate_shapes(store: FaissVectorStore) -> None:
    """Wrong shapes, length mismatches and repeated ids are rejected."""
    with pytest.raises(ValueError, match="shape"):
        store.add([1], np.zeros((1, 3), dtype=np.float32))
    with pytest.raises(ValueError, match="same length"):
        store.add([1, 2], np.zeros((1, 2), dtype=np.float32))
    with pytest.raises(ValueError, match="unique"):
        store.add([1, 1], np.zeros((2, 2), dtype=np.float32))
    with pytest.raises(ValueError, match="query"):
        store.search(np.zeros(3, dtype=np.float32), k=1)
    with pytest.raises(ValueError, match="positive"):
        FaissVectorStore(0)


def test_save_and_load_round_trip(store: FaissVectorStore, tmp_path: Path) -> None:
    """A saved index is loaded with the same vectors and ids."""
    store.save(tmp_path)

    loaded = FaissVectorStore.load(tmp_path)

    assert loaded.count() == 4
    assert loaded.dimension == 2
    assert loaded.search(unit(0, 1), k=1)[0][0] == 30


def test_load_reports_missing_and_corrupted_files(tmp_path: Path) -> None:
    """A missing file and garbage bytes raise domain errors."""
    with pytest.raises(IndexNotFoundError):
        FaissVectorStore.load(tmp_path)
    (tmp_path / INDEX_FILE_NAME).write_bytes(b"not a faiss index")
    with pytest.raises(IndexCorruptedError):
        FaissVectorStore.load(tmp_path)


def test_manifest_validation_rejects_a_different_model(indexed_settings: Settings) -> None:
    """Searching with another model, revision or dimension is refused."""
    manifest = read_manifest(indexed_settings.storage_dir)
    assert manifest is not None

    check_model_compatibility(manifest, "fake-embedder", None, dimension=manifest.dimension)
    with pytest.raises(EmbeddingModelMismatchError, match="other-model"):
        check_model_compatibility(manifest, "other-model", None)
    with pytest.raises(EmbeddingModelMismatchError, match="dimensional"):
        check_model_compatibility(manifest, "fake-embedder", None, dimension=3)

    pinned = manifest.model_copy(update={"embedding_model_revision": "abc"})
    check_model_compatibility(pinned, "fake-embedder", None)
    with pytest.raises(EmbeddingModelMismatchError, match="revision"):
        check_model_compatibility(pinned, "fake-embedder", "def")


def test_load_artifacts_requires_an_index(tmp_path: Path) -> None:
    """Without a manifest the index is reported as not found."""
    assert read_manifest(tmp_path) is None
    with pytest.raises(IndexNotFoundError, match="ingest"):
        load_artifacts(tmp_path)


def test_load_artifacts_detects_inconsistent_files(indexed_settings: Settings) -> None:
    """Chunks that disagree with the manifest make the index corrupted."""
    storage = indexed_settings.storage_dir
    (storage / CHUNKS_FILE_NAME).write_text("[]", encoding="utf-8")

    with pytest.raises(IndexCorruptedError, match="Inconsistent"):
        load_artifacts(storage)


@pytest.mark.parametrize(
    ("file_name", "content", "message"),
    [
        (MANIFEST_FILE_NAME, "{}", "Invalid manifest"),
        (CHUNKS_FILE_NAME, "{not json", "Invalid JSON"),
        (CHUNKS_FILE_NAME, "{}", "JSON list"),
        (CHUNKS_FILE_NAME, '[{"chunk_id": "x"}]', "Invalid chunks"),
    ],
)
def test_load_artifacts_reports_invalid_files(
    indexed_settings: Settings, file_name: str, content: str, message: str
) -> None:
    """Malformed JSON files raise IndexCorruptedError with a clear message."""
    (indexed_settings.storage_dir / file_name).write_text(content, encoding="utf-8")

    with pytest.raises(IndexCorruptedError, match=message):
        load_artifacts(indexed_settings.storage_dir)


def test_load_artifacts_reports_missing_chunks_file(indexed_settings: Settings) -> None:
    """A deleted chunks file is reported as not found."""
    (indexed_settings.storage_dir / CHUNKS_FILE_NAME).unlink()

    with pytest.raises(IndexNotFoundError):
        load_artifacts(indexed_settings.storage_dir)
