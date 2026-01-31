# Task: m3-12-quality-gates - Implement Quality Gates for Stage Output

**Priority:** NORMAL (P2)  
**Effort:** 8 hours  
**Status:** pending  
**Owner:** unassigned

## Summary
Add quality gate checks after synthesis to validate output quality before proceeding. Supports min_confidence, min_findings, require_citations checks.

## Files to Modify
- `src/compiler/langgraph_compiler.py` - Add quality gate node

## Acceptance Criteria
- [ ] Check `min_confidence` threshold (fail if below)
- [ ] Check `min_findings` count (fail if too few)
- [ ] Check `require_citations` if enabled
- [ ] Configurable action on failure: `retry_stage | escalate | proceed_with_warning`
- [ ] Track quality gate failures in observability
- [ ] Retry logic with max attempts
- [ ] E2E test with passing and failing gates

## Config Example
```yaml
quality_gates:
  enabled: true
  min_confidence: 0.7
  min_findings: 5
  require_citations: true
  on_failure: retry_stage  # or escalate, proceed_with_warning
  max_retries: 2
```

## Dependencies
- Blocked by: m3-09-synthesis-node

## Notes
Reliability feature. Prevents low-quality outputs from propagating through workflow.
