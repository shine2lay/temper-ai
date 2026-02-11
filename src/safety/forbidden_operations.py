"""Forbidden Operations Safety Policy.

Detects and blocks forbidden bash operations, dangerous commands,
command injection, and security-sensitive operations.
See _forbidden_ops_helpers.py for extracted logic.
"""
import re
from typing import Any, Dict, List, Optional, Set

from src.constants.limits import PERCENT_100
from src.constants.probabilities import PROB_VERY_LOW

# Helper functions extracted to reduce class size
from src.safety._forbidden_ops_helpers import (
    compile_all_patterns as _compile_all_patterns,
)
from src.safety._forbidden_ops_helpers import (
    extract_command as _extract_command,
)
from src.safety._forbidden_ops_helpers import (
    get_remediation_hint as _get_remediation_hint,
)
from src.safety._forbidden_ops_helpers import (
    is_whitelisted as _is_whitelisted,
)
from src.safety._forbidden_ops_helpers import (
    validate_redirect_context as _validate_redirect_context,
)
from src.safety.base import BaseSafetyPolicy
from src.safety.constants import (
    MAX_EXCLUDED_PATH_LENGTH,
    MAX_EXCLUDED_PATHS,
)
from src.safety.interfaces import SafetyViolation, ValidationResult, ViolationSeverity
from src.safety.validation import ValidationMixin

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

    # Forbidden file write operations (NEVER allowed)
    FILE_WRITE_PATTERNS = {
        "cat_redirect": {
            "pattern": r"\bcat\s+>",
            "message": "Use Write() tool instead of 'cat >' for file operations",
            "severity": ViolationSeverity.CRITICAL
        },
        "cat_append": {
            "pattern": r"\bcat\s+>>",
            "message": "Use Edit() tool instead of 'cat >>' for file operations",
            "severity": ViolationSeverity.CRITICAL
        },
        "cat_heredoc": {
            "pattern": r"\bcat\s+<<\s*['\"]?EOF",
            "message": "Use Write() tool instead of 'cat <<EOF' for file operations",
            "severity": ViolationSeverity.CRITICAL
        },
        "echo_redirect": {
            # SECURITY FIX: Simplified pattern to prevent ReDoS - requires filename with extension
            # Use bounded repetition {0,200} instead of .* to prevent scanning huge strings
            "pattern": r"\becho\s+.{0,200}>\s*\S+\.(txt|json|yaml|yml|py|js|ts|md|csv|log)\b",
            "message": "Use Write() tool instead of 'echo >' for file operations",
            "severity": ViolationSeverity.CRITICAL
        },
        "echo_append": {
            # SECURITY FIX: Simplified pattern to prevent ReDoS - requires filename with extension
            # Use bounded repetition {0,200} instead of .* to prevent scanning huge strings
            "pattern": r"\becho\s+.{0,200}>>\s*\S+\.(txt|json|yaml|yml|py|js|ts|md|csv|log)\b",
            "message": "Use Edit() tool instead of 'echo >>' for file operations",
            "severity": ViolationSeverity.CRITICAL
        },
        "printf_redirect": {
            # SECURITY FIX: Simplified pattern to prevent ReDoS - requires filename with extension
            # Use bounded repetition {0,200} instead of .* to prevent scanning huge strings
            "pattern": r"\bprintf\s+.{0,200}>>?\s*\S+\.(txt|json|yaml|yml|py|js|ts|md|csv|log)\b",
            "message": "Use Write() tool instead of 'printf >' for file operations",
            "severity": ViolationSeverity.CRITICAL
        },
        "tee_write": {
            "pattern": r"\btee\s+(?!-a\s+/dev/null)",
            "message": "Use Write() tool instead of 'tee' for file operations",
            "severity": ViolationSeverity.CRITICAL
        },
        "sed_inplace": {
            "pattern": r"\bsed\s+-i",
            "message": "Use Edit() tool instead of 'sed -i' for file modifications",
            "severity": ViolationSeverity.CRITICAL
        },
        "awk_redirect": {
            "pattern": r"\bawk\s+[^|]+>\s*\S+",
            "message": "Use Write() tool instead of 'awk >' for file operations",
            "severity": ViolationSeverity.CRITICAL
        },
        "redirect_output": {
            # SECURITY FIX: Simplified pattern to prevent ReDoS vulnerability
            # Original pattern had nested quantifiers [^|]* and [^&>\s|]+ causing
            # catastrophic backtracking on inputs like "echo " + "a"*10000 + " >"
            #
            # New approach: Simple pattern + context validation in Python code
            # Pattern just detects "> filename.ext", context check handles exclusions
            "pattern": r">\s*\S+\.(txt|json|yaml|yml|py|js|ts|md|csv|log)\b",
            "message": "Use Write() tool instead of shell redirection for file operations",
            "severity": ViolationSeverity.HIGH,
            "requires_context_check": True  # Validate context separately
        }
    }

    # Dangerous/destructive commands
    DANGEROUS_COMMAND_PATTERNS = {
        "rm_recursive": {
            "pattern": r"\brm\s+(-[rf]+|--recursive|--force)\s+",
            "message": "Recursive/force file deletion requires explicit user approval",
            "severity": ViolationSeverity.CRITICAL
        },
        "rm_root_dirs": {
            # SECURITY FIX: Bounded quantifier to prevent ReDoS
            "pattern": r"\brm\s+[^-]{0,200}(/|/\*|/home|/usr|/etc|/var|/bin|/sbin|/lib)",
            "message": "Attempting to delete system directories",
            "severity": ViolationSeverity.CRITICAL
        },
        "dd_command": {
            "pattern": r"\bdd\s+",
            "message": "Direct disk operations (dd) are forbidden for safety",
            "severity": ViolationSeverity.CRITICAL
        },
        "mkfs_command": {
            "pattern": r"\bmkfs\.",
            "message": "Filesystem creation commands are forbidden",
            "severity": ViolationSeverity.CRITICAL
        },
        "chmod_recursive": {
            "pattern": r"\bchmod\s+-R\s+[0-9]+\s+/",
            "message": "Recursive permission changes on root require approval",
            "severity": ViolationSeverity.HIGH
        },
        "chown_root": {
            "pattern": r"\bchown\s+(-R\s+)?root:",
            "message": "Changing ownership to root requires approval",
            "severity": ViolationSeverity.HIGH
        },
        "curl_pipe_sh": {
            "pattern": r"\bcurl\s+[^|]+\|\s*(bash|sh|zsh)",
            "message": "Piping curl directly to shell is dangerous",
            "severity": ViolationSeverity.CRITICAL
        },
        "wget_execute": {
            "pattern": r"\bwget\s+[^|]+\|\s*(bash|sh|zsh)",
            "message": "Piping wget directly to shell is dangerous",
            "severity": ViolationSeverity.CRITICAL
        },
        "eval_command": {
            "pattern": r"\beval\s+",
            "message": "eval can execute arbitrary code - use with extreme caution",
            "severity": ViolationSeverity.HIGH
        },
        "fork_bomb": {
            "pattern": r":\(\)\s*\{",
            "message": "Potential fork bomb detected",
            "severity": ViolationSeverity.CRITICAL
        },
        "dev_null_overwrite": {
            "pattern": r">\s*/dev/sd[a-z]",
            "message": "Attempting to write directly to disk device",
            "severity": ViolationSeverity.CRITICAL
        }
    }

    # Command injection patterns
    INJECTION_PATTERNS = {
        "semicolon_injection": {
            # SECURITY FIX: Bounded quantifier to prevent ReDoS
            "pattern": r";.{0,500}(\brm\b|\bmv\b|\bchmod\b|\bwget\b|\bcurl\b)",
            "message": "Potential command injection via semicolon",
            "severity": ViolationSeverity.HIGH
        },
        "pipe_injection": {
            "pattern": r"\|\s*\w+\s*>\s*",
            "message": "Potential command injection via pipe and redirect",
            "severity": ViolationSeverity.HIGH
        },
        "backtick_execution": {
            "pattern": r"`[^`]*(\brm\b|\bmv\b|\bcurl\b)`",
            "message": "Potential command injection via backticks",
            "severity": ViolationSeverity.HIGH
        },
        "subshell_injection": {
            "pattern": r"\$\([^)]*(\brm\b|\bmv\b|\bcurl\b)[^)]*\)",
            "message": "Potential command injection via subshell",
            "severity": ViolationSeverity.HIGH
        }
    }

    # Security-sensitive operations
    SECURITY_SENSITIVE_PATTERNS = {
        "password_in_command": {
            "pattern": r"(-p=|password=|passwd=|pwd=)['\"]?[a-zA-Z0-9]{3,}",
            "message": "Password in command - use environment variables or config files",
            "severity": ViolationSeverity.HIGH
        },
        "ssh_no_check": {
            # SECURITY FIX: Bounded quantifier to prevent ReDoS
            "pattern": r"ssh\s+.{0,200}-o\s+StrictHostKeyChecking=no",
            "message": "Disabling SSH host key checking is insecure",
            "severity": ViolationSeverity.HIGH
        },
        "sudo_no_password": {
            # SECURITY FIX: Bounded quantifier to prevent ReDoS
            "pattern": r"sudo\s+.{0,200}NOPASSWD",
            "message": "Passwordless sudo configuration detected",
            "severity": ViolationSeverity.MEDIUM
        }
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
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

        # Validate boolean configuration flags
        self.check_file_writes = self._validate_boolean(
            self.config.get("check_file_writes", True),
            "check_file_writes",
            default=True
        )

        self.check_dangerous_commands = self._validate_boolean(
            self.config.get("check_dangerous_commands", True),
            "check_dangerous_commands",
            default=True
        )

        self.check_injection_patterns = self._validate_boolean(
            self.config.get("check_injection_patterns", True),
            "check_injection_patterns",
            default=True
        )

        self.check_security_sensitive = self._validate_boolean(
            self.config.get("check_security_sensitive", True),
            "check_security_sensitive",
            default=True
        )

        self.allow_read_only = self._validate_boolean(
            self.config.get("allow_read_only", True),
            "allow_read_only",
            default=True
        )

        # Validate custom forbidden patterns (dict of name -> pattern)
        # Already extracted before super().__init__() to avoid base class nested dict rejection
        if not isinstance(custom_patterns_raw, dict):
            raise ValueError(
                f"custom_forbidden_patterns must be a dict, got {type(custom_patterns_raw).__name__}"
            )

        self.custom_forbidden_patterns: Dict[str, str] = {}
        for name, pattern in custom_patterns_raw.items():
            if not isinstance(name, str):
                raise ValueError(
                    f"custom_forbidden_patterns keys must be strings, got {type(name).__name__}"
                )
            if not isinstance(pattern, str):
                raise ValueError(
                    f"custom_forbidden_patterns['{name}'] must be a string, got {type(pattern).__name__}"
                )
            if len(pattern) > MAX_EXCLUDED_PATH_LENGTH:
                raise ValueError(
                    f"custom_forbidden_patterns['{name}'] must be <= {MAX_EXCLUDED_PATH_LENGTH} characters, got {len(pattern)}"
                )

            # SECURITY: Validate regex pattern doesn't have ReDoS vulnerability
            # The _validate_regex_pattern method tests with adversarial inputs
            try:
                self._validate_regex_pattern(
                    pattern,
                    f"custom_forbidden_patterns['{name}']",
                    max_length=MAX_EXCLUDED_PATH_LENGTH,
                    test_timeout=PROB_VERY_LOW
                )
                self.custom_forbidden_patterns[name] = pattern
            except ValueError as e:
                raise ValueError(f"Invalid regex in custom_forbidden_patterns['{name}']: {e}")

        if len(self.custom_forbidden_patterns) > MAX_CUSTOM_PATTERNS:
            raise ValueError(
                f"custom_forbidden_patterns must have <= {MAX_CUSTOM_PATTERNS} patterns, got {len(self.custom_forbidden_patterns)}"
            )

        # Validate whitelist commands (list of strings)
        whitelist_raw = self.config.get("whitelist_commands", [])
        if not isinstance(whitelist_raw, list):
            raise ValueError(
                f"whitelist_commands must be a list of strings, got {type(whitelist_raw).__name__}"
            )

        whitelist_validated: List[str] = []
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

        self.whitelist_commands = set(whitelist_validated)

        # Compile all patterns
        self.compiled_patterns = self._compile_all_patterns()

    def _compile_all_patterns(self) -> Dict[str, Dict[str, Any]]:
        """Compile all regex patterns based on configuration."""
        return _compile_all_patterns(
            self.check_file_writes, self.check_dangerous_commands,
            self.check_injection_patterns, self.check_security_sensitive,
            self.FILE_WRITE_PATTERNS, self.DANGEROUS_COMMAND_PATTERNS,
            self.INJECTION_PATTERNS, self.SECURITY_SENSITIVE_PATTERNS,
            self.custom_forbidden_patterns,
        )

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

    def _extract_command(self, action: Dict[str, Any]) -> Optional[str]:
        """Extract command string from action."""
        return _extract_command(action)

    def _is_whitelisted(self, command: str) -> bool:
        """Check if command matches whitelist."""
        return _is_whitelisted(command, self.whitelist_commands)

    def _validate_redirect_context(self, command: str, match: re.Match) -> bool:
        """Validate that a redirect match is not in an excluded context."""
        return _validate_redirect_context(command, match)

    def validate(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
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

        # No command to check
        if not command:
            return ValidationResult(
                valid=True,
                violations=[],
                policy_name=self.name
            )

        # Check whitelist
        if self._is_whitelisted(command):
            return ValidationResult(
                valid=True,
                violations=[],
                policy_name=self.name,
                metadata={"whitelisted": True}
            )

        # Check all patterns
        violations = []
        for pattern_name, pattern_info in self.compiled_patterns.items():
            match = pattern_info["regex"].search(command)
            if match:
                # Check if pattern requires additional context validation
                if pattern_info.get("requires_context_check"):
                    # For redirect_output, validate the context
                    if pattern_name == "file_write_redirect_output":
                        if not self._validate_redirect_context(command, match):
                            # Excluded context (comment, test, if, while, pipe)
                            continue

                violation = SafetyViolation(
                    policy_name=self.name,
                    severity=pattern_info["severity"],
                    message=pattern_info["message"],
                    action=command,
                    context=context,
                    remediation_hint=self._get_remediation_hint(pattern_info["category"]),
                    metadata={
                        "pattern_name": pattern_name,
                        "category": pattern_info["category"],
                        "matched_text": match.group(0),
                        "match_position": match.start()
                    }
                )
                violations.append(violation)

        # Return result
        return ValidationResult(
            valid=len(violations) == 0,
            violations=violations,
            policy_name=self.name,
            metadata={
                "patterns_checked": len(self.compiled_patterns),
                "violations_found": len(violations)
            }
        )

    def _get_remediation_hint(self, category: str) -> str:
        """Get remediation hint based on violation category."""
        return _get_remediation_hint(category)

    def get_pattern_categories(self) -> Set[str]:
        """Get all pattern categories currently enabled.

        Returns:
            Set of category names
        """
        return {info["category"] for info in self.compiled_patterns.values()}

    def get_patterns_by_category(self, category: str) -> List[str]:
        """Get all pattern names for a specific category.

        Args:
            category: Category name (file_write, dangerous, injection, security, custom)

        Returns:
            List of pattern names in that category
        """
        return [
            name for name, info in self.compiled_patterns.items()
            if info["category"] == category
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
