"""Model-free contracts for Design's advisory pairwise judge (design_pairwise_judge, queue #10).

The host lays out one homepage, or two under neutral letters, as screenshot tiles in judge/; the judge
agent rates each 1-5 and picks the stronger of a pair; the check step validates judge/verdict.json.
Which page is which version stays on the host, so nothing here names versions. No model or browser.
"""
import importlib.util
import json
from pathlib import Path

import pytest
import yaml

from temper_ai.stage.models import WorkflowConfig

ROOT = Path(__file__).resolve().parents[1]
DESIGN = ROOT / "configs/design"
spec = importlib.util.spec_from_file_location("design_pairwise_judge", DESIGN / "bin/design_pairwise_judge.py")
judge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(judge)


def layout(ws: Path, mode: str = "pair", pages=("A", "B")) -> Path:
    (ws / "judge").mkdir(parents=True)
    (ws / "judge/task.json").write_text(json.dumps({"mode": mode, "pages": list(pages)}))
    for page in pages:
        (ws / "judge" / page).mkdir()
        (ws / "judge" / page / "brief.md").write_text("# Brief\nA fictional product.\n")
        (ws / "judge" / page / "desktop-01.png").write_bytes(b"png")
        (ws / "judge" / page / "mobile-01.png").write_bytes(b"png")
    return ws


def verdict(ws: Path, **data) -> None:
    (ws / "judge/verdict.json").write_text(json.dumps(data))


def test_workflow_is_the_judge_then_a_model_free_check():
    raw = yaml.safe_load((DESIGN / "workflows/design_pairwise_judge.yaml").read_text())["workflow"]
    assert WorkflowConfig.from_dict(raw).name == "design_pairwise_judge"
    nodes = {n["name"]: n for n in raw["nodes"]}
    assert list(nodes) == ["judge", "check"]
    assert nodes["judge"]["agent"] == "design_pairwise_judge"
    assert nodes["check"]["agent"] == "design_pairwise_judge_check" and nodes["check"]["depends_on"] == ["judge"]
    assert not [n for n, v in nodes.items() if v.get("gate") or v.get("loop_to")]
    assert set(raw["outputs"]) == {"mode", "pick", "strength", "ratings", "consistent"}


def test_judge_is_an_advisory_opus_agent_and_the_check_a_script():
    agent = yaml.safe_load((DESIGN / "agents/design_pairwise_judge.yaml").read_text())["agent"]
    assert agent["type"] == "llm" and agent["provider"] == "claude" and agent["model"] == "opus"
    prompt = agent["system_prompt"]
    assert "judge/verdict.json" in prompt and "No ties" in prompt and "arbitrary" in prompt
    for word in ("version", "newer", "older", "v1", "v2"):  # the judge is never told which page is which
        assert word not in agent["task_template"]
    text = (DESIGN / "agents/design_pairwise_judge_check.yaml").read_text()
    check = yaml.safe_load(text)["agent"]
    assert check["type"] == "script" and "${" not in text
    assert "/app/configs/design/bin/design_pairwise_judge.py" in check["script_template"]


def test_check_accepts_a_pair_verdict_and_flags_a_pick_that_contradicts_the_ratings(tmp_path):
    ws = layout(tmp_path)
    verdict(ws, mode="pair", pick="B", strength="clear", ratings={"A": 3, "B": 4}, reasons=["one", "two", "three"])
    out = judge.check(ws)
    assert out["pick"] == "B" and out["strength"] == "clear" and out["ratings"] == {"A": 3, "B": 4}
    assert out["consistent"] is True and out["mode"] == "pair" and out["reasons"] == 3
    verdict(ws, mode="pair", pick="A", strength="slight", ratings={"A": 3, "B": 4}, reasons=["one", "two"])
    assert judge.check(ws)["consistent"] is False


def test_check_accepts_a_single_rating(tmp_path):
    ws = layout(tmp_path, "single", ("A",))
    verdict(ws, mode="single", ratings={"A": 2}, reasons=["one", "two"])
    out = judge.check(ws)
    assert out["ratings"] == {"A": 2} and "pick" not in out


@pytest.mark.parametrize("bad, message", [
    ({"pick": "C", "strength": "clear", "ratings": {"A": 3, "B": 4}, "reasons": ["a", "b"]}, "pick must be one of"),
    ({"pick": "A", "strength": "tie", "ratings": {"A": 3, "B": 4}, "reasons": ["a", "b"]}, "strength must be"),
    ({"pick": "A", "strength": "clear", "ratings": {"A": 3}, "reasons": ["a", "b"]}, "ratings must give every page"),
    ({"pick": "A", "strength": "clear", "ratings": {"A": 6, "B": 4}, "reasons": ["a", "b"]}, "whole number from 1 to 5"),
    ({"pick": "A", "strength": "clear", "ratings": {"A": 3.5, "B": 4}, "reasons": ["a", "b"]}, "whole number"),
    ({"pick": "A", "strength": "clear", "ratings": {"A": True, "B": 4}, "reasons": ["a", "b"]}, "whole number"),
    ({"pick": "A", "strength": "clear", "ratings": {"A": 3, "B": 4}, "reasons": ["only one"]}, "two reasons"),
])
def test_check_refuses_incomplete_verdicts(tmp_path, bad, message):
    ws = layout(tmp_path)
    verdict(ws, mode="pair", **bad)
    with pytest.raises(ValueError, match=message):
        judge.check(ws)


def test_check_refuses_a_missing_or_malformed_layout(tmp_path):
    with pytest.raises(ValueError, match="no judge/task.json"):
        judge.check(tmp_path)
    ws = layout(tmp_path / "w1")
    (ws / "judge/task.json").write_text(json.dumps({"mode": "pair", "pages": ["A", "A"]}))
    with pytest.raises(ValueError, match="two different single-letter pages"):
        judge.check(ws)
    ws = layout(tmp_path / "w2")
    (ws / "judge/B/desktop-01.png").unlink()
    with pytest.raises(ValueError, match="page B lacks"):
        judge.check(ws)
    ws = layout(tmp_path / "w3")
    with pytest.raises(ValueError, match="no judge/verdict.json"):
        judge.check(ws)
    (ws / "judge/verdict.json").write_text("{not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        judge.check(ws)
