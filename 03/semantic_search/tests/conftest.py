"""Shared fixtures: a mini dataset, isolated settings and services built with fakes."""

from pathlib import Path

import pytest

from app.core.config import Settings
from app.services.artifacts import load_artifacts
from app.services.indexing_service import IndexingService
from app.services.search_service import SearchService
from tests.fakes import FakeEmbedder, FakeEnricher, FakeQueryRewriter, FakeReranker


def front_matter(doc_id: str, title: str, category: str, tags: str) -> str:
    """Build a front matter like the one written by `scripts/fetch_dataset.py`."""
    return f"""---
id: {doc_id}
title: {title}
category: {category}
tags: [{tags}]
author: Colaboradores da Wikipédia
source_url: https://pt.wikipedia.org/wiki/{title.replace(" ", "_")}
source_revision: 123
license: CC BY-SA 4.0
license_url: https://creativecommons.org/licenses/by-sa/4.0/deed.pt-br
retrieved_at: 2026-10-29
adapted: Plain-text extraction; reference sections removed
---
"""


MINI_DATASET: dict[str, str] = {
    "nut-01-fibras-na-alimentacao.md": front_matter(
        "nut-01", "Fibras na alimentação", "nutrition", "fibras, alimentação, intestino"
    )
    + """As fibras alimentares são partes dos vegetais que o intestino não digere.

## Benefícios

As fibras ajudam o intestino a funcionar bem e aumentam a sensação de saciedade.

Elas também reduzem a absorção de gorduras e ajudam a controlar o açúcar no sangue.

## Fontes

Frutas, verduras, legumes, aveia e grãos integrais são as principais fontes de fibras.
""",
    "nut-02-hidratacao.md": front_matter(
        "nut-02", "Hidratação", "nutrition", "água, eletrólitos, hidratação"
    )
    + """## Água e eletrólitos

Beber água repõe o líquido perdido no suor. Em exercícios longos, os eletrólitos,
como sódio e potássio, também precisam ser repostos.
""",
    "act-01-sono.md": front_matter("act-01", "Sono", "sleep-exercise", "sono, descanso, noite")
    + """## Ciclos do sono

O sono acontece em ciclos que se repetem durante a noite. A melatonina, produzida no
escuro, sinaliza ao corpo que é hora de descansar.
""",
    "inf-01-dengue.md": front_matter(
        "inf-01", "Dengue", "infectious-diseases", "dengue, mosquito, febre"
    )
    + """## Transmissão

A dengue é transmitida pela picada do mosquito Aedes aegypti e causa febre alta,
dores no corpo e manchas na pele.
""",
}


def write_dataset(directory: Path, files: dict[str, str]) -> Path:
    """Write Markdown documents into a folder.

    Args:
        directory: Target folder (created if needed).
        files: File name -> content.

    Returns:
        The folder.
    """
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (directory / name).write_text(content, encoding="utf-8")
    return directory


@pytest.fixture
def documents_dir(tmp_path: Path) -> Path:
    """Folder with the mini dataset."""
    return write_dataset(tmp_path / "documents", MINI_DATASET)


@pytest.fixture
def settings(tmp_path: Path, documents_dir: Path) -> Settings:
    """Settings isolated from `.env`, pointing to temporary folders and the fake model."""
    return Settings(
        _env_file=None,
        documents_dir=documents_dir,
        storage_dir=tmp_path / "storage",
        enrichment_cache_path=tmp_path / "enrichment_cache.json",
        openai_api_key=None,
        embedding_model_name="fake-embedder",
        embedding_model_revision=None,
        chunk_max_tokens=40,
        chunk_overlap_tokens=8,
        chunk_min_tokens=0,
        candidates_k=20,
        rerank_candidates=10,
        max_top_k=10,
    )


@pytest.fixture
def embedder() -> FakeEmbedder:
    """Deterministic fake embedder."""
    return FakeEmbedder()


@pytest.fixture
def indexing_service(settings: Settings, embedder: FakeEmbedder) -> IndexingService:
    """Indexing service using the fake embedder."""
    return IndexingService(settings, embedder_provider=lambda: embedder)


@pytest.fixture
def indexed_settings(settings: Settings, indexing_service: IndexingService) -> Settings:
    """Settings whose storage folder already holds an index of the mini dataset."""
    indexing_service.ingest()
    return settings


@pytest.fixture
def reranker() -> FakeReranker:
    """Fake cross-encoder."""
    return FakeReranker()


@pytest.fixture
def search_service(
    indexed_settings: Settings, embedder: FakeEmbedder, reranker: FakeReranker
) -> SearchService:
    """Search service over the indexed mini dataset, with the fake re-ranker."""
    return SearchService(
        embedder=embedder,
        artifacts=load_artifacts(indexed_settings.storage_dir),
        settings=indexed_settings,
        reranker=reranker,
    )


@pytest.fixture
def enricher() -> FakeEnricher:
    """Fake LLM enricher with a fixed lay vocabulary."""
    return FakeEnricher()


@pytest.fixture
def enriched_settings(
    settings: Settings, embedder: FakeEmbedder, enricher: FakeEnricher
) -> Settings:
    """Settings whose storage folder holds an enriched index of the mini dataset."""
    IndexingService(settings, embedder_provider=lambda: embedder, enricher=enricher).ingest()
    return settings


def build_enriched_service(
    settings: Settings,
    embedder: FakeEmbedder,
    reranker: FakeReranker | None = None,
    rewriter: FakeQueryRewriter | None = None,
) -> SearchService:
    """Create a search service over the enriched index.

    Args:
        settings: Settings pointing to an enriched index.
        embedder: Fake embedder.
        reranker: Fake re-ranker, if any.
        rewriter: Fake query rewriter, if any.

    Returns:
        The service.
    """
    return SearchService(
        embedder=embedder,
        artifacts=load_artifacts(settings.storage_dir),
        settings=settings,
        reranker=reranker,
        query_rewriter=rewriter,
    )
