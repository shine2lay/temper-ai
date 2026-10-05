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


def extra_round_job(tmp_path, **change):
    """A real-mode job after round 2, with the owner's round-2 final answer as the gate wrote it."""
    j = job.Job(str(tmp_path), RUN, "real")
    j.state.update({"round": 2, "brief_hash": "b", "final_artifact_hash": "a2",
                    "direction": {**answer(), "run_id": RUN, "owner_note": "Round-1 note."},
                    "final_feedback": {**answer("final"), "decision": "revise", "owner_note": "Round-1 final note."},
                    "files": {f"selected-r{n:02}": {"exports": [{"kind": "png", "path": f"exports/selected-r{n:02}-00.png"},
                                                             {"kind": "svg", "path": f"exports/selected-r{n:02}-00.svg"}]}
                              for n in (1, 2)}})
    job.save(j.root / "brief.json", brief())
    job.save(j.root / "selected.json", {"concept": {}, "palette": {}})
    record = {"approval": "owner-final", "run_id": RUN, "brief_hash": "b", "artifact_hash": "a2", "decision": "revise",
              "reason": "Owner answer (test).", "owner_note": "Make the base shorter.", "recorded_at": "t",
              "fictional_test": False, **change}
    job.save(j.root / "owner-final-r02.json", {k: v for k, v in record.items() if v is not None})
    j.commit()
    return j


def extra_budget(note="Make the base shorter."):
    return json.dumps({**reservation(), "extra_round_owner_note": note})


@pytest.mark.parametrize("change,payload", [
    ({}, json.dumps(reservation())),                        # budget answer does not name the request
    ({}, extra_budget("Something else.")),                  # names a different note
    ({"decision": "approve"}, extra_budget()),              # owner approved, nothing to revise
    ({"owner_note": None}, extra_budget(None)),             # revise without the owner's own words
    ({"approval": "fixture-test"}, extra_budget()),         # fictional answer
    ({"fictional_test": True}, extra_budget()),
    ({"artifact_hash": "a1"}, extra_budget()),              # answer about other artwork
    ({"run_id": "22222222-2222-4222-8222-222222222222"}, extra_budget()),
])
def test_extra_round_needs_owner_revise_note_and_named_budget(tmp_path, change, payload):
    j = extra_round_job(tmp_path, **change)
    with pytest.raises(ValueError):
        j.budget(payload, "refine")
    assert "extra_round" not in j.state
    with pytest.raises(ValueError, match="two refinement"):
        j.prepare_refine()


def test_owner_requested_extra_round_runs_once_on_their_note_and_last_boards(tmp_path):
    j = extra_round_job(tmp_path)
    (j.root / "owner-final-r02.json").unlink()
    with pytest.raises(ValueError, match="no owner request"):
        j.budget(extra_budget(), "refine")
    j = extra_round_job(tmp_path)
    assert j.budget(extra_budget(), "refine")["round"] == 3
    assert job.Job(str(tmp_path), RUN, "real").state["extra_round"]["owner_note"] == "Make the base shorter."
    j.prepare_refine()
    context = json.loads((j.root / "refine-context.json").read_text())
    assert context["round"] == 3 and context["owner_note"] == "Make the base shorter."
    assert context["pngs"] == ["exports/selected-r02-00.png"] and context["critic"] == "logo/critic-r02.json"
    # Never a fourth round, whatever the owner record says.
    j.state["round"] = 3
    j.commit()
    with pytest.raises(ValueError, match="exhausted"):
        j.prepare_refine()
    job.save(j.root / "owner-final-r03.json", json.loads((j.root / "owner-final-r02.json").read_text()))
    with pytest.raises(ValueError, match="exhausted"):
        j.budget(extra_budget(), "refine")


def test_round_two_refinement_still_reads_round_one_boards_and_note(tmp_path):
    j = extra_round_job(tmp_path)
    j.state["round"] = 1
    j.prepare_refine()
    context = json.loads((j.root / "refine-context.json").read_text())
    assert context["round"] == 2 and context["owner_note"] == "Round-1 final note."
    assert context["pngs"] == ["exports/selected-r01-00.png"]


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
        assert raw["safety"]["policies"][0]["max_cost_usd"] == c.FULL_ESTIMATE == 11.6
        assert nodes["explore"]["input_map"] == {"phase": "draft"} and nodes["revise"]["input_map"] == {"phase": "revise"}
        # Caption-free cold read and same-name check before the shortlist, and again before each selected critic.
        assert nodes["cold_read"]["agent"] == "design_logo_coldread_v1" and nodes["name_check"]["agent"] == "design_logo_names_v1"
        assert nodes["cold_read"]["depends_on"] == nodes["name_check"]["depends_on"] == ["save_revision"]
        assert nodes["save_cold_read"]["depends_on"] == ["cold_read", "name_check"]
        assert nodes["palette"]["depends_on"] == ["save_cold_read"]
        assert nodes["selected_cold_read"]["agent"] == "design_logo_coldread_v1"
        assert nodes["selected_cold_read"]["depends_on"] == nodes["selected_name_check"]["depends_on"] == ["save_refine"]
        assert nodes["save_selected_cold_read"]["depends_on"] == ["selected_cold_read", "selected_name_check"]
        assert nodes["selected_critic"]["depends_on"] == ["save_refine", "save_selected_cold_read"]
    else:
        assert all(n["agent"] == "design_logo_stage_v1" for n in nodes.values())
        assert all(n["input_map"]["mode"] == "fixture" for n in nodes.values())
        assert nodes["save_cold_read"]["depends_on"] == ["save_revision"]
        assert nodes["save_palette"]["depends_on"] == ["save_cold_read"]
        assert nodes["save_selected_critic"]["depends_on"] == ["save_selected_cold_read"]
    assert nodes["save_cold_read"]["input_map"]["stage"] == nodes["save_selected_cold_read"]["input_map"]["stage"] == "coldread"


def test_template_has_native_gate_boundary_no_secret_no_hardcoded_generation():
    stage = yaml.safe_load((BIN.parent / "agents/design_logo_stage_v1.yaml").read_text())["agent"]["script_template"]
    assert "gate is defined" in stage and "--native-gate" in stage
    assert "PENPOT_AGENT_PASSWORD" not in stage
    for name in ("explore", "palette", "critic", "refine", "coldread", "names"):
        agent = yaml.safe_load((BIN.parent / "agents" / f"design_logo_{name}_v1.yaml").read_text())["agent"]
        assert agent["provider"] == "claude" and agent["max_iterations"] == 1
    # Real exploration consumes model geometry; fixed fixtures are guarded.
    assert "c.brief_contract(brief, \"fixture\")" in (BIN / "design_logo_v1.py").read_text()


# Queue #11 (2026-10-04): size check, cold read and same-name check, contract plant A.
# Task #4 (run ad5c270f) found small-size loss and misreadings only through the critic or the owner.

size_check = importlib.import_module("logo_size_check")
SYMBOLS = json.loads((Path(__file__).parent / "design_logo_data/temper-logo-symbols.json").read_text())
ANVIL = next(x for x in SYMBOLS["concepts"] if x["id"] == "approved-anvil")


def size_rows(concepts=None, **kwargs):
    return {r["id"]: r for r in size_check.check(concepts or SYMBOLS["concepts"], **kwargs)["symbols"]}


def test_size_check_flags_round_two_details_that_vanished_at_16_px():
    """Task #4: only the critic saw the fork arcs, the Dovetail T seam and the Keystone seams vanish at 16 px."""
    rows = size_rows()
    fork = rows["ringing-fork"]["failing"]["16"]
    for arc in ("left echo arc", "right echo arc"):
        assert f'width of "{arc}": 5.336 units = 0.85 px at 16 px' in fork
        assert any(f.startswith(f'seam between "fork tines and stem" and "{arc}"') for f in fork)
    assert rows["dovetail-t"]["failing"]["16"] == [
        'seam between "crossbar with dovetail socket" and "stem with flared dovetail tail" at 28.3,22: '
        "6 units = 0.96 px at 16 px"]
    keystone = rows["keystone-gate"]["failing"]["16"]
    for half in ("left half of gateway", "right half of gateway"):
        assert any(f.startswith(f'seam between "{half}" and "keystone"') and "0.95 px" in f for f in keystone)
    for ident in ("ringing-fork", "dovetail-t", "keystone-gate"):
        row = rows[ident]
        assert row["minimum_px"] == 24 and row["failing"]["24"] == [] and row["clear_from_px"] == 48
        assert 16 < row["exact_minimum_px"] < 24 and "fails at 16 px" in row["summary"]


def test_size_check_reports_the_approved_anvil_as_its_brand_sheet_does():
    """Owner-approved packet BRAND.md: symbol minimum 24 px; the dovetail reads from about 48 px."""
    row = size_rows()["approved-anvil"]
    assert (row["minimum_px"], row["exact_minimum_px"], row["claim_px"]) == (24, 20.0, 24)
    assert (row["clear_from_px"], row["exact_clear_from_px"]) == (48, 40.0)
    seam = next(f for f in row["features"] if f["kind"] == "seam")
    assert seam["units"] == 5.0 and seam["px"] == {"16": 0.8, "24": 1.2, "32": 1.6, "48": 2.4}
    assert len(row["failing"]["16"]) == 2 and not row["failing"]["24"]
    assert "at least 1 px from 24px and at least 2 px from 48px" in size_check.board_note(row)


@pytest.mark.parametrize("shape", [{"kind": "rect", "name": "solid square", "x": 10, "y": 10, "w": 80, "h": 80},
                                   {"kind": "ellipse", "name": "solid circle", "x": 10, "y": 10, "w": 80, "h": 80}])
def test_size_check_passes_a_solid_control_at_16_px(shape):
    row = size_rows([{"id": "control", "symbol": [shape], "minimum_symbol_px": 16}])["control"]
    assert row["minimum_px"] == 16 and row["claim_px"] == 16 and row["failing"]["16"] == []
    assert [f["kind"] for f in row["features"]] == ["width"] and row["features"][0]["units"] > 79.9
    assert row["summary"].endswith("passes at 16 px")


def test_size_check_is_honest_and_its_floor_configurable():
    """Never rounded up to pass, never a smaller claim than measured; too thin everywhere says so."""
    assert "0.96 px at 16 px" in size_rows()["dovetail-t"]["failing"]["16"][0]
    low = size_rows([{**ANVIL, "minimum_symbol_px": 16}])["approved-anvil"]
    assert low["claim_px"] == 24
    assert "The concept declared 16px; the measurement sets the minimum." in size_check.board_note(low)
    assert size_rows([ANVIL], floor_px=2.0, clear_px=2.0)["approved-anvil"]["minimum_px"] == 48
    loose = size_rows([ANVIL], floor_px=0.5)["approved-anvil"]
    assert loose["minimum_px"] == 16 and loose["claim_px"] == 24  # the declared 24 still stands
    hair = size_rows([{"id": "hair", "minimum_symbol_px": 24,
                       "symbol": [{"kind": "rect", "name": "hairline", "x": 10, "y": 49, "w": 80, "h": 1}]}])["hair"]
    assert hair["minimum_px"] is None and hair["claim_px"] == 100
    assert hair["summary"].startswith("not present at any checked size")
    for floor, clear in ((0, 2), (3, 2), (1, 9)):
        with pytest.raises(ValueError, match="thresholds"):
            size_check.check([ANVIL], floor_px=floor, clear_px=clear)


def test_cold_read_schema_three_distinct_readings_per_symbol_and_size():
    labels = ["S1", "S2"]
    good = {"readings": [{"label": s, "glance_32": [f"a letter T {s}", f"a hammer {s}", f"a stool {s}"],
                          "close_128": [f"an anvil {s}", f"a letter T {s}", f"a table {s}"]} for s in labels]}
    out = c.readings_contract({"readings": copy.deepcopy(good["readings"][::-1])}, labels)
    assert [r["label"] for r in out["readings"]] == labels
    one, two = good["readings"]
    for rows in ([one], [one, two, one], [{**one, "label": "S9"}, two], [{**one, "glance_32": one["glance_32"][:2]}, two],
                 [{**one, "close_128": ["a T", "A t.", "a table"]}, two], [{**one, "intended": "an anvil"}, two]):
        with pytest.raises(ValueError):
            c.readings_contract({"readings": copy.deepcopy(rows)}, labels)
    with pytest.raises(ValueError):
        c.readings_contract({**copy.deepcopy(good), "product": "Northline"}, labels)
    long = copy.deepcopy(good)
    long["readings"][0]["glance_32"][0] = "a very long reading " * 6
    shortened = c.readings_contract(long, labels)["readings"][0]["glance_32"][0]
    assert len(shortened) <= 80 and shortened.endswith("\u2026")


def test_name_check_schema_pairs_every_lockup_with_every_same_name_mark():
    labels, marks = ["S1", "S2"], ["peer-a.png", "peer-b.png"]
    rows = [{"label": s, "mark": m, "close": (s, m) == ("S1", "peer-a.png"), "why": "Similar arch."}
            for s in labels for m in marks]
    assert len(c.names_contract({"resemblance": copy.deepcopy(rows)}, labels, marks)["resemblance"]) == 4
    assert c.names_contract({"resemblance": []}, labels, []) == {"resemblance": []}
    for bad in (rows[:3], rows + rows[:1], [{**rows[0], "mark": "other.png"}] + rows[1:],
                [{**rows[0], "close": "yes"}] + rows[1:], [{**rows[0], "score": 3}] + rows[1:]):
        with pytest.raises(ValueError):
            c.names_contract({"resemblance": copy.deepcopy(bad)}, labels, marks)


def cold_of(ids, close=("fixture-0",), mark="peer-a.png"):
    """A saved cold read as the contracts take it: {id: {readings, close}}."""
    return {i: {"readings": [{"size": "32", "reading": f"{i} glance {n}"} for n in "abc"] +
                            [{"size": "128", "reading": f"{i} close {n}"} for n in "abc"],
                "close": [mark] if i in close else []} for i in ids}


def test_shortlist_and_critic_must_quote_every_first_reading_and_close_name_flag():
    b = brief()
    concepts = c.exploration_contract(job.fixture_exploration(b), b)["concepts"]
    cold = cold_of([x["id"] for x in concepts])
    good = job.fixture_palette(b, cold)
    first = c.shortlist_contract(copy.deepcopy(good), b, concepts, cold)["shortlist"][0]
    assert [r["reading"] for r in first["first_reads"]] == [r["reading"] for r in cold["fixture-0"]["readings"]]
    assert first["name_marks"] == [{"mark": "peer-a.png", "note": "Fixture flag only; not evidence."}]
    assert c.shortlist_contract(job.fixture_palette(b), b, concepts)  # rows of runs before the cold read
    with pytest.raises(ValueError, match="unexpected or missing"):
        c.shortlist_contract(job.fixture_palette(b), b, concepts, cold)

    def broken(change):
        bad = copy.deepcopy(good)
        change(bad["shortlist"][0])
        return bad

    numbers = broken(lambda row: [r.update(size=int(r["size"])) for r in row["first_reads"]])
    assert c.shortlist_contract(numbers, b, concepts, cold)["shortlist"][0]["first_reads"][0]["size"] == "32"
    for change in (lambda row: row["first_reads"].pop(),                                # a reading left out
                   lambda row: row["first_reads"][0].update(reading="an anvil"),        # a reading changed
                   lambda row: row["first_reads"].append(dict(row["first_reads"][0])),  # quoted twice
                   lambda row: row["first_reads"][0].update(size="128"),                # wrong size
                   lambda row: row["first_reads"][0].update(fits_idea="yes"),
                   lambda row: row["name_marks"].clear(),                               # close flag dropped
                   lambda row: row["name_marks"].append({"mark": "peer-b.png", "note": "x"})):
        with pytest.raises(ValueError):
            c.shortlist_contract(broken(change), b, concepts, cold)
    with pytest.raises(ValueError, match="no saved cold read"):
        c.shortlist_contract(copy.deepcopy(good), b, concepts, {k: v for k, v in cold.items() if k != "fixture-1"})
    reads, marks = job.fixture_first_reads(cold, "fixture-0", with_id=True)
    review = {"product": b["product"], "observations": [], "recommendation": "fixture-0",
              "recommendation_reason": "Advice only.", "limitations": "Static PNGs.", "first_reads": reads, "name_marks": marks}
    assert c.critique_contract(copy.deepcopy(review), b, {"fixture-0"}, cold)["first_reads"][0]["id"] == "fixture-0"
    for change in ({"first_reads": reads[1:]}, {"name_marks": []},
                   {"first_reads": [{**reads[0], "id": "fixture-1"}] + reads[1:]}):
        with pytest.raises(ValueError):
            c.critique_contract({**copy.deepcopy(review), **change}, b, {"fixture-0"}, cold)
    with pytest.raises(ValueError, match="unexpected or missing"):
        c.critique_contract({k: v for k, v in copy.deepcopy(review).items() if k not in ("first_reads", "name_marks")},
                            b, {"fixture-0"}, cold)


def test_contract_plant_a_is_measured_after_its_edit(canvas):
    """Task #4: the critic saw 'Ast' while the measurement, taken before the edit, said 'Aster' fits."""
    canvas.contract_board()
    facts = s.measurements(canvas.state(), {})
    a = next(r for r in facts["text"] if r["name"] == "Wordmark/A")
    assert (a["content_text"], a["rendered_text"], a["final_width"]) == ("Aster", "Ast", 50)
    assert not a["rendered_matches_content"] and not a["advance_fit"]
    assert {r["name"] for r in facts["violations"]} == {"Wordmark/A", "Companion C"}  # D exempt, E clean
    assert facts["measured_from"].startswith("final saved objects")


def offline_native(monkeypatch):
    """Stand-in for Penpot save/reopen/export: the same canvas, placeholder PNGs, no service."""
    monkeypatch.setattr(s.p, "FontMetrics", Font)

    def native_file(self, label, build, kinds=("png", "svg")):
        assets = self.root / "assets"
        assets.mkdir(exist_ok=True)
        for variant in ("regular", "semibold"):
            (assets / f"sourcesanspro-{variant}.ttf").write_bytes(b"test")
        file = {"id": s.p.nid(), "team-id": s.p.nid(), "project-id": s.p.nid(), "name": label, "data": {"pages": [s.p.nid()]}}
        canvas = s.LogoCanvas(file, assets, job.load(self.root / "brief.json")["product"])
        build(canvas)
        state = canvas.state()
        exports = []
        for i, board in enumerate(state["boards"]):
            for kind in kinds:
                path = self.root / "exports" / f"{label}-{i:02}.{kind}"
                path.parent.mkdir(exist_ok=True)
                path.write_bytes(job.PNG + label.encode() + bytes([i]))
                exports.append({"path": str(path.relative_to(self.root.parent)), "board": board["name"], "kind": kind,
                                "width": board["width"], "height": board["height"]})
        job.save(self.root / (label + ".source.json"), state)
        job.save(self.root / (label + ".exports.json"), exports)
        self.state["files"][label] = {"file_id": state["file_id"], "exports": exports, "url": "offline://" + label}
        self.commit()
        return state, exports

    monkeypatch.setattr(job.Job, "native_file", native_file)


def test_cold_read_is_caption_free_and_reaches_shortlist_and_critic(tmp_path, monkeypatch):
    offline_native(monkeypatch)
    files = {"comparison.md": "0" * 64, "peer-a.png": "1" * 64}
    b = c.brief_contract({**brief(), "research": {"dir": "/research", "files": files, "same_name": ["peer-a.png"]}}, "fixture")
    j = job.Job(str(tmp_path), RUN, "fixture")
    job.save(j.root / "brief.json", b)
    j.state["brief_hash"] = c.digest(b)
    assert j.adopt_exploration()["size"] == "logo/roughs.size.json"
    out = j.adopt_revision()
    assert out["size"] == "logo/sketches.size.json" and out["coldread_context"] == "logo/coldread-context.json"
    context, names = job.load(j.root / "coldread-context.json"), job.load(j.root / "names-context.json")
    labels = context["labels"]
    assert labels == [f"S{i}" for i in range(1, 7)] and set(context) == {"labels", "glance_32", "close_128", "output"}
    assert context["glance_32"] == [f"logo/coldread-sketches/{x}-32.png" for x in labels]
    assert context["close_128"] == [f"logo/coldread-sketches/{x}-128.png" for x in labels]
    assert names["header_32"] == [f"logo/coldread-sketches/{x}-header.png" for x in labels]
    assert names["same_name"] == ["logo/research/peer-a.png"]
    assert all((j.root.parent / p).is_file() for p in context["glance_32"] + context["close_128"] + names["header_32"])
    # Nothing tells the reader what a symbol is: no id, name or product, and no text on its boards.
    concepts, shown = job.load(j.root / "sketches.saved.json")["concepts"], json.dumps(context)
    assert not any(x["id"] in shown or x["name"] in shown for x in concepts) and "Northline" not in shown
    mapping = j.state["cold"]["sketches"]["labels"]
    assert sorted(mapping.values()) == sorted(x["id"] for x in concepts)
    assert list(mapping.values()) != [x["id"] for x in concepts]  # seeded shuffle, not the board order
    source_state = job.load(j.root / "coldread-sketches.source.json")
    boards = {bd["id"]: bd["name"] for bd in source_state["boards"]}
    texts = [o for o in source_state["objects"] if o["type"] == "text"]
    assert texts and all(boards[o["frame-id"]].endswith(" header") for o in texts)
    # Saved readings map the neutral labels back to ids.
    j.adopt_cold_read()
    saved = job.load(j.root / "coldread-sketches.saved.json")
    assert set(saved["symbols"]) == set(mapping.values()) and saved["fictional_test"] is True
    assert saved["symbols"][mapping["S1"]]["close"] == ["peer-a.png"] and len(saved["symbols"][mapping["S1"]]["readings"]) == 6
    # The shortlist quotes them; its actual-size boards print the measured minimum.
    j.adopt_palette()
    rows = job.load(j.root / "palette.saved.json")["shortlist"]
    for row in rows:
        assert [r["reading"] for r in row["first_reads"]] == [r["reading"] for r in saved["symbols"][row["id"]]["readings"]]
    notes = [m["text"] for m in job.load(j.root / "directions.measurements.json")["text"] if m["name"] == "Size limitation"]
    assert len(notes) == 3 and all(n.startswith("Symbol minimum: ") for n in notes)
    # The critic's review quotes every reading of every shortlisted id.
    j.adopt_critic()
    review = job.load(j.root / "critic-r00.json")
    assert {r["id"] for r in review["first_reads"]} == {r["id"] for r in rows} and len(review["first_reads"]) == 18
    # A real shortlist that skips the comparison is refused.
    j.mode = "real"
    job.save(j.root / "palette.json", job.fixture_palette(b))
    with pytest.raises(ValueError, match="unexpected or missing"):
        j.adopt_palette()


def test_agents_cold_reader_sees_images_only_and_shortlist_and_critic_quote_it():
    agents = {n: json.dumps(yaml.safe_load((BIN.parent / "agents" / f"design_logo_{n}_v1.yaml").read_text())["agent"])
              for n in ("coldread", "names", "palette", "critic", "refine", "explore")}
    assert "logo/coldread-context.json" in agents["coldread"]
    assert "no caption, brief, product name or intended idea" in agents["coldread"]
    for hidden in ("brief.json", "saved.json", "palette", "names-context", "comparison.md", "header", "research"):
        assert hidden not in agents["coldread"], hidden
    assert "logo/names-context.json" in agents["names"] and "not a trademark search" in agents["names"]
    # The name check reads the run's research notes on each same-name mark: without them
    # it missed both known ontemper.com cases (queue #11 replays A and D).
    assert "logo/research/comparison.md" in agents["names"] and "a colour difference does not undo a shared shape" in agents["names"]
    for name in ("palette", "critic"):
        for expected in ("first_reads", "name_marks", ".size.json", "coldread-"):
            assert expected in agents[name], (name, expected)
    assert "roughs.size.json" in agents["explore"] and "cold_read" in agents["refine"]


def test_refined_size_claim_reaches_boards_tokens_and_brand_sheet(tmp_path, monkeypatch):
    """The packet claims the measured minimum when the concept declared a smaller one."""
    offline_native(monkeypatch)
    b = brief()
    concept = {**job.fixture_exploration(b)["concepts"][2], "symbol": ANVIL["symbol"], "minimum_symbol_px": 16}
    palette = job.fixture_palette(b)["shortlist"][2]["palette"]
    j = job.Job(str(tmp_path), RUN, "fixture")
    job.save(j.root / "brief.json", b)
    job.save(j.root / "selected.json", {"concept": concept, "palette": palette})
    j.state.update(brief_hash=c.digest(b), direction={**answer(fictional=True), "run_id": RUN})
    j.state["files"]["directions"] = {"exports": [{"kind": "png", "path": "logo/exports/directions-00.png"}]}
    j.commit()
    j.prepare_refine()
    out = j.adopt_refine()
    assert out["minimum_px"] == 24 and out["size"] == "logo/selected-r01.size.json"
    note = next(m["text"] for m in job.load(j.root / "selected-r01.measurements.json")["text"] if m["name"] == "Size limitation")
    assert note.startswith("Symbol minimum: 24px.")
    assert job.load(j.root / "coldread-context.json")["labels"] == ["S1"]
    j.adopt_cold_read()
    assert set(job.load(j.root / "coldread-r01.saved.json")["symbols"]) == {"fixture-2"}

    class Fresh:
        def login(self):
            pass

        def get(self, file_id):
            return {"id": file_id}

    monkeypatch.setattr(job.h, "Penpot", Fresh)
    monkeypatch.setattr(job.source, "source_checks", lambda file, state: {"revn": 1, "checks": {"offline": True}})
    job.save(j.root / "critic-r01.json", {"fixture": True})
    j.handoff()
    tokens = job.load(j.root / "tokens.json")
    assert (tokens["minimum_symbol_px"], tokens["declared_minimum_symbol_px"]) == (24, 16)
    assert tokens["measured_size"] == {"minimum_px": 24, "exact_minimum_px": 20.0, "clear_from_px": 48, "exact_clear_from_px": 40.0}
    brand = (j.root / "BRAND.md").read_text()
    assert "Symbol minimum: 24px." in brand and "The concept declared 16px; the measurement sets the minimum." in brand


def fixture_round_two(path, **change):
    """A fixture job after round 2, with the fictional round-2 final answer as final() saved it."""
    j = job.Job(str(path), RUN, "fixture")
    j.state.update({"round": 2, "brief_hash": "b", "final_artifact_hash": "a2",
                    "direction": {**answer(fictional=True), "run_id": RUN},
                    "files": {"selected-r02": {"exports": [{"kind": "png", "path": "logo/exports/selected-r02-00.png"}]}}})
    job.save(j.root / "brief.json", brief())
    job.save(j.root / "selected.json", {"concept": {}, "palette": {}})
    record = {"approval": "fixture-test", "run_id": RUN, "brief_hash": "b", "artifact_hash": "a2", "decision": "revise",
              "reason": "Fixture answer.", "owner_note": "Fixture: shorter base.", "fictional_test": True, **change}
    job.save(j.root / "owner-final-r02.json", record)
    j.commit()
    return j


@pytest.mark.parametrize("change", [{"owner_note": ""}, {"artifact_hash": "a1"}, {"fictional_test": False},
                                    {"decision": "approve"}, {"run_id": "other"}, {"approval": "owner-final"}])
def test_fixture_extra_round_needs_its_own_fictional_revise_note(tmp_path, change):
    with pytest.raises(ValueError, match="two refinement"):
        fixture_round_two(tmp_path, **change).prepare_refine()


def test_fixture_extra_round_runs_once_like_the_real_one(tmp_path):
    j = fixture_round_two(tmp_path)
    j.prepare_refine()
    context = job.load(j.root / "refine-context.json")
    assert context["round"] == 3 and context["owner_note"] == "Fixture: shorter base."
    assert context["pngs"] == ["logo/exports/selected-r02-00.png"] and j.state["extra_round"]["fictional_test"] is True
    j.state["round"] = 3
    j.commit()
    with pytest.raises(ValueError, match="exhausted"):
        j.prepare_refine()


def test_replay_rechecks_saved_symbols_and_nothing_else(tmp_path, monkeypatch):
    offline_native(monkeypatch)
    j = job.Job(str(tmp_path), RUN, "replay")
    job.save(j.root / "brief.json", c.brief_contract(brief(fictional=False), "real"))
    concepts = job.fixture_exploration(brief())["concepts"][:2]
    out = j.adopt_replay(json.dumps({"concepts": concepts, "source": "fixture symbols (test)"}))
    assert out["symbols"] == 2 and out["size"] == "logo/replay.size.json"
    assert job.load(j.root / "coldread-context.json")["labels"] == ["S1", "S2"]
    for stage in (j.adopt_exploration, j.adopt_palette, j.adopt_critic, j.prepare_refine, j.handoff):
        with pytest.raises(ValueError, match="not allowed"):
            stage()
    with pytest.raises(ValueError, match="not allowed"):
        j.budget(json.dumps(reservation()), "initial")
    for bad in ({"concepts": [], "source": "x"}, {"concepts": concepts + concepts[:1], "source": "x"},
                {"concepts": concepts, "source": "x", "extra": 1}):
        with pytest.raises(ValueError):
            j.adopt_replay(json.dumps(bad))
    raw = yaml.safe_load((BIN.parent / "workflows/design_logo_replay_v1.yaml").read_text())["workflow"]
    assert WorkflowConfig.from_dict(raw).name == "design_logo_replay_v1"
    nodes = {v["name"]: v for v in raw["nodes"]}
    assert not any(n.get("gate") for n in nodes.values()) and raw["safety"]["policies"][0]["max_cost_usd"] <= 2
    assert {n["input_map"]["mode"] for n in nodes.values() if n["agent"] == "design_logo_stage_v1"} == {"replay"}
    assert nodes["save_cold_read"]["depends_on"] == ["cold_read", "name_check"]


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
