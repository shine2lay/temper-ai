# Task: m4-05 - Rate Limiting Service

**Priority:** CRITICAL (P0 - Security)
**Effort:** 12 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Implement rate limiting service using token bucket algorithm. Supports per-agent, per-operation, and global rate limits. Tracks API calls, commits, deployments, tool invocations. Integrates with observability for rate limit metrics and prevents abuse/runaway agents.

---

## Files to Create

- `src/safety/policies/rate_limit.py` - Rate limiting policy implementation
- `src/safety/rate_limiter.py` - Token bucket algorithm implementation
- `config/safety/rate_limits.yaml` - Default rate limit configurations
- `tests/safety/policies/test_rate_limit.py` - Rate limit policy tests
- `tests/safety/test_rate_limiter.py` - Algorithm tests

---

## Files to Modify

- `src/core/agent_executor.py` - Add rate limit checks before tool execution

---

## Acceptance Criteria

### Core Functionality
- [ ] Token bucket algorithm with configurable refill rate and capacity
- [ ] Per-agent rate limits: 10 commits/hour, 2 deploys/hour, 100 tool calls/hour
- [ ] Global rate limits across all agents (1000 tool calls/hour total)
- [ ] Cooldown periods after limit violations (exponential backoff)
- [ ] YAML configuration for custom limits

### Rate Limit Types
- [ ] `commit_rate`: Max commits per time window
- [ ] `deployment_rate`: Max deployments per time window
- [ ] `tool_call_rate`: Max tool invocations per time window
- [ ] `api_call_rate`: Max API calls per time window
- [ ] `llm_call_rate`: Max LLM calls per time window

### Observability Integration
- [ ] Metrics: rate limit hits, violations, current token counts
- [ ] Logging: all violations with agent context
- [ ] Dashboard integration: real-time rate limit status

### Testing
- [ ] Unit tests for token bucket algorithm (>90% coverage)
- [ ] Tests for various limit scenarios (burst, sustained, cooldown)
- [ ] Concurrency tests (thread-safe token operations)
- [ ] Integration tests with agent executor

### Security Controls
- [ ] Atomic token operations (no race conditions)
- [ ] Per-agent isolation (one agent can't exhaust another's quota)
- [ ] Violation history tracked for pattern detection

---

## Implementation Details

### Token Bucket Algorithm

```python
import time
import threading
from typing import Dict, Optional
from dataclasses import dataclass

@dataclass
class RateLimit:
    """Rate limit configuration."""
    max_tokens: int          # Bucket capacity
    refill_rate: float       # Tokens per second
    refill_period: float     # Refill interval in seconds
    burst_size: int          # Max burst capacity

class TokenBucket:
    """Thread-safe token bucket rate limiter."""

    def __init__(self, rate_limit: RateLimit):
        self.max_tokens = rate_limit.max_tokens
        self.refill_rate = rate_limit.refill_rate
        self.refill_period = rate_limit.refill_period
        self.burst_size = min(rate_limit.burst_size, rate_limit.max_tokens)

        self.tokens = float(self.max_tokens)
        self.last_refill = time.time()
        self.lock = threading.Lock()

    def consume(self, tokens: int = 1) -> bool:
        """
        Attempt to consume tokens.

        Returns:
            True if tokens consumed, False if rate limit hit
        """
        with self.lock:
            self._refill()

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    def _refill(self):
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_refill

        if elapsed >= self.refill_period:
            # Calculate tokens to add
            tokens_to_add = (elapsed / self.refill_period) * self.refill_rate
            self.tokens = min(self.max_tokens, self.tokens + tokens_to_add)
            self.last_refill = now

    def get_tokens(self) -> float:
        """Get current token count (for observability)."""
        with self.lock:
            self._refill()
            return self.tokens

    def get_wait_time(self, tokens: int = 1) -> float:
        """Calculate wait time until tokens available."""
        with self.lock:
            self._refill()

            if self.tokens >= tokens:
                return 0.0

            tokens_needed = tokens - self.tokens
            return (tokens_needed / self.refill_rate) * self.refill_period
```

### RateLimitPolicy Implementation

```python
from src.safety.base import BaseSafetyPolicy
from src.safety.interfaces import ValidationResult, SafetyViolation, ViolationSeverity
from src.safety.rate_limiter import TokenBucket, RateLimit

class RateLimitPolicy(BaseSafetyPolicy):
    """Rate limiting safety policy."""

    name = "rate_limit_policy"
    version = "1.0"
    priority = 200  # High priority - check before resource-intensive operations

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

        # Initialize rate limiters
        self.limiters: Dict[str, Dict[str, TokenBucket]] = {}

        # Load limits from config
        self.limits = self._load_limits(config)

    def _load_limits(self, config: Dict[str, Any]) -> Dict[str, RateLimit]:
        """Load rate limit configurations."""
        limits = {}

        # Default limits
        limits['commit_rate'] = RateLimit(
            max_tokens=10,
            refill_rate=10/3600,  # 10 per hour
            refill_period=1.0,
            burst_size=2
        )

        limits['deployment_rate'] = RateLimit(
            max_tokens=2,
            refill_rate=2/3600,  # 2 per hour
            refill_period=1.0,
            burst_size=1
        )

        limits['tool_call_rate'] = RateLimit(
            max_tokens=100,
            refill_rate=100/3600,  # 100 per hour
            refill_period=1.0,
            burst_size=10
        )

        # Override with config
        if 'rate_limits' in config:
            for limit_name, limit_config in config['rate_limits'].items():
                limits[limit_name] = RateLimit(**limit_config)

        return limits

    def _get_limiter(self, agent_id: str, limit_type: str) -> TokenBucket:
        """Get or create rate limiter for agent and limit type."""
        if agent_id not in self.limiters:
            self.limiters[agent_id] = {}

        if limit_type not in self.limiters[agent_id]:
            self.limiters[agent_id][limit_type] = TokenBucket(
                self.limits[limit_type]
            )

        return self.limiters[agent_id][limit_type]

    def _validate_impl(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> ValidationResult:
        """Validate action against rate limits."""
        agent_id = context.get('agent_id', 'unknown')
        action_type = action.get('type', 'unknown')

        # Map action types to rate limit types
        limit_type_map = {
            'git_commit': 'commit_rate',
            'deploy': 'deployment_rate',
            'tool_call': 'tool_call_rate',
            'api_call': 'api_call_rate',
        }

        limit_type = limit_type_map.get(action_type)

        if not limit_type or limit_type not in self.limits:
            # No rate limit for this action type
            return ValidationResult(valid=True, violations=[], metadata={})

        # Get rate limiter and check limit
        limiter = self._get_limiter(agent_id, limit_type)

        if not limiter.consume():
            # Rate limit hit
            wait_time = limiter.get_wait_time()

            violation = SafetyViolation(
                policy_name=self.name,
                severity=ViolationSeverity.HIGH,
                message=f"Rate limit exceeded for {limit_type}",
                action=action_type,
                context={
                    'agent_id': agent_id,
                    'limit_type': limit_type,
                    'wait_time': wait_time,
                    'current_tokens': limiter.get_tokens()
                },
                timestamp=time.time(),
                remediation_hint=f"Wait {wait_time:.1f} seconds before retrying"
            )

            return ValidationResult(
                valid=False,
                violations=[violation],
                metadata={'wait_time': wait_time}
            )

        # Rate limit OK
        return ValidationResult(
            valid=True,
            violations=[],
            metadata={
                'tokens_remaining': limiter.get_tokens(),
                'limit_type': limit_type
            }
        )
```

---

## Configuration Example

```yaml
# config/safety/rate_limits.yaml

rate_limits:
  # Commit rate limiting
  commit_rate:
    max_tokens: 10           # Max 10 commits
    refill_rate: 0.00278     # 10 per hour (10/3600)
    refill_period: 1.0       # Check every second
    burst_size: 2            # Allow 2 immediate commits

  # Deployment rate limiting
  deployment_rate:
    max_tokens: 2            # Max 2 deployments
    refill_rate: 0.000556    # 2 per hour
    refill_period: 1.0
    burst_size: 1

  # Tool call rate limiting
  tool_call_rate:
    max_tokens: 100          # Max 100 tool calls
    refill_rate: 0.0278      # 100 per hour
    refill_period: 1.0
    burst_size: 10

  # LLM call rate limiting
  llm_call_rate:
    max_tokens: 50           # Max 50 LLM calls
    refill_rate: 0.0139      # 50 per hour
    refill_period: 1.0
    burst_size: 5

# Global limits (across all agents)
global_limits:
  total_tool_calls:
    max_tokens: 1000
    refill_rate: 0.278       # 1000 per hour
    refill_period: 1.0
    burst_size: 50
```

---

## Test Strategy

### Unit Tests
- Test token bucket algorithm (consume, refill, wait time)
- Test thread safety (concurrent token consumption)
- Test rate limit policy with various action types
- Test per-agent isolation
- Test configuration loading

### Integration Tests
- Test with real agent executor
- Test observability integration (metrics logged)
- Test cooldown behavior
- Test burst vs sustained load scenarios

### Performance Tests
- Benchmark token operations (<1ms per operation)
- Test with 100+ concurrent agents
- Measure memory overhead per agent

---

## Success Metrics

- [ ] Test coverage >90%
- [ ] Token operations are atomic (no race conditions)
- [ ] Rate limit overhead <2ms per operation
- [ ] Handles 1000+ agents concurrently
- [ ] Memory overhead <10MB for 100 agents

---

## Dependencies

**Blocked by:** m4-01, m4-02, m4-03
**Blocks:** m4-08

---

## Design References

- Token Bucket Algorithm: https://en.wikipedia.org/wiki/Token_bucket
- Leaky Bucket variant for comparison
- Python threading.Lock for atomicity

---

## Notes

**Performance is critical** - this is in the critical path for all agent actions.

**Thread safety** - Must handle concurrent access from multiple agents.

**Observability** - Track rate limit violations for anomaly detection (runaway agents).

**Graceful degradation** - If rate limiter fails, should default to allowing action (with logging).
