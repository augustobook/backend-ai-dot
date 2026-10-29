"""Pydantic schemas for creating and reading books."""

from datetime import UTC, date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

MAX_TEXT_LENGTH = 255
MAX_SUMMARY_LENGTH = 5000

NonEmptyStr = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TEXT_LENGTH)
]


class BookBase(BaseModel):
    """Fields shared by the book input and output schemas."""

    title: NonEmptyStr = Field(
        ...,
        description="Title of the book. Leading and trailing spaces are removed.",
        examples=["Harry Potter and the Philosopher's Stone"],
    )
    author: NonEmptyStr = Field(
        ...,
        description="Author of the book. Leading and trailing spaces are removed.",
        examples=["J. K. Rowling"],
    )
    publication_date: date = Field(
        ...,
        description="Publication date in ISO format (YYYY-MM-DD). Cannot be in the future.",
        examples=["1997-06-26"],
    )
    summary: str = Field(
        default="",
        max_length=MAX_SUMMARY_LENGTH,
        description=f"Free-text summary of the book (up to {MAX_SUMMARY_LENGTH} characters).",
        examples=["A young wizard discovers his magical heritage on his eleventh birthday."],
    )


class BookCreate(BookBase):
    """Payload used to register a new book.

    Unknown fields are rejected (422) instead of silently ignored, so a client
    cannot try to set server-controlled values such as `id`.
    """

    model_config = ConfigDict(extra="forbid")

    created_at: datetime | None = Field(
        default=None,
        description=(
            "When the book was registered in the library (ISO 8601). Optional: if omitted, "
            "the current UTC date and time is used. Values without a timezone are treated "
            "as UTC. Cannot be in the future."
        ),
        examples=["2024-05-10T14:30:00Z"],
    )

    @field_validator("publication_date")
    @classmethod
    def publication_date_not_in_future(cls, value: date) -> date:
        """Reject publication dates later than today (UTC).

        Args:
            value: The publication date sent by the client.

        Returns:
            The unchanged publication date.

        Raises:
            ValueError: If the date is in the future.
        """
        if value > datetime.now(UTC).date():
            raise ValueError("publication_date cannot be in the future")
        return value

    @field_validator("created_at")
    @classmethod
    def created_at_in_utc_and_not_in_future(cls, value: datetime | None) -> datetime | None:
        """Normalize `created_at` to UTC and reject future values.

        Args:
            value: The registration datetime sent by the client, if any.

        Returns:
            The datetime converted to UTC, or `None` when omitted.

        Raises:
            ValueError: If the datetime is in the future.
        """
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        value = value.astimezone(UTC)
        if value > datetime.now(UTC):
            raise ValueError("created_at cannot be in the future")
        return value


class BookRead(BookBase):
    """Representation of a stored book returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="Unique identifier of the book.", examples=[1])
    created_at: datetime = Field(
        ...,
        description="When the book was registered in the library, in UTC (ISO 8601).",
        examples=["2024-05-10T14:30:00Z"],
    )
