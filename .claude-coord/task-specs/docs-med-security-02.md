# Task: Clarify cache TTL configurations in security docs

## Summary

Different cache_ttl values shown: 60, 30, 120 without clarification

**Priority:** MEDIUM  
**Category:** consistency  
**Impact:** MEDIUM - Confusing configuration values

---

## Files to Create

_None_

---

## Files to Modify

- `docs/security/M4_SAFETY_SYSTEM.md`

---

## Current State

**Location:** docs/security/M4_SAFETY_SYSTEM.md

**Current:** Inconsistent cache_ttl examples

**Should be:** Clarified environment-specific values

---

## Acceptance Criteria

### Core Functionality

- [ ] Create table showing cache_ttl by environment
- [ ] Default: 60 (from code)
- [ ] Production: 120 (example)
- [ ] Testing: 30 (example)
- [ ] Add context explaining when to use each

### Testing

- [ ] Table shows all values with context
- [ ] Default value matches code

---

## Implementation Notes

See detailed report: `.claude-coord/reports/docs-review-20260130-223705.md`

**Generated from:** Documentation review 2026-01-30  
**Source:** Automated documentation audit (6 specialized agents)
