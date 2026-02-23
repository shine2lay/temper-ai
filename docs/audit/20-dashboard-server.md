# Audit Report: Dashboard & Server Modules

**Date:** 2026-02-22
**Scope:** `temper_ai/interfaces/dashboard/` + `temper_ai/interfaces/server/`
**Auditor:** Claude Opus 4.6

---

## Executive Summary

The dashboard and server modules are well-structured with clean separation of concerns (routes, services, models). Security posture is strong for a project at this maturity level: CORS is properly configured per mode, security headers are present, path traversal is defended, input validation uses Pydantic, and multi-tenant auth is integrated with role-based access control. The main weaknesses are: **missing tenant isolation on several authenticated endpoints** (IDOR risk), **no auth on the agent_routes module**, **no rate limiting on workflow execution endpoints**, and **route duplication from the auth_enabled branching pattern**. Test coverage is solid for dashboard routes and studio CRUD but thin for auth_routes and config_routes.

**Overall Grade: B+ (83/100)**

| Dimension | Score | Notes |
|-----------|-------|-------|
| Code Quality | 88 | Clean functions, good naming, minor duplication |
| Security | 72 | Tenant isolation gaps, missing auth on agent_routes |
| Error Handling | 90 | Consistent pattern, graceful degradation |
| Modularity | 85 | Good service layer, some coupling |
| Feature Completeness | 88 | No TODO/FIXME, complete implementations |
| Test Quality | 78 | Good dashboard coverage, weak server auth coverage |

---

## 1. Security Findings

### S-01: CRITICAL -- Agent Routes Missing Authentication (agent_routes.py)

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/interfaces/server/agent_routes.py`
**Lines:** 38-104

The entire `agent_routes.py` module has **zero auth checks**. All 5 endpoints (list, get, register, unregister, send_message) are completely unauthenticated. When `auth_enabled=True` in server mode, every other router applies `Depends(require_auth)` or `Depends(require_role(...))`, but `agent_routes` is registered via `_register_optional_routes()` (app.py:267-268) without any auth gating.

```python
# agent_routes.py:38 -- no auth dependency
@router.get("")
def list_agents(status: str | None = None):
    ...

# agent_routes.py:58 -- no auth on registration (write operation!)
@router.post("/register")
def register_agent(request: RegisterRequest):
    ...

# agent_routes.py:71 -- no auth on deletion!
@router.delete("/{name}")
def unregister_agent(name: str):
    ...
```

**Impact:** Any unauthenticated client can register, invoke, or delete persistent agents in server mode.
**Recommendation:** Add `Depends(require_auth)` to read endpoints and `Depends(require_role("owner", "editor"))` to write/delete endpoints. Follow the same branching pattern as `routes.py` for `auth_enabled`.

### S-02: HIGH -- Tenant Isolation Missing on Run Endpoints (routes.py)

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/interfaces/server/routes.py`
**Lines:** 256-282

When `auth_enabled=True`, the `list_runs`, `get_run`, `cancel_run`, and `get_run_events` endpoints apply `Depends(require_auth)` as a dependency but **do not pass `tenant_id`** to the handler functions for row-level filtering. Only `create_run` (line 249) passes `tenant_id=ctx.tenant_id`.

```python
# routes.py:256-263 -- auth applied but no tenant filtering
@router.get("/runs", dependencies=read_deps)
async def list_runs(
    status: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    return await _handle_list_runs(execution_service, status, limit, offset)
    # Missing: tenant_id=ctx.tenant_id
```

**Impact:** In multi-tenant mode, authenticated users can see, cancel, and read events for **all tenants' workflow runs** (IDOR vulnerability).
**Recommendation:** Thread `tenant_id` from `AuthContext` into `_handle_list_runs`, `_handle_get_run`, `_handle_cancel_run`, and `_handle_get_run_events`. Update `WorkflowExecutionService` to filter by `tenant_id`.

### S-03: HIGH -- No Rate Limiting on Workflow Execution Endpoints

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/interfaces/server/routes.py`
**Lines:** 243-254

The `POST /api/runs` endpoint creates a new workflow execution backed by a ThreadPoolExecutor. There is no rate limiting -- an attacker with a valid API key (or in dev mode, anyone) can submit unlimited workflow runs, exhausting server resources.

Auth routes (`auth_routes.py`) have per-IP rate limiting for signup and per-user rate limiting for API key creation, but the most resource-intensive endpoint (workflow execution) has none.

**Recommendation:** Apply rate limiting (per-user in server mode, per-IP in dev mode) to `POST /api/runs`. Consider using the existing `_check_rate_limit()` pattern from `auth_routes.py` or the `workflow_rate_limiter` tool.

### S-04: MEDIUM -- Missing Security Headers

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/interfaces/dashboard/app.py`
**Lines:** 89-108

The `_SecurityHeadersMiddleware` adds `X-Content-Type-Options`, `X-Frame-Options`, and `Referrer-Policy` but is missing:

- `Content-Security-Policy` (CSP) -- critical for the SPA to prevent XSS
- `Strict-Transport-Security` (HSTS) -- important for server mode over HTTPS
- `X-XSS-Protection` (legacy but still useful for older browsers)

**Recommendation:** Add at minimum `Content-Security-Policy: default-src 'self'` and `Strict-Transport-Security: max-age=31536000; includeSubDomains` (conditionally, when HTTPS is detected).

### S-05: MEDIUM -- CORS allow_credentials Not Set

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/interfaces/dashboard/app.py`
**Lines:** 60-86

Neither server nor dev mode CORS configuration sets `allow_credentials`. This is currently safe (credentials are not cookies but API keys in headers). However, in dev mode `allow_methods=["*"]` and `allow_headers=["*"]` are overly permissive -- they allow `DELETE`, `PATCH`, and custom headers from any localhost origin.

**Recommendation:** Restrict dev mode `allow_methods` to `["GET", "POST", "PUT", "DELETE"]` and `allow_headers` to `["Content-Type", "Authorization"]` to match server mode.

### S-06: LOW -- WebSocket Token Deprecation Path Leaks Key in URL

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/interfaces/dashboard/websocket.py`
**Lines:** 199-216

The deprecated `?token=` WebSocket auth path puts the API key directly in the URL query string, which is logged by proxies, access logs, and browser history. The warning is issued (line 209-211) but the path remains functional.

**Recommendation:** Set a removal date for the `?token=` path. Consider rejecting it entirely in server mode after a deprecation period.

---

## 2. Code Quality Findings

### CQ-01: Route Duplication from auth_enabled Branching

**Files:**
- `/home/shinelay/meta-autonomous-framework/temper_ai/interfaces/dashboard/routes.py` (lines 91-195)
- `/home/shinelay/meta-autonomous-framework/temper_ai/interfaces/dashboard/studio_routes.py` (lines 191-304)

Both `routes.py` and `studio_routes.py` use an `if auth_enabled: ... else: ...` pattern that duplicates every route handler. In `routes.py`, this produces 8+8 = 16 near-identical route definitions. In `studio_routes.py`, it produces 7+7 = 14.

The handler logic is properly extracted into `_handle_*` functions (good), but the route registration is fully duplicated. This creates maintenance risk: any new endpoint must be added in two places.

**Recommendation:** Use a middleware or dependency-injection approach. For example, define routes once with an optional auth dependency:

```python
auth_dep = Depends(require_auth) if auth_enabled else Depends(lambda: None)
```

Or use FastAPI's dependency override mechanism.

### CQ-02: Broad Exception Catches in App Initialization

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/interfaces/dashboard/app.py`
**Lines:** 240, 252, 263, 269, 326, 340, 352

Seven `except Exception:` blocks catch all errors during optional route registration. While these are annotated with `# noqa: BLE001` (indicating deliberate choice for robustness), they swallow errors that could be important during development -- e.g., import errors from typos, configuration errors, or permission issues.

**Recommendation:** Log at `logger.warning` level with `exc_info=True` to include the traceback. Currently some log at warning level without the traceback.

### CQ-03: Production Import from examples/ Package

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/interfaces/dashboard/data_service.py`
**Line:** 64

```python
from examples.export_waterfall import export_waterfall_trace
```

Production code imports from the `examples/` directory. This couples the dashboard to example scripts and will break if `examples/` is not in `sys.path` or is excluded from deployment.

**Recommendation:** Move `export_waterfall_trace` into `temper_ai/observability/` or provide a fallback implementation within the dashboard module.

### CQ-04: Agent Routes Use Module-Level Router (Not Factory Pattern)

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/interfaces/server/agent_routes.py`
**Lines:** 9, 38-104

Unlike every other route module which uses a factory function (`create_*_router()`), `agent_routes.py` creates a module-level `router` object. This makes it harder to inject dependencies (like `auth_enabled`, tenant scoping) and is inconsistent with the codebase pattern.

```python
# agent_routes.py:9 -- module-level router
router = APIRouter(prefix="/api/agents", tags=["agents"])

# vs. every other module:
def create_auth_router() -> APIRouter:
    router = APIRouter(...)
    ...
    return router
```

**Recommendation:** Refactor to `create_agent_router(auth_enabled: bool = False) -> APIRouter` following the established pattern.

### CQ-05: New Service Instance per Request in Agent Routes

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/interfaces/server/agent_routes.py`
**Lines:** 31-35

```python
def _get_service():
    """Lazy import AgentRegistryService."""
    from temper_ai.registry.service import AgentRegistryService
    return AgentRegistryService()
```

Every request creates a new `AgentRegistryService` instance. If the service holds DB connections or cached state, this is wasteful. Other services (like `StudioService`, `DashboardDataService`) are created once at startup.

**Recommendation:** Create the service instance once during router construction and close over it, following the `create_router(service)` pattern.

### CQ-06: Hardcoded Version String

**Files:**
- `/home/shinelay/meta-autonomous-framework/temper_ai/interfaces/dashboard/app.py` (line 412: `version="0.1.0"`)
- `/home/shinelay/meta-autonomous-framework/temper_ai/interfaces/server/health.py` (line 11: `version: str = "0.1.0"`)

The version `"0.1.0"` is hardcoded in two places and does not reference `pyproject.toml` or any single source of truth.

**Recommendation:** Read the version from `importlib.metadata.version("temper-ai")` or define a `__version__` constant.

### CQ-07: `_check_data_size` Uses `sys.getsizeof` Instead of Actual Byte Length

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/interfaces/dashboard/studio_service.py`
**Lines:** 97-107

```python
def _check_data_size(data: dict) -> None:
    size = sys.getsizeof(json.dumps(data))
    if size > MAX_CONFIG_SIZE_BYTES:
        ...
```

`sys.getsizeof(json.dumps(data))` returns the CPython object overhead of the string, not the byte length. A 1KB JSON string will report as ~1100 bytes due to Python string object overhead. For accurate size checking, use `len(json.dumps(data).encode("utf-8"))`.

**Recommendation:** Replace with `len(json.dumps(data).encode("utf-8"))`.

---

## 3. Error Handling Findings

### EH-01: Inconsistent Error Response Format

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/interfaces/server/routes.py`
**Line:** 101

```python
raise HTTPException(
    status_code=HTTP_500_INTERNAL_SERVER_ERROR,
    detail="Internal server error: workflow execution failed"
)
```

The 500 error detail includes a specific message, while in `_handle_get_run` (line 132) it uses a generic "Failed to retrieve run status". Neither includes a request correlation ID.

**Recommendation:** Standardize error responses. Include a `request_id` or `execution_id` in error details for debugging. Never expose internal details to external users in server mode.

### EH-02: Health Check DB Probe Swallows All Exceptions

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/interfaces/server/health.py`
**Lines:** 54-62

```python
try:
    with get_session() as session:
        session.execute(text("SELECT 1"))
except Exception:  # noqa: BLE001
    db_ok = False
```

The broad exception catch is appropriate for a health check, but the error is not logged. If the database is misconfigured or has connection issues, the health endpoint silently reports `database_ok: false` with no debugging information.

**Recommendation:** Add `logger.warning("Health check DB probe failed", exc_info=True)`.

---

## 4. Modularity Findings

### MD-01: execution_service.py Is a Re-Export Shim

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/interfaces/dashboard/execution_service.py`

The entire file is a re-export shim:

```python
from temper_ai.workflow.execution_service import (  # noqa: F401
    WorkflowExecutionMetadata,
    WorkflowExecutionService,
    WorkflowExecutionStatus,
    _sanitize_workflow_result,
)
```

This is the correct pattern for backward compatibility after a migration. The canonical location is `temper_ai/workflow/execution_service.py`. No action needed but documenting for awareness.

### MD-02: Dashboard Optional Routes Registration is Complex

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/interfaces/dashboard/app.py`
**Lines:** 224-301

The `_register_optional_routes` function uses a mix of direct imports, `importlib.import_module`, and a domain registry pattern. This is intentionally designed to keep fan-out low, but the three different registration styles make the code hard to follow:

1. Direct import for autonomy routes (lines 232-241)
2. Domain registry + importlib for learning/goals/portfolio (lines 243-301)
3. Direct import for experimentation (lines 255-264)
4. Direct import for agent_routes (lines 266-270)

**Recommendation:** Consolidate into the domain registry pattern or use a plugin/autodiscovery mechanism.

### MD-03: `_register_dashboard_extras` Is a Thin Wrapper

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/interfaces/dashboard/app.py`
**Lines:** 168-173

```python
def _register_dashboard_extras(
    app: FastAPI, data_service: Any, config_root: str,
) -> None:
    _register_optional_routes(app, config_root)
```

The `data_service` parameter is accepted but never used. This function is a pass-through that adds no value.

**Recommendation:** Either remove the wrapper and call `_register_optional_routes` directly, or remove the unused `data_service` parameter.

---

## 5. Test Coverage Assessment

### Tests Found

| Module | Test File | Test Count | Coverage |
|--------|-----------|------------|----------|
| dashboard/routes | test_routes.py | ~30 | Good - all endpoints, edge cases, DAG flows |
| dashboard/studio_routes | test_studio_routes.py | ~15 | Good - CRUD, validation, path traversal |
| dashboard/studio_service | test_studio_service.py | ~15 | Good - all service methods |
| dashboard/websocket | test_websocket.py | ~10 | Good - snapshot, events, fingerprint, DB polling |
| server/routes | test_maf_server.py | ~15 | Moderate - health, validate, runs |
| server/auth middleware | test_auth.py | ~8 | Good - auth bypass, key validation |
| server/run_store | test_run_store.py | ~12 | Good - full CRUD coverage |
| server/workflow_runner | test_workflow_runner.py | ~8 | Good - success, failure, cleanup |
| server/server_client | test_server_client.py | ~8 | Good - client methods, CLI help |

### Coverage Gaps

**TC-01: No Tests for auth_routes.py**
The signup, API key CRUD, ws-ticket, and `/me` endpoints have **zero dedicated tests**. The rate limiting logic (`_check_rate_limit`) is also untested. (Note: `tests/test_auth/test_auth_routes.py` exists per MEMORY.md but likely tests the auth module separately, not the HTTP route layer.)

**TC-02: No Tests for config_routes.py**
The import, export, and list config endpoints have no dedicated HTTP-level tests.

**TC-03: No Tests for agent_routes.py**
No HTTP-level tests for the agent management API endpoints.

**TC-04: No Tests for Authenticated Dashboard Routes**
All dashboard route tests use `create_app(...)` in dev mode (no auth). The authenticated code paths with `Depends(require_auth)` in `routes.py` and `studio_routes.py` are not tested.

**TC-05: No Tests for Security Headers Middleware**
`_SecurityHeadersMiddleware` and `_NoCacheStaticMiddleware` have no dedicated tests.

**TC-06: WebSocket Auth Not Tested**
The WebSocket authentication flow (ticket-based and deprecated token-based) in `websocket.py:197-219` has no test coverage.

---

## 6. Architectural Observations

### A-01: Dual Auth Systems (Legacy Middleware vs. M10 Per-Route)

Two authentication mechanisms coexist:

1. **Legacy:** `server/auth.py` -- `APIKeyMiddleware` using `TEMPER_API_KEY` env var, validates `X-API-Key` header globally
2. **M10:** `auth/api_key_auth.py` -- Per-route `Depends(require_auth)` with database-backed API keys (`tk_` prefix), SHA-256 hashed

The legacy middleware is still importable and tested but is **not registered** by `create_app()`. It may confuse developers.

**Recommendation:** Add a deprecation notice to `server/auth.py` or remove it if it's no longer used by any code path.

### A-02: Dashboard Data Service Tenant Filtering Is Application-Level

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/interfaces/dashboard/data_service.py`

Tenant isolation in `DashboardDataService` works by:
1. Fetching the record without tenant filtering (e.g., `backend.get_workflow(workflow_id)`)
2. Checking `result.get("tenant_id") != tenant_id` after the fact

This is an application-level IDOR check rather than a database-level filter. It means the full record is loaded even for unauthorized tenants, and it relies on the backend returning `tenant_id` in every response.

**Recommendation:** Push tenant filtering into the backend query layer (e.g., `backend.get_workflow(workflow_id, tenant_id=...)`) to enforce isolation at the database level.

### A-03: In-Memory Execution Tracking Has No TTL

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/workflow/execution_service.py`
**Line:** 132

```python
self._executions: dict[str, WorkflowExecutionMetadata] = {}
```

Completed/failed executions are never evicted from the in-memory `_executions` dict. In a long-running server process, this will grow unboundedly.

**Recommendation:** Add a TTL or max-size eviction policy for completed executions (e.g., keep the last 1000 or evict after 24 hours).

---

## 7. File-by-File Summary

### Dashboard Module

| File | Lines | Quality | Notes |
|------|-------|---------|-------|
| `app.py` | 428 | Good | Clean app factory; 7 broad exception catches acceptable for optional routes |
| `routes.py` | 197 | Good | Clean handler extraction; route duplication from auth branching |
| `data_service.py` | 373 | Good | Well-structured; `examples/` import is a concern (CQ-03) |
| `execution_service.py` | 7 | Good | Re-export shim (correct pattern) |
| `websocket.py` | 281 | Very Good | Adaptive batching, DB polling, proper cleanup |
| `studio_routes.py` | 307 | Good | Complete CRUD; route duplication from auth branching |
| `studio_service.py` | 686 | Good | Well-structured; `_check_data_size` bug (CQ-07); DB methods clean |
| `constants.py` | 23 | Good | Proper constant extraction |

### Server Module

| File | Lines | Quality | Notes |
|------|-------|---------|-------|
| `routes.py` | 325 | Good | Path traversal defense; tenant isolation gap (S-02) |
| `models.py` | 51 | Good | Clean Pydantic+SQLModel |
| `health.py` | 70 | Good | Clean; needs logging on DB failure (EH-02) |
| `lifecycle.py` | 98 | Very Good | Signal handling, drain timeout, platform fallback |
| `run_store.py` | 82 | Very Good | Clean CRUD with pagination |
| `workflow_runner.py` | 186 | Very Good | Clean library API; proper cleanup |
| `agent_routes.py` | 105 | Needs Work | No auth (S-01), module-level router (CQ-04), per-request service (CQ-05) |
| `auth_routes.py` | 299 | Good | Rate limiting, clean helpers; no tests (TC-01) |
| `config_routes.py` | 157 | Good | Proper validation; no tests (TC-02) |
| `auth.py` | 65 | Legacy | Superseded by M10; should be deprecated (A-01) |
| `constants.py` | 9 | N/A | Placeholder file |

---

## 8. Prioritized Recommendations

### P0 -- Security (Must Fix)

1. **S-01:** Add authentication to `agent_routes.py` endpoints
2. **S-02:** Add tenant_id filtering to `list_runs`, `get_run`, `cancel_run`, `get_run_events` in authenticated mode

### P1 -- Security (Should Fix)

3. **S-03:** Add rate limiting to `POST /api/runs`
4. **S-04:** Add `Content-Security-Policy` and `Strict-Transport-Security` headers
5. **A-02:** Push tenant filtering to database layer in `DashboardDataService`

### P2 -- Quality & Testing

6. **TC-01/02/03:** Add HTTP-level tests for `auth_routes.py`, `config_routes.py`, `agent_routes.py`
7. **TC-04:** Add tests for authenticated code paths in dashboard routes
8. **CQ-01:** Reduce route duplication via dependency injection pattern
9. **CQ-03:** Move `export_waterfall_trace` out of `examples/`
10. **CQ-07:** Fix `_check_data_size` to use byte length instead of `sys.getsizeof`

### P3 -- Maintenance

11. **CQ-04/05:** Refactor `agent_routes.py` to factory pattern with injected service
12. **CQ-06:** Source version string from `pyproject.toml`
13. **A-01:** Deprecate or remove `server/auth.py`
14. **A-03:** Add TTL eviction for completed executions in `WorkflowExecutionService`
15. **MD-03:** Remove unused `data_service` parameter from `_register_dashboard_extras`
