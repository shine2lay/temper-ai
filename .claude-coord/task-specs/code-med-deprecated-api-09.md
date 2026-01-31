# Task: Implement proper deprecation for api_key field

## Summary

Update model_validator. Check for both fields. Use logger.error() for deprecation. Document in migration guide.

**Estimated Effort:** 2.0 hours
**Module:** compiler

---

## Files to Create

_None_

---

## Files to Modify

- src/compiler/schemas.py - Add version-based migration and ERROR-level warnings

---

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Add migration logic in model_validator
- [ ] Raise error if both fields specified
- [ ] Log at ERROR level for visibility
- [ ] Document migration path
- [ ] Add removal version (2.0)
### TESTING
- [ ] Test with api_key only
- [ ] Test with api_key_ref only
- [ ] Test with both (should error)
- [ ] Verify warning visibility

---

## Implementation Details

Update model_validator. Check for both fields. Use logger.error() for deprecation. Document in migration guide.

---

## Test Strategy

Test all combinations. Verify errors/warnings appear. Check migration path documented.

---

## Success Metrics

- [ ] Clear deprecation warnings
- [ ] Migration path documented
- [ ] Breaking change planned

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** InferenceConfig

---

## Design References

- .claude-coord/reports/code-review-20260128-224245.md#11-deprecated-api

---

## Notes

No additional notes

