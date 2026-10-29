"""Custom SQLAlchemy column types."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, Dialect
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware datetime column that is always stored and returned in UTC.

    SQLite has no native timezone support and returns naive datetimes, so the
    value is normalized to UTC before being written and the UTC timezone is
    attached again when it is read back.
    """

    impl = DateTime(timezone=True)
    # The type has no per-instance state that changes the SQL, so SQLAlchemy may
    # cache the statements that use it.
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        """Convert a datetime to UTC before storing it.

        Args:
            value: The datetime to store. Naive values are assumed to be UTC.
            dialect: The database dialect in use.

        Returns:
            The value converted to UTC, or `None`.
        """
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        """Attach the UTC timezone to a datetime read from the database.

        Args:
            value: The datetime read from the database.
            dialect: The database dialect in use.

        Returns:
            A timezone-aware UTC datetime, or `None`.
        """
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
