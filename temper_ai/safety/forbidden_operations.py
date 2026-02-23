"""Forbidden Operations Safety Policy.

Detects and blocks forbidden bash operations, dangerous commands,
command injection, and security-sensitive operations.
See _forbidden_ops_helpers.py for extracted logic.
"""

import re
from typing import Any

# Helper functions and pattern data extracted to reduce class size
from temper_ai.safety._forbidden_ops_helpers import (
    DANGEROUS_COMMAND_PATTERNS,
    FILE_WRITE_PATTERNS,
    INJECTION_PATTERNS,
    SECURITY_SENSITIVE_PATTERNS,
)
from temper_ai.safety._forbidden_ops_helpers import (
    compile_all_patterns as _compile_all_patterns,
)
from temper_ai.safety._forbidden_ops_helpers import (
    extract_command as _extract_command,
)
from temper_ai.safety._forbidden_ops_helpers import (
    get_remediation_hint as _get_remediation_hint,
)
from temper_ai.safety._forbidden_ops_helpers import (
    is_whitelisted as _is_whitelisted,
)
from temper_ai.safety._forbidden_ops_helpers import (
    validate_redirect_context as _validate_redirect_context,
)
from temper_ai.safety.base import BaseSafetyPolicy
from temper_ai.safety.constants import (
    CATEGORY_KEY,
    CUSTOM_FORBIDDEN_PATTERNS_PREFIX,
    MAX_EXCLUDED_PATH_LENGTH,
    MAX_EXCLUDED_PATHS,
    VIOLATION_MESSAGE,
    VIOLATION_SEVERITY,
)
from temper_ai.safety.interfaces import SafetyViolation, ValidationResult
from temper_ai.safety.validation import ValidationMixin
from temper_ai.shared.constants.limits import PERCENT_100
from temper_ai.shared.constants.probabilities import PROB_VERY_LOW

# Forbidden operations policy priority
FORBIDDEN_OPS_PRIORITY = 200
# Maximum whitelist command length
MAX_WHITELIST_COMMAND_LENGTH = 200
# Maximum custom patterns allowed
MAX_CUSTOM_PATTERNS = PERCENT_100


class ForbiddenOperationsPolicy(BaseSafetyPolicy, ValidationMixin):
    """Detects forbidden bash operations and dangerous patterns.

    Uses bounded regex quantifiers to prevent ReDoS attacks.
    See _forbidden_ops_helpers.py for extracted internal logic.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize forbidden operations policy.

        Args:
            config: Policy configuration (optional)

        Raises:
            ValueError: If configuration parameters are invalid
        """
        # Extract and validate custom_forbidden_patterns BEFORE calling super().__init__()
        # because base class rejects nested dicts for security.
        # SA-05: Copy config to avoid mutating caller's dict.
        config = dict(config) if config else {}
        custom_patterns_raw = config.pop("custom_forbidden_patterns", {})

        # Call super().__init__() with config that no longer has nested dict
        super().__init__(config)

        # SECURITY (code-high-12): Validate all configuration inputs
        # Prevents type confusion and ReDoS attacks via malformed patterns

        # Initialize configuration flags
        self._init_boolean_flags()

        # Validate and store custom patterns
        self.custom_forbidden_patterns = self._validate_custom_patterns(
            custom_patterns_raw
        )

        # Validate and store whitelist commands
        self.whitelist_commands = self._validate_whitelist_commands()

        # Compile all patterns
        self.compiled_patterns = self._compile_all_patterns()

    def _init_boolean_flags(self) -> None:
        """Initialize boolean configuration flags."""
        self.check_file_writes = self._validate_boolean(
            self.config.get("check_file_writes", True),
            "check_file_writes",
            default=True,
        )

        self.check_dangerous_commands = self._validate_boolean(
            self.config.get("check_dangerous_commands", True),
            "check_dangerous_commands",
            default=True,
        )

        self.check_injection_patterns = self._validate_boolean(
            self.config.get("check_injection_patterns", True),
            "check_injection_patterns",
            default=True,
        )

        self.check_security_sensitive = self._validate_boolean(
            self.config.get("check_security_sensitive", True),
            "check_security_sensitive",
            default=True,
        )

        self.allow_read_only = self._validate_boolean(
            self.config.get("allow_read_only", True), "allow_read_only", default=True
        )

    def _validate_custom_patterns(self, custom_patterns_raw: Any) -> dict[str, str]:
        """Validate custom forbidden patterns configuration.

        Args:
            custom_patterns_raw: Raw custom patterns from config

        Returns:
            Validated dictionary of custom patterns

        Raises:
            ValueError: If validation fails
        """
        if not isinstance(custom_patterns_raw, dict):
            raise ValueError(
                f"custom_forbidden_patterns must be a dict, got {type(custom_patterns_raw).__name__}"
            )

        custom_patterns: dict[str, str] = {}
        for name, pattern in custom_patterns_raw.items():
            if not isinstance(name, str):
                raise ValueError(
                    f"custom_forbidden_patterns keys must be strings, got {type(name).__name__}"
                )
            if not isinstance(pattern, str):
                raise ValueError(
                    f"{CUSTOM_FORBIDDEN_PATTERNS_PREFIX}{name}'] must be a string, got {type(pattern).__name__}"
                )
            if len(pattern) > MAX_EXCLUDED_PATH_LENGTH:
                raise ValueError(
                    f"{CUSTOM_FORBIDDEN_PATTERNS_PREFIX}{name}'] must be <= {MAX_EXCLUDED_PATH_LENGTH} characters, got {len(pattern)}"
                )

            # SECURITY: Validate regex pattern doesn't have ReDoS vulnerability
            try:
                self._validate_regex_pattern(
                    pattern,
                    f"{CUSTOM_FORBIDDEN_PATTERNS_PREFIX}{name}']",
                    max_length=MAX_EXCLUDED_PATH_LENGTH,
                    test_timeout=PROB_VERY_LOW,
                )
                custom_patterns[name] = pattern
            except ValueError as e:
                raise ValueError(
                    f"Invalid regex in {CUSTOM_FORBIDDEN_PATTERNS_PREFIX}{name}']: {e}"
                )

        if len(custom_patterns) > MAX_CUSTOM_PATTERNS:
            raise ValueError(
                f"custom_forbidden_patterns must have <= {MAX_CUSTOM_PATTERNS} patterns, got {len(custom_patterns)}"
            )

        return custom_patterns

    def _validate_whitelist_commands(self) -> set[str]:
        """Validate whitelist commands configuration.

        Returns:
            Set of validated whitelist commands

        Raises:
            ValueError: If validation fails
        """
        whitelist_raw = self.config.get("whitelist_commands", [])
        if not isinstance(whitelist_raw, list):
            raise ValueError(
                f"whitelist_commands must be a list of strings, got {type(whitelist_raw).__name__}"
            )

        whitelist_validated: list[str] = []
        for cmd in whitelist_raw:
            if not isinstance(cmd, str):
                raise ValueError(
                    f"whitelist_commands items must be strings, got {type(cmd).__name__}"
                )
            if len(cmd) > MAX_WHITELIST_COMMAND_LENGTH:
                raise ValueError(
                    f"whitelist_commands items must be <= {MAX_WHITELIST_COMMAND_LENGTH} characters, got {len(cmd)}"
                )
            whitelist_validated.append(cmd)

        if len(whitelist_validated) > MAX_EXCLUDED_PATHS:
            raise ValueError(
                f"whitelist_commands must have <= {MAX_EXCLUDED_PATHS} items, got {len(whitelist_validated)}"
            )

        return set(whitelist_validated)

    def _compile_all_patterns(self) -> dict[str, dict[str, Any]]:
        """Compile all regex patterns based on configuration."""
        from temper_ai.safety._forbidden_ops_pattern_config import PatternConfig

        config = PatternConfig(
            check_file_writes=self.check_file_writes,
            check_dangerous_commands=self.check_dangerous_commands,
            check_injection_patterns=self.check_injection_patterns,
            check_security_sensitive=self.check_security_sensitive,
            file_write_patterns=FILE_WRITE_PATTERNS,
            dangerous_command_patterns=DANGEROUS_COMMAND_PATTERNS,
            injection_patterns=INJECTION_PATTERNS,
            security_sensitive_patterns=SECURITY_SENSITIVE_PATTERNS,
            custom_forbidden_patterns=self.custom_forbidden_patterns,
        )
        return _compile_all_patterns(config)

    @property
    def name(self) -> str:
        """Return policy name."""
        return "forbidden_operations"

    @property
    def version(self) -> str:
        """Return policy version."""
        return "1.0.0"

    @property
    def priority(self) -> int:
        """Return policy priority (P0 - critical security)."""
        return FORBIDDEN_OPS_PRIORITY  # P0 priority

    def _extract_command(self, action: dict[str, Any]) -> str | None:
        """Extract command string from action."""
        return _extract_command(action)

    def _is_whitelisted(self, command: str) -> bool:
        """Check if command matches whitelist."""
        return _is_whitelisted(command, self.whitelist_commands)

    def _validate_redirect_context(self, command: str, match: re.Match) -> bool:
        """Validate that a redirect match is not in an excluded context."""
        return _validate_redirect_context(command, match)

    def validate(
        self, action: dict[str, Any], context: dict[str, Any]
    ) -> ValidationResult:
        """Validate action for forbidden operations.

        Args:
            action: Action containing command or bash operation
            context: Execution context

        Returns:
            ValidationResult with violations for any forbidden operations
        """
        # Extract command
        command = self._extract_command(action)

        # Guard: No command to check
        if not command:
            return ValidationResult(valid=True, violations=[], policy_name=self.name)

        # Guard: Check whitelist
        if self._is_whitelisted(command):
            return ValidationResult(
                valid=True,
                violations=[],
                policy_name=self.name,
                metadata={"whitelisted": True},
            )

        # Check all patterns for violations
        violations = self._check_all_patterns(command, context)

        # Return result
        return ValidationResult(
            valid=len(violations) == 0,
            violations=violations,
            policy_name=self.name,
            metadata={
                "patterns_checked": len(self.compiled_patterns),
                "violations_found": len(violations),
            },
        )

    def _check_all_patterns(
        self, command: str, context: dict[str, Any]
    ) -> list[SafetyViolation]:
        """Check command against all compiled patterns.

        Args:
            command: Command string to check
            context: Execution context

        Returns:
            List of violations found
        """
        violations = []
        for pattern_name, pattern_info in self.compiled_patterns.items():
            violation = self._check_single_pattern(
                command, context, pattern_name, pattern_info
            )
            if violation:
                violations.append(violation)
        return violations

    def _check_single_pattern(
        self,
        command: str,
        context: dict[str, Any],
        pattern_name: str,
        pattern_info: dict[str, Any],
    ) -> SafetyViolation | None:
        """Check command against a single pattern.

        Args:
            command: Command string to check
            context: Execution context
            pattern_name: Name of the pattern
            pattern_info: Pattern metadata and compiled regex

        Returns:
            SafetyViolation if pattern matches, None otherwise
        """
        match = pattern_info["regex"].search(command)
        if not match:
            return None

        # Check if pattern requires additional context validation
        if pattern_info.get("requires_context_check"):
            if pattern_name == "file_write_redirect_output":
                if not self._validate_redirect_context(command, match):
                    # Excluded context (comment, test, if, while, pipe)
                    return None

        return SafetyViolation(
            policy_name=self.name,
            severity=pattern_info[VIOLATION_SEVERITY],
            message=pattern_info[VIOLATION_MESSAGE],
            action=command,
            context=context,
            remediation_hint=self._get_remediation_hint(pattern_info[CATEGORY_KEY]),
            metadata={
                "pattern_name": pattern_name,
                "category": pattern_info[CATEGORY_KEY],
                "matched_text": match.group(0),
                "match_position": match.start(),
            },
        )

    def _get_remediation_hint(self, category: str) -> str:
        """Get remediation hint based on violation category."""
        return _get_remediation_hint(category)

    def get_pattern_categories(self) -> set[str]:
        """Get all pattern categories currently enabled.

        Returns:
            Set of category names
        """
        return {info[CATEGORY_KEY] for info in self.compiled_patterns.values()}

    def get_patterns_by_category(self, category: str) -> list[str]:
        """Get all pattern names for a specific category.

        Args:
            category: Category name (file_write, dangerous, injection, security, custom)

        Returns:
            List of pattern names in that category
        """
        return [
            name
            for name, info in self.compiled_patterns.items()
            if info[CATEGORY_KEY] == category
        ]

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"ForbiddenOperationsPolicy("
            f"patterns={len(self.compiled_patterns)}, "
            f"file_writes={self.check_file_writes}, "
            f"dangerous={self.check_dangerous_commands}, "
            f"injection={self.check_injection_patterns})"
        )
