"""Structured output validation (R0.1).

Validates LLM output against a JSON schema and provides retry prompts
when validation fails.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_SCHEMA_INSTRUCTION = "\n\nYou MUST respond with valid JSON matching this schema:\n"

_RETRY_INSTRUCTION = (
    "Your previous output was invalid JSON.\n"
    "Error: {error}\n\n"
    "Please fix and respond with valid JSON matching the schema:\n"
)


def validate_output_against_schema(
    output_text: str,
    json_schema: dict[str, Any],
) -> tuple[bool, str | None]:
    """Validate output text against a JSON schema.

    Returns:
        Tuple of (is_valid, error_message). error_message is None on success.
    """
    try:
        parsed = json.loads(output_text)
    except (json.JSONDecodeError, TypeError) as exc:
        return False, f"Invalid JSON: {exc}"

    try:
        import jsonschema  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("jsonschema not installed; skipping schema validation")
        return True, None

    try:
        jsonschema.validate(instance=parsed, schema=json_schema)
        return True, None
    except jsonschema.ValidationError as exc:
        return False, f"Schema validation failed: {exc.message}"


def build_schema_enforcement_prompt(
    original_prompt: str,
    json_schema: dict[str, Any],
) -> str:
    """Append JSON schema instructions to the prompt."""
    schema_text = json.dumps(json_schema, indent=2)
    return original_prompt + _SCHEMA_INSTRUCTION + schema_text


def build_retry_prompt_with_error(
    original_prompt: str,
    output: str,
    error_msg: str,
    json_schema: dict[str, Any],
) -> str:
    """Build a retry prompt that includes the error and schema."""
    schema_text = json.dumps(json_schema, indent=2)
    retry_header = _RETRY_INSTRUCTION.format(error=error_msg)
    return retry_header + schema_text + "\n\nOriginal task:\n" + original_prompt
