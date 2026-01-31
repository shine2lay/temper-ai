# Standardize Security Policy Priority Numbering

**Date:** 2026-01-31
**Task:** docs-high-security-01
**Priority:** P2 (High)
**Category:** Documentation - Consistency

## Summary

Fixed inconsistent security policy priority classification. BlastRadiusPolicy was incorrectly listed under P1 (Priority 80-89) despite having an actual priority value of 90, which falls in the P0 range (90-200).

## Changes Made

### docs/security/M4_SAFETY_SYSTEM.md

**Moved BlastRadiusPolicy from P1 to P0:**

1. **Added to P0 - CRITICAL section:**
   - BlastRadiusPolicy (priority: 90) now correctly listed under P0 (90-200 range)
   - Added "Prevent widespread file modifications" to P0 examples

2. **Removed from P1 - IMPORTANT section:**
   - Moved BlastRadiusPolicy from P1 list
   - Updated P1 purpose to remove "limit blast radius" (now in P0)
   - P1 now focuses on resource exhaustion and best practices only

3. **Priority Ranges (Confirmed Correct):**
   - P0 (Critical): 90-200 ✓
   - P1 (Important): 80-89 ✓
   - P2 (Optimization): 50-79 ✓

## Impact

**Before:**
- BlastRadiusPolicy (priority: 90) incorrectly classified as P1
- Confusion about where priority 90 falls
- Priority ranges and policy classifications didn't match

**After:**
- BlastRadiusPolicy correctly classified as P0
- All policies match their documented priority ranges
- Clear and consistent priority system

## Testing Performed

```bash
# Verified actual priority in code
grep -A 10 "def priority" src/safety/blast_radius.py
# return 90

# Verified priority 90 falls in P0 range (90-200)
# Confirmed: 90 >= 90 (P0 minimum)
```

## Files Modified

- `docs/security/M4_SAFETY_SYSTEM.md` - Moved BlastRadiusPolicy to correct priority tier

## Risks

**None** - Documentation-only change correcting classification

## Follow-up Tasks

None required. All security policies now correctly classified by their actual priority values.

## Notes

**Priority Verification:**
- ForbiddenOperationsPolicy: 200 → P0 ✓
- FileAccessPolicy: 95 → P0 ✓
- SecretDetectionPolicy: 95 → P0 ✓
- **BlastRadiusPolicy: 90 → P0 ✓** (was incorrectly P1)
- RateLimitPolicy: 85 → P1 ✓
- ResourceLimitPolicy: 80 → P1 ✓
- ApprovalWorkflowPolicy: 80 → P1 ✓

**Why BlastRadiusPolicy is P0:**
- Priority 90 falls in P0 range (90-200)
- Prevents widespread damage (critical safety concern)
- Should execute with highest priority alongside other critical policies
- Aligns with comment in code: "high priority since it prevents widespread damage"
