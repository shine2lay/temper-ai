"""
Configuration for M5 Self-Improvement Loop.

Provides sensible defaults while allowing customization of all loop parameters.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LoopConfig:
    """
    Configuration for M5SelfImprovementLoop.

    Controls behavior of all 5 phases and error handling.
    """

    # Phase 1: Detection
    detection_window_hours: int = 168  # 7 days
    min_executions_for_detection: int = 50  # Minimum samples needed
    detection_threshold: float = 0.1  # 10% degradation triggers detection

    # Phase 2: Analysis
    analysis_window_hours: int = 168  # 7 days
    min_executions_for_analysis: int = 10  # Minimum samples for analysis

    # Phase 3: Strategy
    max_variants_per_experiment: int = 3  # A/B/C/D testing (control + 3 variants)
    enable_model_variants: bool = True  # Test different LLM models
    enable_prompt_variants: bool = True  # Test different prompts
    enable_param_variants: bool = True  # Test different inference params

    # Phase 4: Experimentation
    target_samples_per_variant: int = 50  # Samples per variant for statistical significance
    experiment_timeout_hours: int = 72  # 3 days max
    min_improvement_threshold: float = 0.05  # 5% minimum improvement to deploy
    statistical_significance_level: float = 0.05  # p < 0.05 for significance

    # Phase 5: Deployment
    enable_auto_deploy: bool = True  # Auto-deploy winners
    enable_auto_rollback: bool = True  # Auto-rollback on regression
    rollback_check_interval_hours: int = 24  # Check for regression daily
    deployment_confirmation_required: bool = False  # Require manual confirmation

    # Rollback thresholds (from RegressionThresholds)
    rollback_quality_drop_pct: float = 10.0  # 10% quality drop triggers rollback
    rollback_cost_increase_pct: float = 20.0  # 20% cost increase triggers rollback
    rollback_speed_increase_pct: float = 30.0  # 30% speed degradation triggers rollback
    rollback_min_executions: int = 20  # Min samples before rollback check

    # Error handling
    max_retries_per_phase: int = 3  # Retry failed phases up to 3 times
    retry_backoff_multiplier: float = 2.0  # Exponential backoff multiplier
    initial_retry_delay_seconds: float = 5.0  # Initial delay before retry
    fail_on_permanent_error: bool = False  # Skip iteration vs fail completely

    # Continuous mode
    continuous_check_interval_minutes: int = 60  # Check hourly
    continuous_enabled: bool = False  # Disabled by default

    # Observability
    enable_metrics: bool = True  # Collect loop metrics
    enable_detailed_logging: bool = True  # Verbose logging
    log_phase_results: bool = True  # Log detailed phase results

    # State management
    enable_state_persistence: bool = True  # Persist state to DB
    enable_crash_recovery: bool = True  # Resume from crash
    state_checkpoint_interval_seconds: int = 60  # Checkpoint state every minute

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
        if self.max_variants_per_experiment < 1 or self.max_variants_per_experiment > 5:
            raise ValueError("max_variants_per_experiment must be 1-5")
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
