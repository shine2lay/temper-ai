# Task: Make weak consensus penalty configurable

## Summary

Add parameter to __init__. Store as instance variable. Update synthesize() to use it. Document reasoning.

**Estimated Effort:** 2.0 hours
**Module:** strategies

---

## Files to Create

_None_

---

## Files to Modify

- src/strategies/consensus.py - Add weak_consensus_penalty parameter

---

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Add weak_consensus_penalty parameter to __init__
- [ ] Default value 0.7
- [ ] Document rationale in docstring
- [ ] Use instance variable instead of constant
### TESTING
- [ ] Test with different penalty values
- [ ] Verify default behavior
- [ ] Check edge cases (0.0, 1.0)

---

## Implementation Details

Add parameter to __init__. Store as instance variable. Update synthesize() to use it. Document reasoning.

---

## Test Strategy

Test with penalty=0.5, 0.7, 1.0. Verify confidence calculations correct.

---

## Success Metrics

- [ ] Configurable penalty
- [ ] Documented rationale
- [ ] Tunable per use case

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** ConsensusStrategy

---

## Design References

- .claude-coord/reports/code-review-20260128-224245.md#medium-weak-consensus

---

## Notes

No additional notes

