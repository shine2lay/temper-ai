"""Helper functions for TokenBucketRateLimitPolicy.

Extracted to keep the policy class below 500 lines.
These are internal implementation details and should not be used directly.
"""
from typing import Any, Dict, Optional

from temper_ai.shared.constants.durations import SECONDS_PER_HOUR, SECONDS_PER_MINUTE
from temper_ai.shared.constants.limits import SMALL_ITEM_LIMIT
from temper_ai.safety.constants import (
    FILL_PERCENTAGE_KEY,
    FORMAT_ONE_DECIMAL,
    MAX_TOKENS_KEY,
    REFILL_RATE_KEY,
    SCOPE_GLOBAL,
)
from temper_ai.safety.interfaces import SafetyViolation, ViolationSeverity
from temper_ai.safety.token_bucket import TokenBucketManager

# Severity threshold constants
RATE_LIMIT_CRITICAL_THRESHOLD_SECONDS = SECONDS_PER_HOUR
RATE_LIMIT_HOUR_THRESHOLD_SECONDS = SECONDS_PER_HOUR
RATE_LIMIT_MINUTE_THRESHOLD_SECONDS = SECONDS_PER_MINUTE
RATE_LIMIT_PLURAL_THRESHOLD = SMALL_ITEM_LIMIT // SMALL_ITEM_LIMIT + 1  # 2


def format_wait_time(seconds: float) -> str:
    """Format wait time for human readability.

    Returns formatted string like "5.2 minutes" or "1.5 hours".
    """
    if seconds >= RATE_LIMIT_HOUR_THRESHOLD_SECONDS:
        hours = seconds / RATE_LIMIT_HOUR_THRESHOLD_SECONDS
        return f"{hours:{FORMAT_ONE_DECIMAL}} hour{'s' if hours >= RATE_LIMIT_PLURAL_THRESHOLD else ''}"
    elif seconds >= RATE_LIMIT_MINUTE_THRESHOLD_SECONDS:
        minutes = seconds / RATE_LIMIT_MINUTE_THRESHOLD_SECONDS
        return f"{minutes:{FORMAT_ONE_DECIMAL}} minute{'s' if minutes >= RATE_LIMIT_PLURAL_THRESHOLD else ''}"
    else:
        return f"{seconds:{FORMAT_ONE_DECIMAL}} second{'s' if seconds >= RATE_LIMIT_PLURAL_THRESHOLD else ''}"


def check_limit(
    manager: TokenBucketManager,
    entity_id: str,
    limit_type: str,
    action_type: str,
    context: Dict[str, Any],
    scope: str,
    policy_name: str,
) -> tuple[bool, Optional[SafetyViolation]]:
    """Check rate limit for entity and limit type.

    Returns tuple of (is_limited, violation).
    """
    if manager.consume(entity_id, limit_type, 1):
        return False, None

    # Rate limit exceeded - create violation
    wait_time = manager.get_wait_time(entity_id, limit_type, 1)
    current_tokens = manager.get_tokens(entity_id, limit_type) or 0

    bucket = manager.get_bucket(entity_id, limit_type)
    bucket_info = bucket.get_info() if bucket else {}

    if wait_time > RATE_LIMIT_CRITICAL_THRESHOLD_SECONDS:
        severity = ViolationSeverity.CRITICAL
    else:
        severity = ViolationSeverity.HIGH

    violation = SafetyViolation(
        policy_name=policy_name,
        severity=severity,
        message=f"Rate limit exceeded for {action_type} ({scope})",
        action=action_type,
        context=context,
        remediation_hint=f"Wait {format_wait_time(wait_time)} before retrying",
        metadata={
            "limit_type": limit_type,
            "scope": scope,
            "entity_id": entity_id if scope == "per-agent" else SCOPE_GLOBAL,
            "wait_time": round(wait_time, 2),
            "current_tokens": round(current_tokens, 2),
            MAX_TOKENS_KEY: bucket_info.get(MAX_TOKENS_KEY, 0),
            REFILL_RATE_KEY: bucket_info.get(REFILL_RATE_KEY, 0),
            FILL_PERCENTAGE_KEY: bucket_info.get(FILL_PERCENTAGE_KEY, 0),
        },
    )

    return True, violation
