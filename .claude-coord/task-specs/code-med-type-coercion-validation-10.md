# Task: Add type validation before coercion in metrics

## Summary

Add try-except around coercion. Check isinstance(value, (int, float)). Log warnings for skipped metrics.

**Estimated Effort:** 2.0 hours
**Module:** experimentation

---

## Files to Create

_None_

---

## Files to Modify

- src/experimentation/metrics_collector.py - Add type checking before float() coercion

---

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Check isinstance before coercion
- [ ] Skip invalid metrics with warning
- [ ] Log metric name and type
- [ ] Continue processing other metrics
### TESTING
- [ ] Test with valid numeric types
- [ ] Test with strings
- [ ] Test with booleans
- [ ] Test with None
- [ ] Verify warnings logged

---

## Implementation Details

Add try-except around coercion. Check isinstance(value, (int, float)). Log warnings for skipped metrics.

---

## Test Strategy

Test with various invalid types. Verify warnings logged. Ensure processing continues.

---

## Success Metrics

- [ ] No crashes on invalid data
- [ ] Invalid metrics logged
- [ ] Valid metrics processed

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** MetricsCollector

---

## Design References

- .claude-coord/reports/code-review-20260128-224245.md#12-unsafe-type-coercion

---

## Notes

No additional notes

