"""
Path safety exceptions.
"""
from temper_ai.shared.utils.exceptions import SecurityError


class PathSafetyError(SecurityError):
    """Raised when a path fails safety validation."""
    pass


__all__ = ["PathSafetyError"]
