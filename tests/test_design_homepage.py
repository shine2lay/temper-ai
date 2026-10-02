"""Model-free contracts for Design's template-driven Penpot workflow.

No model payloads, accounts, browsers or services. Actual deployment, gates, API
persistence and exports are separate evidence in Design's pilot packet.
"""
import copy
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from temper_ai.stage.models import WorkflowConfig

BIN = Path(__file__).resolve().parents[1] / "configs/design/bin"
sys.path.insert(0, str(BIN))
spec = importlib.util.spec_from_file_location("design_homepage_v1", BIN / "design_homepage_v1.py")
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)


def reservation():
    return {"pacific_day": datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat(),
            "reserve_usd": 2.6, "day_spent_usd": 6.053515, "trial_spent_usd": 0,
            "trial_envelope_usd": 8.75, "subscription_checked": True, "one_design_experiment": True}


@pytest.mark.parametrize("workflow", ["design_homepage_v1", "design_homepage_pilot_v1"])
def test_schema_and_bounded_loop(workflow):
    path = BIN.parent / "workflows" / f"{workflow}.yaml"
    raw = yaml.safe_load(path.read_text())["workflow"]
    config = WorkflowConfig.from_dict(raw)
    assert config.name == workflow
    nodes = {n["name"]: n for n in raw["nodes"]}
    assert nodes["disposition"]["max_loops"] == 3
    assert nodes["disposition"]["loop_to"] == "design"
    assert nodes["budget"]["gate"] is True
    assert nodes["disposition"]["gate"] is True
    assert nodes["critic_a"]["agent"] == nodes["critic_b"]["agent"] == "design_critic"
    assert nodes["merge"]["agent"] == "design_merge"
    if workflow == "design_homepage_v1":
        assert nodes["direction"]["gate"] and nodes["final"]["gate"]
    else:
        assert not nodes["direction"].get("gate")
        assert "final" not in nodes
        assert nodes["brief"]["input_map"]["mode"] == "pilot"


@pytest.mark.parametrize("direction", h.DIRECTIONS)
@pytest.mark.parametrize("width", h.WIDTHS)
def test_editable_geometry_and_measurement(direction, width):
    canvas = h.Canvas(h.p.nid(), h.p.nid())
    canvas.homepage(copy.deepcopy(h.DEFAULT), direction, width)
    state = canvas.state({"team-id": h.p.nid()})
    facts = h.measure(state)
    assert facts["objects"]
    assert not facts["violations"]
    assert not facts["text_box_overlaps"]
    texts = [o for o in state["objects"] if o["type"] == "text"]
    assert len(texts) > 25
    assert all(o["content"]["children"] for o in texts)
    assert state["components"]
    assert any(o.get("shape-ref") for o in state["objects"])
    assert set(h.RUNTIME_ONLY) <= set(facts["runtime_not_checked"])
    assert not any(o["type"] == "image" for o in state["objects"])


def test_structures_are_distinct():
    orders = []
    for direction in h.DIRECTIONS:
        canvas = h.Canvas(h.p.nid(), h.p.nid(), True)
        canvas.homepage(copy.deepcopy(h.DEFAULT), direction, 390)
        names = [m["name"] for m in canvas.metrics if m["board"].startswith("Wireframe ")]
        orders.append([name for name in names if name in ("H2 — How it works", "H2 — room examples", "Needs heading")])
    assert len({tuple(order) for order in orders}) == 3


def test_real_cannot_use_pilot_or_provisional_approval():
    brief = {**h.DEFAULT, "fictional": False}
    with pytest.raises(ValueError, match="refuses real"):
        h.direction_contract(brief, {"direction": "task-led"}, True)
    with pytest.raises(ValueError, match="owner direction"):
        h.direction_contract(brief, {"direction": "task-led", "approval": "provisional-fictional"}, False)
    result = h.direction_contract(brief, {"direction": "task-led", "approval": "owner-direction"}, False)
    assert result["owner_taste_approved"] is False


def test_fictional_choice_never_claims_owner_approval():
    result = h.direction_contract(h.DEFAULT, {"direction": "task-led", "approval": "owner-direction"}, True)
    assert result["approval"] == "provisional-fictional"
    assert not result["owner_taste_approved"]


def test_bad_copy_and_missing_brief():
    with pytest.raises(ValueError, match="explicit fictional"):
        h.brief_contract({})
    with pytest.raises(ValueError, match="exceeds"):
        h.brief_contract({**h.DEFAULT, "headline": "A" * 86})
    with pytest.raises(ValueError, match="disclose demo"):
        h.brief_contract({**h.DEFAULT, "cta": "Book now"})


@pytest.mark.parametrize("changes, error", [
    ({"reserve_usd": 4}, "Pacific-day"),
    ({"trial_spent_usd": 7}, "envelope"),
    ({"trial_envelope_usd": 11}, "envelope"),
    ({"pacific_day": "2000-01-01"}, "expired"),
    ({"subscription_checked": False}, "subscription"),
    ({"reserve_usd": float("nan")}, "finite"),
])
def test_budget_guard_errors(changes, error):
    with pytest.raises(ValueError, match=error):
        h.budget_contract({**reservation(), **changes}, 1)


def test_budget_round_ceiling():
    assert h.budget_contract(reservation(), 3)
    with pytest.raises(ValueError, match="maximum three"):
        h.budget_contract(reservation(), 4)


def test_resume_reuses_and_refuses_changed_completed_stage(tmp_path):
    job = h.Job(tmp_path)
    first = job.brief(json.dumps(h.DEFAULT), True)
    checkpoint = h.load(job.state_path)
    second = h.Job(tmp_path).brief(json.dumps(h.DEFAULT), True)
    assert second["reused"] and first["status"] == "completed"
    assert h.load(job.state_path) == checkpoint
    with pytest.raises(ValueError, match="inputs changed"):
        h.Job(tmp_path).brief(json.dumps({**h.DEFAULT, "subhead": "Different message."}), True)


def test_unknown_and_nonjson_direction_errors():
    with pytest.raises(ValueError, match="JSON decision"):
        h.safe_gate("yes please")
    with pytest.raises(ValueError, match="direction must"):
        h.direction_contract(h.DEFAULT, {"direction": "recolour"}, True)


def test_no_canvas_fallback_or_credential_in_output(monkeypatch):
    monkeypatch.setenv("PENPOT_URL", "https://spark.tailbb5055.ts.net:8790")
    monkeypatch.setenv("PENPOT_AGENT_EMAIL", "design-agent@spark.local")
    monkeypatch.delenv("PENPOT_AGENT_PASSWORD", raising=False)
    with pytest.raises(ValueError, match="never substitute"):
        h.Penpot().login()
    monkeypatch.setenv("PENPOT_URL", "https://untrusted.example")
    with pytest.raises(ValueError, match="authorized Penpot host"):
        h.Penpot()


def test_completion_not_self_attested(tmp_path):
    job = h.Job(tmp_path)
    assert not job.state["packet_verified"]
    assert not job.state["owner_taste_approved"]
    with pytest.raises(ValueError, match="final owner gate"):
        job.final("{}")


def test_unreferenced_or_fourth_fix_refused(tmp_path):
    job = h.Job(tmp_path)
    (tmp_path / "review").mkdir()
    h.save(tmp_path / "review/findings.json", {"findings": [{"id": "D1"}]})
    job.state["review_round"] = 1
    with pytest.raises(ValueError, match="existing evidence"):
        job.disposition(json.dumps({"action": "fix", "issues": ["made-up"], "patch": {"subhead": "Shorter."}}))
    job.state["review_round"] = 3
    with pytest.raises(ValueError, match="exhausted"):
        job.disposition(json.dumps({"action": "fix", "issues": ["D1"], "patch": {"subhead": "Shorter."}}))
