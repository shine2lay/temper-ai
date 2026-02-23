"""
Input validation utilities for safety policies.

Provides validation methods for common parameter types to prevent
security vulnerabilities from malformed configurations.
"""

import logging
import re
import time
from re import Pattern
from typing import Any

from temper_ai.safety.constants import (
    DEFAULT_MAX_ITEM_LENGTH,
    DEFAULT_MAX_ITEMS,
    DEFAULT_MAX_STRING_LENGTH,
    ERROR_CANNOT_BE_EMPTY,
    ERROR_GOT_PREFIX,
    ERROR_MUST_BE_GTE,
    ERROR_MUST_BE_LTE,
    ERROR_MUST_BE_NUMBER,
    FORMAT_ONE_DECIMAL,
    MAX_VALIDATION_TIME_SECONDS,
)
from temper_ai.shared.constants.limits import LARGE_ITEM_LIMIT
from temper_ai.shared.constants.probabilities import PROB_VERY_LOW
from temper_ai.shared.constants.sizes import BYTES_PER_GB, BYTES_PER_KB, BYTES_PER_MB

logger = logging.getLogger(__name__)


class ValidationMixin:
    """Mixin providing input validation for policy configurations.

    This mixin provides methods to validate common parameter types and
    prevent security vulnerabilities from malformed configurations:

    - Integer validation (positive, within bounds)
    - Float validation (range checks, NaN/Inf detection)
    - Time validation (positive, reasonable bounds)
    - Byte size validation (memory/file size limits)
    - Boolean validation (strict type checking)
    - String list validation (length limits, type checking)
    - Regex pattern validation (ReDoS detection)
    - Dictionary validation (type checking)

    Example:
        >>> class MyPolicy(BaseSafetyPolicy, ValidationMixin):
        ...     def __init__(self, config: Dict[str, Any]):
        ...         super().__init__(config)
        ...         self.max_files = self._validate_positive_int(
        ...             config.get("max_files", 100),
        ...             "max_files",
        ...             min_value=1,
        ...             max_value=10000
        ...         )
    """

    def _validate_positive_int(
        self,
        value: Any,
        param_name: str,
        min_value: int = 1,
        max_value: int | None = None,
    ) -> int:
        """Validate that a parameter is a positive integer within bounds.

        Args:
            value: Value to validate
            param_name: Parameter name for error messages
            min_value: Minimum allowed value (default: 1)
            max_value: Maximum allowed value (default: None)

        Returns:
            Validated integer value

        Raises:
            ValueError: If value is not a valid positive integer within bounds

        Example:
            >>> self._validate_positive_int(5, "count", min_value=1, max_value=10)
            5
            >>> self._validate_positive_int(-1, "count", min_value=1)
            ValueError: count must be >= 1, got -1
        """
        # Type check
        if not isinstance(value, (int, float)):
            raise ValueError(
                f"{param_name}{ERROR_MUST_BE_NUMBER}{type(value).__name__}"
            )

        # Convert to int (handles float inputs)
        try:
            int_value = int(value)
        except (ValueError, OverflowError) as e:
            raise ValueError(
                f"{param_name} cannot be converted to integer: {value}"
            ) from e

        # Range check
        if int_value < min_value:
            raise ValueError(
                f"{param_name}{ERROR_MUST_BE_GTE}{min_value}{ERROR_GOT_PREFIX}{int_value}"
            )

        if max_value is not None and int_value > max_value:
            raise ValueError(
                f"{param_name}{ERROR_MUST_BE_LTE}{max_value}{ERROR_GOT_PREFIX}{int_value}"
            )

        return int_value

    def _validate_time_seconds(
        self,
        value: Any,
        param_name: str,
        min_seconds: float = PROB_VERY_LOW,
        max_seconds: float = float(MAX_VALIDATION_TIME_SECONDS),
    ) -> float:
        """Validate that a parameter is a valid time value in seconds.

        Args:
            value: Value to validate
            param_name: Parameter name for error messages
            min_seconds: Minimum allowed value (default: 0.1)
            max_seconds: Maximum allowed value (default: 86400 = 24 hours)

        Returns:
            Validated float value

        Raises:
            ValueError: If value is not a valid time value

        Example:
            >>> self._validate_time_seconds(5.0, "timeout")
            5.0
            >>> self._validate_time_seconds(-1.0, "timeout")
            ValueError: timeout must be >= 0.1s, got -1.0s
        """
        # Type check
        if not isinstance(value, (int, float)):
            raise ValueError(
                f"{param_name}{ERROR_MUST_BE_NUMBER}{type(value).__name__}"
            )

        # Convert to float
        float_value = float(value)

        # NaN/Inf check
        if not (float_value == float_value):  # NaN check
            raise ValueError(f"{param_name} cannot be NaN")

        if float_value == float("inf") or float_value == float("-inf"):
            raise ValueError(f"{param_name} cannot be infinite")

        # Range check
        if float_value < min_seconds:
            raise ValueError(
                f"{param_name} must be >= {min_seconds}s, got {float_value}s"
            )

        if float_value > max_seconds:
            raise ValueError(
                f"{param_name} must be <= {max_seconds}s, got {float_value}s"
            )

        return float_value

    def _validate_byte_size(
        self, value: Any, param_name: str, min_bytes: int, max_bytes: int
    ) -> int:
        """Validate that a parameter is a valid byte size.

        Args:
            value: Value to validate
            param_name: Parameter name for error messages
            min_bytes: Minimum allowed size
            max_bytes: Maximum allowed size

        Returns:
            Validated integer value

        Raises:
            ValueError: If value is not a valid byte size

        Example:
            >>> self._validate_byte_size(1024, "file_size", 1024, 1024*1024)
            1024
            >>> self._validate_byte_size(0, "file_size", 1024, 1024*1024)
            ValueError: file_size must be >= 1KB, got 0 bytes
        """
        # Type check
        if not isinstance(value, (int, float)):
            raise ValueError(
                f"{param_name}{ERROR_MUST_BE_NUMBER}{type(value).__name__}"
            )

        # Convert to int
        int_value = int(value)

        # Range check
        if int_value < min_bytes:
            raise ValueError(
                f"{param_name} must be >= {self._format_bytes(min_bytes)}, "
                f"got {self._format_bytes(int_value)}"
            )

        if int_value > max_bytes:
            raise ValueError(
                f"{param_name} must be <= {self._format_bytes(max_bytes)}, "
                f"got {self._format_bytes(int_value)}"
            )

        return int_value

    def _validate_float_range(
        self, value: Any, param_name: str, min_value: float, max_value: float
    ) -> float:
        """Validate that a parameter is a float within range.

        Args:
            value: Value to validate
            param_name: Parameter name for error messages
            min_value: Minimum allowed value
            max_value: Maximum allowed value

        Returns:
            Validated float value

        Raises:
            ValueError: If value is not within valid range

        Example:
            >>> self._validate_float_range(4.5, "entropy", 0.0, 8.0)
            4.5
            >>> self._validate_float_range(10.0, "entropy", 0.0, 8.0)
            ValueError: entropy must be between 0.0 and 8.0, got 10.0
        """
        # Type check
        if not isinstance(value, (int, float)):
            raise ValueError(
                f"{param_name}{ERROR_MUST_BE_NUMBER}{type(value).__name__}"
            )

        float_value = float(value)

        # NaN/Inf check
        if not (float_value == float_value):  # NaN check
            raise ValueError(f"{param_name} cannot be NaN")

        if float_value == float("inf") or float_value == float("-inf"):
            raise ValueError(f"{param_name} cannot be infinite")

        # Range check
        if float_value < min_value or float_value > max_value:
            raise ValueError(
                f"{param_name} must be between {min_value} and {max_value}, "
                f"got {float_value}"
            )

        return float_value

    def _validate_boolean(
        self, value: Any, param_name: str, default: bool | None = None
    ) -> bool:
        """Validate that a parameter is a boolean value.

        Performs strict type checking to prevent type confusion attacks
        where string "false" evaluates to True.

        Args:
            value: Value to validate
            param_name: Parameter name for error messages
            default: Default value if None (default: None)

        Returns:
            Validated boolean value

        Raises:
            ValueError: If value is not a boolean and no default provided

        Example:
            >>> self._validate_boolean(True, "enabled")
            True
            >>> self._validate_boolean("false", "enabled")
            ValueError: enabled must be a boolean (True/False), got str: false
        """
        # None check - use default if provided
        if value is None:
            if default is None:
                raise ValueError(f"{param_name} cannot be None")
            return default

        # Strict type check (prevents "false" string -> True)
        if not isinstance(value, bool):
            raise ValueError(
                f"{param_name} must be a boolean (True/False), "
                f"got {type(value).__name__}: {value}"
            )

        return value

    def _validate_string_list(
        self,
        values: Any,
        param_name: str,
        allow_empty: bool = False,
        max_items: int = DEFAULT_MAX_ITEMS,
        max_item_length: int = DEFAULT_MAX_ITEM_LENGTH,
    ) -> list[str]:
        """Validate that a parameter is a list of valid strings.

        Args:
            values: Value to validate
            param_name: Parameter name for error messages
            allow_empty: Allow empty list (default: False)
            max_items: Maximum list size (default: 1000)
            max_item_length: Maximum string length (default: 1000)

        Returns:
            Validated list of strings

        Raises:
            ValueError: If value is not a valid string list

        Example:
            >>> self._validate_string_list(["a", "b"], "patterns")
            ["a", "b"]
            >>> self._validate_string_list([], "patterns", allow_empty=False)
            ValueError: patterns cannot be empty
        """
        # Type check
        if not isinstance(values, list):
            raise ValueError(
                f"{param_name} must be a list, got {type(values).__name__}"
            )

        # Empty check
        if not values and not allow_empty:
            raise ValueError(f"{param_name}{ERROR_CANNOT_BE_EMPTY}")

        # Size check
        if len(values) > max_items:
            raise ValueError(
                f"{param_name} exceeds maximum size {max_items}: "
                f"{len(values)} items"
            )

        # Validate each item
        validated = []
        for i, item in enumerate(values):
            if not isinstance(item, str):
                raise ValueError(
                    f"{param_name}[{i}] must be a string, " f"got {type(item).__name__}"
                )

            if len(item) > max_item_length:
                raise ValueError(
                    f"{param_name}[{i}] exceeds maximum length "
                    f"{max_item_length}: {len(item)} characters"
                )

            validated.append(item)

        return validated

    def _validate_regex_pattern(
        self,
        pattern: str,
        param_name: str,
        max_length: int = DEFAULT_MAX_STRING_LENGTH,
        test_timeout: float = PROB_VERY_LOW,
    ) -> Pattern[str]:
        """Validate that a pattern is a safe, compilable regex.

        Tests the pattern for:
        - Validity (can be compiled)
        - Length limits (prevent memory exhaustion)
        - ReDoS vulnerability (test on adversarial inputs)

        Args:
            pattern: Regex pattern string
            param_name: Parameter name for error messages
            max_length: Maximum pattern length (default: 1000)
            test_timeout: Timeout for ReDoS test (default: 0.1s)

        Returns:
            Compiled regex pattern

        Raises:
            ValueError: If pattern is invalid or potentially dangerous

        Example:
            >>> self._validate_regex_pattern("abc.*", "pattern")
            re.compile('abc.*', re.IGNORECASE)
            >>> self._validate_regex_pattern("(a+)+b", "pattern")
            ValueError: pattern may be vulnerable to ReDoS
        """
        # Type check
        if not isinstance(pattern, str):
            raise ValueError(
                f"{param_name} must be a string, got {type(pattern).__name__}"
            )

        # Empty check
        if not pattern:
            raise ValueError(f"{param_name}{ERROR_CANNOT_BE_EMPTY}")

        # Length check
        if len(pattern) > max_length:
            raise ValueError(
                f"{param_name} exceeds maximum length {max_length}: "
                f"{len(pattern)} characters"
            )

        # Compile check
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            raise ValueError(f"{param_name} is not a valid regex: {e}") from e

        # ReDoS check - test on adversarial inputs
        test_strings = [
            "a" * (LARGE_ITEM_LIMIT * 2),  # Repetition (100 chars)
            "a" * LARGE_ITEM_LIMIT + "b",  # Repetition with terminator (50 chars)
            "x" * (LARGE_ITEM_LIMIT * 2),  # Different character (100 chars)
        ]

        for test_str in test_strings:
            start_time = time.time()
            try:
                compiled.search(test_str)
                elapsed = time.time() - start_time

                if elapsed > test_timeout:
                    raise ValueError(
                        f"{param_name} may be vulnerable to ReDoS: "
                        f"took {elapsed:.3f}s on test string"
                    )
            except (re.error, TimeoutError, OverflowError) as e:
                # Pattern causes errors - reject it
                raise ValueError(
                    f"{param_name} causes errors during matching: {e}"
                ) from e

        return compiled

    def _validate_dict(
        self, value: Any, param_name: str, allow_empty: bool = True
    ) -> dict[str, Any]:
        """Validate that a parameter is a dictionary.

        Args:
            value: Value to validate
            param_name: Parameter name for error messages
            allow_empty: Allow empty dict (default: True)

        Returns:
            Validated dictionary

        Raises:
            ValueError: If value is not a dictionary

        Example:
            >>> self._validate_dict({"key": "value"}, "config")
            {"key": "value"}
            >>> self._validate_dict([], "config")
            ValueError: config must be a dictionary, got list
        """
        if not isinstance(value, dict):
            raise ValueError(
                f"{param_name} must be a dictionary, got {type(value).__name__}"
            )

        if not value and not allow_empty:
            raise ValueError(f"{param_name}{ERROR_CANNOT_BE_EMPTY}")

        return value

    @staticmethod
    def _format_bytes(bytes_value: int) -> str:
        """Format byte value as human-readable string.

        Args:
            bytes_value: Byte count to format

        Returns:
            Human-readable string (e.g., "1.5KB", "2MB")

        Example:
            >>> ValidationMixin._format_bytes(1024)
            "1KB"
            >>> ValidationMixin._format_bytes(1536)
            "1.5KB"
        """
        if bytes_value < BYTES_PER_KB:
            return f"{bytes_value} bytes"
        elif bytes_value < BYTES_PER_MB:
            return f"{bytes_value / BYTES_PER_KB:{FORMAT_ONE_DECIMAL}}KB"
        elif bytes_value < BYTES_PER_GB:
            return f"{bytes_value / BYTES_PER_MB:{FORMAT_ONE_DECIMAL}}MB"
        else:
            return f"{bytes_value / BYTES_PER_GB:{FORMAT_ONE_DECIMAL}}GB"
