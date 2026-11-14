FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev

COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable --no-dev

FROM python:3.13-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}"

RUN apt-get update \
    && apt-get install --no-install-recommends -y ca-certificates libexpat1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system ghs \
    && useradd --system --gid ghs --create-home --home-dir /home/ghs ghs

WORKDIR /app
COPY --from=builder --chown=ghs:ghs /app /app
RUN mkdir -p /data/ghs_storage && chown -R ghs:ghs /data/ghs_storage

USER ghs

ENV LOCAL_STORAGE_DIR=/data/ghs_storage
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"]

CMD ["granian", "--interface", "asgi", "--host", "0.0.0.0", "--port", "8080", "geospatial_harmonization.main:app"]
