# M4-03: Safety Violation Types & Exceptions

**Date:** 2026-01-27
**Task:** m4-03
**Type:** Feature - Safety System Foundation
**Impact:** High - Establishes exception hierarchy for safety violations

## Summary

Implemented structured exception hierarchy and violation data models for the M4 safety system. Provides type-safe, serializable exceptions that integrate with observability and enable proper error handling throughout the framework.

## Problem Statement

The safety system needed:
- **Structured exception types** for different violation categories
- **Rich metadata** for debugging and observability integration
- **Clear error messages** with actionable remediation hints
- **JSON serialization** for logging and monitoring
- **Type-safe exception handling** to distinguish between violation types

## Solution Overview

Created a comprehensive exception hierarchy with:
1. **Base exception** (`SafetyViolationException`) wrapping `SafetyViolation` data models
2. **Specific exception types** for different violation categories
3. **Automatic severity mapping** based on violation type
4. **Serialization support** for observability integration
5. **Remediation hints** to guide users toward fixes

### Exception Hierarchy

```
SafetyViolationException (base)
├── BlastRadiusViolation (HIGH)
├── ActionPolicyViolation (CRITICAL)
├── RateLimitViolation (MEDIUM)
├── ResourceLimitViolation (HIGH)
├── ForbiddenOperationViolation (CRITICAL)
└── AccessDeniedViolation (CRITICAL)
```

## Changes

### 1. New Module: src/safety/exceptions.py

**Purpose:** Exception classes for safety violations

**Key Classes:**

#### SafetyViolationException (Base)
```python
class SafetyViolationException(Exception):
    """Base exception for all safety policy violations.

    Wraps SafetyViolation data model with exception semantics.
    """

    def __init__(
        self,
        policy_name: str,
        severity: ViolationSeverity,
        message: str,
        action: str,
        context: Dict[str, Any],
        remediation_hint: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        # Creates wrapped SafetyViolation
        self.violation = SafetyViolation(...)

    def to_dict(self) -> Dict[str, Any]:
        """JSON serialization for logging."""
        return self.violation.to_dict()

    @classmethod
    def from_violation(cls, violation: SafetyViolation):
        """Create exception from SafetyViolation."""
        return cls(...)
```

**Features:**
- Wraps `SafetyViolation` data model
- Implements `to_dict()` for JSON serialization
- Supports `from_violation()` for converting data models to exceptions
- Formatted `__str__()` with severity and remediation
- Rich `__repr__()` for debugging

#### BlastRadiusViolation
```python
class BlastRadiusViolation(SafetyViolationException):
    """Raised when blast radius limits are exceeded.

    Examples:
    - Too many files modified
    - Changes too large
    - Commit scope exceeds policy
    """
```

**Severity:** HIGH
**Default Remediation:** "Reduce the scope of changes"

#### ActionPolicyViolation
```python
class ActionPolicyViolation(SafetyViolationException):
    """Raised when action is forbidden by policy.

    Examples:
    - Blocked tool usage
    - Forbidden operation
    - Policy constraint violation
    """
```

**Severity:** CRITICAL
**Default Remediation:** "Review action policy constraints"

#### RateLimitViolation
```python
class RateLimitViolation(SafetyViolationException):
    """Raised when rate limits are exceeded.

    Examples:
    - API call rate limit
    - Database query rate limit
    - File operation throttling
    """
```

**Severity:** MEDIUM
**Default Remediation:** "Reduce request rate or wait for cooldown"

#### ResourceLimitViolation
```python
class ResourceLimitViolation(SafetyViolationException):
    """Raised when resource consumption limits exceeded.

    Examples:
    - Memory limit
    - CPU usage
    - Disk space
    """
```

**Severity:** HIGH
**Default Remediation:** "Reduce resource consumption"

#### ForbiddenOperationViolation
```python
class ForbiddenOperationViolation(SafetyViolationException):
    """Raised when attempting forbidden operations.

    Examples:
    - Secret access
    - Critical file modification
    - Dangerous command execution
    """
```

**Severity:** CRITICAL
**Default Remediation:** "Remove forbidden operation"

#### AccessDeniedViolation
```python
class AccessDeniedViolation(SafetyViolationException):
    """Raised when access control denies action.

    Examples:
    - File path outside allowed scope
    - Directory access denied
    - Resource permission error
    """
```

**Severity:** CRITICAL
**Default Remediation:** "Ensure access path is within allowed scope"

### 2. New Module: src/safety/models.py

**Purpose:** Re-export safety data models from interfaces.py

```python
from src.safety.interfaces import (
    SafetyViolation,
    ValidationResult,
    ViolationSeverity,
)

__all__ = [
    "SafetyViolation",
    "ValidationResult",
    "ViolationSeverity",
]
```

**Rationale:**
- Provides stable public API
- Centralizes model imports
- Maintains clean separation between interfaces and implementations

### 3. Updated: src/safety/__init__.py

**Changes:** Added exception exports

```python
from src.safety.exceptions import (
    SafetyViolationException,
    BlastRadiusViolation,
    ActionPolicyViolation,
    RateLimitViolation,
    ResourceLimitViolation,
    ForbiddenOperationViolation,
    AccessDeniedViolation,
)

__all__ = [
    # ... existing exports ...
    "SafetyViolationException",
    "BlastRadiusViolation",
    "ActionPolicyViolation",
    "RateLimitViolation",
    "ResourceLimitViolation",
    "ForbiddenOperationViolation",
    "AccessDeniedViolation",
]
```

## Testing

### Test Coverage

**File:** `tests/safety/test_exceptions.py` (33 tests)

**Test Categories:**
1. **Base Exception Tests (10 tests)**
   - Exception creation with all parameters
   - Metadata and remediation hints
   - String formatting (`__str__`, `__repr__`)
   - JSON serialization (`to_dict()`)
   - Conversion from `SafetyViolation` data model
   - Exception raising and catching

2. **Specific Exception Tests (16 tests)**
   - BlastRadiusViolation (4 tests)
   - ActionPolicyViolation (3 tests)
   - RateLimitViolation (3 tests)
   - ResourceLimitViolation (2 tests)
   - ForbiddenOperationViolation (2 tests)
   - AccessDeniedViolation (2 tests)

3. **Exception Hierarchy Tests (3 tests)**
   - Inheritance from base class
   - Catching specific exceptions
   - Catching via base exception

4. **Serialization Tests (2 tests)**
   - Data preservation through serialization
   - JSON serialization compatibility

5. **Message Tests (2 tests)**
   - Clear error messages
   - Actionable remediation hints

### Test Results

```
tests/safety/test_exceptions.py: 33 passed
All safety tests: 105 passed
```

### Coverage Metrics

```
src/safety/exceptions.py:     100% coverage (43 lines, 0 missed)
src/safety/models.py:         100% coverage (2 lines, 0 missed)
tests/safety/test_exceptions.py: 191 lines of test code
```

**Coverage exceeds >90% requirement** ✅

## Usage Examples

### Basic Usage

```python
from src.safety.exceptions import BlastRadiusViolation, ViolationSeverity

# Raise a blast radius violation
try:
    raise BlastRadiusViolation(
        policy_name="BlastRadiusPolicy",
        message="Attempted to modify 50 files (limit: 10)",
        action="git commit",
        context={"agent": "coder", "files": ["file1.py", "file2.py", ...]},
        remediation_hint="Split changes into 5 separate commits",
        metadata={"files_affected": 50, "limit": 10}
    )
except BlastRadiusViolation as e:
    print(e)
    # [HIGH] BlastRadiusPolicy: Attempted to modify 50 files (limit: 10)
    #   Remediation: Split changes into 5 separate commits
```

### JSON Serialization

```python
import json
from src.safety.exceptions import ActionPolicyViolation

exc = ActionPolicyViolation(
    policy_name="ActionPolicy",
    message="Tool 'execute_shell' is forbidden",
    action="execute_shell('rm -rf /')",
    context={"agent": "untrusted"},
    metadata={"tool": "execute_shell", "reason": "destructive"}
)

# Serialize for logging
log_data = exc.to_dict()
json_str = json.dumps(log_data)

# Log data includes:
# - policy_name, severity, severity_value
# - message, action, context
# - timestamp, remediation_hint, metadata
```

### Creating from SafetyViolation

```python
from src.safety.interfaces import SafetyViolation, ViolationSeverity
from src.safety.exceptions import SafetyViolationException

# Create violation data model
violation = SafetyViolation(
    policy_name="FileAccessPolicy",
    severity=ViolationSeverity.CRITICAL,
    message="Access denied to /etc/passwd",
    action="read_file(/etc/passwd)",
    context={"agent": "researcher"}
)

# Convert to exception
exc = SafetyViolationException.from_violation(violation)
raise exc
```

### Catching Specific Violations

```python
from src.safety.exceptions import (
    SafetyViolationException,
    BlastRadiusViolation,
    RateLimitViolation,
)

try:
    # Execute action
    execute_action()
except BlastRadiusViolation as e:
    # Handle blast radius violations
    logger.warning("Blast radius exceeded", extra=e.to_dict())
    split_into_smaller_batches()
except RateLimitViolation as e:
    # Handle rate limits
    logger.info("Rate limit hit", extra=e.to_dict())
    wait_for_cooldown(e.metadata.get("retry_after", 60))
except SafetyViolationException as e:
    # Handle all other safety violations
    logger.error("Safety violation", extra=e.to_dict())
    raise
```

### Integration with Policies

```python
from src.safety import BaseSafetyPolicy, ValidationResult
from src.safety.exceptions import AccessDeniedViolation

class FileAccessPolicy(BaseSafetyPolicy):
    def _validate_impl(self, action, context):
        path = action.get("path", "")

        if path.startswith("/etc/"):
            # Create exception for violation
            exc = AccessDeniedViolation(
                policy_name=self.name,
                message=f"Access denied to {path}",
                action=f"access_file({path})",
                context=context,
                metadata={"path": path, "reason": "system_directory"}
            )

            # Report violation
            self.report_violation(exc.violation)

            # Return invalid result
            return ValidationResult(
                valid=False,
                violations=[exc.violation],
                policy_name=self.name
            )

        return ValidationResult(valid=True, policy_name=self.name)
```

## Design Decisions

### 1. Wrap SafetyViolation Instead of Duplicating

**Rationale:**
- `SafetyViolation` is the source of truth for violation data
- Exceptions provide error handling semantics
- Avoids data duplication and sync issues
- Easy conversion between data models and exceptions

### 2. Default Severity Per Exception Type

**Rationale:**
- Consistency across the codebase
- Clear expectations for exception handling
- Can still override if needed via base class

**Severity Mapping:**
```
CRITICAL: ActionPolicyViolation, ForbiddenOperationViolation, AccessDeniedViolation
HIGH: BlastRadiusViolation, ResourceLimitViolation
MEDIUM: RateLimitViolation
```

### 3. Default Remediation Hints

**Rationale:**
- Provides helpful guidance even when policy doesn't specify
- Can be overridden with specific hints
- Improves user experience

### 4. Rich Metadata Support

**Rationale:**
- Enables detailed debugging
- Supports observability integration
- Allows policy-specific data

### 5. JSON Serialization via to_dict()

**Rationale:**
- Standard pattern for logging frameworks
- Compatible with observability systems
- Supports structured logging

### 6. Classmethod from_violation()

**Rationale:**
- Easy conversion from data models
- Supports existing code using SafetyViolation
- Enables gradual migration to exceptions

## Integration with M1 Observability

Exceptions integrate seamlessly with the observability system:

```python
from src.observability import ExecutionTracker
from src.safety.exceptions import SafetyViolationException

tracker = ExecutionTracker()

try:
    # Execute action
    ...
except SafetyViolationException as e:
    # Log to observability system
    tracker.track_error(
        error_type="safety_violation",
        error_data=e.to_dict(),
        severity=e.severity.name,
        context=e.context
    )
    raise
```

## Files Modified

### Created
- `src/safety/exceptions.py` (43 lines, 6 exception classes)
- `src/safety/models.py` (2 lines, re-exports)
- `tests/safety/test_exceptions.py` (191 lines, 33 tests)

### Modified
- `src/safety/__init__.py` (+7 exception exports)

### Test Results
- **New Tests:** 33
- **Total Safety Tests:** 105
- **All Passed:** ✅
- **Coverage:** 100% (src/safety/exceptions.py)

## Acceptance Criteria

✅ **SafetyViolationException with metadata**
- Includes agent, policy, severity, context
- Supports custom metadata dictionary
- Wraps SafetyViolation data model

✅ **Specific exception types**
- BlastRadiusViolation
- ActionPolicyViolation
- RateLimitViolation
- ResourceLimitViolation
- ForbiddenOperationViolation
- AccessDeniedViolation

✅ **Violation serialization to JSON**
- `to_dict()` method on all exceptions
- JSON-serializable output
- Preserves all violation data

✅ **Clear error messages with remediation hints**
- Formatted `__str__()` includes severity and message
- Remediation hints included when available
- Context displayed for debugging

✅ **Unit tests with >90% coverage**
- 33 tests covering all exception types
- 100% code coverage
- All tests passing

## Next Steps

### Immediate
- **m4-04:** File & Directory Access Restrictions (uses AccessDeniedViolation)
- **m4-05:** Rate Limiting Service (uses RateLimitViolation)
- **m4-06:** Resource Consumption Limits (uses ResourceLimitViolation)
- **m4-07:** Forbidden Operations (uses ForbiddenOperationViolation)

### Future Enhancements
1. **Exception Aggregation:** Collect multiple violations before failing
2. **Telemetry Integration:** Auto-report exceptions to monitoring
3. **Retry Strategies:** Built-in retry logic for rate limits
4. **Escalation Policies:** Auto-escalate CRITICAL violations

## Documentation

**Module Docstrings:** Comprehensive
**Class Docstrings:** Complete with examples
**Method Docstrings:** Full parameter and return descriptions
**Usage Examples:** Provided in docstrings and this changelog

## Deployment Notes

### Backward Compatibility
✅ Fully backward compatible
- Existing code using SafetyViolation continues to work
- Exceptions are opt-in
- No breaking changes to interfaces

### Migration Path
1. Existing policies return `SafetyViolation` (no change needed)
2. New policies can raise exceptions directly
3. Convert violations to exceptions via `from_violation()` when needed
4. Gradually adopt exception-based error handling

### Performance Impact
✅ Negligible - exceptions only created on violations (rare events)

## Conclusion

The exception hierarchy provides a robust foundation for the M4 safety system with:
- **Type-safe error handling** for different violation categories
- **Rich metadata** for debugging and observability
- **Clear error messages** with actionable remediation
- **JSON serialization** for logging and monitoring
- **100% test coverage** ensuring reliability

**Unblocks:**
- m4-04: File & Directory Access Restrictions
- m4-05: Rate Limiting Service
- m4-06: Resource Consumption Limits
- m4-07: Forbidden Operations & Patterns
- m4-12: Safety Gate Implementation
