# Task: test-security-path-injection - Path Safety Edge Cases & Injection Tests

**Priority:** CRITICAL
**Effort:** 2 days
**Status:** pending
**Owner:** unassigned

---

## Summary
Add comprehensive path injection and edge case tests to prevent path traversal, symlink attacks, and encoding bypass.

---

## Files to Create
- `tests/test_security/test_path_injection.py` - New test file for path injection scenarios

---

## Files to Modify
- `tests/test_utils/test_path_safety.py` - Add edge cases to existing tests
- `src/utils/path_safety.py` - Fix any vulnerabilities found

---

## Acceptance Criteria

### Security Controls
- [ ] Test unicode normalization attacks (e.g., %2F%2E%2E%2F for /../)
- [ ] Test TOCTOU race conditions (file changes between validation and use)
- [ ] Test symlink chain depth limits (>40 levels)
- [ ] Test case-insensitive path bypass on Windows
- [ ] Test extremely long paths (>4096 chars)
- [ ] Test null byte injection in paths
- [ ] Test path traversal with mixed separators (/, \)

### Testing
- [ ] All 7 critical path security tests implemented
- [ ] Tests verify rejection of malicious paths
- [ ] Tests check error messages don't leak sensitive info
- [ ] Cross-platform tests (Linux, Windows behavior)

### Coverage
- [ ] path_safety.py coverage >95%
- [ ] All OWASP path traversal vectors tested

---

## Implementation Details

```python
# tests/test_security/test_path_injection.py

import pytest
from src.utils.path_safety import validate_path, PathTraversalError

class TestPathInjectionAttacks:
    """Test path injection and traversal attacks."""
    
    def test_unicode_normalization_bypass(self):
        """Test path traversal via unicode normalization."""
        malicious_paths = [
            "/allowed/path/%2F%2E%2E%2Fetc/passwd",  # URL encoded ../
            "/allowed/path/\u2215\u2215etc/passwd",  # Unicode slashes
            "/allowed/path/\u2216etc/passwd",        # Set minus
        ]
        for path in malicious_paths:
            with pytest.raises(PathTraversalError):
                validate_path(path, allowed_root="/allowed")
    
    def test_toctou_race_condition(self):
        """Test TOCTOU attack on file validation."""
        # Create legitimate file, validate it, then swap with symlink
        # Verify detection of file changes
        pass
    
    def test_symlink_chain_depth_limit(self):
        """Test deeply nested symlink chains are rejected."""
        # Create 50 chained symlinks
        # Verify rejection at depth limit
        pass
    
    def test_case_insensitive_bypass_windows(self, monkeypatch):
        """Test case variations don't bypass forbidden paths."""
        monkeypatch.setattr("sys.platform", "win32")
        forbidden = ["/etc", "/.git", "/proc"]
        bypasses = ["/ETC", "/.GIT", "/PROC", "/.Git", "/Etc"]
        for path in bypasses:
            with pytest.raises(PathTraversalError):
                validate_path(path)
    
    def test_extremely_long_path(self):
        """Test paths exceeding OS limits are rejected."""
        long_path = "/allowed/" + "a" * 5000
        with pytest.raises(ValueError, match="Path too long"):
            validate_path(long_path)
    
    def test_null_byte_injection(self):
        """Test null byte in path is rejected."""
        with pytest.raises(ValueError, match="Null byte"):
            validate_path("/allowed/file\x00.txt")
    
    def test_mixed_path_separators(self):
        """Test mixed separators don't bypass validation."""
        malicious = [
            "/allowed/path\\..\\..\\etc/passwd",
            "/allowed/path/..\\/etc/passwd",
        ]
        for path in malicious:
            with pytest.raises(PathTraversalError):
                validate_path(path, allowed_root="/allowed")
```

---

## Test Strategy

```bash
# Run security tests
pytest tests/test_security/test_path_injection.py -v

# Run with security logging
pytest tests/test_security/ --log-cli-level=DEBUG

# Check coverage
pytest tests/test_security/ --cov=src/utils/path_safety --cov-report=term-missing
```

---

## Success Metrics
- [ ] All 7 path injection tests implemented and passing
- [ ] Coverage >95% for path_safety.py
- [ ] All OWASP path traversal vectors covered
- [ ] Cross-platform tests pass on Linux and Windows

---

## Dependencies
- **Blocked by:** test-fix-failures-04
- **Blocks:** None
- **Integrates with:** src/utils/path_safety.py

---

## Design References
- QA Engineer Report: Test Case #1-5 (Critical path injection scenarios)
- OWASP Path Traversal: https://owasp.org/www-community/attacks/Path_Traversal

---

## Notes
- Test on both Linux and Windows if possible
- Consider fuzzing with pathological inputs
- Verify error messages don't leak internal paths
