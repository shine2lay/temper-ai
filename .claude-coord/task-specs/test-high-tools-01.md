# Task: test-high-tools-01 - Add Tool Parameter Sanitization and Registry Tests

**Priority:** HIGH
**Effort:** 2.5 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Add tests for URL-decoded path traversal detection and tool registry error handling (import failures, circular imports).

---

## Files to Create

- None

---

## Files to Modify

- `tests/test_tools/test_parameter_sanitization.py - Add URL decoding tests`
- `tests/test_tools/test_registry.py - Add error handling tests`

---

## Acceptance Criteria


### Core Functionality
- [ ] Test URL-decoded path traversal detection
- [ ] Test module import failure handling
- [ ] Test circular import detection
- [ ] Verify sanitization happens after URL decoding

### Testing
- [ ] URL decoding: test %2e%2e%2f%2e%2e%2f patterns
- [ ] Import failures: test missing modules, syntax errors
- [ ] Circular imports: test A imports B imports A
- [ ] Edge case: double-encoded attacks

### Security Controls
- [ ] URL decode before path validation
- [ ] Graceful failure on import errors
- [ ] Circular import detection

---

## Implementation Details

```python
def test_url_encoded_path_traversal_detection():
    """Test URL-encoded path traversal is detected"""
    encoded_attacks = [
        "%2e%2e%2f%2e%2e%2fetc%2fpasswd",  # ../../../etc/passwd
        "..%252f..%252fetc%252fpasswd",    # Double-encoded
        "%2e%2e/%2e%2e/etc/passwd",        # Mixed encoding
    ]

    for attack in encoded_attacks:
        with pytest.raises(SecurityViolation, match="Path traversal"):
            sanitize_file_path(attack)

def test_tool_registry_module_import_failure():
    """Test registry handles module import failures gracefully"""
    registry = ToolRegistry()

    # Test missing module
    with pytest.raises(ToolLoadError, match="Module not found"):
        registry.register_tool("nonexistent.module.Tool")

    # Test syntax error in module
    with pytest.raises(ToolLoadError, match="Syntax error"):
        registry.register_tool("broken_syntax_module.Tool")

def test_tool_registry_circular_import_detection():
    """Test circular import detection"""
    # Create circular dependency: tool_a imports tool_b imports tool_a
    registry = ToolRegistry()

    with pytest.raises(CircularImportError, match="Circular dependency"):
        registry.register_tool("circular_a.Tool")
```

---

## Test Strategy

Test URL decoding edge cases. Test import error scenarios. Test circular import detection.

---

## Success Metrics

- [ ] URL-encoded attacks detected
- [ ] Import failures handled gracefully
- [ ] Circular imports detected

---

## Dependencies

- **Blocked by:** None
- **Blocks:** None
- **Integrates with:** ParameterSanitizer, ToolRegistry

---

## Design References

- .claude-coord/reports/test-review-20260128-200844.md - Section 2, High Issues #11-12

---

## Notes

Use urllib.parse.unquote for URL decoding. Test double-encoding attacks.
