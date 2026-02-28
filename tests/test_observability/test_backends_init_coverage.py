"""Tests for backends/__init__.py to cover lazy import logic."""

import pytest


class TestBackendsInit:
    """Test lazy imports in backends/__init__.py."""

    def test_import_composite_backend(self):
        """Test lazy import of CompositeBackend."""
        from temper_ai.observability.backends import CompositeBackend

        assert CompositeBackend is not None

    def test_import_otel_backend(self):
        """Test lazy import of OTelBackend."""
        try:
            from temper_ai.observability.backends import OTelBackend

            assert OTelBackend is not None
        except ImportError:
            # OK if opentelemetry not installed
            pass

    def test_import_nonexistent_attribute(self):
        """Test AttributeError for unknown attributes."""
        import temper_ai.observability.backends as backends_mod

        with pytest.raises(AttributeError, match="has no attribute"):
            _ = backends_mod.NonExistentClass

    def test_import_sql_backend(self):
        """Test direct import of SQL backend."""
        from temper_ai.observability.backends import SQLObservabilityBackend

        assert SQLObservabilityBackend is not None

    def test_import_prometheus_backend(self):
        """Test direct import of Prometheus backend."""
        from temper_ai.observability.backends import PrometheusObservabilityBackend

        assert PrometheusObservabilityBackend is not None

    def test_import_s3_backend(self):
        """Test direct import of S3 backend."""
        from temper_ai.observability.backends import S3ObservabilityBackend

        assert S3ObservabilityBackend is not None
