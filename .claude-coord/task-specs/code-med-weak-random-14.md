# Task: Use secrets module for cryptographic randomness

## Summary

Import secrets. Use secrets.SystemRandom().choices(). Add docstring about crypto security.

**Estimated Effort:** 1.0 hours
**Module:** experimentation

---

## Files to Create

_None_

---

## Files to Modify

- src/experimentation/assignment.py - Replace random with secrets for variant selection

---

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Use secrets.SystemRandom() for cryptographic randomness
- [ ] Document security considerations
- [ ] Maintain distribution properties
### TESTING
- [ ] Test distribution unchanged
- [ ] Verify unpredictability
- [ ] Performance acceptable

---

## Implementation Details

Import secrets. Use secrets.SystemRandom().choices(). Add docstring about crypto security.

---

## Test Strategy

Test variant distribution. Verify unpredictability. Check performance impact minimal.

---

## Success Metrics

- [ ] Cryptographically secure
- [ ] Distribution maintained
- [ ] Documented

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** WeightedAssignment

---

## Design References

- .claude-coord/reports/code-review-20260128-224245.md#14-weak-random

---

## Notes

No additional notes

