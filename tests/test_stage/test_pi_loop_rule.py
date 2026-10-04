"""In a workflow with a Pi step every loop must say ``on_max_loops: fail``.

A Pi workflow must never count as done because a loop ran out of rounds (build plan T1, A8):
``silent`` (the default) and ``ship_with_open_issues`` both carry on as if the loop had
passed. ``temper check`` names such a loop, and starting the run refuses it, with a plain
reason. Workflows without a Pi step keep every policy.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from temper_ai.cli.check import _FileConfigs, check, check_pi_loops
from temper_ai.stage.exceptions import ValidationError
from temper_ai.stage.loader import GraphLoader
from temper_ai.stage.pi_workflows import is_pi_workflow

REPO_CONFIGS = Path(__file__).resolve().parents[2] / "configs"

_PI_STEP = """
    - name: talk
      type: agent
      agent: pi_talk
      depends_on: [brief]
"""


def _workflow(root: Path, name: str, *, policy: str | None, pi: bool = True) -> None:
    """brief -> [talk (the Pi step)] -> review, which loops back to itself."""
    policy_line = f"      on_max_loops: {policy}\n" if policy else ""
    after = "talk" if pi else "brief"
    (root / "workflows").mkdir(parents=True, exist_ok=True)
    (root / "workflows" / f"{name}.yaml").write_text(
        f"workflow:\n  name: {name}\n  nodes:\n"
        "    - name: brief\n      type: agent\n      agent: step\n"
        + (_PI_STEP if pi else "")
        + f"    - name: review\n      type: agent\n      agent: step\n      depends_on: [{after}]\n"
        "      loop_to: review\n      max_loops: 2\n"
        "      loop_condition: {source: review.structured.verdict, operator: equals, value: again}\n"
        + policy_line
    )


def _agent(root: Path) -> None:
    (root / "agents").mkdir(parents=True, exist_ok=True)
    (root / "agents" / "step.yaml").write_text(
        "agent:\n  name: step\n  type: script\n  script: echo done\n")
    (root / "agents" / "pi_talk.yaml").write_text(
        "agent:\n  name: pi_talk\n  type: pi\n  role: scout\n  provider: openai-codex\n"
        "  model: gpt-6.1-sol\n")


@pytest.fixture
def configs(tmp_path) -> Path:
    _agent(tmp_path)
    _workflow(tmp_path, "pi_silent", policy="silent")
    _workflow(tmp_path, "pi_ship", policy="ship_with_open_issues")
    _workflow(tmp_path, "pi_unsaid", policy=None)
    _workflow(tmp_path, "pi_fail", policy="fail")
    _workflow(tmp_path, "plain_silent", policy="silent", pi=False)
    return tmp_path


@pytest.mark.parametrize(("workflow", "said"), [
    ("pi_silent", "silent"),
    ("pi_ship", "ship_with_open_issues"),
    ("pi_unsaid", "silent"),  # the default
])
def test_starting_a_pi_workflow_whose_loop_may_run_out_quietly_is_refused(configs, workflow, said):
    with pytest.raises(ValidationError) as refused:
        GraphLoader(_FileConfigs(configs)).load_workflow(workflow)  # type: ignore[arg-type]
    message = str(refused.value)
    assert f"Node 'review' loops back to 'review' with on_max_loops: {said}." in message
    assert "every loop must say on_max_loops: fail" in message
    assert "stops the run red instead of letting it count as done" in message


def test_a_pi_workflow_whose_loops_say_fail_loads(configs):
    nodes, _ = GraphLoader(_FileConfigs(configs)).load_workflow("pi_fail")  # type: ignore[arg-type]
    assert is_pi_workflow(nodes)


def test_a_workflow_without_a_pi_step_keeps_every_policy(configs):
    nodes, _ = GraphLoader(_FileConfigs(configs)).load_workflow("plain_silent")  # type: ignore[arg-type]
    assert not is_pi_workflow(nodes)
    assert [n.on_max_loops for n in nodes if n.loop_to] == ["silent"]


def test_temper_check_names_each_loop_that_may_run_out(configs, capsys):
    seen, problems = check_pi_loops(configs)
    assert seen == 4, "the four Pi workflows; the plain one is not one"
    assert len(problems) == 3
    for name, said in (("pi_silent", "silent"), ("pi_ship", "ship_with_open_issues"),
                       ("pi_unsaid", "silent")):
        line = next(p for p in problems if f"{name}.yaml" in p)
        assert f"on_max_loops: {said}." in line and "must say on_max_loops: fail" in line
    assert check(configs) == 1
    out = capsys.readouterr().out
    assert "Workflows with a Pi step: 4" in out
    assert "3 loop(s) in Pi workflows may end by running out" in out


def test_temper_check_passes_when_every_pi_loop_says_fail(tmp_path, capsys):
    _agent(tmp_path)
    _workflow(tmp_path, "pi_fail", policy="fail")
    _workflow(tmp_path, "plain_silent", policy="silent", pi=False)
    assert check_pi_loops(tmp_path) == (1, [])
    assert check(tmp_path) == 0
    assert "every loop in a Pi workflow says on_max_loops: fail" in capsys.readouterr().out


def test_the_committed_configs_keep_the_rule():
    seen, problems = check_pi_loops(REPO_CONFIGS)
    assert seen >= 1, "ci_pi_waits is a Pi workflow"
    assert problems == []


def test_the_run_start_refuses_it_with_the_plain_reason(configs):
    from fastapi.testclient import TestClient

    from temper_ai.api.app_state import AppState
    from temper_ai.api.routes import init_app_state
    from temper_ai.config import ConfigStore
    from temper_ai.memory import InMemoryStore, MemoryService
    from temper_ai.server import app

    init_app_state(AppState(config_store=ConfigStore(),
                            graph_loader=GraphLoader(_FileConfigs(configs)),  # type: ignore[arg-type]
                            llm_providers={"mock": MagicMock()},
                            memory_service=MemoryService(InMemoryStore())))
    r = TestClient(app).post("/api/runs", json={"workflow": "pi_ship", "inputs": {}})
    assert r.status_code == 400
    assert "with on_max_loops: ship_with_open_issues" in r.json()["detail"]
    assert "every loop must say on_max_loops: fail" in r.json()["detail"]
