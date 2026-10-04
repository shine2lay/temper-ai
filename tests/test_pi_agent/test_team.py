"""The team strategy (``strategy: team``) and its pre-run check, with the Pi switch on.

A team is one stage: its members are the stage's ``agents:`` (``type: pi`` configs pointing at
existing pi roles) and its ``strategy_config`` has sections, each a ``type`` plus that type's
options. The pre-run check runs when a run starts, before any node, with no model call and no
container; it reports every problem at once and a refused team never becomes a run. The team
node itself fails red until the team runtime (T4/T5/M1) is built.
Sealed: role folders are fixtures, read only; no container, no network, no model.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from temper_ai.pi_agent.member import REFUSED_ADD_ONS
from temper_ai.pi_agent.team import (
    LATER_SECTIONS,
    TEAM_NOT_BUILT,
    AllCommunication,
    EdgesCommunication,
    LeaderMode,
    TeamSettings,
    parse_settings,
    team_topology,
    validate_team,
)
from temper_ai.pi_agent.team_check import (
    TEAM_ENFORCED_POLICIES,
    RoleList,
    check_team,
    goal_problem,
    safety_problems,
)
from temper_ai.pi_agent.team_node import TeamNode
from temper_ai.shared.types import ExecutionContext, Status
from tests.test_pi_agent import support as sup
from tests.test_pi_agent.support import FakeBox

ROLES = {"architecture": "System architecture", "frontend": "Frontend", "qa": "QA"}
GOOD = {"mode": {"type": "leader", "leader": "design"},
        "communication": {"type": "edges", "edges": {"design": ["frontend", "qa"],
                                                     "frontend": ["qa"]}},
        "pause_after_rounds": 3}
GOAL = {"goal": "Add a sign-up page"}
TOOLS = "Read, Edit, Write, Bash, Grep, Glob"


def members() -> list[dict]:
    return [{"name": "design", "type": "pi", "role": "architecture"},
            {"name": "frontend", "type": "pi", "role": "frontend", "tools": ["Read", "Edit", "Glob"]},
            {"name": "qa", "type": "pi", "role": "qa", "tools": ["Read", "Bash"]}]


def make_roles(root: Path) -> Path:
    for rid, title in ROLES.items():
        folder = root / rid
        folder.mkdir(parents=True)
        (folder / "identity.json").write_text(json.dumps(
            {"id": rid, "title": title, "homeChat": f"/home/owner/.pi/sessions/{rid}.jsonl"}))
        (folder / "about.md").write_text(f"# {title}\n")
        (folder / "notebook.md").write_text("## Rules\n")
    return root


def team_box_json(tmp: Path, **over) -> Path:
    raw = {"identities_dir": str(make_roles(tmp / "roles")),
           "routes": {"anthropic": {"provider": "anthropic", "host": "api.anthropic.com"},
                      "openai-codex": {"provider": "openai-codex", "host": "chatgpt.com"}},
           "add_ons": sup.make_add_ons(tmp / "pins")}
    raw.update(over)
    return sup.make_box_config(tmp / "box", **raw)


@pytest.fixture
def box(tmp_path):
    from temper_ai.pi_agent.box import BoxConfig

    return BoxConfig.load(str(team_box_json(tmp_path)))


def tree_digest(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        h.update(str(path.relative_to(root)).encode())
        h.update(oct(path.stat().st_mode).encode())
        if path.is_file():
            h.update(path.read_bytes())
    return h.hexdigest()


# --- the section models -------------------------------------------------------------------


def test_a_team_config_parses_into_its_sections():
    settings, problems = parse_settings(GOOD)
    assert problems == []
    assert settings == TeamSettings(
        mode=LeaderMode(leader="design"),
        communication=EdgesCommunication(edges={"design": ("frontend", "qa"),
                                                "frontend": ("qa",)}),
        pause_after_rounds=3)
    assert settings.as_dict() == GOOD


def test_communication_defaults_to_all():
    settings, problems = parse_settings({"mode": {"type": "leader", "leader": "design"},
                                         "pause_after_rounds": 1})
    assert problems == [] and settings is not None
    assert settings.communication == AllCommunication()
    assert settings.as_dict()["communication"] == {"type": "all"}


def _with(**sections) -> dict:
    cfg = {k: v for k, v in GOOD.items()}
    for key, value in sections.items():
        if value is None:
            cfg.pop(key, None)
        else:
            cfg[key] = value
    return cfg


@pytest.mark.parametrize("cfg, problem", [
    (_with(mode=None), "mode: required: {type: leader, leader: <member name>}"),
    (_with(mode={"type": "vote"}), "mode: unknown type 'vote' (available: leader)"),
    (_with(mode={"leader": "design"}), "mode: needs a 'type' (available: leader)"),
    (_with(mode="leader"), "mode: must be a mapping with a 'type' (one of: leader)"),
    (_with(mode={"type": "leader"}), "mode: type leader needs 'leader: <member name>'"),
    (_with(mode={"type": "leader", "leader": "design", "chair": "qa"}),
     "mode: unknown key 'chair' for type leader (known: type, leader)"),
    (_with(communication={"type": "mesh"}),
     "communication: unknown type 'mesh' (available: all, edges)"),
    (_with(communication={"type": "all", "edges": {}}),
     "communication: unknown key 'edges' for type all (known: type)"),
    (_with(communication={"type": "edges", "edges": ["design"]}),
     "communication: type edges needs 'edges: {member: [members it can start a conversation "
     "with]}'"),
    (_with(communication={"type": "edges", "edges": {"design": "qa"}}),
     "communication: type edges needs 'edges: {member: [members it can start a conversation "
     "with]}'"),
    (_with(pause_after_rounds=None),
     "pause_after_rounds: required, no default: how many rounds before the team pauses for the "
     "owner"),
    (_with(pause_after_rounds=0), "pause_after_rounds: must be a whole number of rounds, 1 or more"),
    (_with(pause_after_rounds=True),
     "pause_after_rounds: must be a whole number of rounds, 1 or more"),
    (_with(pause_after_rounds="3"),
     "pause_after_rounds: must be a whole number of rounds, 1 or more"),
    (_with(budget={"usd": 5}),
     "budget: unknown section (known: mode, communication, pause_after_rounds)"),
    ("leader", "strategy_config: must be a mapping of team sections (mode, communication, "
               "pause_after_rounds)"),
])
def test_each_format_problem_is_refused_by_name(cfg, problem):
    assert parse_settings(cfg)[0] is None
    assert validate_team(members(), cfg) == [problem]


@pytest.mark.parametrize("section", LATER_SECTIONS)
def test_sections_planned_for_later_are_refused_until_their_runtime_exists(section):
    assert validate_team(members(), _with(**{section: {"type": "x"}})) == [
        f"{section}: this section is not available yet; it comes with its runtime piece"]


def test_later_sections_are_the_plans():
    assert set(LATER_SECTIONS) == {"workspace", "lessons", "ask_owner", "conversation"}


# --- the team's own rules -----------------------------------------------------------------


def test_a_good_team_has_no_problems():
    assert validate_team(members(), GOOD) == []


def test_the_leader_must_be_a_member():
    got = validate_team(members(), _with(mode={"type": "leader", "leader": "boss"}))
    assert got == ["mode: leader 'boss' is not a member (members: design, frontend, qa)"]


def test_edges_name_members_only():
    got = validate_team(members(), _with(communication={"type": "edges", "edges": {
        "design": ["frontend", "qa", "ghost"], "intern": ["qa"]}}))
    assert got == ["communication: edges for 'design' name 'ghost', which is not a member",
                   "communication: edges list 'intern', which is not a member"]


def test_every_member_must_be_reachable_from_the_leader():
    one_way = {"type": "edges", "edges": {"design": ["frontend"], "qa": ["design"]}}
    assert validate_team(members(), _with(communication=one_way)) == [
        "communication: 'qa' can't be reached from the leader 'design', directly or through "
        "others"]
    through = {"type": "edges", "edges": {"design": ["frontend"], "frontend": ["qa"]}}
    assert validate_team(members(), _with(communication=through)) == []
    nobody = {"type": "edges", "edges": {}}
    assert validate_team(members(), _with(communication=nobody)) == [
        f"communication: '{name}' can't be reached from the leader 'design', directly or "
        "through others" for name in ("frontend", "qa")]
    assert validate_team(members(), _with(communication={"type": "all"})) == []


def test_members_are_named_pi_agents():
    team = members() + [{"name": "qa", "type": "pi", "role": "qa"},
                        {"name": "old", "type": "llm", "provider": "openai"}]
    assert validate_team(team, GOOD) == [
        "agents: the member name 'qa' is used more than once; give each member its own name:",
        "member 'old': is a 'llm' agent; team members are type: pi agents pointing at a pi role",
        "communication: 'old' can't be reached from the leader 'design', directly or through "
        "others"]
    assert validate_team([], GOOD)[0] == "agents: a team needs at least one member"


def test_a_members_own_config_problems_are_named_with_the_member():
    team = members()
    team[1]["tools"] = ["Read", "WebFetch"]
    team[2]["add_ons"] = ["relays"]
    assert validate_team(team, GOOD) == [
        f"member 'frontend': tool 'WebFetch' has no Pi equivalent (a Pi member can use {TOOLS})",
        f"member 'qa': add-on 'relays' is not allowed: {REFUSED_ADD_ONS['relays']}"]


# --- the pre-run check: roles, read only ----------------------------------------------------


def test_a_good_team_passes_the_pre_run_check(box):
    assert check_team(members(), GOOD, inputs=GOAL, box=box) == []


def test_a_missing_role_is_named_with_a_close_name_never_picked(box):
    team = members()
    team[0]["role"] = "architecure"
    team[2]["role"] = "zebra"
    assert check_team(team, GOOD, inputs=GOAL, box=box) == [
        "member 'design': role 'architecure' is not in the role list (did you mean "
        "'architecture'? Not picked automatically)",
        "member 'qa': role 'zebra' is not in the role list"]


def test_a_role_needs_its_identity_its_about_page_and_a_home_chat(box):
    roles = Path(box.identities_dir)
    (roles / "frontend" / "about.md").unlink()
    (roles / "qa" / "identity.json").write_text(json.dumps({"id": "qa", "title": "QA"}))
    (roles / "architecture" / "identity.json").write_text("{not json")
    assert check_team(members(), GOOD, inputs=GOAL, box=box) == [
        "member 'design': role 'architecture': identity.json is missing or unreadable",
        "member 'frontend': role 'frontend': its about page (about.md) is missing or unreadable",
        "member 'qa': role 'qa': identity.json has no home chat"]
    (roles / "qa" / "identity.json").write_text(json.dumps({"id": "qa", "homeChat": "  "}))
    (roles / "architecture" / "identity.json").write_text("[]")
    got = check_team(members(), GOOD, inputs=GOAL, box=box)
    assert "member 'design': role 'architecture': identity.json is not an object" in got
    assert "member 'qa': role 'qa': identity.json has no home chat" in got


def test_the_check_only_reads_the_role_folders(box):
    roles = Path(box.identities_dir)
    before = tree_digest(roles)
    modes = {path: path.stat().st_mode for path in [roles, *roles.rglob("*")]}
    for path in modes:  # read only, as the real role folders are mounted
        path.chmod(0o555 if path.is_dir() else 0o444)
    try:
        assert check_team(members(), GOOD, inputs=GOAL, box=box) == []
    finally:
        for path, mode in modes.items():
            path.chmod(mode)
    assert tree_digest(roles) == before


def test_the_role_list_must_be_configured(monkeypatch):
    monkeypatch.delenv("TEMPER_PI_BOX_CONFIG", raising=False)
    assert check_team(members(), GOOD, inputs=GOAL) == [
        "roles: role list not configured (set TEMPER_PI_BOX_CONFIG to the worker box config)"]
    assert RoleList(Path("/nonexistent/roles")).ids() == []


def test_a_member_needs_a_worker_route_and_pinned_add_ons(tmp_path):
    from temper_ai.pi_agent.box import BoxConfig

    bare = BoxConfig.load(str(team_box_json(
        tmp_path, add_ons={},
        routes={"anthropic": {"provider": "anthropic", "host": "api.anthropic.com"}})))
    team = members()
    team[1].update(provider="openai-codex", model="gpt-6.1-sol")
    team[2]["add_ons"] = []
    assert check_team(team, GOOD, inputs=GOAL, box=bare) == [
        "member 'design': no pinned copy of add-on(s) billion-context-pi, pi-image-trim, "
        "pi-tldr in the worker box config",
        "member 'frontend': no worker route for provider 'openai-codex' in the worker box config",
        "member 'frontend': no pinned copy of add-on(s) billion-context-pi, pi-image-trim, "
        "pi-tldr in the worker box config"]


# --- the pre-run check: goal and safety -----------------------------------------------------


def test_the_goal_must_be_set():
    assert goal_problem(None, GOAL) is None
    assert goal_problem(None, {}) == ("goal: required: give the run a 'goal' input or map it "
                                      "in the stage's input_map")
    assert goal_problem(None, {"goal": "  "}) is not None
    assert goal_problem({"goal": "input.brief"}, {"brief": "Add a page"}) is None
    assert goal_problem({"goal": "input.brief"}, {}) == (
        "goal: the stage reads it from the run input 'brief', which is not set")
    assert goal_problem({"goal": "plan.output"}, {}) is None  # known only when the node starts
    assert goal_problem({"topic": "input.topic"}, GOAL) == (
        "goal: required: map it in the stage's input_map (goal: <source>)")


def test_each_safety_policy_a_team_cannot_enforce_is_refused_by_name():
    assert TEAM_ENFORCED_POLICIES == frozenset()
    assert safety_problems(None) == [] and safety_problems({"policies": []}) == []
    assert safety_problems({"policies": [{"type": "file_access", "name": "no_secrets"},
                                         {"type": "rate_limit"}, "strict"]}) == [
        "safety: policy 'no_secrets' (file_access) can't be enforced in a team yet; take it out "
        "of the workflow or run without a team stage",
        "safety: policy 'rate_limit' (rate_limit) can't be enforced in a team yet; take it out "
        "of the workflow or run without a team stage",
        "safety: policy '#3' (no type) can't be enforced in a team yet; take it out of the "
        "workflow or run without a team stage"]


def test_a_broken_team_gets_every_problem_at_once(box):
    team = [{"name": "design", "type": "pi", "role": "architecure"},
            {"name": "frontend", "type": "pi", "role": "frontend", "tools": ["Read", "WebFetch"]},
            {"name": "qa", "type": "pi", "role": "qa", "add_ons": ["pi-tldr", "relays"]}]
    cfg = {"mode": {"type": "leader", "leader": "boss"},
           "communication": {"type": "edges", "edges": {"design": ["frontend", "ghost"]}},
           "workspace": {"type": "shared"}}
    got = check_team(team, cfg, inputs={}, box=box,
                     safety={"policies": [{"type": "file_access", "name": "no_secrets"}]},
                     unloaded={"reviewer": "Agent config 'reviewer' not found"})
    assert got == [
        "member 'reviewer': its agent config can't be loaded: Agent config 'reviewer' not found",
        f"member 'frontend': tool 'WebFetch' has no Pi equivalent (a Pi member can use {TOOLS})",
        f"member 'qa': add-on 'relays' is not allowed: {REFUSED_ADD_ONS['relays']}",
        "workspace: this section is not available yet; it comes with its runtime piece",
        "pause_after_rounds: required, no default: how many rounds before the team pauses for "
        "the owner",
        "mode: leader 'boss' is not a member (members: design, frontend, qa)",
        "communication: edges for 'design' name 'ghost', which is not a member",
        "member 'design': role 'architecure' is not in the role list (did you mean "
        "'architecture'? Not picked automatically)",
        "goal: required: give the run a 'goal' input or map it in the stage's input_map",
        "safety: policy 'no_secrets' (file_access) can't be enforced in a team yet; take it out "
        "of the workflow or run without a team stage"]


# --- the team node ------------------------------------------------------------------------


def test_the_team_node_fails_red_until_the_runtime_is_built():
    nodes = team_topology(members(), GOOD)
    assert len(nodes) == 1 and isinstance(nodes[0], TeamNode)
    node = nodes[0]
    assert node.name == "team" and node.depends_on == []
    assert [m["name"] for m in node.agent_configs()] == ["design", "frontend", "qa"]
    result = node.run({"goal": "Add a sign-up page"},
                      ExecutionContext(run_id="r1", workflow_name="w", node_path="build",
                                       agent_name="", event_recorder=None, tool_executor=None))
    assert result.status == Status.FAILED
    assert result.error == TEAM_NOT_BUILT == "team runtime not built yet (T4/T5/M1)"
    assert result.metadata["team"] == {"members": ["design", "frontend", "qa"],
                                       "settings": GOOD}


# --- at run start: the loader -----------------------------------------------------------------


@pytest.fixture
def team_on(monkeypatch, tmp_path):
    """The team strategy registered as with the switch on, and a worker box config naming
    the fixture role list."""
    from temper_ai import pi_agent
    from temper_ai.stage import topology

    saved = [dict(r) for r in (topology._GENERATORS, topology._VALIDATORS,
                               topology._RUN_START_CHECKS)]
    monkeypatch.setenv(pi_agent.SWITCH_ENV, "1")
    path = team_box_json(tmp_path)
    monkeypatch.setenv("TEMPER_PI_BOX_CONFIG", str(path))
    assert pi_agent.register_team_if_enabled() is True
    yield path
    for registry, before in zip((topology._GENERATORS, topology._VALIDATORS,
                                 topology._RUN_START_CHECKS), saved, strict=True):
        registry.clear()
        registry.update(before)


def store(*stages: dict, safety: dict | None = None, extra: dict | None = None):
    configs = {"workflow:team_wf": {"name": "team_wf", "nodes": list(stages),
                                    **({"safety": safety} if safety else {})}}
    for cfg in members():
        configs[f"agent:{cfg['name']}"] = dict(cfg)
    configs.update(extra or {})
    st = MagicMock()

    def get(name, config_type):
        key = f"{config_type}:{name}"
        if key in configs:
            return configs[key]
        raise Exception(f"Config not found: {key}")

    st.get = MagicMock(side_effect=get)
    return st


def team_stage(name: str = "build", **over) -> dict:
    stage = {"name": name, "type": "stage", "strategy": "team",
             "agents": ["design", "frontend", "qa"], "strategy_config": GOOD,
             "input_map": {"goal": "input.goal"}}
    stage.update(over)
    return stage


def test_a_good_team_stage_loads_as_one_team_node(team_on):
    from temper_ai.stage.loader import GraphLoader
    from temper_ai.stage.stage_node import StageNode

    nodes, _ = GraphLoader(store(team_stage())).load_workflow("team_wf", inputs=GOAL,
                                                              run_start=True)
    assert len(nodes) == 1 and isinstance(nodes[0], StageNode)
    (team,) = nodes[0].child_nodes
    assert isinstance(team, TeamNode)
    assert team.settings.as_dict() == GOOD
    assert [m["role"] for m in team.members] == ["architecture", "frontend", "qa"]
    assert [c["name"] for c in nodes[0].agent_configs()] == ["design", "frontend", "qa"]


def test_a_refused_team_lists_every_problem_and_builds_nothing(team_on):
    from temper_ai.stage.exceptions import ValidationError
    from temper_ai.stage.loader import GraphLoader

    broken = team_stage(agents=["design", "ghost", "frontend", "design"],
                        strategy_config={"mode": {"type": "leader", "leader": "boss"},
                                         "pause_after_rounds": 0})
    second = team_stage("check", agents=["qa"],
                        strategy_config={"mode": {"type": "leader", "leader": "qa"},
                                         "pause_after_rounds": 1},
                        input_map={"goal": "build.output"}, depends_on=["build"])
    loader = GraphLoader(store(broken, second,
                               safety={"policies": [{"type": "file_access", "name": "repo"}]}))
    with pytest.raises(ValidationError) as err:
        loader.load_workflow("team_wf", inputs={}, run_start=True)
    text = str(err.value)
    assert text.startswith("Workflow 'team_wf' validation failed:\n")
    lines = [line.removeprefix("  - ") for line in text.splitlines()[1:]]
    policy = ("safety: policy 'repo' (file_access) can't be enforced in a team yet; take it out "
              "of the workflow or run without a team stage")
    assert lines == [
        "Stage 'build': member 'ghost': its agent config can't be loaded: Failed to load agent "
        "config 'ghost': Config not found: agent:ghost",
        "Stage 'build': agents: the member name 'design' is used more than once; give each "
        "member its own name:",
        "Stage 'build': pause_after_rounds: must be a whole number of rounds, 1 or more",
        "Stage 'build': mode: leader 'boss' is not a member (members: design, frontend)",
        "Stage 'build': goal: the stage reads it from the run input 'goal', which is not set",
        f"Stage 'build': {policy}",
        f"Stage 'check': {policy}"]


def test_a_run_start_problem_is_kept_next_to_a_later_load_error(team_on):
    from temper_ai.stage.exceptions import ValidationError
    from temper_ai.stage.loader import GraphLoader

    later = {"name": "review", "type": "stage", "strategy": "parallel", "agents": ["nobody"],
             "depends_on": ["build"]}
    loader = GraphLoader(store(team_stage(), later))
    with pytest.raises(ValidationError) as err:
        loader.load_workflow("team_wf", inputs={}, run_start=True)
    assert "Stage 'build': goal: the stage reads it from the run input 'goal'" in str(err.value)
    assert "Config not found: agent:nobody" in str(err.value)


def test_a_resume_does_not_check_again(team_on):
    from temper_ai.stage.loader import GraphLoader

    roles = Path(json.loads(Path(team_on).read_text())["identities_dir"])
    (roles / "qa" / "about.md").unlink()
    loader = GraphLoader(store(team_stage()))
    nodes, _ = loader.load_workflow("team_wf", inputs=GOAL)  # what a resume does
    assert isinstance(nodes[0].child_nodes[0], TeamNode)
    from temper_ai.stage.exceptions import ValidationError
    with pytest.raises(ValidationError, match="its about page"):
        loader.load_workflow("team_wf", inputs=GOAL, run_start=True)


def test_the_strategy_list_names_team_and_other_strategies_load_as_before(team_on):
    from temper_ai.stage.exceptions import ValidationError
    from temper_ai.stage.loader import GraphLoader

    with pytest.raises(ValidationError, match=r"\(parallel, sequential, leader, team\)"):
        GraphLoader(store({"name": "x", "type": "stage", "agents": ["qa"]})).load_workflow(
            "team_wf")
    plain = {"name": "review", "type": "stage", "strategy": "parallel",
             "agents": ["design", "qa"]}
    started, _ = GraphLoader(store(plain)).load_workflow("team_wf", run_start=True)
    resumed, _ = GraphLoader(store(plain)).load_workflow("team_wf")
    assert [c.name for c in started[0].child_nodes] == [c.name for c in resumed[0].child_nodes]
    assert [c.agent_config for c in started[0].child_nodes] == [
        c.agent_config for c in resumed[0].child_nodes]


# --- at run start: the API ------------------------------------------------------------------


def test_a_refused_team_never_becomes_a_run(pi, team_on, monkeypatch):
    from temper_ai.observability.recorder import get_events
    from temper_ai.stage.loader import GraphLoader

    broken = team_stage(strategy_config={"mode": {"type": "leader", "leader": "boss"}})
    pi.state.graph_loader = GraphLoader(store(broken))
    pi.ws.mkdir(parents=True, exist_ok=True)
    r = pi.client.post("/api/runs", json={"workflow": "team_wf", "inputs": {},
                                          "workspace_path": str(pi.ws)})
    assert r.status_code == 400
    detail = r.json()["detail"]
    for problem in ("pause_after_rounds: required, no default",
                    "mode: leader 'boss' is not a member",
                    "goal: the stage reads it from the run input 'goal', which is not set"):
        assert f"Stage 'build': {problem}" in detail
    assert get_events(event_type="workflow.started", limit=1000) == []
    assert FakeBox.STARTS == []


def test_a_checked_team_runs_and_its_node_fails_red_without_any_worker(pi, team_on):
    from temper_ai.stage.loader import GraphLoader

    pi.state.graph_loader = GraphLoader(store(team_stage()))
    eid = sup.start(pi.client, "team_wf", pi.ws, inputs=GOAL)
    assert sup.wait_ended(eid)[-1]["status"] == "failed"
    said = [e for e in sup.events(eid) if TEAM_NOT_BUILT in json.dumps(e["data"], default=str)]
    assert said, "the run says the team runtime is not built yet"
    assert FakeBox.STARTS == []


def test_the_check_needs_no_model_and_no_container(box, monkeypatch):
    import subprocess

    def refuse(*_a, **_k):
        raise AssertionError("the pre-run check started a process")

    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)
    monkeypatch.setattr(os, "system", refuse)
    assert check_team(members(), GOOD, inputs=GOAL, box=box) == []
