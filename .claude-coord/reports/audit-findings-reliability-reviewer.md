# Reliability & Resilience Audit Findings

**Reviewer:** reliability-reviewer
**Date:** 2026-02-07
**Scope:** All source modules under `src/`
**Focus:** Error handling, resilience patterns, resource management, concurrency safety, recovery
**Codebase:** Post-refactor (commit b97ddac)

---

## Findings Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 3 |
| HIGH     | 7 |
| MEDIUM   | 8 |
| LOW      | 2 |
| INFO     | 1 |
| **Total** | **21** |

---

## Findings Table

| # | Severity | Category | File:Line | Finding | Recommendation |
|---|----------|----------|-----------|---------|----------------|
| R-01 | CRITICAL | race-condition | `src/agents/llm/base.py:239-247` | **`_get_async_lock()` has a TOCTOU race on lazy `asyncio.Lock` creation.** If two coroutines call it concurrently before `_async_client_lock` is set, both see `None`, both create a new `asyncio.Lock`, and one overwrites the other. The loser's lock is never used, so its holder has no mutual exclusion -- two async clients can be created concurrently, leaking connections. | Use `cls.__dict__.setdefault()` with a module-level threading lock guard, or initialize `_async_client_lock` eagerly at class definition time (safe in Python 3.10+). |
| R-02 | CRITICAL | race-condition | `src/safety/approval.py:185-238` | **`ApprovalWorkflow._requests` is a plain `dict` with no thread synchronization.** `ToolExecutor._poll_approval()` calls `is_approved()`/`is_rejected()` from a background thread (the `_approval_executor` pool) while the main thread may call `approve()`/`reject()` concurrently. Dict mutation + reads without a lock is a data race. In CPython this is unlikely to corrupt due to the GIL, but it is undefined behavior under the Python memory model and will fail on free-threaded builds (PEP 703). **Blast radius:** all approval-gated tool executions across the system. | Add a `threading.Lock` to `ApprovalWorkflow` and acquire it for all `_requests` mutations and reads. Alternatively, use `concurrent.futures` primitives to notify the polling thread instead of polling. |
| R-03 | CRITICAL | resource-leak | `src/agents/llm/base.py:334-360,362-392` | **Async HTTP client leaked when only `close()` is called.** `_get_async_client()` (backward-compat sync accessor) creates an `httpx.AsyncClient` under `self._sync_cleanup_lock`. If `close()` is called without `aclose()`, the sync method sets `self._async_client = None` (line 388) but never calls `aclose()` on the client -- just drops the reference. The `__del__` only warns. In long-running processes (servers, daemons), async clients accumulate open connections and file descriptors. | (1) `close()` should attempt to schedule `_async_client.aclose()` on the running event loop if one exists, or at minimum log at WARNING. (2) Deprecate `_get_async_client()` in favor of `_get_async_client_safe()`. (3) Document that callers using async clients MUST use `aclose()` or the async context manager. |
| R-04 | HIGH | error-handling | `src/safety/approval.py:546-562` | **Approval callbacks silently swallow all exceptions.** Both `_trigger_approved_callbacks` and `_trigger_rejected_callbacks` catch `Exception` with bare `pass`. If the `ToolExecutor._handle_approval_rejection` callback fails during auto-rollback, the failure is completely invisible -- no log, no metric, no alert. This is a safety-critical path: a failed rollback-on-rejection means a rejected dangerous action's side effects persist. | Log callback errors at WARNING level: `logger.warning("Approval callback failed: %s", e, exc_info=True)`. |
| R-05 | HIGH | graceful-degradation | `src/compiler/executors/sequential.py:448` | **Retry backoff sleep is not interruptible by shutdown signals.** `_retry_agent_with_backoff()` creates a new `threading.Event()` on each call but the event is never set by any shutdown signal. The comment says the delay is "interruptible" but no mechanism exists to signal it. During graceful shutdown, retrying agents block for the full backoff delay (up to 30s per attempt times N retries). | Pass a shared shutdown event from the executor or workflow level. Set it from the signal handler registered in `src/cli/main.py`. |
| R-06 | HIGH | timeout | `src/tools/executor.py:605-641` | **`execute_batch()` has no overall timeout.** Each individual execution has a per-tool timeout, but `future.result()` is called with no timeout. If thread pool starvation prevents a tool from starting, the caller blocks indefinitely waiting for the future. | Add an `overall_timeout` parameter. Use `concurrent.futures.as_completed()` with a deadline or pass a per-future timeout to `future.result(timeout=...)`. |
| R-07 | HIGH | error-handling | `src/agents/standard_agent.py:684` | **Sync retry loop lacks jitter (thundering herd).** In `_execute_iteration()`, the sync retry uses `time.sleep(retry_delay * (2.0 ** attempt))` with pure exponential backoff but no jitter. The async path (line 500) correctly adds `(0.5 + random.random())`. Under concurrent retries from multiple agents hitting the same LLM endpoint, synchronized retries amplify the overload that caused the original failure. | Add jitter: `backoff_delay = retry_delay * (2.0 ** attempt) * (0.5 + random.random())` to match the async path. |
| R-08 | HIGH | resource-leak | `src/agents/standard_agent.py:66-78` | **Module-level thread pool with imperfect shutdown.** `_TOOL_EXECUTOR_POOL` is a module-level `ThreadPoolExecutor` with an `atexit` handler using `cancel_futures=True`. (1) `atexit` handlers are not called on `SIGKILL`, `os._exit()`, or interpreter crash. (2) In subprocess scenarios each process gets its own pool without cleanup. (3) `cancel_futures=True` requires Python 3.9+ with no version guard. | Consider lazy initialization with explicit lifecycle. Add a version check for `cancel_futures`. For subprocess safety, use `multiprocessing` cleanup hooks. |
| R-09 | HIGH | graceful-degradation | `src/observability/database.py:83-90` | **SQLite StaticPool with single connection shared across all threads.** Under concurrent writes (multiple agents writing observability data), SQLite raises `OperationalError: database is locked`. No retry logic exists for lock contention. A comment acknowledges "development-only" but no runtime guard prevents production use. | Add a startup warning if `StaticPool + SQLite` is detected with agent count > 1. Implement retry-on-lock for the session context manager. For production, PostgreSQL path already uses proper pooling. |
| R-10 | HIGH | timeout | `src/auth/oauth/service.py:122-128` | **OAuth HTTP client has no pool acquisition timeout.** `httpx.AsyncClient` with `max_connections=10` and no `pool` timeout. If all 10 connections are in use (e.g., slow identity provider), new token exchange requests block indefinitely waiting for a pool slot. | Configure explicit pool timeout: `httpx.Timeout(30.0, connect=5.0, pool=10.0)`. |
| R-11 | MEDIUM | error-handling | `src/auth/oauth/service.py:624` | **Token signature validation silently returns False for all exceptions.** `_validate_token_signature()` catches all exceptions and returns `False`. If the JWKS endpoint is misconfigured (wrong URL, network partition), all token validations silently fail, locking out all users. No distinction between "invalid signature" and "validation infrastructure broken". | Log at ERROR level for infrastructure failures (JWKS fetch, key parsing) vs INFO for signature mismatch. Consider a circuit breaker around the JWKS endpoint. |
| R-12 | MEDIUM | error-handling | `src/safety/rollback.py:883` | **Rollback listener callbacks silently swallowed.** `_notify_listeners()` catches exceptions with bare `pass`. Failed listener notifications leave downstream components unaware that a rollback occurred. | Log at WARNING level. Track failed notifications in `RollbackResult`. |
| R-13 | MEDIUM | circuit-breaker | `src/core/circuit_breaker.py:570-576` | **Half-open semaphore rejection does not increment `metrics.rejected_calls`.** In `_reserve_execution()`, when the HALF_OPEN semaphore acquisition fails, it raises `CircuitBreakerError` but skips the `rejected_calls` counter. Monitoring dashboards undercount rejections during recovery testing. | Add `self.metrics.rejected_calls += 1` (under lock) before the raise, consistent with the OPEN rejection path. |
| R-14 | MEDIUM | resource-leak | `src/tools/web_scraper.py:390-413` | **`WebScraper._client` (httpx.Client) cleaned up only in `__del__`.** Lazy initialization with no context manager or `weakref.finalize()`. If `__del__` is not called (circular references, interpreter shutdown), the client leaks connections. | Add `__enter__`/`__exit__` and `weakref.finalize()` for guaranteed cleanup, matching the `ToolExecutor` pattern. |
| R-15 | MEDIUM | recovery | `src/compiler/workflow_executor.py:167-281` | **No idempotency check on checkpoint resume.** `execute_with_checkpoints()` has no deduplication. If the same workflow ID is resumed concurrently (scheduler double-dispatch), duplicate work occurs. The `stage_outputs` check may not prevent this if two instances start simultaneously from the same checkpoint. | Add a checkpoint lock (file lock or DB advisory lock) keyed by workflow_id to prevent concurrent resume. |
| R-16 | MEDIUM | graceful-degradation | `src/observability/buffer.py:599-612` | **Daemon flush thread killed mid-flush on exit.** `ObservabilityBuffer._start_flush_thread()` starts a daemon thread. Without `stop()`, the daemon is killed mid-flush on process exit, losing buffered observability data. `stop()` only waits 5 seconds before continuing. | Register an `atexit` handler calling `stop()`. Log item count at risk if thread doesn't stop in time. |
| R-17 | MEDIUM | error-handling | `src/tools/executor.py:471-476` | **Outermost exception handler strips all diagnostic context.** Returns generic "Tool execution failed due to an internal error" with no error type or details. The calling agent cannot diagnose or recover. | Include sanitized error type: `f"Tool execution failed ({type(e).__name__}): {sanitize_error_message(str(e))}"`. |
| R-18 | MEDIUM | error-handling | `src/agents/agent_observer.py:21` | **Observer tracking methods suppress all exceptions.** If the observability backend is persistently down, every LLM/tool call generates a warning log with no circuit breaker or backoff. At high throughput this floods logs without triggering any alert. | Add a circuit breaker or exponential backoff around observability backend calls. After N consecutive failures, stop attempting for a cooldown period. |
| R-19 | MEDIUM | race-condition | `src/agents/llm/base.py:111,204-225` | **Shared HTTP client eviction can close client in use by another thread.** `_get_shared_http_client()` evicts the oldest client and calls `close()` on it. But another thread may hold a reference to that client from a prior call and be mid-request. The request fails with a closed-client error. | Pin client references per-instance (current non-shared path). For shared path, consider reference counting or copy-on-evict. |
| R-20 | LOW | retry | `src/agents/llm/base.py:564-596` | **Rate limit retries ignore `Retry-After` header.** The retry loop catches `LLMRateLimitError` and uses exponential backoff. Rate limit responses often include a `Retry-After` header with the server's preferred wait time. Ignoring this can retry too early (wasting the attempt) or wait too long. | Parse `Retry-After` from the rate limit response and use it as the minimum backoff delay. |
| R-21 | LOW | timeout | `src/agents/llm/base.py:127` | **Default LLM timeout is 600s (10 minutes).** A hung connection ties up a thread for 10 minutes. Combined with 5-failure circuit breaker threshold, this means up to 50 minutes of wasted time before the breaker opens for a completely dead endpoint. | Consider a lower default (e.g., 120s) with documentation that users should tune per-model. |
| INFO-01 | INFO | resilience | Multiple files | **Strong resilience patterns observed:** Circuit breaker with thundering-herd prevention (semaphore in HALF_OPEN), retry with exponential backoff and error type classification, configurable per-stage error policies, atomic file writes (tempfile + os.replace), resource cleanup via context managers and `weakref.finalize()`, observability buffer with DLQ and retry limits, token bucket with thorough input validation (NaN/Inf checks), swap-and-flush pattern for lock contention reduction. | Continue maintaining. Consider integration tests that verify the full error handling pipeline end-to-end. |

---

## Cross-Cutting Observations

### Positive Patterns
1. **Circuit breaker** is well-implemented with state persistence, thundering herd prevention via semaphore, error classification, and callback hooks.
2. **LLM provider cleanup** uses both `__del__` warnings and context managers -- solid dual-safety approach.
3. **Tool executor** uses `weakref.finalize()` for guaranteed thread pool cleanup -- correct modern Python pattern.
4. **Observability buffer** has dead-letter queue with bounded retries and max DLQ size -- mature data pipeline resilience.
5. **Checkpoint writes** use atomic write (tempfile + os.replace) preventing partial writes.
6. **Error type classification** in `sequential.py` distinguishes transient from permanent errors for retry decisions.
7. **Token bucket** has comprehensive input validation including NaN/Inf checks to prevent rate limit bypass.
8. **LRU eviction bounds** on circuit breakers, HTTP clients, sessions, and token buckets prevent unbounded growth.

### Systemic Concerns
1. **Async/Sync duality creates maintenance burden:** Multiple modules maintain parallel sync and async code paths (BaseLLM, StandardAgent, FailoverProvider) with subtly different error handling. The sync path lacks jitter on retries while the async path has it (R-07). This kind of drift is a reliability risk.
2. **Swallowed exceptions in safety-critical paths:** At least 6 locations in the safety subsystem (`approval.py`, `rollback.py`, `factory.py`) silently swallow exceptions. While the intent is to prevent cascading failures, the effect is that safety-critical failures become invisible.
3. **Thread safety assumptions rely on GIL:** Several data structures (`ApprovalWorkflow._requests`, `BaseLLM._async_client_lock`) lack proper synchronization, relying on CPython's GIL. These will break on free-threaded Python (PEP 703).
4. **Retry pattern fragmentation:** Retry logic is implemented in 5+ places with different patterns, jitter policies, and cap values. The `utils/error_handling.py` utility exists but is not consistently used.

---

## Top 3 Priorities for Remediation

1. **R-01 (CRITICAL)**: `_get_async_lock()` TOCTOU race on lazy asyncio.Lock creation -- can defeat mutual exclusion for async client creation, leaking connections. Fix: eager initialization at class level.
2. **R-02 (CRITICAL)**: `ApprovalWorkflow._requests` accessed without locks from background polling threads -- data race on safety-critical approval checks. Fix: add `threading.Lock`.
3. **R-03 (CRITICAL)**: Async HTTP client leaked when `close()` called without `aclose()` -- open connections and file descriptors accumulate in long-running processes. Fix: schedule async cleanup in `close()` or deprecate sync accessor.
