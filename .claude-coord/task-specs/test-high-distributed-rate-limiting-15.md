# Task: Add distributed rate limiting tests

## Summary

def test_rate_limit_across_instances(redis_client):
    from multiprocessing import Process
    def make_requests(agent_id, count):
        limiter = RateLimiter(redis_client)
        for i in range(count):
            limiter.check_rate_limit(agent_id)
    # 2 processes, each trying 60 requests
    # Limit: 100/min total
    p1 = Process(target=make_requests, args=('agent-1', 60))
    p2 = Process(target=make_requests, args=('agent-1', 60))
    # Should succeed: 100 total, fail: 20 total

**Priority:** HIGH  
**Estimated Effort:** 12.0 hours  
**Module:** Safety  
**Issues Addressed:** 2

---

## Files to Create

- `tests/test_safety/test_distributed_rate_limiting.py` - Multi-instance rate limiting coordination tests

---

## Files to Modify

_None_

---

## Acceptance Criteria


### Core Functionality

- [ ] Shared state coordination (Redis/memcached)
- [ ] Concurrent requests from multiple processes
- [ ] Clock skew handling across instances
- [ ] Cache invalidation timing
- [ ] Agent ID normalization (case sensitivity, Unicode)

### Testing

- [ ] 10+ distributed scenarios
- [ ] Test with 2, 3, 5 concurrent processes
- [ ] Verify rate limits enforced globally
- [ ] Test clock skew scenarios


---

## Implementation Details

def test_rate_limit_across_instances(redis_client):
    from multiprocessing import Process
    def make_requests(agent_id, count):
        limiter = RateLimiter(redis_client)
        for i in range(count):
            limiter.check_rate_limit(agent_id)
    # 2 processes, each trying 60 requests
    # Limit: 100/min total
    p1 = Process(target=make_requests, args=('agent-1', 60))
    p2 = Process(target=make_requests, args=('agent-1', 60))
    # Should succeed: 100 total, fail: 20 total

---

## Test Strategy

Use Redis for shared state. Spawn multiple processes. Verify global rate limits. Test clock skew scenarios.

---

## Success Metrics

- [ ] Multi-instance coordination verified
- [ ] Rate limits enforced globally
- [ ] Clock skew handled
- [ ] No bypass via multiple instances

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** RateLimiter, Redis, DistributedCache

---

## Design References

- .claude-coord/reports/test-review-20260130-223857.md#35-distributed-rate-limiting-not-tested-high---security

---

## Notes

Critical for distributed deployments. Currently only tests single-instance rate limiting.
