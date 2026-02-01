# Fix: Magic Numbers Throughout (code-medi-04)

**Date:** 2026-02-01
**Priority:** MEDIUM (P3)
**Module:** observability, cache
**Status:** Complete

## Summary

Eliminated magic numbers throughout the codebase by extracting them into centralized constant modules. This improves maintainability, readability, and reduces the risk of inconsistent values.

## Problem

Magic numbers (hard-coded values like 1000, 100, 10000) appeared throughout multiple modules without clear meaning or centralized definitions:

1. **Performance Module:** Buffer sizes, thresholds, cleanup intervals
2. **Cache Module:** Default cache sizes and TTL values
3. **Buffer Module:** Flush sizes and retry attempts

**Issues:**
- **Unclear Intent:** Numbers like "1000" don't convey meaning
- **Maintenance Risk:** Changing a limit requires finding all occurrences
- **Inconsistency Risk:** Same concept (e.g., "max samples") might use different values in different places
- **Violates DRY Principle:** Constants duplicated across files

**Impact:**
- Reduced code readability
- Higher maintenance cost
- Risk of inconsistent behavior

## Solution

Created centralized constant modules with descriptive names:

### New Files Created

**1. src/observability/constants.py**
```python
# Performance Monitoring
MAX_LATENCY_SAMPLES = 1000  # Maximum number of latency samples to keep in memory
MAX_SLOW_OPERATIONS = 100   # Maximum number of slow operations to track
DEFAULT_CLEANUP_INTERVAL = 1000  # Run cleanup every N records
DEFAULT_SLOW_THRESHOLD_MS = 1000.0  # Default threshold (1 second)
MS_PER_SECOND = 1000.0  # Milliseconds per second conversion factor

# Default operation thresholds (in milliseconds)
DEFAULT_THRESHOLDS_MS = {
    "llm_call": 5000.0,           # 5 seconds
    "tool_execution": 3000.0,     # 3 seconds
    "stage_execution": 10000.0,   # 10 seconds
    "agent_execution": 30000.0,   # 30 seconds
    "workflow_execution": 60000.0, # 1 minute
}

# Buffer Configuration
DEFAULT_BUFFER_SIZE = 100  # Default number of records to buffer before flush
DEFAULT_BUFFER_TIMEOUT_SECONDS = 5.0  # Flush after N seconds
MAX_RETRY_ATTEMPTS = 3  # Maximum number of retry attempts
RETRY_DELAY_SECONDS = 1.0  # Delay between retry attempts
```

**2. src/cache/constants.py**
```python
# LLM Cache Configuration
DEFAULT_CACHE_SIZE = 1000  # Default maximum number of cached LLM responses
DEFAULT_TTL_SECONDS = 3600  # Default TTL (1 hour)
```

### Files Modified

**1. src/observability/performance.py**
- Replaced `slow_threshold_ms: float = 1000.0` with `DEFAULT_SLOW_THRESHOLD_MS`
- Replaced hardcoded `1000` samples with `MAX_LATENCY_SAMPLES`
- Replaced hardcoded `100` slow ops with `MAX_SLOW_OPERATIONS`
- Replaced hardcoded `1000` cleanup interval with `DEFAULT_CLEANUP_INTERVAL`
- Replaced threshold dict with `DEFAULT_THRESHOLDS_MS.copy()`
- Replaced default threshold `1000.0` with `DEFAULT_SLOW_THRESHOLD_MS`

**2. src/observability/buffer.py**
- Replaced `flush_size: int = 100` with `DEFAULT_BUFFER_SIZE`
- Replaced `max_retries: int = 3` with `MAX_RETRY_ATTEMPTS`

**3. src/cache/llm_cache.py**
- Replaced `max_size: int = 1000` with `DEFAULT_CACHE_SIZE` (2 occurrences)
- Replaced `ttl: Optional[int] = 3600` with `DEFAULT_TTL_SECONDS`

## Testing

All existing tests pass without modification:

```bash
# Performance module tests
pytest tests/test_observability/test_performance.py
# Result: 25 passed

# Buffer module tests
pytest tests/test_observability/test_buffer.py
# Result: All passed

# Cache module tests
pytest tests/test_llm_cache.py
# Result: 73 passed, 7 skipped
```

No test changes required because:
- Constants have the same values as before
- Only the source of truth changed (hardcoded → named constant)
- Behavior remains identical

## Benefits

1. **Improved Readability:**
   - `MAX_LATENCY_SAMPLES` is clearer than `1000`
   - `DEFAULT_SLOW_THRESHOLD_MS` is clearer than `1000.0`

2. **Centralized Configuration:**
   - All observability limits in one place
   - All cache limits in one place
   - Easy to adjust globally

3. **Better Maintainability:**
   - Change limit once, applies everywhere
   - Clear documentation of defaults
   - Type hints and comments explain meaning

4. **Reduced Errors:**
   - No risk of typos (e.g., `1000` vs `10000`)
   - No risk of inconsistent values
   - IDE autocomplete prevents mistakes

## Future Work

This change addresses observability and cache modules. Additional magic numbers exist in:

- **compiler module:** Timeout values, buffer sizes
- **tools module:** Request timeouts, retry counts
- **security module:** Rate limits, blast radius thresholds

Consider creating:
- `src/compiler/constants.py`
- `src/tools/constants.py`
- `src/security/constants.py`

## Related

- Task: code-medi-04
- Report: .claude-coord/reports/code-review-20260130-223423.md (lines 292-299)
- Spec: .claude-coord/task-specs/code-medi-04.md

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
