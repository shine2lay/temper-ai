# Task: Use actual imports in TESTING.md examples

## Summary

Examples use hypothetical imports that don't match actual test patterns

**Priority:** LOW  
**Category:** accuracy  
**Impact:** LOW - Examples don't match reality

---

## Files to Create

_None_

---

## Files to Modify

- `docs/TESTING.md`

---

## Current State

**Location:** docs/TESTING.md:211-241

**Current:** from src.tools.calculator import Calculator (may not exist)

**Should be:** Actual imports from real tests

---

## Acceptance Criteria

### Core Functionality

- [ ] Replace hypothetical examples with actual test code
- [ ] Use real imports from tests/
- [ ] Show actual test patterns used in codebase

### Testing

- [ ] All imports in examples exist in codebase
- [ ] Examples match actual test structure

---

## Implementation Notes

See detailed report: `.claude-coord/reports/docs-review-20260130-223705.md`

**Generated from:** Documentation review 2026-01-30  
**Source:** Automated documentation audit (6 specialized agents)
