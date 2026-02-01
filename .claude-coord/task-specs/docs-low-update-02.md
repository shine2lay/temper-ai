# Task: Update pytest-xdist install instructions

## Summary

TESTING.md shows manual pip install instead of referencing dev dependencies

**Priority:** LOW  
**Category:** accuracy  
**Impact:** LOW - Minor installation confusion

---

## Files to Create

_None_

---

## Files to Modify

- `docs/TESTING.md`

---

## Current State

**Location:** docs/TESTING.md:175-182

**Current:** pip install pytest-xdist

**Should be:** pip install -e '.[dev]'

---

## Acceptance Criteria

### Core Functionality

- [ ] Update to: pip install -e '.[dev]'
- [ ] Note that pytest-xdist is in dev dependencies
- [ ] Show manual install as alternative

### Testing

- [ ] Instructions reference dev dependencies
- [ ] Command works correctly

---

## Implementation Notes

See detailed report: `.claude-coord/reports/docs-review-20260130-223705.md`

**Generated from:** Documentation review 2026-01-30  
**Source:** Automated documentation audit (6 specialized agents)
