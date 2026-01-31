# Change: Update pytest-xdist Install Instructions

**Task:** docs-low-update-02
**Date:** 2026-01-31
**Priority:** P4 (Low)
**Category:** Documentation - Accuracy

---

## Summary

Updated pytest-xdist installation instructions to reference dev dependencies as primary method, with manual install as alternative.

---

## What Changed

### Files Modified

**pyproject.toml:**
- Added `pytest-xdist>=3.0` to dev dependencies (line 56)

**docs/TESTING.md:**
- Updated "Parallel Execution" section (lines 235-255)
- Added note that pytest-xdist is in dev dependencies
- Shows `pip install -e '.[dev]'` as primary installation method
- Keeps manual `pip install pytest-xdist` as alternative

---

## Why

**Problem:** Documentation showed only manual pip install for pytest-xdist, not referencing dev dependencies. This created confusion about whether pytest-xdist was a standard dev dependency.

**Root Cause:** pytest-xdist was NOT in dev dependencies, so manual install was technically correct. However, parallel execution is a standard testing feature and should be included.

**Solution:**
1. Added pytest-xdist to dev dependencies
2. Updated docs to reference dev dependencies

**Impact:** Low - Minor improvement to installation clarity

---

## Testing Performed

1. **Dependency verification:**
   - ✅ pytest-xdist>=3.0 in pyproject.toml dev dependencies
   - ✅ Command syntax `pip install -e '.[dev]'` is correct

2. **Documentation accuracy:**
   - ✅ Instructions reference dev dependencies
   - ✅ Manual install shown as alternative
   - ✅ Clear explanatory note added

3. **Code review:**
   - ✅ Zero issues found
   - ✅ All acceptance criteria met

---

## Risks & Mitigations

**Risk:** None - Additive change only

**Breaking Changes:** None

**Backward Compatibility:** ✓ Manual install still documented as alternative

---

## Acceptance Criteria

### Core Functionality ✅

- [x] Update to: pip install -e '.[dev]'
- [x] Note that pytest-xdist is in dev dependencies
- [x] Show manual install as alternative

### Testing ✅

- [x] Instructions reference dev dependencies
- [x] Command works correctly

---

## References

- Task spec: `.claude-coord/task-specs/docs-low-update-02.md`
- Code review: agent-a224226
- Implementation audit: agent-a87a5d9
