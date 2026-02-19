"""Tests for src/database/validators.py.

Tests database field validators for data integrity.
"""
import pytest

from temper_ai.storage.database.validators import (
    JSONSizeError,
    validate_json_size,
    validate_optional_json_size,
)


class TestValidateJsonSize:
    """Test validate_json_size function."""

    def test_valid_small_json(self):
        """Test that small JSON passes validation."""
        data = {"key": "value", "number": 123}
        # Should not raise
        result = validate_json_size(data, max_bytes=1024 * 1024)
        assert result is None

    def test_valid_with_nested_data(self):
        """Test validation with nested structures."""
        data = {
            "config": {
                "settings": {
                    "timeout": 30,
                    "retries": 3
                }
            },
            "metadata": {"version": "1.0"}
        }
        # Should not raise
        result = validate_json_size(data)
        assert result is None

    def test_exceeds_max_size(self):
        """Test that oversized JSON raises error."""
        # Create JSON that will be >1MB when serialized
        large_data = {"data": "x" * (2 * 1024 * 1024)}  # 2MB of data

        with pytest.raises(JSONSizeError, match="too large"):
            validate_json_size(large_data, max_bytes=1024 * 1024)

    def test_custom_max_bytes(self):
        """Test validation with custom max_bytes."""
        data = {"key": "value" * 1000}  # Moderate size

        # Should pass with large limit
        result = validate_json_size(data, max_bytes=100000)
        assert result is None

        # Should fail with small limit
        with pytest.raises(JSONSizeError):
            validate_json_size(data, max_bytes=100)

    def test_custom_field_name(self):
        """Test that custom field name appears in error."""
        large_data = {"data": "x" * (2 * 1024 * 1024)}

        with pytest.raises(JSONSizeError, match="workflow_config"):
            validate_json_size(
                large_data,
                max_bytes=1024 * 1024,
                field_name="workflow_config"
            )

    def test_not_json_serializable(self):
        """Test that non-JSON-serializable data raises TypeError."""
        # Use a non-serializable object
        data = {"func": lambda x: x}  # Functions can't be JSON serialized

        with pytest.raises(TypeError, match="Failed to serialize"):
            validate_json_size(data)

    def test_empty_dict(self):
        """Test that empty dict is valid."""
        data = {}
        # Should not raise
        result = validate_json_size(data)
        assert result is None

    def test_list_data(self):
        """Test validation with list instead of dict."""
        # The function takes Dict[str, Any] but JSON serialization should work
        data = {"items": [1, 2, 3, 4, 5]}
        # Should not raise
        result = validate_json_size(data)
        assert result is None

    def test_unicode_data(self):
        """Test validation with Unicode characters."""
        data = {"message": "Hello 世界 🌍"}
        # Should not raise
        result = validate_json_size(data)
        assert result is None

    def test_size_calculation_accurate(self):
        """Test that size calculation is accurate."""
        # Known size: {"a":"b"} = 9 bytes with compact JSON
        data = {"a": "b"}
        # Should pass with 10 byte limit
        result = validate_json_size(data, max_bytes=10)
        assert result is None

        # Should fail with 5 byte limit
        with pytest.raises(JSONSizeError):
            validate_json_size(data, max_bytes=5)


class TestValidateOptionalJsonSize:
    """Test validate_optional_json_size function."""

    def test_none_value(self):
        """Test that None value is allowed."""
        # Should not raise
        result = validate_optional_json_size(None)
        assert result is None

    def test_valid_data(self):
        """Test with valid data."""
        data = {"key": "value"}
        # Should not raise
        result = validate_optional_json_size(data)
        assert result is None

    def test_exceeds_max_size(self):
        """Test that oversized data raises error."""
        large_data = {"data": "x" * (2 * 1024 * 1024)}

        with pytest.raises(JSONSizeError):
            validate_optional_json_size(large_data, max_bytes=1024 * 1024)

    def test_custom_params(self):
        """Test with custom parameters."""
        data = {"key": "value"}

        # Should not raise
        result = validate_optional_json_size(
            data,
            max_bytes=100,
            field_name="custom_field"
        )
        assert result is None


class TestJSONSizeError:
    """Test JSONSizeError exception."""

    def test_is_value_error(self):
        """Test that JSONSizeError is a ValueError."""
        error = JSONSizeError("test")
        assert isinstance(error, ValueError)

    def test_error_message(self):
        """Test error message."""
        error = JSONSizeError("Field too large")
        assert str(error) == "Field too large"


class TestEdgeCases:
    """Test edge cases for validators."""

    def test_deeply_nested_structure(self):
        """Test with deeply nested structure."""
        # Create a deeply nested structure
        data = {"level1": {"level2": {"level3": {"level4": {"value": "deep"}}}}}
        # Should not raise
        result = validate_json_size(data)
        assert result is None

    def test_large_array(self):
        """Test with large array."""
        data = {"numbers": list(range(1000))}
        # Should not raise
        result = validate_json_size(data, max_bytes=100000)
        assert result is None

    def test_special_characters(self):
        """Test with special characters that need escaping."""
        data = {
            "quote": '"quoted"',
            "backslash": "\\path\\to\\file",
            "newline": "line1\nline2",
            "tab": "col1\tcol2"
        }
        # Should not raise
        result = validate_json_size(data)
        assert result is None

    def test_boolean_and_null_values(self):
        """Test with boolean and null values."""
        data = {
            "is_active": True,
            "is_deleted": False,
            "optional": None
        }
        # Should not raise
        result = validate_json_size(data)
        assert result is None

    def test_numeric_values(self):
        """Test with various numeric types."""
        data = {
            "integer": 42,
            "negative": -100,
            "float": 3.14159,
            "zero": 0
        }
        # Should not raise
        result = validate_json_size(data)
        assert result is None
