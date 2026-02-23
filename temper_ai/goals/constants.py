"""Constants for goal proposal system."""

# Analysis
ANALYSIS_INTERVAL_HOURS = 12
DEFAULT_LOOKBACK_HOURS = 48
SECONDS_PER_HOUR = 3600

# Scoring weights (sum to 1.0)
WEIGHT_IMPACT = 0.35
WEIGHT_CONFIDENCE = 0.25
WEIGHT_EFFORT_INVERSE = 0.20
WEIGHT_RISK_INVERSE = 0.20

# Effort/risk numeric maps for scoring
EFFORT_SCORES = {
    "trivial": 1.0,
    "small": 0.8,
    "medium": 0.5,
    "large": 0.3,
    "major": 0.1,
}
RISK_SCORES = {
    "low": 1.0,
    "medium": 0.6,
    "high": 0.3,
    "critical": 0.1,
}

# Safety
MAX_PROPOSALS_PER_DAY = 20
MAX_BUDGET_IMPACT_AUTO_USD = 10.0
MAX_BLAST_RADIUS_AUTO = 5
AUTO_APPROVE_RISK_MATRIX = {
    0: None,  # SUPERVISED — never auto-approve
    1: None,  # SPOT_CHECKED — never auto-approve
    2: "low",  # RISK_GATED — low risk only
    3: "medium",  # AUTONOMOUS — low + medium
    4: "high",  # STRATEGIC — up to high (never critical)
}

# Analyzer thresholds
SLOW_STAGE_THRESHOLD_S = 300
DEGRADATION_THRESHOLD_PCT = 20.0
HIGH_COST_AGENT_SHARE = 0.40
MODEL_COST_RATIO = 2.0
MIN_FAILURES_FOR_PROPOSAL = 3
HIGH_FAILURE_RATE = 0.15
MIN_PRODUCT_TYPES_CROSS = 2

# Scoring defaults
DEFAULT_EFFORT_SCORE = 0.5  # noqa: scanner: skip-magic
DEFAULT_RISK_SCORE = 0.5  # noqa: scanner: skip-magic
SCORE_ROUND_DIGITS = 4  # noqa: scanner: skip-magic
RECENT_ANALYSIS_RUNS = 5  # noqa: scanner: skip-magic

# CLI repeated strings
COL_STATUS = "Status"
OPT_REVIEWER = "--reviewer"
OPT_REASON = "--reason"
HELP_REVIEWER = "Reviewer name"

# Store
DEFAULT_LIST_LIMIT = 100
DEFAULT_RUN_LIMIT = 20
DEDUP_KEY_LENGTH = 16
