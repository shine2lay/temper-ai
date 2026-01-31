# Task: Remove unused imports and organize imports

## Summary

Run isort. Remove unused. Configure isort in pyproject.toml. Add pre-commit hook.

**Estimated Effort:** 2.0 hours
**Module:** Multiple

---

## Files to Create

_None_

---

## Files to Modify

- src/compiler/langgraph_engine.py - Remove unused asyncio
- src/core/service.py - Move imports to module level

---

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Remove all unused imports
- [ ] Organize imports (stdlib, third-party, local)
- [ ] Use isort for automation
- [ ] Add to pre-commit hook
### TESTING
- [ ] Run isort
- [ ] Verify no unused imports
- [ ] Tests still pass

---

## Implementation Details

Run isort. Remove unused. Configure isort in pyproject.toml. Add pre-commit hook.

---

## Test Strategy

Run pylint/flake8 for unused imports. Run isort --check. Verify tests pass.

---

## Success Metrics

- [ ] No unused imports
- [ ] Organized imports
- [ ] Automated checking

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** All modules

---

## Design References

- .claude-coord/reports/code-review-20260128-224245.md#19-unused-imports

---

## Notes

No additional notes

