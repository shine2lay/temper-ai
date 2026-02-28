"""
Boundary value constants for parameterized testing.

These constants define test boundaries for configuration limits,
counts, scores, and other numeric parameters throughout the framework.
Used for comprehensive boundary value analysis in tests.
"""

# Agent count boundaries
AGENT_COUNT_BOUNDARIES = {
    "below_minimum": 0,
    "minimum": 1,
    "typical": 3,
    "near_maximum": 9,
    "maximum": 10,
    "above_maximum": 11,
}

# Confidence score boundaries (0.0 to 1.0)
CONFIDENCE_SCORE_BOUNDARIES = {
    "below_minimum": -0.1,
    "minimum": 0.0,
    "low": 0.3,
    "medium": 0.6,
    "high": 0.9,
    "maximum": 1.0,
    "above_maximum": 1.1,
    "way_above_maximum": 2.0,
}

# Token count boundaries
TOKEN_COUNT_BOUNDARIES = {
    "zero": 0,
    "minimum": 1,
    "small": 100,
    "typical": 500,
    "large": 2000,
    "near_limit": 2040,
    "at_limit": 2048,
    "above_limit": 2049,
    "way_above_limit": 10000,
}

# Debate round boundaries
DEBATE_ROUND_BOUNDARIES = {
    "zero": 0,
    "minimum": 1,
    "typical": 3,
    "many": 5,
    "near_maximum": 9,
    "maximum": 10,
    "above_maximum": 11,
}

# Temperature boundaries (typically 0.0 to 2.0)
TEMPERATURE_BOUNDARIES = {
    "below_minimum": -0.1,
    "minimum": 0.0,
    "low": 0.3,
    "typical": 0.7,
    "high": 1.0,
    "very_high": 1.5,
    "maximum": 2.0,
    "above_maximum": 2.1,
}

# File size boundaries (in bytes)
FILE_SIZE_BOUNDARIES = {
    "zero": 0,
    "tiny": 1,
    "small": 1024,  # 1 KB
    "medium": 102400,  # 100 KB
    "large": 1048576,  # 1 MB
    "very_large": 10485760,  # 10 MB
    "at_limit": 10485760,  # 10 MB
    "above_limit": 10485761,  # 10 MB + 1
}

# Max tokens boundaries
MAX_TOKENS_BOUNDARIES = {
    "zero": 0,
    "minimum": 1,
    "small": 100,
    "typical": 2048,
    "large": 4096,
    "very_large": 8192,
    "maximum": 100000,
    "above_maximum": 100001,
}

# Timeout boundaries (in seconds)
TIMEOUT_BOUNDARIES = {
    "zero": 0,
    "minimum": 1,
    "short": 5,
    "typical": 30,
    "long": 120,
    "very_long": 300,
    "maximum": 600,
    "above_maximum": 601,
}

# Priority boundaries
PRIORITY_BOUNDARIES = {
    "below_minimum": -1,
    "minimum": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "maximum": 5,
    "above_maximum": 6,
}

# Rate limit boundaries (requests per minute)
RATE_LIMIT_BOUNDARIES = {
    "zero": 0,
    "minimum": 1,
    "low": 5,
    "typical": 10,
    "high": 60,
    "very_high": 100,
    "maximum": 1000,
    "above_maximum": 1001,
}

# Comprehensive boundary values dictionary
BOUNDARY_VALUES = {
    "agent_count": AGENT_COUNT_BOUNDARIES,
    "confidence_score": CONFIDENCE_SCORE_BOUNDARIES,
    "token_count": TOKEN_COUNT_BOUNDARIES,
    "debate_round": DEBATE_ROUND_BOUNDARIES,
    "temperature": TEMPERATURE_BOUNDARIES,
    "file_size": FILE_SIZE_BOUNDARIES,
    "max_tokens": MAX_TOKENS_BOUNDARIES,
    "timeout": TIMEOUT_BOUNDARIES,
    "priority": PRIORITY_BOUNDARIES,
    "rate_limit": RATE_LIMIT_BOUNDARIES,
}


def get_boundary_test_cases(boundary_type: str, valid_range: tuple = None):
    """
    Generate test cases for a specific boundary type.

    Args:
        boundary_type: Type of boundary (e.g., "agent_count", "confidence_score")
        valid_range: Optional tuple of (min_key, max_key) defining valid range

    Returns:
        List of tuples (value, should_accept) for parameterized tests

    Example:
        >>> cases = get_boundary_test_cases("agent_count", ("minimum", "maximum"))
        >>> # Returns: [(0, False), (1, True), (3, True), (10, True), (11, False)]
    """
    if boundary_type not in BOUNDARY_VALUES:
        raise ValueError(f"Unknown boundary type: {boundary_type}")

    boundaries = BOUNDARY_VALUES[boundary_type]
    test_cases = []

    if valid_range:
        min_key, max_key = valid_range
        min_val = boundaries[min_key]
        max_val = boundaries[max_key]

        for _key, value in boundaries.items():
            should_accept = min_val <= value <= max_val
            test_cases.append((value, should_accept))
    else:
        # Return all values without acceptance info
        test_cases = [(value, None) for value in boundaries.values()]

    return test_cases
