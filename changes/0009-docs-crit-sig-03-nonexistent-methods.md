# Fix Non-Existent Methods in M4 API Docs

**Date:** 2026-01-31
**Task:** docs-crit-sig-03
**Priority:** P1 (Critical)
**Category:** Documentation - Code Mismatch

## Summary

Removed documentation for three non-existent methods/properties across multiple classes in M4_API_REFERENCE.md. The documentation described methods that don't exist in the actual implementation, causing AttributeError for users.

## Changes Made

### docs/M4_API_REFERENCE.md

**Removed Non-Existent Methods/Properties:**

1. **ApprovalRequest.is_resolved() -> bool**
   - Not implemented in src/safety/approval.py
   - Users should use is_pending(), is_approved(), is_rejected(), or is_expired() instead
   - Removed entire method documentation section

2. **RollbackResult.partial_success -> bool**
   - Not a property in src/safety/rollback.py
   - RollbackResult has `status` field (RollbackStatus enum) and `success` boolean
   - Users should check `status == RollbackStatus.PARTIAL` instead
   - Removed entire property documentation section

3. **CircuitBreaker.force_close() -> None**
   - Not implemented in src/safety/circuit_breaker.py
   - CircuitBreaker has `reset()` method instead
   - Removed entire method documentation (reset() is already documented)

## Impact

**Before:**
- Users would get `AttributeError: 'ApprovalRequest' object has no attribute 'is_resolved'`
- Users would get `AttributeError: 'RollbackResult' object has no attribute 'partial_success'`
- Users would get `AttributeError: 'CircuitBreaker' object has no attribute 'force_close'`

**After:**
- Only documented methods/properties that actually exist
- Users will use correct alternatives:
  - ApprovalRequest: is_pending(), is_approved(), is_rejected(), is_expired()
  - RollbackResult: status attribute (RollbackStatus enum)
  - CircuitBreaker: reset() method

## Testing Performed

```bash
# Verified methods don't exist
grep "def is_resolved\|def partial_success\|def force_close" src/safety/*.py
# No matches found

# Verified alternatives exist
grep "def is_pending" src/safety/approval.py
# Found: def is_pending(self) -> bool:

grep "status: RollbackStatus" src/safety/rollback.py
# Found: status: RollbackStatus

grep "def reset" src/safety/circuit_breaker.py
# Found: def reset(self) -> None:
```

## Files Modified

- `docs/M4_API_REFERENCE.md` - Removed 3 non-existent method/property documentations

## Risks

**None** - Documentation-only change removing non-existent method references

## Follow-up Tasks

None required. Users now have accurate API documentation showing only methods that exist.

## Notes

### ApprovalRequest Alternatives
The class provides specific status check methods:
- `is_pending()` - Check if still waiting
- `is_approved()` - Check if approved
- `is_rejected()` - Check if rejected
- `is_expired()` - Check if expired

### RollbackResult Alternatives
Check the status enum directly:
```python
if result.status == RollbackStatus.PARTIAL:
    print("Partial success")
if result.status == RollbackStatus.SUCCESS:
    print("Full success")
```

### CircuitBreaker Alternatives
Use `reset()` method:
```python
# Reset circuit to initial state
breaker.reset()
```
