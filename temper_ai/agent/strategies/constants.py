"""Constants for the strategies module.

Centralized constants for collaboration strategies including merit weighting,
decision thresholds, consensus, dialogue, and debate parameters.
"""

from temper_ai.shared.constants.probabilities import (
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
)

# ============================================================================
# Merit Weighting
# ============================================================================

DEFAULT_MERIT_WEIGHT = 1.0  # Equal weight when no merit data available
MIN_MERIT_WEIGHT = 0.1
MAX_MERIT_WEIGHT = 10.0
MERIT_DECAY_FACTOR = 0.95  # How quickly merit scores decay over time
DEFAULT_MERIT_LOOKBACK_DAYS = 30

# ============================================================================
# Decision Thresholds
# ============================================================================

DEFAULT_AGREEMENT_THRESHOLD = 0.7  # 70% agreement for consensus
HIGH_AGREEMENT_THRESHOLD = 0.9
LOW_AGREEMENT_THRESHOLD = 0.5
DEFAULT_CONFIDENCE_THRESHOLD = CONFIDENCE_MEDIUM  # 0.5
HIGH_CONFIDENCE_THRESHOLD = CONFIDENCE_HIGH  # 0.7

# ============================================================================
# Consensus Strategy
# ============================================================================

DEFAULT_MIN_VOTES = 2
DEFAULT_SUPERMAJORITY_RATIO = 0.67  # Two-thirds majority
UNANIMOUS_RATIO = 1.0

# ============================================================================
# Dialogue Strategy
# ============================================================================

DEFAULT_MAX_ROUNDS = 3
DEFAULT_MIN_ROUNDS = 1
DEFAULT_CONVERGENCE_THRESHOLD = 0.85
DEFAULT_CONTEXT_WINDOW_SIZE = 2  # For "recent" context strategy
MAX_DIALOGUE_ROUNDS = 10
DIALOGUE_COST_BUDGET_DEFAULT = None  # No budget limit by default

# ============================================================================
# Debate Strategy
# ============================================================================

DEFAULT_DEBATE_ROUNDS = 3
MIN_ARGUMENT_LENGTH = 50  # Characters
MAX_ARGUMENT_LENGTH = 5000
REBUTTAL_WEIGHT = 0.8  # Weight given to rebuttals vs original arguments

# ============================================================================
# Conflict Resolution
# ============================================================================

DEFAULT_ESCALATION_THRESHOLD = 3  # Rounds before escalation
CONFLICT_SEVERITY_LOW = 0.3
CONFLICT_SEVERITY_MEDIUM = 0.5
CONFLICT_SEVERITY_HIGH = 0.8
MAX_RESOLUTION_ATTEMPTS = 5

# ============================================================================
# Strategy Names
# ============================================================================

STRATEGY_NAME_CONSENSUS = "consensus"
STRATEGY_NAME_CONCATENATE = "concatenate"
STRATEGY_NAME_DIALOGUE = "dialogue"
STRATEGY_NAME_DEBATE = "debate"
STRATEGY_NAME_INTERACTIVE = "interactive"
STRATEGY_NAME_MERIT_WEIGHTED = "merit_weighted"

# ============================================================================
# Configuration Keys (for strategy config dictionaries)
# ============================================================================

CONFIG_KEY_LEADER_AGENT = "leader_agent"
CONFIG_KEY_MIN_CONSENSUS = "min_consensus"
CONFIG_KEY_CONFIDENCE = "confidence"
CONFIG_KEY_MAX_ROUNDS = "max_rounds"
CONFIG_KEY_MIN_ROUNDS = "min_rounds"
CONFIG_KEY_CONVERGENCE_THRESHOLD = "convergence_threshold"
CONFIG_KEY_MODE_INSTRUCTION = "mode_instruction"
CONFIG_KEY_DEBATE_FRAMING = "debate_framing"

# ============================================================================
# Mode/Context Values
# ============================================================================

MODE_VALUE_FULL = "full"
MODE_VALUE_FIRST = "first"
MODE_VALUE_UNKNOWN = "unknown"

# ============================================================================
# Format Strings (logging/display)
# ============================================================================

FORMAT_FLOAT_3_DECIMAL = ".3f"
FORMAT_PERCENT_1_DECIMAL = ".1%"
