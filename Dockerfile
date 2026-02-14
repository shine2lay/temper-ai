# Meta-Autonomous Framework — Multi-stage Docker build
# Targets: server (HTTP API) | runner (CLI workflow execution)
#
# Build:
#   docker build --target server -t maf-server:latest .
#   docker build --target runner -t maf-runner:latest .

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
COPY src/ ./src/
COPY configs/ ./configs/
COPY alembic/ ./alembic/
COPY alembic.ini ./

RUN pip install --no-cache-dir -e ".[dashboard]"

# ── server ────────────────────────────────────────────────────────────
FROM base AS server

LABEL org.opencontainers.image.title="MAF Server" \
      org.opencontainers.image.description="Meta-Autonomous Framework HTTP API server" \
      org.opencontainers.image.version="${MAF_VERSION}" \
      org.opencontainers.image.revision="${MAF_COMMIT}" \
      org.opencontainers.image.source="https://github.com/meta-autonomous-framework/maf"

# Non-root user
RUN groupadd -r maf && useradd -r -g maf -d /app maf
RUN mkdir -p /app/.meta-autonomous && chown -R maf:maf /app
USER maf

ENV MAF_CONFIG_ROOT=/app/configs
EXPOSE 8420

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8420/api/health || exit 1

CMD ["maf", "serve", "--host", "0.0.0.0", "--port", "8420"]

# ── runner ────────────────────────────────────────────────────────────
FROM base AS runner

LABEL org.opencontainers.image.title="MAF Runner" \
      org.opencontainers.image.description="Meta-Autonomous Framework CLI workflow runner" \
      org.opencontainers.image.version="${MAF_VERSION}" \
      org.opencontainers.image.revision="${MAF_COMMIT}"

# Non-root user with workspace dir
RUN groupadd -r maf && useradd -r -g maf -d /workspace -m maf
RUN mkdir -p /workspace && chown -R maf:maf /workspace
USER maf

ENV MAF_CONFIG_ROOT=/app/configs
WORKDIR /workspace

ENTRYPOINT ["maf", "run"]
