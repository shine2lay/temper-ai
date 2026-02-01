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
import os
from pathlib import Path
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
            # Includes backslash for Windows paths (double backslash in raw string)
            pattern=re.compile(r'^[A-Za-z0-9_./:\\ -]+$'),
            message="Path variables must contain only path-safe characters.",
            examples=[
                "/etc/config",       # Valid (Unix)
                "./configs/agents",  # Valid (Unix)
                "data\\config.yml",  # Valid (Windows)
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

    def _validate_path_traversal(
        self,
        path_value: str,
        base_dir: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate path for traversal attempts (cross-platform).

        Handles:
        - Path normalization (. and ..)
        - Symlink resolution
        - Windows drive letters
        - UNC paths (\\\\server\\share)
        - Mixed separators (/ and \\)

        Args:
            path_value: Path to validate
            base_dir: Optional base directory to check containment

        Returns:
            (is_valid, error_message) - error_message is None if valid
        """
        try:
            # Check for Windows absolute paths BEFORE normalization
            original_path = str(path_value)
            is_unc = original_path.startswith('\\\\') or original_path.startswith('//')
            is_windows_absolute = (
                len(original_path) >= 3 and
                original_path[0].isalpha() and
                original_path[1] == ':' and
                original_path[2] in ('\\', '/')
            )

            # Normalize path separators (convert backslash to forward slash)
            # This ensures cross-platform handling of Windows-style paths on Unix
            path_str = original_path.replace('\\', '/')

            # Normalize and resolve the path (handles .., symlinks, etc.)
            # Try with strict=True first (checks existence), fall back if path doesn't exist yet
            try:
                target = Path(path_str).resolve(strict=True)
            except (FileNotFoundError, RuntimeError, OSError):
                # Path doesn't exist yet (OK for validation), use non-strict resolve
                target = Path(path_str).resolve()

            # If base_dir provided, check containment and absolute path restrictions
            if base_dir:
                base = Path(base_dir).resolve()

                # Reject Windows absolute paths (C:\, D:\, etc.)
                if is_windows_absolute:
                    return False, (
                        f"Absolute Windows path not allowed: {path_value}"
                    )

                # Reject UNC paths if base is not UNC
                base_is_unc = str(base_dir).startswith('\\\\') or str(base_dir).startswith('//')
                if is_unc and not base_is_unc:
                    return False, "UNC path not allowed when base is not UNC"

                # Check if target is within base directory
                try:
                    target.relative_to(base)
                except ValueError:
                    return False, (
                        f"Path escapes base directory: {path_value} "
                        f"is not within {base_dir}"
                    )

                # Check for drive letter mismatch (Windows or when path has drive)
                if base.drive or target.drive:
                    if base.drive != target.drive:
                        return False, (
                            f"Path on different drive: {target.drive} vs {base.drive}"
                        )

            # Note: resolve() handles .. patterns, so no additional check needed
            # The containment check above (relative_to) catches any escapes
            return True, None

        except (ValueError, OSError) as e:
            return False, f"Invalid path: {e}"

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
            # Check for path traversal using robust cross-platform validation
            # Use current working directory as base to prevent absolute path access
            is_safe, error_msg = self._validate_path_traversal(value, base_dir=os.getcwd())
            if not is_safe:
                return False, (
                    f"Environment variable '{var_name}' failed path validation: "
                    f"{error_msg}"
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
