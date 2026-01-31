# Replace PolicyViolation with SafetyViolation in Security Docs

**Date:** 2026-01-31
**Task:** docs-crit-import-03
**Priority:** P1 (Critical)
**Category:** Documentation - Code Mismatch

## Summary

Fixed incorrect exception class name in security documentation. The documentation was using `PolicyViolation` but the actual implementation uses `SafetyViolation`.

## Changes Made

### docs/security/SAFETY_EXAMPLES.md

**Global Replacement:**
- All instances of `PolicyViolation` → `SafetyViolation`

**Locations Fixed:**
1. Line 89: Import statement
   - `from src.safety.base import BaseSafetyPolicy, ViolationSeverity, SafetyViolation`
2. Line 107: Exception usage in example
   - `return [SafetyViolation(...)]`
3. Line 710: Type hint in method signature
   - `async def _log_violation(self, violation: SafetyViolation, context: PolicyExecutionContext)`
4. Line 730: Type hint in method signature
   - `async def _send_alert(self, violation: SafetyViolation, context: PolicyExecutionContext)`

## Impact

**Before:**
- Users copying examples would get `NameError: name 'PolicyViolation' is not defined`
- Import statements referenced non-existent class

**After:**
- All code examples work correctly
- Imports match actual implementation in `src.safety.interfaces`

## Testing Performed

```bash
# Verified correct import
python3 -c "from src.safety.interfaces import SafetyViolation; print('Import successful')"

# Verified no PolicyViolation references remain
grep -r "PolicyViolation" docs/
# No matches found
```

## Files Modified

- `docs/security/SAFETY_EXAMPLES.md` - Replaced all PolicyViolation references

## Risks

**None** - Documentation-only change with no code modifications

## Follow-up Tasks

None required. All security documentation now uses the correct exception class name.

## Notes

- The actual implementation is in `src.safety.interfaces.SafetyViolation`
- This was a consistent naming issue affecting 4 locations in the examples file
- All safety policy examples now use correct exception class
