# Task Specification: code-crit-missing-deps-01

## Problem Statement

Multiple imports from non-existent modules will cause immediate crashes when code paths are executed in the safety module. The missing modules are:
- `src.core.service` (imported in exceptions.py)
- `src.observability.sanitization` (imported in action_policy_engine.py)
- `src.utils.config_helpers` (imported in secret_detection.py)

This will cause runtime crashes when safety violations occur, when logging violations, or when sanitizing secret detection context.

## Context

- **Source:** Code Review Report 2026-02-01 (Critical Issue #1)
- **Files Affected:**
  - `src/safety/exceptions.py:139`
  - `src/safety/action_policy_engine.py:434`
  - `src/safety/secret_detection.py:467`
- **Impact:** Application crashes on safety violation handling
- **Module:** Safety

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Fix all missing module imports in safety module
- [ ] Implement `_sanitize_violation_context()` function
- [ ] Implement missing sanitization functions
- [ ] Implement missing config helper functions
- [ ] Verify all import statements resolve correctly

### IMPLEMENTATION APPROACH
- [ ] Option 1: Create missing modules with proper implementations
- [ ] OR Option 2: Implement functionality inline where needed
- [ ] Remove dependencies on non-existent modules
- [ ] Ensure no circular import issues

### SECURITY CONTROLS
- [ ] Sanitization properly redacts sensitive data (password, secret, key, token)
- [ ] Context sanitization limits string length to prevent log flooding
- [ ] Secure defaults for all sanitization functions

### TESTING
- [ ] Unit tests for sanitization functions
- [ ] Integration tests for safety violation handling
- [ ] Test crash scenarios are now handled gracefully
- [ ] Verify imports work without errors

## Implementation Plan

### Step 1: Audit All Missing Imports

**Action:** Search for all imports from non-existent modules in safety module

```bash
grep -r "from src.core.service" src/safety/
grep -r "from src.observability.sanitization" src/safety/
grep -r "from src.utils.config_helpers" src/safety/
```

### Step 2: Implement Sanitization Functions

**File:** `src/safety/exceptions.py`

**Implementation:**
```python
def _sanitize_violation_context(context: Dict[str, Any]) -> Dict[str, Any]:
    """Remove sensitive data from violation context."""
    sanitized = {}
    sensitive_keys = {'password', 'secret', 'key', 'token', 'credential', 'api_key'}

    for key, value in context.items():
        # Redact sensitive keys
        if key.lower() in sensitive_keys or any(s in key.lower() for s in sensitive_keys):
            sanitized[key] = "[REDACTED]"
        else:
            # Limit string length to prevent log flooding
            sanitized[key] = str(value)[:200]

    return sanitized
```

### Step 3: Fix Imports

**File:** `src/safety/exceptions.py:139`

Replace:
```python
from src.core.service import _sanitize_violation_context
```

With inline implementation (see Step 2).

**File:** `src/safety/action_policy_engine.py:434`

Implement missing sanitization inline or import from exceptions.py.

**File:** `src/safety/secret_detection.py:467`

Implement missing config helpers inline or create proper config module.

### Step 4: Verify No Crashes

Run safety-related code paths to ensure no import errors:
```bash
python -c "from src.safety.exceptions import SafetyViolation"
python -c "from src.safety.action_policy_engine import ActionPolicyEngine"
python -c "from src.safety.secret_detection import SecretDetector"
```

## Test Strategy

### Unit Tests

**File:** `tests/safety/test_exceptions.py`

```python
def test_sanitize_violation_context_redacts_passwords():
    context = {
        'user': 'alice',
        'password': 'secret123',
        'api_key': 'sk_test_123'
    }
    sanitized = _sanitize_violation_context(context)
    assert sanitized['password'] == '[REDACTED]'
    assert sanitized['api_key'] == '[REDACTED]'
    assert sanitized['user'] == 'alice'

def test_sanitize_violation_context_limits_length():
    context = {'long_value': 'x' * 500}
    sanitized = _sanitize_violation_context(context)
    assert len(sanitized['long_value']) == 200
```

### Integration Tests

**File:** `tests/safety/test_violation_handling.py`

```python
def test_safety_violation_with_sensitive_context():
    """Test that violations with sensitive data are logged safely"""
    try:
        raise SafetyViolation(
            "Test violation",
            context={'password': 'secret123'}
        )
    except SafetyViolation as e:
        # Should not crash on import
        assert 'REDACTED' in str(e)
```

## Error Handling

**Scenarios:**
1. Missing key in context dict → skip gracefully
2. Non-dict context → convert to string safely
3. Circular references in context → handle with depth limit

## Success Metrics

- [ ] All imports resolve successfully
- [ ] No runtime crashes when safety violations occur
- [ ] Sensitive data is properly redacted in logs
- [ ] All tests pass
- [ ] Code coverage > 80% for new functions

## Dependencies

**Blocked by:** None

**Blocks:** None (can be done in parallel with other critical fixes)

## References

- Code Review Report: `.claude-coord/reports/code-review-20260201-002732.md` (lines 39-68)
- Safety Module: `src/safety/`

## Estimated Effort

**Time:** 2-3 hours
**Complexity:** Medium (implementation is straightforward, testing is important)

---

*Priority: CRITICAL (0)*
*Category: Security & Reliability*
