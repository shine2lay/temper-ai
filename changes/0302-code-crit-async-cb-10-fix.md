# code-crit-async-cb-10: Async Circuit Breaker Protection

## Problem
`BaseLLM.acomplete()` bypassed the circuit breaker entirely. While the sync
`complete()` method correctly wrapped API calls with `self._circuit_breaker.call()`,
the async path called `_make_async_api_call()` directly, meaning:

- Provider outages were not detected for async callers
- No fast-fail protection when providers were down
- Failure counts were not tracked for async requests
- Half-open recovery testing never triggered from async paths

## Fix

### 1. Added `async_call()` to `CircuitBreaker` (`src/llm/circuit_breaker.py`)
New method mirrors the sync `call()` but awaits the wrapped function:
- Reuses existing `_reserve_execution()` for atomic state check + reservation
- Reuses `_on_success()` / `_on_failure()` for state transitions
- Same semaphore-based thundering herd protection in HALF_OPEN state
- Same thread-safety guarantees (all state mutations hold the lock)

### 2. Wired `acomplete()` through circuit breaker (`src/agents/llm_providers.py`)
Changed from:
```python
return await _make_async_api_call()
```
To:
```python
return await self._circuit_breaker.async_call(_make_async_api_call)
```

## Testing
- 83 circuit breaker tests pass
- 185 LLM provider + circuit breaker tests pass (4 pre-existing failures unrelated)
- No regressions in broader test suite
