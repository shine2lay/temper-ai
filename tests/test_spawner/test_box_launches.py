"""The gate's launch classification (BS1; design-v2 §6, §10 G11).

Positive and fail closed: a launch is sealed only when every part of it is a class a
sealed box enforces, known before the run starts. Anything unknown, anything chosen
while the run goes, and anything only a legacy box has keeps it out. Nothing a config
says about itself counts. The engine's own launch sites are listed, and the list must
match the code exactly.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from temper_ai.spawner import box_launches as bl
from temper_ai.spawner.box_seal import LOCAL_CODE
from temper_ai.tools import TOOL_CLASSES

REPO = Path(__file__).resolve().parents[2]

WORKFLOW = "workflow:\n  name: wf\n  nodes:\n  - name: one\n    agent: a\n"
AGENT = "agent:\n  name: a\n  type: llm\n  provider: claude\n  system_prompt: hi\n"


def _index(tmp_path: Path, files: dict[str, str]) -> bl.ConfigIndex:
    for rel, text in files.items():
        path = tmp_path / "configs" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return bl.ConfigIndex.of(bl.FsTree(tmp_path / "configs"))


def _classify(tmp_path: Path, *, workflow: str = WORKFLOW, agent: str = AGENT,
              extra: dict[str, str] | None = None, **kwargs) -> bl.Launch:
    files = {"workflows/wf.yaml": workflow, "agents/a.yaml": agent, **(extra or {})}
    return bl.classify(_index(tmp_path, files), "wf", **kwargs)


def _agent(*lines: str) -> str:
    return AGENT + "".join(f"  {line}\n" for line in lines)


def _step(*lines: str) -> str:
    return WORKFLOW + "".join(f"    {line}\n" for line in lines)


# -- the lists ---------------------------------------------------------------------------------


def test_every_tool_is_in_exactly_one_class():
    lists = [set(bl.SEALED_TOOLS), set(bl.LEGACY_TOOLS), set(bl.RUN_TIME_TOOLS)]
    assert sum(map(len, lists)) == len(set().union(*lists))
    assert set().union(*lists) == set(TOOL_CLASSES), "a new tool needs a class here"


def test_the_engine_table_lists_exactly_the_places_the_code_starts_programs():
    found = bl.launch_sites(REPO / "temper_ai", prefix="temper_ai/")
    listed = {site for site in bl.ENGINE_LAUNCHES if site.startswith("temper_ai/")}
    assert sorted(found - listed) == [], "classify each new launch site in ENGINE_LAUNCHES"
    assert sorted(listed - found) == [], "remove stale ENGINE_LAUNCHES entries"


def test_every_engine_launch_says_where_it_runs():
    for site, why in bl.ENGINE_LAUNCHES.items():
        assert why.split(":", 1)[0] in ("worker", "box", "legacy", "refused"), site
        assert site.startswith(("temper_ai/", "local/")) and "::" in site, site


def test_the_private_local_code_is_classified_too():
    """Runs where the private code is checked out (TEMPER_TEST_LOCAL_CODE=<its folder>)."""
    local = os.environ.get("TEMPER_TEST_LOCAL_CODE")
    if not local:
        pytest.skip("TEMPER_TEST_LOCAL_CODE isn't set: the worker checks it at every sealed spawn")
    found = bl.launch_sites(local, prefix="local/", only=LOCAL_CODE)
    listed = {site for site in bl.ENGINE_LAUNCHES if site.startswith("local/")}
    assert found == listed


@pytest.mark.parametrize(("source", "site"), [
    ("import subprocess\n\ndef f():\n    subprocess.run(['x'])\n", "m.py::f"),
    ("from subprocess import Popen\n\ndef f():\n    Popen(['x'])\n", "m.py::f"),
    ("import os\n\ndef f():\n    os.system('x')\n", "m.py::f"),
    ("import os\n\nclass C:\n    def f(self):\n        os.execv('/bin/x', ['x'])\n", "m.py::C.f"),
    ("from os import posix_spawn\n\ndef f():\n    posix_spawn('/bin/x', ['x'], {})\n", "m.py::f"),
    ("import asyncio\n\nasync def f():\n    await asyncio.create_subprocess_exec('x')\n",
     "m.py::f"),
    ("async def f(loop):\n    await loop.subprocess_exec(object, 'x')\n", "m.py::f"),
    ("import pty\n\ndef f():\n    pty.spawn('x')\n", "m.py::f"),
    ("import multiprocessing as mp\n\ndef f():\n    mp.Process(target=print).start()\n",
     "m.py::f"),
    ("import ctypes\nlibc = ctypes.CDLL(None)\n", "m.py::<module>"),
    ("from mcp.client.stdio import stdio_client\n", "m.py::<module>"),
    ("def f(:\n", "m.py::<unreadable>"),
])
def test_the_scan_finds_each_way_to_start_a_program(tmp_path, source, site):
    (tmp_path / "m.py").write_text(source)
    assert bl.launch_sites(tmp_path) == {site}


def test_the_scan_ignores_code_that_starts_nothing_and_folders_a_box_doesnt_mount(tmp_path):
    (tmp_path / "providers").mkdir()
    (tmp_path / "providers" / "p.py").write_text("import os\nos.path.join('a', 'b')\n")
    (tmp_path / "standee-ssh").mkdir()
    (tmp_path / "standee-ssh" / "s.py").write_text("import os\nos.system('id')\n")
    assert bl.launch_sites(tmp_path, only=("providers", "agents")) == set()
    assert bl.launch_sites(tmp_path) == {"standee-ssh/s.py::<module>"}
    assert bl.unclassified_sites({"x.py::f"}, {}) == ["x.py::f"]


# -- what a sealed launch is -------------------------------------------------------------------


def test_a_launch_of_classified_parts_is_sealed_and_records_what_it_may_use(tmp_path):
    launch = _classify(tmp_path)
    assert (launch.boundary, launch.reasons) == (bl.SEALED, ())
    assert set(launch.files) == {"configs/workflows/wf.yaml", "configs/agents/a.yaml"}
    assert launch.digest == bl.closure_digest(launch.files)
    assert launch.allowed == {"agent_types": ["llm"], "mcp_servers": [], "providers": ["claude"],
                              "tools": []}
    record = launch.as_dict()
    assert record["configs"] == {"agent": {"a": "configs/agents/a.yaml"},
                                 "workflow": {"wf": "configs/workflows/wf.yaml"}}
    assert record["label"] == bl.LABEL == "gate-classified; not reviewed by Security"
    assert record["classified_by"] == bl.GENERATOR and "review" not in record


def test_the_digest_follows_the_files(tmp_path):
    first = _classify(tmp_path)
    again = bl.classify(bl.ConfigIndex.of(bl.FsTree(tmp_path / "configs")), "wf")
    assert again == first
    (tmp_path / "configs" / "agents" / "a.yaml").write_text(_agent("description: changed"))
    changed = bl.classify(bl.ConfigIndex.of(bl.FsTree(tmp_path / "configs")), "wf")
    assert changed.boundary == bl.SEALED and changed.digest != first.digest


@pytest.mark.parametrize(("kwargs", "boundary", "reason"), [
    # chosen while the run goes
    ({"workflow": _step("type: template")}, bl.REFUSED, "is a template step"),
    ({"workflow": WORKFLOW.replace("agent: a", "agent: '{{ inputs.who }}'")}, bl.REFUSED,
     "picks its agent from a template"),
    ({"agent": _agent("tools: [Delegate]")}, bl.REFUSED, "runs agents it names at run time"),
    ({"workflow": WORKFLOW.replace("    agent: a\n", "    agents:\n    - agent: a\n"
                                   "      tools: [AddNode]\n")}, bl.REFUSED,
     "adds steps at run time"),
    ({"agent": _agent("dispatch:", "- op: add", "  node: {name: d, agent: b}"),
      "extra": {"agents/b.yaml": "agent:\n  name: b\n  provider: claude\n  tools: [Delegate]\n"}},
     bl.REFUSED, "agent 'b''s tool Delegate"),
    ({"agent": _agent("tools: ['{{ inputs.tool }}']")}, bl.REFUSED, "isn't a plain name"),
    # not classified
    ({"agent": _agent("tools: [Mystery]")}, bl.REFUSED, "tool 'Mystery' isn't classified"),
    ({"agent": AGENT.replace("type: llm", "type: claude_code")}, bl.REFUSED,
     "has type 'claude_code'"),
    ({"agent": AGENT.replace("type: llm", "type: jev")}, bl.REFUSED, "has type 'jev'"),
    ({"agent": AGENT.replace("claude", "openai")}, bl.REFUSED, "uses provider 'openai'"),
    ({"workflow": _step("provider: openai")}, bl.REFUSED, "step 'one' uses provider 'openai'"),
    ({"workflow": WORKFLOW.replace("    agent: a\n", "    agents:\n    - agent: a\n"
                                   "      provider: gemini\n")}, bl.REFUSED,
     "agent entry uses provider 'gemini'"),
    ({"agent": _agent("provider_config: {mcp_config: /x.json}")}, bl.REFUSED,
     "provider setting 'mcp_config' isn't classified"),
    ({"agent": _agent("fallback: {model: m, token: OTHER_KEY}")}, bl.REFUSED,
     "fallback has setting 'token'"),
    ({"agent": _agent("fallback: [{provider: openai, model: m}]")}, bl.REFUSED,
     "fallback uses provider 'openai'"),
    ({"agent": _agent("memory: {store: x}")}, bl.REFUSED, "has setting 'memory'"),
    ({"workflow": _step("strategy: team")}, bl.REFUSED, "uses strategy 'team'"),
    ({"workflow": _step("on_failure: {run: cleanup}")}, bl.REFUSED, "has setting 'on_failure'"),
    ({"workflow": WORKFLOW.replace("agent: a", "agent: nobody")}, bl.REFUSED,
     "names agent 'nobody', which isn't in configs/"),
    ({"extra": {"agents/again.yaml": AGENT}}, bl.REFUSED, "defined more than once"),
    ({"agent": _agent("script_template: python3 configs/agents/a_assets/gone.py")}, bl.REFUSED,
     "names configs/agents/a_assets/gone.py, which isn't there"),
    ({"agent": "agent:\n  name: a\n  type: llm\n  provider: claude\n  tools: [x.search]\n",
      "extra": {"mcp_servers/x.yaml": "mcp_server:\n  name: x\n  transport: sse\n"
                                      "  url: http://x\n"}},
     bl.REFUSED, "isn't a kind a sealed box classifies"),
    # needs what only a legacy box has
    ({"agent": _agent("tools: [OpenPullRequest]")}, bl.LEGACY, "shared /app/workspaces/repos"),
    ({"agent": _agent("tools: [RoameeData]")}, bl.LEGACY, "socket folder"),
    ({"agent": "agent:\n  name: a\n  type: pi\n"}, bl.LEGACY, "a Pi step"),
    ({"agent": _agent("system_prompt: read /app/repo/README.md")}, bl.LEGACY,
     "the main repo copy"),
    ({"agent": _agent("script_template: git worktree add ../x")}, bl.LEGACY, "git worktrees"),
    ({"agent": "agent:\n  name: a\n  type: llm\n  provider: claude\n  tools: [git.status]\n",
      "extra": {"mcp_servers/git.yaml": "mcp_server:\n  name: git\n  transport: stdio\n"
                                        "  command: uvx\n"}},
     bl.LEGACY, "MCP server 'git' starts 'uvx' in the box"),
    ({"agent": "agent:\n  name: a\n  type: llm\n  provider: claude\n  tools: [u.go]\n",
      "extra": {"mcp_servers/u.yaml": "mcp_server:\n  name: u\n  url: http://u\n"}},
     bl.LEGACY, "MCP server 'u' starts None in the box"),
])
def test_anything_unknown_run_time_or_legacy_keeps_a_launch_out_of_sealed(tmp_path, kwargs,
                                                                          boundary, reason):
    launch = _classify(tmp_path, **kwargs)
    assert launch.boundary == boundary, launch.reasons
    assert any(reason in why for why in launch.reasons), launch.reasons


@pytest.mark.parametrize("kwargs", [
    {"agent": _agent("fallback: claude-haiku-4")},
    {"agent": _agent("fallback: [{provider: anthropic, model: m, provider_config: {effort: low}}]")},
    {"agent": _agent("provider_config: {effort: high, max_tokens: 4000, cache_ttl: 1h}")},
    {"agent": _agent("tools: [Read, Bash, {name: WebFetch}]")},
    {"workflow": _step("strategy: parallel")},
    {"agent": _agent("script_template: python3 configs/agents/a_assets/check.py"),
     "extra": {"agents/a_assets/check.py": "print('ok')\n"}},
    {"agent": "agent:\n  name: a\n  type: llm\n  provider: claude\n  tools: [web.search]\n",
     "extra": {"mcp_servers/web.yaml": "mcp_server:\n  name: web\n  transport: http\n"
                                       "  url: https://web.example\n"}},
])
def test_classified_settings_tools_assets_and_servers_stay_sealed(tmp_path, kwargs):
    launch = _classify(tmp_path, **kwargs)
    assert (launch.boundary, launch.reasons) == (bl.SEALED, ())


def test_an_asset_and_a_url_server_are_part_of_the_launch(tmp_path):
    launch = _classify(
        tmp_path,
        agent="agent:\n  name: a\n  type: script\n  tools: [web.search]\n"
              "  script_template: python3 configs/agents/a_assets/check.py\n",
        extra={"agents/a_assets/check.py": "print('ok')\n",
               "mcp_servers/web.yaml": "mcp_server:\n  name: web\n  transport: http\n"
                                       "  url: https://web.example\n"})
    assert launch.boundary == bl.SEALED
    assert {"configs/agents/a_assets/check.py", "configs/mcp_servers/web.yaml"} <= set(launch.files)
    assert launch.allowed["mcp_servers"] == ["web"] and launch.allowed["tools"] == ["web.search"]
    assert launch.allowed["agent_types"] == ["script"] and launch.allowed["providers"] == []


@pytest.mark.parametrize(("default", "boundary", "reason"), [
    (None, bl.REFUSED, "the install's default is chosen at run time"),
    ("openai", bl.REFUSED, "default provider 'openai', whose login isn't classified"),
    ("claude", bl.SEALED, None),
])
def test_an_agent_without_a_provider_is_sealed_only_on_a_pinned_default(tmp_path, default,
                                                                        boundary, reason):
    launch = _classify(tmp_path, agent="agent:\n  name: a\n  system_prompt: hi\n",
                       default_provider=default)
    assert launch.boundary == boundary
    if reason:
        assert any(reason in why for why in launch.reasons), launch.reasons
    else:
        assert launch.default_provider == "claude" and launch.allowed["providers"] == ["claude"]


@pytest.mark.parametrize(("where", "key"), [
    ("workflow", "boundary"), ("workflow", "sealed"), ("step", "box"), ("step", "classified"),
    ("agent", "boundary"), ("agent", "review"), ("agent", "launch_class"),
])
def test_a_config_cant_declare_its_own_class(tmp_path, where, key):
    """Security rm-963c1429 condition 2: nothing in YAML can declare or change its class."""
    needs_legacy = _agent("tools: [OpenPullRequest]")
    if where == "workflow":
        kwargs = {"workflow": WORKFLOW.replace("  name: wf\n", f"  name: wf\n  {key}: sealed\n"),
                  "agent": needs_legacy}
    elif where == "step":
        kwargs = {"workflow": _step(f"{key}: sealed"), "agent": needs_legacy}
    else:
        kwargs = {"agent": needs_legacy + f"  {key}: sealed\n"}
    launch = _classify(tmp_path, **kwargs)
    assert launch.boundary == bl.REFUSED
    assert any(f"setting {key!r}" in why for why in launch.reasons), launch.reasons


def test_the_index_skips_what_the_importer_skips(tmp_path):
    """The Team page's settings folder (top level only) and team trials' names."""
    index = _index(tmp_path, {
        "team/wf_team.yaml": "workflow:\n  name: from_team_settings\n  nodes: []\n",
        "workflows/team/deeper.yaml": "workflow:\n  name: deeper\n  nodes: []\n",
        "workflows/trial.yaml": "workflow:\n  name: team-trial-1\n  nodes: []\n",
        "slack/x.yaml": "workflow:\n  name: from_settings\n  nodes: []\n",
    })
    assert set(index.by_kind["workflow"]) == {"deeper"}
    assert bl.classify(index, "team-trial-1").boundary == bl.REFUSED


# -- the configs at this master ----------------------------------------------------------------


def test_the_report_classifies_every_workflow_here():
    """A gate-time view: every workflow has a class, and a sealed one has no reason."""
    index = bl.ConfigIndex.of(bl.FsTree(REPO / "configs"))
    launches = bl.classify_all(index)
    assert [launch.workflow for launch in launches] == sorted(index.by_kind["workflow"])
    for launch in launches:
        assert (launch.boundary == bl.SEALED) == (not launch.reasons), launch.workflow
        assert launch.files and launch.digest, launch.workflow
    assert bl.main(["report", "--configs", str(REPO / "configs")]) == 0
