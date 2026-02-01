# Task: Standardize security policy priority numbering

## Summary

Priority ranges inconsistent - BlastRadiusPolicy listed as P1 but has P0 priority value.

**Priority:** HIGH  
**Category:** consistency  
**Impact:** MEDIUM - Confusing priority values

---

## Files to Create

_None_

---

## Files to Modify

- `docs/security/M4_SAFETY_SYSTEM.md` - Update documentation

---

## Current State

**Location:** docs/security/M4_SAFETY_SYSTEM.md:311-380

**Current:** Conflicting priority ranges

**Should be:** Consistent priority system

---

## Acceptance Criteria

### Core Functionality

- [ ] Clarify: P0 = 90-200, P1 = 80-89, etc.
- [ ] Fix BlastRadiusPolicy classification
- [ ] Verify all actual implementation values

### Testing

- [ ] All documented priorities match code
- [ ] No conflicts

---

## Implementation Notes

See detailed report: `.claude-coord/reports/docs-review-20260130-223705.md`

**Generated from:** Documentation review 2026-01-30  
**Source:** Automated documentation audit (6 specialized agents)
