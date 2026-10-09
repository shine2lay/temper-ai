"""The team strategy (``strategy: team``): a stage whose Pi members work as one team node.

A team is a stage with ``strategy: team`` (owner m02451, m02454), a fourth strategy beside
parallel, sequential and leader. Its members are the stage's ``agents:`` list: each one a
``type: pi`` agent config pointing at an existing pi role, known in the team by its ``name:``.
How the team runs is the stage's ``strategy_config``, in sections, each with a ``type`` plus that
type's options (build plan, "Team settings format"):

    strategy_config:
      mode:          {type: leader, leader: design}     # who gets the goal and says done
      communication: {type: all}                        # or {type: edges, edges: {...}}
      pause_every_usd: 100                              # check-in every $100 spent (default)
      max_parallel: 3                                   # members at once (default: all)

* ``mode``: required; first type ``leader`` (``leader:`` names a member).
* ``communication``: ``all`` (any member may message any member; the default when the section
  is left out) or ``edges`` (each member lists the members it may start a conversation with,
  one direction, e.g. ``{design: [frontend, qa], frontend: [qa]}``). Every member must be
  reachable from the leader. The first team runtime is ``all`` only (R2 rule B7): ``edges`` is
  parsed and checked here, and the run-start check refuses it with ``EDGES_NOT_BUILT`` until
  the later slice builds it.
* ``pause_every_usd``: each time the Project spends this much since its start or the owner's
  last continue / guide, no new turn starts, running turns finish, and the owner is asked
  continue / guide / stop (FLOW F6, R4). Default 100.
* ``max_parallel``: how many members may run a turn at the same moment (FLOW E1). Default:
  every member.

The team is free-flowing: only the leader gets the goal and starts; the other members wait
for its first message. Once woken, members work in parallel and stay on until they call
``idle``. No rounds are run. A non-null ``pause_after_rounds`` is refused by name; null is
ignored so the old page's empty form works across a deploy.

Each section type brings its own parser and check (``MODE_TYPES``, ``COMMUNICATION_TYPES``),
so a new type adds its options without touching the others. Unknown sections, types and keys
are refused by name. The later slice's features (R2: each needs its own proof before use) are
known by the names a config would use for them and refused with a plain sentence (M4 SW-04):
``mode: {type: unanimous}``, ``conversation: {type: fresh_each_round}``,
``conversation: {continue_from: ...}`` (two team stages continuing) and ``private_children``,
besides ``edges`` above. Concurrency is built: use ``max_parallel``. A change to the team's members while its run is
going is refused when the team reopens (``team settings changed``, R2 C3); any other change to
the team's settings or a member's is asked about at a settings wait (SW-85,
:mod:`temper_ai.pi_agent.settings_wait`). The strategy's
check (:func:`validate_team`) reports every problem at once; the run-start check
(:mod:`temper_ai.pi_agent.team_check`) adds the members' roles, the workflow's safety policies
and the goal.

The team node itself (:class:`temper_ai.pi_agent.team_node.TeamNode`) runs the free-flowing
loop (:mod:`temper_ai.pi_agent.team_flow`) on the team runtime (T4 messaging, T5 inboxes).
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
SECTIONS = ("mode", "communication", "pause_every_usd", "max_parallel")
#: The check-in's default and its bounds (US dollars).
PAUSE_EVERY_USD = 100.0
PAUSE_EVERY_MIN = 1.0
PAUSE_EVERY_MAX = 10000.0
#: Said when a team that ran in review rounds is resumed, forked or re-run (FLOW E4).
ROUNDS_TEAM = ("this team ran in review rounds, which Temper no longer runs; start a new "
               "Project")
#: Said for the old review rounds' setting, ``pause_after_rounds``, given a value in a config
#: or a New Project form (FLOW R4).
ROUNDS_GONE = ("pause_after_rounds is gone: teams work free-flowing now; set pause_every_usd "
               "(default 100)")
#: Sections planned for later, each arriving with its runtime piece; refused until then.
LATER_SECTIONS = ("workspace", "lessons", "ask_owner", "conversation")

# The later slice (R2 not_approved and l3_scope.must_list_as_not_built; M4 SW-04): each feature
# needs its own proof before use, so asking for one is refused with what it is and what the
# team does instead. Drop a sentence when its slice builds the feature.
#: ``mode: {type: unanimous}``.
UNANIMOUS_NOT_BUILT = "unanimous mode isn't built yet; use leader"
#: ``conversation: {type: fresh_each_round}``, for the team or one member.
FRESH_NOT_BUILT = ("fresh_each_round isn't built yet: members keep their conversation for the "
                   "whole team stage")
#: ``conversation: {continue_from: <earlier stage>}``: two team stages continuing.
CONTINUE_NOT_BUILT = ("continuing members' conversations from an earlier team stage "
                      "(continue_from) isn't built yet: each team stage starts its members' "
                      "conversations fresh")
#: ``private_children``: a member's own private helpers (the frozen plan's private child).
CHILDREN_NOT_BUILT = ("private children aren't built yet: a team is the members it lists, and "
                      "none of them can start a private helper")
#: Later-slice sections, by the names a config would use (a synonym says the same).
LATER_SLICE_SECTIONS = {
    "private_children": CHILDREN_NOT_BUILT,
    "children": CHILDREN_NOT_BUILT,
    "pause_after_rounds": ROUNDS_GONE,
}
#: Later-slice types of a section that exists.
LATER_SLICE_TYPES = {"mode": {"unanimous": UNANIMOUS_NOT_BUILT}}
#: Keys in a member's own agent config that ask for a later-slice feature for that member
#: (``conversation`` is read by :func:`_later_conversation`).
LATER_SLICE_MEMBER_KEYS = {
    "continue_from": CONTINUE_NOT_BUILT,
    "private_children": CHILDREN_NOT_BUILT,
    "children": CHILDREN_NOT_BUILT,
}


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
    pause_every_usd: float = PAUSE_EVERY_USD
    #: None: every member may run at once.
    max_parallel: int | None = None

    def as_dict(self) -> dict:
        comm: dict = {"type": self.communication.type}
        if isinstance(self.communication, EdgesCommunication):
            comm["edges"] = {k: list(v) for k, v in self.communication.edges.items()}
        return {"mode": {"type": self.mode.type, "leader": self.mode.leader},
                "communication": comm, "pause_every_usd": self.pause_every_usd,
                "max_parallel": self.max_parallel}


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
    later = LATER_SLICE_TYPES.get(name, {})
    if isinstance(kind, str) and kind in later:
        return None, [(name, later[kind])]
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
        if key == "pause_after_rounds" and strategy_config[key] is None:
            continue  # today's dashboard form sends it empty: accepted and ignored (old+new live)
        if key in LATER_SLICE_SECTIONS:
            problems.append((key, LATER_SLICE_SECTIONS[key]))
        elif key == "conversation" and _later_conversation(strategy_config[key]):
            problems += [(key, text) for text in _later_conversation(strategy_config[key])]
        elif key in LATER_SECTIONS:
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
    every = strategy_config.get("pause_every_usd", PAUSE_EVERY_USD)
    if (isinstance(every, bool) or not isinstance(every, (int, float))
            or not PAUSE_EVERY_MIN <= every <= PAUSE_EVERY_MAX):
        problems.append(("pause_every_usd", f"must be a number of US dollars from "
                                            f"{PAUSE_EVERY_MIN:g} to {PAUSE_EVERY_MAX:g}"))
    most = strategy_config.get("max_parallel")
    if most is not None and (isinstance(most, bool) or not isinstance(most, int) or most < 1):
        problems.append(("max_parallel", "must be a whole number of members, 1 or more (leave "
                                         "it out for every member)"))
    if mode is None or comm is None or problems:
        return None, problems
    assert isinstance(mode, LeaderMode)  # noqa: B101 - the only mode type
    assert isinstance(comm, (AllCommunication, EdgesCommunication))  # noqa: B101
    return TeamSettings(mode=mode, communication=comm, pause_every_usd=float(every),
                        max_parallel=most), []


def _later_conversation(raw: object) -> list[str]:
    """The later-slice sentences a ``conversation`` section asks for (SW-04): fresh_each_round
    and continue_from. Empty for anything else, which the section's own refusal covers."""
    if isinstance(raw, str):
        raw = {"type": raw}
    if not isinstance(raw, dict):
        return []
    out = []
    if raw.get("type") == "fresh_each_round" or "fresh_each_round" in raw:
        out.append(FRESH_NOT_BUILT)
    if "continue_from" in raw or raw.get("type") == "continue_from":
        out.append(CONTINUE_NOT_BUILT)
    return out


def _later_member(cfg: dict) -> list[str]:
    """A member's own later-slice settings (SW-04), each refused as ``<key>: <sentence>``."""
    out = []
    if "conversation" in cfg:
        out += [f"conversation: {text}" for text in _later_conversation(cfg["conversation"])
                or ["this setting is not available yet; it comes with its runtime piece"]]
    out += [f"{key}: {text}" for key, text in LATER_SLICE_MEMBER_KEYS.items() if key in cfg]
    return out


def member_name(cfg: dict) -> str:
    return str(cfg.get("name") or "unnamed")


#: A problem with the member it belongs to: (where, what, member). ``member`` is the member's
#: name when the problem is one member's, else None (M3 E20: the Team page marks that row).
MemberProblem = tuple[str, str, str | None]


def stage_findings(agent_configs: list[dict], strategy_config: object) -> list[MemberProblem]:
    """Every problem a team stage shows on its own: its members' configs and its sections,
    each with its member -- taken from where the problem is found, never read back out of
    its text. (The run-start check adds roles, safety policies and the goal.)"""
    problems: list[MemberProblem] = []
    if not agent_configs:
        problems.append(("agents", "a team needs at least one member", None))
    names = [member_name(c) for c in agent_configs]
    for name in sorted({n for n in names if names.count(n) > 1}):
        problems.append(("agents", f"the member name '{name}' is used more than once; give "
                                    "each member its own name:", name))
    for cfg in agent_configs:
        name = member_name(cfg)
        where = f"member '{name}'"
        kind = cfg.get("type", "llm")
        if kind != AGENT_TYPE:
            problems.append((where, f"is a '{kind}' agent; team members are type: pi agents "
                                    "pointing at a pi role", name))
            continue
        problems += [(where, text, name) for text in config_problems(cfg)]
        problems += [(where, text, name) for text in _later_member(cfg)]
    problems += [(where, what, None) for where, what in parse_settings(strategy_config)[1]]
    # Each section type's own check, run when the section itself parsed.
    raw = strategy_config if isinstance(strategy_config, dict) else {}
    most = raw.get("max_parallel")
    if isinstance(most, int) and not isinstance(most, bool) and most > len(agent_configs) >= 1:
        problems.append(("max_parallel", f"is {most}, more than the team's "
                                         f"{len(agent_configs)} member(s)", None))
    mode, _ = _section("mode", raw.get("mode"), MODE_TYPES) if "mode" in raw else (None, [])
    leader = None
    if isinstance(mode, LeaderMode):
        leader = mode.leader
        problems += [(w, t, None) for w, t in MODE_TYPES["leader"].check(mode, names)]
    comm_raw = raw.get("communication", {"type": "all"})
    comm, _ = _section("communication", comm_raw, COMMUNICATION_TYPES)
    if isinstance(comm, (AllCommunication, EdgesCommunication)):
        problems += [(w, t, None)
                     for w, t in COMMUNICATION_TYPES[comm.type].check(comm, names, leader)]
    return problems


def stage_problems(agent_configs: list[dict], strategy_config: object) -> list[Problem]:
    """Every problem a team stage shows on its own, as (where, what)."""
    return [(where, what) for where, what, _member in stage_findings(agent_configs,
                                                                     strategy_config)]


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
