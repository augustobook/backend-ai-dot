"""Tests for the ingestion pipeline with the fake embedder."""

import json
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.exceptions import IndexCorruptedError
from app.ingestion.chunker import CHUNKER_VERSION
from app.services.artifacts import (
    CHUNKS_FILE_NAME,
    DOCUMENTS_FILE_NAME,
    MANIFEST_FILE_NAME,
    load_artifacts,
)
from app.services.indexing_service import IndexingService
from app.vector_store.faiss_store import INDEX_FILE_NAME, QUESTIONS_INDEX_FILE_NAME
from tests.fakes import FAKE_DIMENSION, FakeEmbedder, FakeEnricher


def test_ingest_builds_every_artifact(
    settings: Settings, indexing_service: IndexingService
) -> None:
    """The pipeline writes the index, chunks, documents and a complete manifest."""
    progress: list[tuple[str, int, int]] = []

    report = indexing_service.ingest(
        progress=lambda stage, done, total: progress.append((stage, done, total))
    )

    storage = settings.storage_dir
    for name in (INDEX_FILE_NAME, CHUNKS_FILE_NAME, DOCUMENTS_FILE_NAME, MANIFEST_FILE_NAME):
        assert (storage / name).is_file()
    assert not (storage / ".building").exists()

    manifest = report.manifest
    assert report.skipped is False
    assert manifest.embedding_model == "fake-embedder"
    assert manifest.dimension == FAKE_DIMENSION
    assert manifest.document_count == 4
    assert manifest.chunk_count == len(json.loads((storage / CHUNKS_FILE_NAME).read_text("utf-8")))
    assert manifest.chunk_max_tokens == settings.chunk_max_tokens
    # Without an enricher there is neither an enrichment stage nor generated questions.
    assert {stage for stage, _, _ in progress} == {"embed"}
    assert progress[-1] == ("embed", manifest.chunk_count, manifest.chunk_count)
    assert manifest.enrichment_model is None
    assert manifest.question_count == 0
    assert not (storage / QUESTIONS_INDEX_FILE_NAME).exists()

    artifacts = load_artifacts(storage)
    assert artifacts.store.count() == manifest.chunk_count
    assert artifacts.question_store is None


def test_ingest_embeds_only_title_and_body(
    settings: Settings, indexing_service: IndexingService
) -> None:
    """Chunk texts start with the title and never include front matter fields."""
    indexing_service.ingest()

    chunks = load_artifacts(settings.storage_dir).chunks
    nut01 = [chunk for chunk in chunks if chunk.document_id == "nut-01"]
    assert all(chunk.text.startswith("Fibras na alimentação\n\n") for chunk in nut01)
    assert not any(
        "Colaboradores da Wikipédia" in chunk.text or "category" in chunk.text for chunk in chunks
    )


def test_ingest_is_skipped_when_nothing_changed(settings: Settings, embedder: FakeEmbedder) -> None:
    """A second run with the same dataset and settings does not load the model."""
    calls: list[int] = []

    def provider() -> FakeEmbedder:
        calls.append(1)
        return embedder

    service = IndexingService(settings, embedder_provider=provider)
    first = service.ingest()
    second = service.ingest()

    assert second.skipped is True
    assert second.manifest.created_at == first.manifest.created_at
    assert len(calls) == 1


def test_force_rebuilds_the_index(indexing_service: IndexingService) -> None:
    """--force rebuilds even when the dataset did not change."""
    first = indexing_service.ingest()

    forced = indexing_service.ingest(force=True)

    assert forced.skipped is False
    assert forced.manifest.created_at > first.manifest.created_at


def test_changes_trigger_a_rebuild(
    settings: Settings, indexing_service: IndexingService, documents_dir: Path
) -> None:
    """Editing a document or changing the chunking rebuilds the index."""
    indexing_service.ingest()
    path = documents_dir / "inf-01-dengue.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nNovo parágrafo.", encoding="utf-8")
    assert indexing_service.ingest().skipped is False

    rechunked = settings.model_copy(update={"chunk_max_tokens": 30})
    service = IndexingService(rechunked, embedder_provider=FakeEmbedder)
    assert service.ingest().skipped is False

    # The minimum section size is part of the chunking too.
    joined = rechunked.model_copy(update={"chunk_min_tokens": 10})
    assert IndexingService(joined, embedder_provider=FakeEmbedder).ingest().skipped is False


def test_a_new_chunker_version_triggers_a_rebuild(
    settings: Settings, indexing_service: IndexingService
) -> None:
    """Chunking code changes do not change the dataset hash; the version catches them."""
    manifest = indexing_service.ingest().manifest
    assert manifest.chunker_version == CHUNKER_VERSION
    assert manifest.chunk_min_tokens == settings.chunk_min_tokens

    path = settings.storage_dir / MANIFEST_FILE_NAME
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["chunker_version"] = "1"
    path.write_text(json.dumps(stored), encoding="utf-8")

    assert indexing_service.ingest().skipped is False


def test_enriched_ingest_indexes_questions_and_records_the_enrichment(
    settings: Settings, embedder: FakeEmbedder, enricher: FakeEnricher
) -> None:
    """Every chunk gets its enrichment, and every question a vector of its own."""
    progress: list[str] = []
    service = IndexingService(settings, embedder_provider=lambda: embedder, enricher=enricher)

    manifest = service.ingest(progress=lambda stage, done, total: progress.append(stage)).manifest

    artifacts = load_artifacts(settings.storage_dir)
    questions = [pair for chunk in artifacts.chunks for pair in chunk.question_ids()]
    assert manifest.enrichment_model == "fake-enricher"
    assert manifest.enrichment_prompt_version == "1"
    assert manifest.question_count == len(questions) > manifest.chunk_count
    assert artifacts.question_store is not None
    assert artifacts.question_store.count() == len(questions)
    assert all(chunk.enrichment is not None for chunk in artifacts.chunks)
    assert {"enrich", "embed", "questions"} <= set(progress)
    # The lay vocabulary only exists in the enrichment, never in the displayed text.
    fibers = [chunk for chunk in artifacts.chunks if chunk.document_id == "nut-01"]
    assert all("prisão de ventre" in chunk.search_text for chunk in fibers)
    assert not any("prisão de ventre" in chunk.text for chunk in fibers)
    assert settings.enrichment_cache_path.is_file()


def test_enrichment_changes_trigger_a_rebuild(
    settings: Settings, embedder: FakeEmbedder, enricher: FakeEnricher
) -> None:
    """Another enrichment model, or none at all, rebuilds; the same one skips."""
    service = IndexingService(settings, embedder_provider=lambda: embedder, enricher=enricher)
    service.ingest()
    assert service.ingest().skipped is True

    other = IndexingService(
        settings, embedder_provider=lambda: embedder, enricher=FakeEnricher("other")
    )
    assert other.ingest().skipped is False

    plain = IndexingService(settings, embedder_provider=lambda: embedder)
    assert plain.ingest().skipped is False
    # The question index of the enriched build must not survive a plain build.
    assert not (settings.storage_dir / QUESTIONS_INDEX_FILE_NAME).exists()
    assert load_artifacts(settings.storage_dir).question_store is None


def test_inconsistent_question_index_is_detected(enriched_settings: Settings) -> None:
    """A manifest that disagrees with the question index refuses to load."""
    path = enriched_settings.storage_dir / MANIFEST_FILE_NAME
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["question_count"] += 1
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(IndexCorruptedError, match="question index"):
        load_artifacts(enriched_settings.storage_dir)


def test_broken_manifest_is_rebuilt(settings: Settings, indexing_service: IndexingService) -> None:
    """An unreadable manifest does not block the ingestion."""
    indexing_service.ingest()
    (settings.storage_dir / MANIFEST_FILE_NAME).write_text("{}", encoding="utf-8")

    assert indexing_service.ingest().skipped is False
