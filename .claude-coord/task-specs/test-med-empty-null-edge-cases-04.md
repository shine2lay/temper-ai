# Task: test-med-empty-null-edge-cases-04 - Add empty/null/boundary value edge case tests

**Priority:** NORMAL
**Effort:** 8 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

@pytest.mark.parametrize('value', [
    '',  # Empty string
    None,  # Null
    sys.maxsize,  # MAX_INT
    -sys.maxsize,  # MIN_INT
    'x' * 1_000_000,  # 1MB string
])
def test_field_boundary_values(value):
    # Test handling

**Module:** Validation
**Issues Addressed:** 10

---

## Files to Create

_None_

---

## Files to Modify

- `tests/test_validation/test_boundary_values.py` - Add empty/null/MAX_INT edge cases

---

## Acceptance Criteria

### Core Functionality

- [ ] Test empty strings in all string fields
- [ ] Test None/null values in required fields
- [ ] Test zero-length workflow/stage/agent hierarchies
- [ ] Test MAX_INT in numeric fields
- [ ] Test MIN_INT in numeric fields
- [ ] Test empty lists/dicts in collection fields
- [ ] Test extremely long strings (>1MB)
- [ ] Test extremely large configs (100MB)

### Testing

- [ ] 30+ boundary value tests
- [ ] Test both acceptance and rejection
- [ ] Verify helpful error messages
- [ ] No crashes on boundary values

---

## Implementation Details

@pytest.mark.parametrize('value', [
    '',  # Empty string
    None,  # Null
    sys.maxsize,  # MAX_INT
    -sys.maxsize,  # MIN_INT
    'x' * 1_000_000,  # 1MB string
])
def test_field_boundary_values(value):
    # Test handling

---

## Test Strategy

Use parameterized tests for boundaries. Test min, max, empty, null for each field type.

---

## Success Metrics

- [ ] 30+ boundary tests added
- [ ] All boundaries handled gracefully
- [ ] Clear validation errors
- [ ] No crashes

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** _None_

---

## Design References

- .claude-coord/reports/test-review-20260130-223857.md#52-edge-cases-gaps

---

## Notes

Prevents crashes from unexpected inputs. Essential for robustness.
