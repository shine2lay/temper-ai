"""
Symlink security validation and TOCTOU prevention.

SECURITY CRITICAL: This module validates symlinks BEFORE path resolution
to prevent Time-of-Check-Time-of-Use (TOCTOU) race conditions.

Features:
- Pre-resolution symlink validation
- Parent directory symlink walking
- Circular symlink detection
- Absolute symlink boundary checks
"""
from pathlib import Path

from temper_ai.shared.utils.path_safety.exceptions import PathSafetyError


class SymlinkSecurityValidator:
    """Validates symlinks for security vulnerabilities."""

    def __init__(self, allowed_root: Path):
        """Initialize symlink validator.

        Args:
            allowed_root: Root directory to constrain symlinks to
        """
        self.allowed_root = allowed_root

    def validate_symlink_security(
        self,
        path: Path,
        check_parents: bool = True
    ) -> None:
        """Validate symlink doesn't create security vulnerability.

        SECURITY: Checks BEFORE resolution to prevent TOCTOU.

        Args:
            path: Path to validate (may be symlink)
            check_parents: If True, also check parent directories

        Raises:
            PathSafetyError: If symlink points outside allowed_root
                            or creates security risk
        """
        # Check if the path itself is a symlink
        if path.is_symlink():
            self._check_symlink_target(path)

        # Check parent directories for symlinks
        if check_parents:
            self._walk_and_validate_parent_symlinks(path)

    def _check_symlink_target(self, symlink: Path) -> None:
        """Validate a single symlink target is within bounds.

        Args:
            symlink: Symlink path to validate

        Raises:
            PathSafetyError: If symlink points outside allowed_root
        """
        # Get the symlink target without following it
        try:
            symlink_target = symlink.readlink()

            # If symlink target is absolute, check it's within allowed root
            if symlink_target.is_absolute():
                try:
                    symlink_target.relative_to(self.allowed_root)
                except ValueError:
                    raise PathSafetyError(
                        f"Symlink '{symlink}' points to absolute path outside allowed root: {symlink_target}"
                    )
            else:
                # Relative symlink - resolve it relative to symlink location
                symlink_resolved = (symlink.parent / symlink_target).resolve()
                try:
                    symlink_resolved.relative_to(self.allowed_root)
                except ValueError:
                    raise PathSafetyError(
                        f"Symlink '{symlink}' points outside allowed root: {symlink_resolved}"
                    )
        except OSError as e:
            raise PathSafetyError(f"Cannot read symlink target: {e}")

    def _walk_and_validate_parent_symlinks(self, path: Path) -> None:
        """Walk up directory tree checking for symlinks.

        Args:
            path: Path whose parents to check

        Raises:
            PathSafetyError: If any parent directory is a symlink
                            pointing outside allowed_root
        """
        current = path.absolute()
        allowed_root_abs = self.allowed_root.absolute()

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

    def check_final_symlink(self, original: Path) -> None:
        """Check for absolute symlink abuse (final check).

        This is a final check for absolute symlinks after resolution.

        Args:
            original: Original path provided

        Raises:
            PathSafetyError: If symlink points outside allowed_root
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
