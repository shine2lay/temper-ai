"""
Secure temporary directory management.

This module manages a dedicated temporary directory within allowed_root,
replacing unsafe /tmp access. Features:
- Owner-only permissions (0o700)
- Scoped to allowed_root/.tmp
- Path traversal prevention
- Cleanup operations
"""
from pathlib import Path
from typing import Optional

from src.utils.constants import MAX_COMPONENT_LENGTH
from src.utils.path_safety.exceptions import PathSafetyError


class SecureTempDirectory:
    """Manages secure temporary directory within allowed_root."""

    def __init__(
        self,
        allowed_root: Path,
        enabled: bool = True,
        max_component_length: int = MAX_COMPONENT_LENGTH
    ):
        """Initialize secure temp directory manager.

        Args:
            allowed_root: Root directory to create .tmp under
            enabled: If True, create temp directory
            max_component_length: Maximum filename length
        """
        self.allowed_root = allowed_root
        self.max_component_length = max_component_length
        self.temp_dir: Optional[Path] = None

        if enabled:
            self._create_secure_temp_dir()

    def _create_secure_temp_dir(self) -> None:
        """Create .tmp directory with owner-only permissions (0o700)."""
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

    def get_temp_path(self, filename: str) -> Path:
        """Get secure temporary file path.

        SECURITY:
        - Scoped to allowed_root/.tmp
        - No path traversal allowed in filename
        - Owner-only permissions

        Args:
            filename: Name for temporary file (no path components allowed)

        Returns:
            Path to temporary file within allowed_root/.tmp

        Raises:
            PathSafetyError: If temp directory is disabled or filename invalid
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
        if len(filename) > self.max_component_length:
            raise PathSafetyError(
                f"Temp filename too long (max {self.max_component_length}): {len(filename)}"
            )

        temp_path = self.temp_dir / filename
        return temp_path

    def cleanup_temp_directory(self) -> None:
        """Remove all files in the temporary directory.

        Should be called on application shutdown or session end to clean up
        temporary files.

        SECURITY: Only cleans files within allowed_root/.tmp, preventing
        accidental deletion of files outside the allowed root.

        Raises:
            PathSafetyError: If temp directory is disabled
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

    def is_enabled(self) -> bool:
        """Check if temp directory is enabled.

        Returns:
            True if temp directory is available
        """
        return self.temp_dir is not None
