# Task: Add rate limiting for LLM API calls

## Summary

Create RateLimiter class. Add to each provider. Track costs. Implement circuit breaker on budget.

**Estimated Effort:** 5.0 hours
**Module:** agents

---

## Files to Create

_None_

---

## Files to Modify

- src/agents/llm_providers.py - Implement token bucket rate limiter

---

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Token bucket rate limiter per provider
- [ ] Cost budgets with circuit breaking
- [ ] Daily/hourly spend limits
- [ ] Alerts for abnormal usage
### TESTING
- [ ] Test rate limit enforcement
- [ ] Test budget exhaustion
- [ ] Test alert triggers
- [ ] Test provider isolation

---

## Implementation Details

Create RateLimiter class. Add to each provider. Track costs. Implement circuit breaker on budget.

---

## Test Strategy

Generate burst traffic. Verify rate limiting. Test budget limits. Check alerts.

---

## Success Metrics

- [ ] Costs controlled
- [ ] Rate limits enforced
- [ ] Alerts functional

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** LLMProvider, OpenAIProvider, AnthropicProvider

---

## Design References

- .claude-coord/reports/code-review-20260128-224245.md#13-missing-rate-limiting

---

## Notes

No additional notes

