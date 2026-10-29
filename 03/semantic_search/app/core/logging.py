"""Logging configuration shared by the CLI, the API and the web UI."""

import logging

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"

# Libraries that log a line per HTTP request or per file; kept at WARNING so the
# application's own timing logs stay readable.
NOISY_LOGGERS = ("httpx", "httpcore", "urllib3", "huggingface_hub", "filelock")


def configure_logging(level: str = "INFO") -> None:
    """Configure the root logger once for the whole process.

    Args:
        level: Logging level name (e.g. "INFO", "DEBUG").
    """
    logging.basicConfig(level=level.upper(), format=LOG_FORMAT, force=True)
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
