"""ORM model for the `books` table."""

from datetime import UTC, date, datetime

from sqlalchemy import Date, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime


class Book(Base):
    """A book registered in the library.

    Attributes:
        id: Auto-generated primary key.
        title: Book title.
        author: Book author.
        publication_date: Date the book was published.
        summary: Free-text summary of the book.
        created_at: When the book was registered in the library, in UTC.
    """

    __tablename__ = "books"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255))
    author: Mapped[str] = mapped_column(String(255))
    publication_date: Mapped[date] = mapped_column(Date)
    summary: Mapped[str] = mapped_column(Text, default="")
    # The service always sets `created_at`; this default covers rows inserted
    # without it. A lambda so the time is taken at insert, not at import.
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        """Return a short representation useful for debugging and logs."""
        return f"Book(id={self.id!r}, title={self.title!r}, author={self.author!r})"
