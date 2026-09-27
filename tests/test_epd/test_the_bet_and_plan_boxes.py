"""Each part of the loop run is its own box (queue task 15, 2026-09-27).

The owner could not see in temper's graph where writing the bet ends and planning begins: the loop
run started at its planning box, called `tasks`. The owner: "just put each in a stage so there's
boundary". epd_loop v13 starts with a `bet` box -- the approved pitch and the owner's approval, a
script with no model -- and calls the planning box `plan`. Nothing any box does changed.

The rename must not strand what came before it: a run from before v13 checkpointed its plan as
`tasks`, a bet's state.json recorded it under `tasks`, and `resume --at tasks` is what the RUNBOOK
said to type. The engine reads the old checkpoints through the node's `renamed_from`
(tests/test_stage/test_renamed_node.py); the driver reads the old name everywhere else (here, and
the resume tests in test_a_resume_goes_on_where_it_stopped.py, whose runs still say `tasks`).
"""

import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from temper_ai.agent.script_agent import ScriptAgent
from temper_ai.stage.models import WorkflowConfig
from temper_ai.tools.base import ToolResult
from tests.test_epd import test_epd_loop
from tests.test_epd.test_a_resume_goes_on_where_it_stopped import CHECKPOINTS, _resume
from tests.test_epd.test_script_agents import served_config

# The driver, loaded with its state in a temporary directory: test_epd_loop's fixture, by name.
L = test_epd_loop.L

ROOT = Path(__file__).resolve().parents[2]
LOOP = ROOT / "configs" / "epd" / "workflows" / "epd_loop.yaml"
PROPOSE = ROOT / "configs" / "epd" / "workflows" / "epd_propose.yaml"
BET_BOX = ROOT / "configs" / "epd" / "agents" / "epd_bet_approved.yaml"


def loop_workflow(path: Path = LOOP) -> WorkflowConfig:
    return WorkflowConfig.from_dict(yaml.safe_load(path.read_text())["workflow"])


# ---- the loop run's graph ------------------------------------------------------------------------


def test_the_loop_run_reads_bet_plan_turn_build_ship_deploy_measure():
    nodes = loop_workflow().nodes
    assert [n.name for n in nodes] == ["bet", "plan", "turn", "build", "ship", "deploy", "measure"]
    # one after the other: each box waits for the one before it
    for before, node in zip(nodes, nodes[1:], strict=False):
        assert before.name in node.depends_on, f"{node.name} does not wait for {before.name}"
    assert nodes[0].depends_on == []


def test_the_bet_box_is_a_script_and_the_plan_box_is_the_plan_stage():
    nodes = {n.name: n for n in loop_workflow().nodes}
    assert nodes["bet"].agent == "epd_bet_approved"
    assert served_config(BET_BOX)["type"] == "script"  # no model: it costs nothing
    assert nodes["plan"].type == "stage" and nodes["plan"].ref == "workflows/epd_plan"


def test_the_plan_box_keeps_its_old_name_for_runs_from_before():
    plan = next(n for n in loop_workflow().nodes if n.name == "plan")
    assert plan.renamed_from == ["tasks"]
    # nothing reads the plan's outputs by its old name any more
    text = LOOP.read_text()
    assert "tasks.structured" not in text and "[tasks]\n      type" not in text.replace("renamed_from: [tasks]\n", "")
    assert "depends_on: [tasks]" not in text


# ---- the proposal run's graph: the walks' report, then the problem list and one box per pitch ------


def test_the_proposal_run_reads_report_then_pitches():
    nodes = loop_workflow(PROPOSE).nodes
    assert [n.name for n in nodes] == ["report", "pitches"]
    pitches = nodes[1]
    assert pitches.depends_on == ["report"] and pitches.ref == "workflows/epd_bet"
    assert pitches.renamed_from == ["bet"]  # a round from before the rename resumes as it did
    text = PROPOSE.read_text()
    assert "bet.structured" not in text
    # inside it, each pitch is its own box, added by the problem list (`pitch_<bet id>`)
    inner = loop_workflow(ROOT / "configs" / "epd" / "workflows" / "epd_bet.yaml").nodes
    assert [n.name for n in inner] == ["problems"]


@pytest.mark.parametrize("box", ["pitches", "bet"])  # a round's box, after the rename and before it
def test_a_round_whose_pitches_had_started_is_collected_under_either_name(L, box):
    problems = {"agent": {"agent_name": "epd_problems", "status": "completed"}}
    info = {"nodes": [{"name": "report", "status": "completed"},
                      {"name": box, "status": "failed", "child_nodes": [problems]}]}
    assert L.pitches_were_started(info)
    info["nodes"][1]["child_nodes"] = []
    assert not L.pitches_were_started(info)


# ---- the bet box: shows the approved pitch and the owner's approval, and changes nothing ----------


def run_bet_box(inputs: dict) -> tuple[str, dict | None, str]:
    """The real agent and the real script, run by /bin/sh as the Bash tool runs it."""
    ctx = MagicMock()
    ctx.run_id, ctx.node_path, ctx.agent_name = "t", "bet", "epd_bet_approved"
    ctx.workspace_path = None

    def execute(_tool, args, **_kw):
        env = {"PATH": "/usr/bin:/bin", "HOME": tempfile.gettempdir(), **args["env"]}
        done = subprocess.run(args["command"], shell=True, capture_output=True, text=True, env=env, timeout=60)
        return ToolResult(success=done.returncode == 0, result=done.stdout, error=done.stderr)

    ctx.tool_executor.execute.side_effect = execute
    result = ScriptAgent(config=served_config(BET_BOX)).run(inputs, ctx)
    return result.status.value, result.structured_output, str(result.error or "") + str(result.output or "")


def test_the_bet_box_shows_the_pitch_and_the_approval(tmp_path):
    pitch = tmp_path / "bet.md"
    pitch.write_text("# Don't sell a call that's covered\nThe owner's words: \"it's $5\".\n")
    before = pitch.read_text()
    approval = "## Owner's decision\n\nApproved 2026-09-27 10:05 PDT: build it.\n"
    status, out, text = run_bet_box({"bet_id": "b120", "bet_path": str(pitch), "approval": approval,
                                      "title": "Covered calls", "invariant": "no call on a covered lot",
                                      "threshold": "0 of 20"})
    assert status == "completed", text
    assert out["pitch"] == before and out["approval"] == approval.strip()
    assert out["approved"] is True and out["approved_at"] == "2026-09-27 10:05"
    assert (out["bet_id"], out["title"], out["threshold"]) == ("b120", "Covered calls", "0 of 20")
    assert pitch.read_text() == before and sorted(p.name for p in tmp_path.iterdir()) == ["bet.md"]


def test_the_bet_box_fails_without_the_bet(tmp_path):
    status, _out, text = run_bet_box({"bet_id": "b120", "bet_path": str(tmp_path / "bet.md")})
    assert status == "failed"
    assert "no approved bet" in text


# ---- the driver: `plan` now, and `tasks` still read -----------------------------------------------


def test_a_state_saved_before_the_rename_is_read_as_plan(L):
    test_epd_loop.propose(L)
    st = L.load_state("b001")
    st["status"] = "tasked"
    st["stages"]["tasks"] = {"task_count": 3, "_run_id": "run-0"}
    L.state_path("b001").write_text(json.dumps(st))  # as a driver before v13 saved it
    st = L.load_state("b001")
    assert st["stages"]["plan"] == {"task_count": 3, "_run_id": "run-0"} and "tasks" not in st["stages"]
    assert L.NEXT_STAGE[st["status"]] == "build"  # a planned bet builds next, as before


def test_the_stages_are_named_for_the_new_boxes_and_the_old_name_is_still_taken(L, monkeypatch):
    assert L.STAGES == ["plan", "build", "ship", "deploy", "measure"]
    assert L.NEXT_STAGE["approved"] == "plan" and L.AFTER["plan"] == "tasked"
    assert L.stage_named("tasks") == "plan" and L.stage_named("build") == "build"
    test_epd_loop.propose(L)
    asked = []
    monkeypatch.setattr(L, "cmd_resume", lambda at, bet: asked.append(at))
    for at in ("plan", "tasks"):  # `resume --at tasks`, as the RUNBOOK said to type, is still taken
        monkeypatch.setattr("sys.argv", ["epd_loop.py", "resume", "--at", at, "--bet", "b001"])
        L.main()
    assert asked == ["plan", "tasks"]


def test_resume_at_tasks_plans_again_as_resume_at_plan_does(L, monkeypatch):
    fork, loop, _ = _resume(L, monkeypatch, at="tasks")
    assert fork[1] == 0 and loop["_went_on"] is False  # before the plan: nothing kept but the bet


def test_a_run_from_after_the_rename_resumes_at_its_build_after_its_plan(L, monkeypatch):
    """The same resume as before the rename, on a run whose boxes say `bet` and `plan`."""
    renamed = [("bet", "completed"), *[(n.replace("tasks", "plan"), s) for n, s in CHECKPOINTS]]
    fork, loop, _ = _resume(L, monkeypatch, at="build", checkpoints=renamed,
                            nodes=(("bet", "completed"), ("plan", "completed"), ("turn", "completed"),
                                   ("build", "completed")))
    assert fork[1] == 2  # after `plan`, the checkpoint that ends it
    assert loop["_went_on"] is False


def test_an_old_run_failed_in_its_plan_is_planned_again_under_the_new_name(L, monkeypatch):
    plan = [("tasks.tasks", "completed"), ("tasks.check", "failed")]
    fork, loop, _ = _resume(L, monkeypatch, error="1 node(s) failed: tasks/check", checkpoints=plan,
                            nodes=(("tasks", "failed"),))
    assert fork[1] == 0 and loop["_went_on"] is False
    assert L.load_state("b001")["stages"]["loop"]["_replaces"] == "run-1"
