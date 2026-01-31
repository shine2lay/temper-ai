# Task: Standardize logging levels across codebase

## Summary

Create guidelines doc. Audit all logging calls. Move routine logs to DEBUG. Add sampling for frequent logs.

**Estimated Effort:** 3.0 hours
**Module:** Multiple

---

## Files to Create

_None_

---

## Files to Modify

- docs/logging_guidelines.md - Create logging level guidelines
- src/agents/llm_failover.py - Fix routine INFO logs
- src/tools/executor.py - Add log sampling

---

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Define logging level policy
- [ ] DEBUG for routine operations
- [ ] INFO for significant state changes
- [ ] WARNING for degraded states
- [ ] ERROR for failures requiring attention
- [ ] Add sampling for high-frequency logs
### TESTING
- [ ] Review log output at each level
- [ ] Verify production logs clean
- [ ] Check sampling works

---

## Implementation Details

Create guidelines doc. Audit all logging calls. Move routine logs to DEBUG. Add sampling for frequent logs.

---

## Test Strategy

Run in production mode. Review log volume. Verify important events visible.

---

## Success Metrics

- [ ] Clear logging policy
- [ ] Production logs useful
- [ ] Log volume manageable

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** All modules

---

## Design References

- .claude-coord/reports/code-review-20260128-224245.md#16-inconsistent-logging

---

## Notes

No additional notes

