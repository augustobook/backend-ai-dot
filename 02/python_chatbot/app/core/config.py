"""Centralized application settings loaded from environment variables and `.env`.

Every tunable value (OpenAI model, temperature, timeouts, token limits, LangSmith
tracing...) lives here, so the rest of the code never reads `os.environ` directly.
"""

from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Maximum size of one user question, in characters (all interfaces).
MAX_QUESTION_LENGTH = 5000


class Settings(BaseSettings):
    """Application settings.

    Values are read (case-insensitively) from environment variables first and then
    from a local `.env` file. See `.env.example` for the full list.

    Attributes:
        openai_api_key: Secret OpenAI key. Optional here so the app can start and
            report a friendly error instead of crashing during validation.
        openai_model: Chat model name (GPT-4 family).
        openai_temperature: Sampling temperature. Kept low because a tutor must be
            precise and consistent; a little randomness keeps explanations natural.
        openai_max_tokens: Maximum tokens per answer (bounds latency and cost).
        openai_context_window: Total tokens the model accepts per request (prompt +
            answer). 128k for gpt-4o / gpt-4o-mini; adjust when changing the model.
        openai_timeout: Seconds before an OpenAI request is aborted.
        openai_max_retries: Automatic retries for transient OpenAI failures.
        history_router_enabled: Whether a router decides, per question, if the
            conversation history is sent (False = always send it).
        history_router_model: OpenAI model used by the router (cheap and fast).
        log_level: Root logging level.
        chainlit_show_chain_steps: Whether the web UI shows the LangChain steps.
        chainlit_database_path: SQLite file with the web UI conversation history.
        langsmith_tracing: Enables LangSmith tracing when True.
        langsmith_api_key: LangSmith API key (required when tracing is enabled).
        langsmith_project: LangSmith project that receives the traces.
        langsmith_endpoint: LangSmith API endpoint.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- OpenAI ---------------------------------------------------------------
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o-mini"
    openai_temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    openai_max_tokens: int = Field(default=4096, gt=0)
    openai_context_window: int = Field(default=128_000, gt=0)
    openai_timeout: float = Field(default=60.0, gt=0)
    openai_max_retries: int = Field(default=2, ge=0)

    # --- Conversation -------------------------------------------------------------
    # Ask a small LLM router, per question, whether the history must be sent.
    history_router_enabled: bool = True
    # Cheapest and fastest OpenAI model for a yes/no decision. A non-reasoning
    # model is preferred: reasoning models spend extra "thinking" tokens and time.
    history_router_model: str = "gpt-4.1-nano"

    # --- Logging and interfaces -------------------------------------------------
    log_level: str = "INFO"
    chainlit_show_chain_steps: bool = False
    # SQLite file that stores the web UI's conversation list (created on demand).
    chainlit_database_path: Path = Path("data/chat_history.db")

    # --- LangSmith (optional observability) ---------------------------------------
    langsmith_tracing: bool = False
    langsmith_api_key: SecretStr | None = None
    langsmith_project: str = "python-chatbot"
    langsmith_endpoint: str = "https://api.smith.langchain.com"

    @model_validator(mode="after")
    def _check_token_limits(self) -> Self:
        """Ensure the context window leaves room for the prompt after the answer."""
        if self.openai_max_tokens >= self.openai_context_window:
            raise ValueError("OPENAI_MAX_TOKENS must be smaller than OPENAI_CONTEXT_WINDOW.")
        return self

    @property
    def has_openai_api_key(self) -> bool:
        """Tell whether a non-blank OpenAI API key is configured.

        Returns:
            True when the key is present and not only whitespace.
        """
        return bool(self.openai_api_key and self.openai_api_key.get_secret_value().strip())

    @property
    def max_conversation_tokens(self) -> int:
        """Token budget of a whole conversation (system prompt + history + question).

        The model must fit the full prompt *and* the answer in its context window,
        so the room reserved for the answer is subtracted from the window.

        Returns:
            The maximum number of prompt tokens a request may use.
        """
        return self.openai_context_window - self.openai_max_tokens


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance.

    Cached so `.env` is parsed only once; tests can call `get_settings.cache_clear()`.

    Returns:
        The loaded `Settings`.
    """
    return Settings()
