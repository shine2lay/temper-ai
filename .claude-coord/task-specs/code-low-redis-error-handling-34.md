# Task: Improve Redis error handling specificity

## Summary

Add specific exception handlers. Use appropriate log levels. Re-raise auth errors.

**Estimated Effort:** 2.0 hours
**Module:** cache

---

## Files to Create

_None_

---

## Files to Modify

- src/cache/llm_cache.py - Catch specific Redis exceptions

---

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Catch redis.ConnectionError separately
- [ ] Catch redis.TimeoutError separately
- [ ] Catch redis.AuthenticationError and raise
- [ ] Different log levels for different errors
### TESTING
- [ ] Test connection errors
- [ ] Test timeouts
- [ ] Test auth failures
- [ ] Verify logging

---

## Implementation Details

Add specific exception handlers. Use appropriate log levels. Re-raise auth errors.

---

## Test Strategy

Mock different Redis failures. Verify correct exception handling. Check logs.

---

## Success Metrics

- [ ] Better error diagnostics
- [ ] Appropriate handling
- [ ] Clear logging

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** RedisCache

---

## Design References

- .claude-coord/reports/code-review-20260128-224245.md#8-redis-error-handling

---

## Notes

No additional notes

