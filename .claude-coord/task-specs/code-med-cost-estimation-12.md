# Task: Create configurable pricing system for LLM costs

## Summary

Create pricing config file. Load at initialization. Use model prefix matching. Add version/date tracking.

**Estimated Effort:** 4.0 hours
**Module:** agents

---

## Files to Create

_None_

---

## Files to Modify

- src/agents/standard_agent.py - Create pricing configuration system
- config/llm_pricing.yaml - Create pricing configuration file

---

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Create PRICING_TABLE with model-specific rates
- [ ] Support wildcards (ollama/*)
- [ ] Add pricing version tracking
- [ ] Load from config file
- [ ] Fall back to defaults with warnings
### TESTING
- [ ] Test various models
- [ ] Test pricing updates
- [ ] Test fallback behavior
- [ ] Verify cost calculations

---

## Implementation Details

Create pricing config file. Load at initialization. Use model prefix matching. Add version/date tracking.

---

## Test Strategy

Test with different models. Update pricing and verify reload. Test fallback.

---

## Success Metrics

- [ ] Accurate cost estimates
- [ ] Easy to update pricing
- [ ] Version tracked

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** StandardAgent, _estimate_cost

---

## Design References

- .claude-coord/reports/code-review-20260128-224245.md#10-magic-numbers-cost

---

## Notes

No additional notes

