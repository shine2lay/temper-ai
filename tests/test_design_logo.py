"""Model-free contracts. Mock geometry is not real Penpot/visual evidence.

No services/model requests/browser/vendor assets; deployed fixture proves the
native paths, edit/reopen/export and actual gate resume separately.
"""
import copy
import hashlib
import importlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from temper_ai.stage.models import WorkflowConfig

BIN = Path(__file__).resolve().parents[1] / "configs/design/bin"
sys.path.insert(0, str(BIN))
job = importlib.import_module("design_logo_v1")
c = importlib.import_module("logo_contracts")
s = importlib.import_module("penpot_logo_source")


def brief(name="Northline", fictional=True):
    return {"product": name, "secondary_name": name + " Kit", "fictional": fictional,
            "audience": "Fictional researchers organising field notes.",
            "positioning": "Make evidence easier to navigate.", "qualities": ["calm", "clear"],
            "avoid": ["copied symbols"], "interpretations": ["Direction, not naming history."],
            "sources": [{"id": "owner", "location": "fictional fixture", "fact": "Notes are grouped for later retrieval.", "status": "documented"}]}


def reservation():
    return {"pacific_day": datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat(),
            "reserve_usd": 8.15, "day_spent_usd": 1.55279, "trial_spent_usd": 0,
            "trial_envelope_usd": 8.15, "subscription_checked": True, "one_design_experiment": True,
            "reconciliation": "Model-free test; actual host ledger is separate."}


class Font:
    def __init__(self, data):
        pass

    def width(self, text, size):
        return len(text) * size * .44


@pytest.fixture
def canvas(tmp_path, monkeypatch):
    monkeypatch.setattr(s.p, "FontMetrics", Font)
    for variant in ("regular", "semibold"):
        (tmp_path / f"sourcesanspro-{variant}.ttf").write_bytes(b"test")
    file = {"id": s.p.nid(), "team-id": s.p.nid(), "project-id": s.p.nid(), "name": "Mock",
            "data": {"pages": [s.p.nid()]}}
    return s.LogoCanvas(file, tmp_path, "Northline")


@pytest.mark.parametrize("name", ["Northline", "Field Ledger"])
def test_different_brief_propagates_without_temper_catalogue(canvas, name):
    b = brief(name)
    c.brief_contract(b, "fixture")
    exploration = c.exploration_contract(job.fixture_exploration(b), b)
    palette = c.shortlist_contract(job.fixture_palette(b), b, exploration["concepts"])
    canvas.product = name
    canvas.comparison_board(exploration["concepts"], palette["shortlist"])
    state = canvas.state()
    assert any(m["text"] == name for m in state["metrics"])
    assert all("Temper" not in m["text"] for m in state["metrics"])
    assert any(o["type"] == "path" for o in state["objects"])
    assert not any(o["type"] == "image" for o in state["objects"])
    assert not s.measurements(state, {})["violations"]


@pytest.mark.parametrize("name,fictional,mode", [("Temper", True, "fixture"), ("Temper", False, "fixture"), ("Northline", True, "real")])
def test_real_fictional_modes_fail_closed(name, fictional, mode):
    with pytest.raises(ValueError):
        c.brief_contract(brief(name, fictional), mode)


@pytest.mark.parametrize("change", [{"approval": "owner-final"}, {"product": "x" * 40}, {"sources": []}, {"fictional": "false"}])
def test_brief_unknown_approval_or_unbounded_inputs(change):
    with pytest.raises(ValueError):
        c.brief_contract({**brief(), **change}, "fixture")


@pytest.mark.parametrize("shape", [
    {"kind": "script", "name": "x", "content": "bad"},
    {"kind": "rect", "name": "x", "x": 1, "y": 1, "w": float("nan"), "h": 4},
    {"kind": "ellipse", "name": "x", "x": 90, "y": 10, "w": 30, "h": 30},
    {"kind": "rect", "name": "x", "x": 1, "y": 1, "w": 10, "h": 10, "href": "https://bad.test"},
    {"kind": "path", "name": "x", "commands": [["M", 0, 0], ["L", 10, 10], ["L", 0, 10], ["L", 0, 0]]},
    {"kind": "path", "name": "x", "commands": [["M", 0, 0], ["Q", 1, 2, 3, 4], ["L", 0, 10], ["Z"]]},
])
def test_unsafe_unbounded_geometry_rejected(shape):
    with pytest.raises(ValueError):
        c.shape_contract(shape)


def test_six_divergent_not_recolour_and_cited_sources():
    b = brief()
    value = job.fixture_exploration(b)
    assert c.exploration_contract(value, b)
    duplicate = copy.deepcopy(value)
    duplicate["concepts"][1]["symbol"] = duplicate["concepts"][0]["symbol"]
    with pytest.raises(ValueError, match="duplicate"):
        c.exploration_contract(duplicate, b)
    value["concepts"][0]["source_ids"] = ["invented"]
    with pytest.raises(ValueError, match="cite"):
        c.exploration_contract(value, b)


RUN = "11111111-1111-4111-8111-111111111111"


@pytest.mark.parametrize("families", [
    ["geometric"] * 3 + ["letterform", "pictorial", "emblem"],  # three plain geometric marks
    ["geometric", "letterform"] * 3,  # only two families
])
def test_exploration_spans_families_with_at_most_two_plain_geometric(families):
    b = brief()
    value = job.fixture_exploration(b)
    for concept, family in zip(value["concepts"], families, strict=True):
        concept["family"] = family
    with pytest.raises(ValueError, match="families"):
        c.exploration_contract(value, b)


def test_concepts_name_family_ownable_detail_and_generic_risk():
    b = brief()
    value = job.fixture_exploration(b)
    for change in ({"family": "mascot"}, {"id": c.EXPLORE_AGAIN}, {"ownable_detail": ""}):
        bad = copy.deepcopy(value)
        bad["concepts"][0].update(change)
        with pytest.raises(ValueError):
            c.exploration_contract(bad, b)
    for field in ("ownable_detail", "generic_risk", "family"):
        bad = copy.deepcopy(value)
        del bad["concepts"][0][field]
        with pytest.raises(ValueError, match="declarative"):
            c.exploration_contract(bad, b)
    concepts = copy.deepcopy(value["concepts"])
    for concept in concepts[:3]:
        concept["family"] = "emblem"
    with pytest.raises(ValueError, match="two concept families"):
        c.shortlist_contract(job.fixture_palette(b), b, concepts)


def test_revision_pass_keeps_six_slots_and_bounded_notes():
    b = brief()
    draft = c.exploration_contract(job.fixture_exploration(b), b)
    concepts = copy.deepcopy(draft["concepts"])
    concepts[1]["symbol"] = [{"kind": "ellipse", "name": "Redrawn", "x": 14, "y": 14, "w": 72, "h": 72}]
    note = {"id": "fixture-1", "seen": "The render showed a plain oval.", "change": "Redrew it as a disc."}
    value = {"product": b["product"], "concepts": concepts, "revisions": [note]}
    assert c.revision_contract(value, b, draft)
    swapped = copy.deepcopy(value)
    swapped["concepts"][0], swapped["concepts"][1] = swapped["concepts"][1], swapped["concepts"][0]
    with pytest.raises(ValueError, match="same six concept ids"):
        c.revision_contract(swapped, b, draft)
    for notes in ([note, note], [{**note, "id": "invented"}], [{**note, "seen": ""}], [note] * 7):
        with pytest.raises(ValueError):
            c.revision_contract({**value, "revisions": notes}, b, draft)
    with pytest.raises(ValueError):
        c.revision_contract({**value, "product": "Elsewhere"}, b, draft)


def test_critic_prose_overrun_is_shortened_but_ids_and_unbounded_text_fail():
    """A 129-character location once failed a paid real critic save; shorten advisory prose instead."""
    b = brief()
    row = {"scope": "concept", "id": "fixture-2", "kind": "visual", "element": "Symbol",
           "location": "board " * 22, "evidence": "Seen at 32 px.", "suggestion": "Thicken it."}
    value = {"product": b["product"], "observations": [row], "recommendation": "fixture-2",
             "recommendation_reason": "Advice only.", "limitations": "Static PNGs."}
    out = c.critique_contract(copy.deepcopy(value), b, {"fixture-2"})
    location = out["observations"][0]["location"]
    assert len(location) == 120 and location.endswith("\u2026") and location.startswith("board board")
    for change in ({"location": "x" * 481}, {"location": "line\x00break"}, {"id": "invented"}, {"location": ""}):
        with pytest.raises(ValueError):
            c.critique_contract({**value, "observations": [{**row, **change}]}, b, {"fixture-2"})
    with pytest.raises(ValueError):
        c.critique_contract({**value, "limitations": "x" * 4001}, b, {"fixture-2"})
    assert c.critique_contract(copy.deepcopy({**value, "observations": [{**row, "location": "board 4"}]}), b,
                               {"fixture-2"})["observations"][0]["location"] == "board 4"


def test_model_layer_and_concept_labels_shortened_but_ids_strict():
    """A 49-character layer name once failed a paid real refinement save; shorten labels instead."""
    b = brief()
    concept = copy.deepcopy(job.fixture_exploration(b)["concepts"][0])
    concept["symbol"][0]["name"] = "dovetail tail, thick waist, stepped base and feet"
    concept["idea"] = "i" * 701
    out = c.concept_contract(copy.deepcopy(concept), b)
    assert len(out["symbol"][0]["name"]) == 48 and out["symbol"][0]["name"].endswith("\u2026")
    assert len(out["idea"]) == 700
    within = copy.deepcopy(job.fixture_exploration(b)["concepts"][0])
    assert c.concept_contract(copy.deepcopy(within), b) == within
    for change in ({"id": "x" * 40}, {"name": "n" * 129}, {"family": "stock"}):
        with pytest.raises(ValueError):
            c.concept_contract({**copy.deepcopy(concept), **change}, b)
    concept["symbol"][0]["name"] = "layer\x07name"
    with pytest.raises(ValueError):
        c.concept_contract(concept, b)


def research_folder(tmp_path):
    folder = tmp_path / "research-source"
    folder.mkdir()
    (folder / "comparison.md").write_text("2026-10-03 dated notes; references only.")
    (folder / "peer-a.png").write_bytes(job.PNG + b"fixture image")
    files = {n: hashlib.sha256((folder / n).read_bytes()).hexdigest() for n in ("comparison.md", "peer-a.png")}
    return folder, files


def prior_round():
    return {"run_id": "33333333-3333-4333-8333-333333333333", "owner_answer": "None: explore again",
            "owner_source": "fictional fixture", "rejected": [{"id": "old", "name": "Old", "idea": "An earlier idea."}],
            "evidence": ["peer-a.png"]}


def test_research_screen_and_rejected_round_reach_the_run_pinned(tmp_path):
    folder, files = research_folder(tmp_path)
    b = c.brief_contract({**brief(), "research": {"dir": str(folder), "files": files},
                          "prior_rounds": [prior_round()]}, "fixture")
    (tmp_path / "one").mkdir()
    j = job.Job(str(tmp_path / "one"), RUN, "fixture")
    copies = j.research(b)
    assert sorted(p.name for p in copies) == ["comparison.md", "comparison.md", "peer-a.png"]
    notes = (j.root / "comparison.md").read_text()
    for expected in ("logo/research/peer-a.png", "None: explore again", "Old: An earlier idea.", "dated notes"):
        assert expected in notes
    assert j.research(brief()) == []
    (folder / "peer-a.png").write_bytes(job.PNG + b"changed after pinning")
    (tmp_path / "two").mkdir()
    with pytest.raises(ValueError, match="pinned hash"):
        job.Job(str(tmp_path / "two"), RUN, "fixture").research(b)
    (folder / "peer-a.png").unlink()
    (folder / "peer-a.png").symlink_to(folder / "comparison.md")
    with pytest.raises(ValueError, match="linked"):
        job.Job(str(tmp_path / "two"), RUN, "fixture").research(b)


@pytest.mark.parametrize("change", [
    {"research": {"dir": "relative/research", "files": {"comparison.md": "0" * 64}}},
    {"research": {"dir": "/a/../b", "files": {"comparison.md": "0" * 64}}},
    {"research": {"dir": "/r", "files": {"peer.png": "0" * 64}}},
    {"research": {"dir": "/r", "files": {"comparison.md": "not-a-hash"}}},
    {"research": {"dir": "/r", "files": {"comparison.md": "0" * 64, "../x.png": "0" * 64}}},
    {"research": {"dir": "/r", "files": {"comparison.md": "0" * 64, "x.svg": "0" * 64}}},
    {"research": {"dir": "/r", "files": {"comparison.md": "0" * 64}}, "prior_rounds": [prior_round()]},
    {"research": {"dir": "/r", "files": {"comparison.md": "0" * 64, "peer-a.png": "0" * 64}},
     "prior_rounds": [prior_round()] * 3},
    {"prior_rounds": [{**prior_round(), "run_id": "not-a-run"}]},
])
def test_research_and_prior_rounds_are_bounded_and_pinned(change):
    with pytest.raises(ValueError):
        c.brief_contract({**brief(), **change}, "fixture")


def test_explore_again_records_rejection_ends_run_and_needs_owner_note(tmp_path):
    b = brief()
    j = job.Job(str(tmp_path), RUN, "fixture")
    job.save(j.root / "sketches.saved.json", c.exploration_contract(job.fixture_exploration(b), b))
    job.save(j.root / "palette.saved.json", job.fixture_palette(b))
    j.state.update(brief_hash="b", direction_artifact_hash="a")
    again = {**answer(fictional=True), "run_id": RUN, "decision": c.EXPLORE_AGAIN}
    with pytest.raises(ValueError, match="owner's own note"):
        j.direction(json.dumps(again), True)
    with pytest.raises(ValueError, match="ordinary input"):
        j.direction(json.dumps({**again, "owner_note": "None of these."}), False)
    out = j.direction(json.dumps({**again, "owner_note": "None of these."}), True)
    assert out["outcome"] == "explore_again" and out["direction_owner_approved"] is False
    record = job.load(j.root / "explore-again.json")
    assert [r["id"] for r in record["rejected"]] == ["fixture-0", "fixture-1", "fixture-2"]
    assert record["owner_answer"] == "None of these." and record["fictional_test"] is True
    assert "direction" not in j.state
    with pytest.raises(ValueError, match="no selected owner direction"):
        j.prepare_refine()


def test_board_text_fits_whole_words_never_mid_word(canvas):
    board = canvas.board("text", 0, 0, 400, 400)
    long = "A disc divided by a level gap, the upper half shifted slightly and then settled into balance. " * 3
    canvas.text(board, "Idea", long, 10, 10, 300, 16, max_lines=2)
    facts = s.measurements(canvas.state(), {})
    row = facts["text"][0]
    assert row["abridged"] and row["full_text"] == long and row["text"].endswith("\u2026")
    assert s.whole_words(row) and not facts["violations"]
    assert s.whole_words({**row, "text": "A disc divided by a level\u2026"})
    for cut in ("A disc divided by a lev\u2026", "A disc divided by a lev", "\u2026", long[:-3]):
        assert not s.whole_words({**row, "text": cut})
    assert s.measurements({**canvas.state(), "metrics": [{**canvas.state()["metrics"][0], "text": "A disc divided by a lev"}]},
                          {})["violations"]


def test_sketch_board_of_six_fits_without_violations(canvas):
    b = brief()
    canvas.rough_board(c.exploration_contract(job.fixture_exploration(b), b)["concepts"], "sketches revised after seeing the render")
    facts = s.measurements(canvas.state(), {})
    assert not facts["violations"]
    assert any(m["name"] == "Ownable detail" for m in facts["text"])


@pytest.mark.parametrize("change", [{"pacific_day": "2000-01-01"}, {"day_spent_usd": 2}, {"trial_spent_usd": 1},
                                     {"reserve_usd": float("inf")}, {"subscription_checked": "false"}, {"one_design_experiment": False}])
def test_budget_day_trial_and_fresh_allowance_fences(change):
    assert c.budget_contract(reservation(), c.INITIAL_RESERVE)
    with pytest.raises(ValueError):
        c.budget_contract({**reservation(), **change}, c.INITIAL_RESERVE)


@pytest.mark.parametrize("payload", [
    '<svg><script>alert(1)</script><rect width="1"/></svg>',
    '<svg onload="x"><path d="M0 0L1 1Z"/></svg>',
    '<svg><image href="data:image/png;base64,AA"/></svg>',
    '<svg><use href="https://bad.test/x"/><rect width="1"/></svg>',
    '<svg><style>@import "https://bad.test";</style><rect width="1"/></svg>',
    '<svg><style>text{font:url(https://private.test/x)}</style><rect width="1"/></svg>',
    '<!DOCTYPE svg [<!ENTITY x "bad">]><svg><rect width="1"/></svg>',
    '<svg><path d="MNaN 2L3 4Z"/></svg>',
    '<svg><rect x="1e999" width="1"/></svg>',
    '<svg><foreignObject/></svg>',
])
def test_unsafe_svg_resources_scripts_and_bounds(payload):
    with pytest.raises(ValueError):
        c.safe_svg(payload.encode())


@pytest.mark.parametrize("workspace", ["", ".", "relative", "/definitely-not-a-mounted-logo-workspace"])
def test_missing_or_relative_workspace_rejected_before_artifacts(workspace):
    with pytest.raises(ValueError, match="persistent workspace required"):
        job.Job(workspace, "11111111-1111-4111-8111-111111111111", "fixture")


def test_actual_native_vector_pattern_is_safe_but_resources_are_not():
    # Penpot 2.18.1 exports live-text fill patterns, even for plain colours.
    safe = b'<svg xmlns="http://www.w3.org/2000/svg"><defs><pattern id="p" width="1" height="1" patternUnits="userSpaceOnUse"><rect width="1" height="1" fill="#161616"/></pattern></defs><text fill="url(#p)">Northline</text></svg>'
    assert not c.safe_svg(safe)["external_resources"]
    for resource in (b'<image href="https://bad.test/image.png"/>', b'<use href="https://bad.test/mark.svg"/>', b'<script>bad</script>'):
        with pytest.raises(ValueError):
            c.safe_svg(safe.replace(b'<rect width="1" height="1" fill="#161616"/>', resource))
    for transform in (b'matrix(1e999 0 0 1 0 0)', b'matrix(NaN 0 0 1 0 0)'):
        with pytest.raises(ValueError):
            c.safe_svg(safe.replace(b'id="p"', b'id="p" patternTransform="' + transform + b'"'))


def test_self_contained_vectors_live_text_and_embedded_woff():
    data = b'<svg xmlns="http://www.w3.org/2000/svg"><style>@font-face{font-family:a;src:url(data:font/woff;base64,AA==)}</style><path d="M0 0 L100 0 L0 100 Z"/><text font-family="a">Northline</text></svg>'
    result = c.safe_svg(data)
    assert result["vectors"] == 1 and result["text_elements"] == 1 and not result["external_resources"]


def answer(kind="direction", fictional=False):
    return {"approval": "fixture-test" if fictional else "owner-" + kind, "run_id": "r", "brief_hash": "b",
            "artifact_hash": "a", "decision": "fixture-2" if kind == "direction" else "approve", "reason": "Actual/test gate answer."}


@pytest.mark.parametrize("key,value", [("run_id", "other"), ("brief_hash", "new"), ("artifact_hash", "old"), ("approval", "fixture-test"), ("decision", "unknown")])
def test_owner_gate_identity_fingerprint_and_approval_fence(key, value):
    kwargs = {"kind": "direction", "run_id": "r", "brief_hash": "b", "artifact_hash": "a", "choices": {"fixture-2"}, "gate_only": True}
    assert c.approval_contract(answer(), **kwargs)
    with pytest.raises(ValueError):
        c.approval_contract({**answer(), key: value}, **kwargs)
    with pytest.raises(ValueError, match="ordinary input"):
        c.approval_contract(answer(), **{**kwargs, "gate_only": False})


def test_fixture_cannot_claim_owner_approval():
    kwargs = {"kind": "final", "run_id": "r", "brief_hash": "b", "artifact_hash": "a", "choices": {"approve"}, "gate_only": True, "fictional": True}
    with pytest.raises(ValueError, match="must not claim"):
        c.approval_contract(answer("final"), **kwargs)
    assert c.approval_contract(answer("final", True), **kwargs)


def test_palette_roles_companion_contrast_logo_exemption(canvas):
    palette = job.fixture_palette(brief())["shortlist"][0]["palette"]
    assert c.palette_contract(palette)
    with pytest.raises(ValueError, match="contrast"):
        c.palette_contract({**palette, "muted": "#DDDDDD"})
    board = canvas.board("test", 0, 0, 500, 200)
    canvas.palette("exempt", {**s.MONO, "ink": "#AAAAAA"})
    canvas.text(board, "Logo", "Northline", 10, 10, 400, 40, color="exempt/ink", logo=True)
    facts = s.measurements(canvas.state(), {})
    assert facts["text"][0]["logo_exempt"] and facts["text"][0]["companion_aa"] is None
    assert not facts["violations"]


def test_accent_toned_parts_colour_versions_only(canvas):
    """Owner asked for colour in the mark: toned parts take the accent in colour versions only."""
    b = brief()
    concept = job.fixture_exploration(b)["concepts"][2]
    assert [part.get("tone") for part in concept["symbol"]] == [None, c.ACCENT_TONE]
    palette = c.palette_contract(job.fixture_palette(b)["shortlist"][2]["palette"])
    canvas.final_boards(b, concept, palette)
    boards = {board["id"]: board["name"] for board in canvas.boards}
    key = concept["id"]

    def fills(board_name, part):
        return {o["fills"][0]["fill-color-ref-id"] for o in canvas.objects
                if boards.get(o["parent-id"]) == board_name and o["name"].split("/")[1] == part}

    colour = canvas.colors
    for board_name, base in (("symbol", "ink"), ("primary", "ink"), ("symbol-reverse", "paper"),
                             ("reverse", "paper"), ("avatar-512", "paper")):
        assert fills(board_name, "Fixture accent") == {colour[key + "/accent"]["id"]}, board_name
        assert fills(board_name, "Fixture cubic") == {colour[key + "/" + base]["id"]}, board_name
    for board_name in ("symbol-mono", "monochrome"):
        assert fills(board_name, "Fixture accent") == fills(board_name, "Fixture cubic") == {colour["mono/ink"]["id"]}
    assert not s.measurements(canvas.state(), {key: palette})["violations"]
    # Contracts: tone names only the accent role, and a colour mark keeps an untoned part.
    with pytest.raises(ValueError, match="tone"):
        c.shape_contract({**concept["symbol"][1], "tone": "#FF0000"})
    with pytest.raises(ValueError, match="untoned"):
        c.concept_contract({**concept, "symbol": [concept["symbol"][1]]}, b)
    assert "tone:'accent'" in c.SCHEMA


def test_refine_gets_current_schema_and_pinned_brief_schema_stays(tmp_path):
    j = job.Job(str(tmp_path), RUN, "fixture")
    j.state["direction"] = answer(fictional=True)
    job.save(j.root / "brief.json", brief())
    job.save(j.root / "selected.json", {"concept": {}, "palette": {}})
    (j.root / "schema.txt").write_text("pinned round schema")
    j.state["files"] = {"directions": {"exports": [{"kind": "png", "path": "exports/directions-00.png"}]}}
    j.prepare_refine()
    context = json.loads((j.root / "refine-context.json").read_text())
    assert context["schema"] == "logo/schema-refine.txt" and context["schema_digest"] == c.digest(c.SCHEMA)
    assert (j.root / "schema-refine.txt").read_text() == c.SCHEMA
    assert (j.root / "schema.txt").read_text() == "pinned round schema"
    agent = (BIN.parent / "agents/design_logo_refine_v1.yaml").read_text()
    assert "the schema file it names" in agent and "tone:'accent'" in agent


def test_source_receipts_missing_text_cache_styles_geometry_rejected(canvas):
    b = brief()
    concept = job.fixture_exploration(b)["concepts"][2]
    canvas.final_boards(b, concept, job.fixture_palette(b)["shortlist"][2]["palette"])
    state = canvas.state()
    assert not s.measurements(state, {})["violations"]
    file = {**canvas.file, "revn": 1, "data": {"pages-index": {state["page_id"]: {"objects": {s.p.ROOT: {}, **{o["id"]: o for o in state["objects"]}}}},
                "colors": {v["id"]: v for v in state["colors"].values()}, "typographies": {v["id"]: v for v in state["typographies"].values()}}}
    assert all(s.source_checks(file, state)["checks"].values())
    for field in ("colors", "typographies"):
        changed = copy.deepcopy(file)
        changed["data"][field] = {}
        with pytest.raises(ValueError, match="mismatch"):
            s.source_checks(changed, state)
    changed = copy.deepcopy(file)
    text_obj = next(o for o in state["objects"] if o["type"] == "text")
    changed["data"]["pages-index"][state["page_id"]]["objects"][text_obj["id"]].pop("position-data")
    with pytest.raises(ValueError, match="native_text_cache"):
        s.source_checks(changed, state)


def test_reopen_accepts_penpot_float32_normalization_but_not_real_changes():
    expected = "M850.400000 146.000000 C869.600000 117.200000 922.400000 117.200000 941.600000 146.000000 L927.200000 210.800000 L864.800000 210.800000 Z"
    stored = ("M850.4000244140625,146.0C869.5999755859375,117.19999694824219,922.4000244140625,117.19999694824219,"
              "941.5999755859375,146.0L927.2000122070312,210.8000030517578L864.7999877929688,210.8000030517578Z")
    assert s.same_path(expected, stored)
    for bad in (stored.replace("C869", "L869"), stored.replace("117.19999", "119.2", 1), stored + "M1,1",
                stored.replace("Z", "Z<script>"), None, 5):
        assert not s.same_path(expected, bad)
    item = {"id": "c", "name": "ink", "color": "#161616"}
    assert s._same_library_item(item, {**item, "modified-at": "2026-10-03"})
    assert not s._same_library_item(item, {**item, "color": "#161617"})
    assert not s._same_library_item(item, None)


def test_receipt_identical_resume_changed_input_missing_export(tmp_path):
    j = job.Job(tmp_path, "11111111-1111-4111-8111-111111111111", "fixture")
    path = j.root / "export.svg"
    path.write_text('<svg><rect width="1"/></svg>')
    first = j.receipt("explore", "input-hash", {"status": "completed"}, [path])
    frozen = job.load(j.state_path)
    assert job.Job(tmp_path, j.run_id, "fixture").cached("explore", "input-hash") == first
    assert job.load(j.state_path) == frozen
    with pytest.raises(ValueError, match="input changed"):
        j.cached("explore", "new-hash")
    path.write_text("tampered")
    with pytest.raises(ValueError, match="changed/missing"):
        j.cached("explore", "input-hash")
    with pytest.raises(ValueError, match="another run"):
        job.Job(tmp_path, "22222222-2222-4222-8222-222222222222", "fixture")


def test_partial_identity_recovers_only_known_empty_native_file(tmp_path):
    identity = tmp_path / "pending.json"
    identity.write_text(json.dumps({"file_id": "owned", "page_id": "page", "name": "fixture"}))
    class Client:
        def get(self, file_id):
            return {"id": file_id, "name": "fixture", "revn": 0,
                    "data": {"pages-index": {"page": {"objects": {s.p.ROOT: {}}}}}}
    client = Client()
    assert job.h.recover_empty_pending(client, identity, "fixture")["id"] == "owned"
    client.get = lambda _: {"id": "owned", "name": "fixture", "revn": 1,
                           "data": {"pages-index": {"page": {"objects": {s.p.ROOT: {}, "foreign": {}}}}}}
    with pytest.raises(ValueError):
        job.h.recover_empty_pending(client, identity, "fixture")


def test_two_refinement_rounds_and_no_unguided_final_revision(tmp_path):
    j = job.Job(tmp_path, "11111111-1111-4111-8111-111111111111", "fixture")
    j.state["direction"] = answer(fictional=True)
    j.state["round"] = 2
    with pytest.raises(ValueError, match="two refinement"):
        j.prepare_refine()


@pytest.mark.parametrize("name", ["design_logo_v1", "design_logo_fixture_v1"])
def test_actual_workflow_schema_native_gates_loop_and_new_agents(name):
    raw = yaml.safe_load((BIN.parent / "workflows" / (name + ".yaml")).read_text())["workflow"]
    assert WorkflowConfig.from_dict(raw).name == name
    nodes = {v["name"]: v for v in raw["nodes"]}
    assert nodes["owner_direction"]["gate"] and nodes["owner_final"]["gate"]
    assert nodes["owner_final"]["max_loops"] == 2 and nodes["owner_final"]["on_max_loops"] == "fail"
    assert not set(raw["inputs"]) & {"direction_json", "final_json", "mode", "approval"}
    assert all(n["agent"].startswith("design_logo_") for n in nodes.values())
    order = [v["name"] for v in raw["nodes"]]
    after = order[order.index("owner_direction") + 1:]
    assert after and all(nodes[n]["condition"] == {"source": "owner_direction.structured.outcome",
                                                   "operator": "equals", "value": "selected"} for n in after)
    assert all("condition" not in nodes[n] for n in order[:order.index("owner_direction") + 1])
    assert nodes["save_revision"]["input_map"]["stage"] == "revise"
    if name == "design_logo_v1":
        assert nodes["initial_budget"]["gate"] and nodes["refine_budget"]["gate"]
        assert nodes["owner_final"]["loop_to"] == "refine_budget"
        assert raw["safety"]["policies"][0]["max_cost_usd"] == c.FULL_ESTIMATE == 8.9
        assert nodes["explore"]["input_map"] == {"phase": "draft"} and nodes["revise"]["input_map"] == {"phase": "revise"}
        assert nodes["palette"]["depends_on"] == ["save_revision"]
    else:
        assert all(n["agent"] == "design_logo_stage_v1" for n in nodes.values())
        assert all(n["input_map"]["mode"] == "fixture" for n in nodes.values())


def test_template_has_native_gate_boundary_no_secret_no_hardcoded_generation():
    stage = yaml.safe_load((BIN.parent / "agents/design_logo_stage_v1.yaml").read_text())["agent"]["script_template"]
    assert "gate is defined" in stage and "--native-gate" in stage
    assert "PENPOT_AGENT_PASSWORD" not in stage
    for name in ("explore", "palette", "critic", "refine"):
        agent = yaml.safe_load((BIN.parent / "agents" / f"design_logo_{name}_v1.yaml").read_text())["agent"]
        assert agent["provider"] == "claude" and agent["max_iterations"] == 1
    # Real exploration consumes model geometry; fixed fixtures are guarded.
    assert "c.brief_contract(brief, \"fixture\")" in (BIN / "design_logo_v1.py").read_text()


def run_native_wrapper(tmp_path, *, mode="fixture", stage="brief", workspace=None,
                       container="temper-run-11111111-1111-4111-8111-111111111111",
                       source="print('{}')\n", source_exists=True):
    """Execute only our new script code and a local non-model CLI stub."""
    from jinja2 import Environment

    agent = yaml.safe_load((BIN.parent / "agents/design_logo_stage_v1.yaml").read_text())["agent"]
    assert agent["strict_undefined"] is True
    values = {}

    def stash(value):
        key = "FIXTURE_VALUE_" + str(len(values))
        values[key] = str(value)
        return key

    env = Environment()
    env.filters["env"] = stash
    rendered = env.from_string(agent["script_template"]).render(
        stage=stage, mode=mode, workspace_path=str(tmp_path) if workspace is None else workspace,
        brief_json="{}", budget_json="{}",
    )
    body = rendered.split("<<'PYEOF'\n", 1)[1].rsplit("\nPYEOF", 1)[0]
    stub = tmp_path / "native_cli_stub.py"
    if source_exists:
        stub.write_text(source)
    body = body.replace("/app/configs/design/bin/design_logo_v1.py", str(stub))
    driver = tmp_path / "wrapper.py"
    driver.write_text(body)
    result = subprocess.run([sys.executable, str(driver)], capture_output=True, text=True,
                            env={**os.environ, **values, "TEMPER_RUN_CONTAINER": container}, timeout=10)
    receipts = list((tmp_path / "logo-native-diagnostics").glob("*.json"))
    return result, [json.loads(p.read_text()) for p in receipts]


@pytest.mark.parametrize("options,code", [
    ({"container": ""}, 21),
    ({"container": "temper-run-invalid"}, 22),
    ({"workspace": "relative"}, 23),
    ({"mode": "unknown"}, 24),
    ({"stage": "arbitrary"}, 25),
    ({"stage": "direction"}, 27),
])
def test_native_wrapper_public_preflight_codes_no_artifact_or_gate_bypass(tmp_path, options, code):
    result, receipts = run_native_wrapper(tmp_path, **options)
    assert result.returncode == code
    assert not receipts and not (tmp_path / "logo").exists()
    assert not result.stdout and not result.stderr


def test_native_wrapper_missing_source_has_only_public_receipt(tmp_path):
    result, receipts = run_native_wrapper(tmp_path, source_exists=False)
    assert result.returncode == 29
    assert receipts[-1]["category"] == "native_source_unavailable"
    assert receipts[-1]["source_available"] is False
    assert not (tmp_path / "logo").exists()


def test_native_wrapper_failure_never_preserves_private_output(tmp_path):
    source = "import sys\nsys.stderr.write('PermissionError: private-sentinel\\n')\nraise SystemExit(1)\n"
    result, receipts = run_native_wrapper(tmp_path, source=source)
    assert result.returncode == 36
    assert receipts[-1]["category"] == "filesystem_permission_denied"
    assert "private-sentinel" not in json.dumps(receipts) + result.stdout + result.stderr
    assert not set(receipts[-1]) & {"stdout", "stderr", "env", "raw", "brief_json", "budget_json"}


def test_native_wrapper_success_preserves_native_json_and_source_identity(tmp_path):
    result, receipts = run_native_wrapper(tmp_path)
    assert result.returncode == 0 and json.loads(result.stdout) == {}
    assert receipts[-1]["category"] == "native_command_completed"
    assert receipts[-1]["run_id"] == "11111111-1111-4111-8111-111111111111"
    assert receipts[-1]["isolated_identity_verified"] is True
    assert receipts[-1]["mode"] == "fixture" and receipts[-1]["stage"] == "brief"
