"""Frontend settings read from environment variables or a local `.env` file.

Values set in the environment take precedence over the `.env` file.

| Variable              | Default                 | Meaning                                  |
| --------------------- | ----------------------- | ---------------------------------------- |
| `API_BASE_URL`        | `http://localhost:8000` | Base URL of the Library API              |
| `API_KEY`             | (empty)                 | Sent as `X-API-Key` when the API needs it |
| `API_TIMEOUT_SECONDS` | `5`                     | Timeout of each HTTP request to the API  |
| `API_MAX_PAGE_SIZE`   | `100`                   | Highest `limit` the API accepts          |
| `SEARCH_PAGE_SIZE`    | `10`                    | Rows per page in the Search screen       |
| `DASH_HOST`           | `127.0.0.1`             | Host of the Dash development server      |
| `DASH_PORT`           | `8050`                  | Port of the Dash development server      |
| `DASH_DEBUG`          | `true`                  | Dev server auto-reload + browser refresh |
| `PUBLIC_API_URL`      | `API_BASE_URL`          | API URL written in the Postman download  |
| `POSTMAN_INCLUDE_API_KEY` | `false`             | Put `API_KEY` in the Postman download    |
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

TRUTHY = {"1", "true", "yes", "on"}
DEFAULT_ENV_FILE = Path(".env")


def read_env_file(path: Path) -> dict[str, str]:
    """Read `KEY=value` pairs from a `.env` file.

    Blank lines and `#` comments are skipped, and surrounding quotes are
    removed. A missing file yields an empty mapping.

    Args:
        path: Location of the `.env` file.

    Returns:
        The variables defined in the file.
    """
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("\"'")
    return values


@dataclass(frozen=True, slots=True)
class Settings:
    """Immutable frontend configuration.

    Attributes:
        api_base_url: Base URL of the Library API, without a trailing slash.
        api_key: API key sent in `X-API-Key`; `None` when the API has no key.
            Excluded from `repr` so it never shows up in logs.
        api_timeout_seconds: Timeout applied to every API request.
        api_max_page_size: Highest `limit` accepted by the API.
        search_page_size: Number of rows shown per page in the Search screen.
        host: Host the Dash development server binds to.
        port: Port the Dash development server listens on.
        debug: Whether the development server runs in debug mode, restarting on
            code changes and refreshing the browser automatically. Only used by
            `python -m library_ui.app`; gunicorn ignores it.
        public_api_url: API URL reachable from the user's machine, written into
            the downloadable Postman collection. `api_base_url` may be an
            internal Docker name, so it can differ. Empty means `api_base_url`.
        postman_include_api_key: Whether the downloaded collection carries
            `api_key`. Only for public demos, where the key is already public.
    """

    api_base_url: str = "http://localhost:8000"
    api_key: str | None = field(default=None, repr=False)
    api_timeout_seconds: float = 5.0
    api_max_page_size: int = 100
    search_page_size: int = 10
    host: str = "127.0.0.1"
    port: int = 8050
    debug: bool = True
    public_api_url: str = ""
    postman_include_api_key: bool = False

    @property
    def postman_base_url(self) -> str:
        """Base URL written into the downloadable Postman collection."""
        return self.public_api_url or self.api_base_url

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Self:
        """Build settings from environment variables, falling back to defaults.

        Args:
            environ: Mapping to read from. Defaults to the variables of a local
                `.env` file overridden by `os.environ`.

        Returns:
            The resulting settings.
        """
        # Real environment variables win over the .env file (as in the backend).
        env = {**read_env_file(DEFAULT_ENV_FILE), **os.environ} if environ is None else environ
        defaults = cls()
        return cls(
            # A trailing slash would produce URLs such as `http://api//books`.
            api_base_url=env.get("API_BASE_URL", defaults.api_base_url).rstrip("/"),
            # A blank API_KEY means "the API does not require one".
            api_key=env.get("API_KEY", "").strip() or None,
            api_timeout_seconds=float(env.get("API_TIMEOUT_SECONDS", defaults.api_timeout_seconds)),
            api_max_page_size=int(env.get("API_MAX_PAGE_SIZE", defaults.api_max_page_size)),
            search_page_size=int(env.get("SEARCH_PAGE_SIZE", defaults.search_page_size)),
            host=env.get("DASH_HOST", defaults.host),
            port=int(env.get("DASH_PORT", defaults.port)),
            debug=env.get("DASH_DEBUG", str(defaults.debug)).strip().lower() in TRUTHY,
            public_api_url=env.get("PUBLIC_API_URL", "").strip().rstrip("/"),
            postman_include_api_key=env.get("POSTMAN_INCLUDE_API_KEY", "").strip().lower()
            in TRUTHY,
        )
