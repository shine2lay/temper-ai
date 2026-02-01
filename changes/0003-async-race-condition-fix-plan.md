# Implementation Plan: Fix Async Client Race Conditions

## Summary

**Status:** IN PROGRESS (paused due to token budget)
**Task:** code-crit-async-race-04
**Issue:** Race conditions in async HTTP client cleanup causing connection leaks
**Priority:** CRITICAL (P0)

## Problem Analysis

### Current Race Conditions Identified

The specialists (backend-engineer: a7be498, SRE: a516eb7) identified multiple critical issues:

#### 1. Fire-and-Forget Task (Line 249)
```python
loop.create_task(self._async_client.aclose())  # Orphaned task!
self._async_client = None  # Set before task completes
```
**Impact:** Connection not actually closed when code thinks it is.

#### 2. No Synchronization (Lines 232-284)
```python
# close() and aclose() have no locks
def close(self):
    if self._client is not None:  # Check
        self._client.close()       # Race window!
        self._client = None        # Set

async def aclose(self):
    if self._async_client is not None:  # Check
        await self._async_client.aclose()  # Race window!
        self._async_client = None          # Set
```
**Impact:** Time-of-check-to-time-of-use (TOCTOU) race - double close crashes.

#### 3. No Idempotency Flag
**Impact:** Can't safely call close() multiple times.

#### 4. Dangerous Finalizer (Lines 308-309)
```python
def __del__(self):
    asyncio.run(self._async_client.aclose())  # Can deadlock!
```
**Impact:** May crash during garbage collection.

## Proposed Solution

### Core Fix (This Task)

Implement proper async context manager with:
1. ✅ Async cleanup lock (`asyncio.Lock`) - Lazy initialized
2. ✅ Sync cleanup lock (`threading.Lock`) - For sync `close()`
3. ✅ Idempotency flag (`self._closed`) - Prevent double cleanup
4. ✅ Minimal finalizer - Warn only, don't cleanup
5. ✅ Remove `create_task()` - Wait for cleanup to complete

### Follow-On Tasks (Based on Specialist Recommendations)

#### Task 1: Request Tracking (HIGH - P1)
**Issue:** Closing client while requests are in-flight causes crashes
**Fix:** Add `_request_count` atomic counter, wait for requests before cleanup
**Estimated Effort:** 4 hours
**Files:** `src/agents/llm_providers.py`, `tests/agents/test_llm_cleanup.py`

#### Task 2: Resource Leak Monitoring (MEDIUM - P2)
**Issue:** No production visibility into leaks
**Fix:** Implement LLMLeakDetector, FileDescriptorMonitor, Prometheus metrics
**Estimated Effort:** 8 hours
**Files:** `src/observability/llm_leak_detector.py`, `src/observability/fd_monitor.py`

#### Task 3: Alerting and Runbooks (MEDIUM - P2)
**Issue:** No alerts for resource exhaustion
**Fix:** Prometheus alerts, PagerDuty routing, incident runbooks
**Estimated Effort:** 4 hours
**Files:** `alerts/llm_resource_leaks.yml`, `docs/runbooks/llm-fd-exhaustion.md`

#### Task 4: Load Testing (MEDIUM - P2)
**Issue:** No automated leak detection in CI/CD
**Fix:** Load tests for 1000+ concurrent clients, FD monitoring
**Estimated Effort:** 6 hours
**Files:** `tests/test_load/test_llm_resource_leaks.py`

#### Task 5: Circuit Breaker Integration (LOW - P3)
**Issue:** No graceful degradation on resource exhaustion
**Fix:** Circuit breaker opens at 80% FD usage
**Estimated Effort:** 4 hours
**Files:** `src/agents/llm_circuit_breaker_config.py`

## Implementation Steps for Core Fix

### Step 1: Add Cleanup Coordination Fields

```python
class BaseLLM(ABC):
    def __init__(self, ...):
        # ... existing fields ...

        # Cleanup coordination (NEW)
        self._closed = False
        self._sync_cleanup_lock = threading.Lock()
        self._async_cleanup_lock: Optional[asyncio.Lock] = None  # Lazy init
```

### Step 2: Implement Thread-Safe `aclose()`

```python
async def aclose(self) -> None:
    """Primary cleanup path - idempotent and thread-safe."""
    # Lazy init async lock (can't create in __init__ without event loop)
    if self._async_cleanup_lock is None:
        self._async_cleanup_lock = asyncio.Lock()

    async with self._async_cleanup_lock:
        if self._closed:
            return  # Idempotent

        try:
            if self._client is not None:
                self._client.close()
            if self._async_client is not None:
                await self._async_client.aclose()
        except Exception as e:
            logger.error(f"Error during cleanup: {e}", exc_info=True)
        finally:
            self._client = None
            self._async_client = None
            self._closed = True
```

### Step 3: Fix Sync `close()`

```python
def close(self) -> None:
    """Sync cleanup - uses existing event loop or creates new one."""
    with self._sync_cleanup_lock:
        if self._closed:
            return  # Idempotent

        try:
            # Check if event loop is running
            loop = asyncio.get_running_loop()
            raise RuntimeError(
                "Cannot call sync close() from async context. "
                "Use await aclose() instead."
            )
        except RuntimeError:
            # No running loop - safe to create new one
            asyncio.run(self.aclose())
```

### Step 4: Minimal Finalizer

```python
def __del__(self) -> None:
    """Warn about improper cleanup - DO NOT attempt cleanup."""
    if not self._closed and (self._client or self._async_client):
        import warnings
        warnings.warn(
            f"{self.__class__.__name__} was not properly closed. "
            f"Use 'async with' or 'with' context manager to avoid resource leaks.",
            ResourceWarning,
            stacklevel=2
        )
    # DO NOT attempt cleanup - too risky in finalizer
```

## Files to Modify

### Primary Implementation
- `/home/shinelay/meta-autonomous-framework/src/agents/llm_providers.py`
  - Lines 232-347: Fix `close()`, `aclose()`, `__del__`
  - Add `__init__` cleanup fields
  - Update docstrings

### Testing
- `/home/shinelay/meta-autonomous-framework/tests/agents/test_llm_cleanup.py` (create)
  - Test context manager cleanup
  - Test concurrent `aclose()` safety
  - Test idempotency
  - Test cleanup on exceptions

### Documentation
- `/home/shinelay/meta-autonomous-framework/changes/0003-async-race-fix.md`
  - Document race conditions fixed
  - Migration guide for users
  - Reference specialist reports

## Success Criteria

- [ ] No concurrent `close()`/`aclose()` races
- [ ] Idempotent cleanup (safe to call multiple times)
- [ ] Context managers guarantee cleanup
- [ ] Minimal finalizer (warn only)
- [ ] All tests pass
- [ ] No connection leaks in load tests

## Specialist Consultation Summary

### Backend Engineer (Agent a7be498)

**Key Findings:**
1. Identified 4 race conditions in current code
2. Recommended dual locks (sync + async)
3. Emphasized minimal finalizer (no async in `__del__`)
4. Proposed request tracking for in-flight safety

**Critical Recommendations:**
- Use `asyncio.Lock()` lazy initialization (no event loop in `__init__`)
- Track in-flight requests before cleanup
- Timeout on cleanup (don't hang forever)
- Make `aclose()` the primary cleanup path

### SRE (Agent a516eb7)

**Key Findings:**
1. Designed comprehensive observability strategy
2. Proposed LLMLeakDetector for runtime detection
3. Created runbooks for incident response
4. Specified Prometheus metrics and alerts

**Critical Recommendations:**
- File descriptor monitoring (llm_file_descriptors_used)
- Leak detector with weak references
- Circuit breaker at 80% FD usage
- Load tests for 1000+ concurrent clients

## Next Actions

1. **Resume Implementation:**
   - Implement Step 1-4 above
   - Add comprehensive error logging
   - Update tests

2. **Create Follow-On Tasks:**
   - `code-high-request-tracking`: Add in-flight request safety
   - `code-med-leak-monitoring`: Implement observability
   - `code-med-load-testing`: Add leak detection tests
   - `ops-runbooks`: Create incident response docs

3. **Validate Fix:**
   - Run existing tests
   - Manual testing with concurrent clients
   - Verify no FD leaks with `lsof`

## References

- Task Specification: `.claude-coord/task-specs/code-crit-async-race-04.md`
- Backend Engineer Report: Agent a7be498
- SRE Report: Agent a516eb7
- Current Code: `src/agents/llm_providers.py:232-347`

---

**Current Status:** Paused for token budget management
**Next Session:** Resume at Step 1 implementation
**Lock Status:** File `src/agents/llm_providers.py` is locked by agent-312b49
