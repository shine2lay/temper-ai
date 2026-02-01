# Task: Remove ServiceFactory references from security docs

## Summary

Documentation references ServiceFactory but class doesn't exist in codebase.

**Priority:** CRITICAL  
**Category:** doc-code-mismatch  
**Impact:** CRITICAL - Integration examples won't work

---

## Files to Create

_None_

---

## Files to Modify

- `docs/security/M4_SAFETY_SYSTEM.md` - Update documentation

---

## Current State

**Location:** docs/security/M4_SAFETY_SYSTEM.md:481-494

**Current:** from src.core.service_factory import ServiceFactory

**Should be:** Remove or document actual service registration

---

## Acceptance Criteria

### Core Functionality

- [ ] Remove ServiceFactory references
- [ ] OR document actual service registration pattern
- [ ] Update integration examples

### Testing

- [ ] Verify examples use only existing classes
- [ ] Check src/core/ doesn't have service_factory.py

---

## Implementation Notes

See detailed report: `.claude-coord/reports/docs-review-20260130-223705.md`

**Generated from:** Documentation review 2026-01-30  
**Source:** Automated documentation audit (6 specialized agents)
