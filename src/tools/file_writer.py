"""
FileWriter tool for safely writing content to files.

Includes safety checks for path traversal and dangerous system paths.
Uses centralized path_safety module for validation.
"""
from pathlib import Path
from typing import Any, Dict, Optional, Set

from src.tools.base import BaseTool, ToolMetadata, ToolResult
from src.tools.constants import MAX_FILE_SIZE as _MAX_FILE_SIZE
from src.utils.path_safety import PathSafetyError, PathSafetyValidator

# Dangerous file extensions
FORBIDDEN_EXTENSIONS: Set[str] = {
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".sh",
    ".bash",
    ".zsh",
    ".bat",
    ".cmd",
    ".ps1",
}


class FileWriter(BaseTool):
    """
    Safe file writer tool.

    Features:
    - Write content to specified file path
    - Create parent directories if needed
    - Safety checks for path traversal
    - Prevent writing to dangerous system paths
    - Prevent writing dangerous file types
    - Overwrite protection (requires explicit confirmation)

    Safety:
    - Path traversal protection (no ../ escaping)
    - Forbidden path blocking (/etc, /sys, etc.)
    - Forbidden extension blocking (.exe, .sh, etc.)
    - File size limits
    - Uses centralized path_safety module
    """

    MAX_FILE_SIZE = _MAX_FILE_SIZE  # 10MB limit

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize FileWriter with path safety validator.

        Args:
            config: Optional configuration dict (currently unused)
        """
        super().__init__(config)
        self.path_validator = PathSafetyValidator()

    def get_metadata(self) -> ToolMetadata:
        """Return file writer tool metadata."""
        return ToolMetadata(
            name="FileWriter",
            description="Writes content to a file. Creates parent directories if needed. Includes safety checks to prevent writing to dangerous paths.",
            version="1.0",
            category="file_system",
            requires_network=False,
            requires_credentials=False,
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        """Return JSON schema for file writer parameters."""
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to file to write (absolute or relative to current directory)"
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to file"
                },
                "overwrite": {
                    "type": "boolean",
                    "description": "Whether to overwrite existing file (default: false)",
                    "default": False
                },
                "create_dirs": {
                    "type": "boolean",
                    "description": "Whether to create parent directories if they don't exist (default: true)",
                    "default": True
                }
            },
            "required": ["file_path", "content"]
        }

    def execute(self, **kwargs: Any) -> ToolResult:
        """
        Execute file writer with given parameters.

        Args:
            file_path: Path to file to write
            content: Content to write
            overwrite: Whether to overwrite existing file (default: False)
            create_dirs: Whether to create parent directories (default: True)

        Returns:
            ToolResult with success status and path written
        """
        file_path = kwargs.get("file_path")
        content = kwargs.get("content")
        overwrite = kwargs.get("overwrite", False)
        create_dirs = kwargs.get("create_dirs", True)

        # Validate inputs
        if not file_path or not isinstance(file_path, str):
            return ToolResult(
                success=False,
                error="file_path must be a non-empty string"
            )

        if content is None or not isinstance(content, str):
            return ToolResult(
                success=False,
                error="content must be a string"
            )

        # Check content size
        if len(content.encode('utf-8')) > self.MAX_FILE_SIZE:
            return ToolResult(
                success=False,
                error=f"Content exceeds maximum size of {self.MAX_FILE_SIZE} bytes"
            )

        try:
            # Validate path safety using centralized validator
            try:
                path = self.path_validator.validate_write(
                    Path(file_path),
                    allow_overwrite=overwrite,
                    allow_create_parents=create_dirs
                )
            except PathSafetyError as e:
                return ToolResult(
                    success=False,
                    error=f"Path safety validation failed: {str(e)}"
                )

            # Check if path is a directory
            if path.exists() and path.is_dir():
                return ToolResult(
                    success=False,
                    error=f"Cannot write to directory: {path}"
                )

            # Check for forbidden extensions
            if path.suffix.lower() in FORBIDDEN_EXTENSIONS:
                return ToolResult(
                    success=False,
                    error=f"Cannot write file with forbidden extension: {path.suffix}"
                )

            # Create parent directories if needed
            if create_dirs:
                path.parent.mkdir(parents=True, exist_ok=True)
            elif not path.parent.exists():
                return ToolResult(
                    success=False,
                    error=f"Parent directory does not exist: {path.parent}. Set create_dirs=true to create it."
                )

            # TO-06: Check existence before write, not after
            existed = path.exists()

            # Write file
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)

            return ToolResult(
                success=True,
                result=str(path),
                metadata={
                    "file_path": str(path),
                    "size_bytes": len(content.encode('utf-8')),
                    "overwritten": existed
                }
            )

        except PermissionError:
            return ToolResult(
                success=False,
                error=f"Permission denied: {file_path}"
            )

        except OSError as e:
            return ToolResult(
                success=False,
                error=f"OS error: {str(e)}"
            )

        except (TypeError, ValueError, UnicodeError) as e:
            return ToolResult(
                success=False,
                error=f"Unexpected error: {str(e)}"
            )

