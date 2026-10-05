"""The team strategy (``strategy: team``): a stage whose Pi members work as one team node.

A team is a stage with ``strategy: team`` (owner m02451, m02454), a fourth strategy beside
parallel, sequential and leader. Its members are the stage's ``agents:`` list: each one a
``type: pi`` agent config pointing at an existing pi role, known in the team by its ``name:``.
How the team runs is the stage's ``strategy_config``, in sections, each with a ``type`` plus that
type's options (build plan, "Team settings format"):

    strategy_config:
      mode:          {type: leader, leader: design}     # who gets the brief and says done
      communication: {type: all}                        # or {type: edges, edges: {...}}
      pause_after_rounds: 3                             # required, no default

* ``mode``: required; first type ``leader`` (``leader:`` names a member).
* ``communication``: ``all`` (any member may message any member; the default when the section
  is left out) or ``edges`` (each member lists the members it may start a conversation with,
  one direction, e.g. ``{design: [frontend, qa], frontend: [qa]}``). Every member must be
  reachable from the leader. The first team runtime is ``all`` only (R2 rule B7): ``edges`` is
  parsed and checked here, and the run-start check refuses it with ``EDGES_NOT_BUILT`` until
  the later slice builds it.
* ``pause_after_rounds``: how many rounds before the team pauses for the owner; required.

Each section type brings its own parser and check (``MODE_TYPES``, ``COMMUNICATION_TYPES``),
so a new type adds its options without touching the others. Unknown sections, types and keys
are refused by name. The strategy's check (:func:`validate_team`) reports every problem at once;
the run-start check (:mod:`temper_ai.pi_agent.team_check`) adds the members' roles, the
workflow's safety policies and the goal.

The team node itself (:class:`temper_ai.pi_agent.team_node.TeamNode`) runs the leader loop
(:mod:`temper_ai.pi_agent.team_leader`) on the team runtime (T4 messaging, T5 inboxes).
Registered only with the Pi switch (``TEMPER_PI_AGENT``) on.

This module imports nothing from ``temper_ai.stage``: the stage package imports the topology
module, which registers this strategy, so the node lives in ``team_node`` and is imported when
a team stage is built.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from temper_ai.pi_agent import AGENT_TYPE
from temper_ai.pi_agent.member import config_problems

STRATEGY = "team"
#: Said by the run-start check for ``communication: {type: edges}`` (R2 rule B7): the first
#: team runtime is ``all`` only. Drop it when a later slice builds edges.
EDGES_NOT_BUILT = "edges isn't built yet; use all"
#: The name of the one node a team stage holds (its path is ``<stage>.team``).
NODE_NAME = "team"
SECTIONS = ("mode", "communication", "pause_after_rounds")
#: Sections planned for later, each arriving with its runtime piece; refused until then.
LATER_SECTIONS = ("workspace", "lessons", "ask_owner", "conversation")


# --- section models ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LeaderMode:
    """``mode: {type: leader, leader: <member>}``: the leader gets the brief and says done."""

    leader: str
    type: str = "leader"


@dataclass(frozen=True)
class AllCommunication:
    """``communication: {type: all}``: any member may message any member."""

    type: str = "all"


@dataclass(frozen=True)
class EdgesCommunication:
    """``communication: {type: edges, edges: {member: [members]}}``: one-direction links."""

    edges: dict[str, tuple[str, ...]] = field(default_factory=dict)
    type: str = "edges"


@dataclass(frozen=True)
class TeamSettings:
    """A team stage's ``strategy_config``, parsed and checked."""

    mode: LeaderMode
    communication: AllCommunication | EdgesCommunication
    pause_after_rounds: int

    def as_dict(self) -> dict:
        comm: dict = {"type": self.communication.type}
        if isinstance(self.communication, EdgesCommunication):
            comm["edges"] = {k: list(v) for k, v in self.communication.edges.items()}
        return {"mode": {"type": self.mode.type, "leader": self.mode.leader},
                "communication": comm, "pause_after_rounds": self.pause_after_rounds}


Problem = tuple[str, str]  # (where, what): where is a section name or "member '<name>'"


def _options(section: str, raw: dict, type_name: str, allowed: tuple[str, ...]) -> list[Problem]:
    unknown = sorted(set(raw) - {"type", *allowed})
    return [(section, f"unknown key '{key}' for type {type_name} (known: "
                      f"{', '.join(('type', *allowed))})") for key in unknown]


def _parse_leader(raw: dict) -> tuple[LeaderMode | None, list[Problem]]:
    problems = _options("mode", raw, "leader", ("leader",))
    leader = raw.get("leader")
    if not isinstance(leader, str) or not leader:
        problems.append(("mode", "type leader needs 'leader: <member name>'"))
        return None, problems
    return LeaderMode(leader=leader), problems


def _parse_all(raw: dict) -> tuple[AllCommunication | None, list[Problem]]:
    return AllCommunication(), _options("communication", raw, "all", ())


def _parse_edges(raw: dict) -> tuple[EdgesCommunication | None, list[Problem]]:
    problems = _options("communication", raw, "edges", ("edges",))
    edges = raw.get("edges")
    if not isinstance(edges, dict) or not all(
            isinstance(k, str) and isinstance(v, list) and all(isinstance(t, str) for t in v)
            for k, v in edges.items()):
        problems.append(("communication", "type edges needs 'edges: {member: [members it can "
                                          "start a conversation with]}'"))
        return None, problems
    return EdgesCommunication(edges={k: tuple(v) for k, v in edges.items()}), problems


def _check_leader(mode: LeaderMode, members: list[str]) -> list[Problem]:
    if mode.leader not in members:
        return [("mode", f"leader '{mode.leader}' is not a member (members: "
                         f"{', '.join(dict.fromkeys(members))})")]
    return []


def _check_all(_comm: AllCommunication, _members: list[str], _leader: str | None) -> list[Problem]:
    return []


def _check_edges(comm: EdgesCommunication, members: list[str],
                 leader: str | None) -> list[Problem]:
    problems: list[Problem] = []
    known = set(members)
    for source, targets in comm.edges.items():
        if source not in known:
            problems.append(("communication", f"edges list '{source}', which is not a member"))
        for target in targets:
            if target not in known:
                problems.append(("communication", f"edges for '{source}' name '{target}', "
                                                  "which is not a member"))
    if leader in known:
        reached = {leader}
        todo = [leader]
        while todo:
            for target in comm.edges.get(todo.pop(), ()):
                if target in known and target not in reached:
                    reached.add(target)
                    todo.append(target)
        for name in members:
            if name not in reached:
                problems.append(("communication", f"'{name}' can't be reached from the leader "
                                                  f"'{leader}', directly or through others"))
    return problems


@dataclass(frozen=True)
class SectionType:
    parse: Callable[[dict], tuple[object | None, list[Problem]]]
    check: Callable[..., list[Problem]]


#: Each section's types: a parser for its options and its own check against the members.
MODE_TYPES: dict[str, SectionType] = {
    "leader": SectionType(_parse_leader, _check_leader),
}
COMMUNICATION_TYPES: dict[str, SectionType] = {
    "all": SectionType(_parse_all, _check_all),
    "edges": SectionType(_parse_edges, _check_edges),
}


def _section(name: str, raw: object, types: dict[str, SectionType]) -> tuple[object | None,
                                                                             list[Problem]]:
    if not isinstance(raw, dict):
        return None, [(name, f"must be a mapping with a 'type' (one of: {', '.join(types)})")]
    kind = raw.get("type")
    if kind not in types:
        what = f"unknown type '{kind}'" if kind is not None else "needs a 'type'"
        return None, [(name, f"{what} (available: {', '.join(types)})")]
    return types[kind].parse(raw)


def parse_settings(strategy_config: object) -> tuple[TeamSettings | None, list[Problem]]:
    """The stage's ``strategy_config`` as team settings, with every format problem."""
    if not isinstance(strategy_config, dict):
        return None, [("strategy_config", "must be a mapping of team sections ("
                                          f"{', '.join(SECTIONS)})")]
    problems: list[Problem] = []
    for key in strategy_config:
        if key in LATER_SECTIONS:
            problems.append((key, "this section is not available yet; it comes with its runtime "
                                  "piece"))
        elif key not in SECTIONS:
            problems.append((str(key), f"unknown section (known: {', '.join(SECTIONS)})"))
    mode = None
    if "mode" not in strategy_config:
        problems.append(("mode", "required: {type: leader, leader: <member name>}"))
    else:
        mode, got = _section("mode", strategy_config["mode"], MODE_TYPES)
        problems += got
    comm, got = _section("communication", strategy_config.get("communication", {"type": "all"}),
                         COMMUNICATION_TYPES)
    problems += got
    rounds = strategy_config.get("pause_after_rounds")
    if "pause_after_rounds" not in strategy_config:
        problems.append(("pause_after_rounds", "required, no default: how many rounds before "
                                               "the team pauses for the owner"))
        rounds = None
    elif isinstance(rounds, bool) or not isinstance(rounds, int) or rounds < 1:
        problems.append(("pause_after_rounds", "must be a whole number of rounds, 1 or more"))
        rounds = None
    if mode is None or comm is None or rounds is None or problems:
        return None, problems
    assert isinstance(mode, LeaderMode)  # noqa: B101 - the only mode type
    assert isinstance(comm, (AllCommunication, EdgesCommunication))  # noqa: B101
    return TeamSettings(mode=mode, communication=comm, pause_after_rounds=rounds), []


def member_name(cfg: dict) -> str:
    return str(cfg.get("name") or "unnamed")


def stage_problems(agent_configs: list[dict], strategy_config: object) -> list[Problem]:
    """Every problem a team stage shows on its own: its members' configs and its sections.
    (The run-start check adds roles, safety policies and the goal.)"""
    problems: list[Problem] = []
    if not agent_configs:
        problems.append(("agents", "a team needs at least one member"))
    names = [member_name(c) for c in agent_configs]
    for name in sorted({n for n in names if names.count(n) > 1}):
        problems.append(("agents", f"the member name '{name}' is used more than once; give "
                                    "each member its own name:"))
    for cfg in agent_configs:
        where = f"member '{member_name(cfg)}'"
        kind = cfg.get("type", "llm")
        if kind != AGENT_TYPE:
            problems.append((where, f"is a '{kind}' agent; team members are type: pi agents "
                                    "pointing at a pi role"))
            continue
        problems += [(where, text) for text in config_problems(cfg)]
    problems += parse_settings(strategy_config)[1]
    # Each section type's own check, run when the section itself parsed.
    raw = strategy_config if isinstance(strategy_config, dict) else {}
    mode, _ = _section("mode", raw.get("mode"), MODE_TYPES) if "mode" in raw else (None, [])
    leader = None
    if isinstance(mode, LeaderMode):
        leader = mode.leader
        problems += MODE_TYPES["leader"].check(mode, names)
    comm_raw = raw.get("communication", {"type": "all"})
    comm, _ = _section("communication", comm_raw, COMMUNICATION_TYPES)
    if isinstance(comm, (AllCommunication, EdgesCommunication)):
        problems += COMMUNICATION_TYPES[comm.type].check(comm, names, leader)
    return problems


def validate_team(agent_configs: list[dict], strategy_config: dict) -> list[str]:
    """The team strategy's check (topology ``_VALIDATORS``): every stage-local problem."""
    return [f"{where}: {what}" for where, what in stage_problems(agent_configs, strategy_config)]


def team_topology(agent_configs: list[dict], strategy_config: dict) -> list:
    """The team strategy's generator (topology ``_GENERATORS``): one ``TeamNode``."""
    from temper_ai.pi_agent.team_node import TeamNode
    from temper_ai.stage.models import NodeConfig

    settings, problems = parse_settings(strategy_config)
    if settings is None:  # build_topology runs validate_team first; never reached through it
        raise ValueError("; ".join(f"{w}: {p}" for w, p in problems))
    return [TeamNode(NodeConfig(name=NODE_NAME, type=STRATEGY), agent_configs, settings)]
