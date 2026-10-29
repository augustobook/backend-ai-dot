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
# uv.lock change. pyproject.toml pins torch to the CPU-only index, so the
# CUDA libraries never reach the image.
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
# Stage 2: runtime - just Python, the virtualenv, the code and the index.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# Run as an unprivileged user so a compromised process cannot modify the image.
RUN groupadd --system app && useradd --system --gid app --home-dir /app app

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY app ./app
# The prebuilt FAISS index ships with the image; the documents allow
# rebuilding it with `python -m app.cli ingest` inside the container.
COPY storage ./storage
COPY data ./data

# The Hugging Face models are downloaded on the first start into
# /app/.cache/huggingface, a named volume in docker-compose, so later
# restarts and rebuilds reuse them. The directory must belong to `app`.
RUN mkdir -p /app/.cache/huggingface && chown -R app:app /app/.cache /app/storage

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/app/.cache/huggingface \
    DEVICE=cpu

USER app

EXPOSE 8065

# The first start downloads both models, hence the long start period.
HEALTHCHECK --interval=15s --timeout=3s --start-period=300s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8065/', timeout=2)"]

# One worker on purpose: each worker is a process with its own copy of both
# models, so concurrency comes from threads. The long timeout covers the model
# loading done by the `create_server()` factory.
CMD ["gunicorn", "app.ui.dash_app:create_server()", "--bind", "0.0.0.0:8065", "--workers", "1", "--threads", "4", "--timeout", "300", "--access-logfile", "-"]
