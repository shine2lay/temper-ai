"""Helper functions for ForbiddenOperationsPolicy.

Extracted from ForbiddenOperationsPolicy to keep the class below 500 lines.
These are internal implementation details and should not be used directly.
"""
import re
from typing import Any, Dict, Optional, Set

from src.safety.interfaces import ViolationSeverity

# Pattern categories (used in compile_all_patterns and get_remediation_hint)
CATEGORY_FILE_WRITE = "file_write"
CATEGORY_DANGEROUS = "dangerous"
CATEGORY_INJECTION = "injection"
CATEGORY_SECURITY = "security"
CATEGORY_CUSTOM = "custom"


def compile_all_patterns(
    check_file_writes: bool,
    check_dangerous_commands: bool,
    check_injection_patterns: bool,
    check_security_sensitive: bool,
    file_write_patterns: Dict[str, Dict[str, Any]],
    dangerous_command_patterns: Dict[str, Dict[str, Any]],
    injection_patterns: Dict[str, Dict[str, Any]],
    security_sensitive_patterns: Dict[str, Dict[str, Any]],
    custom_forbidden_patterns: Dict[str, str],
) -> Dict[str, Dict[str, Any]]:
    """Compile all regex patterns based on configuration."""
    patterns: Dict[str, Dict[str, Any]] = {}

    if check_file_writes:
        patterns.update({
            f"file_write_{name}": {
                "regex": re.compile(info["pattern"], re.IGNORECASE),
                "message": info["message"],
                "severity": info["severity"],
                "category": CATEGORY_FILE_WRITE,
                "requires_context_check": info.get("requires_context_check", False)
            }
            for name, info in file_write_patterns.items()
        })

    if check_dangerous_commands:
        patterns.update({
            f"dangerous_{name}": {
                "regex": re.compile(info["pattern"], re.IGNORECASE),
                "message": info["message"],
                "severity": info["severity"],
                "category": CATEGORY_DANGEROUS
            }
            for name, info in dangerous_command_patterns.items()
        })

    if check_injection_patterns:
        patterns.update({
            f"injection_{name}": {
                "regex": re.compile(info["pattern"], re.IGNORECASE),
                "message": info["message"],
                "severity": info["severity"],
                "category": CATEGORY_INJECTION
            }
            for name, info in injection_patterns.items()
        })

    if check_security_sensitive:
        patterns.update({
            f"security_{name}": {
                "regex": re.compile(info["pattern"], re.IGNORECASE),
                "message": info["message"],
                "severity": info["severity"],
                "category": CATEGORY_SECURITY
            }
            for name, info in security_sensitive_patterns.items()
        })

    # Add custom patterns
    for name, pattern_str in custom_forbidden_patterns.items():
        patterns[f"custom_{name}"] = {
            "regex": re.compile(pattern_str, re.IGNORECASE),
            "message": f"Custom forbidden pattern: {name}",
            "severity": ViolationSeverity.HIGH,
            "category": CATEGORY_CUSTOM
        }

    return patterns


def extract_command(action: Dict[str, Any]) -> Optional[str]:
    """Extract command string from action.

    Supports various action formats:
    - {"command": "..."}
    - {"bash": "..."}
    - {"tool": "bash", "args": {"command": "..."}}
    - {"content": "..."}  (for code content)
    """
    if "command" in action:
        cmd = action["command"]
        return str(cmd) if cmd is not None else None

    if "bash" in action:
        bash = action["bash"]
        return str(bash) if bash is not None else None

    if action.get("tool") == "bash" and "args" in action:
        if isinstance(action["args"], dict):
            return action["args"].get("command")
        elif isinstance(action["args"], str):
            return action["args"]

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
