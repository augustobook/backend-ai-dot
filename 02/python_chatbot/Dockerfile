# syntax=docker/dockerfile:1

# Pinned uv image (never `latest`) so builds are reproducible.
FROM ghcr.io/astral-sh/uv:0.11.21 AS uv

# ---------------------------------------------------------------------------
# Stage 1: builder - resolves and installs the production dependencies.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

# Only the uv binary is needed; it never reaches the final image.
COPY --from=uv /uv /usr/local/bin/uv

# Compile bytecode for faster startup, copy files out of the cache mount
# (hard links would break across mounts), and use the image's Python instead
# of downloading one.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Dependencies first: this layer is only rebuilt when pyproject.toml or
# uv.lock change. `--no-dev` leaves pytest, ruff and mypy out of the image.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project

# The project itself is a package (`app`), installed without its dependencies.
COPY pyproject.toml uv.lock README.md ./
COPY app ./app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# ---------------------------------------------------------------------------
# Stage 2: runtime - just Python, the virtualenv and the application code.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# Run as an unprivileged user so a compromised process cannot modify the image.
RUN groupadd --system app && useradd --system --gid app --home-dir /app app

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY app ./app
# Chainlit reads its config, welcome page and static files from the working dir.
# On startup it writes any missing translation file into .chainlit/translations
# (git only keeps pt-BR.json), so that folder must belong to `app`.
COPY --chown=app:app .chainlit ./.chainlit
COPY public ./public
COPY chainlit.md ./

# The SQLite conversation history and the generated auth secret live in
# /app/data (a named volume in docker-compose); Chainlit writes uploads to
# /app/.files. Both must belong to `app`.
RUN mkdir -p /app/data /app/.files && chown app:app /app/data /app/.files

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    CHAINLIT_DATABASE_PATH=/app/data/chat_history.db

USER app

EXPOSE 8000

# python:slim has no curl, so the health check uses the standard library.
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/', timeout=2)"]

# `--headless` keeps Chainlit from trying to open a browser inside the container.
CMD ["chainlit", "run", "app/ui/chainlit_app.py", "--host", "0.0.0.0", "--port", "8000", "--headless"]
