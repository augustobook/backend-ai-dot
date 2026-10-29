"""Test data factories, so each test only spells out the fields it cares about."""

from datetime import UTC, date, datetime
from typing import Any

from app.models.book import Book


def make_book_payload(**overrides: Any) -> dict[str, Any]:
    """Build a valid JSON payload for `POST /books`.

    Args:
        **overrides: Fields to replace or add in the default payload.

    Returns:
        The payload as a JSON-compatible dict.
    """
    payload: dict[str, Any] = {
        "title": "Harry Potter and the Philosopher's Stone",
        "author": "J. K. Rowling",
        "publication_date": "1997-06-26",
        "summary": "A young wizard discovers his magical heritage.",
    }
    payload.update(overrides)
    return payload


def make_book(**overrides: Any) -> Book:
    """Build an unsaved `Book` ORM instance with valid defaults.

    Args:
        **overrides: Attributes to replace in the default book.

    Returns:
        A transient `Book`.
    """
    fields: dict[str, Any] = {
        "title": "Harry Potter and the Philosopher's Stone",
        "author": "J. K. Rowling",
        "publication_date": date(1997, 6, 26),
        "summary": "A young wizard discovers his magical heritage.",
        "created_at": datetime(2024, 5, 10, 14, 30, tzinfo=UTC),
    }
    fields.update(overrides)
    return Book(**fields)
