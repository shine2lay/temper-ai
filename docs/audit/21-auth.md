# Auth Module Audit Report

**Module:** `temper_ai/auth/`
**Files Reviewed:** 19 source files, 27 test files
**Date:** 2026-02-22
**Auditor:** Claude Opus 4.6

---

## Executive Summary

The auth module implements two distinct authentication systems: (1) an OAuth 2.0 flow with session-based cookies for the dashboard UI, and (2) a newer API key system (M10) with tenant-scoped RBAC for the server API. Both systems are competently built with strong security practices (PKCE, CSRF protection, secure cookies, encrypted token storage). However, the audit identified 4 critical security findings, 5 high-severity issues, and 8 moderate issues spanning timing attacks, detached ORM access, missing tenant isolation, and synchronous DB calls in async context.

**Overall Grade: B+ (82/100)**

| Dimension | Score | Notes |
|---|---|---|
| Code Quality | 87 | Clean, well-structured, good constants extraction |
| Security | 72 | Several timing attack vectors, missing tenant scope in API key listing |
| Error Handling | 85 | Good coverage, two broad `except Exception` catches |
| Modularity | 90 | Clean separation of concerns, protocol-based abstractions |
| Feature Completeness | 80 | No TODO/FIXME markers, but ws_tickets and config_seed untested |
| Test Quality | 75 | Strong for core auth, zero coverage for ws_tickets and config_seed |
| Architecture | 88 | Good layering, proper dependency injection patterns |

---

## Critical Findings (P0)

### CRIT-1: Timing Attack on API Key Lookup

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/auth/api_key_auth.py:77-124`
**Severity:** Critical (Security)

The `_lookup_api_key` function performs a direct equality comparison on the key hash via SQL `WHERE key_hash = ?`. While the hash itself provides some protection, the function's observable behavior leaks information:

1. Hash computation time is constant (good), but the DB query returns early for non-existent hashes vs. found-but-inactive keys, creating a measurable timing difference between "key does not exist" and "key exists but is revoked/expired."
2. The `require_auth` function at line 127-180 has distinct code paths with different execution times for each failure mode (no token, bad prefix, not found, revoked, expired, success).

**Recommendation:** Use `hmac.compare_digest()` for hash comparison where possible. More importantly, ensure all error paths take approximately equal time by adding a constant-time comparison stub even on the "not found" path.

### CRIT-2: Synchronous DB Access Inside Async Function

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/auth/api_key_auth.py:77-124`
**Severity:** Critical (Reliability)

`_lookup_api_key` is declared `async` but uses synchronous `with get_session() as session:` and `session.exec()` calls. This blocks the event loop for every authenticated request, creating a bottleneck under concurrent load. The function also performs a `session.commit()` (line 115) inside the lookup path to update usage stats, compounding the blocking time.

```python
async def _lookup_api_key(key_hash: str) -> dict | None:
    # ...
    with get_session() as session:  # Synchronous! Blocks event loop
        stmt = select(...).join(...).where(...)
        row = session.exec(stmt).first()
        # ...
        session.commit()  # Another sync DB call
```

**Recommendation:** Either:
- Run the DB access in `asyncio.to_thread()` / a thread pool executor, or
- Use an async session (SQLAlchemy async engine), or
- Separate the usage-stat update into a fire-and-forget background task to reduce critical-path latency.

### CRIT-3: Detached ORM Instance Access After Session Close

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/auth/config_sync.py:137-149`
**Severity:** Critical (Reliability)

In `export_config`, the record is fetched inside a `with get_session()` block, but `record.config_data` is accessed *after* the session context manager has exited (line 149). If `config_data` is a lazy-loaded JSON column, this will raise `DetachedInstanceError` at runtime:

```python
with get_session() as session:
    record = session.query(db_model_cls).filter_by(...).first()

if record is None:
    raise FileNotFoundError(...)

return yaml.safe_dump(record.config_data, default_flow_style=False)  # DETACHED!
```

The same pattern exists in `list_configs` (lines 164-180), where `records` is iterated after the session closes.

**Recommendation:** Move the data extraction inside the `with` block, or use `session.expunge(record)` before exiting.

### CRIT-4: API Key Pepper Evaluated at Module Import Time

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/auth/api_key_auth.py:20-24`
**Severity:** Critical (Security)

The `_API_KEY_PEPPER` is read from the environment at module import time (line 20). If the pepper environment variable is set *after* the module is imported (e.g., via `.env` file loading in application startup), all API key hashes will use plain SHA-256 instead of HMAC-SHA256, silently degrading security:

```python
_API_KEY_PEPPER = os.environ.get("TEMPER_API_KEY_PEPPER", "")  # Module-level!
```

**Recommendation:** Read the pepper lazily inside `hash_api_key()`, or provide a `configure()` function called explicitly during app startup.

---

## High Findings (P1)

### HIGH-1: Missing Tenant Isolation in list_api_keys

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/interfaces/server/auth_routes.py:207-231`
**Severity:** High (Security)

The `list_api_keys` endpoint filters only by `user_id`, not by `tenant_id`:

```python
keys = session.exec(
    select(APIKey).where(col(APIKey.user_id) == ctx.user_id)
).all()
```

If a user belongs to multiple tenants (future scenario), this would leak API keys from other tenants. The `revoke_api_key` endpoint (line 233-249) also only checks `user_id`, not `tenant_id`.

**Recommendation:** Add `.where(col(APIKey.tenant_id) == ctx.tenant_id)` to both queries.

### HIGH-2: WebSocket Ticket Store Uses Global Mutable State

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/auth/ws_tickets.py:24-25`
**Severity:** High (Reliability)

The ticket store uses module-level mutable globals:

```python
_store: dict[str, _TicketEntry] = {}
_lock = threading.Lock()
```

This creates several issues:
- Not compatible with multi-process deployments (gunicorn with workers)
- No automatic cleanup of expired tickets (the `cleanup_expired()` function exists but is never called automatically)
- The store grows unboundedly if tickets are generated but never validated

**Recommendation:** Add an automatic cleanup mechanism (e.g., clean up during `generate_ws_ticket` when store exceeds a threshold). For production, use Redis or the DB.

### HIGH-3: No Per-User Session Limit Enforcement

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/auth/session.py:99-155`
**Severity:** High (Security)

The `InMemorySessionStore` has a global `MAX_SESSIONS` limit (10,000) with LRU eviction, but no per-user session limit. The constant `DEFAULT_MAX_SESSIONS_PER_USER = 5` is defined in `constants.py` (line 17) but is never used anywhere. An attacker with valid credentials could create thousands of sessions, evicting other users' sessions.

**Recommendation:** Implement per-user session counting in `create_session`. Track `user_id -> set[session_id]` and enforce the `DEFAULT_MAX_SESSIONS_PER_USER` limit.

### HIGH-4: Broad Exception Catch in Pydantic Validation

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/auth/config_sync.py:62-68`
**Severity:** High (Code Quality)

```python
def _validate_with_pydantic(config_type: str, data: dict[str, Any]) -> None:
    model_cls = _get_pydantic_model(config_type)
    try:
        model_cls.model_validate(data)
    except Exception as exc:  # TOO BROAD
        raise ValueError(f"Config validation failed: {exc}") from exc
```

The `except Exception` catches everything including `KeyboardInterrupt` subclasses in some contexts, `SystemExit`, etc. This should catch `ValidationError` specifically.

**Recommendation:** `except (ValidationError, ValueError, TypeError) as exc:`

### HIGH-5: Email Case Sensitivity Inconsistency

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/auth/session.py:264-277` and `/home/shinelay/meta-autonomous-framework/temper_ai/interfaces/server/auth_routes.py:165`
**Severity:** High (Data Integrity)

The signup endpoint normalizes email to lowercase (line 165: `email = body.email.strip().lower()`), but `UserStore.get_user_by_email` performs a case-sensitive lookup (confirmed by test at `test_session.py:604-605`). The OAuth flow in `routes.py` uses `user_info["email"]` directly from the provider without normalization. This means the same user could appear as two different accounts depending on how the email is cased by the OAuth provider.

**Recommendation:** Normalize email to lowercase consistently in all code paths: UserStore, OAuth callback, and DB queries.

---

## Moderate Findings (P2)

### MOD-1: Zero Test Coverage for ws_tickets Module

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/auth/ws_tickets.py`
**Severity:** Moderate (Testing)

No test file exists for `ws_tickets.py`. The grep across all test files confirmed zero references to `ws_ticket`, `generate_ws_ticket`, or `validate_ws_ticket`. This module handles security-sensitive ticket validation and expiry logic.

**Recommendation:** Add tests covering: ticket generation, single-use consumption, expiry, cleanup, concurrent access, and empty/malformed ticket validation.

### MOD-2: Zero Test Coverage for config_seed Module

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/auth/config_seed.py`
**Severity:** Moderate (Testing)

No test file exists for `config_seed.py`. The `seed_configs` function reads arbitrary YAML files from the filesystem and imports them to the DB. Without tests, directory traversal, file encoding issues, and error accumulation go unvalidated.

**Recommendation:** Add tests covering: successful seeding, missing directories, invalid YAML files, permission errors, and error aggregation.

### MOD-3: Rate Limiter in auth_routes Uses Module-Level Global

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/interfaces/server/auth_routes.py:43`
**Severity:** Moderate (Reliability)

```python
_rate_limit_store: dict[str, list[float]] = defaultdict(list)
```

This module-level dict is never cleaned up. Over time, IP addresses accumulate entries that are pruned per-key on access, but keys that are never accessed again persist indefinitely.

**Recommendation:** Add periodic cleanup (e.g., a background task or maximum store size with eviction).

### MOD-4: UserStore Returns Mutable User Objects

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/auth/session.py:251-362`
**Severity:** Moderate (Data Integrity)

`UserStore.get_user_by_id/email/oauth` returns references to the stored `User` objects, not copies. Callers can mutate the returned user and affect other callers. The `User` dataclass is not frozen.

**Recommendation:** Either make `User` a frozen dataclass (like `AuthContext`) or return copies.

### MOD-5: OAuth State Store Stores Timestamps as ISO Strings

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/auth/oauth/state_store.py:130-136`
**Severity:** Moderate (Performance)

The `InMemoryStateStore` stores `expires_at` as an ISO 8601 string, then parses it back to a datetime on every `get_state` call. This is unnecessarily slow for an in-memory store.

**Recommendation:** Store `datetime` objects directly to avoid repeated string parsing.

### MOD-6: f-string Logging Patterns

**Files:** Multiple files throughout `temper_ai/auth/`
**Severity:** Moderate (Performance)

The codebase uses f-string formatting in logger calls throughout:

- `/home/shinelay/meta-autonomous-framework/temper_ai/auth/session.py:145-153` (5 instances)
- `/home/shinelay/meta-autonomous-framework/temper_ai/auth/routes.py:256-388` (8+ instances)
- `/home/shinelay/meta-autonomous-framework/temper_ai/auth/oauth/_service_helpers.py:160-196` (6+ instances)
- `/home/shinelay/meta-autonomous-framework/temper_ai/auth/oauth/rate_limiter.py:114-131` (4 instances)

Example: `logger.info(f"Session created: session_id={session_id[:16]}...")`

This evaluates the f-string even when the log level is disabled. Using `logger.info("Session created: session_id=%s...", session_id[:16])` is the recommended pattern.

### MOD-7: Broad Exception Catch in Token Revocation

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/auth/routes.py:503`
**Severity:** Moderate (Code Quality)

```python
except Exception as e:  # Cleanup: must not fail
    logger.warning(f"Token revocation failed (continuing with logout): {e}")
```

The comment justifies the broad catch for logout resilience, which is acceptable, but this should at minimum be `except (httpx.HTTPError, OAuthError, KeyError, ValueError, AttributeError)` to be explicit about expected failure modes.

### MOD-8: `__init__.py` Does Not Export M10 Components

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/auth/__init__.py`
**Severity:** Moderate (Modularity)

The `__init__.py` only exports `User`, `Session`, `SessionStoreProtocol`, `InMemorySessionStore`, and `OAuthRouteHandlers`. It does not export any M10 components (`AuthContext`, `require_auth`, `require_role`, `hash_api_key`, `generate_api_key`). While direct imports work, the `__all__` is stale and misleading.

**Recommendation:** Update `__all__` to include M10 public API surface.

---

## Low Findings (P3)

### LOW-1: Duplicate `resolve_value` Inner Function

**Files:** `/home/shinelay/meta-autonomous-framework/temper_ai/auth/oauth/config.py:116-135` and `:256-274`
**Severity:** Low (Code Quality)

The `resolve_value` inner function is defined identically in both `OAuthProviderConfig.resolve_env_references()` and `OAuthConfig.resolve_env_references()`. This is a DRY violation.

**Recommendation:** Extract to a module-level `_resolve_env_value(value: str, context: str) -> str` function.

### LOW-2: `SessionStore` Backward Compatibility Alias

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/auth/session.py:366`
**Severity:** Low (Code Quality)

```python
SessionStore = InMemorySessionStore
```

This alias is used in `routes.py:38` (`from temper_ai.auth.session import SessionStore`). It creates naming confusion -- the alias makes it look like a generic store when it is specifically in-memory.

### LOW-3: Hardcoded `"/dashboard"` in `_build_session_response`

**File:** `/home/shinelay/meta-autonomous-framework/temper_ai/auth/routes.py:376-378`
**Severity:** Low (Code Quality)

```python
redirect_url = "/dashboard"
if not self._validate_redirect_url(redirect_url):
    redirect_url = "/dashboard"
```

The fallback is identical to the initial value, making the validation check a no-op.

### LOW-4: `KEYRING_AVAILABLE` and `KeyringError` Duplicated

**Files:** `/home/shinelay/meta-autonomous-framework/temper_ai/auth/oauth/_token_store_helpers.py:17-23` and `/home/shinelay/meta-autonomous-framework/temper_ai/auth/oauth/token_store.py:39-45`
**Severity:** Low (Code Quality)

The optional keyring import with fallback is duplicated in both files. The `token_store.py` imports from `_token_store_helpers.py` but also re-imports keyring independently.

---

## Architecture Assessment

### Strengths

1. **Two-layer auth design:** OAuth for UI sessions + API keys for programmatic access is the right pattern for this system.
2. **Secure defaults:** PKCE for OAuth, CSRF state tokens, HttpOnly/Secure/SameSite cookies, Fernet encryption for token storage, rate limiting at multiple tiers.
3. **Protocol-based abstractions:** `SessionStoreProtocol` (ABC) and `StateStore` (ABC) enable pluggable backends.
4. **Constants centralization:** `constants.py` properly extracts field names, route paths, and configuration values.
5. **Clean helper extraction:** `_service_helpers.py` and `_token_store_helpers.py` keep main classes under 500 lines.
6. **Callback URL validation:** `CallbackURLValidator` implements comprehensive defense-in-depth with scheme, hostname, HTTPS, localhost, query param, and fragment checks.

### Gaps vs. Vision Pillars

| Pillar | Assessment |
|---|---|
| **Safety Through Composition** | Partially met. Auth middleware is composable via `Depends()`, but the two auth systems (OAuth sessions vs API keys) are not unified under a common abstraction. A request can be authenticated via either mechanism but there is no single `AuthMiddleware` that handles both. |
| **Progressive Autonomy** | Not directly applicable to auth, but the API key RBAC model (owner/editor/viewer) provides the permission scaffolding needed for autonomy-level gating. |
| **Multi-Tenant Isolation** | Mostly met via `tenant_scope.py` helpers. However, several endpoints in `auth_routes.py` bypass these helpers and query by `user_id` only (HIGH-1). |

---

## Test Coverage Assessment

| Source File | Test File(s) | Coverage | Verdict |
|---|---|---|---|
| `api_key_auth.py` | `test_api_key_auth.py` (22 tests) | High | Good: covers generate, hash, extract, require_auth, require_role, ws_token |
| `tenant_scope.py` | `test_tenant_scope.py` (8 tests) | High | Good: covers all 3 functions with edge cases |
| `config_sync.py` | `test_config_sync.py` (11 tests) | High | Good: covers import, export, list, validation errors |
| `auth_routes.py` (server) | `test_auth_routes.py` (9 tests) | Medium | Missing: rate limiting, ws-ticket endpoint, tenant slug edge cases |
| `session.py` | `test_session.py` (25+ tests) | High | Excellent: LRU, cleanup, concurrent, security scenarios |
| `routes.py` (OAuth) | `test_routes.py` (not fully reviewed) | Medium | OAuth callback flow tested but not exhaustively |
| `ws_tickets.py` | **NONE** | **Zero** | No tests at all |
| `config_seed.py` | **NONE** | **Zero** | No tests at all |
| `oauth/config.py` | `test_oauth/test_config.py` | Medium | Provider validation, env resolution |
| `oauth/rate_limiter.py` | `test_oauth/test_rate_limiter.py` | High | Multi-tier limits, cleanup |
| `oauth/state_store.py` | `oauth/test_state_store.py` + `test_state_store*.py` | High | TTL, one-time use, eviction |
| `oauth/token_store.py` | `test_token_store.py` + `oauth/test_token_store.py` | High | Encryption, rotation, audit |
| `oauth/callback_validator.py` | `oauth/test_callback_validator.py` + `test_callback_validator.py` | High | Scheme, localhost, whitelist |
| `oauth/_service_helpers.py` | `test_oauth/test__service_helpers.py` | Medium | Token exchange helpers |
| `oauth/service.py` | `test_oauth_service.py` + `test_oauth/test_service.py` | Medium | Core flows |
| `models.py` | `test_models.py` | Low-Medium | Serialization round-trip |
| `constants.py` | `test_constants.py` | Low | Value checks only |

**Missing Test Scenarios:**
- Timing attack resistance on `require_auth` (beyond the basic check in `test_session.py`)
- Concurrent API key creation race conditions
- API key pepper rotation (what happens when pepper changes mid-flight)
- Expired ticket cleanup under load
- `config_seed` with malformed YAML files, missing directories, permission errors

---

## Recommendations Summary

### Immediate (Before Release)

| # | Finding | Fix |
|---|---|---|
| CRIT-2 | Sync DB in async function | Wrap `_lookup_api_key` internals in `asyncio.to_thread()` |
| CRIT-3 | Detached ORM access | Move data extraction inside `with get_session()` blocks in `export_config` and `list_configs` |
| CRIT-4 | Module-level pepper | Read `TEMPER_API_KEY_PEPPER` lazily in `hash_api_key()` |
| HIGH-1 | Missing tenant_id filter | Add `.where(col(APIKey.tenant_id) == ctx.tenant_id)` to list and revoke endpoints |

### Short-term (Next Sprint)

| # | Finding | Fix |
|---|---|---|
| CRIT-1 | Timing attack | Equalize all error-path timings in `require_auth` |
| HIGH-2 | WS ticket cleanup | Add auto-cleanup in `generate_ws_ticket` when store > threshold |
| HIGH-3 | Per-user session limit | Enforce `DEFAULT_MAX_SESSIONS_PER_USER` in `create_session` |
| HIGH-4 | Broad exception | Narrow to `except (ValidationError, ValueError, TypeError)` |
| HIGH-5 | Email normalization | Normalize to lowercase in UserStore and OAuth callback |
| MOD-1 | ws_tickets tests | Add comprehensive test suite |
| MOD-2 | config_seed tests | Add comprehensive test suite |

### Medium-term (Next Milestone)

| # | Finding | Fix |
|---|---|---|
| MOD-3 | Rate limiter cleanup | Background task or bounded store for `_rate_limit_store` |
| MOD-4 | Mutable User objects | Make `User` a frozen dataclass |
| MOD-5 | ISO string timestamps | Store datetime objects directly in state store |
| MOD-6 | f-string logging | Convert to `%s`-style formatting across auth module |
| MOD-8 | Stale `__init__.py` | Update `__all__` with M10 exports |

---

## File Inventory

| File | Lines | Purpose |
|---|---|---|
| `__init__.py` | 19 | Module exports (stale) |
| `api_key_auth.py` | 231 | API key auth: hash, generate, require_auth, require_role |
| `tenant_scope.py` | 80 | Tenant-scoped query helpers |
| `config_sync.py` | 181 | Import/export/list configs (YAML to DB) |
| `config_seed.py` | 92 | CLI helper to seed configs from filesystem |
| `constants.py` | 107 | Centralized auth constants |
| `models.py` | 141 | User and Session data models |
| `session.py` | 367 | Session store (in-memory with LRU) + UserStore |
| `ws_tickets.py` | 56 | Short-lived WebSocket ticket store |
| `routes.py` | 546 | OAuth route handlers (login, callback, logout) |
| `oauth/__init__.py` | 44 | OAuth submodule exports |
| `oauth/service.py` | 286 | OAuth service (PKCE, token exchange, refresh) |
| `oauth/_service_helpers.py` | 678 | Extracted OAuth service logic |
| `oauth/config.py` | 392 | OAuth configuration with env var resolution |
| `oauth/callback_validator.py` | 207 | Callback URL whitelist validator |
| `oauth/rate_limiter.py` | 317 | Multi-tier sliding window rate limiter |
| `oauth/state_store.py` | 220 | OAuth state storage (CSRF tokens) |
| `oauth/_token_store_helpers.py` | 282 | Token encryption/rotation helpers |
| `oauth/token_store.py` | 385 | Fernet-encrypted token store with keyring |
| **Total** | **~4,231** | |
