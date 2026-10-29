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
# when pyproject.toml or uv.lock change. `--no-dev` leaves pytest, ruff, mypy
# and respx out of the image. The cache mount keeps wheels between builds.
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
COPY library_ui ./library_ui

# Inside Docker Compose the API is reached by its service name, not localhost;
# docker-compose.yml sets API_BASE_URL=http://api:8000 explicitly as well.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    API_BASE_URL=http://api:8000

USER app

EXPOSE 8050

# python:slim has no curl, so the health check uses the standard library.
HEALTHCHECK --interval=15s --timeout=3s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8050/', timeout=2)"]

# Production server: gunicorn serves the Flask app behind Dash (not the Dash
# development server). Threads let one worker handle concurrent callbacks
# while waiting on the API.
CMD ["gunicorn", "library_ui.app:server", "--bind", "0.0.0.0:8050", "--workers", "2", "--threads", "4", "--access-logfile", "-"]
