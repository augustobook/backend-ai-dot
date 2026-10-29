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

# Install dependencies before copying the code: this layer is only rebuilt
# when pyproject.toml or uv.lock change, not on every code change. The cache
# mount keeps downloaded wheels between builds.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project

# ---------------------------------------------------------------------------
# Stage 2: runtime - just Python, the virtualenv and the application code.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# Run as an unprivileged user so a compromised process cannot modify the image.
RUN groupadd --system app && useradd --system --gid app --home-dir /app app

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY app ./app

# SQLite lives in /app/data, which docker-compose mounts as a named volume so
# the books survive container restarts. The directory must belong to `app`.
RUN mkdir -p /app/data && chown app:app /app/data

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    DATABASE_URL=sqlite:////app/data/library.db

USER app

EXPOSE 8000

# python:slim has no curl, so the health check uses the standard library.
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]

# Server-level limits: at most 100 concurrent connections (extra ones get 503
# instead of piling up), idle keep-alive connections closed after 5 s, and no
# `server: uvicorn` header advertising the stack.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--limit-concurrency", "100", "--timeout-keep-alive", "5", "--no-server-header"]
