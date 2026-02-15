"""Stage execution modules.

Provides different execution strategies for workflow stages.
"""
from typing import Callable

from src.agent.base_agent import BaseAgent
from src.stage.executors.adaptive import AdaptiveStageExecutor
from src.stage.executors.base import StageExecutor
from src.stage.executors.parallel import ParallelStageExecutor
from src.stage.executors.sequential import SequentialStageExecutor
from src.storage.schemas import AgentConfig

AgentCreator = Callable[[AgentConfig], BaseAgent]
"""Type alias for a callable that creates an agent from its configuration."""

__all__ = [
    "AgentCreator",
    "StageExecutor",
    "SequentialStageExecutor",
    "ParallelStageExecutor",
    "AdaptiveStageExecutor",
]
