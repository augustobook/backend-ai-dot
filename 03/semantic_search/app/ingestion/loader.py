"""Load the documents (Markdown + YAML front matter) and validate their metadata.

Each document is a `<id>-<slug>.md` file holding a real health article of the
Portuguese Wikipedia (see `scripts/fetch_dataset.py`). The front matter carries the
metadata (id, title, category, tags) and the attribution required by the license
(source URL, revision, license); the Markdown body carries the text. Only the title
and the body are ever sent to the embedding model; the metadata is kept alongside
the chunks for filtering, display and attribution.
"""

import hashlib
import logging
from datetime import date
from pathlib import Path
from typing import Literal, get_args

import frontmatter
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError, field_validator

from app.core.exceptions import DatasetError, InvalidDocumentError

logger = logging.getLogger(__name__)

Category = Literal[
    "nutrition",
    "mental-health",
    "sleep-exercise",
    "chronic-diseases",
    "infectious-diseases",
]
"""English category slugs; they are identifiers used by the code and the filters."""

CATEGORIES: tuple[str, ...] = get_args(Category)


class DocumentMetadata(BaseModel):
    """Front matter of a document.

    Attributes:
        id: Stable identifier, e.g. `chr-02`.
        title: Article title (Portuguese).
        category: English category slug.
        tags: Three to five Portuguese tags.
        author: Who wrote the text (e.g. "Colaboradores da Wikipédia").
        source_url: Page the text was taken from.
        source_revision: Revision id of that page, so the exact text can be traced.
        license: License of the text (e.g. "CC BY-SA 4.0").
        license_url: Address of the license.
        retrieved_at: When the text was downloaded.
        adapted: What was changed from the original (required by the license).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z]+-\d{2}$")
    title: str = Field(min_length=1)
    category: Category
    tags: list[str] = Field(min_length=3, max_length=5)
    author: str = Field(min_length=1)
    source_url: HttpUrl
    source_revision: int | None = None
    license: str = Field(min_length=1)
    license_url: HttpUrl
    retrieved_at: date
    adapted: str | None = None

    @field_validator("tags")
    @classmethod
    def _check_tags(cls, value: list[str]) -> list[str]:
        """Reject blank or repeated tags.

        Args:
            value: Tags from the front matter.

        Returns:
            The tags, stripped.

        Raises:
            ValueError: If a tag is blank or repeated.
        """
        tags = [tag.strip() for tag in value]
        if any(not tag for tag in tags):
            raise ValueError("tags must not be blank")
        if len(set(tags)) != len(tags):
            raise ValueError("tags must be unique")
        return tags


class Document(DocumentMetadata):
    """A complete document: metadata plus the Markdown body.

    Attributes:
        body: Markdown body, without the front matter.
        file_name: Name of the source file (kept for error messages and the API).
    """

    body: str = Field(min_length=1)
    file_name: str

    @property
    def metadata(self) -> DocumentMetadata:
        """Return only the front matter fields.

        Returns:
            The metadata of this post.
        """
        return DocumentMetadata(**self.model_dump(include=set(DocumentMetadata.model_fields)))


def load_document(path: Path) -> Document:
    """Read and validate a single post.

    Args:
        path: Path to a `<id>-<slug>.md` file.

    Returns:
        The validated document.

    Raises:
        InvalidDocumentError: If the file cannot be parsed, the front matter is
            invalid, the body is empty or the file name does not start with the id.
    """
    try:
        post = frontmatter.load(str(path), encoding="utf-8")
    except Exception as exc:  # YAML/encoding errors come from several libraries
        raise InvalidDocumentError(f"{path.name}: could not parse the file ({exc})") from exc

    try:
        document = Document(**post.metadata, body=post.content.strip(), file_name=path.name)
    except ValidationError as exc:
        raise InvalidDocumentError(f"{path.name}: invalid front matter or body\n{exc}") from exc

    # The file name is how humans find a post; it must agree with the id inside it.
    if not path.stem.startswith(f"{document.id}-"):
        raise InvalidDocumentError(
            f"{path.name}: the file name must start with the document id '{document.id}-'"
        )
    return document


def list_document_files(documents_dir: Path) -> list[Path]:
    """List the post files in a stable (sorted) order.

    Args:
        documents_dir: Folder with the Markdown posts.

    Returns:
        Sorted paths of the `.md` files.

    Raises:
        DatasetError: If the folder does not exist or has no posts.
    """
    if not documents_dir.is_dir():
        raise DatasetError(f"Documents folder not found: {documents_dir}")
    files = sorted(documents_dir.glob("*.md"))
    if not files:
        raise DatasetError(f"No Markdown documents found in {documents_dir}")
    return files


def load_documents(documents_dir: Path) -> list[Document]:
    """Load every post of the dataset.

    Args:
        documents_dir: Folder with the Markdown posts.

    Returns:
        The documents, sorted by file name.

    Raises:
        DatasetError: If the folder is empty or two posts share an id.
        InvalidDocumentError: If any post is invalid.
    """
    documents = [load_document(path) for path in list_document_files(documents_dir)]

    # Ids are used as keys everywhere (chunks, API, evaluation), so they must be unique.
    seen: dict[str, str] = {}
    for document in documents:
        if document.id in seen:
            raise DatasetError(
                f"Duplicated document id '{document.id}' in {seen[document.id]} "
                f"and {document.file_name}"
            )
        seen[document.id] = document.file_name

    logger.info("Loaded %d documents from %s", len(documents), documents_dir)
    return documents


def compute_dataset_hash(documents_dir: Path) -> str:
    """Hash the names and raw bytes of every post.

    The ingestion compares this hash with the one stored in the manifest to skip
    re-indexing when nothing changed.

    Args:
        documents_dir: Folder with the Markdown posts.

    Returns:
        Hex SHA-256 digest of the dataset.

    Raises:
        DatasetError: If the folder does not exist or has no posts.
    """
    digest = hashlib.sha256()
    for path in list_document_files(documents_dir):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()
