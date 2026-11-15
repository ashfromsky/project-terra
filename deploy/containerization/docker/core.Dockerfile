# ==============================================================================
# PROJECT TERRA — Core Backend & Worker Container Image
# Multi-stage Docker build for terra-core API and terra-worker processes.
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Dependency resolution and non-editable wheel build
# ------------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Copy dependency manifests and committed lockfiles across all local packages
# to maximize Docker layer cache efficiency
COPY backend/scientific/pyproject.toml backend/scientific/uv.lock /app/backend/scientific/
COPY backend/core/pyproject.toml backend/core/uv.lock /app/backend/core/
COPY backend/worker/pyproject.toml backend/worker/uv.lock /app/backend/worker/

# Sync third-party wheels without installing the local packages yet
WORKDIR /app/backend/worker
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev

# Copy package source trees
COPY backend/scientific/src /app/backend/scientific/src
COPY backend/core/terra /app/backend/core/terra
COPY backend/worker/src /app/backend/worker/src

# Install terra-scientific, terra-core, and terra-worker as non-editable packages
# into the production virtual environment
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable --no-dev \
    --reinstall-package terra-core \
    --reinstall-package terra-scientific \
    --reinstall-package terra-worker


# ------------------------------------------------------------------------------
# Stage 2: Production SPA build (served by Core at the API origin)
# ------------------------------------------------------------------------------
FROM node:22-bookworm-slim AS frontend

WORKDIR /web

RUN corepack enable     && corepack prepare pnpm@12.19.0 --activate

COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN --mount=type=cache,target=/root/.npm \
    pnpm install --frozen-lockfile

COPY frontend/ ./
# Contracts are committed; skip the prebuild generator (it requires uv/Python).
RUN pnpm exec tsc -b && pnpm exec vite build


# ------------------------------------------------------------------------------
# Stage 3: Minimal, secure production runtime
# ------------------------------------------------------------------------------
FROM python:3.13-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/backend/worker/.venv/bin:${PATH}"

# Install minimal system certificates and configure non-root system user
RUN apt-get update \
    && apt-get install --no-install-recommends -y ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 terra \
    && useradd --system --uid 10001 --gid terra --create-home --home-dir /home/terra terra

WORKDIR /app

# Copy virtualenv and application directory with correct ownership
COPY --from=builder --chown=terra:terra /app /app
COPY --from=frontend --chown=terra:terra /web/dist /app/web

# Prepare writable directories for scientific artifacts and runtime storage
RUN mkdir -p /data/artifacts && chown -R terra:terra /data/artifacts

USER terra

ENV SCIENTIFIC_ARTIFACT_DIR=/data/artifacts \
    FRONTEND_DIST_DIR=/app/web
EXPOSE 8000

# Default health check targets Core API readiness endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3)"]

# Default entry point runs Core API via Granian; Core Worker overrides CMD
CMD ["granian", "--interface", "asgi", "--host", "0.0.0.0", "--port", "8000", "terra.main:app"]
