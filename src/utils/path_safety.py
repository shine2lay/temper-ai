"""
Path safety validation utilities.

Centralized path validation to prevent:
- Directory traversal attacks
- Access to forbidden directories
- Symlink abuse
- Path injection
- Unicode normalization attacks
- Null byte injection
"""
import os
import sys
import unicodedata
from pathlib import Path
from typing import Any, List, Optional, Union


class PathSafetyError(Exception):
    """Raised when a path fails safety validation."""
    pass


class PathSafetyValidator:
    """
    Validates file paths for security issues.

    Features:
    - Directory traversal prevention
    - Forbidden path blocking (e.g., /etc, system configs)
    - Symlink resolution and validation
    - Working directory constraints
    - Unicode normalization
    - Path length limits
    """

    # Path length limits (conservative values for cross-platform safety)
    MAX_PATH_LENGTH = 4096  # Typical Linux limit
    MAX_COMPONENT_LENGTH = 255  # Typical filename length limit

    # System paths that should never be accessible
    FORBIDDEN_PATHS = [
        "/etc",
        "/sys",
        "/proc",
        "/dev",
        "/boot",
        "/root",
        "/var/log",
        "C:\\Windows",
        "C:\\Program Files",
        "/usr/bin",
        "/usr/sbin",
    ]

    # Forbidden directories within project (safety systems, configs)
    FORBIDDEN_PROJECT_DIRS = [
        ".git",
        ".env",
        "secrets",
        "credentials",
    ]

    def __init__(
        self,
        allowed_root: Optional[Path] = None,
        additional_forbidden: Optional[List[str]] = None
    ):
        """
        Initialize path safety validator.

        Args:
            allowed_root: Root directory to constrain operations to (default: cwd)
            additional_forbidden: Additional forbidden path patterns
        """
        self.allowed_root = Path(allowed_root or Path.cwd()).resolve()

        # Build full forbidden list
        self.forbidden = self.FORBIDDEN_PATHS.copy()
        if additional_forbidden:
            self.forbidden.extend(additional_forbidden)

    def validate_path(
        self,
        path: Union[str, Path],
        must_exist: bool = False,
        allow_create: bool = True
    ) -> Path:
        """
        Validate a path for safety.

        Args:
            path: Path to validate
            must_exist: If True, path must already exist
            allow_create: If False, reject paths that don't exist

        Returns:
            Resolved absolute path

        Raises:
            PathSafetyError: If path fails validation
        """
        # Convert to Path object
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
                    f"Path component '{component[:50]}...' exceeds maximum length of {self.MAX_COMPONENT_LENGTH} characters"
                )

        # Resolve to absolute path (follows symlinks)
        try:
            resolved = path.resolve()
        except (OSError, RuntimeError) as e:
            # Handle "too many levels of symbolic links" and other resolution errors
            error_msg = str(e).lower()
            if "too many" in error_msg or "symbolic" in error_msg:
                raise PathSafetyError(f"Symlink chain too deep or circular: {e}")
            raise PathSafetyError(f"Cannot resolve path: {e}")

        # Check if within allowed root or /tmp (safe temporary location)
        is_in_allowed_root = False
        try:
            resolved.relative_to(self.allowed_root)
            is_in_allowed_root = True
        except ValueError:
            # Check if in /tmp (safe for temporary files)
            try:
                resolved.relative_to("/tmp")
                is_in_allowed_root = True
            except ValueError:
                pass

        if not is_in_allowed_root:
            raise PathSafetyError(
                f"Path '{resolved}' is outside allowed root '{self.allowed_root}'"
            )

        # Check existence requirements
        if must_exist and not resolved.exists():
            raise PathSafetyError(f"Path must exist: {resolved}")

        if not allow_create and not resolved.exists():
            raise PathSafetyError(f"Path does not exist: {resolved}")

        # Check against forbidden paths
        self._check_forbidden(resolved)

        # Check for symlink abuse
        self._check_symlinks(path, resolved)

        return resolved

    def validate_read(self, path: Path) -> Path:
        """
        Validate a path for reading.

        Args:
            path: Path to validate

        Returns:
            Resolved absolute path

        Raises:
            PathSafetyError: If validation fails
        """
        resolved = self.validate_path(path, must_exist=True, allow_create=False)

        if not resolved.is_file():
            raise PathSafetyError(f"Path is not a file: {resolved}")

        if not os.access(resolved, os.R_OK):
            raise PathSafetyError(f"No read permission: {resolved}")

        return resolved

    def validate_write(self, path: Union[str, Path], allow_overwrite: bool = True, allow_create_parents: bool = False) -> Path:
        """
        Validate a path for writing.

        Args:
            path: Path to validate
            allow_overwrite: If False, reject existing files
            allow_create_parents: If True, allow non-existent parent directories

        Returns:
            Resolved absolute path

        Raises:
            PathSafetyError: If validation fails
        """
        # For new files, validate the parent directory
        if isinstance(path, str):
            path = Path(path)

        if not path.exists():
            # Validate parent directory
            parent = path.parent
            if not parent.exists() and not allow_create_parents:
                raise PathSafetyError(f"Parent directory does not exist: {parent}")

            # Check parent path is safe (even if doesn't exist yet)
            # Get the highest existing ancestor
            parent_to_check = parent
            while not parent_to_check.exists() and parent_to_check != parent_to_check.parent:
                parent_to_check = parent_to_check.parent

            # Check this ancestor is within allowed root or /tmp
            if parent_to_check.exists():
                parent_resolved = parent_to_check.resolve()
            else:
                # If no parent exists at all, check the path itself
                parent_resolved = parent.resolve() if parent.exists() else Path(str(parent)).absolute()

            is_parent_allowed = False
            try:
                parent_resolved.relative_to(self.allowed_root)
                is_parent_allowed = True
            except ValueError:
                # Check if in /tmp (safe for temporary files)
                try:
                    parent_resolved.relative_to("/tmp")
                    is_parent_allowed = True
                except ValueError:
                    pass

            if not is_parent_allowed:
                raise PathSafetyError(
                    f"Parent directory '{parent}' is outside allowed root"
                )
        else:
            # File exists - check overwrite permission
            if not allow_overwrite:
                raise PathSafetyError(f"File exists and overwrite not allowed: {path}")

        resolved = self.validate_path(path, must_exist=False, allow_create=True)

        # Check parent directory is writable (only if it exists)
        parent = resolved.parent
        if parent.exists() and not os.access(parent, os.W_OK):
            raise PathSafetyError(f"No write permission in directory: {parent}")

        return resolved

    def _check_forbidden(self, resolved: Path) -> None:
        """
        Check if path is in forbidden locations.

        Args:
            resolved: Resolved absolute path

        Raises:
            PathSafetyError: If path is forbidden
        """
        resolved_str = str(resolved)

        # On Windows and macOS, use case-insensitive comparison
        is_case_insensitive = sys.platform in ("win32", "darwin")

        # Check against forbidden system paths
        for forbidden in self.forbidden:
            if is_case_insensitive:
                if resolved_str.lower().startswith(forbidden.lower()):
                    raise PathSafetyError(f"Access to forbidden path: {resolved}")
            else:
                if resolved_str.startswith(forbidden):
                    raise PathSafetyError(f"Access to forbidden path: {resolved}")

        # Check against forbidden project directories
        parts = resolved.parts
        for forbidden_dir in self.FORBIDDEN_PROJECT_DIRS:
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

    def _check_symlinks(self, original: Path, resolved: Path) -> None:
        """
        Check for symlink abuse.

        Args:
            original: Original path provided
            resolved: Resolved path after following symlinks

        Raises:
            PathSafetyError: If symlink points outside allowed root
        """
        # Check if it's a symlink
        if original.is_symlink():
            target = original.readlink()

            # If symlink is absolute, ensure it's within allowed root
            if target.is_absolute():
                try:
                    target.resolve().relative_to(self.allowed_root)
                except ValueError:
                    raise PathSafetyError(
                        f"Symlink points outside allowed root: {original} -> {target}"
                    )


# Global validator instance (uses cwd as root)
_default_validator = PathSafetyValidator()


def validate_path(path: Union[str, Path], **kwargs: Any) -> Path:
    """
    Validate a path using the default validator.

    Args:
        path: Path to validate
        **kwargs: Additional arguments passed to validator

    Returns:
        Resolved absolute path

    Raises:
        PathSafetyError: If validation fails
    """
    return _default_validator.validate_path(path, **kwargs)


def validate_read(path: Path) -> Path:
    """
    Validate a path for reading using the default validator.

    Args:
        path: Path to validate

    Returns:
        Resolved absolute path
    """
    return _default_validator.validate_read(path)


def validate_write(path: Path, allow_overwrite: bool = True, allow_create_parents: bool = False) -> Path:
    """
    Validate a path for writing using the default validator.

    Args:
        path: Path to validate
        allow_overwrite: If False, reject existing files
        allow_create_parents: If False, reject paths with non-existent parent directories

    Returns:
        Resolved absolute path
    """
    return _default_validator.validate_write(path, allow_overwrite, allow_create_parents)
