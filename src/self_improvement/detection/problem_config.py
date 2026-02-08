"""
Configuration for problem detection thresholds.
"""

from dataclasses import dataclass

from src.constants.limits import DEFAULT_BATCH_SIZE

# Default detection thresholds (relative percentage changes)
DEFAULT_QUALITY_RELATIVE_THRESHOLD = 0.10  # 10% quality degradation triggers detection
DEFAULT_QUALITY_ABSOLUTE_THRESHOLD = 0.05  # 5-point absolute quality drop
DEFAULT_COST_RELATIVE_THRESHOLD = 0.30  # 30% cost increase triggers detection
DEFAULT_COST_ABSOLUTE_THRESHOLD = 0.10  # $0.10 absolute cost increase
DEFAULT_SPEED_RELATIVE_THRESHOLD = 0.50  # 50% speed decrease triggers detection

# Severity classification thresholds
SEVERITY_CRITICAL_THRESHOLD = 0.50  # >50% degradation = CRITICAL
SEVERITY_HIGH_THRESHOLD = 0.30  # >30% degradation = HIGH
SEVERITY_MEDIUM_THRESHOLD = 0.15  # >15% degradation = MEDIUM
SEVERITY_LOW_THRESHOLD = 0.05  # >5% degradation = LOW

# Validation bounds for threshold configuration
MAX_COST_RELATIVE_THRESHOLD = 5  # Maximum allowed cost increase threshold (500%)


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
    quality_relative_threshold: float = DEFAULT_QUALITY_RELATIVE_THRESHOLD
    quality_absolute_threshold: float = DEFAULT_QUALITY_ABSOLUTE_THRESHOLD

    # Cost detection thresholds
    cost_relative_threshold: float = DEFAULT_COST_RELATIVE_THRESHOLD
    cost_absolute_threshold: float = DEFAULT_COST_ABSOLUTE_THRESHOLD

    # Speed detection thresholds
    speed_relative_threshold: float = DEFAULT_SPEED_RELATIVE_THRESHOLD
    speed_absolute_threshold: float = 2.0   # 2 second increase

    # Severity bands
    severity_critical_threshold: float = SEVERITY_CRITICAL_THRESHOLD
    severity_high_threshold: float = SEVERITY_HIGH_THRESHOLD
    severity_medium_threshold: float = SEVERITY_MEDIUM_THRESHOLD
    severity_low_threshold: float = SEVERITY_LOW_THRESHOLD

    # Data quality requirements
    min_executions_for_detection: int = DEFAULT_BATCH_SIZE

    def __post_init__(self) -> None:
        """Validate configuration."""
        if not (0 < self.quality_relative_threshold < 1):
            raise ValueError("quality_relative_threshold must be in (0, 1)")
        if not (0 < self.cost_relative_threshold < MAX_COST_RELATIVE_THRESHOLD):
            raise ValueError(f"cost_relative_threshold must be in (0, {MAX_COST_RELATIVE_THRESHOLD})")
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
