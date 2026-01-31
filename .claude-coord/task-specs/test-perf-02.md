# Task: test-perf-02 - Add Large Template Performance Tests

**Priority:** NORMAL
**Effort:** 1-2 hours
**Status:** pending
**Owner:** unassigned
**Category:** Performance & Infrastructure (P2)

---

## Summary
Test PromptEngine performance with large templates (10KB+).

---

## Files to Modify
- `tests/test_compiler/test_prompt_engine.py` - Add large template tests

---

## Acceptance Criteria

### Performance Benchmarks
- [ ] 10KB template renders in <50ms
- [ ] 100KB template renders in <500ms
- [ ] Memory efficient (no unnecessary copies)

---

## Implementation Details

```python
def test_prompt_engine_large_template_performance():
    """Benchmark large template rendering."""
    import time
    engine = PromptEngine()
    
    # 10KB template
    large_template = "{% for i in range(1000) %}Item {{ i }}: {{ data }}\n{% endfor %}"
    
    start = time.time()
    result = engine.render(large_template, {"data": "test"})
    elapsed_ms = (time.time() - start) * 1000
    
    assert elapsed_ms < 50
    assert len(result) > 0
```

---

## Success Metrics
- [ ] Large templates render efficiently
- [ ] No performance degradation

---

## Dependencies
- **Blocked by:** None
- **Blocks:** None

---

## Design References
- QA Report: test_prompt_engine.py - Large Templates (P2)
