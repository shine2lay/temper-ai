"""Abstract base class and registry for metric collectors."""

import logging
from abc import ABC, abstractmethod
from threading import RLock
from typing import Any, Dict, List, Optional, Protocol

from src.self_improvement.constants import MAX_EXTRACTION_SCORE, MIN_EXTRACTION_SCORE
from src.self_improvement.metrics.types import SIMetricType

logger = logging.getLogger(__name__)


class ExecutionProtocol(Protocol):
    """Minimal interface for execution objects used by metric collectors.

    This protocol defines the minimum attributes that an execution object
    must have to be used with MetricCollectors. Using a Protocol allows
    collectors to work with any execution-like object without tight coupling
    to specific implementation classes.

    Attributes:
        id: Unique identifier for the execution
        status: Execution status (e.g., "completed", "failed", "in_progress")
    """
    id: str
    status: str


class MetricCollector(ABC):
    """Abstract base class for all metric collectors.

    This class defines the contract that all metric collectors must implement.
    Collectors are responsible for extracting specific metrics from agent
    executions and normalizing them to a 0-1 scale.

    All metric collectors must:
    1. Provide a unique metric_name
    2. Specify their metric_type (AUTOMATIC, DERIVED, or CUSTOM)
    3. Implement collect() to compute the metric value
    4. Implement is_applicable() to determine if metric applies to an execution

    Example:
        >>> class SuccessRateCollector(MetricCollector):
        ...     @property
        ...     def metric_name(self) -> str:
        ...         return "success_rate"
        ...
        ...     @property
        ...     def metric_type(self) -> SIMetricType:
        ...         return SIMetricType.AUTOMATIC
        ...
        ...     def collect(self, execution) -> Optional[float]:
        ...         return 1.0 if execution.status == "completed" else 0.0
        ...
        ...     def is_applicable(self, execution) -> bool:
        ...         return True  # Always applicable
    """

    @property
    @abstractmethod
    def metric_name(self) -> str:
        """Unique identifier for this metric.

        Returns:
            str: A unique name for this metric (e.g., 'extraction_quality',
                 'success_rate', 'cost_efficiency')

        Note:
            Metric names should be lowercase with underscores separating words.
            They must be unique across all registered collectors.
        """
        pass

    @property
    @abstractmethod
    def metric_type(self) -> SIMetricType:
        """Classification of how this metric is computed.

        Returns:
            SIMetricType: One of AUTOMATIC, DERIVED, or CUSTOM

        Note:
            - AUTOMATIC: Extracted from AgentExecution metadata
            - DERIVED: Computed from logs/traces
            - CUSTOM: User-defined computation logic
        """
        pass

    @abstractmethod
    def collect(self, execution: ExecutionProtocol) -> Optional[float]:
        """Extract metric value from an agent execution.

        Args:
            execution: Execution object containing execution metadata

        Returns:
            float: Metric value normalized to [METRIC_MIN, METRIC_MAX] scale, where:
                   - METRIC_MIN = worst possible value
                   - METRIC_MAX = best possible value
            None: If metric cannot be computed or is not applicable

        Raises:
            ValueError: If computed value is outside [0.0, 1.0] range

        Note:
            Collectors should return None rather than raising exceptions
            when metrics cannot be computed. The registry will handle
            logging and error recovery.
        """
        pass

    @abstractmethod
    def is_applicable(self, execution: ExecutionProtocol) -> bool:
        """Check if this metric applies to the given execution.

        Args:
            execution: Execution object to check

        Returns:
            bool: True if metric can be computed, False otherwise

        Note:
            This method should be cheap to execute as it's called for
            every collector on every execution. Expensive checks should
            be deferred to collect().
        """
        pass

    @property
    def collector_version(self) -> str:
        """Version string for this collector implementation.

        Returns:
            str: Semantic version (default: "1.0")

        Note:
            Override this property when making breaking changes to
            metric computation logic to enable version-aware queries.
        """
        return "1.0"


class MetricRegistry:
    """Central registry for managing metric collectors.

    The MetricRegistry maintains a collection of MetricCollector instances
    and provides methods to register, unregister, and execute collectors.
    It handles error recovery and ensures that collector failures don't
    prevent other collectors from running.

    The registry is thread-safe and can be used concurrently by multiple
    threads.

    Example:
        >>> registry = MetricRegistry()
        >>> registry.register(SuccessRateCollector())
        >>> registry.register(CostCollector(max_cost_usd=1.0))
        >>>
        >>> metrics = registry.collect_all(execution)
        >>> # Returns: {"success_rate": 1.0, "cost_usd": 0.5}
    """

    def __init__(self):
        """Initialize an empty metric registry."""
        self._collectors: Dict[str, MetricCollector] = {}
        self._lock = RLock()  # Thread-safe registration/collection
        logger.info("Initialized MetricRegistry")

    def register(self, collector: MetricCollector) -> None:
        """Register a metric collector.

        Args:
            collector: MetricCollector instance to register

        Raises:
            TypeError: If collector is not a MetricCollector instance
            ValueError: If a collector with the same metric_name is already
                        registered

        Note:
            Collectors can be registered at any time, even after collection
            has begun. However, they will only apply to future executions.
        """
        if not isinstance(collector, MetricCollector):
            raise TypeError(
                f"collector must be a MetricCollector instance, "
                f"got {type(collector).__name__}"
            )

        with self._lock:
            metric_name = collector.metric_name

            if metric_name in self._collectors:
                raise ValueError(
                    f"Collector with metric_name '{metric_name}' is already "
                    f"registered. Unregister the existing collector first."
                )

            self._collectors[metric_name] = collector
            logger.info(
                f"Registered collector: {metric_name} "
                f"({collector.metric_type.value})"
            )

    def unregister(self, metric_name: str) -> None:
        """Unregister a metric collector by name.

        Args:
            metric_name: Name of the metric collector to remove

        Raises:
            KeyError: If no collector with the given name is registered

        Note:
            Unregistering a collector does not affect already-collected
            metrics in the database.
        """
        with self._lock:
            if metric_name not in self._collectors:
                raise KeyError(
                    f"No collector registered with metric_name '{metric_name}'"
                )

            del self._collectors[metric_name]
            logger.info(f"Unregistered collector: {metric_name}")

    def collect_all(self, execution: ExecutionProtocol) -> Dict[str, float]:
        """Execute all applicable collectors for an execution.

        This method iterates through all registered collectors, checks if
        they're applicable to the execution, and collects their metric values.
        Collector failures are logged but don't prevent other collectors from
        running.

        Args:
            execution: Execution object to collect metrics from

        Returns:
            Dict[str, float]: Mapping of metric_name to metric_value for all
                              successfully collected metrics. Failed or
                              non-applicable collectors are omitted.

        Note:
            This method is thread-safe and can be called concurrently for
            different executions.
        """
        metrics = {}

        with self._lock:
            collectors = list(self._collectors.items())

        for metric_name, collector in collectors:
            try:
                # Check if collector applies to this execution
                if not collector.is_applicable(execution):
                    logger.debug(
                        f"Collector '{metric_name}' not applicable for "
                        f"execution {getattr(execution, 'id', 'unknown')}"
                    )
                    continue

                # Collect metric value
                value = collector.collect(execution)

                # Store value if successfully collected
                if value is not None:
                    # Validate value is in valid range
                    if not (MIN_EXTRACTION_SCORE <= value <= MAX_EXTRACTION_SCORE):
                        logger.error(
                            f"Collector '{metric_name}' returned invalid value "
                            f"{value} (must be in [{MIN_EXTRACTION_SCORE}, {MAX_EXTRACTION_SCORE}])"
                        )
                        continue

                    metrics[metric_name] = value
                    logger.debug(
                        f"Collected {metric_name}={value:.3f} for "
                        f"execution {getattr(execution, 'id', 'unknown')}"
                    )
                else:
                    logger.debug(
                        f"Collector '{metric_name}' returned None for "
                        f"execution {getattr(execution, 'id', 'unknown')}"
                    )

            except Exception as e:
                # Log error but continue with other collectors
                logger.error(
                    f"Collector '{metric_name}' failed for execution "
                    f"{getattr(execution, 'id', 'unknown')}: {e}",
                    exc_info=True
                )
                # Don't add to metrics dict - continue with other collectors

        logger.info(
            f"Collected {len(metrics)} metrics for execution "
            f"{getattr(execution, 'id', 'unknown')}"
        )
        return metrics

    def get_collector(self, metric_name: str) -> Optional[MetricCollector]:
        """Get a registered collector by name.

        Args:
            metric_name: Name of the metric collector

        Returns:
            MetricCollector: The collector instance if registered, None otherwise
        """
        with self._lock:
            return self._collectors.get(metric_name)

    def list_collectors(self) -> List[str]:
        """Get a list of all registered collector names.

        Returns:
            List[str]: Sorted list of registered metric names
        """
        with self._lock:
            return sorted(self._collectors.keys())

    def health_check(self) -> Dict[str, Any]:
        """Check the health of the metric registry.

        Returns:
            Dict[str, Any]: Health status including:
                - collectors_registered: Number of registered collectors
                - collector_names: List of registered collector names

        Note:
            This method can be used for monitoring and debugging.
        """
        with self._lock:
            return {
                "collectors_registered": len(self._collectors),
                "collector_names": sorted(self._collectors.keys()),
            }
