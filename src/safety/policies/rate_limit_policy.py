"""Rate Limit Policy using Token Bucket Algorithm.

Enforces rate limits on various operations to prevent:
- Runaway agents consuming excessive resources
- API quota violations
- Cost overruns from excessive LLM/tool calls
- Abuse patterns

Uses token bucket algorithm for smooth rate limiting with burst support.

Default Limits (per agent):
- 10 commits/hour (burst: 2)
- 2 deploys/hour (burst: 1)
- 100 tool calls/hour (burst: 10)
- 50 LLM calls/hour (burst: 5)
- 1000 API calls/hour (burst: 50)
"""
from typing import Any, Dict, List, Optional

from src.constants.durations import SECONDS_PER_HOUR, SECONDS_PER_MINUTE
from src.constants.limits import (
    LARGE_ITEM_LIMIT,
    MULTIPLIER_LARGE,
    SMALL_ITEM_LIMIT,
    THRESHOLD_MEDIUM_COUNT,
    VERY_LARGE_ITEM_LIMIT,
)
from src.safety.base import BaseSafetyPolicy
from src.safety.constants import (
    ACTION_TYPE_API_CALL,
    ACTION_TYPE_COMMIT,
    ACTION_TYPE_DEPLOY,
    ACTION_TYPE_LLM_CALL,
    ACTION_TYPE_TOOL_CALL,
    FILL_PERCENTAGE_KEY,
    FORMAT_ONE_DECIMAL,
    GLOBAL_LIMITS_KEY,
    MAX_TOKENS_KEY,
    RATE_LIMIT_PRIORITY,
    RATE_LIMITS_KEY,
    REFILL_RATE_KEY,
    SCOPE_GLOBAL,
)
from src.safety.interfaces import SafetyViolation, ValidationResult, ViolationSeverity
from src.safety.token_bucket import RateLimit, TokenBucketManager

# Default rate limits (per agent, per hour)
DEFAULT_COMMITS_PER_HOUR = THRESHOLD_MEDIUM_COUNT
DEFAULT_COMMITS_BURST = SMALL_ITEM_LIMIT // SMALL_ITEM_LIMIT + 1  # 2
DEFAULT_DEPLOYS_PER_HOUR = SMALL_ITEM_LIMIT // SMALL_ITEM_LIMIT + 1  # 2
DEFAULT_DEPLOYS_BURST = SMALL_ITEM_LIMIT // SMALL_ITEM_LIMIT  # 1
DEFAULT_TOOL_CALLS_PER_HOUR = VERY_LARGE_ITEM_LIMIT
DEFAULT_TOOL_CALLS_BURST = THRESHOLD_MEDIUM_COUNT
DEFAULT_LLM_CALLS_PER_HOUR = LARGE_ITEM_LIMIT
DEFAULT_LLM_CALLS_BURST = SMALL_ITEM_LIMIT
DEFAULT_API_CALLS_PER_HOUR = VERY_LARGE_ITEM_LIMIT * THRESHOLD_MEDIUM_COUNT
DEFAULT_API_CALLS_BURST = LARGE_ITEM_LIMIT

# Default global rate limits (across all agents, per hour)
DEFAULT_GLOBAL_TOOL_CALLS_PER_HOUR = VERY_LARGE_ITEM_LIMIT * THRESHOLD_MEDIUM_COUNT
DEFAULT_GLOBAL_TOOL_CALLS_BURST = LARGE_ITEM_LIMIT

# Rate limit configuration limits
MAX_COOLDOWN_MULTIPLIER = MULTIPLIER_LARGE  # Safety limit for cooldown multiplier

# Severity threshold constants
RATE_LIMIT_CRITICAL_THRESHOLD_SECONDS = SECONDS_PER_HOUR  # 1 hour - threshold for CRITICAL severity
RATE_LIMIT_HOUR_THRESHOLD_SECONDS = SECONDS_PER_HOUR  # 1 hour
RATE_LIMIT_MINUTE_THRESHOLD_SECONDS = SECONDS_PER_MINUTE  # 1 minute
RATE_LIMIT_PLURAL_THRESHOLD = SMALL_ITEM_LIMIT // SMALL_ITEM_LIMIT + 1  # Threshold for plural form in formatting


class TokenBucketRateLimitPolicy(BaseSafetyPolicy):
    """Token-bucket-based rate limiting policy.

    Uses the token bucket algorithm for smooth rate limiting with burst support.
    For window-based rate limiting, see ``WindowRateLimitPolicy``
    in ``src.safety.rate_limiter``.

    Configuration options:
        rate_limits: Dict mapping limit types to RateLimit configs
        per_agent: Track limits per agent (default: True)
        global_limits: Global limits across all agents
        cooldown_multiplier: Multiply wait time on violations (default: 1.0)

    Example:
        >>> config = {
        ...     "rate_limits": {
        ...         "commit": {
        ...             "max_tokens": 10,
        ...             "refill_rate": 10/3600,  # 10 per hour
        ...             "refill_period": 1.0,
        ...             "burst_size": 2
        ...         }
        ...     }
        ... }
        >>> policy = TokenBucketRateLimitPolicy(config)
        >>> result = policy.validate(
        ...     action={"operation": "git_commit"},
        ...     context={"agent_id": "agent-123"}
        ... )
    """

    # Default rate limits (per agent)
    DEFAULT_LIMITS = {
        ACTION_TYPE_COMMIT: RateLimit(
            max_tokens=DEFAULT_COMMITS_PER_HOUR,
            refill_rate=DEFAULT_COMMITS_PER_HOUR / SECONDS_PER_HOUR,
            refill_period=float(SMALL_ITEM_LIMIT // SMALL_ITEM_LIMIT),
            burst_size=DEFAULT_COMMITS_BURST
        ),
        ACTION_TYPE_DEPLOY: RateLimit(
            max_tokens=DEFAULT_DEPLOYS_PER_HOUR,
            refill_rate=DEFAULT_DEPLOYS_PER_HOUR / SECONDS_PER_HOUR,
            refill_period=float(SMALL_ITEM_LIMIT // SMALL_ITEM_LIMIT),
            burst_size=DEFAULT_DEPLOYS_BURST
        ),
        ACTION_TYPE_TOOL_CALL: RateLimit(
            max_tokens=DEFAULT_TOOL_CALLS_PER_HOUR,
            refill_rate=DEFAULT_TOOL_CALLS_PER_HOUR / SECONDS_PER_HOUR,
            refill_period=float(SMALL_ITEM_LIMIT // SMALL_ITEM_LIMIT),
            burst_size=DEFAULT_TOOL_CALLS_BURST
        ),
        ACTION_TYPE_LLM_CALL: RateLimit(
            max_tokens=DEFAULT_LLM_CALLS_PER_HOUR,
            refill_rate=DEFAULT_LLM_CALLS_PER_HOUR / SECONDS_PER_HOUR,
            refill_period=float(SMALL_ITEM_LIMIT // SMALL_ITEM_LIMIT),
            burst_size=DEFAULT_LLM_CALLS_BURST
        ),
        ACTION_TYPE_API_CALL: RateLimit(
            max_tokens=DEFAULT_API_CALLS_PER_HOUR,
            refill_rate=DEFAULT_API_CALLS_PER_HOUR / SECONDS_PER_HOUR,
            refill_period=float(SMALL_ITEM_LIMIT // SMALL_ITEM_LIMIT),
            burst_size=DEFAULT_API_CALLS_BURST
        ),
    }

    # Default global limits (across all agents)
    DEFAULT_GLOBAL_LIMITS = {
        "total_tool_calls": RateLimit(
            max_tokens=DEFAULT_GLOBAL_TOOL_CALLS_PER_HOUR,
            refill_rate=DEFAULT_GLOBAL_TOOL_CALLS_PER_HOUR / SECONDS_PER_HOUR,
            refill_period=float(SMALL_ITEM_LIMIT // SMALL_ITEM_LIMIT),
            burst_size=DEFAULT_GLOBAL_TOOL_CALLS_BURST
        ),
    }

    # Map action types to rate limit types
    ACTION_TO_LIMIT_TYPE = {
        "git_commit": ACTION_TYPE_COMMIT,
        ACTION_TYPE_COMMIT: ACTION_TYPE_COMMIT,
        ACTION_TYPE_DEPLOY: ACTION_TYPE_DEPLOY,
        "deployment": ACTION_TYPE_DEPLOY,
        ACTION_TYPE_TOOL_CALL: ACTION_TYPE_TOOL_CALL,
        "tool_execution": ACTION_TYPE_TOOL_CALL,
        ACTION_TYPE_LLM_CALL: ACTION_TYPE_LLM_CALL,
        ACTION_TYPE_API_CALL: ACTION_TYPE_API_CALL,
        "api_request": ACTION_TYPE_API_CALL,
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize rate limit policy.

        Args:
            config: Policy configuration (optional)

        Raises:
            ValueError: If configuration values are invalid
        """
        super().__init__(config or {})

        # Validate configuration parameters
        per_agent = self.config.get("per_agent", True)
        if not isinstance(per_agent, bool):
            raise ValueError(
                f"per_agent must be boolean, got {type(per_agent).__name__}"
            )
        self.per_agent = per_agent

        cooldown_multiplier = self.config.get("cooldown_multiplier", 1.0)
        if not isinstance(cooldown_multiplier, (int, float)):
            raise ValueError(
                f"cooldown_multiplier must be numeric, got {type(cooldown_multiplier).__name__}"
            )
        if cooldown_multiplier < 0:
            raise ValueError(
                f"cooldown_multiplier must be non-negative, got {cooldown_multiplier}"
            )
        if cooldown_multiplier > MAX_COOLDOWN_MULTIPLIER:
            raise ValueError(
                f"cooldown_multiplier must be <= {MAX_COOLDOWN_MULTIPLIER} (safety limit), got {cooldown_multiplier}. "
                f"Hint: Values > {MAX_COOLDOWN_MULTIPLIER} can create extremely long wait times."
            )
        self.cooldown_multiplier = cooldown_multiplier

        # Per-agent limits
        self.per_agent_manager = TokenBucketManager()
        self._load_per_agent_limits(config or {})

        # Global limits (across all agents)
        self.global_manager = TokenBucketManager()
        self._load_global_limits(config or {})

    def _load_per_agent_limits(self, config: Dict[str, Any]) -> None:
        """Load per-agent rate limits from config.

        Args:
            config: Configuration dictionary

        Raises:
            ValueError: If rate limit configuration is invalid
        """
        # Start with defaults
        limits = self.DEFAULT_LIMITS.copy()

        # Override with config
        if RATE_LIMITS_KEY in config:
            if not isinstance(config[RATE_LIMITS_KEY], dict):
                raise ValueError(
                    f"{RATE_LIMITS_KEY} must be a dictionary, got {type(config[RATE_LIMITS_KEY]).__name__}"
                )

            for limit_type, limit_config in config[RATE_LIMITS_KEY].items():
                # Validate limit_type is a string
                if not isinstance(limit_type, str):
                    raise ValueError(
                        f"Rate limit type must be string, got {type(limit_type).__name__}"
                    )

                if isinstance(limit_config, dict):
                    # Validate all required fields are present
                    required_fields = [MAX_TOKENS_KEY, REFILL_RATE_KEY]
                    for field in required_fields:
                        if field not in limit_config:
                            raise ValueError(
                                f"Rate limit '{limit_type}' missing required field '{field}'"
                            )

                    # RateLimit.__post_init__ will validate positive values
                    try:
                        limits[limit_type] = RateLimit(**limit_config)
                    except (ValueError, TypeError) as e:
                        raise ValueError(
                            f"Invalid rate limit configuration for '{limit_type}': {e}"
                        ) from e

                elif isinstance(limit_config, RateLimit):
                    limits[limit_type] = limit_config
                else:
                    raise ValueError(
                        f"Rate limit '{limit_type}' must be dict or RateLimit, "
                        f"got {type(limit_config).__name__}"
                    )

        # Register limits with manager
        for limit_type, rate_limit in limits.items():
            self.per_agent_manager.set_limit(limit_type, rate_limit)

    def _load_global_limits(self, config: Dict[str, Any]) -> None:
        """Load global rate limits from config.

        Args:
            config: Configuration dictionary

        Raises:
            ValueError: If global rate limit configuration is invalid
        """
        # Start with defaults
        limits = self.DEFAULT_GLOBAL_LIMITS.copy()

        # Override with config
        if GLOBAL_LIMITS_KEY in config:
            if not isinstance(config[GLOBAL_LIMITS_KEY], dict):
                raise ValueError(
                    f"{GLOBAL_LIMITS_KEY} must be a dictionary, got {type(config[GLOBAL_LIMITS_KEY]).__name__}"
                )

            for limit_type, limit_config in config[GLOBAL_LIMITS_KEY].items():
                # Validate limit_type is a string
                if not isinstance(limit_type, str):
                    raise ValueError(
                        f"Global rate limit type must be string, got {type(limit_type).__name__}"
                    )

                if isinstance(limit_config, dict):
                    # Validate all required fields are present
                    required_fields = [MAX_TOKENS_KEY, REFILL_RATE_KEY]
                    for field in required_fields:
                        if field not in limit_config:
                            raise ValueError(
                                f"Global rate limit '{limit_type}' missing required field '{field}'"
                            )

                    # RateLimit.__post_init__ will validate positive values
                    try:
                        limits[limit_type] = RateLimit(**limit_config)
                    except (ValueError, TypeError) as e:
                        raise ValueError(
                            f"Invalid global rate limit configuration for '{limit_type}': {e}"
                        ) from e

                elif isinstance(limit_config, RateLimit):
                    limits[limit_type] = limit_config
                else:
                    raise ValueError(
                        f"Global rate limit '{limit_type}' must be dict or RateLimit, "
                        f"got {type(limit_config).__name__}"
                    )

        # Register limits with manager
        for limit_type, rate_limit in limits.items():
            self.global_manager.set_limit(limit_type, rate_limit)

    @property
    def name(self) -> str:
        """Return policy name."""
        return "rate_limit"

    @property
    def version(self) -> str:
        """Return policy version."""
        return "1.0.0"

    @property
    def priority(self) -> int:
        """Return policy priority.

        Rate limiting has high priority to prevent resource exhaustion.
        """
        return RATE_LIMIT_PRIORITY

    def _validate_impl(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> ValidationResult:
        """Validate action against rate limits.

        Args:
            action: Action to validate, should contain:
                - operation: Type of operation (git_commit, deploy, tool_call, etc.)
                - type: Alternative to operation
            context: Execution context (for per-agent tracking)

        Returns:
            ValidationResult with violations if rate limit exceeded
        """
        violations: List[SafetyViolation] = []

        # Extract operation type
        action_type = action.get("operation") or action.get("type", "unknown")

        # Map to rate limit type
        limit_type = self.ACTION_TO_LIMIT_TYPE.get(action_type)

        if not limit_type:
            # No rate limit for this action type
            return ValidationResult(
                valid=True,
                violations=[],
                metadata={"action_type": action_type, "rate_limited": False},
                policy_name=self.name
            )

        # Get agent ID (or use shared ID if per_agent is disabled)
        if self.per_agent:
            entity_id = context.get("agent_id", "unknown")
            scope = "per-agent"
        else:
            # All agents share the same rate limit buckets
            entity_id = SCOPE_GLOBAL
            scope = SCOPE_GLOBAL

        # Check rate limits
        agent_limited, agent_violation = self._check_limit(
            self.per_agent_manager,
            entity_id,
            limit_type,
            action_type,
            context,
            scope=scope
        )

        if agent_limited and agent_violation:
            violations.append(agent_violation)

        # Check global limits
        if limit_type == "tool_call":
            # Tool calls also count against global total
            global_limited, global_violation = self._check_limit(
                self.global_manager,
                "global",
                "total_tool_calls",
                action_type,
                context,
                scope="global"
            )

            if global_limited and global_violation:
                violations.append(global_violation)

        # Determine validity
        valid = len(violations) == 0

        # Calculate retry-after if rate limited
        retry_after = None
        if violations:
            retry_after = max(
                v.metadata.get("wait_time", 0)
                for v in violations
            ) * self.cooldown_multiplier

        return ValidationResult(
            valid=valid,
            violations=violations,
            metadata={
                "action_type": action_type,
                "limit_type": limit_type,
                "rate_limited": not valid,
                "retry_after": retry_after
            },
            policy_name=self.name
        )

    def _check_limit(
        self,
        manager: TokenBucketManager,
        entity_id: str,
        limit_type: str,
        action_type: str,
        context: Dict[str, Any],
        scope: str
    ) -> tuple[bool, Optional[SafetyViolation]]:
        """Check rate limit for entity and limit type.

        Args:
            manager: Token bucket manager (per-agent or global)
            entity_id: Entity identifier
            limit_type: Type of limit
            action_type: Action type for error messages
            context: Execution context
            scope: "per-agent" or "global"

        Returns:
            Tuple of (is_limited, violation)
        """
        # Try to consume token
        if manager.consume(entity_id, limit_type, 1):
            # Rate limit OK
            return False, None

        # Rate limit exceeded - create violation
        wait_time = manager.get_wait_time(entity_id, limit_type, 1)
        current_tokens = manager.get_tokens(entity_id, limit_type) or 0

        # Get bucket info for metadata
        bucket = manager.get_bucket(entity_id, limit_type)
        bucket_info = bucket.get_info() if bucket else {}

        # Determine severity based on how long the wait is
        # Rate limit violations should always be at least HIGH to block actions
        if wait_time > RATE_LIMIT_CRITICAL_THRESHOLD_SECONDS:
            severity = ViolationSeverity.CRITICAL
        else:
            # All rate limit violations are HIGH severity (blocking)
            severity = ViolationSeverity.HIGH

        violation = SafetyViolation(
            policy_name=self.name,
            severity=severity,
            message=f"Rate limit exceeded for {action_type} ({scope})",
            action=action_type,
            context=context,
            remediation_hint=f"Wait {self._format_wait_time(wait_time)} before retrying",
            metadata={
                "limit_type": limit_type,
                "scope": scope,
                "entity_id": entity_id if scope == "per-agent" else SCOPE_GLOBAL,
                "wait_time": round(wait_time, 2),
                "current_tokens": round(current_tokens, 2),
                MAX_TOKENS_KEY: bucket_info.get(MAX_TOKENS_KEY, 0),
                REFILL_RATE_KEY: bucket_info.get(REFILL_RATE_KEY, 0),
                FILL_PERCENTAGE_KEY: bucket_info.get(FILL_PERCENTAGE_KEY, 0)
            }
        )

        return True, violation

    def _format_wait_time(self, seconds: float) -> str:
        """Format wait time for human readability.

        Args:
            seconds: Wait time in seconds

        Returns:
            Formatted string (e.g., "5.2 minutes", "1.5 hours")
        """
        if seconds >= RATE_LIMIT_HOUR_THRESHOLD_SECONDS:
            hours = seconds / RATE_LIMIT_HOUR_THRESHOLD_SECONDS
            return f"{hours:{FORMAT_ONE_DECIMAL}} hour{'s' if hours >= RATE_LIMIT_PLURAL_THRESHOLD else ''}"
        elif seconds >= RATE_LIMIT_MINUTE_THRESHOLD_SECONDS:
            minutes = seconds / RATE_LIMIT_MINUTE_THRESHOLD_SECONDS
            return f"{minutes:{FORMAT_ONE_DECIMAL}} minute{'s' if minutes >= RATE_LIMIT_PLURAL_THRESHOLD else ''}"
        else:
            return f"{seconds:{FORMAT_ONE_DECIMAL}} second{'s' if seconds >= RATE_LIMIT_PLURAL_THRESHOLD else ''}"

    def get_status(self, agent_id: str) -> Dict[str, Any]:
        """Get rate limit status for an agent.

        Args:
            agent_id: Agent identifier

        Returns:
            Dictionary with rate limit status

        Example:
            >>> policy = RateLimitPolicy()
            >>> status = policy.get_status("agent-123")
            >>> print(status["limits"]["commit"]["current_tokens"])
        """
        status: Dict[str, Any] = {
            "agent_id": agent_id,
            "limits": {}
        }

        # Get per-agent limits
        for limit_type in self.per_agent_manager.limits.keys():
            tokens = self.per_agent_manager.get_tokens(agent_id, limit_type)
            bucket = self.per_agent_manager.get_bucket(agent_id, limit_type)

            if tokens is not None and bucket:
                bucket_info = bucket.get_info()
                status["limits"][limit_type] = {
                    "current_tokens": round(tokens, 2),
                    "max_tokens": bucket_info["max_tokens"],
                    "fill_percentage": bucket_info["fill_percentage"],
                    "wait_time_for_one": round(bucket.get_wait_time(1), 2)
                }

        return status

    def reset_limits(
        self,
        agent_id: Optional[str] = None,
        limit_type: Optional[str] = None
    ) -> None:
        """Reset rate limits (useful for testing).

        Args:
            agent_id: Specific agent to reset (None = all)
            limit_type: Specific limit type to reset (None = all)

        Example:
            >>> policy = RateLimitPolicy()
            >>> policy.reset_limits("agent-123", "commit")
            >>> policy.reset_limits()  # Reset all
        """
        self.per_agent_manager.reset(agent_id, limit_type)
        if agent_id is None:
            # Also reset global limits if resetting everything
            self.global_manager.reset()


# Backward-compatible alias (deprecated)
RateLimitPolicy = TokenBucketRateLimitPolicy
