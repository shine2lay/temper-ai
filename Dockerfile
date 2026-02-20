# Temper AI — Multi-stage Docker build
# Targets: server (HTTP API) | runner (CLI workflow execution)
#
# Build:
#   docker build --target server -t temper-ai-server:latest .
#   docker build --target runner -t temper-ai-runner:latest .

# ── base ──────────────────────────────────────────────────────────────
FROM python:3.11.11-slim-bookworm AS base

ARG MAF_VERSION=0.1.0
ARG MAF_COMMIT=unknown

RUN apt-get update && \
    apt-get install -y --no-install-recommends git curl libpq5 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Layer optimisation: install deps first (changes less often than source)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml ./
COPY temper_ai/ ./temper_ai/
COPY configs/ ./configs/
COPY alembic/ ./alembic/
COPY alembic.ini ./

RUN pip install --no-cache-dir -e ".[dashboard]"

# ── server ────────────────────────────────────────────────────────────
FROM base AS server

LABEL org.opencontainers.image.title="Temper AI Server" \
      org.opencontainers.image.description="Temper AI HTTP API server" \
      org.opencontainers.image.version="${MAF_VERSION}" \
      org.opencontainers.image.revision="${MAF_COMMIT}" \
      org.opencontainers.image.source="https://github.com/temper-ai/temper-ai"

# Non-root user
RUN groupadd -r temperai && useradd -r -g temperai -d /app temperai
RUN mkdir -p /app/.temper-ai && chown -R temperai:temperai /app
USER temperai

ENV MAF_CONFIG_ROOT=/app/configs
EXPOSE 8420

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8420/api/health || exit 1

CMD ["temper-ai", "serve", "--host", "0.0.0.0", "--port", "8420"]

# ── runner ────────────────────────────────────────────────────────────
FROM base AS runner

LABEL org.opencontainers.image.title="Temper AI Runner" \
      org.opencontainers.image.description="Temper AI CLI workflow runner" \
      org.opencontainers.image.version="${MAF_VERSION}" \
      org.opencontainers.image.revision="${MAF_COMMIT}"

# Non-root user with workspace dir
RUN groupadd -r temperai && useradd -r -g temperai -d /workspace -m temperai
RUN mkdir -p /workspace && chown -R temperai:temperai /workspace
USER temperai

ENV MAF_CONFIG_ROOT=/app/configs
WORKDIR /workspace

ENTRYPOINT ["temper-ai", "run"]

# ── worker ────────────────────────────────────────────────────────────
FROM base AS worker

LABEL org.opencontainers.image.title="Temper AI Worker" \
      org.opencontainers.image.description="Temper AI background workflow worker" \
      org.opencontainers.image.version="${MAF_VERSION}" \
      org.opencontainers.image.revision="${MAF_COMMIT}"

# Non-root user
RUN groupadd -r temperai && useradd -r -g temperai -d /app temperai
RUN mkdir -p /app/.temper-ai && chown -R temperai:temperai /app
USER temperai

ENV MAF_CONFIG_ROOT=/app/configs

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import sys; sys.exit(0)"]

CMD ["temper-ai", "run", "--local", "--autonomous"]
