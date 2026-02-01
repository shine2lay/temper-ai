# Fix: Silent Exception Swallowing (code-high-10)

**Date:** 2026-02-01
**Priority:** HIGH (P2)
**Module:** observability
**Status:** Complete

## Summary

Fixed silent exception swallowing in `ExecutionTracker` class by adding proper exception logging with full context and stack traces. Previously, broad `except Exception` blocks continued silently without logging, making debugging difficult.

## Problem

Multiple exception handlers in `src/observability/tracker.py` used broad `except Exception:` or `except Exception as e:` without proper logging, causing errors to be swallowed silently.

**Specific Issues:**
1. Line 221: Exception during workflow metric aggregation caught but not logged
2. Line 337: Exception during stage metric aggregation caught but not logged
3. Other exception handlers had minimal or no error context

**Impact:** Hidden bugs, difficult troubleshooting, production issues remain undetected.

## Solution

Added comprehensive logging to all exception handlers:

1. **Workflow metric aggregation** (lines 221-227):
   - Added `logger.warning()` with descriptive message
   - Added `exc_info=True` for full stack traces
   - Included workflow_id in error message for context

2. **Stage metric aggregation** (lines 337-343):
   - Added `logger.warning()` with descriptive message
   - Added `exc_info=True` for full stack traces
   - Included stage_id in error message for context

3. **Collaboration events** (lines 991-997):
   - Enhanced logging with `exc_info=True`
   - Added extra context (event_type, event_data keys)

4. **Data sanitization** (lines 733-740):
   - Security-conscious logging (error type only, not data)
   - Prevents leaking sensitive information in logs

## Changes

### Files Modified

**src/observability/tracker.py:**
- Lines 221-227: Added comprehensive logging for workflow metric aggregation errors
- Lines 337-343: Added comprehensive logging for stage metric aggregation errors
- Lines 991-997: Enhanced collaboration event error logging
- Lines 733-740: Security-conscious error logging for sanitization

### Exception Handling Pattern

**Before (Silent):**
```python
except Exception:
    # Non-SQL backends don't need metric aggregation
    pass
```

**After (Logged):**
```python
except (ImportError, AttributeError):
    # Expected for non-SQL backends
    pass
except Exception as e:
    # Unexpected error during metric aggregation
    logger.warning(
        f"Failed to aggregate workflow metrics for {workflow_id}: {e}",
        exc_info=True
    )
```

## Testing

All observability tests passing:
- Exception logging verified manually
- Stack traces appear in logs when exceptions occur
- No regressions in existing functionality

**Command:**
```bash
python3 -m pytest tests/test_observability/ -v
```

## Performance Impact

**Negligible:**
- Logging only occurs during exceptions (error path)
- Normal execution path unchanged
- `exc_info=True` adds stack trace formatting (acceptable cost for errors)

## Risks

**None identified.** Changes are:
- Backward compatible (only adds logging)
- Low risk (error handling improved, not changed)
- Defensive (preserves existing error behavior)
- Security-conscious (sanitization errors don't leak data)

## Benefits

1. **Debuggability:** Stack traces now available for all unexpected errors
2. **Observability:** Can track error patterns and frequencies
3. **Production Safety:** Issues detected early via log monitoring
4. **Maintenance:** Easier to diagnose and fix production issues

## Verification

- ✅ All exception handlers have proper logging
- ✅ `exc_info=True` provides full stack traces
- ✅ Error messages include context (IDs, operation type)
- ✅ Security-sensitive errors log safely (no data leakage)
- ✅ Expected exceptions (ImportError, AttributeError) handled separately
- ✅ Unexpected exceptions logged with full details

## Architecture Pillars Alignment

| Pillar | Impact |
|--------|--------|
| **P0: Reliability** | ✅ IMPROVED - Errors now visible, can be diagnosed and fixed |
| **P2: Observability** | ✅ IMPROVED - Full error context and stack traces in logs |
| **P3: Maintainability** | ✅ IMPROVED - Easier debugging and troubleshooting |

## Related

- Task: code-high-10
- Report: .claude-coord/reports/code-review-20260130-223423.md (lines 234-237)
- Fixed as part of commit: 58ea5e6 (code-high-09)

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
