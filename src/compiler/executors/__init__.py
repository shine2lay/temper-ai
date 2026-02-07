"""Stage execution modules.

Provides different execution strategies for workflow stages.
"""
from typing import Callable

from src.agents.base_agent import BaseAgent
from src.compiler.executors.adaptive import AdaptiveStageExecutor
from src.compiler.executors.base import StageExecutor
from src.compiler.executors.parallel import ParallelStageExecutor
from src.compiler.executors.sequential import SequentialStageExecutor
from src.schemas import AgentConfig

AgentCreator = Callable[[AgentConfig], BaseAgent]
"""Type alias for a callable that creates an agent from its configuration."""

__all__ = [
    "AgentCreator",
    "StageExecutor",
    "SequentialStageExecutor",
    "ParallelStageExecutor",
    "AdaptiveStageExecutor",
]
