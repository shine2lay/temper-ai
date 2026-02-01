# Task: Add test marker documentation to pyproject.toml

## Summary

TESTING.md documents markers not in pyproject.toml (integration, security)

**Priority:** LOW  
**Category:** consistency  
**Impact:** LOW - pytest warnings for undeclared markers

---

## Files to Create

_None_

---

## Files to Modify

- `pyproject.toml`
- `docs/TESTING.md`

---

## Current State

**Location:** pyproject.toml, docs/TESTING.md

**Current:** Mismatch between docs and config

**Should be:** All markers in both places

---

## Acceptance Criteria

### Core Functionality

- [ ] Add @pytest.mark.integration to pyproject.toml
- [ ] Add @pytest.mark.security to pyproject.toml
- [ ] OR remove from docs if not used
- [ ] Sync markers between config and docs

### Testing

- [ ] pytest --markers shows all documented markers
- [ ] No warnings about undeclared markers

---

## Implementation Notes

See detailed report: `.claude-coord/reports/docs-review-20260130-223705.md`

**Generated from:** Documentation review 2026-01-30  
**Source:** Automated documentation audit (6 specialized agents)
