# 15 — Multi-Tenant Server Mode: End-to-End Flow Trace

**Document:** 15-flow-multi-tenant.md
**System:** temper-ai (Meta-Autonomous Framework)
**Scope:** Complete lifecycle trace of multi-tenant server operation — from `temper-ai serve` startup through tenant signup, API key management, config import, workflow execution with WebSocket streaming, and dashboard result viewing.
**Last Updated:** 2026-02-22
**Milestone:** M10 (Multi-Tenant Access Control)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Architecture in Server Mode](#2-system-architecture-in-server-mode)
3. [Phase A: Server Startup](#3-phase-a-server-startup)
   - 3.1 [Entry Point — `temper-ai serve`](#31-entry-point--temper-ai-serve)
   - 3.2 [Database Initialization](#32-database-initialization)
   - 3.3 [FastAPI Application Factory — `create_app()`](#33-fastapi-application-factory--create_app)
   - 3.4 [Middleware Stack Assembly](#34-middleware-stack-assembly)
   - 3.5 [Route Registration](#35-route-registration)
   - 3.6 [Lifespan — Startup and Shutdown](#36-lifespan--startup-and-shutdown)
4. [Phase B: Tenant Onboarding](#4-phase-b-tenant-onboarding)
   - 4.1 [POST /api/auth/signup](#41-post-apiauthsignup)
   - 4.2 [Tenant and User Record Creation](#42-tenant-and-user-record-creation)
   - 4.3 [API Key Generation — HMAC-SHA256](#43-api-key-generation--hmac-sha256)
   - 4.4 [POST /api/auth/api-keys — Additional Keys](#44-post-apiauthapi-keys--additional-keys)
   - 4.5 [GET /api/auth/me — Identity Verification](#45-get-apiauthme--identity-verification)
5. [Phase C: Configuration Management](#5-phase-c-configuration-management)
   - 5.1 [POST /api/configs/import — Config Upload](#51-post-apiconfigsimport--config-upload)
   - 5.2 [ConfigSyncService — Validation and Storage](#52-configsyncservice--validation-and-storage)
   - 5.3 [Config Seeding from Filesystem](#53-config-seeding-from-filesystem)
   - 5.4 [GET /api/configs/{type} — Listing](#54-get-apiconfigstype--listing)
   - 5.5 [GET /api/configs/{type}/{name}/export — Export](#55-get-apiconfigstypenamexport--export)
   - 5.6 [Studio CRUD — /api/studio/*](#56-studio-crud--apistudio)
6. [Phase D: Workflow Execution via API](#6-phase-d-workflow-execution-via-api)
   - 6.1 [Authentication Pipeline — `require_auth` and `require_role`](#61-authentication-pipeline--require_auth-and-require_role)
   - 6.2 [POST /api/runs — Initiating Execution](#62-post-apiruns--initiating-execution)
   - 6.3 [WorkflowExecutionService — Async Dispatch](#63-workflowexecutionservice--async-dispatch)
   - 6.4 [WorkflowRunner — Synchronous Thread Execution](#64-workflowrunner--synchronous-thread-execution)
   - 6.5 [WorkflowRuntime.run_pipeline() — Core Engine](#65-workflowruntimerun_pipeline--core-engine)
   - 6.6 [RunStore — Persistent Status Tracking](#66-runstore--persistent-status-tracking)
   - 6.7 [GET /api/runs/{run_id} — Status Polling](#67-get-apirunsrun_id--status-polling)
7. [Phase D2: WebSocket Streaming](#7-phase-d2-websocket-streaming)
   - 7.1 [Ticket Exchange — POST /api/auth/ws-ticket](#71-ticket-exchange--post-apiauthws-ticket)
   - 7.2 [WebSocket Handshake — /ws/{workflow_id}](#72-websocket-handshake--wsworkflow_id)
   - 7.3 [Initial Snapshot Delivery](#73-initial-snapshot-delivery)
   - 7.4 [Event Subscription and Streaming Loop](#74-event-subscription-and-streaming-loop)
   - 7.5 [LLM Stream Batching — Chunk Buffer](#75-llm-stream-batching--chunk-buffer)
   - 7.6 [DB Polling Loop — Cross-Process Updates](#76-db-polling-loop--cross-process-updates)
   - 7.7 [Heartbeat — 30 Second Keep-Alive](#77-heartbeat--30-second-keep-alive)
   - 7.8 [Frontend WebSocket Hook — `useWorkflowWebSocket`](#78-frontend-websocket-hook--useworkflowwebsocket)
8. [Phase E: Dashboard Result Viewing](#8-phase-e-dashboard-result-viewing)
   - 8.1 [React ExecutionView Component](#81-react-executionview-component)
   - 8.2 [GET /api/workflows — Listing Results](#82-get-apiworkflows--listing-results)
   - 8.3 [GET /api/workflows/{id} — Snapshot Detail](#83-get-apiworkflowsid--snapshot-detail)
   - 8.4 [Stage, Agent, and LLM Call Drill-Down](#84-stage-agent-and-llm-call-drill-down)
   - 8.5 [Tenant Isolation in Read Paths](#85-tenant-isolation-in-read-paths)
9. [Mermaid Diagrams](#9-mermaid-diagrams)
   - 9.1 [Server Startup Flow](#91-server-startup-flow)
   - 9.2 [Tenant Onboarding Sequence](#92-tenant-onboarding-sequence)
   - 9.3 [Authentication Pipeline Flowchart](#93-authentication-pipeline-flowchart)
   - 9.4 [Workflow Execution via API Sequence](#94-workflow-execution-via-api-sequence)
   - 9.5 [WebSocket Lifecycle Sequence](#95-websocket-lifecycle-sequence)
   - 9.6 [Tenant Isolation at Every Layer](#96-tenant-isolation-at-every-layer)
   - 9.7 [Config Management Flow](#97-config-management-flow)
   - 9.8 [Full Server Mode State Machine](#98-full-server-mode-state-machine)
10. [Data Models Reference](#10-data-models-reference)
    - 10.1 [Tenancy Models — `models_tenancy.py`](#101-tenancy-models--models_tenancypy)
    - 10.2 [AuthContext Dataclass](#102-authcontext-dataclass)
    - 10.3 [WorkflowExecutionMetadata](#103-workflowexecutionmetadata)
    - 10.4 [ServerRun DB Model](#104-serverrun-db-model)
    - 10.5 [Config DB Models](#105-config-db-models)
11. [Security Design Decisions](#11-security-design-decisions)
    - 11.1 [API Key Scheme — `tk_` Prefix, HMAC-SHA256](#111-api-key-scheme--tk_-prefix-hmac-sha256)
    - 11.2 [WebSocket Ticket Isolation](#112-websocket-ticket-isolation)
    - 11.3 [Tenant Isolation Strategy](#113-tenant-isolation-strategy)
    - 11.4 [CORS and Security Headers](#114-cors-and-security-headers)
    - 11.5 [Rate Limiting on Public Endpoints](#115-rate-limiting-on-public-endpoints)
    - 11.6 [Path Traversal Prevention](#116-path-traversal-prevention)
12. [Mode Comparison: Dev vs. Server](#12-mode-comparison-dev-vs-server)
13. [Extension Points](#13-extension-points)
14. [Observations and Recommendations](#14-observations-and-recommendations)

---

## 1. Executive Summary

**System Name:** temper-ai Multi-Tenant Server Mode (M10)

**Purpose:** Provides a production-grade HTTP API and React dashboard where multiple isolated organizations (tenants) can sign up, import workflow configurations, execute AI workflows, and monitor results in real time — all with cryptographic API key authentication, role-based access control, and strict per-row tenant isolation at the database query level.

**Technology Stack:**
- Server: FastAPI + uvicorn, Python 3.11+
- Auth: HMAC-SHA256 API keys (`tk_` prefix), short-lived WebSocket tickets (`wst_` prefix)
- Database: SQLModel/SQLAlchemy, PostgreSQL (production), SQLite (development)
- Migrations: Alembic (`mt_001` migration adds 7 new tables)
- Frontend: React 18, TypeScript, ReactFlow, Zustand, TanStack Query
- Real-time: WebSockets with adaptive LLM stream batching (30ms window)
- Worker pool: ThreadPoolExecutor (4 workers by default)

**Scope of Analysis:** All files under `temper_ai/interfaces/`, `temper_ai/auth/`, `temper_ai/storage/database/models_tenancy.py`, `temper_ai/workflow/db_config_loader.py`, `temper_ai/workflow/execution_service.py`, and the key frontend hooks under `frontend/src/`.

**The Two Operating Modes:**

| Flag | Mode Name | `auth_enabled` | Auth | CORS | Studio Backend |
|------|-----------|----------------|------|------|----------------|
| `--dev` | dev | `False` | No auth | localhost only | YAML files on disk |
| (none) | server | `True` | Bearer API key | `TEMPER_CORS_ORIGINS` env | PostgreSQL database |

The `auth_enabled = (mode == "server")` flag is the single toggle that governs every auth dependency injection throughout the application.

---

## 2. System Architecture in Server Mode

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     EXTERNAL CLIENTS (Tenant A, Tenant B, ...)               │
│   Browser (React SPA) │ curl/httpx │ MCP clients │ SDK integrations          │
└──────────────────────┬───────────────────────────────────────────────────────┘
                       │ HTTP / WebSocket (TLS in production)
                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         uvicorn ASGI server                                  │
│                         (host=0.0.0.0, port=8080)                           │
└──────────────────────┬───────────────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    FastAPI Application  (app.py:create_app)                  │
│                                                                              │
│  MIDDLEWARE STACK (outer to inner):                                          │
│  1. _NoCacheStaticMiddleware   → Cache-Control: no-cache on /app/ routes    │
│  2. _SecurityHeadersMiddleware → X-Frame-Options, X-Content-Type-Options,   │
│                                   Referrer-Policy on all HTTP responses      │
│  3. CORSMiddleware             → server mode: TEMPER_CORS_ORIGINS env        │
│                                   dev mode: localhost regex only             │
│                                                                              │
│  ROUTE GROUPS (all under /api unless noted):                                │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  /api/health           → health.py (liveness + readiness probes)       │ │
│  │  /api/auth/*           → auth_routes.py (signup, keys, ws-ticket, me)  │ │
│  │  /api/configs/*        → config_routes.py (import/export/list)         │ │
│  │  /api/runs             → routes.py (execute, list, cancel)             │ │
│  │  /api/workflows        → routes.py + dashboard/routes.py (list+detail) │ │
│  │  /api/stages/{id}      → dashboard/routes.py                           │ │
│  │  /api/agents/{id}      → dashboard/routes.py (+ agent_routes M9)       │ │
│  │  /api/llm-calls/{id}   → dashboard/routes.py                           │ │
│  │  /api/tool-calls/{id}  → dashboard/routes.py                           │ │
│  │  /api/studio/*         → studio_routes.py (config CRUD)                │ │
│  │  /api/learning/*       → learning/dashboard_routes.py (optional)       │ │
│  │  /api/goals/*          → goals/dashboard_routes.py (optional)          │ │
│  │  /api/portfolio/*      → portfolio/dashboard_routes.py (optional)      │ │
│  │  /api/autonomy/*       → safety/autonomy/dashboard_routes.py (opt)     │ │
│  │  /api/experiments/*    → experimentation/dashboard_routes.py (opt)     │ │
│  │  /ws/{workflow_id}     → websocket.py (real-time event stream)         │ │
│  │  /app/*                → React SPA static files (with SPA fallback)    │ │
│  │  /                     → redirect to /app                              │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  APP STATE:                                                                  │
│    app.state.execution_service → WorkflowExecutionService                   │
│    app.state.shutdown_manager  → GracefulShutdownManager                    │
└──────────────────────────────────────────────────────────────────────────────┘
       │                  │                         │
       ▼                  ▼                         ▼
┌────────────┐  ┌───────────────────┐   ┌───────────────────────┐
│Workflow    │  │ DashboardData     │   │ StudioService         │
│Execution  │  │ Service           │   │ (use_db=True in       │
│Service    │  │ (backend + event  │   │  server mode)         │
│(4-worker  │  │  bus wrappers)    │   │                       │
│ ThreadPool│  │                   │   │  DB: WorkflowConfigDB │
│ RunStore) │  │  → SQL backend    │   │      StageConfigDB    │
└─────┬──────┘  │  → EventBus sub  │   │      AgentConfigDB    │
      │         └────────┬──────────┘   └───────────┬───────────┘
      │                  │                          │
      ▼                  ▼                          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PostgreSQL Database                                  │
│                                                                              │
│  TENANCY TABLES (M10)          OBSERVABILITY TABLES                         │
│  ──────────────────────        ─────────────────────────                    │
│  tenants                       workflow_executions                          │
│  users                           └─ stage_executions                        │
│  tenant_memberships                   └─ agent_executions                   │
│  api_keys                                  ├─ llm_calls                     │
│  workflow_configs (JSONB)                  ├─ tool_executions               │
│  stage_configs    (JSONB)                  └─ decision_outcomes             │
│  agent_configs    (JSONB)      server_runs                                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Phase A: Server Startup

### 3.1 Entry Point — `temper-ai serve`

**Location:** `temper_ai/interfaces/cli/main.py`

The `serve` command is the sole entry point for starting the server. It accepts these key options:

| Option | Default | Environment Variable | Purpose |
|--------|---------|---------------------|---------|
| `--host` | `0.0.0.0` | - | Bind address |
| `--port` | `8080` | - | Listen port |
| `--config-root` | `configs` | `TEMPER_CONFIG_ROOT` | YAML config directory |
| `--db` | - | `TEMPER_DATABASE_URL` | Database URL override |
| `--workers` | `4` | `TEMPER_MAX_WORKERS` | Max concurrent workflows |
| `--dev` | `False` | - | Toggle dev vs. server mode |

```python
# temper_ai/interfaces/cli/main.py (serve command)
mode = "dev" if dev else "server"
app = create_app(
    backend=backend,
    event_bus=event_bus,
    mode=mode,
    config_root=config_root,
    max_workers=workers,
)
uvicorn.run(app, host=host, port=port, log_level="info", reload=dev_reload)
```

When `--dev` is NOT passed, `mode = "server"`, which cascades `auth_enabled = True` throughout the entire application.

### 3.2 Database Initialization

Before creating the FastAPI app, the serve command ensures the database schema exists:

```python
# temper_ai/interfaces/cli/main.py (serve command — database init)
db_url = db or get_database_url()
ExecutionTracker.ensure_database(db_url)
```

`ExecutionTracker.ensure_database()` calls `SQLModel.metadata.create_all()` (or Alembic-managed migrations via `ALEMBIC_MANAGED=1`) to create all tables including the M10 tenancy tables: `tenants`, `users`, `tenant_memberships`, `api_keys`, `workflow_configs`, `stage_configs`, `agent_configs`.

The `TEMPER_DATABASE_URL` environment variable controls which database is used. The default is `postgresql://temper:temper@localhost:5432/temper`. SQLite is supported for development but blocked in production unless running inside pytest.

### 3.3 FastAPI Application Factory — `create_app()`

**Location:** `temper_ai/interfaces/dashboard/app.py:358`

`create_app()` is the single factory function that produces the configured FastAPI application. It executes in this sequence:

1. Call `_init_server_components(mode)` — creates `GracefulShutdownManager`, `RunStore`, optional `BackgroundMiningJob`, and optional `BackgroundAnalysisJob`.
2. Instantiate `WorkflowExecutionService` with `backend`, `event_bus`, `config_root`, `max_workers`, and `run_store`.
3. Wire the cross-workflow trigger: if `event_bus` has `set_execution_service`, inject the execution service so event-triggered workflows can be dispatched.
4. Define the `lifespan` async context manager (startup/shutdown hook).
5. Instantiate `FastAPI(title=..., lifespan=lifespan)`.
6. Store `execution_service` and `shutdown_manager` on `app.state`.
7. Call `_configure_cors(app, mode)`.
8. Add `_SecurityHeadersMiddleware`.
9. Compute `auth_enabled = (mode == "server")`.
10. Instantiate `DashboardDataService`.
11. Call `_register_routes(app, ...)`.
12. If `auth_enabled`, call `_register_auth_routes(app)` to add `/api/auth/*` and `/api/configs/*`.

```python
# temper_ai/interfaces/dashboard/app.py:419
auth_enabled = mode == "server"
```

This single boolean is the pivot point. It is passed into every route factory function and determines whether `Depends(require_auth)` or `Depends(require_role(...))` dependencies are attached to route handlers.

### 3.4 Middleware Stack Assembly

Middleware is applied in Python's add-order (innermost first in execution):

```
Incoming request
     │
     ▼
CORSMiddleware
  server mode: explicit origins from TEMPER_CORS_ORIGINS
  dev mode: regex ^https?://(localhost|127\.0\.0\.1)(:\d+)?$
     │
     ▼
_SecurityHeadersMiddleware
  Adds to every HTTP response:
    X-Content-Type-Options: nosniff
    X-Frame-Options: DENY
    Referrer-Policy: strict-origin-when-cross-origin
     │
     ▼
_NoCacheStaticMiddleware (only active when React dist exists)
  Adds Cache-Control: no-cache, must-revalidate to /app/* responses
     │
     ▼
FastAPI route handlers
```

**Location:** `temper_ai/interfaces/dashboard/app.py:60-109`

Note: in server mode, if `TEMPER_CORS_ORIGINS` is unset, no CORSMiddleware is added at all. The browser's default same-origin policy then applies — which blocks cross-origin requests. This is intentional for deployments where the frontend is co-located with the API.

### 3.5 Route Registration

`_register_routes()` calls four sub-functions to organize route attachment:

```python
# temper_ai/interfaces/dashboard/app.py:111-127
def _register_routes(app, execution_service, data_service, config_root, mode, auth_enabled):
    _register_core_routes(app, ...)        # /api/runs, /api/health, /ws/
    _register_data_api_routes(app, ...)    # /api/workflows, /api/stages, etc.
    _register_studio_routes(app, ...)      # /api/studio/*
    _register_dashboard_extras(app, ...)   # learning, goals, portfolio, autonomy
    # (auth routes added separately via _register_auth_routes when auth_enabled)
```

The auth routes (`/api/auth/*` and `/api/configs/*`) are registered **only** when `auth_enabled = True`. This means they are completely absent from the dev mode server, not just unprotected — they do not exist as routes at all.

StudioService is instantiated with `use_db=auth_enabled`:
```python
# temper_ai/interfaces/dashboard/app.py:164
studio_service = StudioService(config_root=config_root, use_db=auth_enabled)
```

This controls whether Studio CRUD operations read/write to the filesystem (dev) or the PostgreSQL database (server).

### 3.6 Lifespan — Startup and Shutdown

The `lifespan` async context manager handles application lifecycle:

```python
# temper_ai/interfaces/dashboard/app.py:394-410
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    if shutdown_mgr is not None:
        shutdown_mgr.register_signals()      # SIGTERM, SIGINT handlers
    if _mining_job is not None:
        await _mining_job.start()            # Background pattern mining
    if _analysis_job is not None:
        await _analysis_job.start()          # Background goal analysis
    yield
    # --- shutdown ---
    if _analysis_job is not None:
        await _analysis_job.stop()
    if _mining_job is not None:
        await _mining_job.stop()
    if shutdown_mgr is not None:
        await shutdown_mgr.drain(execution_service)  # Wait for active runs
    execution_service.shutdown()             # ThreadPoolExecutor.shutdown(wait=True)
```

On shutdown, `GracefulShutdownManager.drain()` stops the readiness gate (causing `/api/health/ready` to return 503) and waits for in-flight workflow executions to complete before allowing the process to exit.

---

## 4. Phase B: Tenant Onboarding

### 4.1 POST /api/auth/signup

**Location:** `temper_ai/interfaces/server/auth_routes.py:156`

This is the one **public** endpoint in server mode — it does not require an API key.

Rate limiting is applied per client IP address using an in-process sliding-window counter:
- Limit: 5 signup requests per 60-second window per IP
- Implementation: `_check_rate_limit(f"signup:{client_ip}", SIGNUP_RATE_LIMIT)`
- On exceeding: `HTTP 429 Too Many Requests`

**Request body:**
```json
{
  "email": "user@example.com",
  "name": "Jane Smith"
}
```

**Response (201):**
```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "tenant_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "api_key": "tk_J9k2mXp4rQsVwYzA8bNcD6"
}
```

The API key in the response is the **only time** the full plaintext key is ever returned. It is not stored anywhere on the server — only its SHA-256 hash is persisted.

### 4.2 Tenant and User Record Creation

The signup handler executes all four operations inside a single database transaction:

**Step 1: Duplicate email check and user creation**

```python
# temper_ai/interfaces/server/auth_routes.py:78-91
def _create_user(session, email, name) -> UserDB:
    existing = session.exec(select(UserDB).where(col(UserDB.email) == email)).first()
    if existing is not None:
        raise HTTPException(400, "A user with that email already exists.")
    user = UserDB(email=email, name=name)
    session.add(user)
    session.flush()   # Assign UUID without committing
    return user
```

**Step 2: Tenant slug derivation and creation**

The tenant slug is derived from the email domain:
```python
# temper_ai/interfaces/server/auth_routes.py:94-102
def _derive_tenant_slug(email) -> str:
    try:
        domain = email.split("@", 1)[1].split(".")[0]
        if domain:
            return domain
    except (IndexError, AttributeError):
        pass
    return f"personal-{str(uuid.uuid4())[:8]}"
```

For `user@acme.com`, the slug becomes `acme`. On collision, a numeric suffix is appended: `acme-2`, `acme-3`, etc.

**Step 3: TenantMembership creation with ROLE_OWNER**

```python
# temper_ai/interfaces/server/auth_routes.py:118-129
membership = TenantMembership(
    tenant_id=tenant.id,
    user_id=user.id,
    role=ROLE_OWNER,    # First user of a tenant is always owner
)
```

**Step 4: Session commit**

```python
# temper_ai/interfaces/server/auth_routes.py:176
session.commit()
```

All four records (UserDB, Tenant, TenantMembership, APIKey) are committed atomically. If any step fails, the entire transaction rolls back.

**Database state after signup:**

| Table | New Row |
|-------|---------|
| `users` | id, email, name, is_active=True |
| `tenants` | id, name=slug, slug, plan="free", max_workflows=100 |
| `tenant_memberships` | id, tenant_id, user_id, role="owner" |
| `api_keys` | id, user_id, tenant_id, label="default", key_prefix, key_hash, is_active=True |

### 4.3 API Key Generation — HMAC-SHA256

**Location:** `temper_ai/auth/api_key_auth.py:55-66`

API key generation uses `secrets.token_urlsafe(24)` to produce 32 cryptographically random URL-safe characters, prepended with the `tk_` prefix:

```python
def generate_api_key() -> tuple[str, str, str]:
    random_part = secrets.token_urlsafe(API_KEY_RANDOM_BYTES)  # 24 bytes → 32 chars
    full_key = f"{API_KEY_TOKEN_PREFIX}{random_part}"           # "tk_<32chars>"
    key_prefix = full_key[:len(API_KEY_TOKEN_PREFIX) + KEY_PREFIX_DISPLAY_LEN]  # "tk_J9k2mXp"
    key_hash = hash_api_key(full_key)
    return full_key, key_prefix, key_hash
```

The hashing function uses HMAC-SHA256 with a server-side pepper:

```python
# temper_ai/auth/api_key_auth.py:43-52
def hash_api_key(raw_key: str) -> str:
    if not _API_KEY_PEPPER:
        # Dev fallback: plain SHA-256
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    return hmac.new(
        _API_KEY_PEPPER.encode("utf-8"),
        raw_key.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
```

The pepper is read from `TEMPER_API_KEY_PEPPER` environment variable. Without it, the system falls back to plain SHA-256 with a logged warning. In production, this pepper prevents offline cracking if the database is compromised.

**Key storage:**
- `key_hash`: 64-character hex SHA-256 digest (used for DB lookup, indexed)
- `key_prefix`: First 11 characters (`tk_` + 8 chars) shown in API key list, for human identification
- Full plaintext key: Never stored, returned once at creation time

### 4.4 POST /api/auth/api-keys — Additional Keys

**Location:** `temper_ai/interfaces/server/auth_routes.py:183`

Authenticated users can create additional API keys with custom labels:

```
POST /api/auth/api-keys
Authorization: Bearer tk_J9k2mXp4rQsVwYzA8bNcD6
Content-Type: application/json

{ "label": "ci-pipeline" }
```

Rate limit: 10 requests per 60-second window per user ID.

The response includes `api_key` (plaintext, shown once), `api_key_id`, `key_prefix`, and `label`.

To revoke a key:
```
DELETE /api/auth/api-keys/{key_id}
Authorization: Bearer tk_...
```

Revocation sets `is_active = False` (soft delete). The key_hash record remains in the database for audit purposes.

### 4.5 GET /api/auth/me — Identity Verification

**Location:** `temper_ai/interfaces/server/auth_routes.py:260`

Returns the current user's identity, tenant context, and RBAC role:

```json
{
  "user": { "id": "...", "email": "user@acme.com", "name": "Jane Smith" },
  "tenant": { "id": "...", "name": "acme", "slug": "acme", "plan": "free" },
  "role": "owner"
}
```

This endpoint is useful for the frontend to display the current tenant context and for clients to verify their API key is working correctly.

---

## 5. Phase C: Configuration Management

### 5.1 POST /api/configs/import — Config Upload

**Location:** `temper_ai/interfaces/server/config_routes.py:58`

**Required Role:** `editor` or `owner`

This endpoint accepts YAML content as a string, validates it, and stores it in the database scoped to the authenticated tenant.

```
POST /api/configs/import
Authorization: Bearer tk_...
Content-Type: application/json

{
  "config_type": "workflow",
  "name": "my-research-workflow",
  "yaml_content": "workflow:\n  name: Research...\n  stages:\n    ..."
}
```

**Validation pipeline:**
1. Check `config_type` is one of `{"workflow", "stage", "agent"}` — raises HTTP 400 if invalid
2. Check `name` is non-empty — raises HTTP 400 if blank
3. Delegate to `ConfigSyncService.import_config()`
4. On `ValueError` (YAML/schema error): raise HTTP 422 Unprocessable Content

**Response:**
```json
{ "name": "my-research-workflow", "config_type": "workflow", "version": 1 }
```

On re-import of an existing name: version increments, `config_data` is overwritten.

### 5.2 ConfigSyncService — Validation and Storage

**Location:** `temper_ai/auth/config_sync.py:71`

`ConfigSyncService.import_config()` is the backend logic for config validation and persistence. It executes in four steps:

**Step 1: Config type validation**
```python
# temper_ai/auth/config_sync.py:87
_validate_config_type(config_type)  # raises ValueError if invalid
```

**Step 2: YAML parsing**
```python
# temper_ai/auth/config_sync.py:88
data = _parse_yaml(yaml_content)
```
Uses `yaml.safe_load()` (never `yaml.load()`). Raises `ValueError` if content is not valid YAML or not a dict.

**Step 3: Pydantic validation**
```python
# temper_ai/auth/config_sync.py:89
_validate_with_pydantic(config_type, data)
```

The YAML is validated against the full Pydantic schema:
- `WorkflowConfig` for `config_type="workflow"`
- `StageConfig` for `config_type="stage"`
- `AgentConfig` for `config_type="agent"`

Any missing required fields, wrong types, or constraint violations raise `ValueError` with a detailed message from Pydantic's validation error.

**Step 4: Upsert to database**
```python
# temper_ai/auth/config_sync.py:91-115
db_model_cls = _CONFIG_TYPE_DB_MODEL[config_type]
with get_session() as session:
    existing = session.query(db_model_cls).filter_by(
        tenant_id=tenant_id, name=name
    ).first()
    if existing is not None:
        existing.config_data = data        # Update JSONB
        existing.version = existing.version + 1
        existing.updated_by = user_id
        existing.updated_at = utcnow()
    else:
        record = db_model_cls(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,           # Scoped to this tenant
            name=name,
            config_data=data,
            created_by=user_id,
            updated_by=user_id,
        )
        session.add(record)
```

All three config DB models (`WorkflowConfigDB`, `StageConfigDB`, `AgentConfigDB`) store `config_data` as a JSON column in PostgreSQL (or JSON in SQLite). The `(tenant_id, name)` pair has a unique constraint, ensuring no collisions within a tenant.

### 5.3 Config Seeding from Filesystem

**Location:** `temper_ai/auth/config_seed.py:58`

For initial deployment or migration of an existing filesystem-based installation, `seed_configs()` bulk-imports all YAML files from a `configs/` directory tree:

```python
# temper_ai/auth/config_seed.py:58-83
def seed_configs(config_root: str, tenant_id: str, user_id: str) -> dict:
    root = Path(config_root)
    sync_service = ConfigSyncService()
    for subdir, config_type in {
        "workflows": "workflow",
        "stages": "stage",
        "agents": "agent",
    }.items():
        directory = root / subdir
        for file_path in sorted(directory.glob("*.yaml")):
            name = file_path.stem
            yaml_content = file_path.read_text(encoding="utf-8")
            sync_service.import_config(
                tenant_id=tenant_id,
                config_type=config_type,
                name=name,
                yaml_content=yaml_content,
                user_id=user_id,
            )
```

This is also invokable via a client-side loop calling `POST /api/configs/import` for each YAML file found in the config directory.

### 5.4 GET /api/configs/{type} — Listing

**Required Role:** `viewer`, `editor`, or `owner`

```
GET /api/configs/workflow
Authorization: Bearer tk_...
```

`ConfigSyncService.list_configs()` queries the appropriate DB model table filtered by `tenant_id`:
```python
records = session.query(db_model_cls).filter_by(tenant_id=tenant_id).all()
```

Response lists name, version, created_at, and updated_at for each config.

### 5.5 GET /api/configs/{type}/{name}/export — Export

**Required Role:** `viewer`, `editor`, or `owner`

`ConfigSyncService.export_config()` queries the DB by `(tenant_id, name)` and serializes `config_data` back to YAML using `yaml.safe_dump()`. Returns `Content-Type: text/yaml`.

### 5.6 Studio CRUD — /api/studio/*

**Location:** `temper_ai/interfaces/dashboard/studio_routes.py`

The Studio routes provide a richer CRUD interface for the visual Workflow Studio editor, with the same tenant-scoped DB backend in server mode.

In server mode (`use_db=True`), all Studio operations call DB-backed service methods:
- `studio_service.list_configs_db(config_type, tenant_id)` — DB query
- `studio_service.get_config_db(config_type, name, tenant_id)` — DB fetch
- `studio_service.create_config_db(config_type, name, data, tenant_id, user_id)` — DB insert
- `studio_service.update_config_db(config_type, name, data, tenant_id, user_id)` — DB update
- `studio_service.delete_config_db(config_type, name, tenant_id)` — DB delete

RBAC for Studio routes in server mode:
- GET: `require_auth` (viewer+)
- POST/PUT: `require_role("owner", "editor")`
- DELETE: `require_role("owner")`
- Schema GET: always public (no auth)

---

## 6. Phase D: Workflow Execution via API

### 6.1 Authentication Pipeline — `require_auth` and `require_role`

**Location:** `temper_ai/auth/api_key_auth.py:127-200`

Every protected endpoint in server mode uses FastAPI's dependency injection. The two available dependencies are:

**`require_auth`:** Validates any valid API key, returns `AuthContext`.

**`require_role(*allowed_roles)`:** Factory that returns a dependency which first calls `require_auth`, then checks the role.

The authentication flow for every protected request:

```
Request arrives with Authorization: Bearer tk_J9k2mXp...
         │
         ▼
_extract_bearer_token(request)
  → checks "Authorization" header starts with "Bearer "
  → strips prefix, returns token string
         │
         ▼
token.startswith("tk_")?
  No  → HTTP 401 "Invalid API key format"
  Yes → continue
         │
         ▼
key_hash = hash_api_key(token)
  → HMAC-SHA256 with TEMPER_API_KEY_PEPPER (or plain SHA-256)
         │
         ▼
_lookup_api_key(key_hash)
  → SELECT api_keys.id, user_id, tenant_id, is_active, expires_at,
           tenant_memberships.role
     JOIN tenant_memberships ON user_id + tenant_id match
     WHERE key_hash = ?
  → Also updates last_used_at and total_requests (fire-and-forget)
         │
         ▼
result is None?
  Yes → HTTP 401 "Invalid API key"
  No  → continue
         │
         ▼
is_active = False?
  Yes → HTTP 401 "API key has been revoked"
  No  → continue
         │
         ▼
expires_at not None and now > expires_at?
  Yes → HTTP 401 "API key has expired"
  No  → continue
         │
         ▼
return AuthContext(user_id, tenant_id, role, api_key_id)
```

**`AuthContext` dataclass** (frozen, immutable):
```python
@dataclass(frozen=True)
class AuthContext:
    user_id: str     # UUID of the authenticated user
    tenant_id: str   # UUID of the user's tenant (for all DB scoping)
    role: str        # "owner" | "editor" | "viewer"
    api_key_id: str  # UUID of the API key used (for audit logs)
```

The `AuthContext` is injected into route handler parameters. It is the single carrier of tenant identity through the entire request lifecycle.

For `require_role`, the additional check is:
```python
if ctx.role not in allowed:
    raise HTTPException(403, f"Insufficient permissions. Required: {sorted(allowed)}, got: {ctx.role}")
```

### 6.2 POST /api/runs — Initiating Execution

**Location:** `temper_ai/interfaces/server/routes.py:73`

**Required Role:** `editor` or `owner`

```
POST /api/runs
Authorization: Bearer tk_...
Content-Type: application/json

{
  "workflow": "workflows/research.yaml",
  "inputs": { "topic": "AI safety" },
  "run_id": "optional-custom-id"
}
```

When `auth_enabled = True`, the route handler receives `ctx: AuthContext`:

```python
# temper_ai/interfaces/server/routes.py:243-249
@router.post("/runs", response_model=RunResponse)
async def create_run(
    body: RunRequest = Body(...),
    ctx: AuthContext = Depends(require_role("owner", "editor")),
) -> RunResponse:
    return await _handle_create_run(
        execution_service, body, config_root, tenant_id=ctx.tenant_id
    )
```

**Path traversal prevention:**
```python
# temper_ai/interfaces/server/routes.py:81-86
config_root_resolved = Path(config_root).resolve()
workflow_file = (config_root_resolved / body.workflow).resolve()
try:
    workflow_file.relative_to(config_root_resolved)
except ValueError:
    raise HTTPException(400, "Invalid workflow path")
```

This check prevents `../../etc/passwd`-style path traversal attacks.

**Response (200):**
```json
{
  "execution_id": "exec-a1b2c3d4e5f6",
  "status": "pending",
  "message": "Workflow execution started"
}
```

The execution ID is returned immediately — the workflow runs asynchronously in the background. Clients use this ID to poll status or connect via WebSocket.

### 6.3 WorkflowExecutionService — Async Dispatch

**Location:** `temper_ai/workflow/execution_service.py:146`

`execute_workflow_async()` performs:

**Step 1: Prepare execution** via `_prepare_execution()`:
- Generate `execution_id` (`exec-{uuid4().hex[:12]}` or `exec-{run_id}` if provided)
- Call `WorkflowRuntime.load_config()` to validate workflow YAML exists and is valid
- Create `WorkflowExecutionMetadata(status=PENDING)`
- Acquire `self._lock`, store in `self._executions[execution_id]`
- If `run_store` is present, persist a `ServerRun` record with `status="pending"` and `tenant_id`

**Step 2: Schedule background execution** via `asyncio.create_task()`:
```python
asyncio.create_task(
    self._run_workflow_background(execution_id, str(workflow_file), input_data, workspace)
)
```

**Step 3: Return immediately** with `execution_id`.

The `_run_workflow_background()` coroutine then:
1. Updates metadata to `status=RUNNING`, updates `RunStore`
2. Calls `loop.run_in_executor(self._executor, self._execute_workflow_in_runner, ...)` to offload blocking work to the ThreadPoolExecutor
3. On completion: calls `_record_success()` or `_record_failure()`, updating both in-memory metadata and `RunStore`

**Concurrency model:**

```
FastAPI async event loop (main thread)
         │
         │  asyncio.create_task()
         ▼
_run_workflow_background() coroutine
         │
         │  loop.run_in_executor(self._executor, ...)
         ▼
ThreadPoolExecutor worker thread
  → WorkflowRunner.run()
  → WorkflowRuntime.run_pipeline()
  → LangGraph execution (blocking)
```

The ThreadPoolExecutor has `max_workers=4` by default, meaning up to 4 workflows can execute concurrently. Additional requests are queued.

### 6.4 WorkflowRunner — Synchronous Thread Execution

**Location:** `temper_ai/interfaces/server/workflow_runner.py:65`

`WorkflowRunner.run()` is the synchronous execution wrapper that:

1. Records `started_at = datetime.now(UTC)`
2. Subscribes to `event_bus` if an `on_event` callback is provided
3. Calls `_run_core()` which instantiates `WorkflowRuntime` with `RuntimeConfig(config_root, trigger_type="api", environment="server", initialize_database=False, event_bus=...)`
4. Calls `rt.run_pipeline(workflow_path, input_data, workspace, run_id, show_details=False)`
5. Records `completed_at`
6. Returns `WorkflowRunResult(workflow_id, workflow_name, status, result, started_at, completed_at, duration_seconds)`

On success, `run_result.workflow_id` is stored back into `WorkflowExecutionMetadata.workflow_id` — this ID is the LangGraph execution's observable ID used by the dashboard and WebSocket.

The `_sanitize_result()` call strips non-serializable infrastructure objects from the result dict (ExecutionTracker, ConfigLoader, ToolRegistry, Rich Console) before storing in `RunStore`.

### 6.5 WorkflowRuntime.run_pipeline() — Core Engine

**Location:** `temper_ai/workflow/runtime.py`

`run_pipeline()` is the shared entry point for workflow execution. The server-mode execution follows this pipeline:

```
run_pipeline(workflow_path, input_data, workspace, run_id)
    │
    ├── 1. load_config()
    │       → YAML parse + Pydantic validation (WorkflowConfig)
    │
    ├── 2. adapt_lifecycle()
    │       → Optional: inject/remove stages based on lifecycle profile
    │
    ├── 3. on_config_loaded() hook
    │       → Planning pass if enabled
    │       → Experiment variant selection if enabled
    │
    ├── 4. setup_infrastructure()
    │       → ConfigLoader (filesystem OR DBConfigLoader if tenant_id present)
    │       → ToolRegistry (auto-discover or explicit)
    │       → ExecutionTracker (writes to DB)
    │
    ├── 5. compile()
    │       → EngineRegistry → LangGraphExecutionEngine.compile()
    │       → LangGraph StateGraph built, compiled to runnable
    │
    ├── 6. build_state()
    │       → Assemble initial state dict with inputs, workflow_id, metadata
    │
    ├── 7. on_state_built() hook
    │       → Server: no-op (WebSocket handles streaming)
    │
    ├── 8. execute()
    │       → compiled.invoke(state)
    │       → Stage executors → Agent execution → LLM calls
    │       → ObservabilityTracker emits events to EventBus
    │
    ├── 9. on_after_execute() hook
    │       → Autonomous loop (if autonomous: true in request)
    │
    └── 10. cleanup()
            → ToolExecutor shutdown
```

In server mode, when a `tenant_id` is passed through `execute_workflow_async()`, a `DBConfigLoader` is used instead of the filesystem `ConfigLoader`:

```python
# temper_ai/workflow/db_config_loader.py:57-101
class DBConfigLoader:
    def __init__(self, tenant_id: str) -> None:
        self._tenant_id = tenant_id

    def load_workflow(self, name: str) -> dict[str, Any]:
        return _load_config(self._tenant_id, WorkflowConfigDB, name)

    def load_stage(self, name: str, validate: bool = True) -> dict[str, Any]:
        return _load_config(self._tenant_id, StageConfigDB, name)

    def load_agent(self, name: str, validate: bool = True) -> dict[str, Any]:
        return _load_config(self._tenant_id, AgentConfigDB, name)
```

Every config load call becomes a SQL query with `WHERE tenant_id = ? AND name = ?`, ensuring complete config isolation between tenants.

### 6.6 RunStore — Persistent Status Tracking

**Location:** `temper_ai/interfaces/server/run_store.py`

`RunStore` persists all run lifecycle transitions to the `server_runs` table. Status transitions:

```
PENDING → RUNNING → COMPLETED
                 → FAILED
         → CANCELLED (by user request)
```

Persistence calls:
1. `run_store.save_run(ServerRun(..., status="pending"))` — at submission time
2. `run_store.update_status(execution_id, "running", started_at=...)` — when execution begins
3. `run_store.update_status(execution_id, "completed", completed_at=..., workflow_id=..., result_summary=...)` — on success
4. `run_store.update_status(execution_id, "failed", completed_at=..., error_message=...)` — on failure

The `RunStore` uses the same database as the main application (`TEMPER_DATABASE_URL`), sharing a connection pool. Run history survives server restarts.

Status lookups try in-memory cache first (`self._executions`), then fall back to `RunStore`. This means the most recent runs respond quickly without a DB query.

### 6.7 GET /api/runs/{run_id} — Status Polling

**Required Role:** `viewer`, `editor`, or `owner` (requires auth, any role)

```
GET /api/runs/exec-a1b2c3d4e5f6
Authorization: Bearer tk_...
```

Response:
```json
{
  "execution_id": "exec-a1b2c3d4e5f6",
  "workflow_id": "wf-<uuid>",
  "workflow_path": "workflows/research.yaml",
  "workflow_name": "Research Workflow",
  "status": "running",
  "started_at": "2026-02-22T10:15:30.123456+00:00",
  "completed_at": null,
  "error_message": null,
  "result": null
}
```

Once `status = "completed"`, `workflow_id` is populated. This ID is used to connect to the WebSocket endpoint `/ws/{workflow_id}` for real-time event streaming.

---

## 7. Phase D2: WebSocket Streaming

### 7.1 Ticket Exchange — POST /api/auth/ws-ticket

**Location:** `temper_ai/interfaces/server/auth_routes.py:251`

In server mode, the React frontend cannot pass API keys in WebSocket query strings (they would appear in server logs and browser history). Instead, a two-step ticket exchange is used:

**Step 1:** Client exchanges API key for a short-lived ticket:
```
POST /api/auth/ws-ticket
Authorization: Bearer tk_...
```

**Step 2:** Server generates a `wst_` prefixed ticket:
```python
# temper_ai/auth/ws_tickets.py:28-34
def generate_ws_ticket(ctx: AuthContext) -> str:
    ticket_id = f"{TICKET_PREFIX}{secrets.token_urlsafe(TICKET_RANDOM_BYTES)}"
    entry = _TicketEntry(ctx=ctx, expires_at=time.monotonic() + TICKET_TTL_SECONDS)
    with _lock:
        _store[ticket_id] = entry
    return ticket_id
```

**Ticket properties:**
- Prefix: `wst_`
- TTL: 30 seconds (`TICKET_TTL_SECONDS = 30`)
- Single-use: `_store.pop(ticket, None)` consumes the ticket on first use
- In-memory: stored in a process-local dict with threading lock
- Cleanup: `cleanup_expired()` removes stale entries (called by a background task)

**Response:**
```json
{ "ticket": "wst_Kj2mXp4rQsVwYzA8bNcD6eF7hI9jK1" }
```

### 7.2 WebSocket Handshake — /ws/{workflow_id}

**Location:** `temper_ai/interfaces/dashboard/websocket.py:189`

The WebSocket handler is created by `create_ws_endpoint(data_service, auth_enabled)`. In server mode:

```python
# temper_ai/interfaces/dashboard/websocket.py:196-219
if auth_enabled:
    ticket = websocket.query_params.get("ticket")
    token = websocket.query_params.get("token")  # Deprecated: direct API key
    if ticket:
        ctx = validate_ws_ticket(ticket)     # Consumes ticket (one-time use)
        if ctx is None:
            await websocket.close(code=4001, reason="Invalid or expired ticket")
            return
    elif token:
        # Deprecated path: direct API key in query string
        ctx = await authenticate_ws_token(token)
        if ctx is None:
            await websocket.close(code=4001, reason="Invalid auth token")
            return
    else:
        await websocket.close(code=4001, reason="Missing auth ticket")
        return
```

`validate_ws_ticket()` atomically pops the ticket from the in-memory store and checks expiry. Concurrent WebSocket upgrade attempts with the same ticket cause all but the first to fail.

WebSocket URL structure:
```
ws://host/ws/{workflow_id}?ticket=wst_Kj2mXp...
```

After successful ticket validation, `await websocket.accept()` completes the WebSocket handshake.

### 7.3 Initial Snapshot Delivery

Immediately after accepting the connection, the handler fetches the current state of the workflow from the database:

```python
# temper_ai/interfaces/dashboard/websocket.py:239-245
snapshot = await asyncio.to_thread(
    data_service.get_workflow_snapshot, workflow_id,
)
if snapshot:
    await websocket.send_json({"type": "snapshot", "workflow": snapshot})
    initial_fp = _workflow_fingerprint(snapshot)
```

The `asyncio.to_thread()` call is critical: the DB query is blocking (especially for PostgreSQL over network), so it must not block the async event loop. The snapshot contains the full workflow state including all stages, agents, their statuses, timing, and LLM call counts.

The `_workflow_fingerprint()` function creates a pipe-delimited string of all status fields:
```python
parts = [snapshot.get("status", ""), snapshot.get("end_time", "")]
for stage in snapshot.get("stages", []):
    parts.append(stage.get("status", ""))
    for agent in stage.get("agents", []):
        parts.append(agent.get("status", ""))
return "|".join(str(p) for p in parts)
```

This fingerprint is used by the DB polling loop to detect state changes without sending duplicate snapshots.

### 7.4 Event Subscription and Streaming Loop

After delivering the initial snapshot:

**Subscription to EventBus:**
```python
# temper_ai/interfaces/dashboard/websocket.py:248-249
subscription_id = data_service.subscribe_workflow(workflow_id, on_event)
```

The `on_event` callback is called from the workflow execution thread (not the async event loop) for each `ObservabilityEvent` emitted during execution. Thread-safe dispatch is handled by:
- For streaming chunks: `loop.call_soon_threadsafe(chunk_buffer.append, event_dict)`
- For other events: `event_queue.put_nowait(event_dict)` (asyncio.Queue is thread-safe for put_nowait)

**Event format delivered to client:**
```json
{
  "type": "event",
  "event_type": "agent_started",
  "timestamp": "2026-02-22T10:15:31.456789+00:00",
  "data": { "agent_id": "...", "agent_name": "researcher", ... },
  "workflow_id": "wf-<uuid>",
  "stage_id": "stage-research",
  "agent_id": "agent-<uuid>"
}
```

**Three concurrent background tasks run in the WebSocket handler:**

1. `_flush_chunks_task()` — LLM stream chunk batcher (30ms poll)
2. `_db_poll_loop()` — DB state change detector (2s poll)
3. `_stream_events_loop()` — Main event queue drainer (with 30s heartbeat)

The main coroutine runs `_stream_events_loop()` while `flush_task` and `poll_task` run as separate `asyncio.Task` objects.

### 7.5 LLM Stream Batching — Chunk Buffer

**Location:** `temper_ai/interfaces/dashboard/websocket.py:65`

LLM streaming events (`llm_stream_chunk` and `stream_token`) are handled specially to avoid overwhelming the WebSocket with individual token deliveries:

```python
# temper_ai/interfaces/dashboard/websocket.py:53-55
if event.event_type in ("llm_stream_chunk", "stream_token"):
    loop.call_soon_threadsafe(chunk_buffer.append, event_dict)
    return
```

The `_flush_chunks_task` batches these:
```
Every 30ms (CHUNK_IDLE_TIMEOUT_SECONDS):
  If buffer < CHUNK_BATCH_SIZE (10): wait another 30ms
  Else: flush immediately (up to 10 items)
  Send: { "type": "event", "event_type": "llm_stream_batch",
          "data": { "chunks": [...] } }
```

This adaptive batching strategy reduces WebSocket messages from potentially thousands per second (one per token) to ~33 messages/second maximum, while keeping first-token latency to 30-60ms.

### 7.6 DB Polling Loop — Cross-Process Updates

**Location:** `temper_ai/interfaces/dashboard/websocket.py:149`

The `_db_poll_loop()` runs every 2 seconds (`DB_POLL_INTERVAL_SECONDS = 2.0`), querying the database for workflow state changes. This enables:
- Viewing workflow state for runs started by other processes or API clients
- Recovering the UI state after a browser refresh
- Detecting terminal states when event bus events may have been missed

```python
async def _db_poll_loop(websocket, data_service, workflow_id, initial_fingerprint):
    while True:
        await asyncio.sleep(DB_POLL_INTERVAL_SECONDS)
        snapshot = await asyncio.to_thread(
            data_service.get_workflow_snapshot, workflow_id,
        )
        if snapshot:
            fp = _workflow_fingerprint(snapshot)
            if fp != last_fingerprint:
                last_fingerprint = fp
                await websocket.send_json({"type": "snapshot", "workflow": snapshot})
                if snapshot.get("status") in TERMINAL_STATUSES:
                    break  # Stop polling after terminal state
```

Terminal statuses that stop the poll loop: `{"completed", "failed", "halted", "timeout"}`.

### 7.7 Heartbeat — 30 Second Keep-Alive

The `_stream_events_loop()` uses `asyncio.wait_for(event_queue.get(), timeout=30.0)`. On timeout (no events for 30 seconds), it sends a heartbeat:

```json
{
  "type": "heartbeat",
  "timestamp": "2026-02-22T10:16:00.000000+00:00"
}
```

This prevents intermediate proxies and load balancers from closing idle WebSocket connections.

**Cleanup on disconnect:**
```python
# temper_ai/interfaces/dashboard/websocket.py:270-278
finally:
    for task in (flush_task, poll_task):
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    if subscription_id:
        data_service.unsubscribe(subscription_id)
```

All background tasks are cancelled and the event bus subscription is removed, preventing memory leaks and zombie event callbacks.

### 7.8 Frontend WebSocket Hook — `useWorkflowWebSocket`

**Location:** `frontend/src/hooks/useWorkflowWebSocket.ts`

The React hook manages the WebSocket connection lifecycle with exponential backoff reconnection:

```typescript
// frontend/src/hooks/useWorkflowWebSocket.ts:16-27
async function fetchWsTicket(): Promise<string | null> {
  const apiKey = getApiKey();
  if (!apiKey) return null;
  const res = await authFetch('/api/auth/ws-ticket', { method: 'POST' });
  if (!res.ok) return null;
  const data = await res.json();
  return data.ticket ?? null;
}
```

Connection flow:
1. `fetchWsTicket()` — POST to `/api/auth/ws-ticket` with Bearer auth
2. Construct WS URL: `ws://host/ws/{workflowId}?ticket=wst_...`
3. Connect with `new WebSocket(url)`
4. On message: dispatch to Zustand store via `applySnapshot()` or `applyEvent()`
5. On close: schedule reconnect with exponential backoff (initial: `WS_INITIAL_DELAY_MS`, max: `WS_MAX_DELAY_MS`, multiplier: `WS_BACKOFF_MULTIPLIER`)
6. On unmount: cancel reconnect timer, null out `onclose`, call `ws.close()`

The hook nulls out `ws.onclose` before calling `ws.close()` to prevent zombie reconnect loops after component unmount.

In dev mode (no API key configured), `getApiKey()` returns null, `fetchWsTicket()` returns null, and the WebSocket connects without a ticket parameter — the server accepts unauthenticated WebSocket connections in dev mode.

---

## 8. Phase E: Dashboard Result Viewing

### 8.1 React ExecutionView Component

**Location:** `frontend/src/pages/ExecutionView.tsx`

The `ExecutionView` page is rendered when the user navigates to `/app/executions/{workflowId}`. It mounts three hooks:

1. `useWorkflowWebSocket(workflowId)` — establishes WebSocket connection
2. `useInitialData(workflowId)` — fetches initial HTTP data (stages, LLM calls)
3. `useKeyboardShortcuts(...)` — keyboard navigation between tabs

The component renders four views selectable by tabs (or keyboard shortcuts 1-4):
- **DAG** (key `1`): `ExecutionDAG` + `LiveStreamBar` — ReactFlow graph with real-time updates
- **Timeline** (key `2`): `TimelineChart` — Gantt-style stage execution timeline
- **Event Log** (key `3`): `EventLogPanel` — filterable list of observability events
- **LLM Calls** (key `4`): `LLMCallsTable` — table of all LLM invocations with tokens/cost

**State management:** All workflow execution state is stored in the Zustand `executionStore`. WebSocket messages are dispatched via `applySnapshot()` (full state replacement) and `applyEvent()` (incremental update). The DAG re-renders reactively as state changes.

**Status notifications:**
```typescript
useEffect(() => {
  if (prevStatus.current === 'running' && workflow?.status === 'completed') {
    toast.success('Workflow completed successfully');
  } else if (prevStatus.current === 'running' && workflow?.status === 'failed') {
    toast.error('Workflow failed');
  }
}, [workflow?.status]);
```

### 8.2 GET /api/workflows — Listing Results

**Location:** `temper_ai/interfaces/dashboard/routes.py:87`

In server mode, `list_workflows` receives `ctx: AuthContext` and passes `tenant_id=ctx.tenant_id` to `DashboardDataService.list_workflows()`:

```python
# temper_ai/interfaces/dashboard/routes.py:94-100
@router.get("/workflows")
def list_workflows(
    limit: int = Query(DEFAULT_PAGE_LIMIT, ...),
    offset: int = Query(0, ...),
    status: str | None = Query(None),
    ctx: AuthContext = Depends(require_auth),
) -> Any:
    return _handle_list_workflows(data_service, limit, offset, status, tenant_id=ctx.tenant_id)
```

`DashboardDataService` forwards `tenant_id` to the `SQLObservabilityBackend`, which applies it as a `WHERE tenant_id = ?` filter on the `workflow_executions` table.

### 8.3 GET /api/workflows/{id} — Snapshot Detail

`get_workflow_snapshot(workflow_id, tenant_id)` in `DashboardDataService`:

```python
# temper_ai/interfaces/dashboard/data_service.py:30-41
def get_workflow_snapshot(self, workflow_id, tenant_id=None):
    result = self._backend.get_workflow(workflow_id)
    if result is None:
        return None
    if tenant_id is not None and result.get("tenant_id") != tenant_id:
        return None    # Tenant mismatch: return None (frontend sees 404)
    return result
```

The tenant check happens at the service layer, **after** the DB query. Even if tenant isolation at the query level is somehow bypassed, this explicit check ensures cross-tenant data is never returned. This is defense-in-depth.

The snapshot includes:
- Workflow metadata: name, status, start/end time, duration, cost, token counts
- Stages array: each with status, timing, and agents array
- Per-agent: status, model, token counts, tool calls

### 8.4 Stage, Agent, and LLM Call Drill-Down

The frontend allows drilling into progressively more detailed views:

**Stage detail** — `GET /api/stages/{stage_id}`:
```python
result = data_service.get_stage(stage_id, tenant_id=ctx.tenant_id)
```

**Agent detail** — `GET /api/agents/{agent_id}`:
```python
result = data_service.get_agent(agent_id, tenant_id=ctx.tenant_id)
```

**LLM call detail** — `GET /api/llm-calls/{llm_call_id}`:
```python
result = data_service.get_llm_call(llm_call_id, tenant_id=ctx.tenant_id)
```

Each service method applies the same pattern: query backend, then check `result.get("tenant_id") != tenant_id` to enforce isolation.

**Events for a specific run** — `GET /api/runs/{run_id}/events`:
Uses `SQLObservabilityBackend.get_run_events(workflow_id, limit, offset)` to retrieve the event log.

### 8.5 Tenant Isolation in Read Paths

Tenant isolation is enforced at two independent levels in the read path:

**Level 1: Database query filter** (primary defense)
```sql
SELECT * FROM workflow_executions WHERE tenant_id = '<tenant_uuid>'
```

**Level 2: Service-layer validation** (defense-in-depth)
```python
if tenant_id is not None and result.get("tenant_id") != tenant_id:
    return None
```

If a tenant ID is present in the `AuthContext`, it is forwarded through every layer down to the SQL query. No workflow data from another tenant can be returned.

---

## 9. Mermaid Diagrams

### 9.1 Server Startup Flow

```mermaid
flowchart TD
    SERVE["temper-ai serve\n(--dev flag absent → server mode)"]
    DB["ExecutionTracker.ensure_database(db_url)\n(Create all tables via SQLModel or Alembic)"]
    BACKEND["SQLObservabilityBackend(buffer=False)"]
    EVENTBUS["TemperEventBus(ObservabilityEventBus(), persist=False)"]
    CREATE["create_app(backend, event_bus, mode='server', config_root, max_workers)"]

    subgraph INIT["_init_server_components('server')"]
        SDM["GracefulShutdownManager"]
        RS["RunStore(database_url)"]
        MJ["BackgroundMiningJob (optional)"]
        AJ["BackgroundAnalysisJob (optional)"]
    end

    subgraph APP_FACTORY["FastAPI App Factory"]
        ES["WorkflowExecutionService\n(backend, event_bus, config_root, max_workers=4, run_store)"]
        AUTH_FLAG["auth_enabled = (mode == 'server') → True"]
        DS["DashboardDataService(backend, event_bus)"]
        SS["StudioService(config_root, use_db=True)"]
    end

    subgraph MIDDLEWARE["Middleware Stack (outer → inner)"]
        M1["_NoCacheStaticMiddleware"]
        M2["_SecurityHeadersMiddleware"]
        M3["CORSMiddleware(origins=TEMPER_CORS_ORIGINS)"]
    end

    subgraph ROUTES["Route Registration"]
        R1["Server Router (runs, health, validate)"]
        R2["Data Router (workflows, stages, agents, llm-calls)"]
        R3["Studio Router (/api/studio/*)"]
        R4["Auth Router (/api/auth/*)  ← server mode only"]
        R5["Config Router (/api/configs/*)  ← server mode only"]
        WS["/ws/{workflow_id} WebSocket"]
        SPA["/app/* React SPA"]
    end

    LIFESPAN["lifespan: register SIGTERM, start background jobs\n(shutdown: drain active runs, stop workers)"]

    SERVE --> DB --> BACKEND --> EVENTBUS --> CREATE
    CREATE --> INIT
    CREATE --> APP_FACTORY
    APP_FACTORY --> MIDDLEWARE
    APP_FACTORY --> ROUTES
    APP_FACTORY --> LIFESPAN
    INIT --> ES
    AUTH_FLAG --> R4
    AUTH_FLAG --> R5
```

### 9.2 Tenant Onboarding Sequence

```mermaid
sequenceDiagram
    participant Client as Client (curl / browser)
    participant RL as Rate Limiter
    participant AR as auth_routes.py
    participant DB as PostgreSQL

    Client->>AR: POST /api/auth/signup\n{ email, name }
    AR->>RL: _check_rate_limit("signup:<ip>", 5)
    alt Rate limit exceeded
        RL-->>AR: False
        AR-->>Client: 429 Too Many Requests
    else Under limit
        RL-->>AR: True
    end

    AR->>AR: _derive_tenant_slug(email)\ne.g. "user@acme.com" → "acme"

    AR->>DB: BEGIN TRANSACTION
    AR->>DB: SELECT FROM users WHERE email = ?
    alt Email already exists
        DB-->>AR: existing user
        AR-->>Client: 400 "A user with that email already exists"
    else New email
        DB-->>AR: None
    end

    AR->>DB: INSERT INTO users (id, email, name)
    DB-->>AR: user.id = uuid-A

    AR->>DB: SELECT FROM tenants WHERE slug = "acme"
    alt Slug collision
        DB-->>AR: existing tenant
        AR->>DB: SELECT FROM tenants WHERE slug = "acme-2"
    end
    AR->>DB: INSERT INTO tenants (id, name="acme", slug="acme")
    DB-->>AR: tenant.id = uuid-B

    AR->>DB: INSERT INTO tenant_memberships\n(tenant_id=uuid-B, user_id=uuid-A, role="owner")
    DB-->>AR: membership.id = uuid-C

    AR->>AR: generate_api_key()\n→ secrets.token_urlsafe(24)\n→ "tk_<32chars>"\n→ hash_api_key(full_key) → SHA-256 hex

    AR->>DB: INSERT INTO api_keys\n(user_id=uuid-A, tenant_id=uuid-B,\n key_prefix="tk_J9k2mXp", key_hash=sha256,\n label="default")
    DB-->>AR: api_key.id = uuid-D

    AR->>DB: COMMIT
    AR-->>Client: 200 { user_id, tenant_id, api_key: "tk_J9k2mXp..." }

    Note over Client: API key shown ONCE — not stored on server
```

### 9.3 Authentication Pipeline Flowchart

```mermaid
flowchart TD
    REQ["Incoming Request\n(any protected route)"]
    HDR{"Authorization header\nstarts with 'Bearer '?"}
    FORMAT{"token.startswith('tk_')?"}
    HASH["key_hash = hash_api_key(token)\nHMAC-SHA256 with TEMPER_API_KEY_PEPPER\n(fallback: plain SHA-256)"]
    LOOKUP["_lookup_api_key(key_hash)\nSELECT api_keys JOIN tenant_memberships\nWHERE key_hash = ?\n→ Update last_used_at, total_requests"]
    FOUND{"Row found?"}
    ACTIVE{"is_active = True?"}
    EXPIRY{"expires_at not None\nAND now > expires_at?"}
    CTX["AuthContext(user_id, tenant_id, role, api_key_id)"]
    RBAC{"require_role check\n(if applicable)"}
    HANDLER["Route handler executes\nwith AuthContext injected"]

    E401A["HTTP 401\nMissing/invalid Authorization header"]
    E401B["HTTP 401\nInvalid API key format (not tk_)"]
    E401C["HTTP 401\nInvalid API key (hash not found)"]
    E401D["HTTP 401\nAPI key has been revoked"]
    E401E["HTTP 401\nAPI key has expired"]
    E403["HTTP 403\nInsufficient permissions"]

    REQ --> HDR
    HDR -- No --> E401A
    HDR -- Yes --> FORMAT
    FORMAT -- No --> E401B
    FORMAT -- Yes --> HASH
    HASH --> LOOKUP
    LOOKUP --> FOUND
    FOUND -- No --> E401C
    FOUND -- Yes --> ACTIVE
    ACTIVE -- No (revoked) --> E401D
    ACTIVE -- Yes --> EXPIRY
    EXPIRY -- Yes (expired) --> E401E
    EXPIRY -- No --> CTX
    CTX --> RBAC
    RBAC -- Role not in allowed set --> E403
    RBAC -- Role allowed (or no role check) --> HANDLER
```

### 9.4 Workflow Execution via API Sequence

```mermaid
sequenceDiagram
    participant C as Client
    participant Routes as routes.py
    participant Auth as require_role("owner","editor")
    participant ES as WorkflowExecutionService
    participant RS as RunStore (PostgreSQL)
    participant TPE as ThreadPoolExecutor
    participant WR as WorkflowRunner
    participant RT as WorkflowRuntime
    participant EB as EventBus

    C->>Routes: POST /api/runs\nAuthorization: Bearer tk_...\n{ workflow, inputs }
    Routes->>Auth: Depends(require_role("owner","editor"))
    Auth->>Auth: hash_api_key(token) → DB lookup → AuthContext
    Auth-->>Routes: AuthContext{tenant_id, role="editor"}

    Routes->>Routes: Path traversal check\n(workflow relative to config_root)
    Routes->>ES: execute_workflow_async(workflow_path, input_data,\n tenant_id=ctx.tenant_id)

    ES->>ES: _prepare_execution()\n→ validate workflow YAML exists\n→ create execution_id="exec-<12hex>"\n→ store WorkflowExecutionMetadata(status=PENDING)
    ES->>RS: save_run(ServerRun(execution_id, status="pending", tenant_id))
    RS-->>ES: saved

    ES->>ES: asyncio.create_task(_run_workflow_background(...))
    ES-->>Routes: execution_id = "exec-a1b2c3d4e5f6"
    Routes-->>C: 200 { execution_id, status: "pending" }

    Note over ES: Background task runs asynchronously

    ES->>ES: Update metadata: status=RUNNING, started_at
    ES->>RS: update_status(execution_id, "running", started_at)

    ES->>TPE: loop.run_in_executor(executor,\n _execute_workflow_in_runner, ...)
    TPE->>WR: WorkflowRunner.run(workflow_path, input_data)
    WR->>RT: WorkflowRuntime.run_pipeline(...)
    RT->>RT: load_config() → DBConfigLoader(tenant_id).load_workflow(name)
    RT->>RT: compile() → LangGraph StateGraph
    RT->>RT: execute() → stage_executors → agents → LLM calls
    RT-->>EB: emit ObservabilityEvents (agent_started, llm_call, etc.)
    RT-->>WR: result_data
    WR-->>TPE: WorkflowRunResult(workflow_id, status="completed")
    TPE-->>ES: result dict

    ES->>ES: _record_success(execution_id, result)\n→ metadata.status=COMPLETED\n→ metadata.workflow_id=<wf-uuid>
    ES->>RS: update_status(execution_id, "completed",\n workflow_id, result_summary)

    C->>Routes: GET /api/runs/exec-a1b2c3d4e5f6
    Routes->>ES: get_execution_status(execution_id)
    ES-->>Routes: { status: "completed", workflow_id: "wf-<uuid>" }
    Routes-->>C: 200 { status: "completed", workflow_id }
```

### 9.5 WebSocket Lifecycle Sequence

```mermaid
sequenceDiagram
    participant C as React Client
    participant AR as /api/auth/ws-ticket
    participant WS as /ws/{workflow_id}
    participant TS as WS Ticket Store
    participant DS as DashboardDataService
    participant EB as ObservabilityEventBus
    participant DB as PostgreSQL

    C->>AR: POST /api/auth/ws-ticket\nAuthorization: Bearer tk_...
    AR->>AR: require_auth → AuthContext
    AR->>TS: generate_ws_ticket(ctx)\n→ "wst_<32chars>", TTL=30s
    AR-->>C: { "ticket": "wst_Kj2m..." }

    C->>WS: WebSocket CONNECT /ws/{workflow_id}?ticket=wst_Kj2m...
    WS->>TS: validate_ws_ticket(ticket)\n→ pop from store (one-time use)\n→ check expiry
    alt Ticket invalid or expired
        TS-->>WS: None
        WS-->>C: close(code=4001, "Invalid or expired ticket")
    else Valid
        TS-->>WS: AuthContext
        WS-->>C: 101 WebSocket Upgrade (accept())
    end

    WS->>DB: asyncio.to_thread(get_workflow_snapshot, workflow_id)
    DB-->>WS: snapshot dict (full workflow state)
    WS-->>C: { "type": "snapshot", "workflow": {...} }

    WS->>EB: subscribe_workflow(workflow_id, on_event)
    EB-->>WS: subscription_id

    WS->>WS: Start flush_task (_flush_chunks_task, 30ms poll)
    WS->>WS: Start poll_task (_db_poll_loop, 2s poll)

    loop Workflow Executing (event stream)
        EB->>WS: on_event(ObservabilityEvent) [from worker thread]
        alt event_type in ("llm_stream_chunk", "stream_token")
            WS->>WS: loop.call_soon_threadsafe(chunk_buffer.append, event)
            WS->>WS: flush_task batches ≥10 or waits ≤60ms
            WS-->>C: { "type": "event", "event_type": "llm_stream_batch",\n  "data": { "chunks": [...] } }
        else other events (agent_started, stage_completed, etc.)
            WS->>WS: event_queue.put_nowait(event_dict)
            WS-->>C: { "type": "event", "event_type": "...", ... }
        end
    end

    loop DB Poll (every 2s)
        WS->>DB: asyncio.to_thread(get_workflow_snapshot, workflow_id)
        DB-->>WS: snapshot
        alt fingerprint changed
            WS-->>C: { "type": "snapshot", "workflow": updated_snapshot }
        end
        alt status in terminal (completed/failed/halted/timeout)
            WS->>WS: break poll loop
        end
    end

    loop No events for 30s
        WS-->>C: { "type": "heartbeat", "timestamp": "..." }
    end

    alt Client disconnects
        C-->>WS: WebSocket close frame
        WS->>EB: unsubscribe(subscription_id)
        WS->>WS: cancel flush_task, cancel poll_task
    end
```

### 9.6 Tenant Isolation at Every Layer

```mermaid
flowchart TD
    CLIENT["Client Request\n(API key: tk_J9k2...)"]

    subgraph AUTH["Layer 1: Authentication"]
        HASH["hash_api_key(token)"]
        LOOKUP["SELECT api_keys JOIN tenant_memberships\nWHERE key_hash = ?"]
        CTX["AuthContext{ tenant_id = 'uuid-B' }"]
    end

    subgraph ROUTE["Layer 2: Route Handler"]
        RBAC["require_role check\n(role in allowed set)"]
        EXTRACT["ctx.tenant_id extracted\npassed to service layer"]
    end

    subgraph SERVICE["Layer 3: Service Layer"]
        SVCCHECK["if tenant_id is not None\n  and result.get('tenant_id') != tenant_id:\n    return None"]
    end

    subgraph DB["Layer 4: Database Query"]
        SQL["SELECT ... WHERE tenant_id = 'uuid-B'\n(All config and observability queries)"]
        UNIQUE["UNIQUE(tenant_id, name)\nconstraint on config tables"]
        CASCADE["ON DELETE CASCADE\ntenant FK on all config tables"]
    end

    TENANTA["Tenant A data\n(uuid-A rows)"]
    TENANTB["Tenant B data\n(uuid-B rows)"]

    CLIENT --> AUTH
    AUTH --> CTX
    CTX --> ROUTE
    ROUTE --> RBAC
    ROUTE --> EXTRACT
    EXTRACT --> SERVICE
    SERVICE --> SVCCHECK
    SVCCHECK --> DB
    DB --> SQL
    SQL --> TENANTB
    SQL -.->|"WHERE clause\nprevents access"| TENANTA

    style TENANTA fill:#ffcccc,stroke:#cc0000
    style TENANTB fill:#ccffcc,stroke:#006600
```

### 9.7 Config Management Flow

```mermaid
flowchart TD
    CLIENT["Client: POST /api/configs/import\n{ config_type, name, yaml_content }"]
    AUTHCHECK["require_role('owner','editor')\n→ AuthContext{tenant_id, role}"]
    VALIDATE1{"config_type in\n{'workflow','stage','agent'}?"}
    VALIDATE2{"name not empty?"}
    CSS["ConfigSyncService.import_config(\n  tenant_id, config_type,\n  name, yaml_content, user_id\n)"]
    YAML["yaml.safe_load(yaml_content)"]
    PYDANTIC["model_cls.model_validate(data)\nWorkflowConfig / StageConfig / AgentConfig"]
    DBCHECK{"Existing record\nfor (tenant_id, name)?"}
    UPDATE["UPDATE: config_data=new_data\nversion += 1\nupdated_by=user_id\nupdated_at=utcnow()"]
    INSERT["INSERT: id=uuid\ntenant_id=tenant_id\nname=name\nconfig_data=data\ncreated_by=user_id"]
    RESP["200 { name, config_type, version }"]

    E400A["400 Invalid config_type"]
    E400B["400 Name empty"]
    E422A["422 YAML parse error"]
    E422B["422 Pydantic validation failed"]

    CLIENT --> AUTHCHECK
    AUTHCHECK --> VALIDATE1
    VALIDATE1 -- No --> E400A
    VALIDATE1 -- Yes --> VALIDATE2
    VALIDATE2 -- No --> E400B
    VALIDATE2 -- Yes --> CSS
    CSS --> YAML
    YAML -- Error --> E422A
    YAML -- OK --> PYDANTIC
    PYDANTIC -- Error --> E422B
    PYDANTIC -- OK --> DBCHECK
    DBCHECK -- Yes (upsert) --> UPDATE
    DBCHECK -- No (insert) --> INSERT
    UPDATE --> RESP
    INSERT --> RESP
```

### 9.8 Full Server Mode State Machine

```mermaid
stateDiagram-v2
    [*] --> ServerStarting : temper-ai serve

    ServerStarting --> DatabaseReady : ensure_database(db_url)
    DatabaseReady --> AppReady : create_app(mode="server")

    AppReady --> AcceptingRequests : lifespan startup complete

    state AcceptingRequests {
        [*] --> Unauthenticated
        Unauthenticated --> Authenticating : POST /api/auth/signup
        Authenticating --> Onboarded : user + tenant + api_key created

        Onboarded --> Authenticated : Bearer tk_... header validated
        Authenticated --> Configured : POST /api/configs/import
        Authenticated --> Executing : POST /api/runs
        Authenticated --> Monitoring : GET /api/workflows

        Executing --> StreamingEvents : WebSocket /ws/{workflow_id}
        StreamingEvents --> Executing : events flowing
        Executing --> Completed : workflow finished
        Executing --> Failed : workflow error
        Completed --> Monitoring
        Failed --> Monitoring
    }

    AcceptingRequests --> Draining : SIGTERM received
    Draining --> Draining : readiness gate = False (503)\nActive runs finishing
    Draining --> Stopped : all runs complete
    Stopped --> [*]
```

---

## 10. Data Models Reference

### 10.1 Tenancy Models — `models_tenancy.py`

**Location:** `temper_ai/storage/database/models_tenancy.py`

All seven M10 tenancy tables with their key columns:

**`Tenant`** (`tenants` table):

| Column | Type | Description |
|--------|------|-------------|
| `id` | `str` (UUID PK) | Tenant identifier |
| `name` | `str(256)` | Display name (set to slug initially) |
| `slug` | `str(128)` | URL-safe identifier, unique |
| `is_active` | `bool` | Soft-delete flag |
| `plan` | `str(64)` | Billing plan (`"free"` default) |
| `max_workflows` | `int` | Workflow execution limit (100 default) |
| `created_at` | `datetime` | UTC creation timestamp |
| `metadata_json` | `JSON` | Arbitrary tenant metadata |

**`UserDB`** (`users` table):

| Column | Type | Description |
|--------|------|-------------|
| `id` | `str` (UUID PK) | User identifier |
| `email` | `str(320)` | Email, unique constraint |
| `name` | `str(256)` | Display name |
| `oauth_provider` | `str(64)` | For future OAuth integration |
| `is_active` | `bool` | Soft-delete flag |

**`TenantMembership`** (`tenant_memberships` table):

| Column | Type | Description |
|--------|------|-------------|
| `tenant_id` | FK → tenants | ON DELETE CASCADE |
| `user_id` | FK → users | ON DELETE CASCADE |
| `role` | `str(32)` | `"owner"` / `"editor"` / `"viewer"` |
| Unique | `(tenant_id, user_id)` | One role per user per tenant |

**`APIKey`** (`api_keys` table):

| Column | Type | Description |
|--------|------|-------------|
| `user_id` | FK → users | ON DELETE CASCADE |
| `tenant_id` | FK → tenants | ON DELETE CASCADE |
| `label` | `str(128)` | Human-readable key name |
| `key_prefix` | `str(16)` | First 11 chars (`tk_` + 8) for display |
| `key_hash` | `str(64)` | SHA-256 hex digest, indexed |
| `is_active` | `bool` | Soft-delete via revocation |
| `expires_at` | `datetime?` | Optional expiry |
| `last_used_at` | `datetime?` | Updated on each use |
| `total_requests` | `int` | Request count, atomically updated |

**Composite indexes:**
- `idx_api_keys_hash_active (key_hash, is_active)` — auth lookup
- `idx_membership_tenant_role (tenant_id, role)` — RBAC query
- `idx_workflow_configs_tenant (tenant_id, name)` — config load

**`WorkflowConfigDB` / `StageConfigDB` / `AgentConfigDB`** (three separate tables):

| Column | Type | Description |
|--------|------|-------------|
| `tenant_id` | FK → tenants CASCADE | Tenant isolation |
| `name` | `str(256)` | Config name |
| `version` | `int` (≥1) | Incremented on each update |
| `config_data` | `JSON` | Parsed YAML as JSONB |
| `created_by` | FK → users SET NULL | Audit: creator |
| `updated_by` | FK → users SET NULL | Audit: last editor |
| Unique | `(tenant_id, name)` | No name collision per tenant |

### 10.2 AuthContext Dataclass

**Location:** `temper_ai/auth/api_key_auth.py:33`

```python
@dataclass(frozen=True)
class AuthContext:
    user_id: str      # UUID string, references users.id
    tenant_id: str    # UUID string, references tenants.id
    role: str         # "owner" | "editor" | "viewer"
    api_key_id: str   # UUID string, references api_keys.id (for auditing)
```

`frozen=True` makes `AuthContext` immutable — it cannot be modified after creation, preventing accidental mutation in middleware or route handlers.

### 10.3 WorkflowExecutionMetadata

**Location:** `temper_ai/workflow/execution_service.py:61`

In-memory execution tracking (not persisted directly, mirrored to `RunStore`):

| Field | Type | Description |
|-------|------|-------------|
| `execution_id` | `str` | `exec-{12hex}` or `exec-{run_id}` |
| `workflow_path` | `str` | Relative path to workflow YAML |
| `workflow_name` | `str` | Name from workflow config |
| `status` | `WorkflowExecutionStatus` | PENDING/RUNNING/COMPLETED/FAILED/CANCELLED |
| `started_at` | `datetime?` | When RUNNING transition occurred |
| `completed_at` | `datetime?` | When terminal state was reached |
| `error_message` | `str?` | Error details if FAILED |
| `workflow_id` | `str?` | LangGraph workflow UUID (set after execution starts) |
| `result` | `dict?` | Sanitized workflow result |

The `WorkflowExecutionStatus` enum uses string values so it can be serialized directly in JSON responses.

### 10.4 ServerRun DB Model

**Location:** `temper_ai/interfaces/server/models.py`

The `ServerRun` SQLModel table provides persistent run history across server restarts:

| Column | Type | Description |
|--------|------|-------------|
| `execution_id` | `str` PK | `exec-{12hex}` |
| `workflow_path` | `str` | Path used for this run |
| `workflow_name` | `str` | Workflow display name |
| `status` | `str` | String status value |
| `input_data` | `JSON?` | Workflow inputs |
| `workspace` | `str?` | Workspace path |
| `tenant_id` | `str?` | Tenant who triggered the run |
| `workflow_id` | `str?` | LangGraph ID (set after start) |
| `result_summary` | `JSON?` | Sanitized result dict |
| `error_message` | `str?` | Error on failure |
| `started_at` | `datetime?` | Execution start timestamp |
| `completed_at` | `datetime?` | Execution end timestamp |
| `created_at` | `datetime` | Record creation time |

### 10.5 Config DB Models

All three config models (`WorkflowConfigDB`, `StageConfigDB`, `AgentConfigDB`) share the same schema structure with different table names:
- `workflow_configs` — stores complete workflow YAML as JSON
- `stage_configs` — stores stage configuration YAML as JSON
- `agent_configs` — stores agent configuration YAML as JSON

Each has a unique constraint on `(tenant_id, name)` ensuring configs are namespace-isolated per tenant and named uniquely within a tenant's namespace.

---

## 11. Security Design Decisions

### 11.1 API Key Scheme — `tk_` Prefix, HMAC-SHA256

**Location:** `temper_ai/auth/api_key_auth.py`

The API key design follows industry best practices:

1. **Prefix discrimination:** The `tk_` prefix allows instant identification of API keys in logs and configuration files, enabling fast rotation if leaked. Scanners (like GitHub's secret scanning) can be configured to detect this prefix.

2. **HMAC-SHA256 with pepper:** Adding `TEMPER_API_KEY_PEPPER` (server-side secret) means even if the database is fully compromised, an attacker cannot crack stored hashes without also knowing the pepper. Plain SHA-256 without pepper would allow offline brute-forcing of short or predictable keys.

3. **Prefix-only storage for display:** Only `key_prefix` (11 chars: `tk_` + 8) is stored for human identification. This lets users identify which key is which without storing enough to reconstruct or brute-force the full key.

4. **Single plaintext exposure:** The full key is returned exactly once (at creation) and never stored. There is no `GET /api/auth/api-keys/{id}` endpoint that returns the full key.

5. **Usage audit:** Every authentication call updates `last_used_at` and increments `total_requests` — creating an audit trail of key usage without overhead logging.

### 11.2 WebSocket Ticket Isolation

**Location:** `temper_ai/auth/ws_tickets.py`

WebSocket connections cannot use HTTP headers (standard browsers disallow custom headers on WebSocket upgrade). Two alternatives exist:
- Pass token in query string (visible in server logs, browser history, proxy logs)
- Two-step ticket exchange (chosen approach)

The ticket scheme prevents API key exposure:
- Ticket is single-use (consumed on first WebSocket auth check)
- 30-second TTL (enough for page load + connection initiation)
- In-memory storage (never touches database for WS authentication)
- `threading.Lock` for concurrent access safety
- `wst_` prefix distinguishes tickets from API keys in logs

**Deprecated path:** `?token=` (direct API key in WS query string) is still supported for backward compatibility but logs a deprecation warning. Clients should migrate to ticket-based auth.

### 11.3 Tenant Isolation Strategy

Tenant isolation is a defense-in-depth design with three independent layers:

**Layer 1 — Authentication (who you are):** The API key lookup retrieves `tenant_id` from the database via the `TenantMembership` join. An API key is always bound to a specific tenant — it cannot be used to impersonate another tenant.

**Layer 2 — Query-level isolation (what you can see):** Every SQL query for tenant-owned data includes `WHERE tenant_id = ?`. The `tenant_id` value always originates from `AuthContext.tenant_id` (not from user input), so it cannot be spoofed via the request body.

**Layer 3 — Service-layer validation (defense-in-depth):** After every DB query, service methods verify `result.get("tenant_id") == tenant_id`. Even if a query bug returned cross-tenant data, this check would prevent it from being returned to the caller.

**Config table constraints:** The `UNIQUE(tenant_id, name)` constraint on all config tables means even if two tenants both import a config named `"research-workflow"`, they are entirely separate records with no sharing.

**Cascade deletes:** All tenant-owned tables use `ON DELETE CASCADE` on the `tenant_id` foreign key. Deleting a tenant record atomically removes all associated users, memberships, API keys, and configs.

### 11.4 CORS and Security Headers

**Server mode CORS:**
- Origins: explicit whitelist from `TEMPER_CORS_ORIGINS` environment variable
- Methods: `GET, POST` only (no PUT, DELETE, PATCH from CORS)
- Headers: `Content-Type, Authorization` only
- If `TEMPER_CORS_ORIGINS` is unset: NO `CORSMiddleware` is added, relying on same-origin policy

**Dev mode CORS:**
- Regex: `^https?://(localhost|127\.0\.0\.1)(:\d+)?$`
- Methods: `*` (all)
- Headers: `*` (all)
- Prevents XSS attacks from external sites even in development

**Security headers (all modes):**
- `X-Content-Type-Options: nosniff` — prevents MIME-type sniffing attacks
- `X-Frame-Options: DENY` — prevents clickjacking via iframe embedding
- `Referrer-Policy: strict-origin-when-cross-origin` — controls referrer leakage

### 11.5 Rate Limiting on Public Endpoints

**Location:** `temper_ai/interfaces/server/auth_routes.py:46-56`

The in-process rate limiter uses a sliding window stored in a `defaultdict(list)`:

```python
_rate_limit_store: dict[str, list[float]] = defaultdict(list)

def _check_rate_limit(key: str, max_requests: int) -> bool:
    now = time.monotonic()
    window_start = now - RATE_LIMIT_WINDOW   # 60 seconds
    hits = _rate_limit_store[key]
    _rate_limit_store[key] = [t for t in hits if t > window_start]  # prune old
    if len(_rate_limit_store[key]) >= max_requests:
        return False
    _rate_limit_store[key].append(now)
    return True
```

Rate limits:
- Signup (`signup:<ip>`): 5 requests per 60 seconds
- API key creation (`api-key:<user_id>`): 10 requests per 60 seconds

**Limitation noted:** This is an in-process rate limiter. In a multi-process deployment (multiple uvicorn workers), rate limits are not shared between processes. For production, a Redis-based distributed rate limiter would be needed.

### 11.6 Path Traversal Prevention

**Location:** `temper_ai/interfaces/server/routes.py:81-86`

The `POST /api/runs` handler prevents directory traversal attacks in the workflow path parameter:

```python
config_root_resolved = Path(config_root).resolve()
workflow_file = (config_root_resolved / body.workflow).resolve()
try:
    workflow_file.relative_to(config_root_resolved)
except ValueError:
    raise HTTPException(400, "Invalid workflow path")
```

`Path.resolve()` normalizes `./../../../` sequences. `relative_to()` raises `ValueError` if the resolved path escapes the config root. This prevents `../../etc/passwd` or `../../../home/user/.ssh/id_rsa` attacks.

The same validation is also applied in `_handle_validate_workflow()`.

---

## 12. Mode Comparison: Dev vs. Server

| Feature | Dev Mode (`--dev`) | Server Mode (default) |
|---------|-------------------|----------------------|
| `auth_enabled` | `False` | `True` |
| Authentication | None required | Bearer `tk_` API key, HMAC-SHA256 |
| CORS | localhost only (regex) | `TEMPER_CORS_ORIGINS` env variable |
| Auth routes | Not registered | `/api/auth/*` registered |
| Config routes | Not registered | `/api/configs/*` registered |
| Studio backend | YAML files on disk | PostgreSQL database |
| Config storage | Filesystem `configs/` | DB: `workflow_configs`, `stage_configs`, `agent_configs` |
| WebSocket auth | No ticket required | Short-lived `wst_` ticket required |
| RunStore | Active | Active |
| Rate limiting | Active (but no auth means no API key rate limits) | Active |
| Security headers | Active | Active |
| RBAC | Not enforced | 3-role: owner / editor / viewer |
| Tenant isolation | No tenants | Full per-tenant DB isolation |
| DB config loader | Filesystem ConfigLoader | DBConfigLoader (for tenant_id requests) |
| Background mining | Active | Active |
| Background analysis | Active | Active |
| Graceful shutdown | Active | Active |

---

## 13. Extension Points

### Adding a New Protected Route

To add a new route with tenant-aware auth in server mode:

1. Create a new route file under `temper_ai/interfaces/server/` or `temper_ai/interfaces/dashboard/`
2. Import `require_auth` or `require_role` from `temper_ai.auth.api_key_auth`
3. Add `ctx: AuthContext = Depends(require_auth)` or `ctx: AuthContext = Depends(require_role("owner"))` to handler
4. Pass `ctx.tenant_id` to any service or DB call
5. Register the router in `app.py:_register_optional_routes()` or conditionally in `_register_auth_routes()` if server-only

### Adding a New Config Type

To add a fourth config type (e.g., `"tool"`):

1. Add `CONFIG_TYPE_TOOL = "tool"` and update `VALID_CONFIG_TYPES` in `models_tenancy.py`
2. Create `ToolConfigDB` SQLModel in `models_tenancy.py` following the existing pattern
3. Add a `ToolConfig` Pydantic schema in `temper_ai/storage/schemas/`
4. Update `_CONFIG_TYPE_DB_MODEL` in both `config_sync.py` and `db_config_loader.py`
5. Update `_get_pydantic_model()` in `config_sync.py`
6. Generate a new Alembic migration for the new table
7. Update `DBConfigLoader.list_configs()` to handle the new type
8. Update `VALID_CONFIG_TYPES` in `config_routes.py` and `studio_routes.py`

### Adding a New RBAC Role

To add a `"super_admin"` role:

1. Add `ROLE_SUPER_ADMIN = "super_admin"` in `models_tenancy.py`
2. Update `VALID_ROLES` and `ROLE_CHECK` constraint string
3. Generate an Alembic migration to update the `CHECK` constraint
4. Use `Depends(require_role("super_admin"))` on admin-only routes

### Distributed Rate Limiting

To replace the in-process rate limiter with a Redis-based one:

1. Replace `_rate_limit_store: dict[str, list[float]] = defaultdict(list)` with a Redis client
2. Use `INCR` + `EXPIRE` commands or a sorted set sliding-window approach
3. Configure via `TEMPER_REDIS_URL` environment variable
4. This would share rate limit state across all uvicorn worker processes

---

## 14. Observations and Recommendations

### Strengths

**Clean auth_enabled toggle:** The single `auth_enabled = (mode == "server")` boolean flows through the entire application cleanly. Routes are registered with or without dependencies based on this flag. The same codebase handles both dev and production modes without complex conditional logic throughout.

**Defense-in-depth tenant isolation:** Three independent layers (API key binding, SQL WHERE clause, service-layer validation) ensure that cross-tenant data leakage is prevented even if one layer has a bug. The defense-in-depth pattern is a security best practice.

**Ticket-based WebSocket auth:** The `wst_` ticket pattern cleanly solves the problem of API keys in WebSocket query strings. The 30-second TTL and single-use consumption prevent replay attacks. The in-memory storage avoids database overhead on every WebSocket authentication.

**Adaptive LLM stream batching:** The 30ms batching window for LLM streaming tokens delivers first-token latency of 30-60ms while reducing WebSocket message overhead by batching up to 10 chunks. The adaptive behavior (flush immediately at batch size, wait one more window if under threshold) is a good balance of latency and throughput.

**Backward-compatible config versioning:** The `config_data JSONB + version` approach in config tables allows the stored configs to evolve without schema migrations. Config validation happens at write time (via Pydantic), so stored configs are always structurally valid.

**Graceful shutdown design:** The `GracefulShutdownManager` + `drain()` pattern ensures that in-flight workflows complete before the process terminates. The readiness probe correctly signals 503 during draining, allowing load balancers to route new requests to healthy instances.

### Areas of Concern

**In-process rate limiter:** The `defaultdict(list)` rate limiter in `auth_routes.py` is not shared between uvicorn worker processes. In a multi-worker deployment, each worker has its own rate limit counter, effectively multiplying the allowed requests by the number of workers. For production, a Redis-based distributed rate limiter is necessary.

**`_rate_limit_store` memory growth:** The rate limit store is pruned on every request to the same key, but keys for IPs that never make a second request within the window will accumulate indefinitely. A periodic cleanup job (similar to `cleanup_expired()` in `ws_tickets.py`) would prevent unbounded memory growth under distributed denial-of-service conditions.

**`tenant_id` passed through WorkflowExecutionService but not forwarded to WorkflowRunner:** In `_prepare_execution()`, `tenant_id` is saved to the `ServerRun` record, but it is not currently passed through to `WorkflowRunner` and `WorkflowRuntime`. The `DBConfigLoader` path (for loading configs from DB) is only activated when `tenant_id` is explicitly passed to `WorkflowRuntime.run_pipeline()`. The execution chain from `_execute_workflow_in_runner` creates a `WorkflowRunner` without `tenant_id`, so the execution falls back to filesystem config loading even in server mode unless this is explicitly wired.

**WebSocket ticket store cleanup:** `cleanup_expired()` in `ws_tickets.py` removes expired tickets, but it is only defined, not scheduled. There is no background task calling it periodically. Expired tickets accumulate in `_store` until the next request for the same ticket key is made. Under high load, this is a minor memory leak.

**Single database for RunStore and observability:** `RunStore` uses the same `TEMPER_DATABASE_URL` as the main observability database. Under heavy load, run status updates and observability writes contend on the same connection pool. Consider separate databases or at minimum separate connection pools for these workloads.

**`DashboardDataService.get_workflow_trace()` exception handling:** The method catches `ImportError` and `RuntimeError` broadly, falling back to `get_workflow_snapshot()`. If the `export_waterfall` module fails for reasons other than `ImportError`, the tenant_id check in the fallback path could differ from the check in the primary path, creating an inconsistency.

### Best Practices Observed

**Lazy imports for cross-domain dependencies:** `config_routes.py:_get_sync_service()` and `workflow_runner.py:_run_core()` use lazy imports inside methods to avoid circular imports and reduce startup fan-out. This pattern is used consistently throughout the codebase.

**Frozen dataclass for AuthContext:** Making `AuthContext` frozen prevents accidental mutation by route handlers. Since it carries security-critical tenant identity, immutability is essential.

**`asyncio.to_thread()` for DB calls in WebSocket handler:** All database operations in the WebSocket handler use `asyncio.to_thread()` to offload blocking I/O. This prevents the async event loop from stalling, which would delay all WebSocket connections.

**`session.flush()` before `session.commit()` in signup:** The signup handler calls `session.flush()` after each record creation (before the final `session.commit()`). This assigns database-generated IDs (UUIDs) to in-memory objects so they can be referenced by subsequent records within the same transaction, without committing partial state.

**`session.merge()` in RunStore:** Using `session.merge()` instead of `session.add()` in `RunStore.save_run()` implements natural upsert behavior — if the execution ID already exists, the record is updated rather than causing a duplicate key error. This handles the race condition where a run might be saved twice.

---

*End of Document — 15-flow-multi-tenant.md*
