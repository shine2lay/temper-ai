# Task: Fix ToolRegistry method names in API documentation

## Summary

ToolRegistry API documentation uses wrong method names. All examples will fail.

**Priority:** CRITICAL  
**Category:** doc-code-mismatch  
**Impact:** CRITICAL - All ToolRegistry examples fail

---

## Files to Create

_None_

---

## Files to Modify

- `docs/API_REFERENCE.md` - Update documentation

---

## Current State

**Location:** docs/API_REFERENCE.md:273-296

**Current:** register_tool(), get_tool(), has_tool()

**Should be:** register(), get(), (has_tool doesn't exist)

---

## Acceptance Criteria

### Core Functionality

- [ ] Replace register_tool() with register()
- [ ] Replace get_tool() with get()
- [ ] Remove has_tool() or document alternative
- [ ] Update all examples

### Testing

- [ ] Verify: python -c 'from src.tools import ToolRegistry; r = ToolRegistry(); hasattr(r, "register")'
- [ ] All ToolRegistry examples work

---

## Implementation Notes

See detailed report: `.claude-coord/reports/docs-review-20260130-223705.md`

**Generated from:** Documentation review 2026-01-30  
**Source:** Automated documentation audit (6 specialized agents)
