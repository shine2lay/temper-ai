"""Self-monitoring for the observability pipeline.

Checks buffer health (DLQ size, retry queue, pending IDs) and optionally
fires alerts when thresholds are breached.
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from temper_ai.shared.constants.limits import (
    THRESHOLD_LARGE_COUNT,
    THRESHOLD_MEDIUM_COUNT,
)

logger = logging.getLogger(__name__)

# Health check interval default (seconds)
DEFAULT_CHECK_INTERVAL_SECONDS = 60


@dataclass
class HealthStatus:
    """Result of an observability health check."""

    healthy: bool
    issues: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


class ObservabilityHealthMonitor:
    """Monitors the health of the observability pipeline.

    Periodically checks buffer stats and reports issues:
    - DLQ size > THRESHOLD_MEDIUM_COUNT (10): warning
    - DLQ size > THRESHOLD_LARGE_COUNT (100): critical
    - Retry queue > THRESHOLD_MEDIUM_COUNT (10): warning
    - Pending IDs > THRESHOLD_LARGE_COUNT (100): warning
    """

    def __init__(
        self,
        buffer: Any | None = None,
        alert_manager: Any | None = None,
        check_interval: int = DEFAULT_CHECK_INTERVAL_SECONDS,
        backend: Any | None = None,
        db_session_factory: Callable | None = None,
    ):
        self._buffer = buffer
        self._alert_manager = alert_manager
        self._check_interval = check_interval
        self._backend_ref = backend
        self._db_session_factory = db_session_factory
        self._check_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def check_health(self) -> HealthStatus:
        """Check current health of the observability pipeline."""
        issues: list[str] = []
        stats: dict[str, Any] = {}

        # DB connectivity check
        if self._db_session_factory is not None:
            issues.extend(_check_db_health(self._db_session_factory))

        # Backend responsiveness check
        if self._backend_ref is not None:
            issues.extend(_check_backend_health(self._backend_ref))

        # Buffer threshold check (existing)
        if self._buffer is not None:
            stats = self._buffer.get_stats()
            issues.extend(_evaluate_thresholds(stats))

        healthy = len(issues) == 0
        return HealthStatus(healthy=healthy, issues=issues, stats=stats)

    def start_periodic_check(self) -> None:
        """Start background health check thread."""
        if self._check_thread and self._check_thread.is_alive():
            return
        self._stop_event.clear()
        self._check_thread = threading.Thread(target=self._check_loop, daemon=True)
        self._check_thread.start()

    def stop(self) -> None:
        """Stop background health check thread."""
        self._stop_event.set()
        if self._check_thread and self._check_thread.is_alive():
            self._check_thread.join(timeout=self._check_interval + 1)
            self._check_thread = None

    def _check_loop(self) -> None:
        """Background loop for periodic health checks."""
        while not self._stop_event.wait(
            timeout=self._check_interval
        ):  # intentional polling interval
            try:
                status = self.check_health()
                if not status.healthy:
                    for issue in status.issues:
                        logger.warning("Observability health: %s", issue)
                    self._fire_health_alert(status)
            except Exception:  # noqa: BLE001 -- health check must never crash
                logger.debug("Health check failed", exc_info=True)

    def _fire_health_alert(self, status: HealthStatus) -> None:
        """Fire alert for unhealthy status. Best-effort."""
        if not self._alert_manager:
            return
        try:
            self._alert_manager.check_metric(
                metric_type="observability_health",
                value=len(status.issues),
                context={"issues": status.issues},
            )
        except Exception:  # noqa: BLE001 -- alerting must never disrupt
            logger.debug("Health alert failed", exc_info=True)


def _check_db_health(db_session_factory: Any) -> list[str]:
    """Check database connectivity. Returns list of issues."""
    import sqlalchemy as sa  # lazy import to avoid top-level dep

    issues: list[str] = []
    try:
        session = db_session_factory()
        try:
            session.execute(sa.text("SELECT 1"))
        finally:
            session.close()
    except Exception as exc:  # noqa: BLE001 -- health check best-effort
        issues.append(f"Database connectivity failed: {type(exc).__name__}")
    return issues


def _check_backend_health(backend: Any) -> list[str]:
    """Check backend responsiveness. Returns list of issues."""
    issues: list[str] = []
    try:
        if hasattr(backend, "get_stats"):
            backend.get_stats()
    except Exception as exc:  # noqa: BLE001 -- health check best-effort
        issues.append(f"Backend health check failed: {type(exc).__name__}")
    return issues


def _format_threshold_warning(
    label: str, value: int, threshold: int, severity: str = "WARNING"
) -> str:
    """Format a threshold breach message.

    Args:
        label: Human-readable metric name (e.g. "DLQ size").
        value: Current metric value.
        threshold: Threshold that was exceeded.
        severity: Severity tag (e.g. "WARNING", "CRITICAL").

    Returns:
        Formatted warning string.
    """
    return f"{severity}: {label} ({value}) exceeds {threshold}"


def _evaluate_thresholds(stats: dict[str, Any]) -> list[str]:
    """Evaluate buffer stats against health thresholds."""
    issues: list[str] = []

    dlq_size = stats.get("dlq_size", 0)
    if dlq_size > THRESHOLD_LARGE_COUNT:
        issues.append(
            _format_threshold_warning(
                "DLQ size", dlq_size, THRESHOLD_LARGE_COUNT, "CRITICAL"
            )
        )
    elif dlq_size > THRESHOLD_MEDIUM_COUNT:
        issues.append(
            _format_threshold_warning("DLQ size", dlq_size, THRESHOLD_MEDIUM_COUNT)
        )

    retry_size = stats.get("retry_queue_size", 0)
    if retry_size > THRESHOLD_MEDIUM_COUNT:
        issues.append(
            _format_threshold_warning("Retry queue", retry_size, THRESHOLD_MEDIUM_COUNT)
        )

    pending_count = stats.get("pending_ids", 0)
    if pending_count > THRESHOLD_LARGE_COUNT:
        issues.append(
            _format_threshold_warning(
                "Pending IDs", pending_count, THRESHOLD_LARGE_COUNT
            )
        )

    return issues
