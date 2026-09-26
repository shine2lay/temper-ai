"""The EPD script agents: every one parses under /bin/sh, and the plan stage's hand-off counts its rounds.

A script agent's template reaches the shell through the Bash tool (`shell=True`, so /bin/sh: dash on
the server), whatever its `#!` line says. Most of them wrap a Python program in one single-quoted
shell word, so a single apostrophe anywhere in that program -- a comment saying "the check's" is
enough -- ends the quote, and the shell stops before Python starts. epd_plan_docs v2 did exactly
that, and the plan stage failed at its hand-off on every bet (b021, 2026-09-25, after $16.76 of
design and engineers). Nothing ran the script before a bet did; these tests do.
"""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml
from jinja2 import BaseLoader, ChainableUndefined
from jinja2.sandbox import SandboxedEnvironment

from temper_ai.agent.script_agent import (
    BARE_FILTER,
    ENV_FILTER,
    QUOTED_FILTER,
    ScriptAgent,
    _rewrite_interpolations,
    _ValueStash,
)
from temper_ai.config.helpers import substitute_env_vars
from temper_ai.tools.base import ToolResult

ROOT = Path(__file__).resolve().parents[2]
AGENTS = ROOT / "configs" / "epd" / "agents"


def served_config(path: Path) -> dict:
    """The agent config as the server hands it out (ConfigStore.get runs the env substitution)."""
    return substitute_env_vars(yaml.safe_load(path.read_text()))["agent"]


SCRIPT_AGENTS = sorted(p for p in AGENTS.glob("*.yaml") if served_config(p).get("type") == "script")


def test_the_epd_script_agents_are_all_found():
    names = {p.stem for p in SCRIPT_AGENTS}
    assert {"epd_plan_docs", "task_test", "task_cleanup", "epd_ship"} <= names


@pytest.mark.parametrize("path", SCRIPT_AGENTS, ids=lambda p: p.stem)
def test_every_epd_script_agent_parses_under_sh(path):
    """Rendered the way ScriptAgent renders it (every value moved into the environment), with every
    input undefined, then read by `sh -n`: a quote the template leaves open fails here, not on a bet."""
    config = served_config(path)
    stash = _ValueStash()
    env = SandboxedEnvironment(loader=BaseLoader(), undefined=ChainableUndefined)
    env.policies["json.dumps_kwargs"] = {"sort_keys": True, "default": lambda _undefined: None}  # `| tojson`
    env.filters[QUOTED_FILTER] = stash.quoted
    env.filters[BARE_FILTER] = stash.bare
    env.filters[ENV_FILTER] = stash.name
    script = env.from_string(_rewrite_interpolations(config["script_template"], config["name"])).render()
    done = subprocess.run(["sh", "-n", "-c", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, f"{path.name} does not parse under /bin/sh: {done.stderr.strip()}"


# ---- epd_plan_docs: the lead's inputs, and the round that decides its last pass --------------------

DOCS = AGENTS / "epd_plan_docs.yaml"


def run_docs(plan: dict) -> tuple[str, dict | None, str]:
    """The real agent and the real script, run by /bin/sh as the Bash tool runs it."""
    ctx = MagicMock()
    ctx.run_id, ctx.node_path, ctx.agent_name = "t", "docs", "epd_plan_docs"
    ctx.workspace_path = None

    def execute(_tool, args, **_kw):
        env = {"PATH": "/usr/bin:/bin", "HOME": tempfile.gettempdir(), **args["env"]}
        done = subprocess.run(args["command"], shell=True, capture_output=True, text=True, env=env, timeout=60)
        return ToolResult(success=done.returncode == 0, result=done.stdout, error=done.stderr)

    ctx.tool_executor.execute.side_effect = execute
    result = ScriptAgent(config=served_config(DOCS)).run(
        {"bet_path": plan["pitch"], "kb_dir": plan["kb"], "plan_dir": plan["dir"], "tasks_path": plan["tasks"]}, ctx)
    return result.status.value, result.structured_output, str(result.error or "") + str(result.output or "")


@pytest.fixture
def plan(tmp_path):
    kb = tmp_path / "kb"
    (kb / "core").mkdir(parents=True)
    for name in ("map.md", "decisions.md", "gotchas.md"):
        (kb / "core" / name).write_text(f"# {name}\nThe check's rule: a lot's call isn't \"covered\" (it's $5).\n")
    pitch = tmp_path / "bet.md"
    pitch.write_text("# Sell the call\nDon't offer a call on a lot that's already covered.\n")
    d = tmp_path / "plan"
    d.mkdir()
    (d / "design.md").write_text("# Design\nThe lot's call comes from the book.\n")
    for role in ("frontend", "backend", "numbers", "qa"):
        (d / f"{role}.md").write_text(f"# {role}\nIt's fine.\n")
    past = time.time() - 60  # the design came first; everything the lead writes is newer
    os.utime(d / "design.md", (past, past))
    return {"pitch": str(pitch), "kb": str(kb), "dir": str(d), "tasks": str(tmp_path / "tasks.json")}


def lead_writes(plan: dict, n: int) -> None:
    Path(plan["tasks"]).write_text(json.dumps({"tasks": [{"id": f"t{n}"}]}))
    (Path(plan["dir"]) / "plan.md").write_text(f"# Plan, draft {n}\n")


def test_the_first_pass_hands_the_lead_everything_and_no_draft(plan):
    status, out, said = run_docs(plan)
    assert status == "completed", said
    assert out["round"] == 1
    assert out["pitch"].startswith("# Sell the call") and "already covered" in out["pitch"]
    assert out["design"].startswith("# Design")
    assert [out[r].split("\n")[0] for r in ("frontend", "backend", "numbers", "qa")] == \
        ["# frontend", "# backend", "# numbers", "# qa"]
    assert "=== core/map.md" in out["core"] and "=== core/gotchas.md" in out["core"]
    assert "a lot's call isn't \"covered\" (it's $5)" in out["core"], "values reach Python untouched"
    assert (out["previous_tasks"], out["previous_plan"]) == ("", "")


def test_each_revise_is_one_more_round_and_hands_back_the_draft(plan):
    assert run_docs(plan)[1]["round"] == 1
    lead_writes(plan, 1)
    _, out, _ = run_docs(plan)  # the check said revise: back to docs
    assert out["round"] == 2
    assert json.loads(out["previous_tasks"]) == {"tasks": [{"id": "t1"}]}
    assert out["previous_plan"] == "# Plan, draft 1\n"
    lead_writes(plan, 2)
    _, out, _ = run_docs(plan)  # revise again: round 3 is the lead's last pass, and no check follows
    assert out["round"] == 3 and out["previous_plan"] == "# Plan, draft 2\n"


def test_a_newer_design_starts_the_rounds_again_and_drops_the_old_drafts(plan):
    run_docs(plan)
    lead_writes(plan, 1)
    assert run_docs(plan)[1]["round"] == 2
    later = time.time() + 60  # a new run's architect wrote a new design after all of that
    os.utime(Path(plan["dir"]) / "design.md", (later, later))
    _, out, _ = run_docs(plan)
    assert out["round"] == 1
    assert (out["previous_tasks"], out["previous_plan"]) == ("", ""), "an older attempt's draft is not the lead's"


def test_no_design_stops_the_stage(plan):
    (Path(plan["dir"]) / "design.md").unlink()
    status, _, said = run_docs(plan)
    assert status != "completed"
    assert "the architect wrote no design" in said
