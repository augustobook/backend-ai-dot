"""Tests for the section-aware chunker."""

from datetime import date
from pathlib import Path

import pytest

from app.ingestion.chunker import MarkdownChunker, make_chunk_id, split_sections
from app.ingestion.loader import Document, list_document_files, load_document


def count_words(text: str) -> int:
    """Count whitespace-separated words (stands in for the tokenizer)."""
    return len(text.split())


def make_document(body: str, title: str = "Título do post") -> Document:
    """Build a document with the given body."""
    return Document(
        id="nut-01",
        title=title,
        category="nutrition",
        tags=["a", "b", "c"],
        author="Colaboradores da Wikipédia",
        source_url="https://pt.wikipedia.org/wiki/Teste",
        license="CC BY-SA 4.0",
        license_url="https://creativecommons.org/licenses/by-sa/4.0/",
        retrieved_at=date(2026, 10, 29),
        body=body,
        file_name="nut-01-teste.md",
    )


def sentences(count: int, prefix: str = "Frase") -> str:
    """Build a paragraph with `count` five-word sentences."""
    return " ".join(f"{prefix} numero {index} bem curta." for index in range(count))


def test_short_document_becomes_a_single_chunk_with_the_title() -> None:
    """A body that fits the budget yields one chunk that starts with the title."""
    chunker = MarkdownChunker(count_words, max_tokens=100, overlap_tokens=10)

    chunks = chunker.chunk(make_document("Um parágrafo curto."))

    assert len(chunks) == 1
    assert chunks[0].text == "Título do post\n\nUm parágrafo curto."
    assert chunks[0].position == 0
    assert chunks[0].document_id == "nut-01"


def test_chunks_never_exceed_the_budget_including_the_title() -> None:
    """Every chunk, title included, respects max_tokens."""
    body = "\n\n".join(sentences(6, f"P{index}") for index in range(6))
    chunker = MarkdownChunker(count_words, max_tokens=40, overlap_tokens=8)

    chunks = chunker.chunk(make_document(body))

    assert len(chunks) > 1
    assert all(count_words(chunk.text) <= 40 for chunk in chunks)
    assert all(chunk.text.startswith("Título do post\n\n") for chunk in chunks)
    assert [chunk.position for chunk in chunks] == list(range(len(chunks)))


def test_consecutive_chunks_of_a_section_overlap() -> None:
    """The next chunk of a section starts with the last sentences of the previous one."""
    body = "\n\n".join(sentences(3, f"P{index}") for index in range(4))
    chunker = MarkdownChunker(count_words, max_tokens=40, overlap_tokens=6)

    texts = chunker.split("T", body)

    assert len(texts) >= 2
    last_sentence_of_first = texts[0].split(". ")[-1].rstrip(".")
    assert last_sentence_of_first in texts[1]


def test_overlap_can_be_disabled() -> None:
    """With overlap 0, no text is repeated between chunks."""
    body = "\n\n".join(sentences(3, f"P{index}") for index in range(4))
    chunker = MarkdownChunker(count_words, max_tokens=40, overlap_tokens=0)

    texts = chunker.split("T", body)
    passages = [text.removeprefix("T\n\n") for text in texts]

    assert "\n\n".join(passages).count("P0 numero 2") == 1


def test_chunks_do_not_cross_section_boundaries() -> None:
    """Each section produces its own chunks, with the heading text kept."""
    body = "## Primeira\n\nTexto um.\n\n## Segunda\n\nTexto dois."
    chunker = MarkdownChunker(count_words, max_tokens=100, overlap_tokens=10)

    texts = chunker.split("T", body)

    assert texts == ["T\n\nPrimeira\nTexto um.", "T\n\nSegunda\nTexto dois."]


def test_code_blocks_are_kept_whole() -> None:
    """A fenced code block, blank lines included, stays in one chunk."""
    code = "```python\ndef soma(a, b):\n\n    return a + b\n```"
    body = f"Intro curta.\n\n{code}\n\nFim."
    chunker = MarkdownChunker(count_words, max_tokens=14, overlap_tokens=2)

    texts = chunker.split("T", body)

    assert any(code in text for text in texts)


def test_oversized_paragraph_is_split_by_sentences() -> None:
    """A paragraph larger than the budget is broken at sentence boundaries."""
    chunker = MarkdownChunker(count_words, max_tokens=12, overlap_tokens=0)

    texts = chunker.split("T", sentences(6))

    assert len(texts) > 1
    assert all(count_words(text) <= 12 for text in texts)
    assert all(text.endswith(".") for text in texts)


def test_oversized_sentence_and_word_are_hard_split() -> None:
    """A sentence or a single word larger than the budget is still split to fit."""
    chunker = MarkdownChunker(len, max_tokens=12, overlap_tokens=0)

    texts = chunker.split("T", "palavraenormesemespacos " * 2)

    assert all(len(text) <= 12 for text in texts)
    assert "".join(text.removeprefix("T\n\n") for text in texts).replace(" ", "") == (
        "palavraenormesemespacos" * 2
    )


def test_oversized_code_block_is_split_by_lines() -> None:
    """A code block larger than the budget is split by lines as a last resort."""
    code = "```\n" + "\n".join(f"linha {index}" for index in range(10)) + "\n```"
    chunker = MarkdownChunker(count_words, max_tokens=8, overlap_tokens=0)

    texts = chunker.split("T", code)

    assert len(texts) > 1
    assert all(count_words(text) <= 8 for text in texts)


def test_empty_body_yields_no_chunks() -> None:
    """A body without text produces no chunks."""
    chunker = MarkdownChunker(count_words, max_tokens=10, overlap_tokens=0)

    assert chunker.split("T", "   \n\n  ") == []


def test_title_larger_than_budget_is_rejected() -> None:
    """A title that leaves no room for text is a configuration error."""
    chunker = MarkdownChunker(count_words, max_tokens=3, overlap_tokens=0)

    with pytest.raises(ValueError, match="title"):
        chunker.split("um dois tres quatro", "texto")


@pytest.mark.parametrize(("max_tokens", "overlap"), [(0, 0), (10, 10), (10, -1)])
def test_invalid_budget_is_rejected(max_tokens: int, overlap: int) -> None:
    """The budget must be positive and larger than the overlap."""
    with pytest.raises(ValueError):
        MarkdownChunker(count_words, max_tokens=max_tokens, overlap_tokens=overlap)


def test_heading_without_text_never_becomes_a_section() -> None:
    """A heading with no text only lives on in the path of its sub-headings.

    This is the "Causas" case of the Dengue article: `## Causas` directly followed by
    `### Virologia` used to produce a chunk with the single word "Causas".
    """
    body = (
        "## Causas\n\n### Virologia\n\nO vírus.\n\n## Vazia\n\n## Tratamento\n\nRepouso.\n\n## Fim"
    )

    texts = [[block.text for block in section] for section in split_sections(body)]

    assert texts == [["Causas > Virologia\nO vírus."], ["Tratamento\nRepouso."]]


def test_heading_path_follows_the_heading_levels() -> None:
    """Each section carries its heading path, which resets when a level closes."""
    body = (
        "Abertura.\n\n## Causas\n\nGeral.\n\n### Transmissão\n\nMosquito.\n\n"
        "#### Urbana\n\nCidade.\n\n### Virologia\n\nVírus.\n\n## Sintomas\n\nFebre."
    )

    labels = [section[0].text.split("\n")[0] for section in split_sections(body)]

    assert labels == [
        "Abertura.",
        "Causas",
        "Causas > Transmissão",
        "Causas > Transmissão > Urbana",
        "Causas > Virologia",
        "Sintomas",
    ]


def test_unclosed_fence_is_kept_as_code_with_its_heading_path() -> None:
    """An unterminated fence is kept as code, after the label of its section."""
    sections = split_sections("## Vazia\n### Com código\n```\nprint(1)")

    texts = [[block.text for block in section] for section in sections]
    assert texts == [["Vazia > Com código", "```\nprint(1)"]]


def test_small_section_is_joined_to_the_next_one() -> None:
    """A section below min_tokens is joined to the next section when both fit."""
    body = f"## Curta\n\nSó isso.\n\n## Longa\n\n{sentences(3)}\n\n## Outra\n\n{sentences(3)}"
    chunker = MarkdownChunker(count_words, max_tokens=40, overlap_tokens=0, min_tokens=10)

    passages = [text.removeprefix("T\n\n") for text in chunker.split("T", body)]

    assert len(passages) == 2
    assert passages[0].startswith("Curta\nSó isso.\n\nLonga\n")
    assert passages[1].startswith("Outra\n")


def test_small_last_section_is_joined_to_the_previous_one() -> None:
    """With no next section, a small section joins the previous one."""
    body = f"## Longa\n\n{sentences(3)}\n\n## Curta\n\nSó isso."
    chunker = MarkdownChunker(count_words, max_tokens=40, overlap_tokens=0, min_tokens=10)

    passages = [text.removeprefix("T\n\n") for text in chunker.split("T", body)]

    assert len(passages) == 1
    assert passages[0].endswith("Curta\nSó isso.")


def test_small_section_is_not_joined_when_it_would_not_fit() -> None:
    """A join never pushes a passage over the budget."""
    body = f"## Curta\n\nSó isso.\n\n## Longa\n\n{sentences(7)}"
    chunker = MarkdownChunker(count_words, max_tokens=38, overlap_tokens=0, min_tokens=10)

    passages = [text.removeprefix("T\n\n") for text in chunker.split("T", body)]

    assert passages[0] == "Curta\nSó isso."
    assert all(count_words(text) <= 38 for text in chunker.split("T", body))


def test_min_tokens_zero_never_joins_sections() -> None:
    """min_tokens=0 keeps every section on its own."""
    body = "## Um\n\nA.\n\n## Dois\n\nB."
    chunker = MarkdownChunker(count_words, max_tokens=40, overlap_tokens=0, min_tokens=0)

    assert len(chunker.split("T", body)) == 2


def test_min_tokens_must_be_smaller_than_the_budget() -> None:
    """A minimum as large as the budget is rejected."""
    with pytest.raises(ValueError, match="min_tokens"):
        MarkdownChunker(count_words, max_tokens=10, overlap_tokens=0, min_tokens=10)


def test_no_chunk_of_the_dataset_is_only_a_heading_path() -> None:
    """On the real articles, every chunk has text below its labels."""
    chunker = MarkdownChunker(count_words, max_tokens=200, overlap_tokens=36, min_tokens=30)

    for path in list_document_files(Path("data/documents")):
        document = load_document(path)
        for chunk in chunker.chunk(document):
            passage = chunk.text.removeprefix(f"{document.title}\n\n")
            lines = [line for line in passage.splitlines() if line.strip()]
            assert len(lines) > 1 or count_words(passage) > 8, (chunk.document_id, passage)


def test_heading_followed_by_code_is_kept() -> None:
    """A heading right before a code block becomes its own block."""
    sections = split_sections("## Exemplo\n```\nx = 1\n```")

    assert [block.text for block in sections[0]] == ["Exemplo", "```\nx = 1\n```"]


def test_chunk_ids_are_stable_and_positive() -> None:
    """The id depends only on document id and position, and fits a signed int64."""
    assert make_chunk_id("py-01", 0) == make_chunk_id("py-01", 0)
    assert make_chunk_id("py-01", 0) != make_chunk_id("py-01", 1)
    assert 0 <= make_chunk_id("py-01", 0) < 2**63
