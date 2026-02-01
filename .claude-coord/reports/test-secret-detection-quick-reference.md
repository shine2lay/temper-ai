# Secret Detection Test Suite - Quick Reference

**File:** tests/safety/test_secret_detection.py
**Module:** src/safety/secret_detection.py

---

## Quick Test Execution

```bash
# Run all tests
pytest tests/safety/test_secret_detection.py -v

# Run with coverage
pytest tests/safety/test_secret_detection.py --cov=src/safety/secret_detection --cov-report=term-missing

# Run specific category
pytest tests/safety/test_secret_detection.py::TestAWSKeyDetection -v
pytest tests/safety/test_secret_detection.py::TestEntropyCalculation -v
pytest tests/safety/test_secret_detection.py::TestEdgeCases -v
```

---

## Test Method Naming Convention

Format: `test_<what>_<scenario>`

Examples:
- `test_valid_aws_access_key_detected()` - Positive test (should detect)
- `test_public_key_not_detected()` - Negative test (should not detect)
- `test_entropy_of_empty_string()` - Edge case test
- `test_multiple_aws_keys_detected()` - Multiple instance test

---

## Pattern Detection Examples

### AWS Access Key
```python
test_valid_aws_access_key_detected()
Input:  "AKIAIOSFODNN7EXAMPLE"
Output: Invalid, HIGH severity, pattern=aws_access_key
```

### Private Key
```python
test_rsa_private_key_detected()
Input:  "-----BEGIN RSA PRIVATE KEY-----"
Output: Invalid, CRITICAL severity, pattern=private_key
```

### JWT Token
```python
test_valid_jwt_token_detected()
Input:  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKx..."
Output: Invalid, HIGH severity, pattern=jwt_token
```

### Generic API Key
```python
test_api_key_with_equals()
Input:  "api_key=sk_live_abcdefghijklmnopqrstuvwxyz123456"
Output: Invalid, HIGH/MEDIUM severity, pattern=generic_api_key
```

### Database Connection
```python
test_mongodb_connection_string_detected()
Input:  "mongodb://user:password@localhost:27017/mydb"
Output: Invalid, severity based on entropy, pattern=connection_string
```

---

## Entropy Calculation Examples

### Zero Entropy (Empty)
```python
test_entropy_of_empty_string()
Input:  ""
Output: 0.0
```

### Zero Entropy (Single Character)
```python
test_entropy_of_single_character()
Input:  "aaaaaaaaaa"
Output: 0.0
```

### Low Entropy (Two Characters)
```python
test_entropy_of_two_characters_equal()
Input:  "ababababab"
Output: 1.0 (± 0.01)
Formula: -2 * (0.5 * log2(0.5)) = 1.0
```

### High Entropy (Random String)
```python
test_entropy_of_random_string()
Input:  "wJalrXUtnFEMI/K7MDENG"
Output: > 4.0
```

### Edge Cases (No Errors)
```python
test_entropy_calculation_no_division_by_zero()
Inputs: ["", "a", "ab", "abc"*100, "x"*1000]
Output: All return valid float >= 0.0, no NaN/Inf
```

---

## Test Secret Allowlist Examples

### Test Keyword
```python
test_test_secret_allowed_by_default()
Input:  "password=test"
Output: Valid (allowed)
```

### Example Keyword
```python
test_example_secret_allowed()
Input:  "api_key=example_key_12345678901234567890"
Output: Valid (allowed)
```

### Case Insensitive
```python
test_case_insensitive_test_secret_matching()
Input:  "password=TEST_PASSWORD"
Output: Valid (allowed)
```

### Disabled Allowlist
```python
test_test_secrets_can_be_disabled()
Config: {"allow_test_secrets": False}
Input:  "password=test"
Output: Invalid (not allowed when disabled)
```

**All Test Keywords:**
- test
- example
- demo
- placeholder
- changeme
- password123
- dummy
- fake

---

## Path Exclusion Examples

### Git Directory
```python
test_git_directory_excluded()
File:   ".git/config"
Input:  "AKIAIOSFODNN7EXAMPLE"
Output: Valid (path excluded)
```

### Node Modules
```python
test_node_modules_excluded()
File:   "node_modules/package/index.js"
Input:  "AKIAIOSFODNN7EXAMPLE"
Output: Valid (path excluded)
```

### Multiple Exclusions
```python
test_multiple_exclusions()
Config: {"excluded_paths": [".git/", "node_modules/", "vendor/", ".venv/"]}
Files:  [".git/config", "node_modules/lib.js", "vendor/package", ".venv/lib"]
Output: All valid (all excluded)
```

### Non-Excluded Path
```python
test_non_excluded_path_detected()
Config: {"excluded_paths": [".git/"]}
File:   "src/config.py"
Input:  "AKIAIOSFODNN7EXAMPLE"
Output: Invalid (path not excluded)
```

---

## Edge Case Examples

### Empty Content
```python
test_empty_content()
Input:  {"content": ""}
Output: Valid, no violations
```

### Very Long Content
```python
test_very_long_content()
Input:  "a" * (10 * 1024 * 1024) + "AKIAIOSFODNN7EXAMPLE"
Output: Invalid (secret still detected)
```

### Unicode Content
```python
test_unicode_content()
Input:  "密码=MySecretP@ssw0rd123 🔑"
Output: Invalid (password detected)
```

### Whitespace Only
```python
test_whitespace_only_content()
Input:  "   \n\t\r\n   "
Output: Valid, no violations
```

### Secret at Start
```python
test_secret_at_start_of_content()
Input:  "AKIAIOSFODNN7EXAMPLE is the key"
Output: Invalid
```

### Secret at End
```python
test_secret_at_end_of_content()
Input:  "The key is AKIAIOSFODNN7EXAMPLE"
Output: Invalid
```

---

## Multiline Detection Examples

### Multiline Private Key
```python
test_multiline_private_key()
Input:
  {
    "private_key": "-----BEGIN PRIVATE KEY-----
  MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSj...
  -----END PRIVATE KEY-----"
  }
Output: Invalid, CRITICAL severity
```

### JSON with Multiple Secrets
```python
test_json_with_secrets()
Input:
  {
    "database": {
      "connection_string": "postgres://user:pass@localhost:5432/db"
    },
    "api": {
      "key": "sk_live_abcdefghijklmnopqrstuvwxyz"
    }
  }
Output: Invalid, 2+ violations
```

### YAML with Multiple Secrets
```python
test_yaml_with_secrets()
Input:
  database:
    connection: mongodb://user:password@localhost:27017/mydb
  api:
    github_token: ghp_1234567890123456789012345678901234AB
    stripe_key: sk_live_1234567890abcdefghijklmn
Output: Invalid, 3+ violations
```

---

## False Positive Prevention Examples

### Empty Value
```python
test_common_words_not_flagged()
Input:  "password="
Output: Valid (no value)
```

### Type Annotation
```python
test_code_variable_names_not_flagged()
Input:  "api_key: str\npassword: Optional[str]"
Output: Valid (just type annotations)
```

### Short Value
```python
test_short_api_key_not_detected()
Input:  "api_key=short"
Output: Valid (< 20 characters)
```

---

## Severity Assignment Examples

### CRITICAL Severity
```python
test_private_key_is_critical()
Pattern: private_key
Severity: CRITICAL

test_aws_secret_key_is_critical()
Pattern: aws_secret_key
Severity: CRITICAL
```

### HIGH Severity
```python
test_api_keys_are_high()
Patterns: aws_access_key, github_token, stripe_key
Severity: HIGH

test_high_entropy_secret_is_high()
Condition: entropy > 4.5
Severity: HIGH
```

### MEDIUM Severity
```python
test_low_entropy_secret_is_medium()
Condition: entropy <= 4.5
Severity: MEDIUM
```

---

## Performance Benchmarks

### Small Content (<1KB)
```python
test_small_content_fast_detection()
Input:  "AKIAIOSFODNN7EXAMPLE in small file"
Target: < 5ms
```

### Medium Content (10KB)
```python
test_medium_content_reasonable_performance()
Input:  ("a" * 10000) + "AKIAIOSFODNN7EXAMPLE"
Target: < 50ms
```

### No Secrets (Fast Path)
```python
test_no_secrets_fast_processing()
Input:  "This is normal text " * 100
Target: < 10ms
```

---

## Validation Result Structure Examples

### Valid Result
```python
test_valid_result_structure()
Input:  "no secrets here"
Output:
  valid = True
  violations = []
  policy_name = "secret_detection"
```

### Invalid Result
```python
test_invalid_result_structure()
Input:  "AKIAIOSFODNN7EXAMPLE"
Output:
  valid = False
  violations = [SafetyViolation(...)]
  policy_name = "secret_detection"
```

### Violation Metadata
```python
test_violation_metadata_includes_position()
Input:  "prefix text AKIAIOSFODNN7EXAMPLE suffix"
Output:
  violations[0].metadata = {
    "pattern_type": "aws_access_key",
    "entropy": 4.52,
    "match_position": 12  # index of "AKIA"
  }
```

### Remediation Hint
```python
test_violation_includes_remediation_hint()
Input:  "AKIAIOSFODNN7EXAMPLE"
Output:
  violations[0].remediation_hint = "Use environment variables or secret management service"
```

---

## Configuration Examples

### Default Configuration
```python
policy = SecretDetectionPolicy()
# enabled_patterns: all 11 patterns
# entropy_threshold: 4.5
# excluded_paths: []
# allow_test_secrets: True
```

### Custom Entropy Threshold
```python
config = {"entropy_threshold": 5.0}
policy = SecretDetectionPolicy(config)
# Higher threshold = fewer false positives
```

### Selective Patterns
```python
config = {"enabled_patterns": ["aws_access_key", "private_key"]}
policy = SecretDetectionPolicy(config)
# Only AWS and private key detection
```

### Path Exclusions
```python
config = {"excluded_paths": [".git/", "node_modules/", "test/"]}
policy = SecretDetectionPolicy(config)
# Skip common directories
```

### Disable Test Secrets
```python
config = {"allow_test_secrets": False}
policy = SecretDetectionPolicy(config)
# Strict mode - flag all secrets including test ones
```

---

## Coverage Completeness Examples

### All Properties Tested
```python
test_policy_name_property()     # name == "secret_detection"
test_policy_version_property()  # version == "1.0.0"
test_policy_priority_property() # priority == 95
```

### All Patterns Disabled
```python
test_all_patterns_can_be_disabled()
Config: {"enabled_patterns": []}
Input:  "AKIAIOSFODNN7EXAMPLE password=secret123"
Output: Valid (all patterns disabled)
```

### Content Field Priority
```python
test_content_priority_order()
# 1. content field (highest priority)
# 2. config field (if content missing)
# 3. data field (if content and config missing)
```

### All Test Keywords
```python
test_all_test_secret_keywords()
Keywords: ["test", "example", "demo", "placeholder", "changeme", "password123", "dummy", "fake"]
Input:   "password={keyword}_value123"
Output:  Valid (all keywords tested)
```

### Timestamp Validation
```python
test_violation_has_timestamp()
Output:
  violations[0].timestamp = "2026-01-30T12:34:56Z"
  # ISO format with 'T' and 'Z'
```

---

## Common Test Patterns

### Basic Detection Test
```python
def test_pattern_detected(self):
    policy = SecretDetectionPolicy()
    result = policy.validate(
        action={"content": "SECRET_VALUE"},
        context={}
    )
    assert not result.valid
    assert len(result.violations) == 1
    assert result.violations[0].metadata["pattern_type"] == "expected_pattern"
```

### Negative Test (Should Not Detect)
```python
def test_pattern_not_detected(self):
    policy = SecretDetectionPolicy()
    result = policy.validate(
        action={"content": "SAFE_VALUE"},
        context={}
    )
    assert result.valid
    assert len(result.violations) == 0
```

### Multiple Detection Test
```python
def test_multiple_patterns_detected(self):
    policy = SecretDetectionPolicy()
    content = """
    SECRET1
    SECRET2
    SECRET3
    """
    result = policy.validate(action={"content": content}, context={})
    assert not result.valid
    assert len(result.violations) >= 3
```

### Configuration Test
```python
def test_custom_config(self):
    config = {"key": "value"}
    policy = SecretDetectionPolicy(config)
    assert policy.config["key"] == "value"
```

### Metadata Validation Test
```python
def test_violation_metadata(self):
    policy = SecretDetectionPolicy()
    result = policy.validate(
        action={"content": "SECRET"},
        context={}
    )
    assert not result.valid
    assert "pattern_type" in result.violations[0].metadata
    assert "entropy" in result.violations[0].metadata
    assert "match_position" in result.violations[0].metadata
```

---

## Debugging Failed Tests

### Check Pattern Match
```python
import re
pattern = re.compile(r"AKIA[0-9A-Z]{16}", re.IGNORECASE)
matches = pattern.finditer("AKIAIOSFODNN7EXAMPLE")
for match in matches:
    print(f"Match: {match.group(0)} at position {match.start()}")
```

### Check Entropy Calculation
```python
policy = SecretDetectionPolicy()
entropy = policy._calculate_entropy("wJalrXUtnFEMI/K7MDENG")
print(f"Entropy: {entropy}")  # Should be > 4.0
```

### Check Test Secret Matching
```python
policy = SecretDetectionPolicy()
is_test = policy._is_test_secret("password123")
print(f"Is test secret: {is_test}")  # Should be True
```

### Check Path Exclusion
```python
config = {"excluded_paths": [".git/"]}
policy = SecretDetectionPolicy(config)
file_path = ".git/config"
excluded = any(exc in file_path for exc in policy.excluded_paths)
print(f"Path excluded: {excluded}")  # Should be True
```

---

## Quick Reference: Test Count by Category

| Category | Test Count | Priority |
|----------|------------|----------|
| Basics | 5 | MEDIUM |
| AWS Keys | 6 | CRITICAL |
| GitHub Tokens | 5 | HIGH |
| Generic API Keys | 5 | HIGH |
| Generic Secrets | 5 | MEDIUM |
| JWT Tokens | 3 | HIGH |
| Private Keys | 5 | CRITICAL |
| Google API Keys | 2 | HIGH |
| Slack Tokens | 3 | HIGH |
| Stripe Keys | 4 | HIGH |
| Connection Strings | 4 | HIGH |
| Entropy Calculation | 10 | CRITICAL |
| Test Secret Allowlist | 11 | HIGH |
| Path Exclusion | 6 | MEDIUM |
| Multiline Detection | 4 | HIGH |
| Multiple Secrets | 3 | HIGH |
| Edge Cases | 13 | HIGH |
| False Positives | 4 | MEDIUM |
| Severity Assignment | 5 | CRITICAL |
| Result Structure | 5 | MEDIUM |
| Performance | 3 | MEDIUM |
| Coverage Completeness | 9 | HIGH |
| **TOTAL** | **120+** | **CRITICAL** |

---

## Expected Test Output

```
tests/safety/test_secret_detection.py::TestSecretDetectionPolicyBasics::test_default_initialization PASSED
tests/safety/test_secret_detection.py::TestSecretDetectionPolicyBasics::test_custom_entropy_threshold PASSED
tests/safety/test_secret_detection.py::TestSecretDetectionPolicyBasics::test_disabled_test_secrets PASSED
tests/safety/test_secret_detection.py::TestSecretDetectionPolicyBasics::test_selective_pattern_enablement PASSED
tests/safety/test_secret_detection.py::TestSecretDetectionPolicyBasics::test_excluded_paths_configuration PASSED
tests/safety/test_secret_detection.py::TestAWSKeyDetection::test_valid_aws_access_key_detected PASSED
tests/safety/test_secret_detection.py::TestAWSKeyDetection::test_aws_access_key_in_code PASSED
...
tests/safety/test_secret_detection.py::TestCoverageCompleteness::test_violation_has_timestamp PASSED

========== 120+ passed in X.XXs ==========
```

---

## Contact and Support

**Task Spec:** .claude-coord/task-specs/test-crit-secret-detection-01.md
**Implementation:** src/safety/secret_detection.py
**Test File:** tests/safety/test_secret_detection.py
**Design Doc:** .claude-coord/reports/test-secret-detection-design.md

For issues or questions, refer to the comprehensive design document.
