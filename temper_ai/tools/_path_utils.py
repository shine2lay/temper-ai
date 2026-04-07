"""Shared path validation for file tools (FileWriter, FileEdit, FileAppend)."""

from pathlib import Path

_FORBIDDEN_PREFIXES = (
    "/etc", "/sys", "/proc", "/dev", "/boot", "/sbin",
    "/usr/sbin", "/var/run", "/var/lock",
)


def validate_file_path(file_path: str, allowed_root: str | None = None) -> Path:
    """Validate and resolve a file path. Raises ValueError on violations.

    Checks:
    - No null bytes
    - Not in forbidden system directories
    - Within allowed_root if specified (with correct prefix matching)
    """
    if "\x00" in file_path:
        raise ValueError("Path contains null byte")

    resolved = Path(file_path).resolve()
    resolved_str = str(resolved)

    for prefix in _FORBIDDEN_PREFIXES:
        if resolved_str == prefix or resolved_str.startswith(prefix + "/"):
            raise ValueError(f"Writing to {prefix} is forbidden")

    if allowed_root:
        root = Path(allowed_root).resolve()
        root_str = str(root)
        if resolved_str != root_str and not resolved_str.startswith(root_str + "/"):
            raise ValueError(
                f"Path '{resolved}' is outside allowed root '{root}'"
            )

    return resolved
