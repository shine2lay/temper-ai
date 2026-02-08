"""
Configuration for M5 Self-Improvement Loop.

Provides sensible defaults while allowing customization of all loop parameters.
"""
from dataclasses import dataclass
from typing import Optional

from src.constants.durations import (
    HOURS_PER_WEEK,
    MINUTES_PER_HOUR,
    SECONDS_PER_MINUTE,
)
from src.constants.limits import (
    DEFAULT_BATCH_SIZE,
    PERCENT_10,
    PERCENT_20,
    PERCENT_30,
    THRESHOLD_MEDIUM_COUNT,
    THRESHOLD_SMALL_COUNT,
)
from src.constants.retries import (
    DEFAULT_BACKOFF_MULTIPLIER,
    DEFAULT_MAX_RETRIES,
    MEDIUM_BACKOFF_SECONDS,
)
from src.self_improvement.constants import (
    DEFAULT_ALPHA,
    MAX_CONCURRENT_EXPERIMENTS,
    PROMPT_IMPROVEMENT_THRESHOLD,
    ROLLBACK_THRESHOLD,
)

# Loop configuration constants
DEFAULT_EXPERIMENT_TIMEOUT_HOURS = 72  # 3 days maximum for experiments
DEFAULT_ROLLBACK_MIN_EXECUTIONS = 20  # Minimum samples before checking rollback
MAX_VARIANTS_PER_EXPERIMENT_LIMIT = 5  # Maximum variants allowed in experiments


@dataclass
class LoopConfig:
    """
    Configuration for M5SelfImprovementLoop.

    Controls behavior of all 5 phases and error handling.
    """

    # Phase 1: Detection
    detection_window_hours: int = HOURS_PER_WEEK  # 7 days
    min_executions_for_detection: int = DEFAULT_BATCH_SIZE  # Minimum samples needed
    detection_threshold: float = ROLLBACK_THRESHOLD  # 10% degradation triggers detection

    # Phase 2: Analysis
    analysis_window_hours: int = HOURS_PER_WEEK  # 7 days
    min_executions_for_analysis: int = THRESHOLD_MEDIUM_COUNT  # Minimum samples for analysis

    # Phase 3: Strategy
    max_variants_per_experiment: int = MAX_CONCURRENT_EXPERIMENTS  # A/B/C/D testing (control + 3 variants)
    enable_model_variants: bool = True  # Test different LLM models
    enable_prompt_variants: bool = True  # Test different prompts
    enable_param_variants: bool = True  # Test different inference params

    # Phase 4: Experimentation
    target_samples_per_variant: int = DEFAULT_BATCH_SIZE  # Samples per variant for statistical significance
    experiment_timeout_hours: int = DEFAULT_EXPERIMENT_TIMEOUT_HOURS  # 3 days max
    min_improvement_threshold: float = PROMPT_IMPROVEMENT_THRESHOLD  # 5% minimum improvement to deploy
    statistical_significance_level: float = DEFAULT_ALPHA  # p < 0.05 for significance

    # Phase 5: Deployment
    enable_auto_deploy: bool = True  # Auto-deploy winners
    enable_auto_rollback: bool = True  # Auto-rollback on regression
    rollback_check_interval_hours: int = 24  # Check for regression daily
    deployment_confirmation_required: bool = False  # Require manual confirmation

    # Rollback thresholds (from RegressionThresholds)
    rollback_quality_drop_pct: float = float(PERCENT_10)  # 10% quality drop triggers rollback
    rollback_cost_increase_pct: float = float(PERCENT_20)  # 20% cost increase triggers rollback
    rollback_speed_increase_pct: float = float(PERCENT_30)  # 30% speed degradation triggers rollback
    rollback_min_executions: int = DEFAULT_ROLLBACK_MIN_EXECUTIONS  # Min samples before rollback check

    # Error handling
    max_retries_per_phase: int = DEFAULT_MAX_RETRIES  # Retry failed phases up to 3 times
    retry_backoff_multiplier: float = DEFAULT_BACKOFF_MULTIPLIER  # Exponential backoff multiplier
    initial_retry_delay_seconds: float = float(MEDIUM_BACKOFF_SECONDS)  # Initial delay before retry
    fail_on_permanent_error: bool = False  # Skip iteration vs fail completely

    # Continuous mode
    continuous_check_interval_minutes: int = MINUTES_PER_HOUR  # Check hourly
    continuous_enabled: bool = False  # Disabled by default
    continuous_max_iterations: Optional[int] = None  # Max iterations (None = unlimited)
    continuous_convergence_window: int = THRESHOLD_SMALL_COUNT  # Stop if no deployments in N iterations
    continuous_cost_budget: Optional[float] = None  # Max total cost (None = unlimited)

    # Observability
    enable_metrics: bool = True  # Collect loop metrics
    enable_detailed_logging: bool = True  # Verbose logging
    log_phase_results: bool = True  # Log detailed phase results

    # State management
    enable_state_persistence: bool = True  # Persist state to DB
    enable_crash_recovery: bool = True  # Resume from crash
    state_checkpoint_interval_seconds: int = SECONDS_PER_MINUTE  # Checkpoint state every minute

    def validate(self) -> None:
        """
        Validate configuration parameters.

        Raises:
            ValueError: If any parameter is invalid
        """
        if self.detection_window_hours < 1:
            raise ValueError("detection_window_hours must be >= 1")
        if self.min_executions_for_detection < 1:
            raise ValueError("min_executions_for_detection must be >= 1")
        if self.max_variants_per_experiment < 1 or self.max_variants_per_experiment > MAX_VARIANTS_PER_EXPERIMENT_LIMIT:
            raise ValueError(f"max_variants_per_experiment must be 1-{MAX_VARIANTS_PER_EXPERIMENT_LIMIT}")
        if self.target_samples_per_variant < 10:
            raise ValueError("target_samples_per_variant must be >= 10")
        if self.experiment_timeout_hours < 1:
            raise ValueError("experiment_timeout_hours must be >= 1")
        if self.max_retries_per_phase < 0:
            raise ValueError("max_retries_per_phase must be >= 0")
        if self.retry_backoff_multiplier < 1.0:
            raise ValueError("retry_backoff_multiplier must be >= 1.0")

    def to_dict(self):
        """Convert config to dictionary."""
        return {
            k: v for k, v in self.__dict__.items()
            if not k.startswith('_')
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LoopConfig":
        """Load config from dictionary."""
        return cls(**{
            k: v for k, v in data.items()
            if k in cls.__dataclass_fields__
        })
