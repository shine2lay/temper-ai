"""Helper functions for ForbiddenOperationsPolicy.

Extracted from ForbiddenOperationsPolicy to keep the class below 500 lines.
These are internal implementation details and should not be used directly.
"""
import re
from typing import Any, Dict, Optional, Set, cast

from src.safety._forbidden_ops_pattern_config import PatternConfig
from src.safety.constants import (
    ARGS_KEY,
    BASH_KEY,
    CATEGORY_KEY,
    COMMAND_KEY,
    REGEX_KEY,
    VIOLATION_MESSAGE,
    VIOLATION_PATTERN,
    VIOLATION_SEVERITY,
)
from src.safety.interfaces import ViolationSeverity

# Pattern categories (used in compile_all_patterns and get_remediation_hint)
CATEGORY_FILE_WRITE = "file_write"
CATEGORY_DANGEROUS = "dangerous"
CATEGORY_INJECTION = "injection"
CATEGORY_SECURITY = "security"
CATEGORY_CUSTOM = "custom"


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


def extract_command(action: Dict[str, Any]) -> Optional[str]:
    """Extract command string from action.

    Supports various action formats:
    - {"command": "..."}
    - {"bash": "..."}
    - {"tool": "bash", "args": {"command": "..."}}
    - {"content": "..."}  (for code content)
    """
    if COMMAND_KEY in action:
        cmd = action[COMMAND_KEY]
        return str(cmd) if cmd is not None else None

    if BASH_KEY in action:
        bash = action[BASH_KEY]
        return str(bash) if bash is not None else None

    if action.get("tool") == BASH_KEY and ARGS_KEY in action:
        if isinstance(action[ARGS_KEY], dict):
            return cast(Optional[str], action[ARGS_KEY].get(COMMAND_KEY))
        elif isinstance(action[ARGS_KEY], str):
            return cast(Optional[str], action[ARGS_KEY])

    if "content" in action:
        content = action["content"]
        return str(content) if content is not None else None

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
