"""Dash application entry point.

Creates the app, applies the theme, registers layout and callbacks and exposes
`server` (the underlying Flask app) for gunicorn:

    gunicorn library_ui.app:server --bind 0.0.0.0:8050

For local development run `uv run python -m library_ui.app`.
"""

import logging
from pathlib import Path

import dash_bootstrap_components as dbc
from dash import Dash
from flask import Flask

from library_ui.api_client import BooksApiClient
from library_ui.callbacks import register_callbacks
from library_ui.config import Settings
from library_ui.layout import APP_NAME, CLIENT_NAME, build_layout

ASSETS_FOLDER = Path(__file__).parent / "assets"


def create_app(settings: Settings | None = None, client: BooksApiClient | None = None) -> Dash:
    """Build the Dash application.

    Args:
        settings: Frontend settings. Defaults to values read from the environment.
        client: API client. Defaults to one pointing at `settings.api_base_url`.

    Returns:
        The configured Dash app.
    """
    settings = settings or Settings.from_env()
    client = client or BooksApiClient(
        settings.api_base_url,
        timeout=settings.api_timeout_seconds,
        max_page_size=settings.api_max_page_size,
        api_key=settings.api_key,
    )

    app = Dash(
        __name__,
        title=f"{APP_NAME} · {CLIENT_NAME}",
        assets_folder=str(ASSETS_FOLDER),
        external_stylesheets=[dbc.themes.FLATLY, dbc.icons.BOOTSTRAP],
        meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
    )
    # The UI text is Brazilian Portuguese; declaring it helps screen readers and
    # stops browsers from offering to translate the page.
    app.index_string = app.index_string.replace("<html>", '<html lang="pt-BR">', 1)
    # A function (not a component) so the layout, and today's date limits in
    # the date pickers, are rebuilt on every page load.
    app.layout = build_layout
    register_callbacks(app, client, settings)
    return app


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
)
app = create_app()
server: Flask = app.server


if __name__ == "__main__":
    # Development server only (gunicorn never runs this block). With debug on,
    # Python changes restart the server and the open browser tab refreshes by
    # itself; CSS changes in assets/ are applied without a full reload.
    _settings = Settings.from_env()
    app.run(
        host=_settings.host,
        port=_settings.port,
        debug=_settings.debug,
        dev_tools_hot_reload=_settings.debug,
        use_reloader=_settings.debug,
    )
