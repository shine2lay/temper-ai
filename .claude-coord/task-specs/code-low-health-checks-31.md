# Task: Add health check endpoints to services

## Summary

Create health() method. Test DB connection. Test cache. Return dict with status, checks, timestamp.

**Estimated Effort:** 3.0 hours
**Module:** experimentation

---

## Files to Create

_None_

---

## Files to Modify

- src/experimentation/service.py - Add health() method

---

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Add health() method
- [ ] Check database connectivity
- [ ] Check cache availability
- [ ] Verify critical dependencies
- [ ] Return structured status
### TESTING
- [ ] Test healthy state
- [ ] Test database down
- [ ] Test cache unavailable
- [ ] Verify status structure

---

## Implementation Details

Create health() method. Test DB connection. Test cache. Return dict with status, checks, timestamp.

---

## Test Strategy

Mock DB/cache failures. Verify health status correct. Test with orchestration tools.

---

## Success Metrics

- [ ] Health status accurate
- [ ] Works with Kubernetes
- [ ] Structured response

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** ExperimentService

---

## Design References

- .claude-coord/reports/code-review-20260128-224245.md#19-health-checks

---

## Notes

No additional notes

