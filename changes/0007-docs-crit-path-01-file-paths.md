# Fix Wrong File Paths in Security Documentation

**Date:** 2026-01-31
**Task:** docs-crit-path-01
**Priority:** P1 (Critical)
**Category:** Documentation - Incorrect Paths

## Summary

Fixed incorrect file path references in security documentation. The documentation pointed to non-existent file paths, making it impossible for users to locate the referenced code.

## Changes Made

### docs/security/M4_SAFETY_SYSTEM.md

**Fixed File Path References:**

1. **ResourceLimitPolicy path:**
   - ❌ Before: `src/safety/resource_limits.py`
   - ✅ After: `src/safety/policies/resource_limit_policy.py`

2. **ApprovalWorkflowPolicy path:**
   - ❌ Before: `src/safety/approval_workflow.py`
   - ✅ After: `src/safety/approval.py`

## Impact

**Before:**
- Users trying to view referenced files would get "file not found"
- Documentation pointed to non-existent locations
- Confusion about code organization

**After:**
- All file path references are accurate
- Users can navigate directly to the correct files
- Documentation matches actual codebase structure

## Testing Performed

```bash
# Verified correct file paths exist
ls -la src/safety/approval.py
# -rw-rw-r-- 1 shinelay shinelay 16024 Jan 27 18:38 src/safety/approval.py

ls -la src/safety/policies/resource_limit_policy.py
# -rw-rw-r-- 1 shinelay shinelay 16981 Jan 28 17:17 src/safety/policies/resource_limit_policy.py

# Verified no more incorrect paths in security docs
grep -r "approval_workflow\.py\|resource_limits\.py" docs/security/
# No matches found
```

## Files Modified

- `docs/security/M4_SAFETY_SYSTEM.md` - Fixed file path references

## Risks

**None** - Documentation-only change with no code modifications

## Follow-up Tasks

None required. All file path references are now correct.

## Notes

- The test file `tests/test_safety/test_approval_workflow.py` is correctly named
- Only the source file references in M4_SAFETY_SYSTEM.md needed correction
- This reflects actual file organization in the codebase
