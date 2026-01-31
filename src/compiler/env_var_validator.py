"""
Enhanced Environment Variable Validation with Context-Aware Security.

This module provides context-aware validation for environment variables to prevent
command injection, SQL injection, path traversal, and other security vulnerabilities.

SECURITY PRINCIPLES:
1. Defense in Depth: Multiple validation layers
2. Whitelist over Blacklist: Define what's allowed, not what's forbidden
3. Context-Aware: Validate based on how value will be used
4. Fail Secure: Reject on doubt
5. Principle of Least Privilege: Strictest validation by default
"""

import re
from typing import Dict, Pattern, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class ValidationLevel(Enum):
    """Validation strictness levels based on variable usage context."""

    EXECUTABLE = "executable"      # Commands - CRITICAL (strictest)
    PATH = "path"                  # File/directory paths - HIGH
    STRUCTURED = "structured"      # URLs, connection strings - MEDIUM
    IDENTIFIER = "identifier"      # DB names, model names - MEDIUM
    DATA = "data"                  # General config, tokens - LOW
    UNRESTRICTED = "unrestricted"  # Prompts, descriptions - MINIMAL (most permissive)


@dataclass
class ValidationRule:
    """Validation rule for environment variables."""

    level: ValidationLevel
    pattern: Pattern[str]
    message: str
    examples: list[str]


class EnvVarValidator:
    """
    Context-aware environment variable validator.

    Validates environment variables based on:
    1. Variable name patterns (heuristic context detection)
    2. Explicit context hints from config
    3. Security best practices

    Example:
        validator = EnvVarValidator()

        # Auto-detect context from variable name
        is_valid, error = validator.validate("SHELL_CMD", "ls; rm -rf /")
        # Returns: (False, "Executable context variables cannot contain...")

        # Explicit context override
        is_valid, error = validator.validate(
            "CUSTOM_VAR",
            "value",
            context=ValidationLevel.EXECUTABLE
        )
    """

    # Context detection based on variable name patterns
    # Order matters: check UNRESTRICTED first to avoid false matches
    # (e.g., "DESCRIPTION" contains "script" but should be UNRESTRICTED)
    CONTEXT_PATTERNS: Dict[ValidationLevel, list[str]] = {
        ValidationLevel.UNRESTRICTED: [
            'prompt', 'description', 'message', 'text',
            'content_text', 'template_content'
        ],
        ValidationLevel.EXECUTABLE: [
            'cmd', 'command', 'exec', 'script', 'shell', 'run',
            'binary', 'executable', 'program', 'process'
        ],
        ValidationLevel.PATH: [
            'path', 'dir', 'directory', 'file', 'folder',
            'root', 'home', 'config_root'
        ],
        ValidationLevel.STRUCTURED: [
            'url', 'uri', 'endpoint', 'host', 'address',
            'dsn', 'connection', 'connection_string'
        ],
        ValidationLevel.IDENTIFIER: [
            'db', 'database', 'schema', 'table', 'collection',
            'model', 'provider', 'name', 'id'
        ],
        ValidationLevel.DATA: [
            'key', 'token', 'secret', 'password', 'credential',
            'api_key', 'auth'
        ]
    }

    # Validation rules per context
    # Patterns use whitelist approach: define what IS allowed
    VALIDATION_RULES: Dict[ValidationLevel, ValidationRule] = {
        ValidationLevel.EXECUTABLE: ValidationRule(
            level=ValidationLevel.EXECUTABLE,
            # NEVER allow shell metacharacters in executable contexts
            # Only alphanumeric, underscore, dot, slash, colon, hyphen
            pattern=re.compile(r'^[A-Za-z0-9_./:-]+$'),
            message=(
                "Executable context variables cannot contain shell metacharacters. "
                "Allowed: alphanumeric, underscore, dot, slash, colon, hyphen."
            ),
            examples=[
                "/usr/bin/python3",  # Valid
                "python",            # Valid
                "ls; rm -rf /",      # BLOCKED
                "$(whoami)",         # BLOCKED
            ]
        ),

        ValidationLevel.PATH: ValidationRule(
            level=ValidationLevel.PATH,
            # Path-safe characters (traversal checked separately)
            pattern=re.compile(r'^[A-Za-z0-9_./: -]+$'),
            message="Path variables must contain only path-safe characters.",
            examples=[
                "/etc/config",       # Valid
                "./configs/agents",  # Valid
                "../../../passwd",   # BLOCKED (traversal check)
                "/tmp; rm -rf /",    # BLOCKED (semicolon)
            ]
        ),

        ValidationLevel.STRUCTURED: ValidationRule(
            level=ValidationLevel.STRUCTURED,
            # Allow URL/connection string characters
            # Includes: scheme, user, password, host, port, path, query
            pattern=re.compile(r'^[A-Za-z0-9_.:/@?&=#%+,;-]+$'),
            message="Structured data must be properly formatted.",
            examples=[
                "https://api.example.com:443",              # Valid
                "postgresql://user:pass@localhost:5432/db", # Valid
                "api.com?key=value&foo=bar",               # Valid
                "url`whoami`",                             # BLOCKED (backtick)
            ]
        ),

        ValidationLevel.IDENTIFIER: ValidationRule(
            level=ValidationLevel.IDENTIFIER,
            # Database/model identifiers: alphanumeric + limited special chars
            pattern=re.compile(r'^[A-Za-z0-9_:./-]+$'),
            message="Identifiers must be alphanumeric with limited special characters.",
            examples=[
                "llama3.2:3b",       # Valid (model name)
                "my_database",       # Valid
                "users_table",       # Valid
                "'; DROP TABLE --",  # BLOCKED (SQL injection)
            ]
        ),

        ValidationLevel.DATA: ValidationRule(
            level=ValidationLevel.DATA,
            # API keys, tokens: alphanumeric + common separators
            pattern=re.compile(r'^[A-Za-z0-9_+=./-]+$'),
            message="Credential data contains invalid characters.",
            examples=[
                "sk-1234567890abcdef",     # Valid (OpenAI key)
                "eyJhbGciOiJIUzI1NiIs...", # Valid (JWT)
                "key|whoami",              # BLOCKED (pipe)
            ]
        ),

        ValidationLevel.UNRESTRICTED: ValidationRule(
            level=ValidationLevel.UNRESTRICTED,
            # Printable ASCII + newline + tab + common Unicode - only block null bytes and other control chars
            # \x09 = tab, \x0A = newline, \x0D = carriage return
            pattern=re.compile(r'^[\x09\x0A\x0D\x20-\x7E\u0080-\uFFFF]+$'),
            message="Value contains control characters or null bytes.",
            examples=[
                "This is a prompt with punctuation!",  # Valid
                "Multi-line\ntext with\ttabs",        # Valid
                "Unicode: 测试 émojis 🎉",            # Valid
                "Null\x00byte",                        # BLOCKED
            ]
        ),
    }

    # Dangerous patterns for extra validation in EXECUTABLE context
    DANGEROUS_EXECUTABLE_PATTERNS = [
        (r'\$\(', 'Command substitution $(...)'),
        (r'`', 'Backtick command execution'),
        (r'\|\|', 'OR operator'),
        (r'&&', 'AND operator'),
        (r';', 'Command separator'),
        (r'\|', 'Pipe operator'),
        (r'>', 'Output redirection'),
        (r'<', 'Input redirection'),
        (r'\$\{', 'Variable expansion'),
    ]

    # SQL injection patterns (case-insensitive)
    SQL_INJECTION_PATTERNS = [
        ("'--", "SQL comment injection"),
        ("';", "SQL statement termination"),
        ("' OR '", "SQL boolean injection"),
        ("' UNION ", "SQL UNION injection"),
        ("DROP TABLE", "SQL DROP command"),
        ("DELETE FROM", "SQL DELETE command"),
        ("INSERT INTO", "SQL INSERT command"),
        ("UPDATE ", "SQL UPDATE command"),
        ("EXEC ", "SQL EXEC command"),
        ("xp_", "SQL Server extended procedure"),
    ]

    def detect_context(self, var_name: str) -> ValidationLevel:
        """
        Detect validation context from variable name.

        Args:
            var_name: Environment variable name

        Returns:
            ValidationLevel based on variable name heuristics

        Example:
            >>> validator = EnvVarValidator()
            >>> validator.detect_context("SHELL_CMD")
            ValidationLevel.EXECUTABLE
            >>> validator.detect_context("API_URL")
            ValidationLevel.STRUCTURED
        """
        var_lower = var_name.lower()

        # Check in order: UNRESTRICTED first to avoid false matches,
        # then by strictness (most strict to least strict)
        # This ensures "DESCRIPTION" matches UNRESTRICTED before EXECUTABLE
        for level in [
            ValidationLevel.UNRESTRICTED,
            ValidationLevel.EXECUTABLE,
            ValidationLevel.PATH,
            ValidationLevel.STRUCTURED,
            ValidationLevel.IDENTIFIER,
            ValidationLevel.DATA
        ]:
            patterns = self.CONTEXT_PATTERNS.get(level, [])
            if any(pattern in var_lower for pattern in patterns):
                return level

        # Default to DATA level (medium strictness) for unknown contexts
        # This is safer than UNRESTRICTED
        return ValidationLevel.DATA

    def validate(
        self,
        var_name: str,
        value: str,
        context: Optional[ValidationLevel] = None,
        max_length: int = 10 * 1024  # 10KB default
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate environment variable value with context-aware rules.

        Args:
            var_name: Variable name
            value: Variable value to validate
            context: Explicit validation context (overrides auto-detection)
            max_length: Maximum allowed length in bytes

        Returns:
            (is_valid, error_message) - error_message is None if valid

        Example:
            >>> validator = EnvVarValidator()
            >>> is_valid, error = validator.validate("API_ENDPOINT", "http://api.com; rm -rf /")
            >>> print(is_valid, error)
            False, "Environment variable 'API_ENDPOINT' failed validation..."
        """
        # 1. Check basic constraints (all contexts)
        if len(value) > max_length:
            return False, (
                f"Environment variable '{var_name}' value too long: "
                f"{len(value)} bytes (max: {max_length})"
            )

        if '\x00' in value:
            return False, f"Environment variable '{var_name}' contains null bytes"

        # 2. Detect or use provided context
        validation_level = context or self.detect_context(var_name)
        rule = self.VALIDATION_RULES[validation_level]

        # 3. Pre-validation: Check for specific attack patterns FIRST
        #    This provides better error messages than generic pattern failures

        if validation_level == ValidationLevel.PATH:
            # Check for path traversal (both Unix and Windows style)
            if '../' in value or '..\\' in value:
                return False, (
                    f"Environment variable '{var_name}' contains path "
                    f"traversal pattern"
                )

        elif validation_level == ValidationLevel.EXECUTABLE:
            # Extra strict: Check for known dangerous patterns first
            for pattern_regex, description in self.DANGEROUS_EXECUTABLE_PATTERNS:
                if re.search(pattern_regex, value):
                    return False, (
                        f"Environment variable '{var_name}' contains dangerous "
                        f"pattern in executable context: {description}"
                    )

        elif validation_level == ValidationLevel.IDENTIFIER:
            # Check for SQL injection patterns in database-related identifiers
            # This provides specific error messages
            db_patterns = ['db', 'database', 'table', 'schema', 'query', 'sql']
            if any(pattern in var_name.lower() for pattern in db_patterns):
                for pattern, description in self.SQL_INJECTION_PATTERNS:
                    if pattern.upper() in value.upper():
                        return False, (
                            f"Environment variable '{var_name}' contains SQL "
                            f"injection pattern: {description}"
                        )

        # 4. Apply pattern validation (whitelist approach)
        if not rule.pattern.match(value):
            return False, (
                f"Environment variable '{var_name}' failed validation for "
                f"{validation_level.value} context: {rule.message}"
            )

        # All checks passed
        return True, None
