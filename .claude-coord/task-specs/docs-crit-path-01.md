# Task: Fix wrong file paths in security documentation

## Summary

Security docs reference wrong file paths for ApprovalWorkflowPolicy and ResourceLimitPolicy.

**Priority:** CRITICAL  
**Category:** doc-code-mismatch  
**Impact:** CRITICAL - Users can't find referenced files

---

## Files to Create

_None_

---

## Files to Modify

- `docs/security/M4_SAFETY_SYSTEM.md` - Update documentation

---

## Current State

**Location:** docs/security/M4_SAFETY_SYSTEM.md (multiple)

**Current:** approval_workflow.py, resource_limits.py

**Should be:** approval.py, policies/resource_limit_policy.py

---

## Acceptance Criteria

### Core Functionality

- [ ] Fix: src/safety/approval_workflow.py → src/safety/approval.py
- [ ] Fix: src/safety/resource_limits.py → src/safety/policies/resource_limit_policy.py
- [ ] Update all file path references

### Testing

- [ ] Verify: ls -la src/safety/approval.py
- [ ] Verify: ls -la src/safety/policies/resource_limit_policy.py
- [ ] Grep docs for old paths

---

## Implementation Notes

See detailed report: `.claude-coord/reports/docs-review-20260130-223705.md`

**Generated from:** Documentation review 2026-01-30  
**Source:** Automated documentation audit (6 specialized agents)
