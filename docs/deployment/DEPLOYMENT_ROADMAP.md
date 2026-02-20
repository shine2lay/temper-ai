# Temper AI — Deployment Roadmap

## Implementation Order

| Phase | Work | Depends on |
|-------|------|-----------|
| **Phase 1** | PostgreSQL everywhere (local + server) | — |
| **Phase 2** | Configuration layer (`TEMPER_*` env vars, config file) | Phase 1 |
| **Phase 3** | API completeness (all CLI commands as endpoints) | Phase 2 |
| **Phase 4** | Workflow job runner (DB-backed queue + worker) | Phase 1, 3 |
| **Phase 5** | CLI refactor (thin HTTP client) | Phase 3, 4 |
| **Phase 6** | Auth (API key middleware) | Phase 3 |
| **Phase 7** | Docker Compose production stack | Phase 1-6 |
| **Phase 8** | Dev experience (`init`, `--reload`, `--debug`, mock LLM) | Phase 2-5 |

---

## 1. Database: PostgreSQL Everywhere

**Decision:** PostgreSQL for both local dev and server. No SQLite. One dialect, zero parity issues.

**Why:** Dev/prod parity is a core principle. Maintaining two SQL dialects (SQLite quirks vs PostgreSQL) adds testing burden and hides bugs. Local dev should be a miniature production.

**Local setup:** `temper-ai init` starts a PostgreSQL container via Docker (or connects to an existing local instance). One command, no manual setup.

**Implementation approach:**
- Configuration: `TEMPER_DATABASE_URL` env var (default: `postgresql://temper:temper@localhost:5432/temper`)
- Connection pooling: `QueuePool` everywhere
- Remove all SQLite-specific syntax — PostgreSQL only:
  - `JSONB` for flexible fields
  - `TIMESTAMPTZ` for all timestamps
  - `UUID` primary keys via `gen_random_uuid()`
- Alembic migrations target PostgreSQL only
- `temper-ai init` handles local PostgreSQL setup (Docker container or connection URL prompt)
- `temper-ai db reset` / `temper-ai db migrate` wrap Alembic for convenience

**Memory/Context (pgvector):** mem0 supports PostgreSQL via pgvector for vector storage. A single PostgreSQL instance with the pgvector extension serves both workflow data and memory/context. No separate vector DB needed initially.

**Unified PostgreSQL role:**
```
PostgreSQL (pgvector extension)
├── Workflow data     — runs, stages, agents, checkpoints
├── Observability     — events, metrics, traces
├── Memory/context    — mem0-compatible vector storage
└── Job queue         — workflow execution queue (SELECT FOR UPDATE SKIP LOCKED)
```

**Future consideration:** If observability data volume grows, split time-series metrics to TimescaleDB extension. If vector search latency matters at scale, move to dedicated vector DB (Qdrant, Milvus). Not needed initially.

**Industry reference:** LangFlow, Dify, Flowise all use PostgreSQL for production.

---

## 2. Workflow Execution Model: DB-backed Job Runner

**Decision:** DB-backed async job runner as default. Optional Celery + Redis backend for high-throughput.

**Why:** Self-hosters shouldn't need Redis/RabbitMQ just to run workflows. PostgreSQL is already there — use it as the job queue. LangFlow and Flowise both take this approach (optional async, no mandatory broker).

**How it works:**
- Workflow submitted via API → row inserted into `job_queue` table with status `pending`
- Background worker loop: `SELECT ... FOR UPDATE SKIP LOCKED` to claim jobs
- Worker executes workflow, updates status (`running` → `completed`/`failed`)
- Existing checkpoint system handles crash recovery (resume from last checkpoint)
- API polls job status or uses WebSocket for real-time updates (already exists)

**Job table schema (conceptual):**
```sql
CREATE TABLE workflow_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_config JSONB NOT NULL,
    input_data JSONB,
    status VARCHAR(20) DEFAULT 'pending',  -- pending, running, completed, failed, cancelled
    worker_id VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    result JSONB,
    error TEXT,
    priority INT DEFAULT 0
);
CREATE INDEX idx_jobs_pending ON workflow_jobs (priority DESC, created_at ASC) WHERE status = 'pending';
```

**Worker architecture:**
- `temper-ai serve` starts API server + built-in worker pool (configurable concurrency)
- `temper-ai worker` — standalone worker process (optional, for scaling)
- Workers are just Python processes polling the DB — no broker dependency
- Concurrency: `TEMPER_WORKER_CONCURRENCY` env var (default: 2)

**Scaling path:**
1. **Small (default):** Built-in worker pool in `temper-ai serve` (1-5 concurrent workflows)
2. **Medium:** Separate `temper-ai worker` processes on same or different machines
3. **Large:** Optional Celery + Redis backend for horizontal scaling, streaming fan-out

**Local mode:** `temper-ai run` becomes syntactic sugar — submits to local job queue through the same path as server mode.

**Industry reference:** LangFlow uses APScheduler + SQLModel JobStore. Flowise offers standard mode (sync) + queue mode (BullMQ/Redis). CrewAI is in-process only. Dify requires Celery + Redis.

---

## 3. Configuration: Unified Config + Dev/Prod Parity

**Decision:** One execution model, two scale profiles. Local mode is a miniature production — same code paths, different config values.

**Principle:** No "it works locally but breaks in production" — the only differences between local and server are config values (database URL, auth on/off, concurrency).

### Config hierarchy (env vars override config file):
```
1. CLI flags (highest priority)
2. Environment variables (TEMPER_*)
3. ~/.temper/config.yaml (user config)
4. Built-in defaults (lowest priority)
```

### Environment variables:
```bash
TEMPER_DATABASE_URL=postgresql://temper:temper@localhost:5432/temper
TEMPER_LLM_PROVIDER=openai          # default: ollama
TEMPER_OPENAI_API_KEY=sk-...
TEMPER_WORKER_CONCURRENCY=4         # default: 1 (local), 4 (server)
TEMPER_CORS_ORIGINS=https://app.example.com
TEMPER_SECRET_KEY=...               # required in server mode
TEMPER_LOG_LEVEL=info               # default: info
TEMPER_DEBUG=true                    # verbose logging, slower timeouts, no caching
```

### Local vs Server — same code, different config:

| Aspect | Local | Server |
|--------|-------|--------|
| API server | `temper-ai serve` (same FastAPI) | Same, behind reverse proxy |
| Worker | Built-in (in-process, concurrency=1) | Separate `temper-ai worker` or in-process |
| Database | PostgreSQL (local container) | PostgreSQL |
| Auth | Disabled by default, can enable | Required |
| Hot reload | `--reload` flag (watchfiles) | Off |
| Config | `~/.temper/config.yaml` + env vars | Env vars / `.env` |
| Dashboard | Same React app | Same |

### `temper-ai run` behavior:
- Becomes syntactic sugar: starts ephemeral server, submits job through same queue, streams output, exits
- Same job queue code path as server mode — no divergence

### Developer experience features (v1 priority):

**P0 — must have:**
- **Hot reload:** `temper-ai serve --reload` — restart on Python code changes (FastAPI watchfiles) + filesystem watcher on `configs/` to signal workers to reload YAML without restart
- **`temper-ai init`:** First-run scaffolding — copies example configs, creates DB, prints quick start instructions. Critical for adoption.
- **Debug mode:** `TEMPER_DEBUG=true` or `--debug` — verbose logging, full tracebacks, slower timeouts, no LLM caching
- **DB commands:** `temper-ai db reset` (drop + migrate), `temper-ai db migrate` (wraps Alembic)
- **Mock LLM:** Built-in echo/canned response provider for developing workflows without burning API credits

**P1 — fast follow:**
- **Cost preview:** `temper-ai estimate workflow.yaml` — token count x pricing before running
- **Config watch:** Live re-read of YAML configs without server restart
- **Seed data:** `temper-ai init --demo` — populate example workflows with sample results
- **Inline errors:** Rich tracebacks in terminal + dashboard error panel

### Secrets handling:
- API keys via env vars or `~/.temper/secrets.yaml` (gitignored by default)
- Never in workflow YAML configs that get committed
- `temper-ai init` generates `.gitignore` that excludes secrets

---

## 4. Authentication: API Key (simple)

**Decision:** API key auth for server mode. No OAuth until enterprise demand exists.

**How it works:**
- Set `TEMPER_API_KEY=your-secret-key` in env
- All API requests must include `Authorization: Bearer your-secret-key`
- If `TEMPER_API_KEY` is not set, auth is disabled (local mode default)
- FastAPI middleware — single check, zero external dependencies
- Dashboard inherits auth via session cookie set on first valid API key submission

**Implementation:**
- Middleware in `temper_ai/interfaces/server/auth.py` (file already exists)
- Check `Authorization` header on all `/api/*` routes
- Skip auth for health check (`/health`) and static dashboard assets (`/app/*` after login)
- Return 401 with clear error message if key missing/wrong
- `temper-ai serve --api-key=...` as alternative to env var

**Future (when needed):**
- Multiple API keys with scopes (read-only, execute, admin)
- OAuth / SSO via reverse proxy (`X-Forwarded-User` trust)
- Per-user audit trails

---

## 5. Docker Compose (Production): 3 Containers, No Broker

**Decision:** Minimal production stack — API server, worker, PostgreSQL. No Redis/broker required.

**Architecture:**
```yaml
services:
  temper-ai:          # API server + dashboard (FastAPI + React)
  temper-worker:      # Background job worker (same image, different entrypoint)
  postgres:           # PostgreSQL + pgvector extension
```

**docker-compose.yml features:**
- PostgreSQL with pgvector image (`pgvector/pgvector:pg16`)
- Named volume `temper-db-data` for database persistence
- Shared `.env` file for all services (DB URL, API key, LLM keys)
- Health checks on all services:
  - postgres: `pg_isready`
  - temper-ai: `/health` endpoint
  - temper-worker: custom health check (last heartbeat)
- `depends_on` with health check conditions (worker waits for postgres + API)
- Restart policy: `unless-stopped`
- Resource limits: memory cap on worker to prevent runaway workflows
- Exposed ports: `8420:8420` (API + dashboard)

**Entrypoints:**
```yaml
temper-ai:
  command: ["temper-ai", "serve", "--host", "0.0.0.0", "--port", "8420"]

temper-worker:
  command: ["temper-ai", "worker", "--concurrency", "4"]
```

**`.env` file (shared by all services):**
```bash
TEMPER_DATABASE_URL=postgresql://temper:temper@postgres:5432/temper
TEMPER_API_KEY=change-me-in-production
TEMPER_LLM_PROVIDER=openai
TEMPER_OPENAI_API_KEY=sk-...
TEMPER_WORKER_CONCURRENCY=4
TEMPER_LOG_LEVEL=info
```

**Optional production override (`docker-compose.prod.yml`):**
- Caddy/Nginx sidecar for HTTPS termination and automatic certificates
- Documented separately, not in default compose

**Dockerfile updates needed:**
- Multi-stage build (build frontend → slim Python runtime)
- Non-root user (already partially done)
- Health check instruction built into image

---

## 6. API Completeness: API-First, CLI as Thin Client

**Decision:** The REST API is the primary interface. The CLI becomes a thin client that calls the API — no direct Python imports. This makes local and remote usage identical.

**Principle:** `temper-ai run workflow.yaml` and `temper-ai --server https://myserver.com run workflow.yaml` use the same code path — the only difference is the base URL (localhost vs remote).

**CLI refactor:**
```
Before: CLI → imports Python modules → executes directly
After:  CLI → HTTP calls to API → server executes
```

- `temper-ai serve` starts the server (always required, even locally)
- All other commands become API client calls
- `temper-ai serve --run workflow.yaml` as convenience shortcut (start server, submit job, stream output, exit)
- `--server URL` flag to point at remote instance (default: `http://localhost:8420`)

**API endpoints needed (audit against CLI subcommands):**

| CLI Command | API Endpoint | Status |
|-------------|-------------|--------|
| `temper-ai run <workflow>` | `POST /api/workflows/run` | Exists (partial) |
| `temper-ai list workflows\|agents\|stages` | `GET /api/workflows`, `GET /api/agents`, `GET /api/stages` | Partial |
| `temper-ai validate <config>` | `POST /api/validate` | Missing |
| `temper-ai experiment list\|create\|start\|stop\|results` | `CRUD /api/experiments/*` | Missing |
| `temper-ai autonomy audit\|apply-pending` | `GET/POST /api/autonomy/*` | Missing |
| `temper-ai lifecycle adapt\|rollback` | `POST /api/lifecycle/*` | Missing |
| `temper-ai goals propose\|review` | `CRUD /api/goals/*` | Exists (dashboard routes) |
| `temper-ai learning mine\|recommend` | `POST /api/learning/*` | Missing |
| `temper-ai portfolio schedule\|optimize` | `CRUD /api/portfolio/*` | Exists (dashboard routes) |
| `temper-ai config create\|update\|delete` | `CRUD /api/config/*` | Exists (studio routes) |
| `temper-ai db migrate\|reset` | `POST /api/admin/db/*` | Missing |
| `temper-ai logs <run-id>` | `GET /api/runs/{id}/logs` | Exists |
| `temper-ai dashboard` | N/A (opens browser to `/app/`) | N/A |
| `temper-ai init` | N/A (local scaffolding only) | N/A |
| `temper-ai worker` | N/A (starts worker process) | N/A |

**Implementation order:**
1. Core execution: `/api/workflows/run`, `/api/jobs/{id}/status`, WebSocket streaming
2. CRUD: experiments, lifecycle, goals, learning, portfolio (many dashboard routes exist)
3. Admin: validate, db migrate/reset
4. CLI refactor: swap direct imports for HTTP client calls
5. Auth: all endpoints gated by API key middleware

**API design conventions:**
- RESTful: nouns for resources, verbs via HTTP methods
- Consistent response envelope: `{ "data": ..., "error": null }`
- Pagination: `?page=1&per_page=20` on list endpoints
- Streaming: WebSocket for real-time workflow output, SSE as fallback
- OpenAPI spec auto-generated by FastAPI (already works)

---

## Open-Source Prep (before public release)

**Done:**
- [x] LICENSE — Apache 2.0 + NOTICE file
- [x] Package rename — `temper_ai/`, CLI `temper-ai`, PyPI `temper-ai`
- [x] Dashboard rebrand — all MAF references → Temper AI

**TODO (save for later — after deployment work is done):**
- [ ] README rewrite — public-facing: hook, quick start, features, architecture, examples
- [ ] Security scrub — grep for hardcoded secrets, internal URLs, private infra references
- [ ] CI pipeline — GitHub Actions: lint, test, build on PR; PyPI publish on release tag
- [ ] Test failures — fix 81 pre-existing failures in security/circuit breaker tests
- [ ] CONTRIBUTING.md — dev setup, how to run tests, PR process, code style
- [ ] .gitignore review — ensure no .env, db files, build artifacts leak
- [ ] SECURITY.md — vulnerability reporting process
- [ ] Dependency cleanup — audit pyproject.toml for unused/overly-pinned deps
- [ ] Git history — decide squash vs keep before making repo public
