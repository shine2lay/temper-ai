"""Tests for _is_instrumentation_enabled helper and httpx default-ON behavior."""

from unittest.mock import patch

import pytest

from temper_ai.observability.otel_setup import (
    _ENV_TEMPER_OTEL_INSTRUMENT_HTTPX,
    _ENV_TEMPER_OTEL_INSTRUMENT_SQLALCHEMY,
    _is_instrumentation_enabled,
)


class TestIsInstrumentationEnabled:
    """Tests for the _is_instrumentation_enabled helper function."""

    # --- httpx: default ON when env var not set ---

    def test_httpx_default_on_when_env_not_set(self) -> None:
        """httpx instrumentation defaults to ON when env var is absent."""
        with patch.dict("os.environ", {}, clear=True):
            result = _is_instrumentation_enabled(
                _ENV_TEMPER_OTEL_INSTRUMENT_HTTPX, default_enabled=True
            )
        assert result is True

    # --- httpx: explicit opt-out ---

    def test_httpx_opt_out_with_false(self) -> None:
        """httpx can be explicitly disabled with 'false'."""
        with patch.dict(
            "os.environ", {_ENV_TEMPER_OTEL_INSTRUMENT_HTTPX: "false"}, clear=True
        ):
            result = _is_instrumentation_enabled(
                _ENV_TEMPER_OTEL_INSTRUMENT_HTTPX, default_enabled=True
            )
        assert result is False

    def test_httpx_opt_out_with_zero(self) -> None:
        """httpx can be explicitly disabled with '0'."""
        with patch.dict(
            "os.environ", {_ENV_TEMPER_OTEL_INSTRUMENT_HTTPX: "0"}, clear=True
        ):
            result = _is_instrumentation_enabled(
                _ENV_TEMPER_OTEL_INSTRUMENT_HTTPX, default_enabled=True
            )
        assert result is False

    # --- httpx: explicit opt-in ---

    def test_httpx_opt_in_with_true(self) -> None:
        """httpx enabled with 'true'."""
        with patch.dict(
            "os.environ", {_ENV_TEMPER_OTEL_INSTRUMENT_HTTPX: "true"}, clear=True
        ):
            result = _is_instrumentation_enabled(
                _ENV_TEMPER_OTEL_INSTRUMENT_HTTPX, default_enabled=True
            )
        assert result is True

    def test_httpx_opt_in_with_one(self) -> None:
        """httpx enabled with '1'."""
        with patch.dict(
            "os.environ", {_ENV_TEMPER_OTEL_INSTRUMENT_HTTPX: "1"}, clear=True
        ):
            result = _is_instrumentation_enabled(
                _ENV_TEMPER_OTEL_INSTRUMENT_HTTPX, default_enabled=True
            )
        assert result is True

    # --- SQLAlchemy: default OFF ---

    def test_sqlalchemy_default_off_when_env_not_set(self) -> None:
        """SQLAlchemy instrumentation defaults to OFF when env var is absent."""
        with patch.dict("os.environ", {}, clear=True):
            result = _is_instrumentation_enabled(
                _ENV_TEMPER_OTEL_INSTRUMENT_SQLALCHEMY, default_enabled=False
            )
        assert result is False

    def test_sqlalchemy_opt_in_with_true(self) -> None:
        """SQLAlchemy can be explicitly enabled with 'true'."""
        with patch.dict(
            "os.environ", {_ENV_TEMPER_OTEL_INSTRUMENT_SQLALCHEMY: "true"}, clear=True
        ):
            result = _is_instrumentation_enabled(
                _ENV_TEMPER_OTEL_INSTRUMENT_SQLALCHEMY, default_enabled=False
            )
        assert result is True

    # --- Case insensitivity ---

    def test_case_insensitive_uppercase_false(self) -> None:
        """'FALSE' (uppercase) is recognized as false."""
        with patch.dict(
            "os.environ", {_ENV_TEMPER_OTEL_INSTRUMENT_HTTPX: "FALSE"}, clear=True
        ):
            result = _is_instrumentation_enabled(
                _ENV_TEMPER_OTEL_INSTRUMENT_HTTPX, default_enabled=True
            )
        assert result is False

    def test_case_insensitive_mixed_case_true(self) -> None:
        """'True' (mixed case) is recognized as true."""
        with patch.dict(
            "os.environ", {_ENV_TEMPER_OTEL_INSTRUMENT_HTTPX: "True"}, clear=True
        ):
            result = _is_instrumentation_enabled(
                _ENV_TEMPER_OTEL_INSTRUMENT_HTTPX, default_enabled=False
            )
        assert result is True

    # --- Unknown values fall back to default ---

    def test_unknown_value_falls_back_to_default_enabled_true(self) -> None:
        """Unknown value falls back to default_enabled (True)."""
        with patch.dict(
            "os.environ", {_ENV_TEMPER_OTEL_INSTRUMENT_HTTPX: "maybe"}, clear=True
        ):
            result = _is_instrumentation_enabled(
                _ENV_TEMPER_OTEL_INSTRUMENT_HTTPX, default_enabled=True
            )
        assert result is True

    def test_unknown_value_falls_back_to_default_enabled_false(self) -> None:
        """Unknown value falls back to default_enabled (False)."""
        with patch.dict(
            "os.environ", {_ENV_TEMPER_OTEL_INSTRUMENT_HTTPX: "maybe"}, clear=True
        ):
            result = _is_instrumentation_enabled(
                _ENV_TEMPER_OTEL_INSTRUMENT_HTTPX, default_enabled=False
            )
        assert result is False
