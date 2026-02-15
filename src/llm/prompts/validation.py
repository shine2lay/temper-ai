"""
Template variable validation for PromptEngine.

Provides type safety and size validation for template variables to prevent
Server-Side Template Injection (SSTI) attacks.
"""
from typing import Any, Dict

from src.shared.constants.limits import MULTIPLIER_MEDIUM, MULTIPLIER_SMALL

ERROR_MSG_VARIABLE_PREFIX = "Variable '"
from src.shared.constants.sizes import SIZE_100MB
from src.shared.utils.exceptions import AgentError, ErrorCode


class PromptRenderError(AgentError):
    """Raised when prompt rendering fails."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(
            message=message,
            error_code=ErrorCode.AGENT_EXECUTION_ERROR,
            **kwargs
        )


def _is_safe_template_value(value: Any) -> bool:
    """Check whether a value is safe to pass into Jinja2 templates.

    Uses an allowlist approach: only serializable primitive types, lists,
    tuples, and dicts (with string keys) are permitted.  Functions, classes,
    modules, and other arbitrary objects are rejected.

    Args:
        value: The value to check.

    Returns:
        True if the value (and all nested children) contains only safe types.
    """
    if value is None:
        return True
    if isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, (list, tuple)):
        return all(_is_safe_template_value(v) for v in value)
    if isinstance(value, dict):
        return all(
            isinstance(k, str) and _is_safe_template_value(v)
            for k, v in value.items()
        )
    return False


class TemplateVariableValidator:
    """Validates template variables for type safety and size limits.

    Prevents SSTI by ensuring only safe primitive types are passed to
    the template engine. Blocks functions, classes, modules, and other
    objects that could be used to access Python internals.
    """

    # Allowed types for template variables (defense against SSTI via dangerous objects)
    ALLOWED_TYPES = (str, int, float, bool, list, dict, tuple, type(None))
    # Maximum size per variable in bytes (100KB)
    MAX_VAR_SIZE = SIZE_100MB // MULTIPLIER_MEDIUM // MULTIPLIER_MEDIUM  # 100KB = 100MB / 10 / 10

    def validate_variables(self, variables: Dict[str, Any]) -> None:
        """
        Validate template variables for type safety and size limits.

        Args:
            variables: Variables to validate

        Raises:
            PromptRenderError: If any variable has a disallowed type or exceeds size limit
        """
        for key, value in variables.items():
            self._validate_value(key, value)

    def _validate_value(self, key: str, value: Any, depth: int = 0) -> None:
        """Recursively validate a single value."""
        if depth > MULTIPLIER_MEDIUM * MULTIPLIER_SMALL:  # 20 = 10 * 2
            raise PromptRenderError(
                f"{ERROR_MSG_VARIABLE_PREFIX}{key}' has excessive nesting depth (>{MULTIPLIER_MEDIUM * MULTIPLIER_SMALL})"
            )

        if not isinstance(value, self.ALLOWED_TYPES):
            raise PromptRenderError(
                f"{ERROR_MSG_VARIABLE_PREFIX}{key}' has disallowed type: {type(value).__name__}. "
                f"Allowed: str, int, float, bool, list, dict, tuple, None"
            )

        # Check size for string values
        if isinstance(value, str):
            size = len(value.encode('utf-8', errors='replace'))
            if size > self.MAX_VAR_SIZE:
                raise PromptRenderError(
                    f"{ERROR_MSG_VARIABLE_PREFIX}{key}' exceeds size limit: {size} > {self.MAX_VAR_SIZE}"
                )

        # Recursively validate nested structures
        if isinstance(value, dict):
            for k, v in value.items():
                self._validate_value(f"{key}.{k}", v, depth + 1)
        elif isinstance(value, (list, tuple)):
            for i, item in enumerate(value):
                self._validate_value(f"{key}[{i}]", item, depth + 1)
