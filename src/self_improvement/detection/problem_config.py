"""
Configuration for problem detection thresholds.
"""

from dataclasses import dataclass

from src.constants.limits import DEFAULT_BATCH_SIZE


@dataclass
class ProblemDetectionConfig:
    """
    Configuration for problem detection thresholds.

    Defines when performance changes should trigger problem detection.
    Supports both relative (percentage) and absolute thresholds.

    Design Philosophy:
    - Relative thresholds (%) catch proportional degradations
    - Absolute thresholds prevent noise on small values
    - Severity bands prioritize urgent issues

    Attributes:
        # Quality detection
        quality_relative_threshold: Min % degradation to detect (default: 0.10 = 10%)
        quality_absolute_threshold: Min absolute drop (default: 0.05)

        # Cost detection
        cost_relative_threshold: Min % increase to detect (default: 0.30 = 30%)
        cost_absolute_threshold: Min absolute increase USD (default: 0.10)

        # Speed detection
        speed_relative_threshold: Min % increase to detect (default: 0.50 = 50%)
        speed_absolute_threshold: Min absolute increase seconds (default: 2.0)

        # Severity bands (for calculating ProblemSeverity)
        severity_critical_threshold: Degradation > 50% = CRITICAL
        severity_high_threshold: Degradation > 30% = HIGH
        severity_medium_threshold: Degradation > 15% = MEDIUM
        severity_low_threshold: Degradation > 5% = LOW

        # Minimum data requirements
        min_executions_for_detection: Min samples needed (default: 50)

    Example:
        >>> # Strict configuration (sensitive to small changes)
        >>> config = ProblemDetectionConfig(
        ...     quality_relative_threshold=0.05,  # 5% degradation triggers
        ...     cost_relative_threshold=0.20,     # 20% increase triggers
        ...     speed_relative_threshold=0.30     # 30% increase triggers
        ... )

        >>> # Lenient configuration (only major changes)
        >>> config = ProblemDetectionConfig(
        ...     quality_relative_threshold=0.20,  # 20% degradation triggers
        ...     cost_relative_threshold=0.50,     # 50% increase triggers
        ...     speed_relative_threshold=1.00     # 100% increase triggers
        ... )
    """

    # Quality detection thresholds
    quality_relative_threshold: float = 0.10  # 10% degradation
    quality_absolute_threshold: float = 0.05  # 5 point drop (e.g., 0.85 → 0.80)

    # Cost detection thresholds
    cost_relative_threshold: float = 0.30  # 30% increase
    cost_absolute_threshold: float = 0.10  # $0.10 USD increase

    # Speed detection thresholds
    speed_relative_threshold: float = 0.50  # 50% increase
    speed_absolute_threshold: float = 2.0   # 2 second increase

    # Severity bands
    severity_critical_threshold: float = 0.50  # >50% = CRITICAL
    severity_high_threshold: float = 0.30      # >30% = HIGH
    severity_medium_threshold: float = 0.15    # >15% = MEDIUM
    severity_low_threshold: float = 0.05       # >5% = LOW

    # Data quality requirements
    min_executions_for_detection: int = DEFAULT_BATCH_SIZE

    def __post_init__(self):
        """Validate configuration."""
        if not (0 < self.quality_relative_threshold < 1):
            raise ValueError("quality_relative_threshold must be in (0, 1)")
        if not (0 < self.cost_relative_threshold < 5):
            raise ValueError("cost_relative_threshold must be in (0, 5)")
        if not (0 < self.speed_relative_threshold < 10):
            raise ValueError("speed_relative_threshold must be in (0, 10)")
        if self.quality_absolute_threshold < 0:
            raise ValueError("quality_absolute_threshold must be >= 0")
        if self.cost_absolute_threshold < 0:
            raise ValueError("cost_absolute_threshold must be >= 0")
        if self.speed_absolute_threshold < 0:
            raise ValueError("speed_absolute_threshold must be >= 0")
        if self.min_executions_for_detection < 1:
            raise ValueError("min_executions_for_detection must be >= 1")
