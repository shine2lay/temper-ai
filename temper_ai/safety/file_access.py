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
from typing import Any

from temper_ai.safety._file_access_helpers import (
    extract_paths,
    has_forbidden_extension,
    has_parent_traversal,
    is_allowed,
    is_denied,
    is_forbidden_directory,
    is_forbidden_file,
    normalize_path,
)
from temper_ai.safety.base import BaseSafetyPolicy
from temper_ai.safety.constants import (
    ERROR_CHARS_GOT,
    ERROR_ITEMS_GOT,
    MAX_EXCLUDED_PATH_LENGTH,
    MAX_EXCLUDED_PATHS,
    PATH_KEY,
    VIOLATION_KEY,
)
from temper_ai.safety.interfaces import (
    SafetyViolation,
    ValidationResult,
    ViolationSeverity,
)
from temper_ai.safety.validation import ValidationMixin
from temper_ai.shared.constants.limits import MAX_SHORT_STRING_LENGTH

# File access violation types
VIOLATION_PARENT_TRAVERSAL = "parent_traversal"
VIOLATION_ABSOLUTE_PATH = "absolute_path"
VIOLATION_FORBIDDEN_FILE = "forbidden_file"
VIOLATION_FORBIDDEN_DIRECTORY = "forbidden_directory"
VIOLATION_FORBIDDEN_EXTENSION = "forbidden_extension"
VIOLATION_NOT_IN_ALLOWLIST = "not_in_allowlist"
VIOLATION_IN_DENYLIST = "in_denylist"

# File access modes
MODE_ALLOWLIST = "allowlist"
MODE_DENYLIST = "denylist"

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
        "/etc",
        "/sys",
        "/proc",
        "/dev",
        "/boot",
        "/root",
        "/.ssh",
        "/.aws",
        "/.gcp",
        "/.azure",
    }

    # Files that should always be protected
    DEFAULT_FORBIDDEN_FILES = {
        "/.env",
        "/.env.local",
        "/.env.production",
        "/etc/passwd",
        "/etc/shadow",
        "/etc/sudoers",
        "/.bashrc",
        "/.bash_profile",
        "/.zshrc",
    }

    # File extensions that may indicate security risks
    DEFAULT_FORBIDDEN_EXTENSIONS = {
        ".pem",
        ".key",
        ".p12",
        ".pfx",
        ".crt",
        ".cer",
    }

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize file access policy.

        Args:
            config: Policy configuration (optional)

        Raises:
            ValueError: If configuration parameters are invalid
        """
        super().__init__(config or {})

        # Initialize and validate path configurations
        self.allowed_paths = self._init_path_list("allowed_paths")
        self.denied_paths = self._init_path_list("denied_paths")

        # Initialize security settings
        self._init_security_settings()

        # Initialize forbidden patterns
        self.forbidden_extensions = self._init_forbidden_extensions()
        self.forbidden_directories = self._init_forbidden_directories()
        self.forbidden_files = self._init_forbidden_files()

        # Mode detection
        self.mode = MODE_ALLOWLIST if self.allowed_paths else MODE_DENYLIST

    def _init_path_list(self, config_key: str) -> list[str]:
        """Initialize and validate a path list from configuration.

        Args:
            config_key: Configuration key to read

        Returns:
            Validated list of paths

        Raises:
            ValueError: If validation fails
        """
        paths_raw = self.config.get(config_key, [])
        if not isinstance(paths_raw, list):
            raise ValueError(
                f"{config_key} must be a list of strings, got {type(paths_raw).__name__}"
            )

        paths: list[str] = []
        for path in paths_raw:
            if not isinstance(path, str):
                raise ValueError(
                    f"{config_key} items must be strings, got {type(path).__name__}"
                )
            if len(path) > MAX_EXCLUDED_PATH_LENGTH:
                raise ValueError(
                    f"{config_key} items must be <= {MAX_EXCLUDED_PATH_LENGTH}{ERROR_CHARS_GOT}{len(path)}"
                )
            paths.append(path)

        if len(paths) > MAX_EXCLUDED_PATHS:
            raise ValueError(
                f"{config_key} must have <= {MAX_EXCLUDED_PATHS}{ERROR_ITEMS_GOT}{len(paths)}"
            )

        return paths

    def _init_security_settings(self) -> None:
        """Initialize boolean security settings."""
        self.allow_parent_traversal = self._validate_boolean(
            self.config.get("allow_parent_traversal", False),
            "allow_parent_traversal",
            default=False,
        )
        self.allow_symlinks = self._validate_boolean(
            self.config.get("allow_symlinks", False), "allow_symlinks", default=False
        )
        self.allow_absolute_paths = self._validate_boolean(
            self.config.get("allow_absolute_paths", True),
            "allow_absolute_paths",
            default=True,
        )
        self.case_sensitive = self._validate_boolean(
            self.config.get("case_sensitive", True), "case_sensitive", default=True
        )

    def _init_forbidden_extensions(self) -> set[str]:
        """Initialize forbidden file extensions.

        Returns:
            Set of forbidden extensions (with defaults)

        Raises:
            ValueError: If validation fails
        """
        forbidden_ext_raw = self.config.get("forbidden_extensions", [])
        if not isinstance(forbidden_ext_raw, list):
            raise ValueError(
                f"forbidden_extensions must be a list of strings, got {type(forbidden_ext_raw).__name__}"
            )

        forbidden_ext_validated: list[str] = []
        for ext in forbidden_ext_raw:
            if not isinstance(ext, str):
                raise ValueError(
                    f"forbidden_extensions items must be strings, got {type(ext).__name__}"
                )
            if len(ext) > MAX_EXTENSION_LENGTH:
                raise ValueError(
                    f"forbidden_extensions items must be <= {MAX_EXTENSION_LENGTH}{ERROR_CHARS_GOT}{len(ext)}"
                )
            if not ext.startswith("."):
                ext = "." + ext
            forbidden_ext_validated.append(ext.lower())

        if len(forbidden_ext_validated) > MAX_FILENAME_ITEMS:
            raise ValueError(
                f"forbidden_extensions must have <= {MAX_FILENAME_ITEMS}{ERROR_ITEMS_GOT}{len(forbidden_ext_validated)}"
            )

        return set(forbidden_ext_validated) | self.DEFAULT_FORBIDDEN_EXTENSIONS

    def _init_forbidden_directories(self) -> set[str]:
        """Initialize forbidden directories.

        Returns:
            Set of forbidden directories (with defaults)

        Raises:
            ValueError: If validation fails
        """
        forbidden_dirs_raw = self.config.get("forbidden_directories", [])
        if not isinstance(forbidden_dirs_raw, list):
            raise ValueError(
                f"forbidden_directories must be a list of strings, got {type(forbidden_dirs_raw).__name__}"
            )

        forbidden_dirs_validated: list[str] = []
        for dir_path in forbidden_dirs_raw:
            if not isinstance(dir_path, str):
                raise ValueError(
                    f"forbidden_directories items must be strings, got {type(dir_path).__name__}"
                )
            if len(dir_path) > MAX_EXCLUDED_PATH_LENGTH:
                raise ValueError(
                    f"forbidden_directories items must be <= {MAX_EXCLUDED_PATH_LENGTH}{ERROR_CHARS_GOT}{len(dir_path)}"
                )
            forbidden_dirs_validated.append(dir_path)

        if len(forbidden_dirs_validated) > MAX_EXCLUDED_PATHS:
            raise ValueError(
                f"forbidden_directories must have <= {MAX_EXCLUDED_PATHS}{ERROR_ITEMS_GOT}{len(forbidden_dirs_validated)}"
            )

        return set(forbidden_dirs_validated) | self.DEFAULT_FORBIDDEN_DIRS

    def _init_forbidden_files(self) -> set[str]:
        """Initialize forbidden files.

        Returns:
            Set of forbidden files (with defaults)

        Raises:
            ValueError: If validation fails
        """
        forbidden_files_raw = self.config.get("forbidden_files", [])
        if not isinstance(forbidden_files_raw, list):
            raise ValueError(
                f"forbidden_files must be a list of strings, got {type(forbidden_files_raw).__name__}"
            )

        forbidden_files_validated: list[str] = []
        for file_name in forbidden_files_raw:
            if not isinstance(file_name, str):
                raise ValueError(
                    f"forbidden_files items must be strings, got {type(file_name).__name__}"
                )
            if len(file_name) > MAX_SHORT_STRING_LENGTH:
                raise ValueError(
                    f"forbidden_files items must be <= {MAX_SHORT_STRING_LENGTH}{ERROR_CHARS_GOT}{len(file_name)}"
                )
            forbidden_files_validated.append(file_name)

        if len(forbidden_files_validated) > MAX_EXCLUDED_PATHS:
            raise ValueError(
                f"forbidden_files must have <= {MAX_EXCLUDED_PATHS}{ERROR_ITEMS_GOT}{len(forbidden_files_validated)}"
            )

        return set(forbidden_files_validated) | self.DEFAULT_FORBIDDEN_FILES

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
        self, action: dict[str, Any], context: dict[str, Any]
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
        violations: list[SafetyViolation] = []
        paths = extract_paths(action)

        for path in paths:
            normalized_path = normalize_path(path, self.case_sensitive)

            # Check for security violations
            violation = self._check_path_security(
                path, normalized_path, action, context
            )
            if violation:
                violations.append(violation)
                continue

            # Check access control (allowlist/denylist)
            violation = self._check_path_access(path, normalized_path, action, context)
            if violation:
                violations.append(violation)

        valid = not any(v.severity >= ViolationSeverity.HIGH for v in violations)

        return ValidationResult(
            valid=valid,
            violations=violations,
            metadata={"mode": self.mode, "paths_checked": len(paths)},
            policy_name=self.name,
        )

    def _check_path_security(  # noqa: long
        self,
        path: str,
        normalized_path: str,
        action: dict[str, Any],
        context: dict[str, Any],
    ) -> SafetyViolation | None:
        """Check path for traversal, absolute-path, and forbidden-path violations."""
        v = self._check_traversal_and_absolute(path, action, context)
        if v is not None:
            return v
        return self._check_forbidden_path(path, normalized_path, action, context)

    def _check_traversal_and_absolute(
        self,
        path: str,
        action: dict[str, Any],
        context: dict[str, Any],
    ) -> SafetyViolation | None:
        """Return a violation if path uses traversal or an absolute path."""
        if not self.allow_parent_traversal and has_parent_traversal(path):
            return SafetyViolation(
                policy_name=self.name,
                severity=ViolationSeverity.CRITICAL,
                message=f"Path traversal detected: {path}",
                action=str(action),
                context=context,
                remediation_hint="Remove parent directory references (../)",
                metadata={PATH_KEY: path, VIOLATION_KEY: VIOLATION_PARENT_TRAVERSAL},
            )
        if not self.allow_absolute_paths and os.path.isabs(path):
            return SafetyViolation(
                policy_name=self.name,
                severity=ViolationSeverity.HIGH,
                message=f"Absolute path not allowed: {path}",
                action=str(action),
                context=context,
                remediation_hint="Use relative paths only",
                metadata={PATH_KEY: path, VIOLATION_KEY: VIOLATION_ABSOLUTE_PATH},
            )
        return None

    def _check_forbidden_path(
        self,
        path: str,
        normalized_path: str,
        action: dict[str, Any],
        context: dict[str, Any],
    ) -> SafetyViolation | None:
        """Return a violation if path is a forbidden file, directory, or extension."""
        if is_forbidden_file(
            normalized_path, self.forbidden_files, self.case_sensitive
        ):
            return SafetyViolation(
                policy_name=self.name,
                severity=ViolationSeverity.CRITICAL,
                message=f"Access to forbidden file: {path}",
                action=str(action),
                context=context,
                remediation_hint="This file contains sensitive data and cannot be accessed",
                metadata={PATH_KEY: path, VIOLATION_KEY: VIOLATION_FORBIDDEN_FILE},
            )
        if is_forbidden_directory(
            normalized_path, self.forbidden_directories, self.case_sensitive
        ):
            return SafetyViolation(
                policy_name=self.name,
                severity=ViolationSeverity.CRITICAL,
                message=f"Access to forbidden directory: {path}",
                action=str(action),
                context=context,
                remediation_hint="This directory is protected and cannot be accessed",
                metadata={PATH_KEY: path, VIOLATION_KEY: VIOLATION_FORBIDDEN_DIRECTORY},
            )
        if has_forbidden_extension(path, self.forbidden_extensions):
            ext = Path(path).suffix
            return SafetyViolation(
                policy_name=self.name,
                severity=ViolationSeverity.CRITICAL,
                message=f"Access to file with forbidden extension: {ext}",
                action=str(action),
                context=context,
                remediation_hint=f"Files with {ext} extension are not allowed",
                metadata={
                    "path": path,
                    "extension": ext,
                    "violation": VIOLATION_FORBIDDEN_EXTENSION,
                },
            )
        return None

    def _check_path_access(
        self,
        path: str,
        normalized_path: str,
        action: dict[str, Any],
        context: dict[str, Any],
    ) -> SafetyViolation | None:
        """Check path against allowlist/denylist.

        Args:
            path: Original path
            normalized_path: Normalized path
            action: Action being validated
            context: Execution context

        Returns:
            SafetyViolation if path fails access check, None otherwise
        """
        if self.mode == MODE_ALLOWLIST:
            if not is_allowed(normalized_path, self.allowed_paths, self.case_sensitive):
                return SafetyViolation(
                    policy_name=self.name,
                    severity=ViolationSeverity.CRITICAL,
                    message=f"Path not in allowlist: {path}",
                    action=str(action),
                    context=context,
                    remediation_hint="Add path to allowed_paths or use an allowed directory",
                    metadata={
                        PATH_KEY: path,
                        VIOLATION_KEY: VIOLATION_NOT_IN_ALLOWLIST,
                    },
                )
        else:
            if is_denied(normalized_path, self.denied_paths, self.case_sensitive):
                return SafetyViolation(
                    policy_name=self.name,
                    severity=ViolationSeverity.CRITICAL,
                    message=f"Path in denylist: {path}",
                    action=str(action),
                    context=context,
                    remediation_hint="Use a different path not in denied_paths",
                    metadata={PATH_KEY: path, VIOLATION_KEY: VIOLATION_IN_DENYLIST},
                )
        return None
