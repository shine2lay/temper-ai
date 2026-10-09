"""The team's pre-run check: everything about a ``strategy: team`` stage that can be checked
before the run starts, with no model call and no container (owner, build plan "M2 decisions so
far").

:func:`check_team` is the one function; the loader calls it through :func:`run_start_check`
when a run starts, before any node (``GraphLoader.load_workflow(..., run_start=True)``), and a
Team page can call it as it is. It reports every problem at once; any problem means the run does
not start. It checks:

* each member: its agent config loads and is a valid ``type: pi`` config (Temper tool names,
  allowed add-ons, model settings); its role exists in the role list under that exact id (a
  close name may be suggested, never picked); the role's ``identity.json`` and about page are
  readable; ``identity.json`` names a home chat; its add-ons have pinned copies, its provider
  has a worker route, and the search binary its Pi grep or find runs (rg, fd) is pinned in the
  worker box config;
* the team: its sections (leader is a member, edges name members, every member reachable from
  the leader, ``pause_every_usd`` and ``max_parallel`` valid) and its goal; ``communication: edges`` is refused for
  now (R2 rule B7: the first team runtime is ``all`` only);
* the workflow: every ``safety: policies:`` entry, since a team can't enforce one yet.

The role list is the worker box config's ``identities_dir`` (``TEMPER_PI_BOX_CONFIG``), the same
folder a Pi step copies its role from; the check only reads it. Unset means "role list not
configured". Only imported with the Pi switch (``TEMPER_PI_AGENT``) on.

Where the check reads it (ADR-M4-21, :func:`load_box_or_lane_view`): in the Pi lane, from the
disk, as always; anywhere else (the server, which is the run boxes' template and holds no Pi
folder), only from the Pi lane view pi-worker publishes (shared/pi_lane_view.py), never the
disk. The view is advisory: the Pi lane checks again on disk at run start and at the team node's
start (:func:`load_box`), with the same words.
"""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from temper_ai.pi_agent import AGENT_TYPE
from temper_ai.pi_agent.box import CONFIG_ENV, ROLE_RE, BoxConfig, BoxError
from temper_ai.pi_agent.member import (
    ADD_ONS,
    add_on_names,
    add_on_problems,
    launched_tools,
    settings,
    tool_problems,
)
from temper_ai.pi_agent.route.model import RESERVED_IDS
from temper_ai.pi_agent.search_tools import search_tool_problems
from temper_ai.pi_agent.team import EDGES_NOT_BUILT, member_name, stage_findings
from temper_ai.pi_agent.team_config import NAME_RE

if TYPE_CHECKING:  # the stage package imports this module's registration; no import cycle
    from collections.abc import Iterable

    from temper_ai.stage.topology import RunStart

#: The role's about page, which the identity extension shows as the role's description.
ABOUT_PAGE = "about.md"
#: Workflow safety policy types a team can enforce. None yet: a team's members act inside their
#: own worker boxes, where Temper's tool-call policies don't reach.
TEAM_ENFORCED_POLICIES: frozenset[str] = frozenset()
#: Why a member can't have Bash yet (M3 E11, SW-61): a Bash member can reach the API from its
#: box, so it waits until only the owner's key can approve, cancel or resume (#45 enforce).
BASH_OFF = "Bash is off until owner-only writes are enforced (#45)"
#: A member's name rule in words (M3 E6, ``team_config.NAME_PATTERN``).
NAME_RULE = ("a name starts with a lowercase letter and has only lowercase letters, digits, "
             "'-' and '_' (40 at most)")
#: The Team page's form field each team section's problems belong to (M3 E20). A member's
#: problems belong to ``members``; a section with no form field gets none.
SECTION_FIELDS = {"agents": "members", "mode": "leader", "communication": "communication",
                  "pause_after_rounds": "pause_after_rounds",
                  "pause_every_usd": "pause_every_usd", "max_parallel": "max_parallel",
                  "goal": "goal",
                  "project": "project_path"}


@dataclass(frozen=True)
class Finding:
    """One problem (or note) and where the Team page shows it (M3 E20). ``text`` is the
    engine's sentence word for word, ``"<where>: <what>"``, the same words chat and the run
    page show; ``field`` is the form field it belongs to (None when no field fits) and
    ``member`` the member row's team name when it is one member's. Both come from where the
    problem is found, never from its text."""

    text: str
    field: str | None = None
    member: str | None = None

    def as_dict(self) -> dict:
        out: dict = {"field": self.field, "text": self.text}
        if self.member is not None:
            out["member"] = self.member
        return out


def finding(where: str, what: str, member: str | None = None) -> Finding:
    """A ``"<where>: <what>"`` problem with its field: ``members`` for a member's, else the
    section's own field."""
    field = "members" if member is not None else SECTION_FIELDS.get(where)
    return Finding(f"{where}: {what}", field, member)


def not_listed(role: str, ids: Iterable[str]) -> str:
    """The words for a role that isn't in the role list, with a close id as a hint (never
    picked): the same from the disk (:class:`RoleList`) and from the Pi lane view
    (:class:`ViewRoles`)."""
    close = difflib.get_close_matches(role, list(ids), n=1, cutoff=0.6)
    hint = f" (did you mean '{close[0]}'? Not picked automatically)" if close else ""
    return f"role '{role}' is not in the role list{hint}"


@dataclass(frozen=True)
class RoleList:
    """The folder of pi roles, read only: one folder per role id."""

    root: Path

    def ids(self) -> list[str]:
        try:
            return sorted(p.name for p in self.root.iterdir() if p.is_dir())
        except OSError:
            return []

    def problems(self, role: str) -> list[str]:
        """What keeps ``role`` from being used as it is (empty when it can be)."""
        folder = self.root / role
        if not ROLE_RE.match(role) or not folder.is_dir():
            return [not_listed(role, self.ids())]
        problems = []
        try:
            identity = json.loads((folder / "identity.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            identity = None
            problems.append(f"role '{role}': identity.json is missing or unreadable")
        if identity is not None and not isinstance(identity, dict):
            identity = None
            problems.append(f"role '{role}': identity.json is not an object")
        try:
            (folder / ABOUT_PAGE).read_text(encoding="utf-8")
        except OSError:
            problems.append(f"role '{role}': its about page ({ABOUT_PAGE}) is missing or "
                            "unreadable")
        if identity is not None:
            home = identity.get("homeChat")
            if not isinstance(home, str) or not home.strip():
                problems.append(f"role '{role}': identity.json has no home chat")
        return problems

    def card(self, role: str) -> dict:
        """What the Team page shows of a role: its id, title, about page and whether it has a
        home chat, with its problems. Nothing else of the role's folder (no chat ids, no
        paths) leaves the server."""
        folder = self.root / role
        try:
            identity = json.loads((folder / "identity.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            identity = None
        identity = identity if isinstance(identity, dict) else {}
        try:
            about = (folder / ABOUT_PAGE).read_text(encoding="utf-8")
        except OSError:
            about = None
        home = identity.get("homeChat")
        title = identity.get("title")
        return {"id": role, "title": title if isinstance(title, str) and title.strip() else role,
                "about": about, "has_home_chat": isinstance(home, str) and bool(home.strip()),
                "problems": self.problems(role)}


class ViewRoles:
    """The role list as the Pi lane view carries it (shared/pi_lane_view.py): the ids and
    each role's card, read on disk by pi-worker. Answers like :class:`RoleList`, word for
    word: a role in the list has the problems its card has, any other gets
    :func:`not_listed` over the same ids."""

    def __init__(self, ids: list[str], cards: list[dict]):
        self._ids = list(ids)
        self._cards = {card["id"]: dict(card) for card in cards}

    def ids(self) -> list[str]:
        return list(self._ids)

    def problems(self, role: str) -> list[str]:
        card = self._cards.get(role)
        if card is None:
            return [not_listed(role, self._ids)]
        return list(card["problems"])

    def card(self, role: str) -> dict:
        card = self._cards.get(role)
        if card is None:
            return {"id": role, "title": role, "about": None, "has_home_chat": False,
                    "problems": self.problems(role)}
        return {**card, "problems": list(card["problems"])}


@dataclass(frozen=True)
class LaneView:
    """What the checks read of the worker box config, from the Pi lane view instead of the
    disk (ADR-M4-21): the role list and the route, add-on and search-tool names. Only outside
    the Pi lane (:func:`load_box_or_lane_view`)."""

    roles: ViewRoles
    routes: frozenset[str]
    add_ons: frozenset[str]
    search_tools: frozenset[str]
    box_config_sha256: str
    published_at: str

    @classmethod
    def of(cls, view: dict) -> LaneView:
        """A view :func:`temper_ai.shared.pi_lane_view.parse` accepted."""
        return cls(roles=ViewRoles(view["role_ids"], view["roles"]),
                   routes=frozenset(view["routes"]), add_ons=frozenset(view["add_ons"]),
                   search_tools=frozenset(view["search_tools"]),
                   box_config_sha256=view["box_config_sha256"],
                   published_at=view["published_at"])


def role_list(box: BoxConfig | LaneView) -> RoleList | ViewRoles:
    """The role list ``box`` names: its folder on disk, or the one the Pi lane view carries."""
    if isinstance(box, LaneView):
        return box.roles
    return RoleList(Path(box.identities_dir))


def load_box() -> tuple[BoxConfig | None, str | None]:
    """The worker box config from the disk (it names the role list), or why there is none.
    The Pi lane's own reader: its run-start, node-start and claim checks."""
    try:
        return BoxConfig.load(), None
    except BoxError as exc:
        if exc.code == "box_not_configured":
            return None, f"role list not configured (set {CONFIG_ENV} to the worker box config)"
        return None, str(exc)


def load_box_or_lane_view() -> tuple[BoxConfig | LaneView | None, str | None]:
    """What the team checks read, by where they run (ADR-M4-21): in the Pi lane the box config
    from the disk (:func:`load_box`), never the view; anywhere else only the Pi lane view from
    Redis (shared/pi_lane_view.py), never the disk, and no usable view is a roles problem in
    plain words."""
    from temper_ai.runner.lanes import in_pi_lane

    if in_pi_lane():
        return load_box()
    from temper_ai.shared import pi_lane_view

    view, problem = pi_lane_view.read()
    if view is None:
        return None, problem
    return LaneView.of(view), None


def goal_problem(input_map: dict | None, inputs: dict) -> str | None:
    """The team's goal must be set: mapped in the stage's ``input_map`` or given as the run's
    ``goal`` input. A goal mapped from an earlier node's output can only be checked when the
    team node starts."""
    def missing(value: object) -> bool:
        return value is None or (isinstance(value, str) and not value.strip())

    if input_map and "goal" in input_map:
        head, _, field = str(input_map["goal"]).partition(".")
        if head in ("input", "workflow") and missing(inputs.get(field)):
            return f"goal: the stage reads it from the run input '{field}', which is not set"
        return None
    if input_map:
        return "goal: required: map it in the stage's input_map (goal: <source>)"
    if missing(inputs.get("goal")):
        return ("goal: required: give the run a 'goal' input or map it in the stage's "
                "input_map")
    return None


def safety_problems(safety: dict | None) -> list[str]:
    """Each workflow safety policy a team can't enforce yet, by name; never skipped."""
    policies = (safety or {}).get("policies") or []
    problems = []
    for i, policy in enumerate(policies):
        kind = policy.get("type") if isinstance(policy, dict) else None
        if kind in TEAM_ENFORCED_POLICIES:
            continue
        name = (policy.get("name") if isinstance(policy, dict) else None) or kind or f"#{i + 1}"
        problems.append(f"safety: policy '{name}' ({kind or 'no type'}) can't be enforced in a "
                        "team yet; take it out of the workflow or run without a team stage")
    return problems


def check_team(agent_configs: list[dict], strategy_config: object, *,
               input_map: dict | None = None, inputs: dict | None = None,
               safety: dict | None = None, unloaded: dict[str, str] | None = None,
               box: BoxConfig | LaneView | None = None,
               box_problem: str | None = None) -> list[str]:
    """Every problem with a team stage, as ``"<where>: <what>"`` texts, in a stable order
    (:func:`team_findings`' texts)."""
    return [f.text for f in team_findings(
        agent_configs, strategy_config, input_map=input_map, inputs=inputs, safety=safety,
        unloaded=unloaded, box=box, box_problem=box_problem)]


def team_findings(agent_configs: list[dict], strategy_config: object, *,
                  input_map: dict | None = None, inputs: dict | None = None,
                  safety: dict | None = None, unloaded: dict[str, str] | None = None,
                  box: BoxConfig | LaneView | None = None,
                  box_problem: str | None = None) -> list[Finding]:
    """Every problem with a team stage, each with its form field and member, in a stable
    order.

    ``agent_configs`` are the members' resolved agent configs; ``unloaded`` maps a member whose
    config could not be loaded to the loader's error. ``box`` is the worker box config or the
    Pi lane view (:func:`load_box_or_lane_view` when neither it nor ``box_problem`` is given).
    Reads the role folders or the view, never writes; no model call, no container.
    """
    if box is None and box_problem is None:
        box, box_problem = load_box_or_lane_view()
    problems = [finding(f"member '{name}'", f"its agent config can't be loaded: {error}", name)
                for name, error in (unloaded or {}).items()]
    problems += [finding(where, what, member)
                 for where, what, member in stage_findings(agent_configs, strategy_config)]
    problems += member_findings(agent_configs)
    if _uses_edges(strategy_config):
        # R2 rule B7: edges stay in the format and are checked above, but the first team
        # runtime is ``all`` only, so a run can't use them yet.
        problems.append(finding("communication", EDGES_NOT_BUILT))
    if box is None:
        problems.append(finding("roles", str(box_problem)))
    else:
        roles = role_list(box)
        for cfg in agent_configs:
            role = cfg.get("role")
            if cfg.get("type") != AGENT_TYPE or not isinstance(role, str):
                continue  # already reported with the member's config
            name = member_name(cfg)
            where = f"member '{name}'"
            problems += [finding(where, text, name) for text in roles.problems(role)]
            provider = settings(cfg)["provider"]
            if provider not in box.routes:
                problems.append(finding(where, f"no worker route for provider '{provider}' in "
                                               "the worker box config", name))
            listed = cfg.get("add_ons")
            if listed is None or (isinstance(listed, list)
                                  and all(isinstance(a, str) for a in listed)):
                unpinned = [a for a in add_on_names(cfg)
                            if a in ADD_ONS and a not in box.add_ons]
                if unpinned:
                    problems.append(finding(where, f"no pinned copy of add-on(s) "
                                                   f"{', '.join(unpinned)} in the worker box "
                                                   "config", name))
            if not tool_problems(cfg.get("tools")) and not add_on_problems(cfg.get("add_ons")):
                # (a bad tools or add-ons list is already reported with the member's config)
                problems += [finding(where, text, name)
                             for text in search_tool_problems(launched_tools(cfg), box)]
    goal = goal_problem(input_map, inputs or {})
    if goal:
        problems.append(Finding(goal, "goal"))
    problems += [Finding(text) for text in safety_problems(safety)]
    return problems


def bash_allowed() -> bool:
    """Whether a member may have Bash: only once the API guard enforces owner-only writes
    (M3 E11; ``TEMPER_API_GUARD``, #45)."""
    from temper_ai.api.caller import guard_mode

    return guard_mode() == "enforce"


def member_problems(agent_configs: list[dict]) -> list[str]:
    """Members the first team runtime can't tell apart, reach or allow, as texts
    (:func:`member_findings`)."""
    return [f.text for f in member_findings(agent_configs)]


def member_findings(agent_configs: list[dict]) -> list[Finding]:
    """Members the first team runtime can't tell apart, reach or allow: a name outside the
    name rule (M3 E6: a name reaches a git folder and message routing), a member named like
    one of Temper's own ids (T4T5 N3: a member called ``owner`` could not be reached under the
    ``all`` policy; the team's own open refuses those names too), two members with the same
    role (M2 binding B8, until the owner decides about the same role twice), and Bash before
    the API guard enforces owner-only writes (M3 E11)."""
    out: list[Finding] = []
    first_with: dict[str, str] = {}
    seen: set[str] = set()
    bash = None
    for cfg in agent_configs:
        name = member_name(cfg)
        if name in seen:
            continue  # the same member listed twice: reported once, as a repeated name
        seen.add(name)
        where = f"member '{name}'"
        # A reserved id in any case says so first: "OWNER" is refused for being Temper's own id,
        # which is the more useful sentence than the character rule it also breaks.
        if name.strip().lower() in RESERVED_IDS:
            out.append(finding(where, "the name is reserved for Temper's own use; pick "
                                      "another", name))
        elif not NAME_RE.match(name):
            out.append(finding(where, NAME_RULE, name))
        tools = cfg.get("tools")
        if isinstance(tools, list) and "Bash" in tools:
            bash = bash_allowed() if bash is None else bash
            if not bash:
                out.append(finding(where, BASH_OFF, name))
        role = cfg.get("role")
        if not isinstance(role, str) or not role.strip():
            continue  # already reported with the member's config
        key = role.strip().casefold()
        if key in first_with:
            out.append(finding(where, f"same role '{role}' as member '{first_with[key]}'; a "
                                      "team has one member per role", name))
        else:
            first_with[key] = name
    return out


def _uses_edges(strategy_config: object) -> bool:
    section = strategy_config.get("communication") if isinstance(strategy_config, dict) else None
    return isinstance(section, dict) and section.get("type") == "edges"


def run_start_check(start: RunStart) -> list[str]:
    """The team strategy's run-start check (topology ``register_topology(...,
    run_start_check=...)``)."""
    return check_team(start.agent_configs, start.stage.strategy_config,
                      input_map=start.stage.input_map, inputs=start.inputs,
                      safety=start.workflow.safety, unloaded=start.unloaded)
