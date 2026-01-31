# Fix datetime.utcnow() Deprecation Warnings

**Type:** Bug Fix / Code Quality
**Scope:** Codebase-wide
**Date:** 2026-01-27

## Summary

Replaced all deprecated `datetime.utcnow()` calls with `datetime.now(UTC)` to eliminate deprecation warnings and ensure future compatibility with Python 3.13+.

## Motivation

Python's `datetime.utcnow()` is deprecated as of Python 3.12 and will be removed in future versions. The replacement `datetime.now(UTC)` is more explicit about timezone handling and follows modern Python best practices.

## Changes

### Source Files Updated

1. **src/compiler/checkpoint_backends.py**
   - Updated import: `from datetime import datetime, UTC`
   - Replaced 2 occurrences of `datetime.utcnow()` with `datetime.now(UTC)`
   - Lines: 236, 421

2. **src/compiler/checkpoint.py**
   - Updated import: `from datetime import datetime, UTC`
   - Replaced 1 occurrence of `datetime.utcnow()` with `datetime.now(UTC)`
   - Line: 218

3. **src/compiler/domain_state.py**
   - Updated import: `from datetime import datetime, UTC`
   - Updated default_factory: `field(default_factory=lambda: datetime.now(UTC))`
   - Line: 96

4. **src/compiler/langgraph_state.py**
   - Updated import: `from datetime import datetime, UTC`
   - Updated default_factory: `field(default_factory=lambda: datetime.now(UTC))`
   - Line: 76

### Test Files Updated

5. **tests/integration/test_milestone1_e2e.py**
   - Updated import: `from datetime import datetime, timedelta, UTC`
   - Replaced 40+ occurrences of `datetime.utcnow()` with `datetime.now(UTC)`
   - Lines: 141, 160, 177, 194, 195, 220, 221, 235, 254, 267, etc.

6. **tests/test_compiler/test_checkpoint.py**
   - Updated import: `from datetime import datetime, UTC`
   - Replaced 2 occurrences of `datetime.utcnow()` with `datetime.now(UTC)`
   - Lines: 23, 35

## Testing

- ✅ All integration tests pass (79 passed, 11 skipped)
- ✅ Zero datetime deprecation warnings in test output
- ✅ All datetime-related functionality works correctly
- ✅ Checkpoint creation and loading working properly

## Impact

### Before
```
tests/integration/test_milestone1_e2e.py:529: DeprecationWarning:
  datetime.datetime.utcnow() is deprecated and scheduled for removal in
  a future version. Use timezone-aware objects to represent datetimes in UTC:
  datetime.datetime.now(datetime.UTC).
```

### After
- Zero deprecation warnings related to datetime
- Clean test output
- Future-proof code for Python 3.13+

## Remaining Warnings

### SQLModel session.query() Warnings
- Status: Lower priority
- Scope: Test files only
- Impact: Does not affect production code
- Note: These warnings recommend using `session.exec()` instead of `session.query()`
- Future task: Convert test queries to use SQLModel's recommended `exec()` method

### Pydantic Field Deprecation
- Status: Intentional
- File: src/compiler/schemas.py line 43
- Purpose: Warning users about deprecated `api_key` field
- Note: This is correct behavior - warns users to migrate to `api_key_ref`

## Related Issues

- Fixes deprecation warnings reported in test suite
- Improves code quality and maintainability
- Prepares codebase for Python 3.13+ compatibility

## Breaking Changes

None. All changes are backwards compatible.

## Migration Guide

No migration needed for users. Internal change only.

## References

- Python 3.12 datetime deprecation: https://docs.python.org/3/library/datetime.html#datetime.datetime.utcnow
- Modern datetime practices: Use timezone-aware datetime objects with UTC
