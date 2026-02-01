# Task: Fix Strategy class names in API documentation

## Summary

API documentation uses wrong class names for collaboration strategies. Users copying examples will get ImportError.

**Priority:** CRITICAL  
**Category:** doc-code-mismatch  
**Impact:** CRITICAL - All strategy examples cause ImportError

---

## Files to Create

_None_

---

## Files to Modify

- `docs/API_REFERENCE.md` - Update documentation

---

## Current State

**Location:** docs/API_REFERENCE.md:640-685

**Current:** DebateStrategy, MeritWeightedStrategy, HierarchicalStrategy

**Should be:** DebateAndSynthesize, MeritWeightedResolver, (HierarchicalStrategy doesn't exist)

---

## Acceptance Criteria

### Core Functionality

- [ ] Replace DebateStrategy with DebateAndSynthesize
- [ ] Replace MeritWeightedStrategy with MeritWeightedResolver
- [ ] Remove or clarify HierarchicalStrategy (doesn't exist)
- [ ] Update all import examples

### Testing

- [ ] Verify: python -c 'from src.strategies.debate import DebateAndSynthesize'
- [ ] All code examples in docs/API_REFERENCE.md work

---

## Implementation Notes

See detailed report: `.claude-coord/reports/docs-review-20260130-223705.md`

**Generated from:** Documentation review 2026-01-30  
**Source:** Automated documentation audit (6 specialized agents)
