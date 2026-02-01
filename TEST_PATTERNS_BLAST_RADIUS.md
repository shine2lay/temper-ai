# Test Patterns Used in BlastRadiusPolicy Test Suite

## Testing Patterns Reference

This document describes the testing patterns, strategies, and best practices used in the BlastRadiusPolicy test suite. Use this as a template for creating similar test suites.

---

## 1. Test Organization Pattern

### Class-Based Organization
```python
class TestFeatureName:
    """Tests for specific feature."""

    def test_normal_case(self):
        """Test the happy path."""
        pass

    def test_boundary_condition(self):
        """Test edge of acceptable range."""
        pass

    def test_error_case(self):
        """Test error handling."""
        pass
```

**Benefits:**
- Logical grouping of related tests
- Clear test discovery and navigation
- Shared context within class (can use fixtures)

**Used in:**
- TestFileCountLimits - All file count tests
- TestLinesPerFileLimits - All lines per file tests
- TestEntityLimits - All entity limit tests

---

## 2. Boundary Value Testing

### Pattern
```python
def test_exactly_at_limit(self):
    """Test action with exactly max value (boundary)."""
    policy = BlastRadiusPolicy({"max_files_per_operation": 3})
    result = policy.validate(
        action={"files": ["a.py", "b.py", "c.py"]},  # Exactly 3
        context={}
    )
    assert result.valid  # Should be valid

def test_one_over_limit(self):
    """Test action with one over limit (boundary)."""
    policy = BlastRadiusPolicy({"max_files_per_operation": 3})
    result = policy.validate(
        action={"files": ["a.py", "b.py", "c.py", "d.py"]},  # 4 > 3
        context={}
    )
    assert not result.valid  # Should be invalid
```

**Test Coverage:**
- Value below limit (valid)
- Value exactly at limit (valid)
- Value one over limit (invalid)
- Value far over limit (invalid)

**Used in:**
- File count limits (3 files vs 4 files)
- Lines per file (100 lines vs 101 lines)
- Total lines (1000 lines vs 1001 lines)
- Entity limits (50 entities vs 51 entities)

---

## 3. Type Safety Testing

### Pattern
```python
def test_field_correct_type(self):
    """Test with expected type."""
    policy = BlastRadiusPolicy()
    result = policy.validate(
        action={"files": ["a.py", "b.py"]},  # List (expected)
        context={}
    )
    assert result.valid

def test_field_wrong_type(self):
    """Test graceful handling of wrong type."""
    policy = BlastRadiusPolicy()
    result = policy.validate(
        action={"files": "not_a_list"},  # String instead of list
        context={}
    )
    # Should not crash, gracefully handle
    assert result.valid  # Type check fails, no violation

def test_field_missing(self):
    """Test handling of missing field."""
    policy = BlastRadiusPolicy()
    result = policy.validate(
        action={"operation": "test"},  # No 'files' field
        context={}
    )
    assert result.valid  # No field to validate
```

**Coverage:**
- Expected type (list, dict, string)
- Unexpected type (wrong type)
- Missing field (absent)

**Used in:**
- files: list vs string vs missing
- lines_changed: dict vs string vs missing
- entities: list vs string vs missing
- content: string vs int vs missing

---

## 4. Multiple Violation Testing

### Pattern
```python
def test_all_limits_violated(self):
    """Test violation of all limits simultaneously."""
    policy = BlastRadiusPolicy({
        "max_files_per_operation": 2,
        "max_lines_per_file": 100,
        "max_total_lines": 200,
        "max_entities_affected": 10,
        "forbidden_patterns": ["DROP TABLE"]
    })

    result = policy.validate(
        action={
            "files": ["a.py", "b.py", "c.py"],  # Violates
            "lines_changed": {"a.py": 150, "b.py": 120},  # Both violate
            "total_lines": 500,  # Violates
            "entities": [f"user_{i}" for i in range(20)],  # Violates
            "content": "DROP TABLE users"  # Violates
        },
        context={}
    )

    assert not result.valid
    assert len(result.violations) == 6  # All violations reported
```

**Benefits:**
- Tests aggregation of multiple violations
- Verifies all checks execute (no short-circuit)
- Validates severity distribution

**Used in:**
- TestCombinedViolations class

---

## 5. Performance Testing

### Pattern
```python
import time

def test_validation_performance(self):
    """Test validation completes in <1ms."""
    policy = BlastRadiusPolicy()
    action = {"files": ["a.py", "b.py"]}

    start = time.perf_counter()
    result = policy.validate(action, context={})
    duration = time.perf_counter() - start

    assert result.valid
    assert duration < 0.001  # <1ms requirement
```

**Coverage:**
- Simple actions
- Complex actions (many files, entities, patterns)
- Actions with violations
- Worst-case scenarios

**Used in:**
- TestPerformanceRequirements class
- All 4 performance tests passed with 10-100x headroom

---

## 6. Violation Metadata Testing

### Pattern
```python
def test_violation_includes_metadata(self):
    """Test that violations include required metadata."""
    policy = BlastRadiusPolicy({"max_files_per_operation": 2})

    result = policy.validate(
        action={"files": ["a.py", "b.py", "c.py"]},
        context={"agent": "test"}
    )

    violation = result.violations[0]

    # Check required fields
    assert violation.policy_name == "blast_radius"
    assert violation.severity == ViolationSeverity.HIGH
    assert violation.message is not None
    assert violation.timestamp is not None
    assert violation.remediation_hint is not None
    assert violation.context == {"agent": "test"}
```

**Benefits:**
- Ensures violations are actionable
- Verifies observability data
- Validates serialization

**Used in:**
- TestValidationResultStructure
- TestEdgeCases

---

## 7. Case-Insensitive Testing

### Pattern
```python
def test_case_insensitive_pattern_matching(self):
    """Test that pattern matching is case-insensitive."""
    policy = BlastRadiusPolicy({
        "forbidden_patterns": ["DELETE FROM"]
    })

    # Lowercase content
    result = policy.validate(
        action={"content": "delete from users"},
        context={}
    )
    assert not result.valid  # Should still detect

    # Mixed case content
    result = policy.validate(
        action={"content": "DeLeTe FrOm users"},
        context={}
    )
    assert not result.valid  # Should still detect
```

**Benefits:**
- Tests normalization logic
- Prevents bypass via case manipulation

**Used in:**
- TestForbiddenPatterns

---

## 8. Remediation Hint Testing

### Pattern
```python
def test_remediation_hint_for_violation(self):
    """Test that violation includes helpful remediation hint."""
    policy = BlastRadiusPolicy({"max_files_per_operation": 5})

    result = policy.validate(
        action={"files": [f"file_{i}.py" for i in range(10)]},
        context={}
    )

    assert result.violations[0].remediation_hint is not None
    assert len(result.violations[0].remediation_hint) > 0
    assert "5 or less" in result.violations[0].remediation_hint
```

**Benefits:**
- Ensures violations are actionable
- Validates user experience
- Tests documentation

**Used in:**
- All limit test classes have remediation tests

---

## 9. Edge Case Testing

### Pattern
```python
def test_empty_input(self):
    """Test handling of empty input."""
    policy = BlastRadiusPolicy()
    result = policy.validate(action={}, context={})
    assert result.valid  # No violations in empty action

def test_extreme_values(self):
    """Test extreme configuration values."""
    policy = BlastRadiusPolicy({
        "max_files_per_operation": 0  # Extreme: zero
    })
    result = policy.validate(
        action={"files": ["a.py"]},
        context={}
    )
    assert not result.valid  # Any file violates zero limit
```

**Coverage:**
- Empty inputs
- Extreme values (0, very large numbers)
- Unusual combinations

**Used in:**
- TestEdgeCases class

---

## 10. Default Configuration Testing

### Pattern
```python
def test_default_initialization(self):
    """Test policy with default configuration."""
    policy = BlastRadiusPolicy()

    assert policy.max_files == 10
    assert policy.max_lines_per_file == 500
    assert policy.max_total_lines == 2000
    assert policy.forbidden_patterns == []

def test_defaults_match_constants(self):
    """Test that defaults match documented constants."""
    assert BlastRadiusPolicy.DEFAULT_MAX_FILES == 10

    policy = BlastRadiusPolicy()
    assert policy.max_files == BlastRadiusPolicy.DEFAULT_MAX_FILES
```

**Benefits:**
- Ensures backward compatibility
- Validates documentation
- Tests default behavior

**Used in:**
- TestBlastRadiusPolicyBasics
- TestDefaultConstants

---

## Testing Checklist

For each feature/validation:

- [ ] Test normal case (happy path)
- [ ] Test boundary at limit (exactly)
- [ ] Test boundary over limit (one over)
- [ ] Test far over limit
- [ ] Test empty/zero values
- [ ] Test correct type
- [ ] Test wrong type (graceful handling)
- [ ] Test missing field
- [ ] Test violation severity
- [ ] Test violation message
- [ ] Test remediation hint
- [ ] Test performance (<1ms)
- [ ] Test combined with other violations

---

## Test Naming Convention

```python
def test_<feature>_<scenario>(self):
    """Brief description of what is tested."""
```

**Examples:**
- `test_within_file_limit()` - Files under limit
- `test_exactly_at_file_limit()` - Boundary condition
- `test_one_over_file_limit()` - Boundary violation
- `test_files_not_a_list()` - Type safety
- `test_remediation_hint_for_file_limit()` - Metadata

**Benefits:**
- Clear test purpose from name
- Easy to find specific tests
- Self-documenting

---

## Assertion Patterns

### Basic Validation
```python
assert result.valid  # Should pass
assert not result.valid  # Should fail
```

### Violation Count
```python
assert len(result.violations) == 0  # No violations
assert len(result.violations) == 1  # One violation
assert len(result.violations) >= 1  # At least one
```

### Severity
```python
assert result.violations[0].severity == ViolationSeverity.HIGH
assert result.violations[0].severity == ViolationSeverity.CRITICAL
```

### Message Content
```python
assert "4 > 3" in result.violations[0].message
assert "file1.py" in result.violations[0].message
assert "DELETE FROM" in result.violations[0].message
```

### Performance
```python
assert duration < 0.001  # <1ms
```

---

## Code Coverage Strategy

1. **Line Coverage** - Every line executed
2. **Branch Coverage** - Every if/else path taken
3. **Boundary Coverage** - Edge values tested
4. **Type Coverage** - All type checks exercised
5. **Error Coverage** - All error paths tested

**Result:** 100% coverage (49/49 statements)

---

## Continuous Improvement

### Add More Tests For:
1. **Property-based testing** (Hypothesis)
   ```python
   from hypothesis import given, strategies as st

   @given(st.integers(min_value=0, max_value=1000))
   def test_file_count_property(count):
       policy = BlastRadiusPolicy({"max_files_per_operation": 10})
       action = {"files": [f"file_{i}.py" for i in range(count)]}
       result = policy.validate(action, {})
       assert result.valid == (count <= 10)
   ```

2. **Mutation testing** (verify test quality)
3. **Concurrency testing** (thread safety)
4. **Integration testing** (with other policies)
5. **Regression testing** (prevent bugs from reoccurring)

---

## Summary

The BlastRadiusPolicy test suite demonstrates:

✅ Comprehensive boundary testing
✅ Robust type safety validation
✅ Multiple violation aggregation
✅ Performance requirements verification
✅ Metadata and observability testing
✅ Edge case handling
✅ 100% code coverage

Use these patterns as a template for creating high-quality test suites for other safety policies.
