"""Tests for temper_ai/safety/validation.py.

Covers:
- ValidationMixin._validate_positive_int
- ValidationMixin._validate_time_seconds
- ValidationMixin._validate_byte_size
- ValidationMixin._validate_float_range
- ValidationMixin._validate_boolean
- ValidationMixin._validate_string_list
- ValidationMixin._validate_regex_pattern
- ValidationMixin._validate_dict
- ValidationMixin._format_bytes
"""

import pytest

from temper_ai.safety.validation import ValidationMixin
from temper_ai.shared.constants.sizes import BYTES_PER_GB, BYTES_PER_KB, BYTES_PER_MB


class _Validator(ValidationMixin):
    """Concrete class to test the mixin."""

    pass


@pytest.fixture
def v():
    return _Validator()


# ---------------------------------------------------------------------------
# TestValidatePositiveInt
# ---------------------------------------------------------------------------


class TestValidatePositiveInt:
    """_validate_positive_int checks type, range, and converts."""

    def test_valid_int(self, v):
        assert v._validate_positive_int(5, "count") == 5

    def test_float_converted_to_int(self, v):
        assert v._validate_positive_int(3.7, "count") == 3

    def test_below_min_raises(self, v):
        with pytest.raises(ValueError, match="must be >="):
            v._validate_positive_int(0, "count", min_value=1)

    def test_above_max_raises(self, v):
        with pytest.raises(ValueError, match="must be <="):
            v._validate_positive_int(100, "count", max_value=10)

    def test_at_min_passes(self, v):
        assert v._validate_positive_int(1, "count", min_value=1) == 1

    def test_at_max_passes(self, v):
        assert v._validate_positive_int(10, "count", max_value=10) == 10

    def test_string_raises(self, v):
        with pytest.raises(ValueError, match="must be a number"):
            v._validate_positive_int("five", "count")

    def test_none_raises(self, v):
        with pytest.raises(ValueError, match="must be a number"):
            v._validate_positive_int(None, "count")

    def test_no_max_value_allows_large(self, v):
        assert v._validate_positive_int(999999, "count") == 999999


# ---------------------------------------------------------------------------
# TestValidateTimeSeconds
# ---------------------------------------------------------------------------


class TestValidateTimeSeconds:
    """_validate_time_seconds checks type, NaN/Inf, and range."""

    def test_valid_time(self, v):
        result = v._validate_time_seconds(5.0, "timeout")
        assert result == 5.0

    def test_int_converted_to_float(self, v):
        result = v._validate_time_seconds(10, "timeout")
        assert isinstance(result, float)
        assert result == 10.0

    def test_nan_raises(self, v):
        with pytest.raises(ValueError, match="NaN"):
            v._validate_time_seconds(float("nan"), "timeout")

    def test_inf_raises(self, v):
        with pytest.raises(ValueError, match="infinite"):
            v._validate_time_seconds(float("inf"), "timeout")

    def test_neg_inf_raises(self, v):
        with pytest.raises(ValueError, match="infinite"):
            v._validate_time_seconds(float("-inf"), "timeout")

    def test_below_min_raises(self, v):
        with pytest.raises(ValueError, match="must be >="):
            v._validate_time_seconds(0.001, "timeout", min_seconds=0.1)

    def test_above_max_raises(self, v):
        with pytest.raises(ValueError, match="must be <="):
            v._validate_time_seconds(100000.0, "timeout", max_seconds=86400.0)

    def test_string_raises(self, v):
        with pytest.raises(ValueError, match="must be a number"):
            v._validate_time_seconds("fast", "timeout")


# ---------------------------------------------------------------------------
# TestValidateByteSize
# ---------------------------------------------------------------------------


class TestValidateByteSize:
    """_validate_byte_size checks type and range with formatted errors."""

    def test_valid_size(self, v):
        assert v._validate_byte_size(1024, "file_size", 512, 2048) == 1024

    def test_below_min_raises(self, v):
        with pytest.raises(ValueError, match="must be >="):
            v._validate_byte_size(100, "file_size", 1024, BYTES_PER_MB)

    def test_above_max_raises(self, v):
        with pytest.raises(ValueError, match="must be <="):
            v._validate_byte_size(BYTES_PER_GB, "file_size", 1024, BYTES_PER_MB)

    def test_float_converted_to_int(self, v):
        result = v._validate_byte_size(2048.5, "size", 1024, 4096)
        assert result == 2048

    def test_string_raises(self, v):
        with pytest.raises(ValueError, match="must be a number"):
            v._validate_byte_size("big", "size", 0, 1024)


# ---------------------------------------------------------------------------
# TestValidateFloatRange
# ---------------------------------------------------------------------------


class TestValidateFloatRange:
    """_validate_float_range checks NaN/Inf and range."""

    def test_valid_float(self, v):
        assert v._validate_float_range(0.5, "threshold", 0.0, 1.0) == 0.5

    def test_at_min(self, v):
        assert v._validate_float_range(0.0, "threshold", 0.0, 1.0) == 0.0

    def test_at_max(self, v):
        assert v._validate_float_range(1.0, "threshold", 0.0, 1.0) == 1.0

    def test_below_min_raises(self, v):
        with pytest.raises(ValueError, match="must be between"):
            v._validate_float_range(-0.1, "threshold", 0.0, 1.0)

    def test_above_max_raises(self, v):
        with pytest.raises(ValueError, match="must be between"):
            v._validate_float_range(1.1, "threshold", 0.0, 1.0)

    def test_nan_raises(self, v):
        with pytest.raises(ValueError, match="NaN"):
            v._validate_float_range(float("nan"), "threshold", 0.0, 1.0)

    def test_inf_raises(self, v):
        with pytest.raises(ValueError, match="infinite"):
            v._validate_float_range(float("inf"), "threshold", 0.0, 1.0)

    def test_int_accepted(self, v):
        result = v._validate_float_range(1, "threshold", 0.0, 2.0)
        assert isinstance(result, float)

    def test_string_raises(self, v):
        with pytest.raises(ValueError, match="must be a number"):
            v._validate_float_range("high", "threshold", 0.0, 1.0)


# ---------------------------------------------------------------------------
# TestValidateBoolean
# ---------------------------------------------------------------------------


class TestValidateBoolean:
    """_validate_boolean does strict type checking."""

    def test_true(self, v):
        assert v._validate_boolean(True, "enabled") is True

    def test_false(self, v):
        assert v._validate_boolean(False, "enabled") is False

    def test_string_false_raises(self, v):
        with pytest.raises(ValueError, match="must be a boolean"):
            v._validate_boolean("false", "enabled")

    def test_int_one_raises(self, v):
        with pytest.raises(ValueError, match="must be a boolean"):
            v._validate_boolean(1, "enabled")

    def test_none_with_default(self, v):
        assert v._validate_boolean(None, "enabled", default=True) is True

    def test_none_without_default_raises(self, v):
        with pytest.raises(ValueError, match="cannot be None"):
            v._validate_boolean(None, "enabled")


# ---------------------------------------------------------------------------
# TestValidateStringList
# ---------------------------------------------------------------------------


class TestValidateStringList:
    """_validate_string_list checks type, size, and item constraints."""

    def test_valid_list(self, v):
        result = v._validate_string_list(["a", "b"], "patterns")
        assert result == ["a", "b"]

    def test_empty_list_not_allowed_by_default(self, v):
        with pytest.raises(ValueError, match="cannot be empty"):
            v._validate_string_list([], "patterns")

    def test_empty_list_allowed_when_flag_set(self, v):
        result = v._validate_string_list([], "patterns", allow_empty=True)
        assert result == []

    def test_non_list_raises(self, v):
        with pytest.raises(ValueError, match="must be a list"):
            v._validate_string_list("not_a_list", "patterns")

    def test_too_many_items_raises(self, v):
        with pytest.raises(ValueError, match="exceeds maximum size"):
            v._validate_string_list(["a"] * 5, "patterns", max_items=3)

    def test_non_string_item_raises(self, v):
        with pytest.raises(ValueError, match="must be a string"):
            v._validate_string_list(["a", 42], "patterns")

    def test_item_too_long_raises(self, v):
        with pytest.raises(ValueError, match="exceeds maximum length"):
            v._validate_string_list(["x" * 100], "patterns", max_item_length=10)


# ---------------------------------------------------------------------------
# TestValidateRegexPattern
# ---------------------------------------------------------------------------


class TestValidateRegexPattern:
    """_validate_regex_pattern compiles, checks length, and detects ReDoS."""

    def test_valid_pattern(self, v):
        compiled = v._validate_regex_pattern(r"abc.*", "pattern")
        assert compiled.pattern == r"abc.*"

    def test_empty_pattern_raises(self, v):
        with pytest.raises(ValueError, match="cannot be empty"):
            v._validate_regex_pattern("", "pattern")

    def test_invalid_regex_raises(self, v):
        with pytest.raises(ValueError, match="not a valid regex"):
            v._validate_regex_pattern("[invalid", "pattern")

    def test_too_long_raises(self, v):
        with pytest.raises(ValueError, match="exceeds maximum length"):
            v._validate_regex_pattern("a" * 200, "pattern", max_length=100)

    def test_non_string_raises(self, v):
        with pytest.raises(ValueError, match="must be a string"):
            v._validate_regex_pattern(42, "pattern")

    def test_case_insensitive_flag(self, v):
        import re

        compiled = v._validate_regex_pattern(r"test", "pattern")
        assert compiled.flags & re.IGNORECASE


# ---------------------------------------------------------------------------
# TestValidateDict
# ---------------------------------------------------------------------------


class TestValidateDict:
    """_validate_dict checks type and emptiness."""

    def test_valid_dict(self, v):
        result = v._validate_dict({"key": "val"}, "config")
        assert result == {"key": "val"}

    def test_empty_dict_allowed_by_default(self, v):
        result = v._validate_dict({}, "config")
        assert result == {}

    def test_empty_dict_not_allowed_when_flag_set(self, v):
        with pytest.raises(ValueError, match="cannot be empty"):
            v._validate_dict({}, "config", allow_empty=False)

    def test_non_dict_raises(self, v):
        with pytest.raises(ValueError, match="must be a dictionary"):
            v._validate_dict([], "config")


# ---------------------------------------------------------------------------
# TestFormatBytes
# ---------------------------------------------------------------------------


class TestFormatBytes:
    """_format_bytes produces human-readable size strings."""

    def test_bytes(self):
        assert ValidationMixin._format_bytes(500) == "500 bytes"

    def test_kilobytes(self):
        result = ValidationMixin._format_bytes(BYTES_PER_KB)
        assert "KB" in result

    def test_megabytes(self):
        result = ValidationMixin._format_bytes(BYTES_PER_MB)
        assert "MB" in result

    def test_gigabytes(self):
        result = ValidationMixin._format_bytes(BYTES_PER_GB)
        assert "GB" in result

    def test_zero_bytes(self):
        assert ValidationMixin._format_bytes(0) == "0 bytes"
