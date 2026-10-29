"""Metadata the LLM produces: for each chunk at ingestion, and for each query at search.

Both sides share the same vocabulary (categories and content types), so what the
query asks for can be compared with what each chunk is about.

These models double as the JSON schemas of the structured outputs. OpenAI's strict
mode requires every field to be present, so they have no default values.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.ingestion.loader import Category

ContentType = Literal[
    "definition",
    "symptoms",
    "causes",
    "risk-factors",
    "diagnosis",
    "treatment",
    "prevention",
    "diet",
    "epidemiology",
    "history",
    "other",
]
"""What a passage talks about (or what a query wants), independent of the disease."""

MAX_QUESTIONS = 5
MAX_SIMILAR_TERMS = 10
MAX_ALTERNATIVE_QUERIES = 3


class ChunkEnrichment(BaseModel):
    """What the LLM adds to a chunk at ingestion.

    Attributes:
        context: One or two sentences placing the passage inside its article (the
            passage alone often omits the subject: "o tratamento inclui...").
        questions: Questions a lay person could ask that the passage answers. They
            are embedded on their own, so a query is matched against questions.
        similar_terms: Synonyms and popular names of the concepts of the passage
            ("prisão de ventre" for "constipação"), indexed for BM25 and embeddings.
        content_types: What the passage is about (symptoms, treatment...).
    """

    model_config = ConfigDict(frozen=True)

    context: str
    questions: list[str]
    similar_terms: list[str]
    content_types: list[ContentType]


class QueryAnalysis(BaseModel):
    """What the LLM understands from a query at search time.

    Attributes:
        rewritten_query: The query in the vocabulary of an encyclopedic article
            (technical names instead of popular ones).
        alternative_queries: Other ways of asking the same thing (multi-query): each
            one is searched too, so one bad rewrite cannot steer the whole search.
        similar_terms: Synonyms, technical and popular names of what is asked.
        categories: Categories that probably hold the answer (may be empty).
        content_types: Kind of information wanted (may be empty).
    """

    model_config = ConfigDict(frozen=True)

    rewritten_query: str
    alternative_queries: list[str]
    similar_terms: list[str]
    categories: list[Category]
    content_types: list[ContentType]


def clean_items(items: list[str], limit: int) -> list[str]:
    """Strip, drop blanks and case-insensitive duplicates, and keep the first `limit`.

    Args:
        items: Strings returned by the model.
        limit: Maximum number of items kept.

    Returns:
        The cleaned list, in the original order.
    """
    seen: set[str] = set()
    cleaned: list[str] = []
    for item in items:
        text = " ".join(item.split())
        if text and text.lower() not in seen:
            seen.add(text.lower())
            cleaned.append(text)
    return cleaned[:limit]
