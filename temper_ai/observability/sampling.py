"""Sampling strategies for observability data collection.

Determines which workflows/executions should be fully tracked vs skipped,
reducing overhead in high-throughput environments.
"""
import logging
import random
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@dataclass
class SamplingContext:
    """Context provided to sampling strategies for decision-making."""

    workflow_id: str = ""
    workflow_name: str = ""
    environment: str = ""
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SamplingDecision:
    """Result of a sampling decision."""

    sampled: bool
    reason: str
    strategy_name: str


@runtime_checkable
class SamplingStrategy(Protocol):
    """Protocol for sampling strategies."""

    @property
    def name(self) -> str:
        """Strategy name for logging/debugging."""
        ...

    def should_sample(self, context: SamplingContext) -> SamplingDecision:
        """Decide whether to sample this execution."""
        ...


class AlwaysSample:
    """Sample everything -- current default behavior."""

    @property
    def name(self) -> str:
        """Return strategy name."""
        return "always"

    def should_sample(self, context: SamplingContext) -> SamplingDecision:
        """Always sample: return True."""
        return SamplingDecision(
            sampled=True, reason="always sample", strategy_name=self.name
        )


class NeverSample:
    """Disable observability tracking."""

    @property
    def name(self) -> str:
        """Return strategy name."""
        return "never"

    def should_sample(self, context: SamplingContext) -> SamplingDecision:
        """Never sample: return False."""
        return SamplingDecision(
            sampled=False, reason="never sample", strategy_name=self.name
        )


class RateSample:
    """Sample based on random probability.

    Args:
        rate: Probability of sampling (0.0 to 1.0)

    Raises:
        ValueError: If rate is outside [0.0, 1.0]
    """

    def __init__(self, rate: float) -> None:
        """Initialize with sampling rate (0.0-1.0)."""
        if not 0.0 <= rate <= 1.0:
            raise ValueError(
                f"Sample rate must be between 0.0 and 1.0, got {rate}"
            )
        self._rate = rate

    @property
    def name(self) -> str:
        """Return strategy name with rate value."""
        return f"rate({self._rate})"

    def should_sample(self, context: SamplingContext) -> SamplingDecision:
        """Sample based on random probability."""
        sampled = random.random() < self._rate  # noqa: S311
        return SamplingDecision(
            sampled=sampled,
            reason=f"rate={self._rate}",
            strategy_name=self.name,
        )


class RuleBasedSample:
    """Sample based on matching rules (regex patterns, tags, environments).

    First matching rule wins. If no rule matches, uses default_sampled.

    Args:
        name_patterns: Regex patterns to match workflow_name (sample if match)
        tag_whitelist: Tags that trigger sampling (sample if any tag matches)
        environment_whitelist: Environments that trigger sampling
        default_sampled: Default when no rule matches
    """

    def __init__(
        self,
        name_patterns: Optional[List[str]] = None,
        tag_whitelist: Optional[List[str]] = None,
        environment_whitelist: Optional[List[str]] = None,
        default_sampled: bool = True,
    ) -> None:
        """Initialize with name patterns and filter rules."""
        self._name_patterns = [re.compile(p) for p in (name_patterns or [])]
        self._tag_whitelist = set(tag_whitelist or [])
        self._environment_whitelist = set(environment_whitelist or [])
        self._default_sampled = default_sampled

    @property
    def name(self) -> str:
        """Return strategy name."""
        return "rule_based"

    def should_sample(self, context: SamplingContext) -> SamplingDecision:
        """Sample based on pattern matching rules."""
        return self._check_rules(context)

    def _check_rules(self, context: SamplingContext) -> SamplingDecision:
        """Evaluate rules in priority order: name, tags, environment."""
        name_decision = self._check_name_patterns(context)
        if name_decision is not None:
            return name_decision

        tag_decision = self._check_tag_whitelist(context)
        if tag_decision is not None:
            return tag_decision

        env_decision = self._check_environment(context)
        if env_decision is not None:
            return env_decision

        return SamplingDecision(
            sampled=self._default_sampled,
            reason="no rule matched, using default",
            strategy_name=self.name,
        )

    def _check_name_patterns(
        self, context: SamplingContext
    ) -> Optional[SamplingDecision]:
        """Check workflow name against regex patterns."""
        for pattern in self._name_patterns:
            if pattern.search(context.workflow_name):
                return SamplingDecision(
                    sampled=True,
                    reason=f"name matched '{pattern.pattern}'",
                    strategy_name=self.name,
                )
        return None

    def _check_tag_whitelist(
        self, context: SamplingContext
    ) -> Optional[SamplingDecision]:
        """Check if any context tags are in the whitelist."""
        if self._tag_whitelist and context.tags:
            matched = self._tag_whitelist.intersection(context.tags)
            if matched:
                return SamplingDecision(
                    sampled=True,
                    reason=f"tag matched: {sorted(matched)}",
                    strategy_name=self.name,
                )
        return None

    def _check_environment(
        self, context: SamplingContext
    ) -> Optional[SamplingDecision]:
        """Check if the environment is whitelisted."""
        if self._environment_whitelist and context.environment:
            if context.environment in self._environment_whitelist:
                return SamplingDecision(
                    sampled=True,
                    reason=f"environment '{context.environment}' whitelisted",
                    strategy_name=self.name,
                )
        return None


class CompositeSampler:
    """Combines multiple strategies with OR logic -- sample if any says yes.

    Args:
        strategies: List of sampling strategies to evaluate
    """

    def __init__(self, strategies: List[SamplingStrategy]) -> None:
        """Initialize with list of strategies (OR logic)."""
        self._strategies = strategies

    @property
    def name(self) -> str:
        """Return strategy name."""
        return "composite"

    def should_sample(self, context: SamplingContext) -> SamplingDecision:
        """Sample if any strategy says yes."""
        for strategy in self._strategies:
            decision = strategy.should_sample(context)
            if decision.sampled:
                return SamplingDecision(
                    sampled=True,
                    reason=f"matched by {decision.strategy_name}: {decision.reason}",
                    strategy_name=self.name,
                )
        return SamplingDecision(
            sampled=False,
            reason="no strategy approved sampling",
            strategy_name=self.name,
        )
