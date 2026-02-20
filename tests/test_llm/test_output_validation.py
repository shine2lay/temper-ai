"""Tests for structured output validation (R0.1)."""
import json

import pytest

from temper_ai.llm.output_validation import (
    build_retry_prompt_with_error,
    build_schema_enforcement_prompt,
    validate_output_against_schema,
)


SIMPLE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "age": {"type": "integer"},
    },
    "required": ["name", "age"],
}

ENUM_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["ok", "error"]},
    },
    "required": ["status"],
}


class TestValidateOutputAgainstSchema:
    """Tests for validate_output_against_schema."""

    def test_valid_json_matching_schema(self):
        """Should pass for valid JSON matching the schema."""
        output = json.dumps({"name": "Alice", "age": 30})
        valid, error = validate_output_against_schema(output, SIMPLE_SCHEMA)
        assert valid is True
        assert error is None

    def test_invalid_json(self):
        """Should fail for invalid JSON."""
        valid, error = validate_output_against_schema("not json", SIMPLE_SCHEMA)
        assert valid is False
        assert "Invalid JSON" in error

    def test_valid_json_wrong_schema(self):
        """Should fail for valid JSON not matching the schema."""
        output = json.dumps({"name": "Alice"})  # missing required "age"
        valid, error = validate_output_against_schema(output, SIMPLE_SCHEMA)
        # This depends on jsonschema being installed
        try:
            import jsonschema  # noqa: F401
            assert valid is False
            assert "Schema validation failed" in error
        except ImportError:
            # Without jsonschema, validation is skipped
            assert valid is True

    def test_empty_string(self):
        """Should fail for empty string."""
        valid, error = validate_output_against_schema("", SIMPLE_SCHEMA)
        assert valid is False
        assert "Invalid JSON" in error

    def test_valid_json_enum_match(self):
        """Should pass for valid enum value."""
        output = json.dumps({"status": "ok"})
        valid, error = validate_output_against_schema(output, ENUM_SCHEMA)
        assert valid is True
        assert error is None

    def test_valid_json_enum_mismatch(self):
        """Should fail for invalid enum value."""
        output = json.dumps({"status": "unknown"})
        valid, error = validate_output_against_schema(output, ENUM_SCHEMA)
        try:
            import jsonschema  # noqa: F401
            assert valid is False
            assert error is not None
        except ImportError:
            assert valid is True

    def test_none_output(self):
        """Should fail for None output."""
        valid, error = validate_output_against_schema(None, SIMPLE_SCHEMA)
        assert valid is False

    def test_json_array_against_object_schema(self):
        """Should fail for array when schema expects object."""
        output = json.dumps([1, 2, 3])
        valid, error = validate_output_against_schema(output, SIMPLE_SCHEMA)
        try:
            import jsonschema  # noqa: F401
            assert valid is False
        except ImportError:
            assert valid is True


class TestBuildSchemaEnforcementPrompt:
    """Tests for build_schema_enforcement_prompt."""

    def test_appends_schema(self):
        """Should append schema instructions to prompt."""
        result = build_schema_enforcement_prompt("Do X", SIMPLE_SCHEMA)
        assert result.startswith("Do X")
        assert '"name"' in result
        assert "MUST respond with valid JSON" in result

    def test_preserves_original_prompt(self):
        """Should keep the original prompt intact."""
        prompt = "This is my original task"
        result = build_schema_enforcement_prompt(prompt, SIMPLE_SCHEMA)
        assert prompt in result


class TestBuildRetryPromptWithError:
    """Tests for build_retry_prompt_with_error."""

    def test_includes_error(self):
        """Should include the error message."""
        result = build_retry_prompt_with_error(
            "Do X", '{"bad"}', "Invalid JSON", SIMPLE_SCHEMA,
        )
        assert "Invalid JSON" in result

    def test_includes_schema(self):
        """Should include the schema."""
        result = build_retry_prompt_with_error(
            "Do X", '{"bad"}', "error", SIMPLE_SCHEMA,
        )
        assert '"name"' in result

    def test_includes_original_prompt(self):
        """Should include the original task prompt."""
        result = build_retry_prompt_with_error(
            "Original task here", '{"bad"}', "error", SIMPLE_SCHEMA,
        )
        assert "Original task here" in result

    def test_format_is_readable(self):
        """Should produce a readable prompt."""
        result = build_retry_prompt_with_error(
            "Do X", "bad output", "Parse error", SIMPLE_SCHEMA,
        )
        assert "previous output was invalid" in result
