"""Helper functions for ForbiddenOperationsPolicy.

Extracted from ForbiddenOperationsPolicy to keep the class below 500 lines.
These are internal implementation details and should not be used directly.
"""
import re
from typing import Any, Dict, Optional, Set, cast

from temper_ai.safety._forbidden_ops_pattern_config import PatternConfig
from temper_ai.safety.constants import (
    ARGS_KEY,
    BASH_KEY,
    CATEGORY_KEY,
    COMMAND_KEY,
    REGEX_KEY,
    VIOLATION_MESSAGE,
    VIOLATION_PATTERN,
    VIOLATION_SEVERITY,
)
from temper_ai.safety.interfaces import ViolationSeverity

# Pattern categories (used in compile_all_patterns and get_remediation_hint)
CATEGORY_FILE_WRITE = "file_write"
CATEGORY_DANGEROUS = "dangerous"
CATEGORY_INJECTION = "injection"
CATEGORY_SECURITY = "security"
CATEGORY_CUSTOM = "custom"


# -- Pattern dictionaries (extracted from ForbiddenOperationsPolicy class) --

FILE_WRITE_PATTERNS = {
    "cat_redirect": {
        VIOLATION_PATTERN: r"\bcat\s+>",
        VIOLATION_MESSAGE: "Use Write() tool instead of 'cat >' for file operations",
        VIOLATION_SEVERITY: ViolationSeverity.CRITICAL
    },
    "cat_append": {
        VIOLATION_PATTERN: r"\bcat\s+>>",
        VIOLATION_MESSAGE: "Use Edit() tool instead of 'cat >>' for file operations",
        VIOLATION_SEVERITY: ViolationSeverity.CRITICAL
    },
    "cat_heredoc": {
        VIOLATION_PATTERN: r"\bcat\s+<<\s*['\"]?EOF",
        VIOLATION_MESSAGE: "Use Write() tool instead of 'cat <<EOF' for file operations",
        VIOLATION_SEVERITY: ViolationSeverity.CRITICAL
    },
    "echo_redirect": {
        VIOLATION_PATTERN: r"\becho\s+.{0,200}>\s*\S+\.(txt|json|yaml|yml|py|js|ts|md|csv|log)\b",
        VIOLATION_MESSAGE: "Use Write() tool instead of 'echo >' for file operations",
        VIOLATION_SEVERITY: ViolationSeverity.CRITICAL
    },
    "echo_append": {
        VIOLATION_PATTERN: r"\becho\s+.{0,200}>>\s*\S+\.(txt|json|yaml|yml|py|js|ts|md|csv|log)\b",
        VIOLATION_MESSAGE: "Use Edit() tool instead of 'echo >>' for file operations",
        VIOLATION_SEVERITY: ViolationSeverity.CRITICAL
    },
    "printf_redirect": {
        VIOLATION_PATTERN: r"\bprintf\s+.{0,200}>>?\s*\S+\.(txt|json|yaml|yml|py|js|ts|md|csv|log)\b",
        VIOLATION_MESSAGE: "Use Write() tool instead of 'printf >' for file operations",
        VIOLATION_SEVERITY: ViolationSeverity.CRITICAL
    },
    "tee_write": {
        VIOLATION_PATTERN: r"\btee\s+(?!-a\s+/dev/null)",
        VIOLATION_MESSAGE: "Use Write() tool instead of 'tee' for file operations",
        VIOLATION_SEVERITY: ViolationSeverity.CRITICAL
    },
    "sed_inplace": {
        VIOLATION_PATTERN: r"\bsed\s+-i",
        VIOLATION_MESSAGE: "Use Edit() tool instead of 'sed -i' for file modifications",
        VIOLATION_SEVERITY: ViolationSeverity.CRITICAL
    },
    "awk_redirect": {
        VIOLATION_PATTERN: r"\bawk\s+[^|]+>\s*\S+",
        VIOLATION_MESSAGE: "Use Write() tool instead of 'awk >' for file operations",
        VIOLATION_SEVERITY: ViolationSeverity.CRITICAL
    },
    "redirect_output": {
        VIOLATION_PATTERN: r">\s*\S+\.(txt|json|yaml|yml|py|js|ts|md|csv|log)\b",
        VIOLATION_MESSAGE: "Use Write() tool instead of shell redirection for file operations",
        VIOLATION_SEVERITY: ViolationSeverity.HIGH,
        "requires_context_check": True
    }
}

DANGEROUS_COMMAND_PATTERNS = {
    "rm_recursive": {
        VIOLATION_PATTERN: r"\brm\s+(-[rf]+|--recursive|--force)\s+",
        VIOLATION_MESSAGE: "Recursive/force file deletion requires explicit user approval",
        VIOLATION_SEVERITY: ViolationSeverity.CRITICAL
    },
    "rm_root_dirs": {
        VIOLATION_PATTERN: r"\brm\s+[^-]{0,200}(/|/\*|/home|/usr|/etc|/var|/bin|/sbin|/lib)",
        VIOLATION_MESSAGE: "Attempting to delete system directories",
        VIOLATION_SEVERITY: ViolationSeverity.CRITICAL
    },
    "dd_command": {
        VIOLATION_PATTERN: r"\bdd\s+",
        VIOLATION_MESSAGE: "Direct disk operations (dd) are forbidden for safety",
        VIOLATION_SEVERITY: ViolationSeverity.CRITICAL
    },
    "mkfs_command": {
        VIOLATION_PATTERN: r"\bmkfs\.",
        VIOLATION_MESSAGE: "Filesystem creation commands are forbidden",
        VIOLATION_SEVERITY: ViolationSeverity.CRITICAL
    },
    "chmod_recursive": {
        VIOLATION_PATTERN: r"\bchmod\s+-R\s+[0-9]+\s+/",
        VIOLATION_MESSAGE: "Recursive permission changes on root require approval",
        VIOLATION_SEVERITY: ViolationSeverity.HIGH
    },
    "chown_root": {
        VIOLATION_PATTERN: r"\bchown\s+(-R\s+)?root:",
        VIOLATION_MESSAGE: "Changing ownership to root requires approval",
        VIOLATION_SEVERITY: ViolationSeverity.HIGH
    },
    "curl_pipe_sh": {
        VIOLATION_PATTERN: r"\bcurl\s+[^|]+\|\s*(bash|sh|zsh)",
        VIOLATION_MESSAGE: "Piping curl directly to shell is dangerous",
        VIOLATION_SEVERITY: ViolationSeverity.CRITICAL
    },
    "wget_execute": {
        VIOLATION_PATTERN: r"\bwget\s+[^|]+\|\s*(bash|sh|zsh)",
        VIOLATION_MESSAGE: "Piping wget directly to shell is dangerous",
        VIOLATION_SEVERITY: ViolationSeverity.CRITICAL
    },
    "eval_command": {
        VIOLATION_PATTERN: r"\beval\s+",
        VIOLATION_MESSAGE: "eval can execute arbitrary code - use with extreme caution",
        VIOLATION_SEVERITY: ViolationSeverity.HIGH
    },
    "fork_bomb": {
        VIOLATION_PATTERN: r":\(\)\s*\{",
        VIOLATION_MESSAGE: "Potential fork bomb detected",
        VIOLATION_SEVERITY: ViolationSeverity.CRITICAL
    },
    "dev_null_overwrite": {
        VIOLATION_PATTERN: r">\s*/dev/sd[a-z]",
        VIOLATION_MESSAGE: "Attempting to write directly to disk device",
        VIOLATION_SEVERITY: ViolationSeverity.CRITICAL
    }
}

INJECTION_PATTERNS = {
    "semicolon_injection": {
        VIOLATION_PATTERN: r";.{0,500}(\brm\b|\bmv\b|\bchmod\b|\bwget\b|\bcurl\b)",
        VIOLATION_MESSAGE: "Potential command injection via semicolon",
        VIOLATION_SEVERITY: ViolationSeverity.HIGH
    },
    "pipe_injection": {
        VIOLATION_PATTERN: r"\|\s*\w+\s*>\s*",
        VIOLATION_MESSAGE: "Potential command injection via pipe and redirect",
        VIOLATION_SEVERITY: ViolationSeverity.HIGH
    },
    "backtick_execution": {
        VIOLATION_PATTERN: r"`[^`]*(\brm\b|\bmv\b|\bcurl\b)`",
        VIOLATION_MESSAGE: "Potential command injection via backticks",
        VIOLATION_SEVERITY: ViolationSeverity.HIGH
    },
    "subshell_injection": {
        VIOLATION_PATTERN: r"\$\([^)]*(\brm\b|\bmv\b|\bcurl\b)[^)]*\)",
        VIOLATION_MESSAGE: "Potential command injection via subshell",
        VIOLATION_SEVERITY: ViolationSeverity.HIGH
    }
}

SECURITY_SENSITIVE_PATTERNS = {
    "password_in_command": {
        VIOLATION_PATTERN: r"(-p=|password=|passwd=|pwd=)['\"]?[a-zA-Z0-9]{3,}",
        VIOLATION_MESSAGE: "Password in command - use environment variables or config files",
        VIOLATION_SEVERITY: ViolationSeverity.HIGH
    },
    "ssh_no_check": {
        VIOLATION_PATTERN: r"ssh\s+.{0,200}-o\s+StrictHostKeyChecking=no",
        VIOLATION_MESSAGE: "Disabling SSH host key checking is insecure",
        VIOLATION_SEVERITY: ViolationSeverity.HIGH
    },
    "sudo_no_password": {
        VIOLATION_PATTERN: r"sudo\s+.{0,200}NOPASSWD",
        VIOLATION_MESSAGE: "Passwordless sudo configuration detected",
        VIOLATION_SEVERITY: ViolationSeverity.MEDIUM
    }
}


def _compile_pattern_category(
    prefix: str,
    category: str,
    pattern_dict: Dict[str, Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    """Compile a single category of patterns.

    Args:
        prefix: Pattern name prefix (e.g., "file_write_", "dangerous_")
        category: Category name for metadata
        pattern_dict: Dictionary of pattern definitions

    Returns:
        Dictionary of compiled patterns with full metadata
    """
    return {
        f"{prefix}{name}": {
            REGEX_KEY: re.compile(info[VIOLATION_PATTERN], re.IGNORECASE),
            VIOLATION_MESSAGE: info[VIOLATION_MESSAGE],
            VIOLATION_SEVERITY: info[VIOLATION_SEVERITY],
            CATEGORY_KEY: category,
            "requires_context_check": info.get("requires_context_check", False)
        }
        for name, info in pattern_dict.items()
    }


def _compile_custom_patterns(
    custom_patterns: Dict[str, str]
) -> Dict[str, Dict[str, Any]]:
    """Compile custom forbidden patterns.

    Args:
        custom_patterns: Dictionary of custom pattern definitions

    Returns:
        Dictionary of compiled custom patterns
    """
    return {
        f"custom_{name}": {
            "regex": re.compile(pattern_str, re.IGNORECASE),
            VIOLATION_MESSAGE: f"Custom forbidden pattern: {name}",
            VIOLATION_SEVERITY: ViolationSeverity.HIGH,
            "category": CATEGORY_CUSTOM
        }
        for name, pattern_str in custom_patterns.items()
    }


def compile_all_patterns(config: PatternConfig) -> Dict[str, Dict[str, Any]]:
    """Compile all regex patterns based on configuration.

    Args:
        config: Pattern configuration with enable flags and pattern dictionaries

    Returns:
        Dictionary of all compiled patterns with metadata
    """
    patterns: Dict[str, Dict[str, Any]] = {}

    if config.check_file_writes:
        patterns.update(_compile_pattern_category(
            "file_write_", CATEGORY_FILE_WRITE, config.file_write_patterns
        ))

    if config.check_dangerous_commands:
        patterns.update(_compile_pattern_category(
            "dangerous_", CATEGORY_DANGEROUS, config.dangerous_command_patterns
        ))

    if config.check_injection_patterns:
        patterns.update(_compile_pattern_category(
            "injection_", CATEGORY_INJECTION, config.injection_patterns
        ))

    if config.check_security_sensitive:
        patterns.update(_compile_pattern_category(
            "security_", CATEGORY_SECURITY, config.security_sensitive_patterns
        ))

    # Add custom patterns
    patterns.update(_compile_custom_patterns(config.custom_forbidden_patterns))

    return patterns


def _stringify_if_not_none(value: Any) -> Optional[str]:
    """Return str(value) if value is not None, else None."""
    return str(value) if value is not None else None


def _extract_bash_tool_args(args: Any) -> Optional[str]:
    """Extract command from bash tool args field.

    Args:
        args: The ``args`` value from a tool action (dict or str)

    Returns:
        Command string or None
    """
    if isinstance(args, dict):
        return cast(Optional[str], args.get(COMMAND_KEY))
    if isinstance(args, str):
        return cast(Optional[str], args)
    return None


def extract_command(action: Dict[str, Any]) -> Optional[str]:
    """Extract command string from action.

    Supports various action formats:
    - {"command": "..."}
    - {"bash": "..."}
    - {"tool": "bash", "args": {"command": "..."}}
    - {"content": "..."}  (for code content)
    """
    if COMMAND_KEY in action:
        return _stringify_if_not_none(action[COMMAND_KEY])

    if BASH_KEY in action:
        return _stringify_if_not_none(action[BASH_KEY])

    if action.get("tool") == BASH_KEY and ARGS_KEY in action:
        return _extract_bash_tool_args(action[ARGS_KEY])

    if "content" in action:
        return _stringify_if_not_none(action["content"])

    return None


def is_whitelisted(command: str, whitelist_commands: Set[str]) -> bool:
    """Check if command matches whitelist."""
    command_lower = command.lower().strip()
    return any(wl in command_lower for wl in whitelist_commands)


def validate_redirect_context(command: str, match: re.Match) -> bool:
    """Validate that a redirect match is not in an excluded context.

    Args:
        command: Full command string
        match: Regex match object for the redirect pattern

    Returns:
        True if this is a forbidden redirect (violation)
        False if this redirect should be excluded (comment, test, control flow, etc.)
    """
    line_start = command.rfind('\n', 0, match.start()) + 1
    line = command[line_start:match.end()]

    if line.lstrip().startswith('#'):
        return False

    if re.match(r'\s*test\s+', line, re.IGNORECASE):
        return False

    if re.match(r'\s*(if|while)\s+', line, re.IGNORECASE):
        return False

    before_redirect = command[line_start:match.start()]
    if '|' in before_redirect:
        return False

    return True


def get_remediation_hint(category: str) -> str:
    """Get remediation hint based on violation category."""
    hints = {
        CATEGORY_FILE_WRITE: (
            "Use dedicated file operation tools: "
            "Write() for creating files, Edit() for modifying files, Read() for reading files. "
            "These tools provide proper validation, locking, and error handling."
        ),
        CATEGORY_DANGEROUS: (
            "Destructive operations require explicit user approval. "
            "Consider safer alternatives or request user confirmation before proceeding."
        ),
        CATEGORY_INJECTION: (
            "Avoid constructing commands from untrusted input. "
            "Use parameterized tools or validate/sanitize all inputs before use."
        ),
        CATEGORY_SECURITY: (
            "Use secure configuration and credential management. "
            "Store sensitive data in environment variables or secure vaults, not in commands."
        ),
        CATEGORY_CUSTOM: (
            "This operation matches a custom forbidden pattern. "
            "Review the operation and ensure it's safe and necessary."
        )
    }
    return hints.get(category, "Review operation for safety and use approved alternatives.")
