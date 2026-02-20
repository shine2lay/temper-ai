"""Tests for OTEL setup — env var detection and graceful import failure."""
import os
from unittest.mock import patch

import pytest

from temper_ai.observability.otel_setup import is_otel_configured


class TestIsOtelConfigured:
    """Test OTEL activation logic."""

    def test_not_configured_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert is_otel_configured() is False

    def test_configured_via_endpoint(self) -> None:
        with patch.dict(os.environ, {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317"}):
            assert is_otel_configured() is True

    def test_configured_via_maf_flag(self) -> None:
        with patch.dict(os.environ, {"TEMPER_OTEL_ENABLED": "true"}):
            assert is_otel_configured() is True

    def test_configured_via_maf_flag_1(self) -> None:
        with patch.dict(os.environ, {"TEMPER_OTEL_ENABLED": "1"}):
            assert is_otel_configured() is True

    def test_not_configured_with_false_flag(self) -> None:
        with patch.dict(os.environ, {"TEMPER_OTEL_ENABLED": "false"}, clear=True):
            assert is_otel_configured() is False


class TestInitOtel:
    """Test init_otel graceful failure when packages are missing."""

    def test_init_otel_noop_when_not_configured(self) -> None:
        from temper_ai.observability.otel_setup import init_otel

        with patch.dict(os.environ, {}, clear=True):
            result = init_otel()
            assert result is None  # noop when not configured

    def test_create_otel_backend_returns_none_when_not_configured(self) -> None:
        from temper_ai.observability.otel_setup import create_otel_backend

        with patch.dict(os.environ, {}, clear=True):
            assert create_otel_backend() is None
