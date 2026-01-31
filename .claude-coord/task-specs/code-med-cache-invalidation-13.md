# Task: Implement cache invalidation for experiments

## Summary

Add timestamp to cache entries. Check TTL on access. Invalidate cache on mutations. Add metrics.

**Estimated Effort:** 3.0 hours
**Module:** experimentation

---

## Files to Create

_None_

---

## Files to Modify

- src/experimentation/service.py - Add cache TTL and invalidation logic

---

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Add TTL to cache entries
- [ ] Invalidate on update operations
- [ ] Consider Redis for distributed cache
- [ ] Add cache hit/miss metrics
### TESTING
- [ ] Test TTL expiration
- [ ] Test invalidation on updates
- [ ] Test distributed scenario
- [ ] Verify metrics tracked

---

## Implementation Details

Add timestamp to cache entries. Check TTL on access. Invalidate cache on mutations. Add metrics.

---

## Test Strategy

Test cache expiration. Update experiment and verify cache cleared. Test metrics.

---

## Success Metrics

- [ ] No stale data served
- [ ] Cache metrics available
- [ ] Distributed-safe

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** ExperimentService

---

## Design References

- .claude-coord/reports/code-review-20260128-224245.md#11-experiment-cache

---

## Notes

No additional notes

