# Fix SQLAlchemy Reserved Field Name in RollbackEvent

**Type:** Bug Fix / Critical
**Scope:** Observability System
**Date:** 2026-01-27

## Summary

Renamed `RollbackEvent.metadata` field to `rollback_metadata` to avoid conflict with SQLAlchemy's reserved `metadata` attribute. This fix resolves a critical error that was preventing 23 test files from being collected and run.

## Motivation

SQLAlchemy's Declarative API reserves the name `metadata` for internal use (ClassVar for table metadata). Using `metadata` as a column name causes an `InvalidRequestError` during model creation, blocking all tests that import observability models.

## Error Before Fix

```
sqlalchemy.exc.InvalidRequestError: Attribute name 'metadata' is reserved when using the Declarative API.
```

**Impact:**
- 23 test files failed to collect
- All observability tests blocked
- Critical test suite blocker

## Changes

### 1. Model Definition Updated

**File:** `src/observability/models.py`

```python
# Before (line 458)
metadata: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

# After
rollback_metadata: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
```

**Purpose:** The field stores additional context/metadata for manual rollback events. Renamed to `rollback_metadata` to be more descriptive and avoid the reserved name conflict.

### 2. Usage Updated

**File:** `src/observability/rollback_logger.py`

```python
# Before (line 99)
event = RollbackEvent(
    ...
    metadata=result.metadata
)

# After
event = RollbackEvent(
    ...
    rollback_metadata=result.metadata
)
```

## Testing

### Before Fix
```bash
$ pytest tests/test_observability/ --co
ERROR collecting tests/test_observability/test_tracker.py
sqlalchemy.exc.InvalidRequestError: Attribute name 'metadata' is reserved
```

### After Fix
```bash
$ pytest tests/test_observability/ -q
238 passed, 2 skipped ✅
```

**Results:**
- ✅ All observability tests can be collected
- ✅ 238 tests passing
- ✅ No SQLAlchemy InvalidRequestError
- ✅ RollbackEvent model instantiates correctly

## Database Impact

**Schema Change:** Column renamed from `metadata` to `rollback_metadata`

**Migration Required:** Yes (if rollback_events table exists in production)

**Migration Strategy:**
```sql
-- For existing deployments
ALTER TABLE rollback_events RENAME COLUMN metadata TO rollback_metadata;
```

**Note:** Since the rollback system is part of M4 (in progress) and likely not in production yet, this change should have minimal impact. New deployments will create the table with the correct column name.

## Breaking Changes

**API Change:** The `RollbackEvent` model field name changed from `metadata` to `rollback_metadata`.

**Impact:**
- Internal change only (observability system)
- No public API affected
- Only affects code that directly queries or creates RollbackEvent records
- All known usages updated in this change

**Migration:**
```python
# Before
event.metadata  # ❌ Reserved name

# After
event.rollback_metadata  # ✅ Descriptive, non-reserved
```

## Related Issues

- Fixes test collection errors blocking 23 test files
- Resolves SQLAlchemy reserved attribute conflict
- Enables observability test suite to run

## Lessons Learned

**SQLAlchemy/SQLModel Reserved Names:**
- `metadata` - Reserved for table metadata
- `query` - Reserved for query interface
- `registry` - Reserved for mapper registry

**Best Practice:** Use descriptive, domain-specific field names to avoid conflicts with framework internals. Prefer `rollback_metadata`, `event_context`, `audit_data` over generic `metadata`.

## References

- SQLAlchemy Declarative API: https://docs.sqlalchemy.org/en/20/orm/declarative_tables.html
- SQLModel Reserved Attributes: https://sqlmodel.tiangolo.com/tutorial/fastapi/simple-hero-api/
- Related change: M4 Rollback System (changes/0127-m4-rollback-mechanism.md)
