# Task: Add venv activation to pytest commands in TESTING.md

## Summary

Test commands assume pytest is globally installed.

**Priority:** HIGH  
**Category:** completeness  
**Impact:** MEDIUM - Commands fail for new users

---

## Files to Create

_None_

---

## Files to Modify

- `docs/TESTING.md` - Update documentation

---

## Current State

**Location:** docs/TESTING.md:159-169

**Current:** Direct pytest commands

**Should be:** Include venv activation step

---

## Acceptance Criteria

### Core Functionality

- [ ] Add prerequisite section
- [ ] Show venv activation
- [ ] Note: pip install -e '.[dev]' required

### Testing

- [ ] Instructions work for new users

---

## Implementation Notes

See detailed report: `.claude-coord/reports/docs-review-20260130-223705.md`

**Generated from:** Documentation review 2026-01-30  
**Source:** Automated documentation audit (6 specialized agents)
