# Task: Replace MD5 with modern hash function

## Summary

Use hashlib.sha256(). Add comment about determinism vs security. Consider xxHash for performance.

**Estimated Effort:** 1.0 hours
**Module:** experimentation

---

## Files to Create

_None_

---

## Files to Modify

- src/experimentation/assignment.py - Replace MD5 with SHA256 or xxHash

---

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Replace hashlib.md5() with hashlib.sha256()
- [ ] Add comment explaining crypto strength not required
- [ ] Update tests if hash values hardcoded
- [ ] Maintain deterministic assignment
### TESTING
- [ ] Verify deterministic output
- [ ] Test variant distribution
- [ ] Check performance acceptable

---

## Implementation Details

Use hashlib.sha256(). Add comment about determinism vs security. Consider xxHash for performance.

---

## Test Strategy

Verify same input produces same hash. Check variant distribution unchanged.

---

## Success Metrics

- [ ] Modern hash function used
- [ ] Performance acceptable
- [ ] Assignment deterministic

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** HashBasedAssignment

---

## Design References

- .claude-coord/reports/code-review-20260128-224245.md#9-md5-usage

---

## Notes

No additional notes

