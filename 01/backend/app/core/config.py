"""Centralized application settings.

Values are read from environment variables or from a `.env` file, falling back
to the defaults declared here. See `.env.example` for the available variables.

Settings are grouped by concern: application metadata, database connections,
pagination, HTTP security and logging. The defaults are safe for local
development; the README lists what to change for production.
"""

from functools import lru_cache
from typing import Annotated, Any, Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

# Lists are written as comma-separated values in the environment
# (`CORS_ORIGINS=http://a.com,http://b.com`), so JSON decoding is disabled.
CsvList = Annotated[list[str], NoDecode]


class Settings(BaseSettings):
    """Application settings loaded from the environment.

    Attributes:
        app_name: Human-readable name shown in the OpenAPI documentation.
        app_version: Application version shown in the OpenAPI documentation.
        database_url: SQLAlchemy database URL.
        db_pool_size: Connections kept open in the pool.
        db_max_overflow: Extra connections allowed above `db_pool_size` under load.
        db_pool_timeout_seconds: How long a request waits for a free connection.
        db_pool_recycle_seconds: Connections older than this are replaced (-1 disables).
        sqlite_busy_timeout_seconds: How long SQLite waits for a lock before failing.
        default_page_size: Number of items returned when `limit` is omitted.
        max_page_size: Maximum value accepted for the `limit` query parameter.
        cors_origins: Browser origins allowed to call the API (CORS).
        allowed_hosts: Accepted values of the `Host` header.
        api_key: When set, every `/books` request must send it in `X-API-Key`.
        enable_docs: Whether `/docs`, `/redoc` and `/openapi.json` are served.
        docs_show_api_key: Whether the docs page prints `api_key`, so visitors of a
            public demo can try the endpoints. Never enable it for a real secret.
        max_request_body_bytes: Largest request body accepted.
        rate_limit_requests: Requests allowed per client per window (0 disables).
        rate_limit_window_seconds: Length of the rate-limit window.
        log_level: Minimum level of the application logger.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Application ---------------------------------------------------------
    app_name: str = Field(default="Library API", description="Application name.")
    app_version: str = Field(default="0.1.0", description="Application version.")

    # --- Database connections -------------------------------------------------
    database_url: str = Field(
        default="sqlite:///./library.db", description="SQLAlchemy database URL."
    )
    db_pool_size: int = Field(default=5, ge=1, description="Pooled connections.")
    db_max_overflow: int = Field(default=5, ge=0, description="Extra connections under load.")
    db_pool_timeout_seconds: float = Field(
        default=10, gt=0, description="Wait for a free connection before failing."
    )
    db_pool_recycle_seconds: int = Field(
        default=1800, ge=-1, description="Recycle connections older than this."
    )
    sqlite_busy_timeout_seconds: float = Field(
        default=5, ge=0, description="Wait for SQLite locks before failing."
    )

    # --- Pagination -------------------------------------------------------------
    default_page_size: int = Field(default=20, ge=1, description="Default page size.")
    max_page_size: int = Field(default=100, ge=1, description="Maximum page size.")

    # --- HTTP security ----------------------------------------------------------
    cors_origins: CsvList = Field(
        default=["http://localhost:8050", "http://127.0.0.1:8050"],
        description="Browser origins allowed by CORS.",
    )
    allowed_hosts: CsvList = Field(
        default=["localhost", "127.0.0.1", "api"],
        description="Accepted Host headers ('*' accepts any).",
    )
    api_key: SecretStr | None = Field(
        default=None, description="Optional API key required in the X-API-Key header."
    )
    enable_docs: bool = Field(default=True, description="Serve the interactive API docs.")
    docs_show_api_key: bool = Field(
        default=False, description="Print the API key in the docs (public demos only)."
    )
    max_request_body_bytes: int = Field(
        default=64 * 1024, ge=1024, description="Largest request body accepted."
    )
    rate_limit_requests: int = Field(
        default=300, ge=0, description="Requests per client per window (0 disables)."
    )
    rate_limit_window_seconds: int = Field(default=60, ge=1, description="Rate-limit window.")

    # --- Logging ----------------------------------------------------------------
    log_level: LogLevel = Field(default="INFO", description="Application log level.")

    @field_validator("cors_origins", "allowed_hosts", mode="before")
    @classmethod
    def split_comma_separated(cls, value: Any) -> Any:
        """Accept comma-separated strings for list settings.

        Args:
            value: The raw value, e.g. `"http://a.com, http://b.com"`.

        Returns:
            A list of trimmed, non-empty items, or the value unchanged if it is
            not a string.
        """
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("api_key", mode="before")
    @classmethod
    def blank_api_key_disables_it(cls, value: Any) -> Any:
        """Treat an empty `API_KEY` as "not configured".

        Args:
            value: The raw value.

        Returns:
            `None` for blank strings, otherwise the value unchanged.
        """
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def check_page_sizes(self) -> Self:
        """Ensure the default page size never exceeds the maximum page size.

        Returns:
            The validated settings instance.

        Raises:
            ValueError: If `default_page_size` is greater than `max_page_size`.
        """
        if self.default_page_size > self.max_page_size:
            raise ValueError("default_page_size must be less than or equal to max_page_size")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the application settings, built once and cached.

    Returns:
        The process-wide `Settings` instance.
    """
    return Settings()
