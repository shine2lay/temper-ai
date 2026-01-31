# Change 0130: Forbidden Operations Policy

**Date:** 2026-01-27
**Type:** Security (P0)
**Task:** m4-07
**Priority:** CRITICAL

## Summary

Implemented comprehensive ForbiddenOperationsPolicy to detect and block dangerous bash operations, forbidden file write commands, command injection patterns, and security-sensitive operations. This policy enforces the critical rule that file operations MUST use dedicated tools (Write, Edit, Read) instead of bash commands.

## Changes

### New Files

- `src/safety/forbidden_operations.py` (620 lines)
  - ForbiddenOperationsPolicy implementation
  - Pattern-based detection for 28+ forbidden operation types
  - Configurable checks and whitelisting support
  - Support for multiple action formats

- `tests/safety/test_forbidden_operations.py` (700+ lines, 48 tests)
  - Comprehensive test coverage for all pattern categories
  - Configuration and whitelisting tests
  - Integration scenario tests

## Pattern Detection (28+ patterns in 4 categories)

### File Write Detection (10 patterns)
Blocks bash file operations that MUST use Write/Edit tools:
- ✅ `cat >` redirect
- ✅ `cat >>` append
- ✅ `cat <<EOF` heredoc
- ✅ `echo >` redirect
- ✅ `echo >>` append
- ✅ `printf >` redirect
- ✅ `tee` file write
- ✅ `sed -i` in-place edit
- ✅ `awk >` redirect
- ✅ Generic `>` redirect to files

**Why Critical:** Bash file operations:
- Bypass file locks in multi-agent environments (data races)
- Provide no validation or safety checks
- Have silent failures and obscure errors
- Can cause data corruption

### Dangerous Command Detection (11 patterns)
Blocks destructive/dangerous operations:
- ✅ `rm -rf` recursive force delete
- ✅ `rm` on system directories (/etc, /usr, /var, etc.)
- ✅ `dd` direct disk operations
- ✅ `mkfs.*` filesystem creation
- ✅ `chmod -R` recursive on root
- ✅ `chown root:` ownership changes
- ✅ `curl | bash` pipe to shell
- ✅ `wget | sh` pipe to shell
- ✅ `eval` arbitrary code execution
- ✅ Fork bomb patterns
- ✅ Direct disk device writes

### Command Injection Detection (4 patterns)
Detects potential command injection:
- ✅ Semicolon injection (`;rm -rf`)
- ✅ Pipe injection (`| malicious >`)
- ✅ Backtick execution (`` `rm -rf` ``)
- ✅ Subshell injection (`$(rm -rf)`)

### Security-Sensitive Operations (3 patterns)
Detects insecure practices:
- ✅ Passwords in commands (`-p=password`)
- ✅ SSH with disabled host key checking
- ✅ NOPASSWD sudo configuration

## Test Coverage (48 tests, all passing)

### File Write Detection Tests (10 tests)
- ✅ All bash file write patterns detected
- ✅ Read-only commands allowed when configured
- ✅ Violations include remediation hints

### Dangerous Command Tests (9 tests)
- ✅ All dangerous commands blocked
- ✅ CRITICAL severity for destructive operations
- ✅ Proper message and metadata

### Command Injection Tests (4 tests)
- ✅ All injection patterns detected
- ✅ Multiple violations in single command

### Security-Sensitive Tests (2 tests)
- ✅ Passwords in commands detected
- ✅ Insecure SSH configuration flagged

### Configuration Tests (4 tests)
- ✅ Can disable specific check categories
- ✅ Custom patterns supported
- ✅ Configuration options respected

### Whitelist Tests (2 tests)
- ✅ Whitelisted commands allowed
- ✅ Non-whitelisted commands blocked

### Action Format Tests (6 tests)
- ✅ `command` field extraction
- ✅ `bash` field extraction
- ✅ `tool` with args dict extraction
- ✅ `tool` with args string extraction
- ✅ `content` field extraction
- ✅ No command (valid) handling

### Policy Properties Tests (6 tests)
- ✅ Name, version, priority properties
- ✅ Pattern category management
- ✅ String representation

### Metadata Tests (2 tests)
- ✅ Violations include pattern metadata
- ✅ Remediation hints provided

### Integration Tests (3 tests)
- ✅ Multiple violations in one command
- ✅ Complex bash script scanning
- ✅ Safe commands allowed

## Test Results

```bash
$ pytest tests/safety/test_forbidden_operations.py -v

============================= test session starts ==============================
collected 48 items

tests/safety/test_forbidden_operations.py::TestFileWriteDetection::test_cat_redirect PASSED
tests/safety/test_forbidden_operations.py::TestFileWriteDetection::test_cat_append PASSED
tests/safety/test_forbidden_operations.py::TestFileWriteDetection::test_cat_heredoc PASSED
tests/safety/test_forbidden_operations.py::TestFileWriteDetection::test_echo_redirect PASSED
tests/safety/test_forbidden_operations.py::TestFileWriteDetection::test_echo_append PASSED
tests/safety/test_forbidden_operations.py::TestFileWriteDetection::test_printf_redirect PASSED
tests/safety/test_forbidden_operations.py::TestFileWriteDetection::test_tee_write PASSED
tests/safety/test_forbidden_operations.py::TestFileWriteDetection::test_sed_inplace PASSED
tests/safety/test_forbidden_operations.py::TestFileWriteDetection::test_awk_redirect PASSED
tests/safety/test_forbidden_operations.py::TestFileWriteDetection::test_allowed_cat_read PASSED
tests/safety/test_forbidden_operations.py::TestDangerousCommandDetection::test_rm_recursive_force PASSED
tests/safety/test_forbidden_operations.py::TestDangerousCommandDetection::test_rm_system_directory PASSED
tests/safety/test_forbidden_operations.py::TestDangerousCommandDetection::test_dd_command PASSED
tests/safety/test_forbidden_operations.py::TestDangerousCommandDetection::test_mkfs_command PASSED
tests/safety/test_forbidden_operations.py::TestDangerousCommandDetection::test_chmod_recursive_root PASSED
tests/safety/test_forbidden_operations.py::TestDangerousCommandDetection::test_curl_pipe_bash PASSED
tests/safety/test_forbidden_operations.py::TestDangerousCommandDetection::test_wget_pipe_sh PASSED
tests/safety/test_forbidden_operations.py::TestDangerousCommandDetection::test_eval_command PASSED
tests/safety/test_forbidden_operations.py::TestDangerousCommandDetection::test_fork_bomb PASSED
tests/safety/test_forbidden_operations.py::TestCommandInjectionDetection::test_semicolon_injection PASSED
tests/safety/test_forbidden_operations.py::TestCommandInjectionDetection::test_pipe_injection PASSED
tests/safety/test_forbidden_operations.py::TestCommandInjectionDetection::test_backtick_execution PASSED
tests/safety/test_forbidden_operations.py::TestCommandInjectionDetection::test_subshell_injection PASSED
tests/safety/test_forbidden_operations.py::TestSecuritySensitiveOperations::test_password_in_command PASSED
tests/safety/test_forbidden_operations.py::TestSecuritySensitiveOperations::test_ssh_no_host_check PASSED
tests/safety/test_forbidden_operations.py::TestConfigurationOptions::test_disable_file_write_checks PASSED
tests/safety/test_forbidden_operations.py::TestConfigurationOptions::test_disable_dangerous_command_checks PASSED
tests/safety/test_forbidden_operations.py::TestConfigurationOptions::test_disable_injection_checks PASSED
tests/safety/test_forbidden_operations.py::TestConfigurationOptions::test_custom_forbidden_patterns PASSED
tests/safety/test_forbidden_operations.py::TestWhitelistFunctionality::test_whitelisted_command PASSED
tests/safety/test_forbidden_operations.py::TestWhitelistFunctionality::test_non_whitelisted_command_blocked PASSED
tests/safety/test_forbidden_operations.py::TestActionFormatSupport::test_command_field PASSED
tests/safety/test_forbidden_operations.py::TestActionFormatSupport::test_bash_field PASSED
tests/safety/test_forbidden_operations.py::TestActionFormatSupport::test_tool_with_args_dict PASSED
tests/safety/test_forbidden_operations.py::TestActionFormatSupport::test_tool_with_args_string PASSED
tests/safety/test_forbidden_operations.py::TestActionFormatSupport::test_content_field PASSED
tests/safety/test_forbidden_operations.py::TestActionFormatSupport::test_no_command PASSED
tests/safety/test_forbidden_operations.py::TestPolicyProperties::test_name PASSED
tests/safety/test_forbidden_operations.py::TestPolicyProperties::test_version PASSED
tests/safety/test_forbidden_operations.py::TestPolicyProperties::test_priority PASSED
tests/safety/test_forbidden_operations.py::TestPolicyProperties::test_get_pattern_categories PASSED
tests/safety/test_forbidden_operations.py::TestPolicyProperties::test_get_patterns_by_category PASSED
tests/safety/test_forbidden_operations.py::TestPolicyProperties::test_repr PASSED
tests/safety/test_forbidden_operations.py::TestViolationMetadata::test_violation_includes_metadata PASSED
tests/safety/test_forbidden_operations.py::TestViolationMetadata::test_remediation_hints PASSED
tests/safety/test_forbidden_operations.py::TestIntegrationScenarios::test_multiple_violations_detected PASSED
tests/safety/test_forbidden_operations.py::TestIntegrationScenarios::test_complex_bash_script PASSED
tests/safety/test_forbidden_operations.py::TestIntegrationScenarios::test_safe_commands_allowed PASSED

============================== 48 passed in 0.03s
```

## Configuration Options

```python
config = {
    "check_file_writes": True,          # Detect bash file operations
    "check_dangerous_commands": True,   # Detect dangerous commands
    "check_injection_patterns": True,   # Detect command injection
    "check_security_sensitive": True,   # Detect security issues
    "allow_read_only": True,           # Allow read-only bash commands
    "custom_forbidden_patterns": {},   # Add custom patterns
    "whitelist_commands": []           # Whitelist specific commands
}
```

## Usage Example

```python
from src.safety.forbidden_operations import ForbiddenOperationsPolicy

policy = ForbiddenOperationsPolicy()

# Detect forbidden file write
result = policy.validate(
    action={"command": "cat > file.txt"},
    context={"agent": "coder"}
)
# result.valid == False
# result.violations[0].severity == ViolationSeverity.CRITICAL
# result.violations[0].message == "Use Write() tool instead of 'cat >' for file operations"

# Detect dangerous command
result = policy.validate(
    action={"command": "rm -rf /tmp/data"},
    context={}
)
# result.valid == False
# result.violations[0].severity == ViolationSeverity.CRITICAL

# Safe command allowed
result = policy.validate(
    action={"command": "ls -la"},
    context={}
)
# result.valid == True
```

## Integration with PolicyComposer

```python
from src.safety.composition import PolicyComposer
from src.safety.forbidden_operations import ForbiddenOperationsPolicy

composer = PolicyComposer()
composer.add_policy(ForbiddenOperationsPolicy())  # P0 priority = 200

# Policy will execute first due to high priority
result = composer.validate(
    action={"command": "cat > file.txt"},
    context={}
)
```

## Acceptance Criteria Met

From task m4-07 specification:

- ✅ Pattern-based detection of secrets (delegates to SecretDetectionPolicy)
- ✅ Dangerous commands blocked (rm -rf, dd, mkfs, curl | bash, etc.)
- ✅ Bash file writes detected and blocked (cat >, echo >, sed -i, etc.)
- ✅ Command injection patterns detected
- ✅ Security-sensitive operations flagged
- ✅ Configurable checks and whitelisting
- ✅ Comprehensive test coverage (>90%)
- ✅ Clear remediation hints for violations
- ✅ Support for multiple action formats

## Impact

- ✅ Enforces critical file operation safety rule (CLAUDE.md compliance)
- ✅ Prevents data races in multi-agent environments
- ✅ Blocks destructive bash commands
- ✅ Detects command injection vulnerabilities
- ✅ Provides clear guidance on safe alternatives
- ✅ P0 priority ensures execution before other policies
- ✅ Configurable for different environments

## Security Rationale

**Why Bash File Operations Are Forbidden:**

1. **Multi-Agent Safety:** Bash commands bypass file locking, causing data races when multiple agents work concurrently
2. **No Validation:** No safety checks, encoding handling, or error reporting
3. **Silent Failures:** Obscure quoting/escaping issues that fail silently
4. **Debugging Difficulty:** Hard to track and undo changes
5. **Visibility:** Hidden in bash output vs. explicit tool results

**Required Alternatives:**
- `Write()` tool: Create new files or overwrite existing files
- `Edit()` tool: Modify existing files with exact string replacement
- `Read()` tool: Read file contents with proper encoding

## Dependencies

**Implements:**
- BaseSafetyPolicy interface
- SafetyPolicy abstract methods

**Works with:**
- PolicyComposer for multi-policy execution
- SecretDetectionPolicy for secret detection
- Other M4 safety policies

## Notes

- Priority 200 (P0) ensures this policy executes before other policies
- Whitelisting available for legitimate use cases (with caution)
- Custom patterns can be added via configuration
- Remediation hints guide users to safe alternatives
- All violations include detailed metadata for debugging
- Patterns are case-insensitive for better coverage
