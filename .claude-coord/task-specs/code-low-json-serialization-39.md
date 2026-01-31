# Task: Add JSON serialization error handling

## Summary

Wrap json.dumps in try-except. On TypeError, use repr() for problematic values. Log warning.

**Estimated Effort:** 1.0 hours
**Module:** cache

---

## Files to Create

_None_

---

## Files to Modify

- src/cache/llm_cache.py - Handle TypeError in generate_key

---

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Catch TypeError from json.dumps
- [ ] Fallback to repr() for non-serializable values
- [ ] Log warning about fallback
- [ ] Still generate deterministic key
### TESTING
- [ ] Test with function parameters
- [ ] Test with class instances
- [ ] Test with normal values
- [ ] Verify keys still unique

---

## Implementation Details

Wrap json.dumps in try-except. On TypeError, use repr() for problematic values. Log warning.

---

## Test Strategy

Pass non-serializable objects. Verify fallback works. Check key uniqueness.

---

## Success Metrics

- [ ] No crashes on bad input
- [ ] Graceful degradation
- [ ] Keys still unique

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** LLMCache.generate_key

---

## Design References

- .claude-coord/reports/code-review-20260128-224245.md#20-json-serialization

---

## Notes

No additional notes

