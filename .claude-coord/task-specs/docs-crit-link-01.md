# Task: Fix broken internal links in README and QUICK_START

## Summary

Multiple broken internal links due to case mismatch and wrong paths.

**Priority:** CRITICAL  
**Category:** broken-links  
**Impact:** HIGH - Users can't navigate documentation

---

## Files to Create

_None_

---

## Files to Modify

_None_

---

## Current State

**Location:** README.md, QUICK_START.md

**Current:** Links to configuration.md, observability.md, etc.

**Should be:** Correct paths and case

---

## Acceptance Criteria

### Core Functionality

- [ ] README.md:276 → ./docs/CONFIGURATION.md (fix case)
- [ ] README.md:277 → fix or remove observability.md link
- [ ] QUICK_START.md:266 → correct path to multi_agent_collaboration.md
- [ ] QUICK_START.md:267 → correct path to collaboration_strategies.md
- [ ] Verify all internal links work

### Testing

- [ ] Run link checker
- [ ] Manually test all links in README and QUICK_START

---

## Implementation Notes

See detailed report: `.claude-coord/reports/docs-review-20260130-223705.md`

**Generated from:** Documentation review 2026-01-30  
**Source:** Automated documentation audit (6 specialized agents)
