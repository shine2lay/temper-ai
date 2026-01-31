# Task: test-fix-failures-01 - Fix Config Loading Test Failures

**Priority:** CRITICAL
**Effort:** 2-3 days
**Status:** pending
**Owner:** unassigned

---

## Summary
Fix 22 failing tests in test_config_loader.py related to environment variable substitution, file extension support, and config caching.

---

## Files to Modify
- `tests/test_compiler/test_config_loader.py` - Fix failing test cases
- `src/compiler/config_loader.py` - Fix environment variable substitution and caching logic

---

## Acceptance Criteria

### Core Functionality
- [ ] All 22 config loading tests pass
- [ ] Environment variable substitution works correctly (${VAR} syntax)
- [ ] Both .yaml and .yml file extensions supported
- [ ] Config caching maintains consistency on file changes
- [ ] Relative path resolution works correctly
- [ ] Template loading from prompts directory succeeds

### Testing
- [ ] Existing tests pass without modification to test logic
- [ ] Add regression tests for each fixed failure pattern
- [ ] Test coverage for config_loader.py remains >90%

### Error Handling
- [ ] Clear error messages for missing environment variables
- [ ] Validation errors show helpful context
- [ ] File not found errors include attempted paths

---

## Implementation Details

**Current Failures:**
- 6 tests failing on environment variable substitution
- 1 test failing on .yml extension support  
- 3 tests failing on config caching
- 5 tests failing on relative path resolution
- 7 tests failing on template loading

**Root Cause Analysis Needed:**
1. Check environment variable regex pattern in config_loader.py
2. Verify file extension handling in load_config()
3. Review cache invalidation logic
4. Test path resolution with different working directories
5. Verify prompts directory path construction

**Implementation Steps:**
1. Run failing tests individually to isolate issues
2. Add debug logging to config_loader.py 
3. Fix environment variable substitution
4. Add .yml extension support
5. Fix cache invalidation logic
6. Verify all tests pass

---

## Test Strategy

```bash
# Run only config loader tests
pytest tests/test_compiler/test_config_loader.py -v

# Run with debugging
pytest tests/test_compiler/test_config_loader.py -v -s --tb=long

# Check coverage
pytest tests/test_compiler/test_config_loader.py --cov=src/compiler/config_loader
```

---

## Success Metrics
- [ ] 0/22 tests failing (100% pass rate)
- [ ] Coverage >90% for config_loader.py
- [ ] No new test failures introduced
- [ ] Regression tests added for each failure pattern

---

## Dependencies
- **Blocked by:** None
- **Blocks:** test-integration-compiler-engine
- **Integrates with:** src/compiler/config_loader.py

---

## Design References
- See QA Engineer analysis: 87 missing test cases report
- Specialist recommendation: Fix failing tests before adding new tests

---

## Notes
- Priority is fixing existing tests, not adding new ones
- Some failures may be due to test environment setup issues
- Check for hardcoded paths or missing test fixtures
