"""Helper free functions for StrategyRegistry to reduce class size."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from temper_ai.agent.strategies.registry import (
        ResolverMetadata,
        StrategyMetadata,
    )

logger = logging.getLogger(__name__)


# Default strategy definitions: (names, module_path, class_name)
_DEFAULT_STRATEGIES: list[tuple[list[str], str, str]] = [
    (
        ["consensus"],
        "temper_ai.agent.strategies.consensus",
        "ConsensusStrategy",
    ),
    (
        ["concatenate"],
        "temper_ai.agent.strategies.concatenate",
        "ConcatenateStrategy",
    ),
    (
        ["debate", "debate_and_synthesize", "llm_debate_and_synthesize"],
        "temper_ai.agent.strategies.multi_round",
        "MultiRoundStrategy",
    ),
    (
        ["dialogue"],
        "temper_ai.agent.strategies.multi_round",
        "MultiRoundStrategy",
    ),
    (
        ["multi_round"],
        "temper_ai.agent.strategies.multi_round",
        "MultiRoundStrategy",
    ),
    (
        ["leader"],
        "temper_ai.agent.strategies.leader",
        "LeaderCollaborationStrategy",
    ),
]

# Default resolver definitions: name -> (module_path, class_name)
_DEFAULT_RESOLVERS: dict[str, tuple[str, str]] = {
    "merit_weighted": (
        "temper_ai.agent.strategies.merit_weighted",
        "MeritWeightedResolver",
    ),
    "highest_confidence": (
        "temper_ai.agent.strategies.conflict_resolution",
        "HighestConfidenceResolver",
    ),
    "random_tiebreaker": (
        "temper_ai.agent.strategies.conflict_resolution",
        "RandomTiebreakerResolver",
    ),
    "human_escalation": (
        "temper_ai.agent.strategies.merit_weighted",
        "HumanEscalationResolver",
    ),
}


def build_strategy_metadata_list(
    strategies: dict[str, Any],
) -> list[StrategyMetadata]:
    """Build StrategyMetadata list from the registered strategies dict."""
    from temper_ai.agent.strategies.registry import (
        StrategyMetadata as _StrategyMetadata,
    )

    metadata_list: list[_StrategyMetadata] = []
    for name, strategy_class in list(strategies.items()):
        try:
            instance = strategy_class()
            capabilities = instance.get_capabilities()
            meta = instance.get_metadata()
            metadata_list.append(
                _StrategyMetadata(
                    name=name,
                    class_name=strategy_class.__name__,
                    description=meta.get("description", ""),
                    capabilities=capabilities,
                    config_schema=meta.get("config_schema", {}),
                )
            )
        except Exception as exc:
            logger.warning(
                "Failed to instantiate strategy %r for metadata: %s", name, exc
            )
            metadata_list.append(
                _StrategyMetadata(
                    name=name,
                    class_name=strategy_class.__name__,
                    description="",
                    capabilities={},
                    config_schema={},
                )
            )
    return metadata_list


def build_resolver_metadata_list(
    resolvers: dict[str, Any],
) -> list[ResolverMetadata]:
    """Build ResolverMetadata list from the registered resolvers dict."""
    from temper_ai.agent.strategies.registry import (
        ResolverMetadata as _ResolverMetadata,
    )

    metadata_list: list[_ResolverMetadata] = []
    for name, resolver_class in list(resolvers.items()):
        try:
            instance = resolver_class()
            capabilities = instance.get_capabilities()
            meta = instance.get_metadata()
            metadata_list.append(
                _ResolverMetadata(
                    name=name,
                    class_name=resolver_class.__name__,
                    description=meta.get("description", ""),
                    capabilities=capabilities,
                    config_schema=meta.get("config_schema", {}),
                )
            )
        except Exception as exc:
            logger.warning(
                "Failed to instantiate resolver %r for metadata: %s", name, exc
            )
            metadata_list.append(
                _ResolverMetadata(
                    name=name,
                    class_name=resolver_class.__name__,
                    description="",
                    capabilities={},
                    config_schema={},
                )
            )
    return metadata_list


def build_default_strategies() -> list[tuple[list[str], str, str]]:
    """Return the list of default strategy definitions."""
    return _DEFAULT_STRATEGIES


def build_default_resolvers() -> dict[str, tuple[str, str]]:
    """Return the dict of default resolver definitions."""
    return _DEFAULT_RESOLVERS
