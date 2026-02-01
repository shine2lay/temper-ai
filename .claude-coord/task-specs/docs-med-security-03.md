# Task: Document all safety exception types

## Summary

Security docs show generic Exception handling but don't document actual exception types

**Priority:** MEDIUM  
**Category:** completeness  
**Impact:** MEDIUM - Developers don't know which exceptions to catch

---

## Files to Create

_None_

---

## Files to Modify

- `docs/security/M4_SAFETY_SYSTEM.md`

---

## Current State

**Location:** docs/security/M4_SAFETY_SYSTEM.md:589-604

**Current:** Generic exception examples

**Should be:** All exception types documented

---

## Acceptance Criteria

### Core Functionality

- [ ] Document all exceptions from src/safety/exceptions.py
- [ ] Add exception hierarchy diagram
- [ ] Show when each exception is raised
- [ ] Provide catch examples for each type

### Testing

- [ ] All exception types from code are documented
- [ ] Examples show correct exception handling

---

## Implementation Notes

See detailed report: `.claude-coord/reports/docs-review-20260130-223705.md`

**Generated from:** Documentation review 2026-01-30  
**Source:** Automated documentation audit (6 specialized agents)
