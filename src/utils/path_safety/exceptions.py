"""
Path safety exceptions.
"""
from src.utils.exceptions import SecurityError


class PathSafetyError(SecurityError):
    """Raised when a path fails safety validation."""
    pass


__all__ = ["PathSafetyError"]
