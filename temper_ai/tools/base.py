"""
Base class for all tools.

Defines the interface that all tools must implement.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from pydantic import BaseModel, Field, ValidationError

from temper_ai.shared.constants.limits import MAX_LONG_STRING_LENGTH, MAX_TEXT_LENGTH

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Module-level schema utilities (kept out of BaseTool to stay under
# the 20-method god-class threshold).
# ------------------------------------------------------------------


def _pydantic_to_llm_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Convert a Pydantic ``model_json_schema()`` to LLM function-calling format.

    Strips Pydantic noise (``title``, ``$defs``, root ``description``),
    simplifies ``anyOf`` for Optional fields, and resolves ``$ref``.
    """
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})
    cleaned: dict[str, Any] = {}

    for key, value in raw.items():
        if key in ("title", "description"):
            continue
        if key == "properties":
            cleaned["properties"] = {
                name: _clean_schema_property(prop, defs) for name, prop in value.items()
            }
        else:
            cleaned[key] = value

    return cleaned


def _clean_schema_property(
    prop: dict[str, Any], defs: dict[str, Any]
) -> dict[str, Any]:
    """Clean a single property schema node for LLM consumption."""
    result = dict(prop)

    # Resolve $ref
    if "$ref" in result:
        ref_name = result["$ref"].rsplit("/", 1)[-1]
        if ref_name in defs:
            resolved = dict(defs[ref_name])
            for key in ("description", "default"):
                if key in result:
                    resolved[key] = result[key]
            result = resolved

    # Simplify anyOf for Optional types (pick non-null branch)
    if "anyOf" in result:
        non_null = [t for t in result["anyOf"] if t != {"type": "null"}]
        if len(non_null) == 1:
            outer = {k: v for k, v in result.items() if k != "anyOf"}
            result = {**non_null[0], **outer}

    # Strip Pydantic title noise
    result.pop("title", None)

    # Strip default=null (implicit for optional fields)
    if "default" in result and result["default"] is None:
        del result["default"]

    return result


def _check_json_schema_type(value: Any, expected_type: str) -> bool:
    """Check if value matches expected JSON schema type."""
    type_map: dict[str, type[Any] | tuple[type[Any], ...]] = {
        "string": str,
        "number": (int, float),
        "integer": int,
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    if expected_type not in type_map:
        return True  # Unknown type, skip validation
    expected_python_type = type_map[expected_type]
    return isinstance(value, expected_python_type)


class ToolParameter(BaseModel):
    """Tool parameter definition."""

    name: str
    type: str  # "string", "number", "boolean", "object", "array"
    description: str
    required: bool = True
    default: Any | None = None
    enum: list[Any] | None = None


class ToolMetadata(BaseModel):
    """Tool metadata."""

    name: str
    description: str
    version: str = "1.0"
    category: str | None = None
    requires_network: bool = False
    requires_credentials: bool = False
    modifies_state: bool = True  # Whether tool modifies system state (files, DB, etc.)
    cacheable: bool | None = None  # None = auto-detect from modifies_state


class ToolResult(BaseModel):
    """Structured tool execution result."""

    success: bool
    result: Any | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ParameterValidationResult(BaseModel):
    """Parameter validation result."""

    valid: bool
    errors: list[str] = Field(default_factory=list)

    @property
    def error_message(self) -> str:
        """Get formatted error message."""
        if not self.errors:
            return ""
        return "; ".join(self.errors)


class BaseTool(ABC):
    """
    Abstract base class for all tools.

    All tools must inherit from this class and implement the required methods.
    """

    config_model: ClassVar[type[BaseModel] | None] = None
    params_model: ClassVar[type[BaseModel] | None] = None

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize tool with metadata and optional configuration.

        Args:
            config: Optional configuration dict for tool-specific settings
        """
        self.config = config or {}
        self._metadata = self.get_metadata()
        self._validate_metadata()

    @property
    def name(self) -> str:
        """Get tool name."""
        return self._metadata.name

    @property
    def description(self) -> str:
        """Get tool description."""
        return self._metadata.description

    @property
    def version(self) -> str:
        """Get tool version."""
        return self._metadata.version

    @abstractmethod
    def get_metadata(self) -> ToolMetadata:
        """
        Return tool metadata.

        Returns:
            ToolMetadata with name, description, version, etc.
        """
        pass

    def get_parameters_model(self) -> type[BaseModel] | None:
        """Return Pydantic model class for parameter validation."""
        return self.params_model

    def get_parameters_schema(self) -> dict[str, Any]:
        """Return JSON schema for tool parameters (OpenAI function calling format).

        Auto-derived from ``params_model`` when set. Override for dynamic schemas.
        """
        if self.params_model is not None:
            return _pydantic_to_llm_schema(self.params_model)
        raise NotImplementedError(
            f"{self.__class__.__name__} must set params_model or override get_parameters_schema()"
        )

    def get_config_schema(self) -> dict[str, Any]:
        """Return JSON schema for YAML config overrides.

        Auto-derived from ``config_model`` when set. Override for custom schemas.
        """
        if self.config_model is not None:
            return _pydantic_to_llm_schema(self.config_model)
        return {"type": "object", "properties": {}}

    def validate_config(self) -> ParameterValidationResult:
        """Validate ``self.config`` against ``config_model`` if defined.

        Jinja2 template strings (containing ``{{``) and internal keys
        (starting with ``_``) are excluded from validation.
        """
        if self.config_model is None:
            return ParameterValidationResult(valid=True, errors=[])
        config_to_validate = {
            k: v
            for k, v in self.config.items()
            if not k.startswith("_") and not (isinstance(v, str) and "{{" in v)
        }
        return self._validate_with_pydantic(config_to_validate, self.config_model)

    def get_typed_config(self) -> BaseModel | None:
        """Return a validated Pydantic instance of the tool config, or None."""
        if self.config_model is None:
            return None
        config_clean = {
            k: v
            for k, v in self.config.items()
            if not k.startswith("_") and not (isinstance(v, str) and "{{" in v)
        }
        return self.config_model(**config_clean)

    def get_result_schema(self) -> dict[str, Any] | None:
        """
        Return JSON schema for tool result (optional).

        Provides the LLM with a contract for what the tool output looks like.
        This helps the LLM reliably extract information from tool results,
        especially for tools that return structured data.

        Not required - many tools have simple string results. Override this
        for tools that return complex structured data.

        Returns:
            Dict with JSON Schema for result, or None for simple/unstructured results

        Example (WebScraper returning structured data):
            {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Page title"},
                    "content": {"type": "string", "description": "Extracted text"},
                    "links": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "URLs found on page"
                    },
                    "metadata": {
                        "type": "object",
                        "properties": {
                            "status_code": {"type": "integer"},
                            "content_type": {"type": "string"}
                        }
                    }
                },
                "required": ["title", "content"]
            }

        Example (Calculator returning simple number):
            Return None (or simple schema like {"type": "number"})
        """
        return None

    def safe_execute(self, **kwargs: Any) -> ToolResult:
        """
        Execute tool with guaranteed no-exception contract (M-33).

        Validates parameters before execution and returns validation errors
        as failed ToolResult if validation fails. Catches common exceptions
        (RuntimeError, TypeError, ValueError, OSError, KeyError, AttributeError)
        from execute() and wraps them in a ToolResult with success=False so
        callers never need to handle those exceptions.

        Args:
            **kwargs: Tool-specific parameters

        Returns:
            ToolResult - always returns, never raises
        """
        # Validate parameters
        try:
            validation_result = self.validate_params(kwargs)
            if not validation_result.valid:
                return ToolResult(
                    success=False,
                    error=f"Parameter validation failed: {validation_result.error_message}",
                    metadata={"validation_errors": validation_result.errors},
                )
        except (TypeError, ValueError, KeyError, AttributeError) as e:
            logger.error("Tool %s parameter validation raised: %s", self.name, e)
            return ToolResult(
                success=False,
                error=f"Parameter validation error: {e}",
            )

        # Execute tool -- catch any exception to enforce no-exception contract
        try:
            return self.execute(**kwargs)
        except (
            RuntimeError,
            TypeError,
            ValueError,
            OSError,
            KeyError,
            AttributeError,
        ) as e:
            logger.error("Tool %s execution failed: %s", self.name, e, exc_info=True)
            return ToolResult(
                success=False,
                error=f"Tool execution failed: {e}",
            )

    @abstractmethod
    def execute(self, **kwargs: Any) -> ToolResult:
        """
        Execute the tool with given parameters.

        Args:
            **kwargs: Tool-specific parameters

        Returns:
            ToolResult with success status, result data, and optional error

        Raises:
            Should NOT raise exceptions - wrap in ToolResult with success=False

        Note:
            For automatic parameter validation, use safe_execute() instead.
            This method should be called by safe_execute() after validation.
        """
        pass

    def validate_params(self, params: dict[str, Any]) -> ParameterValidationResult:
        """
        Validate parameters against schema using Pydantic if available.

        Args:
            params: Parameters to validate

        Returns:
            ParameterValidationResult with validation status and error messages
        """
        # Try Pydantic validation first (comprehensive)
        params_model = self.get_parameters_model()
        if params_model is not None:
            return self._validate_with_pydantic(params, params_model)

        # Fall back to JSON Schema validation (basic)
        return self._validate_with_json_schema(params)

    def _validate_with_pydantic(
        self, params: dict[str, Any], model: type[BaseModel]
    ) -> ParameterValidationResult:
        """
        Validate parameters using Pydantic model.

        Provides comprehensive validation including:
        - Type checking
        - Constraints (min/max, length, patterns)
        - Format validation (email, URL, etc.)
        - Custom validators
        - Nested object validation

        Args:
            params: Parameters to validate
            model: Pydantic model class

        Returns:
            ParameterValidationResult with detailed error messages
        """
        try:
            # Validate using Pydantic model
            model(**params)
            return ParameterValidationResult(valid=True, errors=[])
        except ValidationError as e:
            # Extract readable error messages
            errors = []
            for error in e.errors():
                field = ".".join(str(loc) for loc in error["loc"])
                msg = error["msg"]
                errors.append(f"{field}: {msg}")
            return ParameterValidationResult(valid=False, errors=errors)
        except (TypeError, KeyError, AttributeError) as e:
            return ParameterValidationResult(
                valid=False, errors=[f"Validation error: {str(e)}"]
            )

    def _validate_with_json_schema(
        self, params: dict[str, Any]
    ) -> ParameterValidationResult:
        """
        Validate parameters using JSON Schema (fallback for tools without Pydantic models).

        Args:
            params: Parameters to validate

        Returns:
            ParameterValidationResult with error messages
        """
        schema = self.get_parameters_schema()
        required_params = schema.get("required", [])
        properties = schema.get("properties", {})
        errors = []

        # Check required parameters
        for param in required_params:
            if param not in params:
                errors.append(f"{param}: field required")

        # Check parameter types and unknown params
        for param_name, param_value in params.items():
            if param_name not in properties:
                errors.append(f"{param_name}: unexpected parameter")
                continue

            param_schema = properties[param_name]
            expected_type = param_schema.get("type")

            # Basic type checking
            if not _check_json_schema_type(param_value, expected_type):
                errors.append(
                    f"{param_name}: expected {expected_type}, got {type(param_value).__name__}"
                )

        return ParameterValidationResult(valid=len(errors) == 0, errors=errors)

    def _validate_metadata(self) -> None:
        """Validate that metadata is properly set."""
        if not self._metadata.name:
            raise ValueError(f"Tool {self.__class__.__name__} must have a name")
        if not self._metadata.description:
            raise ValueError(f"Tool {self._metadata.name} must have a description")

    def to_llm_schema(self) -> dict[str, Any]:
        """
        Convert tool to LLM function calling schema (OpenAI format).

        Returns:
            Dict in OpenAI function calling format
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.get_parameters_schema(),
            },
        }

    def __repr__(self) -> str:
        """Return string representation of the tool.

        Returns:
            String representation showing tool class name, name, and version
        """
        return (
            f"{self.__class__.__name__}(name='{self.name}', version='{self.version}')"
        )


# Consolidated: canonical definition in src/utils/exceptions.py
from temper_ai.shared.utils.exceptions import SecurityError  # noqa: E402, F401


class ParameterSanitizer:
    """
    Sanitizes tool parameters to prevent security attacks.

    Prevents:
    - Path traversal attacks (../, absolute paths, null bytes)
    - Command injection (shell metacharacters, command substitution)
    - Input validation violations (length, range, type)
    - SQL injection (if applicable)

    Examples:
        >>> sanitizer = ParameterSanitizer()
        >>> safe_path = sanitizer.sanitize_path("../../etc/passwd", "/home/user")
        SecurityError: Path traversal detected

        >>> safe_cmd = sanitizer.sanitize_command("ls; rm -rf /")
        SecurityError: Dangerous character ';' in command
    """

    @staticmethod
    def sanitize_path(path: str, allowed_base: str | None = None) -> str:
        """
        Sanitize file path to prevent traversal attacks.

        Args:
            path: Path to sanitize
            allowed_base: Base directory to restrict paths to

        Returns:
            Sanitized absolute path

        Raises:
            SecurityError: If path contains traversal attempts or null bytes
            ValueError: If path is empty

        Examples:
            >>> sanitizer = ParameterSanitizer()
            >>> sanitizer.sanitize_path("test.txt", "/home/user")
            '/home/user/test.txt'

            >>> sanitizer.sanitize_path("../../../etc/passwd", "/home/user")
            SecurityError: Path traversal detected
        """
        from pathlib import Path

        if not path:
            raise ValueError("Path cannot be empty")

        # Detect null bytes (directory traversal trick)
        if "\x00" in path:
            raise SecurityError("Null bytes not allowed in path")

        # Normalize backslashes to forward slashes for cross-platform consistency
        # (Windows-style paths on Linux would otherwise bypass .. detection)
        normalized_path = path.replace("\\", "/")

        # Block obvious traversal attempts in the original path BEFORE resolving
        # (Check original path because resolve() normalizes away the ..)
        path_parts = Path(normalized_path).parts
        if ".." in path_parts:
            raise SecurityError(f"Path traversal detected: {path} contains '..'")

        # Normalize path to resolve symlinks and .. components
        try:
            normalized = Path(path).resolve()
        except (OSError, RuntimeError) as e:
            raise SecurityError(f"Invalid path: {e}") from e

        # Check if within allowed base directory
        if allowed_base:
            try:
                allowed = Path(allowed_base).resolve()
                # Check if normalized path is within allowed base
                normalized.relative_to(allowed)
            except ValueError as e:
                raise SecurityError(
                    f"Path traversal detected: {path} is outside {allowed_base}"
                ) from e

        return str(normalized)

    # Maximum command length to prevent DoS
    MAX_COMMAND_LENGTH = MAX_LONG_STRING_LENGTH

    @staticmethod
    def _check_dangerous_chars(normalized: str) -> None:
        """Raise SecurityError if command contains shell metacharacters."""
        dangerous_chars = [
            ";",  # Command separator
            "|",  # Pipe
            "&",  # Background/AND
            "$",  # Variable expansion
            "`",  # Command substitution
            "\n",  # Newline injection
            "\r",  # Carriage return
            ">",  # Output redirection
            "<",  # Input redirection
        ]
        for char in dangerous_chars:
            if char in normalized:
                raise SecurityError(
                    f"Dangerous character '{char}' detected in command: "
                    f"{normalized}"
                )

    @staticmethod
    def _check_dangerous_patterns(normalized: str) -> None:
        """Raise SecurityError if command contains injection patterns."""
        import re

        dangerous_patterns = [
            (r"\$\(", "command substitution $()"),
            (r"\$\{", "variable expansion ${}"),
            (r"\{[^}]*,[^}]*\}", "brace expansion"),
            (r"\{[^}]*\.\.[^}]*\}", "brace range expansion"),
            (r"\\[xX][0-9a-fA-F]{2}", "hex escape sequence"),
        ]
        for pattern, description in dangerous_patterns:
            if re.search(pattern, normalized):
                raise SecurityError(
                    f"Dangerous pattern detected ({description}) in command"
                )

    @staticmethod
    def sanitize_command(
        command: str,
        allowed_commands: list[str] | None = None,
        max_length: int | None = None,
    ) -> str:
        """
        Sanitize command to prevent injection attacks.

        WARNING: This function does NOT make shell=True safe.
        ALWAYS use subprocess.run(..., shell=False) with argument lists.

        Applies Unicode NFKC normalization to prevent homoglyph bypass attacks
        before checking for dangerous patterns.

        Args:
            command: Command string to sanitize
            allowed_commands: Optional whitelist of allowed command names
            max_length: Maximum allowed command length

        Returns:
            Sanitized command string (NFKC-normalized)

        Raises:
            SecurityError: If command contains dangerous characters or patterns
            ValueError: If command is empty or exceeds max length

        Examples:
            >>> sanitizer = ParameterSanitizer()
            >>> sanitizer.sanitize_command("ls")
            'ls'

            >>> sanitizer.sanitize_command("ls; rm -rf /")
            SecurityError: Dangerous character ';' in command
        """
        import unicodedata

        if not command:
            raise ValueError("Command cannot be empty")

        # Enforce length limit
        limit = max_length or ParameterSanitizer.MAX_COMMAND_LENGTH
        if len(command) > limit:
            raise ValueError(f"Command too long ({len(command)} > {limit})")

        # Block null bytes before any other processing
        if "\x00" in command:
            raise SecurityError("Null byte detected in command")

        # Normalize Unicode to NFKC to prevent homoglyph attacks
        normalized = unicodedata.normalize("NFKC", command)

        ParameterSanitizer._check_dangerous_chars(normalized)
        ParameterSanitizer._check_dangerous_patterns(normalized)

        # Whitelist validation
        if allowed_commands is not None:
            cmd_name = normalized.split()[0] if normalized.split() else ""
            if cmd_name not in allowed_commands:
                raise SecurityError(
                    f"Command '{cmd_name}' not in allowed list: " f"{allowed_commands}"
                )

        return normalized

    @staticmethod
    def validate_string_length(
        value: str, max_length: int = MAX_TEXT_LENGTH, param_name: str = "parameter"
    ) -> str:
        """
        Validate string length to prevent DoS attacks.

        Args:
            value: String to validate
            max_length: Maximum allowed length
            param_name: Parameter name for error messages

        Returns:
            Original string if valid

        Raises:
            ValueError: If string exceeds max_length

        Examples:
            >>> sanitizer = ParameterSanitizer()
            >>> sanitizer.validate_string_length("test", max_length=100)
            'test'

            >>> sanitizer.validate_string_length("x" * 1000, max_length=100)
            ValueError: String too long
        """
        if not isinstance(value, str):
            raise TypeError(
                f"{param_name}: expected string, got {type(value).__name__}"
            )

        if len(value) > max_length:
            raise ValueError(
                f"{param_name}: string too long ({len(value)} > {max_length})"
            )

        return value

    @staticmethod
    def validate_integer_range(
        value: int,
        minimum: int | None = None,
        maximum: int | None = None,
        param_name: str = "parameter",
    ) -> int:
        """
        Validate integer is within acceptable range.

        Args:
            value: Integer to validate
            minimum: Minimum allowed value
            maximum: Maximum allowed value
            param_name: Parameter name for error messages

        Returns:
            Original integer if valid

        Raises:
            ValueError: If integer is out of range
            TypeError: If value is not an integer

        Examples:
            >>> sanitizer = ParameterSanitizer()
            >>> sanitizer.validate_integer_range(50, minimum=0, maximum=100)
            50

            >>> sanitizer.validate_integer_range(-1, minimum=0, maximum=100)
            ValueError: Value below minimum
        """
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(
                f"{param_name}: expected integer, got {type(value).__name__}"
            )

        if minimum is not None and value < minimum:
            raise ValueError(f"{param_name}: value {value} below minimum {minimum}")

        if maximum is not None and value > maximum:
            raise ValueError(f"{param_name}: value {value} above maximum {maximum}")

        return value

    @staticmethod
    def sanitize_sql_input(value: Any, param_name: str = "parameter") -> Any:
        """
        Sanitize input for SQL to prevent injection.

        NOTE: This is a basic sanitizer. ALWAYS use parameterized queries
        as the primary defense. This is defense-in-depth only.

        Args:
            value: Input string to sanitize
            param_name: Parameter name for error messages

        Returns:
            Original string if no SQL keywords detected

        Raises:
            SecurityError: If SQL keywords or dangerous patterns detected

        Examples:
            >>> sanitizer = ParameterSanitizer()
            >>> sanitizer.sanitize_sql_input("user123")
            'user123'

            >>> sanitizer.sanitize_sql_input("user' OR '1'='1")
            SecurityError: SQL injection attempt detected
        """
        if not isinstance(value, str):
            return value

        # Detect common SQL injection patterns
        dangerous_patterns = [
            "';",  # Statement terminator
            "--",  # SQL comment
            "/*",  # Block comment start
            "*/",  # Block comment end
            "xp_",  # SQL Server extended procedures
            "sp_",  # SQL Server stored procedures
            "UNION",  # UNION-based injection
            "SELECT",  # SELECT injection
            "INSERT",  # INSERT injection
            "UPDATE",  # UPDATE injection
            "DELETE",  # DELETE injection
            "DROP",  # DROP injection
            "CREATE",  # CREATE injection
            "ALTER",  # ALTER injection
            "EXEC",  # EXEC injection
            "EXECUTE",  # EXECUTE injection
        ]

        value_upper = value.upper()
        for pattern in dangerous_patterns:
            if pattern in value_upper:
                raise SecurityError(
                    f"{param_name}: SQL injection attempt detected (pattern: {pattern})"
                )

        # Detect single quotes followed by OR/AND
        if "'" in value and (" OR " in value_upper or " AND " in value_upper):
            raise SecurityError(
                f"{param_name}: SQL injection attempt detected (quote + boolean)"
            )

        return value
