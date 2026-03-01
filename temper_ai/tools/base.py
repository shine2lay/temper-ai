"""
Base class for all tools.

Defines the interface that all tools must implement.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from pydantic import BaseModel, Field, ValidationError

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


def _resolve_schema_ref(
    prop: dict[str, Any], defs: dict[str, Any]
) -> dict[str, Any]:  # noqa: radon
    """Resolve a $ref to its definition, preserving description/default overrides."""
    ref_name = prop["$ref"].rsplit("/", 1)[-1]
    if ref_name not in defs:
        return prop
    resolved = dict(defs[ref_name])
    for key in ("description", "default"):
        if key in prop:
            resolved[key] = prop[key]
    return resolved


def _simplify_schema_any_of(prop: dict[str, Any]) -> dict[str, Any]:
    """Simplify anyOf for Optional types by picking the single non-null branch."""
    non_null = [t for t in prop["anyOf"] if t != {"type": "null"}]
    if len(non_null) != 1:
        return prop
    outer = {k: v for k, v in prop.items() if k != "anyOf"}
    return {**non_null[0], **outer}


def _clean_schema_property(
    prop: dict[str, Any], defs: dict[str, Any]
) -> dict[str, Any]:
    """Clean a single property schema node for LLM consumption."""
    result = dict(prop)

    if "$ref" in result:
        result = _resolve_schema_ref(result, defs)

    if "anyOf" in result:
        result = _simplify_schema_any_of(result)

    result.pop("title", None)

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

    @classmethod
    def get_parameters_schema_cls(cls) -> dict[str, Any]:
        """Return JSON schema from class-level ``params_model`` without instantiation.

        Only works when ``params_model`` is set. For tools with dynamic schemas
        (overriding ``get_parameters_schema``), use an instance instead.
        """
        if cls.params_model is not None:
            return _pydantic_to_llm_schema(cls.params_model)
        raise NotImplementedError(
            f"{cls.__name__} must set params_model or use an instance for get_parameters_schema()"
        )

    def get_parameters_schema(self) -> dict[str, Any]:
        """Return JSON schema for tool parameters (OpenAI function calling format).

        Auto-derived from ``params_model`` when set. Override for dynamic schemas.
        """
        if self.params_model is not None:
            return _pydantic_to_llm_schema(self.params_model)
        raise NotImplementedError(
            f"{self.__class__.__name__} must set params_model or override get_parameters_schema()"
        )

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
