"""Shared constants for portfolio management module."""

# List limits
DEFAULT_LIST_LIMIT = 100
DEFAULT_RUN_LIMIT = 50
DEFAULT_SNAPSHOT_LIMIT = 30

# Scheduler
DEFAULT_MAX_TOTAL_CONCURRENT = 8
DEFAULT_PRODUCT_WEIGHT = 1.0
DEFAULT_MAX_CONCURRENT_PER_PRODUCT = 2

# Component analyzer
MIN_SIMILARITY_THRESHOLD = 0.6

# Optimizer — scorecard weights (sum to 1.0)
WEIGHT_SUCCESS_RATE = 0.30
WEIGHT_COST_EFFICIENCY = 0.25
WEIGHT_TREND = 0.25
WEIGHT_UTILIZATION = 0.20

# Optimizer — action thresholds
THRESHOLD_INVEST = 0.75
THRESHOLD_MAINTAIN = 0.50
THRESHOLD_REDUCE = 0.25
TREND_NEGATIVE_THRESHOLD = -0.1  # noqa: scanner: skip-magic
TREND_OFFSET = 0.5  # noqa: scanner: skip-magic

# Optimizer — lookback
DEFAULT_LOOKBACK_HOURS = 720  # 30 days
RECENT_LOOKBACK_HOURS = 168  # 7 days (for trend calculation)

# Knowledge graph
MAX_BFS_DEPTH = 4
DEFAULT_BFS_DEPTH = 1

# Display
ID_DISPLAY_LEN = 12
SIMILARITY_DISPLAY_DECIMALS = 3
SCORE_DISPLAY_DECIMALS = 3

# Repeated CLI strings
COL_NAME = "Name"
COL_PRODUCT = "Product"
ERR_PORTFOLIO_NOT_FOUND = "Portfolio config not found"

# Portfolio config directory
DEFAULT_PORTFOLIO_CONFIG_DIR = "configs/portfolios"
