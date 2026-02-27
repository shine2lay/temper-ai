# Temper AI — Multi-stage Docker build
# Targets: server (HTTP API)
#
# Build:
#   docker build --target server -t temper-ai-server:latest .

# ── base ──────────────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS base

ARG TEMPER_VERSION=1.0.0
ARG TEMPER_COMMIT=unknown

RUN apt-get update && \
    apt-get install -y --no-install-recommends git curl libpq5 && \
    rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Layer optimisation: install deps first (changes less often than source)
COPY pyproject.toml uv.lock README.md ./
RUN mkdir -p temper_ai && touch temper_ai/__init__.py && \
    uv sync --frozen --no-dev --extra dashboard

# Copy source and install package (deps already cached above)
COPY temper_ai/ ./temper_ai/
COPY configs/ ./configs/
COPY alembic/ ./alembic/
COPY alembic.ini ./

# ── server ────────────────────────────────────────────────────────────
FROM base AS server

LABEL org.opencontainers.image.title="Temper AI Server" \
      org.opencontainers.image.description="Temper AI HTTP API server" \
      org.opencontainers.image.version="${TEMPER_VERSION}" \
      org.opencontainers.image.revision="${TEMPER_COMMIT}" \
      org.opencontainers.image.source="https://github.com/temper-ai/temper-ai"

# Non-root user
RUN groupadd -r temperai && useradd -r -g temperai -d /app temperai
RUN mkdir -p /app/.temper-ai && chown -R temperai:temperai /app
USER temperai

ENV TEMPER_CONFIG_ROOT=/app/configs
EXPOSE 8420

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8420/api/health || exit 1

CMD ["temper-ai", "serve", "--host", "0.0.0.0", "--port", "8420"]
