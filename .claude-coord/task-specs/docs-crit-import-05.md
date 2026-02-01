# Task: Fix PolicyComposer method names in M4 API docs

## Summary

PolicyComposer documentation shows clear() but actual method is clear_policies(). Also documents non-existent set_fail_fast().

**Priority:** CRITICAL  
**Category:** doc-code-mismatch  
**Impact:** CRITICAL - Examples won't work

---

## Files to Create

_None_

---

## Files to Modify

- `docs/M4_API_REFERENCE.md` - Update documentation

---

## Current State

**Location:** docs/M4_API_REFERENCE.md:175-180, 184-198

**Current:** clear(), set_fail_fast(enabled: bool)

**Should be:** clear_policies(), (set_fail_fast doesn't exist)

---

## Acceptance Criteria

### Core Functionality

- [ ] Replace clear() with clear_policies()
- [ ] Remove set_fail_fast() or implement it
- [ ] Document short_circuit_on_critical (exists but not documented)
- [ ] Document parallel_execution (exists but not documented)

### Testing

- [ ] Verify: grep 'def clear_policies' src/safety/composition.py
- [ ] All PolicyComposer examples work

---

## Implementation Notes

See detailed report: `.claude-coord/reports/docs-review-20260130-223705.md`

**Generated from:** Documentation review 2026-01-30  
**Source:** Automated documentation audit (6 specialized agents)
