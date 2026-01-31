# Task: Add namespace prefix to cache keys

## Summary

Add namespace to __init__. Prefix in generate_key(). Test isolation.

**Estimated Effort:** 2.0 hours
**Module:** cache

---

## Files to Create

_None_

---

## Files to Modify

- src/cache/llm_cache.py - Add namespace parameter and prefix keys

---

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Add namespace parameter to __init__
- [ ] Prefix all keys with namespace:
- [ ] Support multiple applications on same cache
- [ ] Default namespace from config
### TESTING
- [ ] Test with different namespaces
- [ ] Verify key isolation
- [ ] Test shared cache backend

---

## Implementation Details

Add namespace to __init__. Prefix in generate_key(). Test isolation.

---

## Test Strategy

Create two caches with different namespaces. Verify isolation. Test shared backend.

---

## Success Metrics

- [ ] Cache isolation working
- [ ] Multi-tenant safe
- [ ] No key collisions

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** LLMCache

---

## Design References

- .claude-coord/reports/code-review-20260128-224245.md#7-cache-namespace

---

## Notes

No additional notes

