"""Helper functions for FileAccessPolicy.

Extracted from FileAccessPolicy to keep the class below 500 lines.
These are internal implementation details and should not be used directly.
"""

import os
import pathlib
import re
import unicodedata
import urllib.parse
from pathlib import Path
from typing import Any

from temper_ai.safety.constants import PATH_KEY, PATHS_KEY


def extract_paths(action: dict[str, Any]) -> list[str]:
    """Extract file paths from action.

    Args:
        action: Action dictionary

    Returns:
        List of file paths
    """
    paths = []

    # Single path
    if PATH_KEY in action:
        paths.append(str(action[PATH_KEY]))

    # Multiple paths
    if PATHS_KEY in action and isinstance(action[PATHS_KEY], list):
        paths.extend([str(p) for p in action[PATHS_KEY]])

    # Source/destination paths (for copy/move operations)
    if "source" in action:
        paths.append(str(action["source"]))
    if "destination" in action:
        paths.append(str(action["destination"]))

    return paths


def decode_url_fully(path: str, max_iterations: int = 10) -> str:
    """Recursively decode URL encoding until fully decoded.

    SECURITY FIX (test-crit-url-decode-01): Prevent URL encoding bypasses.

    Handles:
    - Single encoding: %2e%2e -> ..
    - Double encoding: %252e -> %2e -> .
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
    """
    decoded = path
    for _i in range(max_iterations):
        previous = decoded
        try:
            decoded = urllib.parse.unquote(decoded, errors="strict")
        except (UnicodeDecodeError, ValueError):
            return path

        if decoded == previous:
            return decoded

    raise ValueError(
        f"URL decoding did not stabilize after {max_iterations} iterations. "
        f"Path may contain deeply nested encoding: {path[:100]}"
    )


def normalize_unicode(path: str) -> str:
    """Normalize Unicode to prevent bypass attacks.

    SECURITY FIX (test-crit-unicode-norm-01): Prevent Unicode bypass attacks.

    Uses NFKC normalization plus manual replacement of dangerous lookalikes that
    NFKC doesn't handle (U+2215, U+2044, etc.).

    Args:
        path: Path to normalize

    Returns:
        Normalized path with dangerous Unicode converted to ASCII
    """
    # Strip BOM (Byte Order Mark) if present at start
    if path and path[0] == "\ufeff":
        path = path[1:]

    # Remove zero-width characters (often used in obfuscation)
    zero_width_chars = [
        "\u200b",  # ZERO WIDTH SPACE
        "\u200c",  # ZERO WIDTH NON-JOINER
        "\u200d",  # ZERO WIDTH JOINER
        "\ufeff",  # ZERO WIDTH NO-BREAK SPACE (BOM)
        "\u2060",  # WORD JOINER
    ]
    for char in zero_width_chars:
        path = path.replace(char, "")

    # CRITICAL: Manually replace dangerous Unicode lookalikes that NFKC doesn't normalize
    dangerous_lookalikes = {
        "\u2215": "/",  # DIVISION SLASH -> SOLIDUS
        "\u2044": "/",  # FRACTION SLASH -> SOLIDUS
        "\u29f8": "/",  # BIG SOLIDUS -> SOLIDUS
        "\u2024": ".",  # ONE DOT LEADER -> PERIOD
        "\u2025": "..",  # TWO DOT LEADER -> TWO PERIODS
        "\u2026": "...",  # HORIZONTAL ELLIPSIS -> THREE PERIODS
        "\u00b7": ".",  # MIDDLE DOT -> PERIOD
        "\u2027": ".",  # HYPHENATION POINT -> PERIOD
        "\u0338": "",  # COMBINING LONG SOLIDUS OVERLAY -> remove
    }
    for dangerous, safe in dangerous_lookalikes.items():
        path = path.replace(dangerous, safe)

    # Apply NFKC normalization
    try:
        normalized = unicodedata.normalize("NFKC", path)
    except (UnicodeError, ValueError):
        return path

    return normalized


def normalize_path(path: str, case_sensitive: bool) -> str:
    """Normalize path for comparison.

    SECURITY: Applies multiple normalization layers to prevent bypasses:
    1. URL decoding (test-crit-url-decode-01)
    2. Unicode normalization (test-crit-unicode-norm-01)
    3. Path normalization

    Args:
        path: File path
        case_sensitive: Whether path matching is case-sensitive

    Returns:
        Fully normalized path
    """
    try:
        decoded = decode_url_fully(path)
    except ValueError:
        decoded = path

    unicode_normalized = normalize_unicode(decoded)

    try:
        p = Path(unicode_normalized)
        normalized = os.path.normpath(str(p))

        if not case_sensitive:
            normalized = normalized.lower()

        return normalized
    except (OSError, ValueError, TypeError):
        return unicode_normalized if case_sensitive else unicode_normalized.lower()


def has_parent_traversal(path: str) -> bool:
    """Check if path contains parent directory traversal.

    SA-08: Check for '..' as a path component, not as a substring.

    Args:
        path: File path

    Returns:
        True if path contains ../ path traversal
    """
    parts = pathlib.PurePosixPath(path).parts
    if ".." in parts:
        return True
    parts_win = pathlib.PureWindowsPath(path).parts
    if ".." in parts_win:
        return True
    return False


def is_forbidden_file(
    path: str, forbidden_files: set[str], case_sensitive: bool
) -> bool:
    """Check if path is a forbidden file.

    Args:
        path: Normalized file path
        forbidden_files: Set of forbidden file paths
        case_sensitive: Whether matching is case-sensitive

    Returns:
        True if file is forbidden
    """
    path_lower = path.lower() if not case_sensitive else path

    for forbidden_file in forbidden_files:
        forbidden_lower = (
            forbidden_file.lower() if not case_sensitive else forbidden_file
        )
        if path_lower == forbidden_lower or path_lower.endswith(forbidden_lower):
            return True

    return False


def is_forbidden_directory(
    path: str, forbidden_directories: set[str], case_sensitive: bool
) -> bool:
    """Check if path is under a forbidden directory.

    Args:
        path: Normalized file path
        forbidden_directories: Set of forbidden directory paths
        case_sensitive: Whether matching is case-sensitive

    Returns:
        True if path is under forbidden directory
    """
    path_lower = path.lower() if not case_sensitive else path

    for forbidden_dir in forbidden_directories:
        forbidden_lower = forbidden_dir.lower() if not case_sensitive else forbidden_dir
        if path_lower.startswith(forbidden_lower):
            if len(path_lower) == len(forbidden_lower) or path_lower[
                len(forbidden_lower) : len(forbidden_lower) + 1
            ] in ("/", "\\"):
                return True

    return False


def has_forbidden_extension(path: str, forbidden_extensions: set[str]) -> bool:
    """Check if path has a forbidden extension.

    Args:
        path: File path
        forbidden_extensions: Set of forbidden extensions

    Returns:
        True if extension is forbidden
    """
    ext = Path(path).suffix.lower()
    return ext in {e.lower() for e in forbidden_extensions}


def matches_pattern(path: str, pattern: str, case_sensitive: bool) -> bool:
    """Check if path matches pattern.

    Supports:
    - Exact match: /project/src/main.py
    - Wildcard: /project/*.py
    - Recursive wildcard: /project/**/*.py
    - Directory prefix: /project/src/

    Args:
        path: File path to check
        pattern: Pattern to match against
        case_sensitive: Whether matching is case-sensitive

    Returns:
        True if path matches pattern
    """
    if not case_sensitive:
        path = path.lower()
        pattern = pattern.lower()

    if path == pattern:
        return True

    if pattern.endswith("/"):
        return path.startswith(pattern)

    regex_pattern = pattern.replace("**/", "__RECURSIVE__/")
    regex_pattern = regex_pattern.replace("**", "__RECURSIVE_END__")
    regex_pattern = regex_pattern.replace("*", "[^/]*")
    regex_pattern = regex_pattern.replace("__RECURSIVE__/", "(?:.*/)?")
    regex_pattern = regex_pattern.replace("__RECURSIVE_END__", ".*")
    regex_pattern = "^" + regex_pattern + "$"

    try:
        return bool(re.match(regex_pattern, path))
    except re.error:
        return path.startswith(pattern.rstrip("*"))


def is_allowed(path: str, allowed_paths: list[str], case_sensitive: bool) -> bool:
    """Check if path matches allowlist.

    Args:
        path: Normalized file path
        allowed_paths: List of allowed path patterns
        case_sensitive: Whether matching is case-sensitive

    Returns:
        True if path is allowed
    """
    if not allowed_paths:
        return False

    for pattern in allowed_paths:
        if matches_pattern(path, pattern, case_sensitive):
            return True

    return False


def is_denied(path: str, denied_paths: list[str], case_sensitive: bool) -> bool:
    """Check if path matches denylist.

    Args:
        path: Normalized file path
        denied_paths: List of denied path patterns
        case_sensitive: Whether matching is case-sensitive

    Returns:
        True if path is denied
    """
    if not denied_paths:
        return False

    for pattern in denied_paths:
        if matches_pattern(path, pattern, case_sensitive):
            return True

    return False
