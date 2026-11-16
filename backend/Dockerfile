# Base image pinned by digest (python:3.11-slim index, resolved 2026-11-16). To update, resolve the new
# digest with `docker buildx imagetools inspect python:3.11-slim`, rebuild and run the tests.
ARG PYTHON_IMAGE=python:3.11-slim@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535

# --- Build stage: install the locked runtime dependencies (no dev extras) into /opt/venv ---
FROM ${PYTHON_IMAGE} AS builder
# uv (pinned by digest) installs exactly what uv.lock records, with its hashes.
COPY --from=ghcr.io/astral-sh/uv:0.9.12@sha256:0eaa66c625730a3b13eb0b7bfbe085ed924b5dca6240b6f0632b4256cfb53f31 \
    /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /build
# Only the manifests, so this layer is cached until dependencies change.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# --- Runtime stage ---
FROM ${PYTHON_IMAGE}

# Static ffmpeg/ffprobe (multi-arch, pinned by digest): the worker cuts one preview frame per recording.
COPY --from=mwader/static-ffmpeg:7.1.1@sha256:11a44711684c0b9f754c047dcd64235b8b52deab251bd0e0a86f22faa160749c \
    /ffmpeg /ffprobe /usr/local/bin/

# Unprivileged runtime user with a fixed uid/gid. The code stays root-owned (read-only for it).
RUN groupadd --system --gid 10001 sauri \
    && useradd --system --uid 10001 --gid 10001 --create-home --home-dir /home/sauri --shell /usr/sbin/nologin sauri

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY . .

USER sauri

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
