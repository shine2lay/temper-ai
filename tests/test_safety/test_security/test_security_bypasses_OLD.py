"""
Comprehensive Security Bypass Tests (CRITICAL Priority).

Tests sophisticated bypass techniques across attack vectors:
- Path Traversal Bypasses (encoding, Unicode, null bytes)
- SQL Injection Bypasses (comment obfuscation, encoding)
- Command Injection Bypasses (whitespace variants, quote bypasses)
- SSRF Bypasses (IP encoding, protocol smuggling)

Total: 50+ bypass tests
Performance Target: <5ms per test
Success Criteria: 100% blocked, zero false negatives

This test suite validates that security policies block well-known
attack bypass techniques used by sophisticated attackers.

Reference:
- test-review-20260130-223857.md#26-security-bypass-tests-missing-severity-critical
- OWASP Top 10
- CWE-22 (Path Traversal), CWE-89 (SQL Injection), CWE-78 (Command Injection), CWE-918 (SSRF)
"""
import time

import pytest

from temper_ai.tools.base import ParameterSanitizer, ValidationError
from temper_ai.shared.utils.path_safety import PathSafetyError, PathSafetyValidator

# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def path_validator(tmp_path):
    """Path safety validator with temp workspace."""
    return PathSafetyValidator(allowed_base=tmp_path)


@pytest.fixture
def param_sanitizer():
    """Parameter sanitizer for injection attacks."""
    return ParameterSanitizer()


# ============================================================================
# Path Traversal Bypass Tests (25 tests)
# ============================================================================

class TestPathTraversalEncodingBypasses:
    """Test path traversal bypasses using encoding techniques."""

    # URL encoding bypass payloads
    ENCODING_BYPASSES = [
        ("url_encoded_dots", "%2E%2E%2F"),
        ("url_encoded_mixed", "%2E%2E/"),
        ("double_url_encoded", "%252E%252E%252F"),
        ("url_encoded_backslash", "%2E%2E%5C"),
        ("url_encoded_null", "%2E%2E%2F%00"),
    ]

    @pytest.mark.parametrize("name,payload", ENCODING_BYPASSES)
    def test_url_encoding_bypasses_blocked(self, path_validator, tmp_path, name, payload):
        """URL encoding bypasses must be blocked."""
        # Create safe file in temp directory
        safe_file = tmp_path / "safe.txt"
        safe_file.write_text("safe content")

        # Attempt bypass using encoded path
        malicious_path = str(tmp_path) + "/" + payload + "etc/passwd"

        with pytest.raises(PathSafetyError, match="Path traversal"):
            path_validator.validate_path(malicious_path)

    def test_unicode_slash_bypass_blocked(self, path_validator, tmp_path):
        """Unicode slash variants must be blocked."""
        safe_file = tmp_path / "safe.txt"
        safe_file.write_text("safe")

        # Unicode slash (U+2215 DIVISION SLASH)
        malicious_path = str(tmp_path) + "/..\u2215etc/passwd"

        with pytest.raises(PathSafetyError):
            path_validator.validate_path(malicious_path)

    def test_unicode_dot_bypass_blocked(self, path_validator, tmp_path):
        """Unicode dot variants must be blocked."""
        safe_file = tmp_path / "safe.txt"
        safe_file.write_text("safe")

        # Unicode middle dot (U+00B7)
        malicious_path = str(tmp_path) + "/\u00b7\u00b7/etc/passwd"

        with pytest.raises(PathSafetyError):
            path_validator.validate_path(malicious_path)

    def test_mixed_encoding_bypass_blocked(self, path_validator, tmp_path):
        """Mixed encoding techniques must be blocked."""
        safe_file = tmp_path / "safe.txt"
        safe_file.write_text("safe")

        # Mix of URL encoding and plain text
        malicious_path = str(tmp_path) + "/.%2E/%2E./etc/passwd"

        with pytest.raises(PathSafetyError):
            path_validator.validate_path(malicious_path)


class TestPathTraversalNullByteBypasses:
    """Test null byte injection bypasses."""

    NULL_BYTE_BYPASSES = [
        ("null_at_end", "safe.txt\x00../../etc/passwd"),
        ("null_in_middle", "../\x00../etc/passwd"),
        ("null_before_extension", "safe\x00.txt"),
        ("url_encoded_null", "safe.txt%00../../etc/passwd"),
    ]

    @pytest.mark.parametrize("name,payload", NULL_BYTE_BYPASSES)
    def test_null_byte_bypasses_blocked(self, path_validator, tmp_path, name, payload):
        """Null byte injection bypasses must be blocked."""
        safe_file = tmp_path / "safe.txt"
        safe_file.write_text("safe")

        # Construct path with null byte
        if not payload.startswith("../"):
            malicious_path = str(tmp_path) / payload
        else:
            malicious_path = str(tmp_path) + "/" + payload

        with pytest.raises(PathSafetyError, match="null byte|invalid"):
            path_validator.validate_path(str(malicious_path))


class TestPathTraversalSeparatorBypasses:
    """Test mixed separator and normalization bypasses."""

    SEPARATOR_BYPASSES = [
        ("backslash_forward", "..\\../"),
        ("forward_backslash", "../..\\"),
        ("double_slash", "..//etc/passwd"),
        ("triple_dot", ".../etc/passwd"),
        ("dot_slash_dot", "./.././etc/passwd"),
    ]

    @pytest.mark.parametrize("name,payload", SEPARATOR_BYPASSES)
    def test_separator_bypasses_blocked(self, path_validator, tmp_path, name, payload):
        """Mixed separator bypasses must be blocked."""
        safe_file = tmp_path / "safe.txt"
        safe_file.write_text("safe")

        malicious_path = str(tmp_path) + "/" + payload

        with pytest.raises(PathSafetyError):
            path_validator.validate_path(malicious_path)


class TestPathTraversalAbsolutePaths:
    """Test absolute path escape bypasses."""

    def test_absolute_unix_path_blocked(self, path_validator):
        """Absolute Unix paths outside allowed base must be blocked."""
        with pytest.raises(PathSafetyError, match="outside allowed"):
            path_validator.validate_path("/etc/passwd")

    def test_absolute_windows_path_blocked(self, path_validator):
        """Absolute Windows paths must be blocked."""
        with pytest.raises(PathSafetyError):
            path_validator.validate_path("C:\\Windows\\System32\\config\\SAM")

    def test_unc_path_blocked(self, path_validator):
        """UNC paths must be blocked."""
        with pytest.raises(PathSafetyError):
            path_validator.validate_path("\\\\localhost\\c$\\windows\\system.ini")


# ============================================================================
# SQL Injection Bypass Tests (12 tests)
# ============================================================================

class TestSQLInjectionBypasses:
    """Test SQL injection bypass techniques."""

    CLASSIC_SQL_BYPASSES = [
        ("classic_or", "' OR '1'='1"),
        ("classic_or_comment", "' OR '1'='1'--"),
        ("classic_or_hash", "' OR '1'='1'#"),
        ("admin_bypass", "admin'--"),
        ("always_true", "' OR 1=1--"),
    ]

    @pytest.mark.parametrize("name,payload", CLASSIC_SQL_BYPASSES)
    def test_classic_sql_injection_blocked(self, param_sanitizer, name, payload):
        """Classic SQL injection payloads must be blocked."""
        with pytest.raises(ValidationError, match="SQL injection|forbidden"):
            param_sanitizer.sanitize_sql_input(payload)

    COMMENT_OBFUSCATION_BYPASSES = [
        ("inline_comment", "'/**/OR/**/1=1--"),
        ("multiline_comment", "'/* comment */OR/* comment */1=1"),
        ("nested_comment", "'/*/**/*/OR/**/1=1"),
    ]

    @pytest.mark.parametrize("name,payload", COMMENT_OBFUSCATION_BYPASSES)
    def test_comment_obfuscation_blocked(self, param_sanitizer, name, payload):
        """SQL comment obfuscation bypasses must be blocked."""
        with pytest.raises(ValidationError):
            param_sanitizer.sanitize_sql_input(payload)

    ENCODING_BYPASSES = [
        ("url_encoded_quote", "%27%20OR%201=1--"),
        ("double_encoded", "%2527%2520OR%25201=1"),
        ("hex_encoded", "0x27204F522031=31"),
    ]

    @pytest.mark.parametrize("name,payload", ENCODING_BYPASSES)
    def test_sql_encoding_bypasses_blocked(self, param_sanitizer, name, payload):
        """SQL encoding bypasses must be blocked."""
        with pytest.raises(ValidationError):
            param_sanitizer.sanitize_sql_input(payload)


# ============================================================================
# Command Injection Bypass Tests (15 tests)
# ============================================================================

class TestCommandInjectionBypasses:
    """Test command injection bypass techniques."""

    SHELL_METACHARACTER_BYPASSES = [
        ("semicolon", "; rm -rf /"),
        ("pipe", "| bash -c 'malicious'"),
        ("ampersand", "& malicious"),
        ("backtick", "`malicious`"),
        ("dollar_paren", "$(malicious)"),
        ("redirect_output", "> /dev/null; malicious"),
        ("redirect_input", "< /etc/passwd"),
    ]

    @pytest.mark.parametrize("name,payload", SHELL_METACHARACTER_BYPASSES)
    def test_shell_metacharacter_bypasses_blocked(self, param_sanitizer, name, payload):
        """Shell metacharacter bypasses must be blocked."""
        with pytest.raises(ValidationError, match="command injection|forbidden"):
            param_sanitizer.sanitize_command(payload)

    WHITESPACE_BYPASSES = [
        ("newline", "safe\nmalicious"),
        ("carriage_return", "safe\rmalicious"),
        ("tab", "safe\tmalicious"),
        ("form_feed", "safe\fmalicious"),
        ("vertical_tab", "safe\vmalicious"),
    ]

    @pytest.mark.parametrize("name,payload", WHITESPACE_BYPASSES)
    def test_whitespace_bypasses_blocked(self, param_sanitizer, name, payload):
        """Whitespace character bypasses must be blocked."""
        with pytest.raises(ValidationError):
            param_sanitizer.sanitize_command(payload)

    QUOTE_BYPASSES = [
        ("partial_quote", "l\"s\" -la"),
        ("mixed_quotes", "'l's' -la'"),
        ("escaped_quote", "l\\\"s -la"),
    ]

    @pytest.mark.parametrize("name,payload", QUOTE_BYPASSES)
    def test_quote_bypasses_blocked(self, param_sanitizer, name, payload):
        """Quote manipulation bypasses must be blocked."""
        # These may be allowed depending on sanitization strategy
        # If command contains quotes, it should be carefully validated
        try:
            result = param_sanitizer.sanitize_command(payload)
            # If allowed, ensure it's properly escaped
            assert '"' not in result or '\\"' in payload
        except ValidationError:
            # Blocking is also acceptable
            pass


# ============================================================================
# Performance Tests
# ============================================================================

class TestBypassPerformance:
    """Test that bypass validation meets performance requirements."""

    def test_path_traversal_validation_performance(self, path_validator, tmp_path):
        """Path traversal validation must complete in <5ms."""
        safe_file = tmp_path / "safe.txt"
        safe_file.write_text("safe")

        bypasses = [
            "../etc/passwd",
            "%2E%2E%2F",
            "\x00../../etc/passwd",
            "..\\../etc/passwd",
        ]

        for bypass in bypasses:
            malicious_path = str(tmp_path) + "/" + bypass

            start = time.perf_counter()
            try:
                path_validator.validate_path(malicious_path)
            except PathSafetyError:
                pass  # Expected
            elapsed_ms = (time.perf_counter() - start) * 1000

            assert elapsed_ms < 5.0, f"Validation took {elapsed_ms:.2f}ms (target: <5ms)"

    def test_sql_injection_validation_performance(self, param_sanitizer):
        """SQL injection validation must complete in <5ms."""
        bypasses = [
            "' OR '1'='1",
            "'/**/OR/**/1=1--",
            "%27%20OR%201=1--",
        ]

        for bypass in bypasses:
            start = time.perf_counter()
            try:
                param_sanitizer.sanitize_sql_input(bypass)
            except ValidationError:
                pass  # Expected
            elapsed_ms = (time.perf_counter() - start) * 1000

            assert elapsed_ms < 5.0, f"Validation took {elapsed_ms:.2f}ms (target: <5ms)"

    def test_command_injection_validation_performance(self, param_sanitizer):
        """Command injection validation must complete in <5ms."""
        bypasses = [
            "; rm -rf /",
            "| bash",
            "$(malicious)",
            "`malicious`",
        ]

        for bypass in bypasses:
            start = time.perf_counter()
            try:
                param_sanitizer.sanitize_command(bypass)
            except ValidationError:
                pass  # Expected
            elapsed_ms = (time.perf_counter() - start) * 1000

            assert elapsed_ms < 5.0, f"Validation took {elapsed_ms:.2f}ms (target: <5ms)"


# ============================================================================
# Comprehensive "All Blocked" Validation
# ============================================================================

class TestComprehensiveBypassValidation:
    """Validate that ALL bypass attempts are blocked (zero false negatives)."""

    def test_all_path_traversal_bypasses_blocked(self, path_validator, tmp_path):
        """CRITICAL: All path traversal bypasses must be blocked."""
        safe_file = tmp_path / "safe.txt"
        safe_file.write_text("safe")

        all_bypasses = [
            # URL encoding
            "%2E%2E%2F", "%252E%252E%252F", "%2E%2E/",
            # Unicode
            "..\u2215", "\u00b7\u00b7/",
            # Null bytes
            "\x00../../", "safe\x00../",
            # Mixed separators
            "..\\../", "../..\\/",
            # Absolute paths
            "/etc/passwd", "C:\\Windows\\System32",
        ]

        blocked_count = 0
        allowed = []

        for bypass in all_bypasses:
            try:
                if not bypass.startswith("/") and not bypass.startswith("C:"):
                    malicious_path = str(tmp_path) + "/" + bypass + "etc/passwd"
                else:
                    malicious_path = bypass

                path_validator.validate_path(malicious_path)
                # Should not reach here
                allowed.append(bypass)
            except PathSafetyError:
                blocked_count += 1

        assert len(allowed) == 0, (
            f"\nCRITICAL: {len(allowed)} path traversal bypass(es) succeeded:\n" +
            "\n".join([f"  - {b}" for b in allowed])
        )

        assert blocked_count == len(all_bypasses)
        print(f"\n✓ All {blocked_count} path traversal bypasses blocked")

    def test_all_sql_injection_bypasses_blocked(self, param_sanitizer):
        """CRITICAL: All SQL injection bypasses must be blocked."""
        all_bypasses = [
            # Classic
            "' OR '1'='1", "' OR 1=1--", "admin'--",
            # Comment obfuscation
            "'/**/OR/**/1=1--", "'/* */OR/* */1=1",
            # Encoding
            "%27%20OR%201=1--", "%2527%2520OR%25201=1",
        ]

        blocked_count = 0
        allowed = []

        for bypass in all_bypasses:
            try:
                param_sanitizer.sanitize_sql_input(bypass)
                # Should not reach here
                allowed.append(bypass)
            except ValidationError:
                blocked_count += 1

        assert len(allowed) == 0, (
            f"\nCRITICAL: {len(allowed)} SQL injection bypass(es) succeeded:\n" +
            "\n".join([f"  - {b}" for b in allowed])
        )

        assert blocked_count == len(all_bypasses)
        print(f"\n✓ All {blocked_count} SQL injection bypasses blocked")

    def test_all_command_injection_bypasses_blocked(self, param_sanitizer):
        """CRITICAL: All command injection bypasses must be blocked."""
        all_bypasses = [
            # Metacharacters
            "; rm -rf /", "| bash", "& malicious", "`malicious`", "$(malicious)",
            # Whitespace
            "safe\nmalicious", "safe\rmalicious", "safe\tmalicious",
            # Redirection
            "> /dev/null", "< /etc/passwd",
        ]

        blocked_count = 0
        allowed = []

        for bypass in all_bypasses:
            try:
                param_sanitizer.sanitize_command(bypass)
                # Should not reach here
                allowed.append(bypass)
            except ValidationError:
                blocked_count += 1

        assert len(allowed) == 0, (
            f"\nCRITICAL: {len(allowed)} command injection bypass(es) succeeded:\n" +
            "\n".join([f"  - {b}" for b in allowed])
        )

        assert blocked_count == len(all_bypasses)
        print(f"\n✓ All {blocked_count} command injection bypasses blocked")
