"""Rate Limit Policy using Token Bucket Algorithm.

Enforces rate limits on operations (commits, deploys, tool/LLM/API calls)
to prevent resource exhaustion and cost overruns. Uses token bucket algorithm
for smooth rate limiting with burst support.
"""

from typing import Any

from temper_ai.safety.base import BaseSafetyPolicy
from temper_ai.safety.constants import (
    ACTION_TYPE_API_CALL,
    ACTION_TYPE_COMMIT,
    ACTION_TYPE_DEPLOY,
    ACTION_TYPE_LLM_CALL,
    ACTION_TYPE_TOOL_CALL,
    GLOBAL_LIMITS_KEY,
    MAX_TOKENS_KEY,
    RATE_LIMIT_PRIORITY,
    RATE_LIMITS_KEY,
    REFILL_RATE_KEY,
    SCOPE_GLOBAL,
)
from temper_ai.safety.interfaces import SafetyViolation, ValidationResult
from temper_ai.safety.policies._rate_limit_helpers import check_limit, format_wait_time
from temper_ai.safety.token_bucket import RateLimit, TokenBucketManager
from temper_ai.shared.constants.durations import SECONDS_PER_HOUR
from temper_ai.shared.constants.limits import (
    LARGE_ITEM_LIMIT,
    MULTIPLIER_LARGE,
    SMALL_ITEM_LIMIT,
    THRESHOLD_MEDIUM_COUNT,
    VERY_LARGE_ITEM_LIMIT,
)

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


class TokenBucketRateLimitPolicy(BaseSafetyPolicy):
    """Token-bucket-based rate limiting policy with burst support.

    Config: rate_limits (per-type), per_agent (bool), global_limits, cooldown_multiplier.
    For window-based limiting, see ``WindowRateLimitPolicy`` in ``temper_ai.safety.rate_limiter``.
    """

    # Default rate limits (per agent)
    DEFAULT_LIMITS = {
        ACTION_TYPE_COMMIT: RateLimit(
            max_tokens=DEFAULT_COMMITS_PER_HOUR,
            refill_rate=DEFAULT_COMMITS_PER_HOUR / SECONDS_PER_HOUR,
            refill_period=float(SMALL_ITEM_LIMIT // SMALL_ITEM_LIMIT),
            burst_size=DEFAULT_COMMITS_BURST,
        ),
        ACTION_TYPE_DEPLOY: RateLimit(
            max_tokens=DEFAULT_DEPLOYS_PER_HOUR,
            refill_rate=DEFAULT_DEPLOYS_PER_HOUR / SECONDS_PER_HOUR,
            refill_period=float(SMALL_ITEM_LIMIT // SMALL_ITEM_LIMIT),
            burst_size=DEFAULT_DEPLOYS_BURST,
        ),
        ACTION_TYPE_TOOL_CALL: RateLimit(
            max_tokens=DEFAULT_TOOL_CALLS_PER_HOUR,
            refill_rate=DEFAULT_TOOL_CALLS_PER_HOUR / SECONDS_PER_HOUR,
            refill_period=float(SMALL_ITEM_LIMIT // SMALL_ITEM_LIMIT),
            burst_size=DEFAULT_TOOL_CALLS_BURST,
        ),
        ACTION_TYPE_LLM_CALL: RateLimit(
            max_tokens=DEFAULT_LLM_CALLS_PER_HOUR,
            refill_rate=DEFAULT_LLM_CALLS_PER_HOUR / SECONDS_PER_HOUR,
            refill_period=float(SMALL_ITEM_LIMIT // SMALL_ITEM_LIMIT),
            burst_size=DEFAULT_LLM_CALLS_BURST,
        ),
        ACTION_TYPE_API_CALL: RateLimit(
            max_tokens=DEFAULT_API_CALLS_PER_HOUR,
            refill_rate=DEFAULT_API_CALLS_PER_HOUR / SECONDS_PER_HOUR,
            refill_period=float(SMALL_ITEM_LIMIT // SMALL_ITEM_LIMIT),
            burst_size=DEFAULT_API_CALLS_BURST,
        ),
    }

    # Default global limits (across all agents)
    DEFAULT_GLOBAL_LIMITS = {
        "total_tool_calls": RateLimit(
            max_tokens=DEFAULT_GLOBAL_TOOL_CALLS_PER_HOUR,
            refill_rate=DEFAULT_GLOBAL_TOOL_CALLS_PER_HOUR / SECONDS_PER_HOUR,
            refill_period=float(SMALL_ITEM_LIMIT // SMALL_ITEM_LIMIT),
            burst_size=DEFAULT_GLOBAL_TOOL_CALLS_BURST,
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

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize rate limit policy. Raises ValueError for invalid config."""
        super().__init__(config or {})

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
                f"cooldown_multiplier must be <= {MAX_COOLDOWN_MULTIPLIER} (safety limit), "
                f"got {cooldown_multiplier}. "
                f"Hint: Values > {MAX_COOLDOWN_MULTIPLIER} can create extremely long wait times."
            )
        self.cooldown_multiplier = cooldown_multiplier

        self.per_agent_manager = TokenBucketManager()
        self._load_per_agent_limits(config or {})

        self.global_manager = TokenBucketManager()
        self._load_global_limits(config or {})

    @property
    def rate_limits(self) -> dict[str, Any]:
        """Per-agent rate limits (keyed by limit type)."""
        return self.per_agent_manager.limits

    def _validate_rate_limit_config(
        self, limit_type: str, limit_config: Any
    ) -> RateLimit:
        """Validate and convert a single rate limit config to RateLimit."""
        if not isinstance(limit_type, str):
            raise ValueError(
                f"Rate limit type must be string, got {type(limit_type).__name__}"
            )
        if isinstance(limit_config, RateLimit):
            return limit_config
        if not isinstance(limit_config, dict):
            raise ValueError(
                f"Rate limit '{limit_type}' must be dict or RateLimit, "
                f"got {type(limit_config).__name__}"
            )
        required_fields = [MAX_TOKENS_KEY, REFILL_RATE_KEY]
        for field in required_fields:
            if field not in limit_config:
                raise ValueError(
                    f"Rate limit '{limit_type}' missing required field '{field}'"
                )
        try:
            return RateLimit(**limit_config)
        except (ValueError, TypeError) as e:
            raise ValueError(
                f"Invalid rate limit configuration for '{limit_type}': {e}"
            ) from e

    def _load_per_agent_limits(self, config: dict[str, Any]) -> None:
        """Load per-agent rate limits from config."""
        limits = self.DEFAULT_LIMITS.copy()
        if RATE_LIMITS_KEY not in config:
            for limit_type, rate_limit in limits.items():
                self.per_agent_manager.set_limit(limit_type, rate_limit)
            return
        if not isinstance(config[RATE_LIMITS_KEY], dict):
            raise ValueError(
                f"{RATE_LIMITS_KEY} must be a dictionary, "
                f"got {type(config[RATE_LIMITS_KEY]).__name__}"
            )
        for limit_type, limit_config in config[RATE_LIMITS_KEY].items():
            limits[limit_type] = self._validate_rate_limit_config(
                limit_type, limit_config
            )
        for limit_type, rate_limit in limits.items():
            self.per_agent_manager.set_limit(limit_type, rate_limit)

    def _load_global_limits(self, config: dict[str, Any]) -> None:
        """Load global rate limits from config."""
        limits = self.DEFAULT_GLOBAL_LIMITS.copy()
        if GLOBAL_LIMITS_KEY not in config:
            for limit_type, rate_limit in limits.items():
                self.global_manager.set_limit(limit_type, rate_limit)
            return
        if not isinstance(config[GLOBAL_LIMITS_KEY], dict):
            raise ValueError(
                f"{GLOBAL_LIMITS_KEY} must be a dictionary, "
                f"got {type(config[GLOBAL_LIMITS_KEY]).__name__}"
            )
        for limit_type, limit_config in config[GLOBAL_LIMITS_KEY].items():
            limits[limit_type] = self._validate_rate_limit_config(
                limit_type, limit_config
            )
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
        """Return policy priority (high to prevent resource exhaustion)."""
        return RATE_LIMIT_PRIORITY

    def _get_entity_id_and_scope(self, context: dict[str, Any]) -> tuple[str, str]:
        """Return (entity_id, scope) based on per_agent setting."""
        if self.per_agent:
            return context.get("agent_id", "unknown"), "per-agent"
        return SCOPE_GLOBAL, SCOPE_GLOBAL

    def _check_all_limits(
        self,
        limit_type: str,
        action_type: str,
        entity_id: str,
        scope: str,
        context: dict[str, Any],
    ) -> list[SafetyViolation]:
        """Check all applicable rate limits and return violations."""
        violations: list[SafetyViolation] = []
        agent_limited, agent_violation = check_limit(
            self.per_agent_manager,
            entity_id,
            limit_type,
            action_type,
            context,
            scope=scope,
            policy_name=self.name,
        )
        if agent_limited and agent_violation:
            violations.append(agent_violation)
        if limit_type == "tool_call":
            global_limited, global_violation = check_limit(
                self.global_manager,
                "global",
                "total_tool_calls",
                action_type,
                context,
                scope="global",
                policy_name=self.name,
            )
            if global_limited and global_violation:
                violations.append(global_violation)
        return violations

    def _validate_impl(
        self, action: dict[str, Any], context: dict[str, Any]
    ) -> ValidationResult:
        """Validate action against rate limits."""
        action_type = action.get("operation") or action.get("type", "unknown")
        limit_type = self.ACTION_TO_LIMIT_TYPE.get(action_type)
        if not limit_type:
            return ValidationResult(
                valid=True,
                violations=[],
                metadata={"action_type": action_type, "rate_limited": False},
                policy_name=self.name,
            )
        entity_id, scope = self._get_entity_id_and_scope(context)
        violations = self._check_all_limits(
            limit_type, action_type, entity_id, scope, context
        )
        retry_after = None
        if violations:
            retry_after = (
                max(v.metadata.get("wait_time", 0) for v in violations)
                * self.cooldown_multiplier
            )
        return ValidationResult(
            valid=len(violations) == 0,
            violations=violations,
            metadata={
                "action_type": action_type,
                "limit_type": limit_type,
                "rate_limited": bool(violations),
                "retry_after": retry_after,
            },
            policy_name=self.name,
        )

    def _format_wait_time(self, seconds: float) -> str:
        """Format wait time for human readability."""
        return format_wait_time(seconds)

    def get_status(self, agent_id: str) -> dict[str, Any]:
        """Get rate limit status for an agent."""
        status: dict[str, Any] = {"agent_id": agent_id, "limits": {}}
        for limit_type in self.per_agent_manager.limits.keys():
            tokens = self.per_agent_manager.get_tokens(agent_id, limit_type)
            bucket = self.per_agent_manager.get_bucket(agent_id, limit_type)
            if tokens is not None and bucket:
                bucket_info = bucket.get_info()
                status["limits"][limit_type] = {
                    "current_tokens": round(tokens, 2),
                    "max_tokens": bucket_info["max_tokens"],
                    "fill_percentage": bucket_info["fill_percentage"],
                    "wait_time_for_one": round(bucket.get_wait_time(1), 2),
                }
        return status

    def reset_limits(
        self,
        agent_id: str | None = None,
        limit_type: str | None = None,
    ) -> None:
        """Reset rate limits. Pass agent_id/limit_type to reset specific limits."""
        self.per_agent_manager.reset(agent_id, limit_type)
        if agent_id is None:
            self.global_manager.reset()


# Backward-compatible alias (deprecated)
RateLimitPolicy = TokenBucketRateLimitPolicy
