"""
JSON parser tool for parsing, extracting, validating, and formatting JSON data.

Uses stdlib json — no external dependencies required.
"""

import json
import logging
from typing import Any

from temper_ai.tools.base import BaseTool, ToolMetadata, ToolResult

logger = logging.getLogger(__name__)

JSON_OPERATIONS = frozenset({"parse", "extract", "validate", "format"})
JSON_FORMAT_INDENT = 2


def _parse_json(data: str) -> tuple[Any, str | None]:
    """Parse JSON string. Returns (parsed, error)."""
    try:
        return json.loads(data), None
    except json.JSONDecodeError as exc:
        return None, f"Invalid JSON: {exc}"


def _extract_by_path(parsed: Any, path: str) -> tuple[Any, str | None]:
    """
    Extract value using dot-notation + array index path.

    Example: "users.0.name" on {"users": [{"name": "Alice"}]} → "Alice"
    Returns (value, error).
    """
    parts = path.split(".")
    current: Any = parsed
    traversed: list[str] = []

    for part in parts:
        try:
            index = int(part)
            if not isinstance(current, list):
                joined = ".".join(traversed) or "(root)"
                return (
                    None,
                    f"Path segment '{part}' is an array index but '{joined}' is not a list",
                )
            if index < 0 or index >= len(current):
                return (
                    None,
                    f"Array index {index} is out of range (length: {len(current)})",
                )
            current = current[index]
        except ValueError:
            if not isinstance(current, dict):
                joined = ".".join(traversed) or "(root)"
                return (
                    None,
                    f"Path segment '{part}' expects a dict but '{joined}' is not a dict",
                )
            if part not in current:
                return None, f"Key '{part}' not found"
            current = current[part]
        traversed.append(part)

    return current, None


def _validate_json(data: str, schema: dict[str, Any] | None) -> tuple[bool, str | None]:
    """
    Validate that data is valid JSON and optionally check required keys.

    Returns (is_valid, error).
    """
    parsed, parse_error = _parse_json(data)
    if parse_error:
        return False, parse_error

    if schema and isinstance(schema, dict):
        required_keys: list[str] | Any = schema.get("required", [])
        if isinstance(required_keys, list) and isinstance(parsed, dict):
            missing = [k for k in required_keys if k not in parsed]
            if missing:
                return False, f"Missing required keys: {missing}"

    return True, None


class JSONParserTool(BaseTool):
    """
    JSON parser tool for parsing, extracting, validating, and formatting JSON.

    Operations:
    - parse: Parse a JSON string into a Python object
    - extract: Extract a nested value using dot-notation path
    - validate: Check if the data is valid JSON (optionally check required keys)
    - format: Pretty-print JSON with indentation
    """

    def get_metadata(self) -> ToolMetadata:
        """Return JSON parser tool metadata."""
        return ToolMetadata(
            name="JSONParser",
            description=(
                "Parses, extracts, validates, and formats JSON data. "
                "Supports dot-notation path extraction (e.g., 'users.0.name')."
            ),
            version="1.0",
            category="utility",
            requires_network=False,
            requires_credentials=False,
            modifies_state=False,
        )

    def get_parameters_schema(self) -> dict[str, Any]:
        """Return JSON schema for JSON parser parameters."""
        return {
            "type": "object",
            "properties": {
                "data": {"type": "string", "description": "JSON string to operate on"},
                "operation": {
                    "type": "string",
                    "description": "Operation: parse | extract | validate | format",
                },
                "path": {
                    "type": "string",
                    "description": "Dot-notation path for extract operation (e.g., 'users.0.name')",
                },
                "schema": {
                    "type": "object",
                    "description": "Optional schema for validate operation (supports 'required' key list)",
                },
            },
            "required": ["data", "operation"],
        }

    def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the JSON parser operation."""
        data = kwargs.get("data", "")
        operation = kwargs.get("operation", "")

        if not data or not isinstance(data, str):
            return ToolResult(success=False, error="data must be a non-empty string")

        if operation not in JSON_OPERATIONS:
            return ToolResult(
                success=False,
                error=f"Invalid operation '{operation}'. Must be one of: {sorted(JSON_OPERATIONS)}",
            )

        dispatch = {
            "parse": self._op_parse,
            "extract": self._op_extract,
            "validate": self._op_validate,
            "format": self._op_format,
        }
        return dispatch[operation](data, kwargs)

    def _op_parse(self, data: str, kwargs: dict[str, Any]) -> ToolResult:
        """Execute parse operation."""
        parsed, error = _parse_json(data)
        if error:
            return ToolResult(success=False, error=error)
        return ToolResult(success=True, result=parsed)

    def _op_extract(self, data: str, kwargs: dict[str, Any]) -> ToolResult:
        """Execute extract operation."""
        path = kwargs.get("path")
        if not path or not isinstance(path, str):
            return ToolResult(
                success=False, error="path is required for extract operation"
            )
        parsed, error = _parse_json(data)
        if error:
            return ToolResult(success=False, error=error)
        value, extract_error = _extract_by_path(parsed, path)
        if extract_error:
            return ToolResult(success=False, error=extract_error)
        return ToolResult(success=True, result=value, metadata={"path": path})

    def _op_validate(self, data: str, kwargs: dict[str, Any]) -> ToolResult:
        """Execute validate operation."""
        schema = kwargs.get("schema")
        schema_dict = schema if isinstance(schema, dict) else None
        is_valid, error = _validate_json(data, schema_dict)
        return ToolResult(
            success=is_valid,
            result={"valid": is_valid},
            error=error,
        )

    def _op_format(self, data: str, kwargs: dict[str, Any]) -> ToolResult:
        """Execute format operation."""
        parsed, error = _parse_json(data)
        if error:
            return ToolResult(success=False, error=error)
        formatted = json.dumps(parsed, indent=JSON_FORMAT_INDENT)
        return ToolResult(success=True, result=formatted)
