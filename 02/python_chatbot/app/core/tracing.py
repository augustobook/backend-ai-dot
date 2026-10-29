"""Optional LangSmith tracing setup.

LangChain sends traces to LangSmith automatically when the `LANGSMITH_*` variables
are present in the process environment. Settings may come from `.env` (which
pydantic-settings does not export), so this module copies them to `os.environ`.
Without LangSmith configured, tracing stays off and the app works normally.
"""

import logging
import os

from app.core.config import Settings

logger = logging.getLogger(__name__)


def configure_tracing(settings: Settings) -> bool:
    """Enable or disable LangSmith tracing based on the settings.

    Args:
        settings: Application settings.

    Returns:
        True when tracing was enabled, False otherwise.
    """
    api_key = settings.langsmith_api_key.get_secret_value() if settings.langsmith_api_key else ""

    # Tracing is opt-in: do nothing unless it was explicitly requested.
    if not settings.langsmith_tracing:
        os.environ["LANGSMITH_TRACING"] = "false"
        logger.debug("LangSmith tracing is disabled.")
        return False

    # Tracing without a key would fail on every run; warn once and keep working.
    if not api_key.strip():
        os.environ["LANGSMITH_TRACING"] = "false"
        logger.warning("LANGSMITH_TRACING is true but LANGSMITH_API_KEY is empty; tracing is off.")
        return False

    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = api_key
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint
    logger.info("LangSmith tracing enabled (project=%s).", settings.langsmith_project)
    return True
