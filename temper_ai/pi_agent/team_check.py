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
  the leader, ``pause_after_rounds`` set) and its goal; ``communication: edges`` is refused for
  now (R2 rule B7: the first team runtime is ``all`` only);
* the workflow: every ``safety: policies:`` entry, since a team can't enforce one yet.

The role list is the worker box config's ``identities_dir`` (``TEMPER_PI_BOX_CONFIG``), the same
folder a Pi step copies its role from; the check only reads it. Unset means "role list not
configured". Only imported with the Pi switch (``TEMPER_PI_AGENT``) on.
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
from temper_ai.pi_agent.team import EDGES_NOT_BUILT, member_name, stage_problems

if TYPE_CHECKING:  # the stage package imports this module's registration; no import cycle
    from temper_ai.stage.topology import RunStart

#: The role's about page, which the identity extension shows as the role's description.
ABOUT_PAGE = "about.md"
#: Workflow safety policy types a team can enforce. None yet: a team's members act inside their
#: own worker boxes, where Temper's tool-call policies don't reach.
TEAM_ENFORCED_POLICIES: frozenset[str] = frozenset()


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
            close = difflib.get_close_matches(role, self.ids(), n=1, cutoff=0.6)
            hint = f" (did you mean '{close[0]}'? Not picked automatically)" if close else ""
            return [f"role '{role}' is not in the role list{hint}"]
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


def load_box() -> tuple[BoxConfig | None, str | None]:
    """The worker box config (it names the role list), or why there is none."""
    try:
        return BoxConfig.load(), None
    except BoxError as exc:
        if exc.code == "box_not_configured":
            return None, f"role list not configured (set {CONFIG_ENV} to the worker box config)"
        return None, str(exc)


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
               box: BoxConfig | None = None, box_problem: str | None = None) -> list[str]:
    """Every problem with a team stage, as ``"<where>: <what>"`` texts, in a stable order.

    ``agent_configs`` are the members' resolved agent configs; ``unloaded`` maps a member whose
    config could not be loaded to the loader's error. ``box`` is the worker box config (loaded
    from ``TEMPER_PI_BOX_CONFIG`` when neither it nor ``box_problem`` is given). Reads the role
    folders, never writes; no model call, no container.
    """
    if box is None and box_problem is None:
        box, box_problem = load_box()
    problems = [f"member '{name}': its agent config can't be loaded: {error}"
                for name, error in (unloaded or {}).items()]
    problems += [f"{where}: {what}" for where, what in stage_problems(agent_configs,
                                                                     strategy_config)]
    problems += member_problems(agent_configs)
    if _uses_edges(strategy_config):
        # R2 rule B7: edges stay in the format and are checked above, but the first team
        # runtime is ``all`` only, so a run can't use them yet.
        problems.append(f"communication: {EDGES_NOT_BUILT}")
    if box is None:
        problems.append(f"roles: {box_problem}")
    else:
        roles = RoleList(Path(box.identities_dir))
        for cfg in agent_configs:
            role = cfg.get("role")
            if cfg.get("type") != AGENT_TYPE or not isinstance(role, str):
                continue  # already reported with the member's config
            where = f"member '{member_name(cfg)}'"
            problems += [f"{where}: {text}" for text in roles.problems(role)]
            provider = settings(cfg)["provider"]
            if provider not in box.routes:
                problems.append(f"{where}: no worker route for provider '{provider}' in the "
                                "worker box config")
            listed = cfg.get("add_ons")
            if listed is None or (isinstance(listed, list)
                                  and all(isinstance(a, str) for a in listed)):
                unpinned = [a for a in add_on_names(cfg)
                            if a in ADD_ONS and a not in box.add_ons]
                if unpinned:
                    problems.append(f"{where}: no pinned copy of add-on(s) "
                                    f"{', '.join(unpinned)} in the worker box config")
            if not tool_problems(cfg.get("tools")) and not add_on_problems(cfg.get("add_ons")):
                # (a bad tools or add-ons list is already reported with the member's config)
                problems += [f"{where}: {text}"
                             for text in search_tool_problems(launched_tools(cfg), box)]
    goal = goal_problem(input_map, inputs or {})
    if goal:
        problems.append(goal)
    problems += safety_problems(safety)
    return problems


def member_problems(agent_configs: list[dict]) -> list[str]:
    """Members the first team runtime can't tell apart or reach: two members with the same
    role (M2 binding B8, until the owner decides about the same role twice), and a member
    named like one of Temper's own ids (T4T5 N3: a member called ``owner`` could not be
    reached under the ``all`` policy). The team's own open refuses those names too."""
    out: list[str] = []
    first_with: dict[str, str] = {}
    seen: set[str] = set()
    for cfg in agent_configs:
        name = member_name(cfg)
        if name in seen:
            continue  # the same member listed twice: reported once, as a repeated name
        seen.add(name)
        if name.strip().lower() in RESERVED_IDS:
            out.append(f"member '{name}': the name is reserved for Temper's own use; pick "
                       "another")
        role = cfg.get("role")
        if not isinstance(role, str) or not role.strip():
            continue  # already reported with the member's config
        key = role.strip().casefold()
        if key in first_with:
            out.append(f"member '{name}': same role '{role}' as member '{first_with[key]}'; "
                       "a team has one member per role")
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
