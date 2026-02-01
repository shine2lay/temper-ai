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
from typing import Dict, Any, List, Optional
from src.safety.base import BaseSafetyPolicy
from src.safety.interfaces import ValidationResult, SafetyViolation, ViolationSeverity
from src.safety.token_bucket import TokenBucket, TokenBucketManager, RateLimit


class RateLimitPolicy(BaseSafetyPolicy):
    """Rate limiting policy using token bucket algorithm.

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
        >>> policy = RateLimitPolicy(config)
        >>> result = policy.validate(
        ...     action={"operation": "git_commit"},
        ...     context={"agent_id": "agent-123"}
        ... )
    """

    # Default rate limits (per agent)
    DEFAULT_LIMITS = {
        "commit": RateLimit(
            max_tokens=10,
            refill_rate=10/3600,  # 10 per hour
            refill_period=1.0,
            burst_size=2
        ),
        "deploy": RateLimit(
            max_tokens=2,
            refill_rate=2/3600,  # 2 per hour
            refill_period=1.0,
            burst_size=1
        ),
        "tool_call": RateLimit(
            max_tokens=100,
            refill_rate=100/3600,  # 100 per hour
            refill_period=1.0,
            burst_size=10
        ),
        "llm_call": RateLimit(
            max_tokens=50,
            refill_rate=50/3600,  # 50 per hour
            refill_period=1.0,
            burst_size=5
        ),
        "api_call": RateLimit(
            max_tokens=1000,
            refill_rate=1000/3600,  # 1000 per hour
            refill_period=1.0,
            burst_size=50
        ),
    }

    # Default global limits (across all agents)
    DEFAULT_GLOBAL_LIMITS = {
        "total_tool_calls": RateLimit(
            max_tokens=1000,
            refill_rate=1000/3600,  # 1000 per hour total
            refill_period=1.0,
            burst_size=50
        ),
    }

    # Map action types to rate limit types
    ACTION_TO_LIMIT_TYPE = {
        "git_commit": "commit",
        "commit": "commit",
        "deploy": "deploy",
        "deployment": "deploy",
        "tool_call": "tool_call",
        "tool_execution": "tool_call",
        "llm_call": "llm_call",
        "api_call": "api_call",
        "api_request": "api_call",
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
        if cooldown_multiplier > 100:
            raise ValueError(
                f"cooldown_multiplier must be <= 100 (safety limit), got {cooldown_multiplier}. "
                f"Hint: Values > 100 can create extremely long wait times."
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
        if "rate_limits" in config:
            if not isinstance(config["rate_limits"], dict):
                raise ValueError(
                    f"rate_limits must be a dictionary, got {type(config['rate_limits']).__name__}"
                )

            for limit_type, limit_config in config["rate_limits"].items():
                # Validate limit_type is a string
                if not isinstance(limit_type, str):
                    raise ValueError(
                        f"Rate limit type must be string, got {type(limit_type).__name__}"
                    )

                if isinstance(limit_config, dict):
                    # Validate all required fields are present
                    required_fields = ["max_tokens", "refill_rate"]
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
        if "global_limits" in config:
            if not isinstance(config["global_limits"], dict):
                raise ValueError(
                    f"global_limits must be a dictionary, got {type(config['global_limits']).__name__}"
                )

            for limit_type, limit_config in config["global_limits"].items():
                # Validate limit_type is a string
                if not isinstance(limit_type, str):
                    raise ValueError(
                        f"Global rate limit type must be string, got {type(limit_type).__name__}"
                    )

                if isinstance(limit_config, dict):
                    # Validate all required fields are present
                    required_fields = ["max_tokens", "refill_rate"]
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
        return 85

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
            entity_id = "global"
            scope = "global"

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
        if wait_time > 3600:  # > 1 hour
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
                "entity_id": entity_id if scope == "per-agent" else "global",
                "wait_time": round(wait_time, 2),
                "current_tokens": round(current_tokens, 2),
                "max_tokens": bucket_info.get("max_tokens", 0),
                "refill_rate": bucket_info.get("refill_rate", 0),
                "fill_percentage": bucket_info.get("fill_percentage", 0)
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
        if seconds >= 3600:
            hours = seconds / 3600
            return f"{hours:.1f} hour{'s' if hours >= 2 else ''}"
        elif seconds >= 60:
            minutes = seconds / 60
            return f"{minutes:.1f} minute{'s' if minutes >= 2 else ''}"
        else:
            return f"{seconds:.1f} second{'s' if seconds >= 2 else ''}"

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
