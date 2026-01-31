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
    - Dedicated temporary directory (replaces unsafe /tmp access)
    - Unicode normalization
    - Path length limits

    Security Notes:
    - /tmp access is NO LONGER allowed (removed in security fix for code-crit-13)
    - Use get_temp_path() for temporary files (creates allowed_root/.tmp)
    - Temp directory has owner-only permissions (0o700) to prevent cross-user access
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
        additional_forbidden: Optional[List[str]] = None,
        enable_temp_directory: bool = True
    ):
        """
        Initialize path safety validator.

        Args:
            allowed_root: Root directory to constrain operations to (default: cwd)
            additional_forbidden: Additional forbidden path patterns
            enable_temp_directory: Create dedicated temp directory under allowed_root
                                 (replaces unsafe /tmp access)
        """
        self.allowed_root = Path(allowed_root or Path.cwd()).resolve()

        # Build full forbidden list
        self.forbidden = self.FORBIDDEN_PATHS.copy()
        if additional_forbidden:
            self.forbidden.extend(additional_forbidden)

        # Create dedicated temp directory (replaces /tmp for security)
        if enable_temp_directory:
            self.temp_dir = self.allowed_root / ".tmp"
            try:
                self.temp_dir.mkdir(mode=0o700, exist_ok=True)
                # Ensure restrictive permissions (owner-only)
                self.temp_dir.chmod(0o700)
            except OSError as e:
                # If we can't create secure temp dir, disable it
                import logging
                logging.warning(
                    f"Could not create secure temp directory: {e}. "
                    "Temp directory disabled."
                )
                self.temp_dir = None
        else:
            self.temp_dir = None

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

        # SECURITY: Check for symlinks BEFORE resolution to prevent path traversal
        # Check if the path itself is a symlink
        if path.is_symlink():
            # Get the symlink target without following it
            try:
                symlink_target = path.readlink()

                # If symlink target is absolute, check it's within allowed root
                if symlink_target.is_absolute():
                    try:
                        symlink_target.relative_to(self.allowed_root)
                    except ValueError:
                        raise PathSafetyError(
                            f"Symlink '{path}' points to absolute path outside allowed root: {symlink_target}"
                        )
                else:
                    # Relative symlink - resolve it relative to symlink location
                    symlink_resolved = (path.parent / symlink_target).resolve()
                    try:
                        symlink_resolved.relative_to(self.allowed_root)
                    except ValueError:
                        raise PathSafetyError(
                            f"Symlink '{path}' points outside allowed root: {symlink_resolved}"
                        )
            except OSError as e:
                raise PathSafetyError(f"Cannot read symlink target: {e}")

        # Check parent directories for symlinks
        current = path.absolute()
        allowed_root_abs = Path(self.allowed_root).absolute()

        # Walk up the directory tree checking for symlinks
        while current != current.parent and current != allowed_root_abs:
            if current.is_symlink():
                try:
                    symlink_target = current.readlink()

                    # Resolve symlink and check it's within bounds
                    if symlink_target.is_absolute():
                        symlink_resolved = symlink_target
                    else:
                        symlink_resolved = (current.parent / symlink_target).resolve()

                    try:
                        symlink_resolved.relative_to(allowed_root_abs)
                    except ValueError:
                        raise PathSafetyError(
                            f"Parent directory '{current}' is a symlink pointing outside allowed root: {symlink_resolved}"
                        )
                except OSError as e:
                    raise PathSafetyError(f"Cannot validate symlink in path: {e}")

            current = current.parent

        # Resolve to absolute path (follows symlinks - but we've validated them above)
        try:
            resolved = path.resolve()
        except (OSError, RuntimeError) as e:
            # Handle "too many levels of symbolic links" and other resolution errors
            error_msg = str(e).lower()
            if "too many" in error_msg or "symbolic" in error_msg:
                raise PathSafetyError(f"Symlink chain too deep or circular: {e}")
            raise PathSafetyError(f"Cannot resolve path: {e}")

        # Check if within allowed root
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

            # Check this ancestor is within allowed root
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

    def get_temp_path(self, filename: str) -> Path:
        """
        Get a secure temporary file path within allowed_root.

        This replaces the use of /tmp with a dedicated directory
        that is scoped to the current allowed_root, preventing
        cross-user access and symlink attacks.

        SECURITY: Temporary files are created under allowed_root/.tmp
        with owner-only permissions (0o700), preventing:
        - Cross-user file access
        - Symlink attacks via world-writable /tmp
        - Path traversal outside allowed_root

        Args:
            filename: Name for temporary file (no path components allowed)

        Returns:
            Path to temporary file within allowed_root/.tmp

        Raises:
            PathSafetyError: If temp directory is disabled or filename invalid

        Example:
            >>> validator = PathSafetyValidator(allowed_root='/var/app')
            >>> temp_file = validator.get_temp_path('session_data.json')
            >>> # Returns: /var/app/.tmp/session_data.json
        """
        if self.temp_dir is None:
            raise PathSafetyError(
                "Temporary directory is disabled. "
                "Enable with enable_temp_directory=True"
            )

        # Validate filename doesn't contain path traversal
        if "/" in filename or "\\" in filename or ".." in filename:
            raise PathSafetyError(
                f"Invalid temp filename (no path components allowed): {filename}"
            )

        # Validate filename length
        if len(filename) > self.MAX_COMPONENT_LENGTH:
            raise PathSafetyError(
                f"Temp filename too long (max {self.MAX_COMPONENT_LENGTH}): {len(filename)}"
            )

        temp_path = self.temp_dir / filename
        return self.validate_path(temp_path, must_exist=False, allow_create=True)

    def cleanup_temp_directory(self) -> None:
        """
        Remove all files in the temporary directory.

        Should be called on application shutdown or session end to clean up
        temporary files.

        SECURITY: Only cleans files within allowed_root/.tmp, preventing
        accidental deletion of files outside the allowed root.

        Raises:
            PathSafetyError: If temp directory is disabled

        Example:
            >>> validator = PathSafetyValidator(allowed_root='/var/app')
            >>> # ... use temp files ...
            >>> validator.cleanup_temp_directory()  # Clean up on exit
        """
        if self.temp_dir is None:
            raise PathSafetyError(
                "Temporary directory is disabled. "
                "Enable with enable_temp_directory=True"
            )

        if self.temp_dir.exists():
            import shutil
            try:
                # Remove all contents
                shutil.rmtree(self.temp_dir)
                # Recreate with secure permissions
                self.temp_dir.mkdir(mode=0o700, exist_ok=True)
                self.temp_dir.chmod(0o700)
            except OSError as e:
                import logging
                logging.warning(f"Could not cleanup temp directory: {e}")

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
