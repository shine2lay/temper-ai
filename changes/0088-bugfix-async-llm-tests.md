# Change Log 0088: Bugfix - Async LLM Test Mocks

**Date:** 2026-01-27
**Task:** bugfix-async-llm-tests
**Category:** Testing (Bugfix)
**Priority:** HIGH

---

## Summary

Fixed failing async LLM tests caused by incorrect mock setup. The `AsyncMock` was making `response.json()` async when it should be synchronous in httpx, causing `AttributeError: 'coroutine' object has no attribute 'get'` errors.

---

## Problem Statement

Two async LLM tests were failing:
- `test_acomplete_success`
- `test_acomplete_retry_on_timeout`

**Error:**
```
AttributeError: 'coroutine' object has no attribute 'get'
File: src/agents/llm_providers.py:651
Line: content=response.get("response", ""),
```

**Root Cause:**
Mock responses were created with `AsyncMock()`, which makes ALL methods async by default. When the code called `response.json()`, it returned a coroutine instead of the parsed JSON dictionary. The `_parse_response` method then tried to call `.get()` on a coroutine, causing the error.

**Why This Happened:**
In httpx, `response.json()` is a synchronous method that returns a dict. But `AsyncMock()` converts all methods to async coroutines. The mock setup needed to explicitly make `json` synchronous.

---

## Solution

Fixed the mock setup to use regular `Mock` for the `json` method instead of inheriting `AsyncMock` behavior.

**Before:**
```python
mock_response = AsyncMock()
mock_response.status_code = 200
mock_response.json.return_value = {
    "response": "Test response",
    "model": "llama3.2:3b",
    "done": True,
}
```

**After:**
```python
mock_response = AsyncMock()
mock_response.status_code = 200
# json() is synchronous in httpx, so use Mock not AsyncMock
mock_response.json = Mock(return_value={
    "response": "Test response",
    "model": "llama3.2:3b",
    "done": True,
})
```

---

## Changes Made

### 1. Fixed Fixture Mock

**File:** `tests/test_agents/test_llm_async.py`

**Line 40-51:** Fixed `mock_async_response` fixture
```python
@pytest.fixture
def mock_async_response():
    """Mock async HTTP response."""
    mock_response = AsyncMock()
    mock_response.status_code = 200
    # json() is synchronous in httpx, so use Mock not AsyncMock
    mock_response.json = Mock(return_value={
        "response": "Test response",
        "model": "llama3.2:3b",
        "done": True,
        "prompt_eval_count": 10,
        "eval_count": 20,
    })
    return mock_response
```

### 2. Fixed Inline Mock in Retry Test

**File:** `tests/test_agents/test_llm_async.py`

**Line 192-206:** Fixed inline mock in `test_acomplete_retry_on_timeout`
```python
async def mock_post(*args, **kwargs):
    nonlocal call_count
    call_count += 1
    if call_count < 3:
        raise httpx.TimeoutException("Timeout")

    mock_response = AsyncMock()
    mock_response.status_code = 200
    # json() is synchronous in httpx, so use Mock not AsyncMock
    mock_response.json = Mock(return_value={
        "response": "Success",
        "model": "llama3.2:3b",
        "done": True,
    })
    return mock_response
```

---

## Test Results

**Before Fix:**
```bash
$ pytest tests/test_agents/test_llm_async.py -v
FAILED tests/test_agents/test_llm_async.py::test_acomplete_success
FAILED tests/test_agents/test_llm_async.py::test_acomplete_retry_on_timeout
======================== 2 failed, 6 passed ========================
```

**After Fix:**
```bash
$ pytest tests/test_agents/test_llm_async.py -v
======================== 8 passed in 0.46s ========================
```

**All Tests Passing:**
```
✓ test_async_client_lazy_initialization
✓ test_async_context_manager
✓ test_acomplete_success
✓ test_parallel_execution
✓ test_acomplete_retry_on_timeout
✓ test_acomplete_timeout_error
✓ test_all_providers_have_async_methods
✓ test_async_performance_baseline
```

---

## Technical Details

### httpx Response API

In httpx (unlike aiohttp), the `Response.json()` method is **synchronous**:

```python
import httpx

response = httpx.get("https://api.example.com/data")
data = response.json()  # Synchronous call, returns dict
```

This is because httpx buffers the response body synchronously during the async request, so parsing it to JSON doesn't require another await.

### AsyncMock Behavior

`unittest.mock.AsyncMock` converts ALL attribute accesses into async operations by default:

```python
from unittest.mock import AsyncMock

mock = AsyncMock()
mock.method.return_value = "result"

# This creates a coroutine, not "result"
result = mock.method()  # <coroutine object>

# You must await it
result = await mock.method()  # "result"
```

### The Fix

To make a specific method synchronous on an AsyncMock, explicitly assign a regular Mock:

```python
from unittest.mock import AsyncMock, Mock

mock = AsyncMock()
# Make json() synchronous
mock.json = Mock(return_value={"key": "value"})

# Now it works like httpx
data = mock.json()  # {"key": "value"}, no await needed
```

---

## Lessons Learned

1. **AsyncMock makes everything async** - When using `AsyncMock()`, all methods become coroutines unless explicitly overridden.

2. **Know your library's async boundaries** - httpx uses async for requests but synchronous for response parsing. The mock needs to match this.

3. **Test mock behavior matches real behavior** - Mocks should mirror the actual library's API, including which methods are sync vs async.

4. **Read the error carefully** - "coroutine object has no attribute 'get'" immediately tells us an awaitable is being used where a dict is expected.

---

## Impact

**Before Fix:**
- 2 async LLM tests failing
- Async completion path untested
- Retry logic not validated
- Could miss real async bugs

**After Fix:**
- All 8 async LLM tests passing ✓
- Async completion path fully tested ✓
- Retry logic validated (3 attempts) ✓
- Timeout handling verified ✓
- Parallel execution tested ✓
- Performance baseline established ✓

---

## Files Modified

```
tests/test_agents/test_llm_async.py  [MODIFIED]  2 mock fixes
changes/0088-bugfix-async-llm-tests.md  [NEW]
```

---

## Verification

All async LLM tests now pass:
```bash
$ pytest tests/test_agents/test_llm_async.py -v
======================== 8 passed in 0.46s ========================
```

No other tests affected:
```bash
$ pytest tests/test_agents/ -v
======================== 70+ passed ========================
```

---

**Status:** ✅ COMPLETE

Bugfix applied and verified. All async LLM tests passing. Mock behavior now correctly matches httpx API.
