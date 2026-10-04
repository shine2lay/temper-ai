"""The team node: the one node a ``strategy: team`` stage holds. A stub until the team runtime
(T4 messaging, T5 inboxes, M1 leader mode) is built.

The loader builds a team stage like any strategy stage: ``build_topology("team", members,
strategy_config)`` returns ``[TeamNode]`` (``temper_ai.pi_agent.team.team_topology``) and the
stage becomes ``StageNode(stage, [TeamNode])``. The stage's sub-graph executor then calls
``TeamNode.run(input_data, context)`` like any node's ``run``: ``input_data`` is the stage's
input (its ``input_map`` values, such as ``goal``), ``context.node_path`` is the stage's name.
What ``run`` returns is the stage's result, which later nodes read (``<stage>.output``,
``<stage>.structured.<key>``, ``<stage>.status``).

Until the runtime exists, ``run`` fails red with ``TEAM_NOT_BUILT``; it never passes.
"""

from __future__ import annotations

from temper_ai.pi_agent.team import TEAM_NOT_BUILT, TeamSettings, member_name
from temper_ai.shared.types import ExecutionContext, NodeResult, Status
from temper_ai.stage.models import NodeConfig
from temper_ai.stage.node import Node


class TeamNode(Node):
    """The one node a team stage holds; the graph executor runs it like any node.

    It gets the checked settings (:class:`~temper_ai.pi_agent.team.TeamSettings`) and the
    members' resolved agent configs when the workflow loads, and the stage's input at run.
    """

    def __init__(self, config: NodeConfig, members: list[dict], settings: TeamSettings):
        super().__init__(config)
        self.members = [dict(m) for m in members]
        self.settings = settings

    def agent_configs(self) -> list[dict]:
        """The members' agent configs (the stage's ``agent_configs()`` collects these)."""
        return [dict(m) for m in self.members]

    def run(self, input_data: dict, context: ExecutionContext) -> NodeResult:
        """Fails red until the team runtime (T4/T5/M1) replaces it."""
        return NodeResult(
            status=Status.FAILED, output=TEAM_NOT_BUILT, error=TEAM_NOT_BUILT,
            metadata={"team": {"members": [member_name(m) for m in self.members],
                               "settings": self.settings.as_dict()}})
