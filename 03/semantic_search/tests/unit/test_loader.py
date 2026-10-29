"""Tests for reading documents and validating their front matter."""

from pathlib import Path

import pytest

from app.core.exceptions import DatasetError, InvalidDocumentError
from app.ingestion.loader import compute_dataset_hash, load_document, load_documents
from tests.conftest import MINI_DATASET, front_matter, write_dataset

VALID_DOCUMENT = (
    front_matter("nut-05", "Vitamina D", "nutrition", "vitaminas, sol, ossos") + "Texto do artigo."
)


def write_post(directory: Path, name: str, content: str) -> Path:
    """Write a single document and return its path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(content, encoding="utf-8")
    return path


def test_load_document_reads_metadata_and_body(tmp_path: Path) -> None:
    """A valid document is parsed into metadata, attribution and body."""
    path = write_post(tmp_path, "nut-05-vitamina-d.md", VALID_DOCUMENT)

    document = load_document(path)

    assert document.id == "nut-05"
    assert document.category == "nutrition"
    assert document.tags == ["vitaminas", "sol", "ossos"]
    assert document.body == "Texto do artigo."
    assert document.license == "CC BY-SA 4.0"
    assert str(document.source_url) == "https://pt.wikipedia.org/wiki/Vitamina_D"
    assert document.metadata.title == "Vitamina D"


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("category: nutrition", "category: unknown"),
        ("retrieved_at: 2026-10-29", "retrieved_at: ontem"),
        ("tags: [vitaminas, sol, ossos]", "tags: [vitaminas]"),
        ("tags: [vitaminas, sol, ossos]", "tags: [sol, sol, ossos]"),
        ("id: nut-05", "id: NUT_5"),
        ("author: Colaboradores da Wikipédia\n", ""),
        ("source_url: https://pt.wikipedia.org/wiki/Vitamina_D", "source_url: nao-e-url"),
        ("license: CC BY-SA 4.0\n", ""),
    ],
)
def test_load_document_rejects_invalid_front_matter(tmp_path: Path, old: str, new: str) -> None:
    """Invalid categories, dates, tags, ids, URLs or missing attribution are rejected."""
    path = write_post(tmp_path, "nut-05-vitamina-d.md", VALID_DOCUMENT.replace(old, new))

    with pytest.raises(InvalidDocumentError):
        load_document(path)


def test_load_document_rejects_empty_body(tmp_path: Path) -> None:
    """A document without text is rejected."""
    path = write_post(
        tmp_path, "nut-05-vitamina-d.md", VALID_DOCUMENT.replace("Texto do artigo.", "")
    )

    with pytest.raises(InvalidDocumentError):
        load_document(path)


def test_load_document_requires_file_name_to_match_id(tmp_path: Path) -> None:
    """The file name must start with the id of the document."""
    path = write_post(tmp_path, "nut-06-vitamina-d.md", VALID_DOCUMENT)

    with pytest.raises(InvalidDocumentError, match="must start with"):
        load_document(path)


def test_load_document_rejects_broken_yaml(tmp_path: Path) -> None:
    """Unparseable YAML is reported as an invalid document."""
    path = write_post(tmp_path, "nut-05-vitamina-d.md", "---\nid: [unclosed\n---\nTexto.")

    with pytest.raises(InvalidDocumentError, match="could not parse"):
        load_document(path)


def test_load_documents_returns_sorted_documents(documents_dir: Path) -> None:
    """All documents are loaded in file name order."""
    documents = load_documents(documents_dir)

    assert [document.id for document in documents] == ["act-01", "inf-01", "nut-01", "nut-02"]


def test_load_documents_rejects_duplicated_ids(tmp_path: Path) -> None:
    """Two files with the same id are a dataset error."""
    directory = write_dataset(tmp_path / "docs", MINI_DATASET)
    write_post(directory, "nut-01-copia.md", MINI_DATASET["nut-01-fibras-na-alimentacao.md"])

    with pytest.raises(DatasetError, match="Duplicated"):
        load_documents(directory)


def test_load_documents_requires_existing_non_empty_folder(tmp_path: Path) -> None:
    """A missing or empty folder is a dataset error."""
    with pytest.raises(DatasetError, match="not found"):
        load_documents(tmp_path / "missing")
    (tmp_path / "empty").mkdir()
    with pytest.raises(DatasetError, match="No Markdown"):
        load_documents(tmp_path / "empty")


def test_dataset_hash_changes_only_when_files_change(documents_dir: Path) -> None:
    """The hash is stable across calls and changes when a document is edited."""
    first = compute_dataset_hash(documents_dir)
    assert compute_dataset_hash(documents_dir) == first

    path = documents_dir / "nut-02-hidratacao.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nMais texto.", encoding="utf-8")

    assert compute_dataset_hash(documents_dir) != first
