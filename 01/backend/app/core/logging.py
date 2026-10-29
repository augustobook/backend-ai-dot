"""Logging configuration for the application.

All application modules log through children of the `app` logger
(`logging.getLogger(__name__)`), so configuring it here is enough.
"""

import logging

APP_LOGGER_NAME = "app"
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def configure_logging(level: str) -> None:
    """Configure the application logger.

    Calling this function more than once is safe: the handler is only added
    the first time, while the level is always updated.

    Args:
        level: Minimum log level name, such as `"INFO"` or `"DEBUG"`.
    """
    logger = logging.getLogger(APP_LOGGER_NAME)
    logger.setLevel(level.upper())
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        logger.addHandler(handler)
