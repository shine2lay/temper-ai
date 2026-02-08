"""
Main PathSafetyValidator coordinator class.

This module contains the slim orchestrator that delegates to specialized
modules for:
- Platform-specific handling
- Symlink security
- Temporary directory management
- Validation rules enforcement
"""
import os
from pathlib import Path
from typing import List, Optional, Union

from src.utils.path_safety.exceptions import PathSafetyError
from src.utils.path_safety.path_rules import PathValidationRules
from src.utils.path_safety.platform_detector import PlatformPathDetector
from src.utils.path_safety.symlink_validator import SymlinkSecurityValidator
from src.utils.path_safety.temp_directory import SecureTempDirectory


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

    @staticmethod
    def _get_windows_system_paths() -> List[str]:
        """DEPRECATED: Use PlatformPathDetector.get_windows_system_paths()."""
        return PlatformPathDetector.get_windows_system_paths()

    @classmethod
    def _get_forbidden_paths(cls) -> List[str]:
        """DEPRECATED: Use PlatformPathDetector.get_forbidden_paths()."""
        return PlatformPathDetector.get_forbidden_paths()

    # Cache forbidden paths (computed once per class, not per instance)
    FORBIDDEN_PATHS = None  # Will be populated on first access

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

        # Populate FORBIDDEN_PATHS on first access (class-level caching)
        if PathSafetyValidator.FORBIDDEN_PATHS is None:
            PathSafetyValidator.FORBIDDEN_PATHS = PlatformPathDetector.get_forbidden_paths()

        # Build full forbidden list
        self.forbidden = self.FORBIDDEN_PATHS.copy()
        if additional_forbidden:
            self.forbidden.extend(additional_forbidden)

        # Initialize path validation rules
        self.rules = PathValidationRules(
            allowed_root=self.allowed_root,
            forbidden_paths=self.forbidden,
            forbidden_project_dirs=self.FORBIDDEN_PROJECT_DIRS
        )

        # Initialize symlink security validator
        self.symlink_validator = SymlinkSecurityValidator(
            allowed_root=self.allowed_root
        )

        # Initialize secure temp directory manager
        self.temp_dir_manager = SecureTempDirectory(
            allowed_root=self.allowed_root,
            enabled=enable_temp_directory,
            max_component_length=self.MAX_COMPONENT_LENGTH
        )

        # Expose temp_dir for backward compatibility
        self.temp_dir = self.temp_dir_manager.temp_dir

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
        # Step 1: Normalize and basic validation
        path = self.rules.normalize_and_validate_basic(path)

        # Step 2: Pre-resolution symlink security (CRITICAL for TOCTOU)
        self.symlink_validator.validate_symlink_security(
            path,
            check_parents=True
        )

        # Step 3: Resolve path safely
        resolved = self.rules.resolve_path_safely(path)

        # Step 4: Check within allowed root
        self.rules.check_within_allowed_root(resolved)

        # Step 5: Existence checks
        if must_exist and not resolved.exists():
            raise PathSafetyError(f"Path must exist: {resolved}")

        if not allow_create and not resolved.exists():
            raise PathSafetyError(f"Path does not exist: {resolved}")

        # Step 6: Forbidden path checks
        self.rules.check_forbidden_paths(resolved)

        # Step 7: Final symlink check (for absolute symlinks)
        self.symlink_validator.check_final_symlink(path)

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
        """Get secure temp path (delegates to temp directory manager).

        Args:
            filename: Name for temporary file (no path components allowed)

        Returns:
            Path to temporary file within allowed_root/.tmp

        Raises:
            PathSafetyError: If temp directory is disabled or filename invalid
        """
        temp_path = self.temp_dir_manager.get_temp_path(filename)
        return self.validate_path(temp_path, must_exist=False, allow_create=True)

    def cleanup_temp_directory(self) -> None:
        """Cleanup temp directory (delegates to manager).

        Raises:
            PathSafetyError: If temp directory is disabled
        """
        self.temp_dir_manager.cleanup_temp_directory()

    def _check_forbidden(self, resolved: Path) -> None:
        """DEPRECATED: Use rules.check_forbidden_paths()."""
        self.rules.check_forbidden_paths(resolved)

    def _check_symlinks(self, original: Path, resolved: Path) -> None:
        """DEPRECATED: Use symlink_validator.check_final_symlink()."""
        self.symlink_validator.check_final_symlink(original)
