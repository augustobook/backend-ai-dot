"""Tests for the Portuguese tokenizer and the BM25 retriever."""

from app.ingestion.chunker import Chunk
from app.search.keyword import KeywordRetriever, normalize_text, tokenize_pt


def make_chunks(*texts: str) -> list[Chunk]:
    """Build chunks with ids 1..n."""
    return [
        Chunk(chunk_id=index, document_id=f"doc-{index:02d}", position=0, text=text)
        for index, text in enumerate(texts, start=1)
    ]


def test_normalize_text_lowercases_and_strips_accents() -> None:
    """Accents and case do not matter."""
    assert normalize_text("Ação RÁPIDA, Pão!") == "acao rapida, pao!"


def test_tokenize_pt_removes_stopwords_and_punctuation() -> None:
    """Stopwords (with or without accents) and punctuation are dropped."""
    assert tokenize_pt("Como é que você faz o pão de levain?") == [
        "faz",
        "pao",
        "levain",
    ]


def test_tokenize_pt_keeps_numbers_and_identifiers() -> None:
    """Digits and code identifiers survive tokenization."""
    assert tokenize_pt("Regra dos 72 e defaultdict") == ["regra", "72", "defaultdict"]


def test_exact_term_ranks_first() -> None:
    """The chunk containing the rare query term comes first."""
    retriever = KeywordRetriever(
        make_chunks(
            "O defaultdict cria valores padrão para chaves novas.",
            "Listas guardam valores em ordem.",
            "Dicionários guardam pares de chave e valor.",
        )
    )

    results = retriever.retrieve("defaultdict", k=3)

    assert [result.chunk_id for result in results] == [1]
    assert results[0].score > 0


def test_accents_in_query_do_not_matter() -> None:
    """A query typed without accents matches accented text."""
    retriever = KeywordRetriever(make_chunks("A reação de Maillard doura a carne.", "Outro texto."))

    assert retriever.retrieve("reacao maillard", k=2)[0].chunk_id == 1


def test_allowed_ids_restrict_the_results() -> None:
    """Only allowed chunks are returned."""
    retriever = KeywordRetriever(make_chunks("levain levain", "levain e forno", "forno quente"))

    results = retriever.retrieve("levain", k=5, allowed_ids={2, 3})

    assert [result.chunk_id for result in results] == [2]


def test_query_with_only_stopwords_returns_nothing() -> None:
    """A query without content words has no keyword matches."""
    retriever = KeywordRetriever(make_chunks("Texto qualquer sobre listas."))

    assert retriever.retrieve("como e que o", k=5) == []


def test_empty_corpus_and_zero_k_return_nothing() -> None:
    """An empty index or k <= 0 returns an empty list."""
    assert KeywordRetriever([]).retrieve("listas", k=5) == []
    assert KeywordRetriever(make_chunks("listas")).retrieve("listas", k=0) == []
