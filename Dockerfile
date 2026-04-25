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

# ── worker ────────────────────────────────────────────────────────────
# Heavier image with toolchain agents need to actually exercise their work
# (pytest, npm, docker CLI, db clients). Runs the watch-queue daemon which
# polls Postgres for queued workflow runs and spawns each as a subprocess.
#
# Build:
#   docker build --target worker -t temper-ai-worker:latest .
#
# Toolchain rationale: bake the system layer (apt) so agents never need
# sudo at runtime; leave the language layer (pip --user, npm) to runtime
# so per-project deps don't bloat the image. Mirrors the GitHub Actions
# runner pattern. Iterate the bake list as gaps surface in real runs.

FROM base AS worker

USER root

# System libs needed to compile common Python packages from source
# (psycopg2, cryptography, pillow, etc.) without the agent hitting "no
# such header" errors mid-pip-install.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        g++ \
        make \
        pkg-config \
        libpq-dev \
        libssl-dev \
        libffi-dev \
        zlib1g-dev \
        libsqlite3-dev \
        postgresql-client \
        redis-tools \
        jq \
        vim-tiny \
        ca-certificates \
        gnupg \
    && rm -rf /var/lib/apt/lists/*

# Docker CLI + compose plugin (no daemon — uses host socket via DooD)
RUN install -m 0755 -d /etc/apt/keyrings && \
    curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc && \
    chmod a+r /etc/apt/keyrings/docker.asc && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" \
        > /etc/apt/sources.list.d/docker.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        docker-ce-cli \
        docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for the watcher + spawned workers. UID 1000 chosen to
# match common host user IDs so workspace files written by the worker
# stay readable on the host without chowning.
RUN groupadd -g 1000 temperai-worker && \
    useradd -u 1000 -g 1000 -m -s /bin/bash temperai-worker && \
    mkdir -p /app/.local/bin && \
    chown -R temperai-worker:temperai-worker /app

# /var/run/docker.sock is mounted from host at runtime; user's group
# membership for it is added via docker-compose `group_add` at deploy
# time (the host's docker GID isn't known at build time).

USER temperai-worker

ENV PATH="/home/temperai-worker/.local/bin:/app/.local/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1

# Default: run the watcher. Spawned workers are subprocesses of this
# command (see temper_ai/cli/watch_queue.py).
CMD ["uv", "run", "python", "-m", "temper_ai.cli.main", "watch-queue"]
