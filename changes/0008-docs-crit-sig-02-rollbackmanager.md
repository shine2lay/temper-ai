# Remove Non-Existent RollbackManager Methods from Docs

**Date:** 2026-01-31
**Task:** docs-crit-sig-02
**Priority:** P1 (Critical)
**Category:** Documentation - Code Mismatch

## Summary

Removed documentation for two non-existent RollbackManager methods. The documentation described `delete_snapshot()` and `cleanup_old_snapshots()` methods that don't exist in the actual implementation.

## Changes Made

### docs/M4_API_REFERENCE.md

**Removed Non-Existent Methods:**

1. **delete_snapshot(snapshot_id: str) -> bool**
   - Not implemented in src/safety/rollback.py
   - Removed entire method documentation section

2. **cleanup_old_snapshots(max_age_hours: int = 24) -> int**
   - Not implemented in src/safety/rollback.py
   - Removed entire method documentation section

**Kept Existing Methods:**
- `get_snapshot(snapshot_id: str)` - exists and works
- `get_history() -> List[RollbackResult]` - exists and works
- `create_snapshot()` - exists and works
- `execute_rollback()` - exists and works

## Impact

**Before:**
- Users trying to call `delete_snapshot()` would get `AttributeError`
- Users trying to call `cleanup_old_snapshots()` would get `AttributeError`
- Documentation promised features that don't exist

**After:**
- Only documented methods that actually exist
- All examples will work correctly
- No false expectations for users

## Testing Performed

```bash
# Verified methods don't exist
grep "def delete_snapshot\|def cleanup_old_snapshots" src/safety/rollback.py
# No matches found

# Verified get_history exists
grep "def get_history" src/safety/rollback.py
# Found: def get_history(self) -> List[RollbackResult]:
```

## Files Modified

- `docs/M4_API_REFERENCE.md` - Removed documentation for non-existent methods

## Risks

**None** - Documentation-only change removing non-existent method references

## Follow-up Tasks

If snapshot deletion functionality is needed in the future, these methods could be implemented and documented. Current implementation focuses on:
- Creating snapshots
- Executing rollbacks
- Retrieving snapshots
- Viewing rollback history

## Notes

- RollbackManager currently doesn't support snapshot deletion
- This may be intentional for audit/compliance reasons
- Snapshots are stored but not programmatically deleted
- The remaining documented methods (get_snapshot, get_history, create_snapshot, execute_rollback) all exist
