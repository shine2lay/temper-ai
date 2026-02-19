"""
Core path validation rules and safety checks.

This module implements validation rules including:
- Unicode normalization (NFC)
- Null byte injection detection
- Path length limits
- Component length limits
- Forbidden path checking
- Boundary validation (within allowed_root)
"""
import unicodedata
from pathlib import Path
from typing import List, Union

from temper_ai.shared.utils.constants import MAX_COMPONENT_LENGTH, MAX_PATH_LENGTH
from temper_ai.shared.utils.path_safety.exceptions import PathSafetyError
from temper_ai.shared.utils.path_safety.platform_detector import PlatformPathDetector

# Error message truncation length for long path components
ERROR_MSG_COMPONENT_TRUNCATE_LENGTH = 50


class PathValidationRules:
    """Core path validation rules and safety checks."""

    MAX_PATH_LENGTH = MAX_PATH_LENGTH
    MAX_COMPONENT_LENGTH = MAX_COMPONENT_LENGTH

    def __init__(
        self,
        allowed_root: Path,
        forbidden_paths: List[str],
        forbidden_project_dirs: List[str]
    ):
        """Initialize path validation rules.

        Args:
            allowed_root: Root directory to constrain operations to
            forbidden_paths: List of forbidden system paths
            forbidden_project_dirs: List of forbidden project directories
        """
        self.allowed_root = allowed_root
        self.forbidden_paths = forbidden_paths
        self.forbidden_project_dirs = forbidden_project_dirs

    def normalize_and_validate_basic(self, path: Union[str, Path]) -> Path:
        """Normalize path and perform basic validation.

        Checks:
        - Unicode normalization (NFC)
        - Null byte injection
        - Path length limits
        - Component length limits

        Args:
            path: Path to normalize and validate

        Returns:
            Path object with normalized unicode

        Raises:
            PathSafetyError: If validation fails
        """
        # Convert to Path object with unicode normalization
        if isinstance(path, str):
            # Normalize unicode to NFC form (composed form)
            # This prevents attacks using different unicode representations
            path_str = unicodedata.normalize('NFC', path)
            path = Path(path_str)
        else:
            path = Path(unicodedata.normalize('NFC', str(path)))

        # Check for null bytes (path injection)
        path_str = str(path)
        if '\x00' in path_str:
            raise PathSafetyError("Path contains null bytes")

        # Check path length limits
        if len(path_str) > self.MAX_PATH_LENGTH:
            raise PathSafetyError(
                f"Path exceeds maximum length of {self.MAX_PATH_LENGTH} characters"
            )

        # Check component length limits
        for component in path.parts:
            if len(component) > self.MAX_COMPONENT_LENGTH:
                raise PathSafetyError(
                    f"Path component '{component[:ERROR_MSG_COMPONENT_TRUNCATE_LENGTH]}...' exceeds maximum length of {self.MAX_COMPONENT_LENGTH} characters"
                )

        return path

    def check_within_allowed_root(self, resolved: Path) -> None:
        """Verify resolved path is within allowed_root.

        Args:
            resolved: Resolved absolute path

        Raises:
            PathSafetyError: If path is outside allowed_root
        """
        is_in_allowed_root = False
        try:
            resolved.relative_to(self.allowed_root)
            is_in_allowed_root = True
        except ValueError:
            pass

        if not is_in_allowed_root:
            raise PathSafetyError(
                f"Path '{resolved}' is outside allowed root '{self.allowed_root}'"
            )

    def check_forbidden_paths(self, resolved: Path) -> None:
        """Check path doesn't access forbidden system/project paths.

        Args:
            resolved: Resolved absolute path

        Raises:
            PathSafetyError: If path is forbidden
        """
        resolved_str = str(resolved)

        # On Windows and macOS, use case-insensitive comparison
        is_case_insensitive = PlatformPathDetector.is_case_insensitive_fs()

        # Check against forbidden system paths
        for forbidden in self.forbidden_paths:
            if is_case_insensitive:
                if resolved_str.lower().startswith(forbidden.lower()):
                    raise PathSafetyError(f"Access to forbidden path: {resolved}")
            else:
                if resolved_str.startswith(forbidden):
                    raise PathSafetyError(f"Access to forbidden path: {resolved}")

        # Check against forbidden project directories
        parts = resolved.parts
        for forbidden_dir in self.forbidden_project_dirs:
            if is_case_insensitive:
                # Case-insensitive check for project directories
                parts_lower = [p.lower() for p in parts]
                if forbidden_dir.lower() in parts_lower:
                    raise PathSafetyError(
                        f"Access to forbidden directory '{forbidden_dir}': {resolved}"
                    )
            else:
                if forbidden_dir in parts:
                    raise PathSafetyError(
                        f"Access to forbidden directory '{forbidden_dir}': {resolved}"
                    )

    def resolve_path_safely(self, path: Path) -> Path:
        """Resolve path handling symlink resolution errors.

        Args:
            path: Path to resolve

        Returns:
            Resolved absolute path

        Raises:
            PathSafetyError: For circular symlinks or excessive depth
        """
        try:
            resolved = path.resolve()
        except (OSError, RuntimeError) as e:
            # Handle "too many levels of symbolic links" and other resolution errors
            error_msg = str(e).lower()
            if "too many" in error_msg or "symbolic" in error_msg:
                raise PathSafetyError(f"Symlink chain too deep or circular: {e}")
            raise PathSafetyError(f"Cannot resolve path: {e}")

        return resolved
