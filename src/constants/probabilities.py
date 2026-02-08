"""Common probability and weight constants used across the framework.

These constants provide semantic meaning to commonly-used probability thresholds
and weight values, improving code readability and maintainability.
"""

# Probability thresholds for decision-making
PROB_MINIMAL = 0.05  # 5% probability threshold (very rare events)
PROB_VERY_LOW = 0.1  # 10% probability threshold
PROB_LOW = 0.15  # 15% probability threshold
PROB_MEDIUM_LOW = 0.2  # 20% probability threshold
PROB_LOW_MEDIUM = 0.3  # 30% probability threshold
PROB_MEDIUM_LOW_PLUS = 0.35  # 35% probability threshold
PROB_MODERATE = 0.4  # 40% probability threshold
PROB_MEDIUM = 0.5  # 50% probability threshold (balanced/neutral)
PROB_MEDIUM_HIGH = 0.6  # 60% probability threshold
PROB_HIGH = 0.7  # 70% probability threshold
PROB_VERY_HIGH = 0.8  # 80% probability threshold
PROB_CRITICAL = 0.85  # 85% probability threshold (high confidence)
PROB_VERY_HIGH_PLUS = 0.9  # 90% probability threshold
PROB_NEAR_CERTAIN = 0.95  # 95% probability threshold (very high confidence)

# Weight values for combining/aggregating results
WEIGHT_MINIMAL = 0.1  # 10% weight
WEIGHT_SMALL = 0.25  # 25% weight
WEIGHT_MEDIUM = 0.5  # 50% weight (balanced/neutral)
WEIGHT_LARGE = 0.75  # 75% weight
WEIGHT_VERY_LARGE = 0.9  # 90% weight

# Confidence thresholds (same as probabilities but for clarity in different contexts)
CONFIDENCE_VERY_LOW = 0.1
CONFIDENCE_LOW = 0.3
CONFIDENCE_MEDIUM = 0.5
CONFIDENCE_HIGH = 0.7
CONFIDENCE_VERY_HIGH = 0.9

# Common decimal fractions
FRACTION_QUARTER = 0.25
FRACTION_THIRD = 0.33
FRACTION_HALF = 0.5
FRACTION_TWO_THIRDS = 0.67
FRACTION_THREE_QUARTERS = 0.75

# Tolerance/threshold values
TOLERANCE_VERY_TIGHT = 0.01
TOLERANCE_TIGHT = 0.05
TOLERANCE_NORMAL = 0.1
TOLERANCE_LOOSE = 0.2
TOLERANCE_VERY_LOOSE = 0.5
