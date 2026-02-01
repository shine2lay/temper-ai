# Task: Replace PolicyViolation with SafetyViolation in security docs

## Summary

Security documentation uses PolicyViolation but code uses SafetyViolation. Global find/replace needed.

**Priority:** CRITICAL  
**Category:** doc-code-mismatch  
**Impact:** CRITICAL - All policy examples cause NameError

---

## Files to Create

_None_

---

## Files to Modify

- `docs/security/M4_SAFETY_SYSTEM.md` - Update documentation

---

## Current State

**Location:** docs/security/M4_SAFETY_SYSTEM.md (multiple locations)

**Current:** PolicyViolation

**Should be:** SafetyViolation

---

## Acceptance Criteria

### Core Functionality

- [ ] Global replace PolicyViolation → SafetyViolation in all security docs
- [ ] Update imports
- [ ] Update class references
- [ ] Update examples

### Testing

- [ ] Verify: python -c 'from src.safety.interfaces import SafetyViolation'
- [ ] Grep security docs to ensure no PolicyViolation references remain

---

## Implementation Notes

See detailed report: `.claude-coord/reports/docs-review-20260130-223705.md`

**Generated from:** Documentation review 2026-01-30  
**Source:** Automated documentation audit (6 specialized agents)
