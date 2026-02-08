"""Constants for the self-improvement module.

Centralized constants for ML parameters, statistical thresholds,
deployment configuration, detection parameters, and loop configuration.
Domain bridge pattern: imports from src/constants/ for cross-cutting values.
"""

from src.constants.durations import (
    DAYS_PER_WEEK,
    HOURS_PER_DAY,
)

# ============================================================================
# Statistical Testing & Analysis
# ============================================================================

# Sequential testing defaults
DEFAULT_ALPHA = 0.05  # Type I error rate (false positive)
DEFAULT_BETA = 0.20  # Type II error rate (false negative)
DEFAULT_MDE = 0.10  # Minimum detectable effect
DEFAULT_POWER = 0.80  # Statistical power (1 - beta)
DEFAULT_CREDIBLE_LEVEL = 0.95  # Bayesian credible interval

# Sample size thresholds
MIN_SAMPLES_SEQUENTIAL = 10  # Minimum samples for sequential test
MAX_SAMPLE_SIZE_FALLBACK = 10000  # Fallback when effect size is zero
MIN_SAMPLES_COMPARISON = 5  # Minimum samples for metric comparison

# Confidence interval
DEFAULT_CONFIDENCE_LEVEL = 0.95
Z_SCORE_95 = 1.96  # Z-score for 95% confidence

# ============================================================================
# Temperature Search Strategy
# ============================================================================

DEFAULT_TEMPERATURE = 0.7
MIN_TEMPERATURE = 0.1
MAX_TEMPERATURE = 2.0
TEMPERATURE_STEP = 0.1
TEMPERATURE_GRID_SIZE = 5  # Number of temperature points to search
MIN_TEMP_FOR_REDUCTION = 0.15  # Below this, don't reduce further
TEMPERATURE_RANGE_LOW = 0.3
TEMPERATURE_RANGE_HIGH = 1.5

# ============================================================================
# Strategy Configuration
# ============================================================================

# Prompt optimization
MAX_PROMPT_VARIANTS = 5
DEFAULT_PROMPT_ITERATIONS = 3
PROMPT_IMPROVEMENT_THRESHOLD = 0.05  # 5% improvement required

# Ollama model strategy
DEFAULT_OLLAMA_PORT = 11434
OLLAMA_HEALTH_TIMEOUT = 5  # seconds
OLLAMA_PULL_TIMEOUT = 300  # seconds (5 min for model download)
MODEL_TIER_SMALL_MAX = 5  # Parameters in billions
MODEL_TIER_MEDIUM_MAX = 15

# ERC721 strategy
ERC721_MIN_CONFIDENCE = 0.6
ERC721_HIGH_CONFIDENCE = 0.8
ERC721_MAX_RETRIES = 3
ERC721_BATCH_SIZE = 10
ERC721_GAS_MULTIPLIER = 1.2

# ============================================================================
# Detection Parameters
# ============================================================================

# Problem detection
PROBLEM_DETECTION_WINDOW_HOURS = 24
MIN_EXECUTIONS_FOR_DETECTION = 10
ERROR_RATE_THRESHOLD = 0.3  # 30% error rate triggers detection
LATENCY_INCREASE_THRESHOLD = 1.5  # 50% increase triggers detection
COST_INCREASE_THRESHOLD = 2.0  # 100% increase triggers detection

# Improvement detection
IMPROVEMENT_SCORE_THRESHOLD = 0.1  # 10% improvement needed
MIN_IMPROVEMENT_SAMPLES = 5
IMPROVEMENT_LOOKBACK_DAYS = 7
REGRESSION_THRESHOLD = -0.05  # -5% is regression  # noqa: Constant definition (negative value)

# Pattern mining
MIN_PATTERN_FREQUENCY = 3
MIN_PATTERN_CONFIDENCE = 0.7
MAX_PATTERNS_PER_CATEGORY = 20
PATTERN_DECAY_FACTOR = 0.95

# ============================================================================
# Loop Configuration
# ============================================================================

# Continuous executor
DEFAULT_LOOP_INTERVAL_SECONDS = 300  # 5 minutes
MAX_CONSECUTIVE_FAILURES = 5
FAILURE_BACKOFF_MULTIPLIER = 2.0
MAX_BACKOFF_SECONDS = 3600  # 1 hour max backoff

# Orchestrator
MAX_CONCURRENT_EXPERIMENTS = 3
EXPERIMENT_TIMEOUT_HOURS = 24
ORCHESTRATOR_POLL_INTERVAL = 60  # seconds
DEFAULT_EXPERIMENT_DURATION_HOURS = 4

# Error recovery
MAX_RECOVERY_ATTEMPTS = 3
RECOVERY_COOLDOWN_SECONDS = 60
ERROR_HISTORY_SIZE = 100

# ============================================================================
# Deployment Configuration
# ============================================================================

# Rollback monitor
ROLLBACK_CHECK_INTERVAL = 60  # seconds
ROLLBACK_METRIC_WINDOW = 300  # 5 minutes
ROLLBACK_THRESHOLD = 0.1  # 10% degradation triggers rollback
MAX_ROLLBACK_HISTORY = 50

# Deployer
DEPLOYMENT_TIMEOUT_SECONDS = 600  # 10 minutes
HEALTH_CHECK_INTERVAL = 10  # seconds
HEALTH_CHECK_RETRIES = 5
CANARY_TRAFFIC_PERCENT = 10

# ============================================================================
# Metrics & Scoring
# ============================================================================

# Extraction quality
MIN_EXTRACTION_SCORE = 0.0
MAX_EXTRACTION_SCORE = 1.0
DEFAULT_QUALITY_THRESHOLD = 0.7
QUALITY_WEIGHTS_COMPLETENESS = 0.4
QUALITY_WEIGHTS_ACCURACY = 0.4
QUALITY_WEIGHTS_FORMAT = 0.2

# Performance analysis
DEFAULT_ANALYSIS_WINDOW_HOURS = HOURS_PER_DAY * DAYS_PER_WEEK  # 168 hours = 1 week
MIN_EXECUTIONS_FOR_PROFILE = 10
PERCENTILE_95 = 95
PERCENTILE_99 = 99
PERCENTILE_50 = 50

# Model registry context windows
CONTEXT_WINDOW_4K = 4096
CONTEXT_WINDOW_8K = 8192
CONTEXT_WINDOW_32K = 32768

# ============================================================================
# Data Models & Storage
# ============================================================================

# Experiment storage
MAX_EXPERIMENT_HISTORY = 1000
MAX_RESULT_PAYLOAD_SIZE = 10000  # characters
DEFAULT_BASELINE_WINDOW_DAYS = 7
MAX_TAGS_PER_EXPERIMENT = 20

# Strategy learning
LEARNING_RATE = 0.1
DISCOUNT_FACTOR = 0.9
EXPLORATION_RATE = 0.1
MIN_EXPLORATION_RATE = 0.01
EXPLORATION_DECAY = 0.995

# CLI
DEFAULT_DISPLAY_LIMIT = 20  # Number of items to show in CLI
