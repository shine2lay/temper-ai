"""The team node: the one node a ``strategy: team`` stage holds (switched off with the Pi agent).

The loader builds a team stage like any strategy stage: ``build_topology("team", members,
strategy_config)`` returns ``[TeamNode]`` (``temper_ai.pi_agent.team.team_topology``) and the
stage becomes ``StageNode(stage, [TeamNode])``. The stage's sub-graph executor then calls
``TeamNode.run(input_data, context)`` like any node's ``run``: ``input_data`` is the stage's
input (its ``input_map`` values, such as ``goal``), ``context.node_path`` is the stage's name.
What ``run`` returns is the stage's result, which later nodes read (``<stage>.output``,
``<stage>.structured.<key>``, ``<stage>.status``).

``run`` is the leader loop (:func:`~temper_ai.pi_agent.team_leader.run_team_node`, task #38):
it checks the team again with the goal it was handed, opens the team and drives it until the
leader's done is recorded (completed, with Temper's done record as the structured output),
the owner stops it or a member's turn fails (failed, red -- and the stage with it), or the run
is cancelled. An owner wait on the way parks the run; the answer carries it on through here.
"""

from __future__ import annotations

from typing import ClassVar

from temper_ai.pi_agent.team import TeamSettings
from temper_ai.shared.types import ExecutionContext, NodeResult
from temper_ai.stage.models import NodeConfig
from temper_ai.stage.node import Node


class TeamNode(Node):
    """The one node a team stage holds; the graph executor runs it like any node.

    It gets the checked settings (:class:`~temper_ai.pi_agent.team.TeamSettings`) and the
    members' resolved agent configs when the workflow loads, and the stage's input at run.
    """

    #: A failed team fails its stage too: never the tolerant "completed" of other stages
    #: (R2 B13, M2-roles P2).
    fails_stage: ClassVar[bool] = True
    #: A team stage has no deadline: its pause and waits never expire (R2 B10, A8).
    no_stage_timeout: ClassVar[bool] = True

    def __init__(self, config: NodeConfig, members: list[dict], settings: TeamSettings):
        super().__init__(config)
        self.members = [dict(m) for m in members]
        self.settings = settings

    def agent_configs(self) -> list[dict]:
        """The members' agent configs (the stage's ``agent_configs()`` collects these)."""
        return [dict(m) for m in self.members]

    def run(self, input_data: dict, context: ExecutionContext) -> NodeResult:
        """The team's leader loop (see :mod:`temper_ai.pi_agent.team_leader`)."""
        from temper_ai.pi_agent.team_leader import run_team_node

        return run_team_node(self, input_data, context)
