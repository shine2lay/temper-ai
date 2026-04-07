# Temper AI — Multi-stage Docker build
#
# Build:
#   docker build --target server -t temper-ai:latest .

# ── base ──────────────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS base

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl libpq5 git && \
    rm -rf /var/lib/apt/lists/*

# Node.js — needed by agents that scaffold/verify Expo projects
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install deps first (layer caching)
COPY pyproject.toml uv.lock README.md ./
RUN mkdir -p temper_ai && touch temper_ai/__init__.py && \
    uv sync --frozen --no-dev

ENV PYTHONDONTWRITEBYTECODE=1
COPY temper_ai/ ./temper_ai/
# Remove any .pyc from the COPY — prevents stale bytecode when
# source is volume-mounted in dev (the .pyc would shadow newer .py files)
RUN find /app/temper_ai -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

# ── frontend ─────────────────────────────────────────────────────────
FROM base AS frontend-build

COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN cd frontend && npm ci --ignore-scripts

COPY frontend/ ./frontend/
RUN cd frontend && npx vite build

# ── server ────────────────────────────────────────────────────────────
FROM base AS server

# Copy pre-built frontend (used if frontend/dist is not volume-mounted)
COPY --from=frontend-build /app/frontend/dist /app/frontend/dist

RUN groupadd -r temperai && useradd -r -g temperai -d /app temperai && \
    chown -R temperai:temperai /app && \
    mkdir -p /tmp/workspaces && chown temperai:temperai /tmp/workspaces && \
    mkdir -p /app/.claude /app/.local/bin /opt/claude/versions && \
    chown -R temperai:temperai /app/.claude /app/.local /opt/claude
ENV PATH="/app/.local/bin:${PATH}"
COPY --chown=temperai:temperai entrypoint.sh /app/entrypoint.sh

USER temperai

EXPOSE 8420

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8420/api/health || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uv", "run", "uvicorn", "temper_ai.server:app", "--host", "0.0.0.0", "--port", "8420"]
