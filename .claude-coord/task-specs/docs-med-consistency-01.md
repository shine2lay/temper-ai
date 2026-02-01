# Task: Consolidate duplicate configuration guides

## Summary

Two separate configuration guides exist (CONFIGURATION.md and M4_CONFIGURATION_GUIDE.md) which may cause confusion for users.

**Priority:** MEDIUM  
**Category:** organization  
**Impact:** MEDIUM - Users may follow wrong guide or get confused

---

## Files to Create

_None_

---

## Files to Modify

- `docs/CONFIGURATION.md`
- `docs/M4_CONFIGURATION_GUIDE.md`

---

## Current State

**Location:** docs/CONFIGURATION.md, docs/M4_CONFIGURATION_GUIDE.md

**Current:** Two separate config guides

**Should be:** Single unified guide or clearly differentiated guides

---

## Acceptance Criteria

### Core Functionality

- [ ] Either consolidate into single guide
- [ ] OR clearly label M4_CONFIGURATION_GUIDE as M4-specific
- [ ] OR clearly label CONFIGURATION.md as general/basic
- [ ] Add cross-references between guides
- [ ] Ensure no conflicting information

### Testing

- [ ] Both guides have clear scope definitions
- [ ] No duplicate content without cross-reference
- [ ] User can determine which guide to use

---

## Implementation Notes

See detailed report: `.claude-coord/reports/docs-review-20260130-223705.md`

**Generated from:** Documentation review 2026-01-30  
**Source:** Automated documentation audit (6 specialized agents)
