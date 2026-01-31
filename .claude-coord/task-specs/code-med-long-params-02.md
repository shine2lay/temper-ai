# Task: Replace long parameter lists with configuration objects

## Summary

Use @dataclass. Provide from_dict() method. Support both config object and **kwargs.

**Estimated Effort:** 4.0 hours
**Module:** observability

---

## Files to Create

_None_

---

## Files to Modify

- src/observability/tracker.py - Create WorkflowConfig dataclass for track_workflow()
- src/observability/buffer.py - Create BufferConfig dataclass

---

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Create WorkflowConfig with all 12 parameters
- [ ] Create BufferConfig for buffer initialization
- [ ] Update method signatures
- [ ] Maintain backward compatibility with kwargs
### TESTING
- [ ] Test with config objects
- [ ] Test backward compatibility
- [ ] Verify all parameters work

---

## Implementation Details

Use @dataclass. Provide from_dict() method. Support both config object and **kwargs.

---

## Test Strategy

Test both old and new calling patterns. Verify all parameters validated.

---

## Success Metrics

- [ ] API clearer and more maintainable
- [ ] Type safety improved
- [ ] Backward compatible

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** ExecutionTracker, Buffer

---

## Design References

- .claude-coord/reports/code-review-20260128-224245.md#10-long-parameter-lists

---

## Notes

No additional notes

