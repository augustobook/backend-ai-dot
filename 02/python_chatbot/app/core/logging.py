"""Logging configuration shared by every entry point (CLI, API, web UI, scripts)."""

import logging

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

# Third-party libraries that are too chatty at INFO level.
_NOISY_LOGGERS = ("httpx", "httpcore", "openai", "langsmith")


def configure_logging(level: str = "INFO") -> None:
    """Configure the root logger with a single, consistent format.

    Args:
        level: Logging level name (e.g. "DEBUG", "INFO", "WARNING").
    """
    # `force=True` replaces handlers installed by other libraries (e.g. uvicorn,
    # Chainlit) so every log line has the same format.
    logging.basicConfig(level=level.upper(), format=LOG_FORMAT, force=True)

    # HTTP client logs would print every request to OpenAI; keep only warnings.
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
