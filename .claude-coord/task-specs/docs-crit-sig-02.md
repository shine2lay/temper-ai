# Task: Remove non-existent RollbackManager methods from docs

## Summary

Documentation shows delete_snapshot() and cleanup_old_snapshots() but these methods don't exist.

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

**Location:** docs/M4_API_REFERENCE.md:714-745

**Current:** Documents delete_snapshot(), cleanup_old_snapshots()

**Should be:** Remove or implement these methods

---

## Acceptance Criteria

### Core Functionality

- [ ] Remove delete_snapshot() from docs OR implement it
- [ ] Remove cleanup_old_snapshots() from docs OR implement it
- [ ] Update examples to use only existing methods

### Testing

- [ ] Grep src/safety/rollback.py for these methods
- [ ] All RollbackManager examples work

---

## Implementation Notes

See detailed report: `.claude-coord/reports/docs-review-20260130-223705.md`

**Generated from:** Documentation review 2026-01-30  
**Source:** Automated documentation audit (6 specialized agents)
