"""Tests for settings validation, device selection, pooling and the service factory."""

import logging
from pathlib import Path

import pytest
import torch
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.core.device import configure_torch_threads, resolve_device
from app.core.exceptions import EmbeddingModelMismatchError, IndexNotFoundError
from app.core.logging import configure_logging
from app.embeddings.transformers_embedder import default_prefixes, l2_normalize, mean_pooling
from app.services.factory import build_reranker, build_search_service


@pytest.mark.parametrize(
    "overrides",
    [
        {"chunk_max_tokens": 500, "embedding_max_tokens": 512},
        {"chunk_max_tokens": 100, "chunk_overlap_tokens": 100},
        {"default_top_k": 30, "max_top_k": 20},
        {"rrf_dense_weight": 0.0, "rrf_keyword_weight": 0.0},
        {"chunk_max_tokens": 100, "chunk_min_tokens": 100},
        {"chunk_max_tokens": 300, "enrichment_max_tokens": 300},
    ],
)
def test_inconsistent_settings_are_rejected(overrides: dict[str, object]) -> None:
    """Chunks larger than the model window and other contradictions fail fast."""
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_default_settings_are_valid() -> None:
    """The defaults pin both models and use hybrid search."""
    get_settings.cache_clear()
    settings = get_settings()

    assert settings.default_search_mode == "hybrid"
    assert settings.embedding_model_revision
    assert settings.reranker_model_revision
    get_settings.cache_clear()


def test_resolve_device_and_threads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Auto falls back to CPU, and an unavailable GPU is an error."""
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)

    assert resolve_device("auto").type == "cpu"
    assert resolve_device("cpu").type == "cpu"
    with pytest.raises(ValueError, match="CUDA"):
        resolve_device("cuda")

    previous = torch.get_num_threads()
    configure_torch_threads(1)
    assert torch.get_num_threads() == 1
    configure_torch_threads(None)
    assert torch.get_num_threads() == 1
    torch.set_num_threads(previous)


def test_mean_pooling_ignores_padding() -> None:
    """Padding tokens do not change the pooled vector."""
    tokens = torch.tensor([[[1.0, 1.0], [3.0, 3.0], [100.0, 100.0]]])
    mask = torch.tensor([[1, 1, 0]])

    assert mean_pooling(tokens, mask).tolist() == [[2.0, 2.0]]


def test_l2_normalize_produces_unit_vectors() -> None:
    """Every row ends with norm 1."""
    normalized = l2_normalize(torch.tensor([[3.0, 4.0], [1.0, 0.0]]))

    assert normalized.norm(dim=1).tolist() == pytest.approx([1.0, 1.0])
    assert normalized[0].tolist() == pytest.approx([0.6, 0.8])


def test_default_prefixes_follow_the_model_family() -> None:
    """E5 models get query/passage prefixes; others get none."""
    assert default_prefixes("intfloat/multilingual-e5-small") == ("query: ", "passage: ")
    assert default_prefixes("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2") == (
        "",
        "",
    )


def test_configure_logging_quiets_noisy_libraries() -> None:
    """The root level is set and HTTP client loggers stay at WARNING."""
    configure_logging("DEBUG")

    assert logging.getLogger().level == logging.DEBUG
    assert logging.getLogger("httpx").level == logging.WARNING
    configure_logging("INFO")


def test_factory_fails_fast_without_index(tmp_path: Path) -> None:
    """No index means a clear error before any model is loaded."""
    settings = Settings(_env_file=None, storage_dir=tmp_path)

    with pytest.raises(IndexNotFoundError):
        build_search_service(settings)


def test_factory_rejects_index_built_with_another_model(indexed_settings: Settings) -> None:
    """The manifest check runs before the configured model is loaded."""
    other = indexed_settings.model_copy(update={"embedding_model_name": "another/model"})

    with pytest.raises(EmbeddingModelMismatchError):
        build_search_service(other)


def test_reranker_can_be_disabled(settings: Settings) -> None:
    """RERANK_ENABLED=false returns no re-ranker without loading a model."""
    assert build_reranker(settings.model_copy(update={"rerank_enabled": False})) is None
