# Temper AI — Multi-stage Docker build
#
# Build:
#   docker build --target server -t temper-ai:latest .

# ── base ──────────────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS base

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl libpq5 && \
    rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install deps first (layer caching)
COPY pyproject.toml uv.lock README.md ./
RUN mkdir -p temper_ai && touch temper_ai/__init__.py && \
    uv sync --frozen --no-dev

COPY temper_ai/ ./temper_ai/

# ── server ────────────────────────────────────────────────────────────
FROM base AS server

RUN groupadd -r temperai && useradd -r -g temperai -d /app temperai && \
    chown -R temperai:temperai /app
USER temperai

EXPOSE 8420

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8420/api/health || exit 1

CMD ["uv", "run", "uvicorn", "temper_ai.server:app", "--host", "0.0.0.0", "--port", "8420"]
