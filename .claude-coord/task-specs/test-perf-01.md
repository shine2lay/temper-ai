# Task: test-perf-01 - Add Template Compilation Caching Tests

**Priority:** HIGH
**Effort:** 2 hours
**Status:** pending
**Owner:** unassigned
**Category:** Performance & Infrastructure (P1)

---

## Summary
Test that PromptEngine caches compiled templates for performance.

---

## Files to Modify
- `tests/test_compiler/test_prompt_engine.py` - Add caching tests
- `src/compiler/prompt_engine.py` - Implement caching if needed

---

## Acceptance Criteria

### Caching Behavior
- [ ] Templates compiled once and cached
- [ ] Cache key includes template content
- [ ] Cache invalidated when template changes
- [ ] LRU or TTL cache policy

### Performance
- [ ] Cached renders >10x faster than first render
- [ ] Cache hit rate >90% in typical usage
- [ ] Memory usage reasonable (<100MB for 1000 templates)

---

## Implementation Details

```python
def test_prompt_engine_caches_compiled_templates():
    """Test templates are compiled once and cached."""
    import time
    engine = PromptEngine()
    template = "Hello {{ name }}"
    
    # First render (compilation + render)
    start = time.time()
    engine.render(template, {"name": "Alice"})
    first_time = time.time() - start
    
    # Second render (cache hit)
    start = time.time()
    engine.render(template, {"name": "Bob"})
    second_time = time.time() - start
    
    # Cached version should be >5x faster
    assert second_time < first_time * 0.2
```

---

## Success Metrics
- [ ] Caching implemented and tested
- [ ] Performance improvement >5x on cache hit

---

## Dependencies
- **Blocked by:** None
- **Blocks:** None

---

## Design References
- QA Report: test_prompt_engine.py - Template Caching (P1)
