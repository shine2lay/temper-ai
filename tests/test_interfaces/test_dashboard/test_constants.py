"""Tests for dashboard module constants."""

from temper_ai.interfaces.dashboard import constants


class TestApiEndpoints:
    """Tests for API endpoint constants."""

    def test_config_endpoint_is_string(self) -> None:
        """API_CONFIG_ENDPOINT is a string."""
        assert isinstance(constants.API_CONFIG_ENDPOINT, str)

    def test_config_endpoint_has_config_type_placeholder(self) -> None:
        """Endpoint template has {config_type} placeholder."""
        assert "{config_type}" in constants.API_CONFIG_ENDPOINT

    def test_config_endpoint_has_name_placeholder(self) -> None:
        """Endpoint template has {name} placeholder."""
        assert "{name}" in constants.API_CONFIG_ENDPOINT

    def test_config_endpoint_value(self) -> None:
        """Endpoint matches expected path pattern."""
        assert constants.API_CONFIG_ENDPOINT == "/configs/{config_type}/{name}"

    def test_config_endpoint_starts_with_slash(self) -> None:
        """Endpoint path starts with '/'."""
        assert constants.API_CONFIG_ENDPOINT.startswith("/")

    def test_config_endpoint_can_be_formatted(self) -> None:
        """Template can be formatted with concrete values."""
        formatted = constants.API_CONFIG_ENDPOINT.format(
            config_type="workflows", name="my-workflow"
        )
        assert formatted == "/configs/workflows/my-workflow"


class TestEncoding:
    """Tests for encoding constants."""

    def test_default_encoding_is_string(self) -> None:
        """DEFAULT_ENCODING is a string."""
        assert isinstance(constants.DEFAULT_ENCODING, str)

    def test_default_encoding_is_utf8(self) -> None:
        """DEFAULT_ENCODING is 'utf-8'."""
        assert constants.DEFAULT_ENCODING == "utf-8"

    def test_default_encoding_is_valid(self) -> None:
        """DEFAULT_ENCODING is a valid Python codec name."""
        # Should not raise
        "test".encode(constants.DEFAULT_ENCODING)


class TestErrorMessages:
    """Tests for error message string constants."""

    def test_config_not_found_is_string(self) -> None:
        """ERROR_CONFIG_NOT_FOUND is a string."""
        assert isinstance(constants.ERROR_CONFIG_NOT_FOUND, str)

    def test_config_not_found_is_non_empty(self) -> None:
        """ERROR_CONFIG_NOT_FOUND is non-empty."""
        assert len(constants.ERROR_CONFIG_NOT_FOUND) > 0

    def test_config_not_found_contains_config(self) -> None:
        """Message prefix references 'Config'."""
        assert "Config" in constants.ERROR_CONFIG_NOT_FOUND

    def test_config_not_found_ends_with_separator(self) -> None:
        """Message ends with separator for appending path info."""
        # Should end with ': ' or similar separator to concatenate type/name
        assert constants.ERROR_CONFIG_NOT_FOUND.endswith(
            ":"
        ) or constants.ERROR_CONFIG_NOT_FOUND.endswith(": ")


class TestAllConstantsDefined:
    """Tests that all expected constants are exported."""

    def test_api_config_endpoint_exists(self) -> None:
        """API_CONFIG_ENDPOINT is defined in module."""
        assert hasattr(constants, "API_CONFIG_ENDPOINT")

    def test_default_encoding_exists(self) -> None:
        """DEFAULT_ENCODING is defined in module."""
        assert hasattr(constants, "DEFAULT_ENCODING")

    def test_error_config_not_found_exists(self) -> None:
        """ERROR_CONFIG_NOT_FOUND is defined in module."""
        assert hasattr(constants, "ERROR_CONFIG_NOT_FOUND")
