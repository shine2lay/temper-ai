"""Stage module — composable graph execution engine.

Two node types:
- AgentNode: leaf node, runs a single agent
- StageNode: composite node, contains child nodes (recursive)

One executor runs everything — workflows, stages, and nested stages
all use the same execution engine.

Usage:
    from temper_ai.stage import load_workflow, execute_workflow

    nodes, config = load_workflow("workflows/sdlc_pipeline")
    result = execute_workflow(nodes, inputs, context)
"""

from temper_ai.stage.executor import execute_graph
from temper_ai.stage.loader import GraphLoader
from temper_ai.stage.node import Node

__all__ = [
    "Node",
    "execute_graph",
    "GraphLoader",
]
