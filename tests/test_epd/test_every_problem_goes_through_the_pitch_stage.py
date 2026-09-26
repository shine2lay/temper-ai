"""Every problem a round finds goes through the pitch stage (epd_bet v6, queue task 3, 2026-09-26).

One agent used to read the report and write one to five pitches itself. Now epd_problems lists every
problem not already on file, one per slot, and dispatches workflows/epd_pitch for each, at most 4 at
once. Here: the shipped YAML, and the dispatch rendered through the real renderer. The driver's side
(the slots, the code copy, collecting no-bets and failed stages) is tested in test_epd_loop.
"""

from pathlib import Path

import yaml

from temper_ai.llm.prompt_renderer import PromptRenderer
from temper_ai.stage.dispatch import render_dispatch

EPD = Path(__file__).resolve().parents[2] / "configs" / "epd"


def workflow(name: str) -> dict:
    return yaml.safe_load((EPD / "workflows" / f"{name}.yaml").read_text())["workflow"]


def agent(name: str) -> dict:
    return yaml.safe_load((EPD / "agents" / f"{name}.yaml").read_text())["agent"]


def required(name: str) -> set[str]:
    return {k for k, v in workflow(name)["inputs"].items() if v.get("required")}


def dispatched(n: int, bets_dir: str = "/app/workspaces/epd/rollcall/bets") -> list:
    problems = [{"bet_id": f"b{i:03d}", "title": f"problem {i}"} for i in range(1, n + 1)]
    return render_dispatch(agent("epd_problems"), agent_structured={"problems": problems},
                           agent_input_data={"bets_dir": bets_dir})


def test_the_bet_stage_is_one_agent_that_lists_the_problems():
    nodes = workflow("epd_bet")["nodes"]
    assert [(n["name"], n.get("agent")) for n in nodes] == [("problems", "epd_problems")]
    assert workflow("epd_bet")["outputs"]["candidates"] == "problems.structured.problems"


def test_the_proposal_passes_the_bet_stage_everything_the_pitch_stage_reads():
    bet = next(n for n in workflow("epd_propose")["nodes"] if n["name"] == "bet")
    assert bet["ref"] == "workflows/epd_bet"
    assert required("epd_bet") <= set(bet["input_map"]), f"missing {required('epd_bet') - set(bet['input_map'])}"
    for k in ("code_dir", "reach", "qa_config_path", "measure_config_path", "no_bets"):
        assert bet["input_map"][k] == f"input.{k}"
        assert k in workflow("epd_propose")["inputs"]


def test_each_problem_gets_its_own_pitch_stage_with_every_input_it_needs():
    ops = dispatched(2)
    stages = [node for op in ops for node in op.all_added_nodes()]
    assert [s["name"] for s in stages] == ["pitch_b001", "pitch_b002"]
    bet_inputs = set(workflow("epd_bet")["inputs"])
    for s, b in zip(stages, ("b001", "b002"), strict=True):
        assert s["type"] == "stage" and s["ref"] == "workflows/epd_pitch" and s["run_after_failure"] is True
        m = s["input_map"]
        assert required("epd_pitch") <= set(m), f"missing {required('epd_pitch') - set(m)}"
        assert set(m) <= set(workflow("epd_pitch")["inputs"]), "passes nothing the stage does not take"
        assert m["bet_id"] == b
        assert m["problem_path"] == f"/app/workspaces/epd/rollcall/bets/{b}/problem.md"
        assert m["out_path"] == f"/app/workspaces/epd/rollcall/bets/{b}/bet.md"
        refs = {v.split(".", 1)[1] for v in m.values() if v.startswith("input.")}
        assert refs <= bet_inputs, f"refers to {refs - bet_inputs}, which epd_bet does not take"


def test_at_most_four_pitch_stages_run_at_once():
    stages = [node for op in dispatched(9) for node in op.all_added_nodes()]
    deps = {s["name"]: s["depends_on"] for s in stages}
    assert all(deps[f"pitch_b00{i}"] == ["problems"] for i in (1, 2, 3, 4))
    assert deps["pitch_b005"] == ["pitch_b001"] and deps["pitch_b008"] == ["pitch_b004"]
    assert deps["pitch_b009"] == ["pitch_b005"]


def test_no_problem_dispatches_nothing():
    assert [node for op in dispatched(0) for node in op.all_added_nodes()] == []


def test_the_problem_list_is_told_what_is_on_file_and_writes_no_pitch():
    config = agent("epd_problems")
    assert "Write" in config["tools"] and "Bash" not in config["tools"]
    messages = PromptRenderer().render(agent_config=config, input_data={
        "round_id": "r018", "bets_dir": "/b", "slots": "b089 b090", "goals": "g", "profile": "p",
        "report_path": "/r/report.md", "bets_tsv": "b084\tproposed", "unfinished": "",
        "no_bets": "- b070: Loading is slow -- no bet: the first draw is already 0.2 s"})
    system, task = messages[0]["content"], messages[1]["content"]
    assert "Slot ids, in order: b089 b090" in task and "b084\tproposed" in task
    assert "- b070: Loading is slow -- no bet: the first draw is already 0.2 s" in task
    assert "no solution, no invariant, no threshold" in system
    plain = PromptRenderer().render(agent_config=config, input_data={
        "round_id": "r018", "bets_dir": "/b", "slots": "b089", "goals": "g", "profile": "p",
        "report_path": "/r/report.md", "bets_tsv": "", "unfinished": "", "no_bets": ""})[1]["content"]
    assert "found not real" not in plain
