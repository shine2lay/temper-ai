# Task: Standardize TTL handling across cache backends

## Summary

Add TTL validation. Warn on invalid values. Treat <=0 as None. Document in set() method.

**Estimated Effort:** 2.0 hours
**Module:** cache

---

## Files to Create

_None_

---

## Files to Modify

- src/cache/llm_cache.py - Consistent TTL=0 and None handling

---

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Validate TTL values
- [ ] TTL <= 0 → warning + no expiration
- [ ] TTL = None → no expiration
- [ ] Consistent across InMemoryCache and RedisCache
- [ ] Document behavior
### TESTING
- [ ] Test TTL=0
- [ ] Test TTL=None
- [ ] Test TTL=-1
- [ ] Verify consistency

---

## Implementation Details

Add TTL validation. Warn on invalid values. Treat <=0 as None. Document in set() method.

---

## Test Strategy

Test all TTL edge cases. Verify consistent behavior. Check documentation.

---

## Success Metrics

- [ ] Consistent TTL handling
- [ ] Documented behavior
- [ ] No surprises

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** InMemoryCache, RedisCache

---

## Design References

- .claude-coord/reports/code-review-20260128-224245.md#11-inconsistent-ttl

---

## Notes

No additional notes

