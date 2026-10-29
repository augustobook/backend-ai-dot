"""Domain exceptions.

The services raise these instead of library errors, so every interface (CLI, API,
web UI) can turn them into a clear message or HTTP status without knowing which
library failed underneath.
"""


class SemanticSearchError(Exception):
    """Base class for every error raised by this application."""


class InvalidDocumentError(SemanticSearchError):
    """A post could not be parsed or its front matter is invalid."""


class DatasetError(SemanticSearchError):
    """The dataset as a whole is invalid (empty folder, duplicated ids...)."""


class IndexNotFoundError(SemanticSearchError):
    """The index artifacts do not exist yet; the ingestion must run first."""


class IndexCorruptedError(SemanticSearchError):
    """The index artifacts exist but are inconsistent or unreadable."""


class EmbeddingModelMismatchError(SemanticSearchError):
    """The configured embedding model differs from the one used to build the index.

    Vectors produced by different models live in different spaces, so comparing a
    query embedding with them would return meaningless scores.
    """


class DocumentNotFoundError(SemanticSearchError):
    """No document has the requested id."""


class LLMError(SemanticSearchError):
    """The LLM could not be reached or returned an unusable answer."""


class InvalidQueryError(SemanticSearchError, ValueError):
    """The search parameters are invalid (empty query, `top_k` out of range...)."""


class InvalidSearchModeError(InvalidQueryError):
    """The requested search mode is not one of `semantic`, `keyword` or `hybrid`."""
