"""Stage execution modules.

Provides different execution strategies for workflow stages.
"""

from collections.abc import Callable

from temper_ai.agent.base_agent import BaseAgent
from temper_ai.stage.executors.adaptive import AdaptiveStageExecutor
from temper_ai.stage.executors.base import StageExecutor
from temper_ai.stage.executors.parallel import ParallelStageExecutor
from temper_ai.stage.executors.sequential import SequentialStageExecutor
from temper_ai.storage.schemas import AgentConfig

AgentCreator = Callable[[AgentConfig], BaseAgent]
"""Type alias for a callable that creates an agent from its configuration."""

__all__ = [
    "AgentCreator",
    "StageExecutor",
    "SequentialStageExecutor",
    "ParallelStageExecutor",
    "AdaptiveStageExecutor",
]
