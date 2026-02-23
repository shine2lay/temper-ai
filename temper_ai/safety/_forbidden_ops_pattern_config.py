"""Pattern configuration dataclass for ForbiddenOperationsPolicy.

Extracted to reduce parameter count in compile_all_patterns function.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class PatternConfig:
    """Configuration for pattern compilation.

    Bundles all pattern dictionaries and their enable flags into a single config object.
    """

    check_file_writes: bool
    check_dangerous_commands: bool
    check_injection_patterns: bool
    check_security_sensitive: bool
    file_write_patterns: dict[str, dict[str, Any]]
    dangerous_command_patterns: dict[str, dict[str, Any]]
    injection_patterns: dict[str, dict[str, Any]]
    security_sensitive_patterns: dict[str, dict[str, Any]]
    custom_forbidden_patterns: dict[str, str]
