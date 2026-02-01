# Task: Fix non-existent methods in M4 API docs

## Summary

Multiple documented methods don't exist: CircuitBreaker.force_close(), ApprovalRequest.is_resolved(), RollbackResult.partial_success

**Priority:** CRITICAL  
**Category:** doc-code-mismatch  
**Impact:** CRITICAL - Examples will fail

---

## Files to Create

_None_

---

## Files to Modify

- `docs/M4_API_REFERENCE.md` - Update documentation

---

## Current State

**Location:** docs/M4_API_REFERENCE.md (multiple)

**Current:** Documents non-existent methods

**Should be:** Remove or implement missing methods

---

## Acceptance Criteria

### Core Functionality

- [ ] CircuitBreaker.force_close() → use reset() instead
- [ ] ApprovalRequest.is_resolved() → remove or implement
- [ ] RollbackResult.partial_success → remove (doesn't exist)
- [ ] Update all affected examples

### Testing

- [ ] Grep source files to verify method existence
- [ ] All API examples work

---

## Implementation Notes

See detailed report: `.claude-coord/reports/docs-review-20260130-223705.md`

**Generated from:** Documentation review 2026-01-30  
**Source:** Automated documentation audit (6 specialized agents)
