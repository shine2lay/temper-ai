"""Forbidden Operations Safety Policy.

Detects and blocks forbidden operations including:
- Bash file write commands (cat >, echo >, tee, etc.)
- Dangerous bash commands (rm -rf, dd, mkfs, etc.)
- Command injection patterns
- Destructive operations
- Security-sensitive operations

This policy enforces the rule that file operations MUST use dedicated tools
(Write, Edit, Read) instead of bash commands, as bash commands:
- Bypass file locks in multi-agent environments
- Provide no validation or safety checks
- Have silent failures and obscure errors
- Can cause data races and corruption

Reference: CLAUDE.md file operation rules
"""
import re
from typing import Dict, Any, List, Optional, Set
from src.safety.base import BaseSafetyPolicy
from src.safety.interfaces import ValidationResult, SafetyViolation, ViolationSeverity


class ForbiddenOperationsPolicy(BaseSafetyPolicy):
    """Detects forbidden bash operations and dangerous patterns.

    Configuration options:
        check_file_writes: Detect bash file write operations (default: True)
        check_dangerous_commands: Detect dangerous/destructive commands (default: True)
        check_injection_patterns: Detect command injection (default: True)
        allow_read_only: Allow read-only bash commands like cat, head (default: True)
        custom_forbidden_patterns: Additional regex patterns to block
        whitelist_commands: Specific commands to allow despite matching patterns

    Example:
        >>> config = {
        ...     "check_file_writes": True,
        ...     "check_dangerous_commands": True
        ... }
        >>> policy = ForbiddenOperationsPolicy(config)
        >>> result = policy.validate(
        ...     action={"command": "cat > file.txt", "tool": "bash"},
        ...     context={"agent": "coder"}
        ... )
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
            "pattern": r"\becho\s+[^|]*\s*>(?!>)",
            "message": "Use Write() tool instead of 'echo >' for file operations",
            "severity": ViolationSeverity.CRITICAL
        },
        "echo_append": {
            "pattern": r"\becho\s+[^|]*\s*>>",
            "message": "Use Edit() tool instead of 'echo >>' for file operations",
            "severity": ViolationSeverity.CRITICAL
        },
        "printf_redirect": {
            "pattern": r"\bprintf\s+[^|]*\s*>>?",
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
            "pattern": r"(?<!#)(?<!test\s)(?<!if\s)(?<!while\s)[^|]*\s*>\s*[^&>\s|]+\.(txt|json|yaml|yml|py|js|ts|md|csv|log)",
            "message": "Use Write() tool instead of shell redirection for file operations",
            "severity": ViolationSeverity.HIGH
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
            "pattern": r"\brm\s+[^-]*(/|/\*|/home|/usr|/etc|/var|/bin|/sbin|/lib)",
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
            "message": "eval() can execute arbitrary code - use with extreme caution",
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
            "pattern": r";.*(\brm\b|\bmv\b|\bchmod\b|\bwget\b|\bcurl\b)",
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
            "pattern": r"ssh\s+.*-o\s+StrictHostKeyChecking=no",
            "message": "Disabling SSH host key checking is insecure",
            "severity": ViolationSeverity.HIGH
        },
        "sudo_no_password": {
            "pattern": r"sudo\s+.*NOPASSWD",
            "message": "Passwordless sudo configuration detected",
            "severity": ViolationSeverity.MEDIUM
        }
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize forbidden operations policy.

        Args:
            config: Policy configuration (optional)
        """
        super().__init__(config or {})

        # Configuration
        self.check_file_writes = self.config.get("check_file_writes", True)
        self.check_dangerous_commands = self.config.get("check_dangerous_commands", True)
        self.check_injection_patterns = self.config.get("check_injection_patterns", True)
        self.check_security_sensitive = self.config.get("check_security_sensitive", True)
        self.allow_read_only = self.config.get("allow_read_only", True)
        self.custom_forbidden_patterns = self.config.get("custom_forbidden_patterns", {})
        self.whitelist_commands = set(self.config.get("whitelist_commands", []))

        # Compile all patterns
        self.compiled_patterns = self._compile_all_patterns()

    def _compile_all_patterns(self) -> Dict[str, Dict[str, Any]]:
        """Compile all regex patterns based on configuration."""
        patterns = {}

        if self.check_file_writes:
            patterns.update({
                f"file_write_{name}": {
                    "regex": re.compile(info["pattern"], re.IGNORECASE),
                    "message": info["message"],
                    "severity": info["severity"],
                    "category": "file_write"
                }
                for name, info in self.FILE_WRITE_PATTERNS.items()
            })

        if self.check_dangerous_commands:
            patterns.update({
                f"dangerous_{name}": {
                    "regex": re.compile(info["pattern"], re.IGNORECASE),
                    "message": info["message"],
                    "severity": info["severity"],
                    "category": "dangerous"
                }
                for name, info in self.DANGEROUS_COMMAND_PATTERNS.items()
            })

        if self.check_injection_patterns:
            patterns.update({
                f"injection_{name}": {
                    "regex": re.compile(info["pattern"], re.IGNORECASE),
                    "message": info["message"],
                    "severity": info["severity"],
                    "category": "injection"
                }
                for name, info in self.INJECTION_PATTERNS.items()
            })

        if self.check_security_sensitive:
            patterns.update({
                f"security_{name}": {
                    "regex": re.compile(info["pattern"], re.IGNORECASE),
                    "message": info["message"],
                    "severity": info["severity"],
                    "category": "security"
                }
                for name, info in self.SECURITY_SENSITIVE_PATTERNS.items()
            })

        # Add custom patterns
        for name, info in self.custom_forbidden_patterns.items():
            patterns[f"custom_{name}"] = {
                "regex": re.compile(info["pattern"], re.IGNORECASE),
                "message": info.get("message", f"Custom forbidden pattern: {name}"),
                "severity": info.get("severity", ViolationSeverity.HIGH),
                "category": "custom"
            }

        return patterns

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
        return 200  # P0 priority

    def _extract_command(self, action: Dict[str, Any]) -> Optional[str]:
        """Extract command string from action.

        Supports various action formats:
        - {"command": "..."}
        - {"bash": "..."}
        - {"tool": "bash", "args": {"command": "..."}}
        - {"content": "..."}  (for code content)
        """
        # Direct command field
        if "command" in action:
            cmd = action["command"]
            return str(cmd) if cmd is not None else None

        # Bash field
        if "bash" in action:
            bash = action["bash"]
            return str(bash) if bash is not None else None

        # Tool with args
        if action.get("tool") == "bash" and "args" in action:
            if isinstance(action["args"], dict):
                return action["args"].get("command")
            elif isinstance(action["args"], str):
                return action["args"]

        # Content field (for code snippets)
        if "content" in action:
            content = action["content"]
            return str(content) if content is not None else None

        return None

    def _is_whitelisted(self, command: str) -> bool:
        """Check if command matches whitelist."""
        command_lower = command.lower().strip()
        return any(wl in command_lower for wl in self.whitelist_commands)

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
        hints = {
            "file_write": (
                "Use dedicated file operation tools: "
                "Write() for creating files, Edit() for modifying files, Read() for reading files. "
                "These tools provide proper validation, locking, and error handling."
            ),
            "dangerous": (
                "Destructive operations require explicit user approval. "
                "Consider safer alternatives or request user confirmation before proceeding."
            ),
            "injection": (
                "Avoid constructing commands from untrusted input. "
                "Use parameterized tools or validate/sanitize all inputs before use."
            ),
            "security": (
                "Use secure configuration and credential management. "
                "Store sensitive data in environment variables or secure vaults, not in commands."
            ),
            "custom": (
                "This operation matches a custom forbidden pattern. "
                "Review the operation and ensure it's safe and necessary."
            )
        }
        return hints.get(category, "Review operation for safety and use approved alternatives.")

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
