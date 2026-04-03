"""Node ABC — the composable interface everything implements.

The graph executor calls node.run() without knowing what type it is.
AgentNode runs an agent. StageNode runs a sub-graph. Future node types
implement the same interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from temper_ai.shared.types import ExecutionContext, NodeResult
from temper_ai.stage.models import NodeConfig


class Node(ABC):
    """Base interface for all graph nodes.

    Attributes:
        name: Unique name within the parent graph.
        config: The resolved NodeConfig for this node.
    """

    def __init__(self, config: NodeConfig):
        self.name = config.name
        self.config = config

    @abstractmethod
    def run(self, input_data: dict, context: ExecutionContext) -> NodeResult:
        """Execute this node. Returns a uniform NodeResult."""
        ...

    @property
    def depends_on(self) -> list[str]:
        """Dependencies — names of nodes that must complete before this one."""
        return self.config.depends_on

    @property
    def condition(self) -> dict | None:
        """Optional condition — if set, node is skipped when condition evaluates to False."""
        return self.config.condition

    @property
    def loop_to(self) -> str | None:
        """If set, re-execute the named node when this node fails."""
        return self.config.loop_to

    @property
    def max_loops(self) -> int:
        """Maximum loop iterations (only relevant if loop_to is set)."""
        return self.config.max_loops

    @property
    def loop_condition(self) -> dict | None:
        """Optional condition that triggers a loop rewind when met (on COMPLETED nodes)."""
        return self.config.loop_condition
