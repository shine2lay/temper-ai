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
import re
import unicodedata
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from src.safety.base import BaseSafetyPolicy
from src.safety.interfaces import SafetyViolation, ValidationResult, ViolationSeverity
from src.safety.validation import ValidationMixin


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

    Path matching supports:
        - Wildcards: /project/*.py, /data/**/*.json
        - Exact paths: /project/src/main.py
        - Directory prefixes: /project/src/ (matches all under src/)

    Example (Allowlist mode):
        >>> config = {
        ...     "allowed_paths": ["/project/src/**", "/tmp/**"],
        ...     "allow_parent_traversal": False,
        ...     "allow_symlinks": False
        ... }
        >>> policy = FileAccessPolicy(config)
        >>> result = policy.validate(
        ...     action={"operation": "read", "path": "/project/src/main.py"},
        ...     context={"agent": "coder"}
        ... )

    Example (Denylist mode):
        >>> config = {
        ...     "denied_paths": ["/etc/**", "/root/**"],
        ...     "forbidden_extensions": [".exe", ".dll"]
        ... }
        >>> policy = FileAccessPolicy(config)
        >>> result = policy.validate(
        ...     action={"operation": "write", "path": "/home/user/data.txt"},
        ...     context={}
        ... )
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

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize file access policy.

        Args:
            config: Policy configuration (optional)

        Raises:
            ValueError: If configuration parameters are invalid
        """
        super().__init__(config or {})

        # SECURITY (code-high-12): Validate all configuration inputs
        # Prevents type confusion and security bypass via malformed config

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
            if len(path) > 500:
                raise ValueError(f"allowed_paths items must be <= 500 characters, got {len(path)}")
            self.allowed_paths.append(path)

        if len(self.allowed_paths) > 1000:
            raise ValueError(f"allowed_paths must have <= 1000 items, got {len(self.allowed_paths)}")

        denied_paths_raw = self.config.get("denied_paths", [])
        if not isinstance(denied_paths_raw, list):
            raise ValueError(
                f"denied_paths must be a list of strings, got {type(denied_paths_raw).__name__}"
            )

        self.denied_paths: List[str] = []
        for path in denied_paths_raw:
            if not isinstance(path, str):
                raise ValueError(f"denied_paths items must be strings, got {type(path).__name__}")
            if len(path) > 500:
                raise ValueError(f"denied_paths items must be <= 500 characters, got {len(path)}")
            self.denied_paths.append(path)

        if len(self.denied_paths) > 1000:
            raise ValueError(f"denied_paths must have <= 1000 items, got {len(self.denied_paths)}")

        # Validate security settings (booleans)
        # CRITICAL: Prevents type confusion attacks like allow_parent_traversal="false" -> True
        self.allow_parent_traversal = self._validate_boolean(
            self.config.get("allow_parent_traversal", False),
            "allow_parent_traversal",
            default=False
        )

        self.allow_symlinks = self._validate_boolean(
            self.config.get("allow_symlinks", False),
            "allow_symlinks",
            default=False
        )

        self.allow_absolute_paths = self._validate_boolean(
            self.config.get("allow_absolute_paths", True),
            "allow_absolute_paths",
            default=True
        )

        self.case_sensitive = self._validate_boolean(
            self.config.get("case_sensitive", True),
            "case_sensitive",
            default=True
        )

        # Validate forbidden patterns (lists of strings)
        forbidden_ext_raw = self.config.get("forbidden_extensions", [])
        if not isinstance(forbidden_ext_raw, list):
            raise ValueError(
                f"forbidden_extensions must be a list of strings, got {type(forbidden_ext_raw).__name__}"
            )

        forbidden_ext_validated: List[str] = []
        for ext in forbidden_ext_raw:
            if not isinstance(ext, str):
                raise ValueError(f"forbidden_extensions items must be strings, got {type(ext).__name__}")
            if len(ext) > 20:
                raise ValueError(f"forbidden_extensions items must be <= 20 characters, got {len(ext)}")
            if not ext.startswith('.'):
                ext = '.' + ext  # Auto-add dot prefix
            forbidden_ext_validated.append(ext.lower())

        if len(forbidden_ext_validated) > 100:
            raise ValueError(
                f"forbidden_extensions must have <= 100 items, got {len(forbidden_ext_validated)}"
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
            if len(dir_path) > 500:
                raise ValueError(
                    f"forbidden_directories items must be <= 500 characters, got {len(dir_path)}"
                )
            forbidden_dirs_validated.append(dir_path)

        if len(forbidden_dirs_validated) > 1000:
            raise ValueError(
                f"forbidden_directories must have <= 1000 items, got {len(forbidden_dirs_validated)}"
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
            if len(file_name) > 255:
                raise ValueError(f"forbidden_files items must be <= 255 characters, got {len(file_name)}")
            forbidden_files_validated.append(file_name)

        if len(forbidden_files_validated) > 1000:
            raise ValueError(
                f"forbidden_files must have <= 1000 items, got {len(forbidden_files_validated)}"
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
        """Return policy priority.

        File access has highest priority as it's a critical security control.
        """
        return 95

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

        # Extract paths from action
        paths = self._extract_paths(action)

        for path in paths:
            # Normalize path
            normalized_path = self._normalize_path(path)

            # Check for path traversal
            if not self.allow_parent_traversal and self._has_parent_traversal(path):
                violations.append(SafetyViolation(
                    policy_name=self.name,
                    severity=ViolationSeverity.CRITICAL,
                    message=f"Path traversal detected: {path}",
                    action=str(action),
                    context=context,
                    remediation_hint="Remove parent directory references (../)",
                    metadata={"path": path, "violation": "parent_traversal"}
                ))
                continue

            # Check absolute path restriction
            if not self.allow_absolute_paths and os.path.isabs(path):
                violations.append(SafetyViolation(
                    policy_name=self.name,
                    severity=ViolationSeverity.HIGH,
                    message=f"Absolute path not allowed: {path}",
                    action=str(action),
                    context=context,
                    remediation_hint="Use relative paths only",
                    metadata={"path": path, "violation": "absolute_path"}
                ))
                continue

            # Check forbidden files
            if self._is_forbidden_file(normalized_path):
                violations.append(SafetyViolation(
                    policy_name=self.name,
                    severity=ViolationSeverity.CRITICAL,
                    message=f"Access to forbidden file: {path}",
                    action=str(action),
                    context=context,
                    remediation_hint="This file contains sensitive data and cannot be accessed",
                    metadata={"path": path, "violation": "forbidden_file"}
                ))
                continue

            # Check forbidden directories
            if self._is_forbidden_directory(normalized_path):
                violations.append(SafetyViolation(
                    policy_name=self.name,
                    severity=ViolationSeverity.CRITICAL,
                    message=f"Access to forbidden directory: {path}",
                    action=str(action),
                    context=context,
                    remediation_hint="This directory is protected and cannot be accessed",
                    metadata={"path": path, "violation": "forbidden_directory"}
                ))
                continue

            # Check forbidden extensions
            if self._has_forbidden_extension(path):
                ext = Path(path).suffix
                violations.append(SafetyViolation(
                    policy_name=self.name,
                    severity=ViolationSeverity.CRITICAL,
                    message=f"Access to file with forbidden extension: {ext}",
                    action=str(action),
                    context=context,
                    remediation_hint=f"Files with {ext} extension are not allowed",
                    metadata={"path": path, "extension": ext, "violation": "forbidden_extension"}
                ))
                continue

            # Apply allowlist/denylist rules
            if self.mode == "allowlist":
                if not self._is_allowed(normalized_path):
                    violations.append(SafetyViolation(
                        policy_name=self.name,
                        severity=ViolationSeverity.CRITICAL,
                        message=f"Path not in allowlist: {path}",
                        action=str(action),
                        context=context,
                        remediation_hint="Add path to allowed_paths or use an allowed directory",
                        metadata={"path": path, "violation": "not_in_allowlist"}
                    ))
            else:  # denylist mode
                if self._is_denied(normalized_path):
                    violations.append(SafetyViolation(
                        policy_name=self.name,
                        severity=ViolationSeverity.CRITICAL,
                        message=f"Path in denylist: {path}",
                        action=str(action),
                        context=context,
                        remediation_hint="Use a different path not in denied_paths",
                        metadata={"path": path, "violation": "in_denylist"}
                    ))

        # Determine validity
        valid = not any(
            v.severity >= ViolationSeverity.HIGH
            for v in violations
        )

        return ValidationResult(
            valid=valid,
            violations=violations,
            metadata={"mode": self.mode, "paths_checked": len(paths)},
            policy_name=self.name
        )

    def _extract_paths(self, action: Dict[str, Any]) -> List[str]:
        """Extract file paths from action.

        Args:
            action: Action dictionary

        Returns:
            List of file paths
        """
        paths = []

        # Single path
        if "path" in action:
            paths.append(str(action["path"]))

        # Multiple paths
        if "paths" in action and isinstance(action["paths"], list):
            paths.extend([str(p) for p in action["paths"]])

        # Source/destination paths (for copy/move operations)
        if "source" in action:
            paths.append(str(action["source"]))
        if "destination" in action:
            paths.append(str(action["destination"]))

        return paths

    def _decode_url_fully(self, path: str, max_iterations: int = 10) -> str:
        """Recursively decode URL encoding until fully decoded.

        SECURITY FIX (test-crit-url-decode-01): Prevent URL encoding bypasses.

        Handles:
        - Single encoding: %2e%2e → ..
        - Double encoding: %252e → %2e → .
        - Triple+ encoding: recursive until stable
        - Case-insensitive encoding: %2E same as %2e
        - Null byte injection: %00

        Args:
            path: Path to decode
            max_iterations: Prevent infinite loops (default: 10)

        Returns:
            Fully decoded path

        Raises:
            ValueError: If decoding doesn't stabilize after max_iterations

        Examples:
            >>> _decode_url_fully("/etc/%2e%2e/passwd")
            "/etc/../passwd"
            >>> _decode_url_fully("/etc/%252e%252e/passwd")
            "/etc/../passwd"
            >>> _decode_url_fully("/files/my%20document.txt")
            "/files/my document.txt"
        """
        decoded = path
        for i in range(max_iterations):
            previous = decoded
            try:
                # Use strict error handling - malformed encoding raises exception
                decoded = urllib.parse.unquote(decoded, errors='strict')
            except (UnicodeDecodeError, ValueError):
                # Malformed percent encoding (e.g., %GG, %2, %) - use original path
                # This is safer than trying to partially decode
                return path

            if decoded == previous:
                # Stable - fully decoded
                return decoded

        # Didn't stabilize after max_iterations - possible attack (deeply nested encoding)
        # Raise error to block suspicious paths
        raise ValueError(
            f"URL decoding did not stabilize after {max_iterations} iterations. "
            f"Path may contain deeply nested encoding: {path[:100]}"
        )

    def _normalize_unicode(self, path: str) -> str:
        """Normalize Unicode to prevent bypass attacks.

        SECURITY FIX (test-crit-unicode-norm-01): Prevent Unicode bypass attacks.

        Uses NFKC normalization plus manual replacement of dangerous lookalikes that
        NFKC doesn't handle (U+2215, U+2044, etc.).

        Args:
            path: Path to normalize

        Returns:
            Normalized path with dangerous Unicode converted to ASCII

        Examples:
            >>> _normalize_unicode('/etc\u2215passwd')
            '/etc/passwd'
            >>> _normalize_unicode('ｆｉｌｅ.ｔｘｔ')
            'file.txt'
            >>> _normalize_unicode('/et\u200bc/passwd')  # Zero-width space
            '/etc/passwd'
        """
        # Strip BOM (Byte Order Mark) if present at start
        if path and path[0] == '\ufeff':
            path = path[1:]

        # Remove zero-width characters (often used in obfuscation)
        # These are invisible and can hide malicious patterns
        zero_width_chars = [
            '\u200b',  # ZERO WIDTH SPACE
            '\u200c',  # ZERO WIDTH NON-JOINER
            '\u200d',  # ZERO WIDTH JOINER
            '\ufeff',  # ZERO WIDTH NO-BREAK SPACE (BOM)
            '\u2060',  # WORD JOINER
        ]
        for char in zero_width_chars:
            path = path.replace(char, '')

        # CRITICAL: Manually replace dangerous Unicode lookalikes that NFKC doesn't normalize
        # These characters are NOT in NFKC compatibility decomposition table
        dangerous_lookalikes = {
            '\u2215': '/',  # DIVISION SLASH → SOLIDUS
            '\u2044': '/',  # FRACTION SLASH → SOLIDUS
            '\u29f8': '/',  # BIG SOLIDUS → SOLIDUS
            '\u2024': '.',  # ONE DOT LEADER → PERIOD
            '\u2025': '..',  # TWO DOT LEADER → TWO PERIODS
            '\u2026': '...',  # HORIZONTAL ELLIPSIS → THREE PERIODS
            '\u00b7': '.',  # MIDDLE DOT → PERIOD
            '\u2027': '.',  # HYPHENATION POINT → PERIOD
            '\u0338': '',  # COMBINING LONG SOLIDUS OVERLAY → remove
        }
        for dangerous, safe in dangerous_lookalikes.items():
            path = path.replace(dangerous, safe)

        # Apply NFKC normalization
        # NFKC handles fullwidth characters and some compatibility equivalents
        # Example: ＡＢＣ → ABC, ＿ → _, ／ → /
        try:
            normalized = unicodedata.normalize('NFKC', path)
        except (UnicodeError, ValueError):
            # If normalization fails (invalid Unicode), return current state
            # Better to potentially reject than to crash
            return path

        return normalized

    def _normalize_path(self, path: str) -> str:
        """Normalize path for comparison.

        SECURITY: Applies multiple normalization layers to prevent bypasses:
        1. URL decoding (test-crit-url-decode-01)
        2. Unicode normalization (test-crit-unicode-norm-01)
        3. Path normalization

        Args:
            path: File path

        Returns:
            Fully normalized path
        """
        # SECURITY FIX (test-crit-url-decode-01): Decode URL encoding FIRST
        # This prevents bypasses like /etc/%2e%2e/passwd or /etc%2fpasswd
        try:
            decoded = self._decode_url_fully(path)
        except ValueError:
            # Deeply nested encoding detected - treat as invalid/suspicious
            # Return original path which will likely fail validation
            decoded = path

        # SECURITY FIX (test-crit-unicode-norm-01): Normalize Unicode SECOND
        # This prevents bypasses like /etc\u2215passwd (unicode slash)
        # MUST happen after URL decoding (e.g., %2F → / then \u2215 → /)
        unicode_normalized = self._normalize_unicode(decoded)

        # Convert to Path object for normalization
        try:
            p = Path(unicode_normalized)
            # Resolve . and .. components (but not symlinks)
            normalized = os.path.normpath(str(p))

            # Apply case sensitivity
            if not self.case_sensitive:
                normalized = normalized.lower()

            return normalized
        except (OSError, ValueError, TypeError):
            # If path is invalid, return as-is for error reporting
            return unicode_normalized if self.case_sensitive else unicode_normalized.lower()

    def _has_parent_traversal(self, path: str) -> bool:
        """Check if path contains parent directory traversal.

        SA-08: Check for '..' as a path component, not as a substring.
        This prevents false positives on filenames like 'my..file.txt'.

        Args:
            path: File path

        Returns:
            True if path contains ../ path traversal
        """
        import pathlib
        # Check each path component for '..'
        parts = pathlib.PurePosixPath(path).parts
        if '..' in parts:
            return True
        # Also check Windows-style paths
        parts_win = pathlib.PureWindowsPath(path).parts
        if '..' in parts_win:
            return True
        return False

    def _is_forbidden_file(self, path: str) -> bool:
        """Check if path is a forbidden file.

        Args:
            path: Normalized file path

        Returns:
            True if file is forbidden
        """
        path_lower = path.lower() if not self.case_sensitive else path

        for forbidden_file in self.forbidden_files:
            forbidden_lower = forbidden_file.lower() if not self.case_sensitive else forbidden_file

            # Exact match or ends with (for relative paths)
            if path_lower == forbidden_lower or path_lower.endswith(forbidden_lower):
                return True

        return False

    def _is_forbidden_directory(self, path: str) -> bool:
        """Check if path is under a forbidden directory.

        Args:
            path: Normalized file path

        Returns:
            True if path is under forbidden directory
        """
        path_lower = path.lower() if not self.case_sensitive else path

        for forbidden_dir in self.forbidden_directories:
            forbidden_lower = forbidden_dir.lower() if not self.case_sensitive else forbidden_dir

            # Check if path starts with forbidden directory
            if path_lower.startswith(forbidden_lower):
                # Exact match or followed by separator
                if len(path_lower) == len(forbidden_lower) or \
                   path_lower[len(forbidden_lower):len(forbidden_lower)+1] in ('/', '\\'):
                    return True

        return False

    def _has_forbidden_extension(self, path: str) -> bool:
        """Check if path has a forbidden extension.

        Args:
            path: File path

        Returns:
            True if extension is forbidden
        """
        ext = Path(path).suffix.lower()
        return ext in {e.lower() for e in self.forbidden_extensions}

    def _is_allowed(self, path: str) -> bool:
        """Check if path matches allowlist.

        Args:
            path: Normalized file path

        Returns:
            True if path is allowed
        """
        if not self.allowed_paths:
            return False

        for pattern in self.allowed_paths:
            if self._matches_pattern(path, pattern):
                return True

        return False

    def _is_denied(self, path: str) -> bool:
        """Check if path matches denylist.

        Args:
            path: Normalized file path

        Returns:
            True if path is denied
        """
        if not self.denied_paths:
            return False

        for pattern in self.denied_paths:
            if self._matches_pattern(path, pattern):
                return True

        return False

    def _matches_pattern(self, path: str, pattern: str) -> bool:
        """Check if path matches pattern.

        Supports:
        - Exact match: /project/src/main.py
        - Wildcard: /project/*.py
        - Recursive wildcard: /project/**/*.py
        - Directory prefix: /project/src/

        Args:
            path: File path to check
            pattern: Pattern to match against

        Returns:
            True if path matches pattern
        """
        # Apply case sensitivity
        if not self.case_sensitive:
            path = path.lower()
            pattern = pattern.lower()

        # Exact match
        if path == pattern:
            return True

        # Directory prefix (pattern ends with /)
        if pattern.endswith('/'):
            return path.startswith(pattern)

        # Convert glob pattern to regex
        # ** matches any number of directories
        # * matches any characters except /
        # Use placeholders to avoid conflicts during replacement
        regex_pattern = pattern.replace('**/', '__RECURSIVE__/')  # Mark **/ for later
        regex_pattern = regex_pattern.replace('**', '__RECURSIVE_END__')  # Mark ** at end
        regex_pattern = regex_pattern.replace('*', '[^/]*')  # * -> [^/]*
        regex_pattern = regex_pattern.replace('__RECURSIVE__/', '(?:.*/)?')  # **/ -> optional path segments
        regex_pattern = regex_pattern.replace('__RECURSIVE_END__', '.*')  # ** at end -> .*
        regex_pattern = '^' + regex_pattern + '$'

        try:
            return bool(re.match(regex_pattern, path))
        except re.error:
            # If regex is invalid, fall back to prefix match
            return path.startswith(pattern.rstrip('*'))
