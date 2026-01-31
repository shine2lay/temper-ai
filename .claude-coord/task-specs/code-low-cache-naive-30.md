# Task: Upgrade template cache to proper LRU implementation

## Summary

Use @lru_cache decorator or cachetools.LRUCache. Add size tracking. Implement cache warming.

**Estimated Effort:** 2.0 hours
**Module:** agents

---

## Files to Create

_None_

---

## Files to Modify

- src/agents/prompt_engine.py - Replace dict cache with functools.lru_cache or cachetools

---

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Use functools.lru_cache(maxsize=100)
- [ ] Add memory size tracking
- [ ] Implement cache warming for hot templates
- [ ] Add cache hit/miss metrics
### TESTING
- [ ] Test cache eviction
- [ ] Test LRU ordering
- [ ] Verify memory bounded
- [ ] Check metrics

---

## Implementation Details

Use @lru_cache decorator or cachetools.LRUCache. Add size tracking. Implement cache warming.

---

## Test Strategy

Test with >maxsize templates. Verify LRU eviction. Check memory usage. Test metrics.

---

## Success Metrics

- [ ] Proper LRU eviction
- [ ] Memory bounded
- [ ] Better hit rates

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** PromptEngine

---

## Design References

- .claude-coord/reports/code-review-20260128-224245.md#23-cache-naive

---

## Notes

No additional notes

