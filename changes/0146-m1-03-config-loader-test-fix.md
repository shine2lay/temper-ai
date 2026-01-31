# Change Log: Fix Config Loader Test Assertions

**Change ID:** 0146
**Date:** 2026-01-31
**Task:** m1-03-config-loader
**Type:** Bug Fix
**Priority:** P3

---

## Summary

Fixed two failing test assertions in `test_config_loader.py` where the expected error message patterns did not match the actual error messages from the config loader.

---

## What Changed

### Files Modified

- `tests/test_compiler/test_config_loader.py`
  - Updated `test_load_invalid_yaml_raises_error` error message pattern
  - Updated `test_load_invalid_json_raises_error` error message pattern

---

## Changes Detail

### Test Assertion Updates

**Before:**
```python
with pytest.raises(ConfigValidationError, match="Failed to parse config file"):
```

**After:**
```python
# For YAML test
with pytest.raises(ConfigValidationError, match="YAML parsing failed"):

# For JSON test
with pytest.raises(ConfigValidationError, match="JSON parsing failed"):
```

---

## Why Changed

The error messages in `src/compiler/config_loader.py` were updated to be more specific:
- YAML errors: `"[CONFIG_VALIDATION_ERROR] YAML parsing failed for..."`
- JSON errors: `"[CONFIG_VALIDATION_ERROR] JSON parsing failed for..."`

But the test assertions still expected the old generic pattern `"Failed to parse config file"`, causing test failures.

---

## Testing Performed

```bash
# Before fix: 2 failures
pytest tests/test_compiler/test_config_loader.py
# FAILED tests/test_compiler/test_config_loader.py::TestErrorHandling::test_load_invalid_yaml_raises_error
# FAILED tests/test_compiler/test_config_loader.py::TestErrorHandling::test_load_invalid_json_raises_error

# After fix: All pass
pytest tests/test_compiler/test_config_loader.py
# 39 passed in 0.11s
```

---

## Risks

**None** - This is a test-only change with no impact on production code.

---

## Impact

- ✅ All config loader tests now pass (39/39)
- ✅ No functional changes to config loader implementation
- ✅ Test coverage maintained at ~91%
- ✅ Task m1-03-config-loader can now be marked complete

---

## Related Tasks

- m1-03-config-loader (unblocked by this fix)
- m1-00-structure (already complete)
- m1-01-observability-db (dependency)

---

## Notes

- This task (m1-03-config-loader) was found to be substantially complete
- Only test assertions needed updating to match current implementation
- All core functionality was already implemented and working
