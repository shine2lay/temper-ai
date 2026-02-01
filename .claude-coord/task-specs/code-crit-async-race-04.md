# Task Specification: code-crit-async-race-04

## Problem Statement

Async client cleanup in `AnthropicLLM.close()` has race conditions that can cause connection leaks, leading to "Too many open files" errors. Under concurrent load, the async HTTP client may not be properly cleaned up, causing resource exhaustion and potential data corruption.

This is a critical reliability issue that can cause production outages.

## Context

- **Source:** Code Review Report 2026-02-01 (Critical Issue #4)
- **File Affected:** `src/agents/llm_providers.py:232-275`
- **Impact:** Resource exhaustion, connection leaks, production instability
- **Module:** Agents
- **Related:** Async context manager pattern

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Implement proper async context manager (`__aenter__`, `__aexit__`)
- [ ] Ensure client cleanup is atomic and race-free
- [ ] Support both context manager and manual cleanup
- [ ] Handle cleanup errors gracefully

### RELIABILITY
- [ ] No connection leaks under concurrent load
- [ ] Proper cleanup even when exceptions occur
- [ ] No "too many open files" errors
- [ ] Idempotent cleanup (safe to call close() multiple times)

### BACKWARD COMPATIBILITY
- [ ] Existing code continues to work
- [ ] Manual close() still supported
- [ ] Add deprecation warning for manual cleanup (encourage context manager)

### TESTING
- [ ] Test context manager cleanup
- [ ] Test concurrent client usage
- [ ] Test cleanup under exceptions
- [ ] Test resource leak detection
- [ ] Load testing to verify no leaks

## Implementation Plan

### Step 1: Read Current Implementation

**File:** `src/agents/llm_providers.py:232-275`

```bash
grep -A 50 "class AnthropicLLM" src/agents/llm_providers.py
```

Understand current cleanup logic and race condition.

### Step 2: Implement Async Context Manager

**File:** `src/agents/llm_providers.py`

**Before:**
```python
class AnthropicLLM:
    def __init__(self, api_key: str):
        self._client = httpx.AsyncClient()

    async def close(self):
        # Race condition: concurrent close() calls can interfere
        await self._client.aclose()
```

**After:**
```python
import asyncio
from contextlib import asynccontextmanager

class AnthropicLLM:
    def __init__(self, api_key: str):
        self._client = httpx.AsyncClient()
        self._closed = False
        self._cleanup_lock = asyncio.Lock()

    async def __aenter__(self):
        """Async context manager entry"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - guarantees cleanup"""
        await self.aclose()
        return False  # Don't suppress exceptions

    async def aclose(self):
        """Thread-safe async cleanup"""
        async with self._cleanup_lock:
            if self._closed:
                return  # Already closed, idempotent

            try:
                if self._client:
                    await self._client.aclose()
            except Exception as e:
                # Log but don't raise - cleanup should be robust
                import logging
                logging.error(f"Error closing HTTP client: {e}")
            finally:
                self._closed = True
                self._client = None

    async def close(self):
        """Deprecated: Use aclose() or context manager instead"""
        import warnings
        warnings.warn(
            "close() is deprecated, use aclose() or async with",
            DeprecationWarning,
            stacklevel=2
        )
        await self.aclose()

    def __del__(self):
        """Fallback cleanup if context manager not used"""
        if not self._closed and self._client:
            import warnings
            warnings.warn(
                "AnthropicLLM not properly closed. Use async with or await aclose()",
                ResourceWarning,
                stacklevel=2
            )
```

### Step 3: Update Usage Pattern

**File:** Usage examples in docs and existing code

**Old pattern:**
```python
llm = AnthropicLLM(api_key="...")
try:
    response = await llm.call(prompt)
finally:
    await llm.close()
```

**New pattern (recommended):**
```python
async with AnthropicLLM(api_key="...") as llm:
    response = await llm.call(prompt)
# Automatic cleanup, even on exceptions
```

### Step 4: Find and Update All Usage Sites

```bash
grep -r "AnthropicLLM(" src/
grep -r "\.close()" src/agents/
```

Update to use context manager pattern where possible.

### Step 5: Add Resource Tracking (Optional)

For debugging leaks:
```python
_active_clients = set()

class AnthropicLLM:
    def __init__(self, api_key: str):
        # ... existing init ...
        _active_clients.add(id(self))

    async def aclose(self):
        async with self._cleanup_lock:
            # ... existing cleanup ...
            _active_clients.discard(id(self))

# Debug helper
def get_active_client_count():
    return len(_active_clients)
```

## Test Strategy

### Unit Tests

**File:** `tests/agents/test_llm_cleanup.py`

```python
import pytest
import asyncio
from src.agents.llm_providers import AnthropicLLM

@pytest.mark.asyncio
async def test_context_manager_cleanup():
    """Test that context manager properly cleans up resources"""
    async with AnthropicLLM(api_key="test") as llm:
        assert llm._client is not None
        assert not llm._closed

    # After context exit, should be closed
    assert llm._closed
    assert llm._client is None

@pytest.mark.asyncio
async def test_cleanup_on_exception():
    """Test cleanup happens even when exception occurs"""
    try:
        async with AnthropicLLM(api_key="test") as llm:
            raise ValueError("Test error")
    except ValueError:
        pass

    # Should still be cleaned up
    assert llm._closed

@pytest.mark.asyncio
async def test_concurrent_close_is_safe():
    """Test that concurrent close() calls don't race"""
    llm = AnthropicLLM(api_key="test")

    # Attempt to close concurrently
    await asyncio.gather(
        llm.aclose(),
        llm.aclose(),
        llm.aclose(),
    )

    # Should be cleanly closed, no errors
    assert llm._closed

@pytest.mark.asyncio
async def test_idempotent_close():
    """Test that calling close() multiple times is safe"""
    llm = AnthropicLLM(api_key="test")

    await llm.aclose()
    assert llm._closed

    # Closing again should be safe
    await llm.aclose()
    assert llm._closed

@pytest.mark.asyncio
async def test_manual_close_shows_deprecation():
    """Test that old close() method shows deprecation warning"""
    llm = AnthropicLLM(api_key="test")

    with pytest.warns(DeprecationWarning, match="deprecated"):
        await llm.close()
```

### Load Tests

**File:** `tests/agents/test_llm_resource_leaks.py`

```python
import pytest
import asyncio
import psutil
import os

@pytest.mark.asyncio
async def test_no_connection_leaks_under_load():
    """Test that high concurrency doesn't leak connections"""
    process = psutil.Process(os.getpid())
    initial_fds = process.num_fds()

    # Create and close 1000 clients
    async def create_and_close():
        async with AnthropicLLM(api_key="test") as llm:
            await asyncio.sleep(0.01)  # Simulate work

    await asyncio.gather(*[create_and_close() for _ in range(1000)])

    # File descriptors should return to baseline (within tolerance)
    final_fds = process.num_fds()
    assert final_fds <= initial_fds + 10, f"Leaked {final_fds - initial_fds} file descriptors"

@pytest.mark.asyncio
async def test_concurrent_client_usage():
    """Test multiple clients can be used concurrently"""
    async def use_client(client_id):
        async with AnthropicLLM(api_key="test") as llm:
            # Simulate API call
            await asyncio.sleep(0.01)
            return client_id

    results = await asyncio.gather(*[use_client(i) for i in range(100)])
    assert len(results) == 100
```

## Error Handling

**Scenarios:**
1. Client already closed → Return silently (idempotent)
2. Exception during cleanup → Log error but mark as closed
3. Concurrent close calls → Use lock to serialize
4. Context manager exception → Cleanup still happens

## Success Metrics

- [ ] No connection leaks in load testing (1000+ clients)
- [ ] File descriptor count returns to baseline
- [ ] All cleanup is idempotent
- [ ] Concurrent cleanup is race-free
- [ ] All tests pass
- [ ] Zero "too many open files" errors in production

## Dependencies

**Blocked by:** None

**Blocks:** None (can be done in parallel)

**Requires:** `httpx`, `asyncio` (already in use)

## References

- Code Review Report: `.claude-coord/reports/code-review-20260201-002732.md` (lines 110-131)
- Python Async Context Managers: https://docs.python.org/3/reference/datamodel.html#async-context-managers
- Resource Management Best Practices

## Estimated Effort

**Time:** 3-4 hours
**Complexity:** Medium (async patterns require careful testing)

---

*Priority: CRITICAL (0)*
*Category: Reliability & Resource Management*
