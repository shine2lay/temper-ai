"""Pattern configuration dataclass for ForbiddenOperationsPolicy.

Extracted to reduce parameter count in compile_all_patterns function.
"""
from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class PatternConfig:
    """Configuration for pattern compilation.

    Bundles all pattern dictionaries and their enable flags into a single config object.
    """
    check_file_writes: bool
    check_dangerous_commands: bool
    check_injection_patterns: bool
    check_security_sensitive: bool
    file_write_patterns: Dict[str, Dict[str, Any]]
    dangerous_command_patterns: Dict[str, Dict[str, Any]]
    injection_patterns: Dict[str, Dict[str, Any]]
    security_sensitive_patterns: Dict[str, Dict[str, Any]]
    custom_forbidden_patterns: Dict[str, str]
