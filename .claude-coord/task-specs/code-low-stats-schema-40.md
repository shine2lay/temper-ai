# Task: Standardize get_stats schema across backends

## Summary

Add backend-specific stats. Use -1 for N/A. Document expected schema.

**Estimated Effort:** 1.0 hours
**Module:** cache

---

## Files to Create

_None_

---

## Files to Modify

- src/cache/llm_cache.py - Return consistent stats structure

---

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Add size, max_size, evictions to Redis stats
- [ ] Use -1 or null for unavailable metrics
- [ ] Document schema in docstring
- [ ] Consistent across backends
### TESTING
- [ ] Test InMemoryCache stats
- [ ] Test RedisCache stats
- [ ] Verify schema consistent
- [ ] Check documentation

---

## Implementation Details

Add backend-specific stats. Use -1 for N/A. Document expected schema.

---

## Test Strategy

Call get_stats on both backends. Verify schema matches. Check documentation.

---

## Success Metrics

- [ ] Consistent schema
- [ ] Better monitoring
- [ ] Documented API

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** LLMCache, CacheBackend

---

## Design References

- .claude-coord/reports/code-review-20260128-224245.md#21-stats-schema

---

## Notes

No additional notes

