"""
FileWriter tool for safely writing content to files.

Includes safety checks for path traversal and dangerous system paths.
Uses centralized path_safety module for validation.
"""

import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from temper_ai.shared.utils.path_safety import PathSafetyError, PathSafetyValidator
from temper_ai.tools.base import (
    BaseTool,
    ParameterValidationResult,
    ToolMetadata,
    ToolResult,
)
from temper_ai.tools.constants import FILE_ENCODING_UTF8
from temper_ai.tools.constants import MAX_FILE_SIZE as _MAX_FILE_SIZE

logger = logging.getLogger(__name__)

# Dangerous file extensions
FORBIDDEN_EXTENSIONS: set[str] = {
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


class FileWriterParams(BaseModel):
    """Call-time parameters for the FileWriter tool."""

    file_path: str = Field(
        description="Path to file to write (absolute or relative to current directory)",
    )
    content: str = Field(description="Content to write to file")
    overwrite: bool = Field(
        default=False,
        description="Whether to overwrite existing file (default: false)",
    )
    create_dirs: bool = Field(
        default=True,
        description="Whether to create parent directories if they don't exist (default: true)",
    )


class FileWriterConfig(BaseModel):
    """YAML config schema for the FileWriter tool."""

    allowed_root: str | None = Field(
        default=None,
        description="Root directory for file writes. Files can only be written within this directory tree.",
    )


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

    params_model = FileWriterParams
    config_model = FileWriterConfig

    MAX_FILE_SIZE = _MAX_FILE_SIZE  # 10MB limit

    # LLMs commonly use these aliases instead of canonical parameter names
    _PARAM_ALIASES: dict[str, str] = {
        "path": "file_path",
        "filepath": "file_path",
        "filename": "file_path",
        "file": "file_path",
        "contents": "content",
        "text": "content",
        "data": "content",
    }

    @staticmethod
    def _normalize_params(params: dict[str, Any]) -> dict[str, Any]:
        """Normalize common LLM parameter aliases to canonical names."""
        normalized = {}
        for key, value in params.items():
            canonical = FileWriter._PARAM_ALIASES.get(key, key)
            # Don't overwrite canonical key if already present
            if canonical not in normalized:
                normalized[canonical] = value
            elif key == canonical:
                # Canonical key wins over previously-mapped alias
                normalized[canonical] = value
        return normalized

    def validate_params(self, params: dict[str, Any]) -> ParameterValidationResult:
        """Validate parameters, normalizing common LLM aliases first."""
        return super().validate_params(self._normalize_params(params))

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize FileWriter with path safety validator.

        Args:
            config: Optional configuration dict with keys:
                - allowed_root: Root directory to constrain writes to.
                    If set, all file paths must resolve within this directory.
                    Supports workspace isolation for multi-agent workflows.
        """
        super().__init__(config)
        self._configured_root: str | None = (self.config or {}).get("allowed_root")
        self.path_validator = PathSafetyValidator(
            allowed_root=Path(self._configured_root) if self._configured_root else None
        )

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

    def _sync_config(self) -> None:
        """Sync allowed_root from config (may be updated by agent)."""
        current_root = (self.config or {}).get("allowed_root")
        if current_root != self._configured_root:
            logger.info(
                "FileWriter allowed_root changed: %s -> %s",
                self._configured_root,
                current_root,
            )
            self._configured_root = current_root
            self.path_validator = PathSafetyValidator(
                allowed_root=Path(current_root) if current_root else None
            )

    def _validate_inputs(self, file_path: Any, content: Any) -> ToolResult | None:
        """Validate file_path and content inputs. Returns error or None."""
        if not file_path or not isinstance(file_path, str):
            return ToolResult(
                success=False, error="file_path must be a non-empty string"
            )

        if content is None or not isinstance(content, str):
            return ToolResult(success=False, error="content must be a string")

        # Check content size
        if len(content.encode(FILE_ENCODING_UTF8)) > self.MAX_FILE_SIZE:
            return ToolResult(
                success=False,
                error=f"Content exceeds maximum size of {self.MAX_FILE_SIZE} bytes",
            )

        return None

    def _validate_path(
        self, file_path: str, overwrite: bool, create_dirs: bool
    ) -> tuple[Path | None, ToolResult | None]:
        """Validate path safety. Returns (path, None) or (None, error)."""
        try:
            path = self.path_validator.validate_write(
                Path(file_path),
                allow_overwrite=overwrite,
                allow_create_parents=create_dirs,
            )
        except PathSafetyError as e:
            return None, ToolResult(
                success=False, error=f"Path safety validation failed: {str(e)}"
            )

        # Check if path is a directory
        if path.exists() and path.is_dir():
            return None, ToolResult(
                success=False, error=f"Cannot write to directory: {path}"
            )

        # Check for forbidden extensions
        if path.suffix.lower() in FORBIDDEN_EXTENSIONS:
            return None, ToolResult(
                success=False,
                error=f"Cannot write file with forbidden extension: {path.suffix}",
            )

        return path, None

    def _prepare_directory(self, path: Path, create_dirs: bool) -> ToolResult | None:
        """Create parent directories if needed. Returns error or None."""
        if create_dirs:
            path.parent.mkdir(parents=True, exist_ok=True)
        elif not path.parent.exists():
            return ToolResult(
                success=False,
                error=f"Parent directory does not exist: {path.parent}. Set create_dirs=true to create it.",
            )
        return None

    def _do_write(
        self,
        file_path: str,
        content: str,
        overwrite: bool,
        create_dirs: bool,
    ) -> ToolResult:
        """Validate path, prepare directory, and write content to disk.

        This is the inner write logic extracted from ``execute()`` to keep
        the public method concise.  All OS-level errors are caught and
        returned as failed ``ToolResult`` instances.
        """
        try:
            path, error_result = self._validate_path(file_path, overwrite, create_dirs)
            if error_result is not None:
                return error_result
            if path is None:
                return ToolResult(success=False, error="Path validation failed")

            error_result = self._prepare_directory(path, create_dirs)
            if error_result is not None:
                return error_result

            existed = path.exists()

            if content is None:
                return ToolResult(success=False, error="Content is required")
            with open(path, "w", encoding=FILE_ENCODING_UTF8) as f:
                f.write(content)

            return ToolResult(
                success=True,
                result=str(path),
                metadata={
                    "file_path": str(path),
                    "size_bytes": len(content.encode(FILE_ENCODING_UTF8)),
                    "overwritten": existed,
                },
            )
        except PermissionError:
            return ToolResult(success=False, error=f"Permission denied: {file_path}")
        except OSError as e:
            return ToolResult(success=False, error=f"OS error: {str(e)}")
        except (TypeError, ValueError, UnicodeError) as e:
            return ToolResult(success=False, error=f"Unexpected error: {str(e)}")

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
        kwargs = self._normalize_params(kwargs)
        file_path = kwargs.get("file_path")
        content = kwargs.get("content")
        overwrite = kwargs.get("overwrite", False)
        create_dirs = kwargs.get("create_dirs", True)

        self._sync_config()

        error_result = self._validate_inputs(file_path, content)
        if error_result is not None:
            return error_result
        if not isinstance(file_path, str):
            return ToolResult(success=False, error="file_path must be a string")

        # Resolve relative paths against allowed_root (LLMs often omit the prefix)
        if self._configured_root and not Path(file_path).is_absolute():
            file_path = str(Path(self._configured_root) / file_path)

        if not isinstance(content, str):
            return ToolResult(success=False, error="content must be a string")
        return self._do_write(file_path, content, overwrite, create_dirs)
