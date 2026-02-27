# Plan: Remove Dead SafetyGate and CircuitBreakerManager

## Problem

`temper_ai/safety/circuit_breaker.py` contains three classes — `SafetyGateBlocked`, `SafetyGate`, and `CircuitBreakerManager` — that are defined, exported, tested, but **never used in production code**.

These were a v1 safety design that combined circuit breakers with policy validation. They were fully superseded by `ActionPolicyEngine` which handles policy enforcement, caching, fail-closed semantics, async support, and observability without needing circuit breaker wrappers.

**Zero production references.** The only consumers are:
- `temper_ai/safety/__init__.py` (lazy exports, lines 103-108)
- `tests/test_safety/test_circuit_breaker.py` (test classes `TestSafetyGate`, `TestCircuitBreakerManager`)
- `tests/test_safety/test_m4_integration.py` (`TestSafetyGateCoordination` class and manager tests)

## Changes

### 1. Delete `temper_ai/safety/circuit_breaker.py`

Remove the entire file (320 lines). Contains:
- `SafetyGateBlocked` exception (line 28)
- `SafetyGate` class (lines 34-181)
- `CircuitBreakerManager` class (lines 184-319)

### 2. Remove exports from `temper_ai/safety/__init__.py`

Remove from the lazy-loading `_EXPORTS` dict (lines 102-108):
```python
"SafetyGate": ("temper_ai.safety.circuit_breaker", "SafetyGate"),
"SafetyGateBlocked": ("temper_ai.safety.circuit_breaker", "SafetyGateBlocked"),
"CircuitBreakerManager": (
    "temper_ai.safety.circuit_breaker",
    "CircuitBreakerManager",
),
```

Remove from `__all__` list (lines 203-205):
```python
"SafetyGate",
"SafetyGateBlocked",
"CircuitBreakerManager",
```

### 3. Clean up test files

**`tests/test_safety/test_circuit_breaker.py`:**
- Remove `SafetyGate`, `SafetyGateBlocked`, `CircuitBreakerManager` imports (lines 8-10)
- Delete `TestSafetyGate` class (line 305+, ~130 lines)
- Delete `TestCircuitBreakerManager` class (line 435+, ~200 lines)
- Delete integration tests at bottom that use `SafetyGate`/`CircuitBreakerManager` (lines 679+)
- Keep any tests that test the core `CircuitBreaker` from `temper_ai.shared.core.circuit_breaker` — those are still used

**`tests/test_safety/test_m4_integration.py`:**
- Remove `CircuitBreakerManager`, `SafetyGate`, `SafetyGateBlocked` imports (lines 17-22)
- Delete `TestSafetyGateCoordination` class (line 223+)
- Delete `CircuitBreakerManager` tests (lines 293+)
- Keep any tests for other safety components (policies, rollback, etc.)

## Files to modify

| File | Change |
|---|---|
| `temper_ai/safety/circuit_breaker.py` | **Delete** |
| `temper_ai/safety/__init__.py` | Remove 3 exports from `_EXPORTS` dict and `__all__` |
| `tests/test_safety/test_circuit_breaker.py` | Remove SafetyGate/Manager test classes and imports |
| `tests/test_safety/test_m4_integration.py` | Remove SafetyGate/Manager test classes and imports |

## Verification

```bash
# Confirm no remaining references
grep -rn "SafetyGate\|CircuitBreakerManager\|SafetyGateBlocked" temper_ai/ tests/

# Run remaining safety tests
pytest tests/test_safety/ -v

# Full suite
pytest tests/ -x
```
