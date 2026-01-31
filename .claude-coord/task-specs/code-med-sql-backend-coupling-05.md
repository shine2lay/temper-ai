# Task: Move SQL-specific logic from tracker to backend

## Summary

Define abstract method in base. Implement in SQL backend. Call from tracker.

**Estimated Effort:** 5.0 hours
**Module:** observability

---

## Files to Create

_None_

---

## Files to Modify

- src/observability/tracker.py - Remove SQL aggregation logic
- src/observability/backends/base.py - Add aggregate_workflow_metrics to interface
- src/observability/backends/sql_backend.py - Implement SQL-specific aggregation

---

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Add aggregate_workflow_metrics() to ObservabilityBackend ABC
- [ ] Implement in SQLBackend
- [ ] Remove SQL logic from tracker
- [ ] Non-SQL backends return empty metrics
### TESTING
- [ ] Test with SQL backend
- [ ] Test with non-SQL backend
- [ ] Verify metrics correct

---

## Implementation Details

Define abstract method in base. Implement in SQL backend. Call from tracker.

---

## Test Strategy

Unit tests for each backend. Integration tests for metric accuracy.

---

## Success Metrics

- [ ] Backend abstraction maintained
- [ ] SQL logic isolated
- [ ] Non-SQL backends work

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** ExecutionTracker, ObservabilityBackend

---

## Design References

- .claude-coord/reports/code-review-20260128-224245.md#12-tight-backend-coupling

---

## Notes

No additional notes

