"""Constants for the experimentation module.

Centralized constants for experiment configuration, statistical testing,
sample sizes, and assignment parameters.
"""

# ============================================================================
# Statistical Testing Defaults
# ============================================================================

DEFAULT_ALPHA = 0.05  # Type I error rate
DEFAULT_BETA = 0.20  # Type II error rate
DEFAULT_MDE = 0.10  # Minimum detectable effect
DEFAULT_POWER = 0.80  # Statistical power
DEFAULT_CREDIBLE_LEVEL = 0.95
MAX_SAMPLE_SIZE_FALLBACK = 10000

# ============================================================================
# Sample Size & Data Requirements
# ============================================================================

MIN_SAMPLES_SEQUENTIAL = 10  # Minimum for sequential test
MIN_SAMPLES_ANALYSIS = 5
DEFAULT_MIN_SAMPLE_SIZE = 30
MAX_SAMPLE_SIZE = 100000
MIN_OBSERVATIONS_PER_VARIANT = 10

# ============================================================================
# Experiment Configuration
# ============================================================================

DEFAULT_MAX_EXPERIMENTS = 100
DEFAULT_EXPERIMENT_DURATION_HOURS = 24
MAX_VARIANTS_PER_EXPERIMENT = 10
MAX_METRICS_PER_EXPERIMENT = 50
DEFAULT_TRAFFIC_ALLOCATION = 0.5  # 50/50 split

# ============================================================================
# Assignment & Traffic
# ============================================================================

DEFAULT_HASH_SEED = 42
ASSIGNMENT_BUCKET_SIZE = 1000  # Number of hash buckets
MIN_TRAFFIC_PERCENT = 1  # Minimum 1% traffic per variant
MAX_TRAFFIC_PERCENT = 99

# ============================================================================
# Sequential Testing
# ============================================================================

SPRT_MIN_OBSERVATIONS = 10
FUTILITY_BOUNDARY_MULTIPLIER = 0.5

# ============================================================================
# Bayesian Analysis
# ============================================================================

DEFAULT_PRIOR_MEAN = 0.0
DEFAULT_PRIOR_STD = 1.0
NUM_POSTERIOR_SAMPLES = 10000
ROPE_MARGIN = 0.01  # Region of Practical Equivalence

# ============================================================================
# Field Names (Dictionary Keys)
# ============================================================================

FIELD_CREATED_BY = "created_by"
FIELD_NAME = "name"
FIELD_CONFIDENCE = "confidence"
FIELD_RECOMMENDATION = "recommendation"
FIELD_LLR = "llr"
FIELD_SAMPLES = "samples"

# ============================================================================
# Status Values
# ============================================================================

STATUS_FAILED = "failed"

# ============================================================================
# Error Messages
# ============================================================================

ERROR_EXPERIMENT_NOT_FOUND = "Experiment not found: "

# ============================================================================
# Model Relationships
# ============================================================================

RELATIONSHIP_EXPERIMENT = "experiment"
FK_EXPERIMENTS_ID = "experiments.id"
