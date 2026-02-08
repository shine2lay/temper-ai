"""File and Directory Access Restrictions Policy.

Enforces file system access controls to prevent unauthorized access to:
- System directories (/etc, /sys, /proc, etc.)
- Configuration files
- Secrets and credentials
- Parent directory traversal (../)
- Symbolic link exploitation

Supports both allowlist (explicit permissions) and denylist (explicit denials) modes.
"""
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from src.safety._file_access_helpers import (
    decode_url_fully,
    extract_paths,
    has_forbidden_extension,
    has_parent_traversal,
    is_allowed,
    is_denied,
    is_forbidden_directory,
    is_forbidden_file,
    normalize_path,
)
from src.constants.limits import MAX_SHORT_STRING_LENGTH
from src.safety.base import BaseSafetyPolicy
from src.safety.constants import (
    MAX_EXCLUDED_PATH_LENGTH,
    MAX_EXCLUDED_PATHS,
)
from src.safety.interfaces import SafetyViolation, ValidationResult, ViolationSeverity
from src.safety.validation import ValidationMixin

# File access policy priority
FILE_ACCESS_PRIORITY = 95
# Maximum extension length
MAX_EXTENSION_LENGTH = 20
# Maximum file name items
MAX_FILENAME_ITEMS = 100


class FileAccessPolicy(BaseSafetyPolicy, ValidationMixin):
    """Enforces file and directory access restrictions.

    Configuration options:
        allowed_paths: List of allowed path patterns (allowlist mode)
        denied_paths: List of denied path patterns (denylist mode)
        allow_parent_traversal: Allow ../ in paths (default: False)
        allow_symlinks: Allow symbolic link following (default: False)
        allow_absolute_paths: Allow absolute paths (default: True)
        forbidden_extensions: File extensions to block (e.g., [".exe", ".dll"])
        forbidden_directories: Directories to always block
        case_sensitive: Case-sensitive path matching (default: True)

    Default forbidden directories:
        - /etc (system configuration)
        - /sys (kernel interface)
        - /proc (process information)
        - /dev (device files)
        - /boot (boot files)
        - /root (root home)
        - /.ssh (SSH keys)
        - /.aws (AWS credentials)
        - /.env (environment files)
    """

    # System directories that should always be protected
    DEFAULT_FORBIDDEN_DIRS = {
        "/etc", "/sys", "/proc", "/dev", "/boot",
        "/root", "/.ssh", "/.aws", "/.gcp", "/.azure",
    }

    # Files that should always be protected
    DEFAULT_FORBIDDEN_FILES = {
        "/.env", "/.env.local", "/.env.production",
        "/etc/passwd", "/etc/shadow", "/etc/sudoers",
        "/.bashrc", "/.bash_profile", "/.zshrc",
    }

    # File extensions that may indicate security risks
    DEFAULT_FORBIDDEN_EXTENSIONS = {
        ".pem", ".key", ".p12", ".pfx", ".crt", ".cer",
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize file access policy.

        Args:
            config: Policy configuration (optional)

        Raises:
            ValueError: If configuration parameters are invalid
        """
        super().__init__(config or {})

        # Validate path lists (allowed/denied paths)
        allowed_paths_raw = self.config.get("allowed_paths", [])
        if not isinstance(allowed_paths_raw, list):
            raise ValueError(
                f"allowed_paths must be a list of strings, got {type(allowed_paths_raw).__name__}"
            )

        self.allowed_paths: List[str] = []
        for path in allowed_paths_raw:
            if not isinstance(path, str):
                raise ValueError(f"allowed_paths items must be strings, got {type(path).__name__}")
            if len(path) > MAX_EXCLUDED_PATH_LENGTH:
                raise ValueError(f"allowed_paths items must be <= {MAX_EXCLUDED_PATH_LENGTH} characters, got {len(path)}")
            self.allowed_paths.append(path)

        if len(self.allowed_paths) > MAX_EXCLUDED_PATHS:
            raise ValueError(f"allowed_paths must have <= {MAX_EXCLUDED_PATHS} items, got {len(self.allowed_paths)}")

        denied_paths_raw = self.config.get("denied_paths", [])
        if not isinstance(denied_paths_raw, list):
            raise ValueError(
                f"denied_paths must be a list of strings, got {type(denied_paths_raw).__name__}"
            )

        self.denied_paths: List[str] = []
        for path in denied_paths_raw:
            if not isinstance(path, str):
                raise ValueError(f"denied_paths items must be strings, got {type(path).__name__}")
            if len(path) > MAX_EXCLUDED_PATH_LENGTH:
                raise ValueError(f"denied_paths items must be <= {MAX_EXCLUDED_PATH_LENGTH} characters, got {len(path)}")
            self.denied_paths.append(path)

        if len(self.denied_paths) > MAX_EXCLUDED_PATHS:
            raise ValueError(f"denied_paths must have <= {MAX_EXCLUDED_PATHS} items, got {len(self.denied_paths)}")

        # Validate security settings (booleans)
        self.allow_parent_traversal = self._validate_boolean(
            self.config.get("allow_parent_traversal", False),
            "allow_parent_traversal", default=False
        )
        self.allow_symlinks = self._validate_boolean(
            self.config.get("allow_symlinks", False),
            "allow_symlinks", default=False
        )
        self.allow_absolute_paths = self._validate_boolean(
            self.config.get("allow_absolute_paths", True),
            "allow_absolute_paths", default=True
        )
        self.case_sensitive = self._validate_boolean(
            self.config.get("case_sensitive", True),
            "case_sensitive", default=True
        )

        # Validate forbidden extensions
        forbidden_ext_raw = self.config.get("forbidden_extensions", [])
        if not isinstance(forbidden_ext_raw, list):
            raise ValueError(
                f"forbidden_extensions must be a list of strings, got {type(forbidden_ext_raw).__name__}"
            )

        forbidden_ext_validated: List[str] = []
        for ext in forbidden_ext_raw:
            if not isinstance(ext, str):
                raise ValueError(f"forbidden_extensions items must be strings, got {type(ext).__name__}")
            if len(ext) > MAX_EXTENSION_LENGTH:
                raise ValueError(f"forbidden_extensions items must be <= {MAX_EXTENSION_LENGTH} characters, got {len(ext)}")
            if not ext.startswith('.'):
                ext = '.' + ext
            forbidden_ext_validated.append(ext.lower())

        if len(forbidden_ext_validated) > MAX_FILENAME_ITEMS:
            raise ValueError(
                f"forbidden_extensions must have <= {MAX_FILENAME_ITEMS} items, got {len(forbidden_ext_validated)}"
            )

        self.forbidden_extensions: Set[str] = set(forbidden_ext_validated) | self.DEFAULT_FORBIDDEN_EXTENSIONS

        # Validate forbidden directories
        forbidden_dirs_raw = self.config.get("forbidden_directories", [])
        if not isinstance(forbidden_dirs_raw, list):
            raise ValueError(
                f"forbidden_directories must be a list of strings, got {type(forbidden_dirs_raw).__name__}"
            )

        forbidden_dirs_validated: List[str] = []
        for dir_path in forbidden_dirs_raw:
            if not isinstance(dir_path, str):
                raise ValueError(
                    f"forbidden_directories items must be strings, got {type(dir_path).__name__}"
                )
            if len(dir_path) > MAX_EXCLUDED_PATH_LENGTH:
                raise ValueError(
                    f"forbidden_directories items must be <= {MAX_EXCLUDED_PATH_LENGTH} characters, got {len(dir_path)}"
                )
            forbidden_dirs_validated.append(dir_path)

        if len(forbidden_dirs_validated) > MAX_EXCLUDED_PATHS:
            raise ValueError(
                f"forbidden_directories must have <= {MAX_EXCLUDED_PATHS} items, got {len(forbidden_dirs_validated)}"
            )

        self.forbidden_directories: Set[str] = set(forbidden_dirs_validated) | self.DEFAULT_FORBIDDEN_DIRS

        # Validate forbidden files
        forbidden_files_raw = self.config.get("forbidden_files", [])
        if not isinstance(forbidden_files_raw, list):
            raise ValueError(
                f"forbidden_files must be a list of strings, got {type(forbidden_files_raw).__name__}"
            )

        forbidden_files_validated: List[str] = []
        for file_name in forbidden_files_raw:
            if not isinstance(file_name, str):
                raise ValueError(f"forbidden_files items must be strings, got {type(file_name).__name__}")
            if len(file_name) > MAX_SHORT_STRING_LENGTH:
                raise ValueError(f"forbidden_files items must be <= {MAX_SHORT_STRING_LENGTH} characters, got {len(file_name)}")
            forbidden_files_validated.append(file_name)

        if len(forbidden_files_validated) > MAX_EXCLUDED_PATHS:
            raise ValueError(
                f"forbidden_files must have <= {MAX_EXCLUDED_PATHS} items, got {len(forbidden_files_validated)}"
            )

        self.forbidden_files: Set[str] = set(forbidden_files_validated) | self.DEFAULT_FORBIDDEN_FILES

        # Mode detection
        self.mode = "allowlist" if self.allowed_paths else "denylist"

    @property
    def name(self) -> str:
        """Return policy name."""
        return "file_access"

    @property
    def version(self) -> str:
        """Return policy version."""
        return "1.0.0"

    @property
    def priority(self) -> int:
        """Return policy priority."""
        return FILE_ACCESS_PRIORITY

    def _validate_impl(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> ValidationResult:
        """Validate file access action.

        Args:
            action: Action to validate, should contain:
                - operation: "read", "write", "delete", "execute"
                - path: File or directory path
                - paths: List of paths (for batch operations)
            context: Execution context

        Returns:
            ValidationResult with violations if access denied
        """
        violations: List[SafetyViolation] = []
        paths = self._extract_paths(action)

        for path in paths:
            normalized_path = self._normalize_path(path)

            if not self.allow_parent_traversal and self._has_parent_traversal(path):
                violations.append(SafetyViolation(
                    policy_name=self.name, severity=ViolationSeverity.CRITICAL,
                    message=f"Path traversal detected: {path}",
                    action=str(action), context=context,
                    remediation_hint="Remove parent directory references (../)",
                    metadata={"path": path, "violation": "parent_traversal"}
                ))
                continue

            if not self.allow_absolute_paths and os.path.isabs(path):
                violations.append(SafetyViolation(
                    policy_name=self.name, severity=ViolationSeverity.HIGH,
                    message=f"Absolute path not allowed: {path}",
                    action=str(action), context=context,
                    remediation_hint="Use relative paths only",
                    metadata={"path": path, "violation": "absolute_path"}
                ))
                continue

            if self._is_forbidden_file(normalized_path):
                violations.append(SafetyViolation(
                    policy_name=self.name, severity=ViolationSeverity.CRITICAL,
                    message=f"Access to forbidden file: {path}",
                    action=str(action), context=context,
                    remediation_hint="This file contains sensitive data and cannot be accessed",
                    metadata={"path": path, "violation": "forbidden_file"}
                ))
                continue

            if self._is_forbidden_directory(normalized_path):
                violations.append(SafetyViolation(
                    policy_name=self.name, severity=ViolationSeverity.CRITICAL,
                    message=f"Access to forbidden directory: {path}",
                    action=str(action), context=context,
                    remediation_hint="This directory is protected and cannot be accessed",
                    metadata={"path": path, "violation": "forbidden_directory"}
                ))
                continue

            if self._has_forbidden_extension(path):
                ext = Path(path).suffix
                violations.append(SafetyViolation(
                    policy_name=self.name, severity=ViolationSeverity.CRITICAL,
                    message=f"Access to file with forbidden extension: {ext}",
                    action=str(action), context=context,
                    remediation_hint=f"Files with {ext} extension are not allowed",
                    metadata={"path": path, "extension": ext, "violation": "forbidden_extension"}
                ))
                continue

            if self.mode == "allowlist":
                if not self._is_allowed(normalized_path):
                    violations.append(SafetyViolation(
                        policy_name=self.name, severity=ViolationSeverity.CRITICAL,
                        message=f"Path not in allowlist: {path}",
                        action=str(action), context=context,
                        remediation_hint="Add path to allowed_paths or use an allowed directory",
                        metadata={"path": path, "violation": "not_in_allowlist"}
                    ))
            else:
                if self._is_denied(normalized_path):
                    violations.append(SafetyViolation(
                        policy_name=self.name, severity=ViolationSeverity.CRITICAL,
                        message=f"Path in denylist: {path}",
                        action=str(action), context=context,
                        remediation_hint="Use a different path not in denied_paths",
                        metadata={"path": path, "violation": "in_denylist"}
                    ))

        valid = not any(v.severity >= ViolationSeverity.HIGH for v in violations)

        return ValidationResult(
            valid=valid, violations=violations,
            metadata={"mode": self.mode, "paths_checked": len(paths)},
            policy_name=self.name
        )

    def _extract_paths(self, action: Dict[str, Any]) -> List[str]:
        """Extract file paths from action. Delegates to helper."""
        return extract_paths(action)

    def _decode_url_fully(self, path: str, max_iterations: int = 10) -> str:
        """Recursively decode URL encoding until fully decoded. Delegates to helper."""
        return decode_url_fully(path, max_iterations)

    def _normalize_path(self, path: str) -> str:
        """Normalize path for comparison. Delegates to helper."""
        return normalize_path(path, self.case_sensitive)

    def _has_parent_traversal(self, path: str) -> bool:
        """Check if path contains parent directory traversal. Delegates to helper."""
        return has_parent_traversal(path)

    def _is_forbidden_file(self, path: str) -> bool:
        """Check if path is a forbidden file. Delegates to helper."""
        return is_forbidden_file(path, self.forbidden_files, self.case_sensitive)

    def _is_forbidden_directory(self, path: str) -> bool:
        """Check if path is under a forbidden directory. Delegates to helper."""
        return is_forbidden_directory(path, self.forbidden_directories, self.case_sensitive)

    def _has_forbidden_extension(self, path: str) -> bool:
        """Check if path has a forbidden extension. Delegates to helper."""
        return has_forbidden_extension(path, self.forbidden_extensions)

    def _is_allowed(self, path: str) -> bool:
        """Check if path matches allowlist. Delegates to helper."""
        return is_allowed(path, self.allowed_paths, self.case_sensitive)

    def _is_denied(self, path: str) -> bool:
        """Check if path matches denylist. Delegates to helper."""
        return is_denied(path, self.denied_paths, self.case_sensitive)
