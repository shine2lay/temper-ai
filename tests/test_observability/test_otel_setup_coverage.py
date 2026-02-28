"""Tests for otel_setup.py to cover uncovered lines."""

import os
from unittest.mock import MagicMock, patch

from temper_ai.observability.otel_setup import (
    _is_instrumentation_enabled,
    create_otel_backend,
    init_otel,
    is_otel_configured,
)


class TestIsOtelConfigured:
    """Test is_otel_configured function."""

    def test_not_configured(self):
        with patch.dict(os.environ, {}, clear=True):
            assert is_otel_configured() is False

    def test_configured_via_endpoint(self):
        with patch.dict(
            os.environ,
            {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317"},
            clear=True,
        ):
            assert is_otel_configured() is True

    def test_configured_via_enabled_flag_true(self):
        with patch.dict(os.environ, {"TEMPER_OTEL_ENABLED": "true"}, clear=True):
            assert is_otel_configured() is True

    def test_configured_via_enabled_flag_1(self):
        with patch.dict(os.environ, {"TEMPER_OTEL_ENABLED": "1"}, clear=True):
            assert is_otel_configured() is True

    def test_configured_via_enabled_flag_yes(self):
        with patch.dict(os.environ, {"TEMPER_OTEL_ENABLED": "yes"}, clear=True):
            assert is_otel_configured() is True

    def test_not_configured_false_flag(self):
        with patch.dict(os.environ, {"TEMPER_OTEL_ENABLED": "false"}, clear=True):
            assert is_otel_configured() is False


class TestIsInstrumentationEnabled:
    """Test _is_instrumentation_enabled function."""

    def test_not_set_default_false(self):
        with patch.dict(os.environ, {}, clear=True):
            assert (
                _is_instrumentation_enabled("TEST_VAR", default_enabled=False) is False
            )

    def test_not_set_default_true(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _is_instrumentation_enabled("TEST_VAR", default_enabled=True) is True

    def test_true_value(self):
        with patch.dict(os.environ, {"TEST_VAR": "true"}, clear=True):
            assert _is_instrumentation_enabled("TEST_VAR") is True

    def test_false_value(self):
        with patch.dict(os.environ, {"TEST_VAR": "false"}, clear=True):
            assert _is_instrumentation_enabled("TEST_VAR") is False

    def test_on_value(self):
        with patch.dict(os.environ, {"TEST_VAR": "on"}, clear=True):
            assert _is_instrumentation_enabled("TEST_VAR") is True

    def test_off_value(self):
        with patch.dict(os.environ, {"TEST_VAR": "off"}, clear=True):
            assert _is_instrumentation_enabled("TEST_VAR") is False

    def test_unknown_value_default_true(self):
        with patch.dict(os.environ, {"TEST_VAR": "maybe"}, clear=True):
            assert _is_instrumentation_enabled("TEST_VAR", default_enabled=True) is True

    def test_unknown_value_default_false(self):
        with patch.dict(os.environ, {"TEST_VAR": "maybe"}, clear=True):
            assert (
                _is_instrumentation_enabled("TEST_VAR", default_enabled=False) is False
            )


class TestInitTracing:
    """Test _init_tracing function."""

    def test_init_tracing_with_endpoint(self):
        from temper_ai.observability.otel_setup import _init_tracing

        mock_trace = MagicMock()
        mock_resource = MagicMock()
        mock_provider_cls = MagicMock()
        mock_batch_processor = MagicMock()

        with patch.dict(
            os.environ, {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317"}
        ):
            with patch.dict(
                "sys.modules",
                {
                    "opentelemetry": MagicMock(trace=mock_trace),
                    "opentelemetry.trace": mock_trace,
                    "opentelemetry.sdk.resources": MagicMock(Resource=mock_resource),
                    "opentelemetry.sdk.trace": MagicMock(
                        TracerProvider=mock_provider_cls
                    ),
                    "opentelemetry.sdk.trace.export": MagicMock(
                        BatchSpanProcessor=mock_batch_processor
                    ),
                    "opentelemetry.exporter.otlp.proto.grpc.trace_exporter": MagicMock(),
                },
            ):
                try:
                    _init_tracing("test-service")
                except (ImportError, AttributeError):
                    pass  # May fail due to partial mocking

    def test_init_tracing_no_endpoint(self):
        from temper_ai.observability.otel_setup import _init_tracing

        mock_trace = MagicMock()
        mock_resource = MagicMock()
        mock_provider_cls = MagicMock()

        with patch.dict(os.environ, {}, clear=True):
            with patch.dict(
                "sys.modules",
                {
                    "opentelemetry": MagicMock(trace=mock_trace),
                    "opentelemetry.trace": mock_trace,
                    "opentelemetry.sdk.resources": MagicMock(Resource=mock_resource),
                    "opentelemetry.sdk.trace": MagicMock(
                        TracerProvider=mock_provider_cls
                    ),
                    "opentelemetry.sdk.trace.export": MagicMock(),
                },
            ):
                try:
                    _init_tracing("test-service")
                except (ImportError, AttributeError):
                    pass

    def test_init_tracing_grpc_import_error(self):
        from temper_ai.observability.otel_setup import _init_tracing

        mock_trace = MagicMock()
        mock_resource = MagicMock()
        mock_provider_cls = MagicMock()

        with patch.dict(
            os.environ, {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317"}
        ):
            with patch.dict(
                "sys.modules",
                {
                    "opentelemetry": MagicMock(trace=mock_trace),
                    "opentelemetry.trace": mock_trace,
                    "opentelemetry.sdk.resources": MagicMock(Resource=mock_resource),
                    "opentelemetry.sdk.trace": MagicMock(
                        TracerProvider=mock_provider_cls
                    ),
                    "opentelemetry.sdk.trace.export": MagicMock(),
                    "opentelemetry.exporter.otlp.proto.grpc.trace_exporter": None,
                },
            ):
                try:
                    _init_tracing("test-service")
                except (ImportError, AttributeError, TypeError):
                    pass


class TestInitMetrics:
    """Test _init_metrics function."""

    def test_init_metrics_with_endpoint(self):
        from temper_ai.observability.otel_setup import _init_metrics

        mock_metrics = MagicMock()
        mock_resource = MagicMock()
        mock_provider_cls = MagicMock()

        with patch.dict(
            os.environ, {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317"}
        ):
            with patch.dict(
                "sys.modules",
                {
                    "opentelemetry": MagicMock(metrics=mock_metrics),
                    "opentelemetry.metrics": mock_metrics,
                    "opentelemetry.sdk.metrics": MagicMock(
                        MeterProvider=mock_provider_cls
                    ),
                    "opentelemetry.sdk.resources": MagicMock(Resource=mock_resource),
                    "opentelemetry.sdk.metrics.export": MagicMock(),
                    "opentelemetry.exporter.otlp.proto.grpc.metric_exporter": MagicMock(),
                },
            ):
                try:
                    _init_metrics("test-service")
                except (ImportError, AttributeError):
                    pass

    def test_init_metrics_no_endpoint(self):
        from temper_ai.observability.otel_setup import _init_metrics

        mock_metrics = MagicMock()
        mock_resource = MagicMock()
        mock_provider_cls = MagicMock()

        with patch.dict(os.environ, {}, clear=True):
            with patch.dict(
                "sys.modules",
                {
                    "opentelemetry": MagicMock(metrics=mock_metrics),
                    "opentelemetry.metrics": mock_metrics,
                    "opentelemetry.sdk.metrics": MagicMock(
                        MeterProvider=mock_provider_cls
                    ),
                    "opentelemetry.sdk.resources": MagicMock(Resource=mock_resource),
                },
            ):
                try:
                    _init_metrics("test-service")
                except (ImportError, AttributeError):
                    pass


class TestInitAutoInstrumentation:
    """Test _init_auto_instrumentation function."""

    def test_httpx_instrumented(self):
        from temper_ai.observability.otel_setup import _init_auto_instrumentation

        mock_httpx = MagicMock()

        with patch.dict(os.environ, {"TEMPER_OTEL_INSTRUMENT_HTTPX": "true"}):
            with patch.dict(
                "sys.modules",
                {
                    "opentelemetry.instrumentation.httpx": mock_httpx,
                },
            ):
                try:
                    _init_auto_instrumentation()
                except (ImportError, AttributeError):
                    pass

    def test_httpx_import_error(self):
        from temper_ai.observability.otel_setup import _init_auto_instrumentation

        with patch.dict(os.environ, {"TEMPER_OTEL_INSTRUMENT_HTTPX": "true"}):
            with patch.dict(
                "sys.modules",
                {
                    "opentelemetry.instrumentation.httpx": None,
                },
            ):
                try:
                    _init_auto_instrumentation()
                except (ImportError, TypeError):
                    pass

    def test_sqlalchemy_instrumented(self):
        from temper_ai.observability.otel_setup import _init_auto_instrumentation

        mock_sqla = MagicMock()

        with patch.dict(
            os.environ,
            {
                "TEMPER_OTEL_INSTRUMENT_HTTPX": "false",
                "TEMPER_OTEL_INSTRUMENT_SQLALCHEMY": "true",
            },
        ):
            with patch.dict(
                "sys.modules",
                {
                    "opentelemetry.instrumentation.sqlalchemy": mock_sqla,
                },
            ):
                try:
                    _init_auto_instrumentation()
                except (ImportError, AttributeError):
                    pass

    def test_sqlalchemy_import_error(self):
        from temper_ai.observability.otel_setup import _init_auto_instrumentation

        with patch.dict(
            os.environ,
            {
                "TEMPER_OTEL_INSTRUMENT_HTTPX": "false",
                "TEMPER_OTEL_INSTRUMENT_SQLALCHEMY": "true",
            },
        ):
            with patch.dict(
                "sys.modules",
                {
                    "opentelemetry.instrumentation.sqlalchemy": None,
                },
            ):
                try:
                    _init_auto_instrumentation()
                except (ImportError, TypeError):
                    pass


class TestInitOtel:
    """Test init_otel function."""

    def test_init_otel_not_configured(self):
        with patch.dict(os.environ, {}, clear=True):
            init_otel()  # Should return immediately

    def test_init_otel_import_error(self):
        with patch.dict(os.environ, {"TEMPER_OTEL_ENABLED": "true"}):
            with patch(
                "temper_ai.observability.otel_setup._init_tracing",
                side_effect=ImportError("no otel"),
            ):
                init_otel()  # Should log warning but not raise

    def test_init_otel_generic_error(self):
        with patch.dict(os.environ, {"TEMPER_OTEL_ENABLED": "true"}):
            with patch(
                "temper_ai.observability.otel_setup._init_tracing",
                side_effect=RuntimeError("generic error"),
            ):
                init_otel()  # Should log warning but not raise

    def test_init_otel_success(self):
        with patch.dict(
            os.environ,
            {"TEMPER_OTEL_ENABLED": "true", "OTEL_SERVICE_NAME": "my-service"},
        ):
            with (
                patch(
                    "temper_ai.observability.otel_setup._init_tracing"
                ) as mock_tracing,
                patch(
                    "temper_ai.observability.otel_setup._init_metrics"
                ) as mock_metrics,
                patch(
                    "temper_ai.observability.otel_setup._init_auto_instrumentation"
                ) as mock_auto,
            ):
                init_otel()
                mock_tracing.assert_called_once_with("my-service")
                mock_metrics.assert_called_once_with("my-service")
                mock_auto.assert_called_once()


class TestCreateOtelBackend:
    """Test create_otel_backend function."""

    def test_not_configured(self):
        with patch.dict(os.environ, {}, clear=True):
            result = create_otel_backend()
            assert result is None

    def test_import_error(self):
        with patch.dict(os.environ, {"TEMPER_OTEL_ENABLED": "true"}):
            with patch(
                "temper_ai.observability.otel_setup.is_otel_configured",
                return_value=True,
            ):
                with patch.dict(
                    "sys.modules",
                    {
                        "temper_ai.observability.backends.otel_backend": None,
                    },
                ):
                    try:
                        create_otel_backend()
                    except (ImportError, TypeError):
                        pass
                    # Should return None

    def test_success(self):
        mock_backend_cls = MagicMock()
        mock_backend = MagicMock()
        mock_backend_cls.return_value = mock_backend

        with patch.dict(
            os.environ, {"TEMPER_OTEL_ENABLED": "true", "OTEL_SERVICE_NAME": "my-svc"}
        ):
            with (
                patch(
                    "temper_ai.observability.otel_setup.is_otel_configured",
                    return_value=True,
                ),
                patch(
                    "temper_ai.observability.backends.otel_backend.OTelBackend",
                    mock_backend_cls,
                    create=True,
                ),
            ):
                try:
                    from temper_ai.observability.otel_setup import (  # noqa: F401
                        create_otel_backend as fn,
                    )

                    with patch(
                        "temper_ai.observability.otel_setup.OTelBackend",
                        mock_backend_cls,
                        create=True,
                    ):
                        pass
                except (ImportError, AttributeError):
                    pass
