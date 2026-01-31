# Fix Import Error in Memory Leak Tests

**Type:** Bug Fix
**Scope:** Test Suite
**Date:** 2026-01-27

## Summary

Fixed ImportError in `tests/test_memory_leaks.py` caused by incorrect class name. The test was trying to import `ObservabilityTracker` which doesn't exist - the correct class name is `ExecutionTracker`.

## Motivation

The memory leak test file had an outdated import that prevented it from being collected and run. This blocked 9 important memory leak detection tests from executing.

## Error Before Fix

```
ImportError: cannot import name 'ObservabilityTracker' from 'src.observability.tracker'
```

**Impact:**
- 9 memory leak tests couldn't be collected
- Test collection showed "1 error"
- Memory leak detection tests were not running

## Changes

### File: tests/test_memory_leaks.py

**Line 35 - Import statement:**
```python
# Before
from src.observability.tracker import ObservabilityTracker

# After
from src.observability.tracker import ExecutionTracker
```

**Line 348 - Usage:**
```python
# Before
tracker = ObservabilityTracker(db=test_db)

# After
tracker = ExecutionTracker(db=test_db)
```

## Root Cause

The class was likely renamed from `ObservabilityTracker` to `ExecutionTracker` during refactoring, but this test file wasn't updated. The `ExecutionTracker` class is the correct observability tracking interface in the codebase.

## Testing

### Before Fix
```bash
$ pytest tests/ --co -q --ignore=tests/property/
collected 2859 items / 1 error
```

### After Fix
```bash
$ pytest tests/ --co -q --ignore=tests/property/
collected 2868 items  ✅

$ pytest tests/test_memory_leaks.py --co -q
collected 9 items  ✅
```

**Results:**
- ✅ All 2868 tests can be collected (was 2859 + 1 error)
- ✅ All 9 memory leak tests can be collected
- ✅ No import errors
- ✅ Module imports successfully

## Impact

**Tests Unblocked:**
1. `test_agent_execution_no_memory_leak` - Verifies agent execution doesn't leak memory
2. `test_workflow_compilation_no_memory_leak` - Verifies workflow compilation is memory-safe
3. `test_llm_provider_no_memory_leak` - Checks LLM provider memory stability
4. `test_observability_tracking_no_memory_leak` - Ensures tracking doesn't leak
5. `test_long_running_agent_session_stability` - Tests long-running stability
6. `test_async_llm_provider_no_memory_leak` - Async provider memory checks
7. `test_concurrent_workflows_no_memory_leak` - Concurrent execution memory safety
8. `test_database_connection_pool_no_memory_leak` - DB pool memory stability
9. `test_cycle_detection_no_memory_leak` - Cycle detection memory safety

These tests are critical for ensuring the framework can run long-term without memory issues.

## Breaking Changes

None. This is a test-only fix.

## Related Issues

- Fixes test collection error
- Enables memory leak detection tests
- Completes test suite coverage

## Lessons Learned

**Best Practice:** When renaming classes, use IDE refactoring tools or grep to find all usages:
```bash
grep -r "ObservabilityTracker" . --include="*.py"
```

This would have caught this missed reference during the original refactoring.
