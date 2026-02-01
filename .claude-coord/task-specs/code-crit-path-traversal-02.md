# Task Specification: code-crit-path-traversal-02

## Problem Statement

Template path loading in the compiler has insufficient validation - doesn't check for null bytes or other control characters that could bypass security checks. Attackers could potentially read arbitrary files by crafting malicious template paths with null bytes (e.g., `/allowed/path\x00/../../etc/passwd`).

## Context

- **Source:** Code Review Report 2026-02-01 (Critical Issue #2)
- **File Affected:** `src/compiler/config_loader.py:239`
- **Impact:** Path traversal attacks could read sensitive files
- **Module:** Compiler
- **OWASP Category:** A01:2021 - Broken Access Control

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Add null byte detection to template path validation
- [ ] Add control character detection (0x00-0x1F except \n\r\t)
- [ ] Ensure path validation happens BEFORE Path.resolve()
- [ ] Verify relative_to() check still works correctly

### SECURITY CONTROLS
- [ ] Block null bytes (\x00) in paths
- [ ] Block other dangerous control characters
- [ ] Raise ConfigValidationError with clear message
- [ ] Log security violations for monitoring
- [ ] Validate on EVERY path input, not just user-provided

### TESTING
- [ ] Test null byte attack scenarios
- [ ] Test control character bypasses
- [ ] Test legitimate paths still work
- [ ] Test path traversal attempts are blocked
- [ ] Fuzz testing with malicious inputs

## Implementation Plan

### Step 1: Read Current Implementation

**File:** `src/compiler/config_loader.py:239`

Understand current validation logic.

### Step 2: Add Enhanced Validation

**File:** `src/compiler/config_loader.py`

**Before:**
```python
def load_prompt_template(self, template_path: str) -> str:
    # Existing relative_to() check
    real_path = Path(template_path).resolve()
    if not real_path.is_relative_to(self.template_dir):
        raise ConfigValidationError('Path traversal detected')
```

**After:**
```python
def load_prompt_template(self, template_path: str) -> str:
    # Add null byte check FIRST
    if '\x00' in template_path:
        logger.warning(f"Null byte detected in template path: {template_path!r}")
        raise ConfigValidationError('Invalid template path: null byte detected')

    # Add control character check
    if any(ord(c) < 32 and c not in '\n\r\t' for c in template_path):
        logger.warning(f"Control characters detected in template path: {template_path!r}")
        raise ConfigValidationError('Invalid template path: control characters detected')

    # Existing relative_to() check is good but comes after validation
    real_path = Path(template_path).resolve()
    if not real_path.is_relative_to(self.template_dir):
        logger.warning(f"Path traversal attempt: {template_path} -> {real_path}")
        raise ConfigValidationError('Path traversal detected: path must be within template directory')

    # ... rest of implementation
```

### Step 3: Add Security Logging

Ensure security violations are logged for monitoring and alerting.

### Step 4: Apply Same Validation to All Path Inputs

Search for other places in config_loader.py that accept paths:
```bash
grep -n "Path(" src/compiler/config_loader.py
```

Apply same validation to all path inputs.

## Test Strategy

### Unit Tests

**File:** `tests/compiler/test_config_loader_security.py`

```python
import pytest
from src.compiler.config_loader import ConfigLoader, ConfigValidationError

def test_null_byte_attack_blocked():
    """Test that null byte injection is blocked"""
    loader = ConfigLoader(template_dir="/templates")

    # Null byte can truncate path on some systems
    malicious_path = "/allowed/path\x00/../../etc/passwd"

    with pytest.raises(ConfigValidationError, match="null byte"):
        loader.load_prompt_template(malicious_path)

def test_control_character_attack_blocked():
    """Test that control characters are blocked"""
    loader = ConfigLoader(template_dir="/templates")

    # Control characters might bypass filters
    malicious_path = "/allowed/path\x01/../etc/passwd"

    with pytest.raises(ConfigValidationError, match="control characters"):
        loader.load_prompt_template(malicious_path)

def test_legitimate_path_with_newlines_in_content_allowed():
    """Ensure we don't break legitimate use cases"""
    # Note: newlines in path are usually invalid, but check edge cases
    loader = ConfigLoader(template_dir="/templates")

    # This should work (normal path)
    valid_path = "/templates/prompt.txt"
    # Test implementation...

def test_path_traversal_still_blocked():
    """Ensure original path traversal check still works"""
    loader = ConfigLoader(template_dir="/templates")

    with pytest.raises(ConfigValidationError, match="traversal"):
        loader.load_prompt_template("/templates/../../../etc/passwd")

def test_logging_on_security_violation(caplog):
    """Ensure security violations are logged"""
    loader = ConfigLoader(template_dir="/templates")

    with pytest.raises(ConfigValidationError):
        loader.load_prompt_template("/path\x00attack")

    assert "Null byte detected" in caplog.text
```

### Fuzz Testing

**File:** `tests/compiler/test_config_loader_fuzz.py`

```python
import hypothesis
from hypothesis import given, strategies as st

@given(st.text())
def test_fuzz_path_validation(path_input):
    """Fuzz test path validation with random inputs"""
    loader = ConfigLoader(template_dir="/templates")

    try:
        loader.load_prompt_template(path_input)
    except (ConfigValidationError, ValueError, OSError):
        # Expected for invalid paths
        pass
    except Exception as e:
        # Unexpected exception - test fails
        pytest.fail(f"Unexpected exception: {e}")
```

## Security Considerations

**Threats:**
1. **Null byte injection**: `\x00` can truncate strings in C libraries
   - **Mitigation:** Check for null bytes before any path operations

2. **Control character bypass**: Characters like `\x01-\x1F` might bypass filters
   - **Mitigation:** Block all control characters except safe whitespace

3. **Unicode normalization attacks**: Different Unicode can represent same path
   - **Future consideration:** Add Unicode normalization

**Defense in Depth:**
- ✅ Null byte check (this task)
- ✅ Control character check (this task)
- ✅ relative_to() validation (existing)
- ✅ Security logging (this task)
- 🔄 Consider: symlink validation (separate task if needed)

## Error Handling

**Clear error messages:**
```python
# Good: Specific and actionable
raise ConfigValidationError('Invalid template path: null byte detected')

# Bad: Vague
raise ValueError('Invalid path')
```

## Success Metrics

- [ ] All null byte attacks blocked
- [ ] All control character attacks blocked
- [ ] Legitimate paths still work
- [ ] Security violations are logged
- [ ] All tests pass
- [ ] Fuzz testing passes

## Dependencies

**Blocked by:** None

**Blocks:** None (can be done in parallel)

## References

- Code Review Report: `.claude-coord/reports/code-review-20260201-002732.md` (lines 71-91)
- OWASP Path Traversal: https://owasp.org/www-community/attacks/Path_Traversal
- CWE-35: Path Traversal

## Estimated Effort

**Time:** 2-3 hours
**Complexity:** Low-Medium (simple checks, but thorough testing needed)

---

*Priority: CRITICAL (0)*
*Category: Security*
