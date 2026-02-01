# Task: Add ObservabilityBuffer integration test

## Summary

def test_observability_buffer_reduces_queries(self, db):
    query_count = 0
    def count_queries(*args, **kwargs):
        nonlocal query_count
        query_count += 1
    with patch('db.execute', side_effect=count_queries):
        buffer = ObservabilityBuffer(max_size=10, flush_interval=1.0)
        for i in range(100):
            buffer.track_event(Event(...))
        buffer.flush()
    assert query_count < 15  # <15 queries for 100 events (>85% reduction)

**Priority:** HIGH  
**Estimated Effort:** 6.0 hours  
**Module:** Observability  
**Issues Addressed:** 1

---

## Files to Create

- `tests/test_observability/test_buffer_integration.py` - E2E test showing 90%+ query reduction with buffering

---

## Files to Modify

_None_

---

## Acceptance Criteria


### Core Functionality

- [ ] Buffer 100+ observability events
- [ ] Flush buffer to database in batches
- [ ] Verify 90%+ query reduction vs non-buffered
- [ ] Test buffer overflow scenarios
- [ ] Test flush on timeout vs size

### Testing

- [ ] E2E test with 100 operations
- [ ] Count actual DB queries
- [ ] Verify <10 queries vs 100 non-buffered
- [ ] Test buffer size limits
- [ ] Test timeout-based flushing


---

## Implementation Details

def test_observability_buffer_reduces_queries(self, db):
    query_count = 0
    def count_queries(*args, **kwargs):
        nonlocal query_count
        query_count += 1
    with patch('db.execute', side_effect=count_queries):
        buffer = ObservabilityBuffer(max_size=10, flush_interval=1.0)
        for i in range(100):
            buffer.track_event(Event(...))
        buffer.flush()
    assert query_count < 15  # <15 queries for 100 events (>85% reduction)

---

## Test Strategy

Use real buffer with mocked DB. Count actual queries. Compare buffered vs non-buffered. Verify query reduction.

---

## Success Metrics

- [ ] Query reduction >85%
- [ ] Buffer overflow handled
- [ ] Timeout flushing works
- [ ] Integration test passes

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** ObservabilityBuffer, ObservabilityTracker, DatabaseManager

---

## Design References

- .claude-coord/reports/test-review-20260130-223857.md#critical-paths-without-tests

---

## Notes

Currently only theoretical calculation exists. Need real integration test.
