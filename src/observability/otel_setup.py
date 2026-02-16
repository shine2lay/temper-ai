"""Environment-variable-gated OpenTelemetry initialisation.

Reads standard OTEL env vars plus ``MAF_OTEL_ENABLED`` to decide whether
to activate tracing and metrics.  When the ``opentelemetry`` packages are
not installed, every public function in this module is a safe no-op.

Typical activation::

    export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
    maf run configs/workflows/quick_decision_demo.yaml --input examples/demo_input.yaml

Or explicitly::

    export MAF_OTEL_ENABLED=true
    export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
    export OTEL_SERVICE_NAME=maf
"""
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Standard env vars
_ENV_OTEL_ENDPOINT = "OTEL_EXPORTER_OTLP_ENDPOINT"
_ENV_OTEL_SERVICE_NAME = "OTEL_SERVICE_NAME"
_ENV_MAF_OTEL_ENABLED = "MAF_OTEL_ENABLED"
_ENV_MAF_OTEL_INSTRUMENT_HTTPX = "MAF_OTEL_INSTRUMENT_HTTPX"
_ENV_MAF_OTEL_INSTRUMENT_SQLALCHEMY = "MAF_OTEL_INSTRUMENT_SQLALCHEMY"

# Defaults
_DEFAULT_SERVICE_NAME = "maf"

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def is_otel_configured() -> bool:
    """Return True if OTEL should be activated.

    Activation requires either:
    * ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set, **or**
    * ``MAF_OTEL_ENABLED`` is truthy (``1`` / ``true`` / ``yes``).
    """
    if os.environ.get(_ENV_MAF_OTEL_ENABLED, "").lower() in _TRUE_VALUES:
        return True
    return bool(os.environ.get(_ENV_OTEL_ENDPOINT))


def _init_tracing(service_name: str) -> None:
    """Configure the OTEL tracer provider with OTLP exporter."""
    from opentelemetry import trace as otel_trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    endpoint = os.environ.get(_ENV_OTEL_ENDPOINT)
    if endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )

            exporter = OTLPSpanExporter(endpoint=endpoint)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info("OTEL tracing → %s (service=%s)", endpoint, service_name)
        except ImportError:
            logger.warning(
                "OTLP gRPC exporter not installed. "
                "Install: pip install opentelemetry-exporter-otlp-proto-grpc"
            )

    otel_trace.set_tracer_provider(provider)


def _init_metrics(service_name: str) -> None:
    """Configure the OTEL meter provider with OTLP exporter."""
    from opentelemetry import metrics as otel_metrics
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.resources import Resource

    resource = Resource.create({"service.name": service_name})
    provider = MeterProvider(resource=resource)

    endpoint = os.environ.get(_ENV_OTEL_ENDPOINT)
    if endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                OTLPMetricExporter,
            )
            from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

            reader = PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=endpoint))
            provider = MeterProvider(resource=resource, metric_readers=[reader])
            logger.info("OTEL metrics → %s", endpoint)
        except ImportError:
            logger.warning(
                "OTLP gRPC metric exporter not installed. "
                "Install: pip install opentelemetry-exporter-otlp-proto-grpc"
            )

    otel_metrics.set_meter_provider(provider)


def _init_auto_instrumentation() -> None:
    """Optionally instrument httpx and SQLAlchemy."""
    if os.environ.get(_ENV_MAF_OTEL_INSTRUMENT_HTTPX, "").lower() in _TRUE_VALUES:
        try:
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

            HTTPXClientInstrumentor().instrument()
            logger.info("OTEL auto-instrumented httpx")
        except ImportError:
            logger.debug("httpx OTEL instrumentation not available")

    if os.environ.get(_ENV_MAF_OTEL_INSTRUMENT_SQLALCHEMY, "").lower() in _TRUE_VALUES:
        try:
            from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

            SQLAlchemyInstrumentor().instrument()
            logger.info("OTEL auto-instrumented SQLAlchemy")
        except ImportError:
            logger.debug("SQLAlchemy OTEL instrumentation not available")


def init_otel() -> None:
    """Initialise OTEL tracing + metrics if configured.

    Safe to call unconditionally — returns immediately when OTEL
    packages are not installed or env vars are absent.
    """
    if not is_otel_configured():
        return

    service_name = os.environ.get(_ENV_OTEL_SERVICE_NAME, _DEFAULT_SERVICE_NAME)

    try:
        _init_tracing(service_name)
        _init_metrics(service_name)
        _init_auto_instrumentation()
    except ImportError:
        logger.warning(
            "OpenTelemetry SDK not installed. "
            "Install with: pip install -e '.[otel]'"
        )
    except Exception:  # noqa: BLE001 — OTEL init must never crash the app
        logger.warning("OTEL initialisation failed", exc_info=True)


def create_otel_backend() -> Optional["OTelBackend"]:  # type: ignore[name-defined]  # noqa: F821
    """Create an OTelBackend instance, or None if OTEL is not available."""
    if not is_otel_configured():
        return None

    try:
        from src.observability.backends.otel_backend import OTelBackend

        service_name = os.environ.get(_ENV_OTEL_SERVICE_NAME, _DEFAULT_SERVICE_NAME)
        return OTelBackend(service_name=service_name)
    except ImportError:
        logger.debug("OTelBackend not available (opentelemetry not installed)")
        return None
