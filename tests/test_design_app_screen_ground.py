"""design_app_screen_v1 stage 3, ground (Design #210): the host's prep (capability map, knowledge files, the shared
fixture), the source items, the fixture's invariants, the measured checks around the model step, the stage's
script steps and the trial grader.

Each check is shown one good fixed model output and broken copies of it. The app, screens and words here are
invented test data (the repository is public); the real cases (RollCall at a pinned commit, a planted app and its
clean twin) live in the lab (~/design-lab/app-screen-workflow/known-cases/ground/).
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "configs/design/bin"
sys.path.insert(0, str(BIN))
sys.path.insert(0, str(ROOT / "configs/epd/bin"))

import capabilities  # noqa: E402
from app_screen import (  # noqa: E402
    contracts,
    ground,
    ground_check,
    ground_fixture,
    ground_grade,
    ground_host,
    ground_sources,
    ground_task,
    product_app,
    stored_copy,
)
from app_screen.product_store import ProductStore  # noqa: E402
from app_screen.workspace import Workspace  # noqa: E402

MAP = """# What demo can do

<!-- temper:capabilities v1 -->

5 capabilities, 4 described.

## HTTP API (3)

### plants

- `GET /api/plants` — Every plant and when it needs water. · `server/plants.js:3`
- `POST /api/plants/{id}/water` — Marks a plant watered; refused with too_soon within an hour of the last time. · `server/plants.js:9`

### dev

- `POST /api/dev/reset` — _(undescribed)_ · `server/dev.js:2`

## Pages (2)

- `/` — Today's plants to water first, then the rest. · `web/routes.js:4`
- `/plants/:id` — One plant: its watering history. · `web/routes.js:5`
"""
NOTES = "# Plants\n\nThe water button is greyed while a plant is too soon to water.\n"
FIXTURE = {"states": ["normal", "loading"],
           "plants": [{"name": "Fern", "water": "today"}, {"name": "Basil", "water": "tomorrow"}],
           "today": {"plant": {"name": "Fern", "water": "today"}},
           "counts": {"total": 2, "today": 1, "later": 1}}
INVARIANTS = {"same_value": [{"key": "name", "field": "water"}],
              "totals": [{"total": "counts.total", "plus": ["counts.today", "counts.later"]}]}
SIZES = {"390": {"height": 844, "phone": True}, "1440": {"height": 900, "phone": False}}
APP_FILE = {
    "product": "demo", "name": "Demo", "job": "Demo shows a gardener which plants need water today.",
    "page": {"main": "main", "key_regions": {"main_status": "#status"}},
    "sizes": SIZES, "sheet_width": 390,
    "screens": [{"id": "home", "name": "Home", "route": "/index.html", "widths": [390, 1440],
                 "states": {"normal": {"what": "today"}}}],
    "capabilities": "sources/capabilities.md", "notes": ["sources/plants.md"],
    "fixture": {"file": "sources/fixture.json", "parts": "sources/parts", "invariants": INVARIANTS},
}
APP_JSON = {"product": "demo", "name": "Demo", "job": APP_FILE["job"], "sheet_width": 390, "sizes": SIZES,
            "screens": [{"id": "home", "name": "Home",
                         "states": {"normal": {"what": "today's plants", "widths": [390, 1440]}}}]}
REQUIREMENTS = {"source": "test", "items": [
    {"id": "R1", "item": "S1", "owner_words": "show what needs water first", "kind": "goal",
     "means": "The plants to water today come first.", "maps_to": ["home"]},
    {"id": "R2", "item": "S2", "owner_words": "I want to see each plant's history", "kind": "feature",
     "maps_to": ["plant"]}]}
JOURNEYS = {"source": "test", "journeys": [{"id": "J1", "name": "Water today", "goal": "Know what to water",
                                            "screens": ["home"], "problems": []}]}
QUESTIONS = {"questions": [{"id": "Q1", "question": "Is a missed day shown?", "status": "open"}]}
TEXTS = {"home-390-normal": {"first_view": ["Fern"], "all": ["Fern", "Water  now", "2", "Fern"]},
         "home-1440-normal": {"first_view": ["Fern"], "all": ["Fern", "Basil later", "$4.00"]}}
AUDIT = {"source": "test", "product": "demo", "screens": [
    {"id": "home-390-normal", "screen": "home", "state": "normal", "width": 390},
    {"id": "home-1440-normal", "screen": "home", "state": "normal", "width": 1440}]}

GOOD = {
    "screens": [
        {"id": "today", "name": "Today", "sources": ["page:/", "screen:home", "req:R1", "journey:J1"],
         "states": [{"name": "normal"}, {"name": "loading"}, {"name": "empty"}, {"name": "error"},
                    {"name": "partial"}],
         "shows": [{"what": "plants to water today", "sources": ["api:GET /api/plants"]}],
         "actions": [{"id": "water", "what": "mark a plant watered", "states": ["pending", "done", "error", "too-soon"],
                      "sources": ["api:POST /api/plants/{id}/water", "note:plants#L3"]}]},
        {"id": "plant", "name": "Plant history", "sources": ["page:/plants/:id", "req:R2"],
         "states": [{"name": "normal"}, {"name": "loading"}, {"name": "empty"}, {"name": "error"},
                    {"name": "partial"}, {"name": "never-watered", "sources": ["page:/plants/:id"]}]},
    ],
    "excluded": [{"source": "api:POST /api/dev/reset", "reason": "a developer reset, no user sees it"}],
}


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")


@pytest.fixture
def store(tmp_path):
    folder = tmp_path / "products" / "demo"
    _write(folder / "app.yaml", yaml.safe_dump(APP_FILE))
    _write(folder / "sources/capabilities.md", MAP)
    _write(folder / "sources/plants.md", NOTES)
    _write(folder / "sources/fixture.json", FIXTURE)
    _write(folder / "sources/parts/watering.json", {"log": [{"name": "Fern", "water": "today", "on": "Mon"}]})
    return tmp_path / "products"


def _stage_inputs(folder: Path) -> None:
    _write(folder / "01-request/requirements.json", REQUIREMENTS)
    _write(folder / "01-request/questions.json", QUESTIONS)
    _write(folder / "02-existing/app.json", APP_JSON)
    _write(folder / "02-existing/journeys.json", JOURNEYS)
    _write(folder / "02-existing/texts.json", TEXTS)
    _write(folder / "02-existing/audit.json", AUDIT)


@pytest.fixture
def ws(tmp_path, store):
    folder = tmp_path / "run"
    folder.mkdir()
    ground_host.prep("demo", folder, store=store)
    _stage_inputs(folder)
    return Workspace(folder)


def _found(ws, draft):
    return ground_check.check_draft(ground.context(ws), draft)


def _checks(found):
    return {p["check"] for p in found["problems"]}


# --- the capability map and the product file ---------------------------------------------------------------------

def test_read_map_keeps_every_entry_with_its_kind_group_and_intent():
    caps = capabilities.read_map(MAP)
    assert [(c.kind, c.key, c.group) for c in caps] == [
        ("http", "GET /api/plants", "plants"), ("http", "POST /api/plants/{id}/water", "plants"),
        ("http", "POST /api/dev/reset", "dev"), ("page", "/", ""), ("page", "/plants/:id", "")]
    assert caps[2].intent == "" and caps[1].where == "server/plants.js:9"
    assert "too_soon" in caps[1].intent


def test_product_file_takes_the_ground_entries_and_refuses_bad_ones():
    assert product_app.check(APP_FILE) == []
    bad = copy.deepcopy(APP_FILE)
    bad["fixture"] = {"parts": "sources/parts"}
    bad["capabilities"] = ""
    found = " ".join(product_app.check(bad))
    assert "'file' is a required property" in found and "capabilities" in found
    derive_spec = {**copy.deepcopy(APP_FILE), "capabilities": "derive", "path": "/tmp/x/.temper/design/app.yaml",
                   "repo": "/tmp/no-such-checkout"}
    with pytest.raises(ground_host.GroundPrepError, match="derive reads the product repo checkout"):
        ground_host.read_capabilities(derive_spec, Path("/tmp"))


# --- the host's prep -----------------------------------------------------------------------------------------------

def test_prep_copies_map_notes_and_fixture_and_records_them(ws):
    folder = ws.folder("ground")
    prep = json.loads((folder / "source/prep.json").read_text())
    assert contracts.check_json("ground_prep", prep, "prep.json") == []
    assert len(prep["capabilities"]["items"]) == 5 and prep["notes"][0]["name"] == "plants"
    assert json.loads((folder / "fixture.json").read_text()) == FIXTURE
    assert prep["fixture"]["sha256"] == ground_host.sha256_file(folder / "fixture.json")
    assert set(prep["fixture"]["parts"]) == {"watering"} and (folder / "fixtures/watering.json").is_file()
    assert prep["design_files"]["registered"] is False


def test_prep_refuses_a_used_workspace_and_a_part_named_like_a_fixture_key(ws, store, tmp_path):
    with pytest.raises(ground_host.GroundPrepError, match="already holds"):
        ground_host.prep("demo", ws.path, store=store)
    _write(store / "demo/sources/parts/plants.json", [])
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    with pytest.raises(ground_host.GroundPrepError, match="fixture key plants is in both"):
        ground_host.prep("demo", fresh, store=store)


# --- the source items and the task ---------------------------------------------------------------------------------

def test_source_items_carry_one_id_each(ws):
    prep = json.loads((ws.folder("ground") / "source/prep.json").read_text())
    items = {i["id"]: i for i in ground_sources.items(ws, prep)}
    assert {"page:/", "page:/plants/:id", "api:GET /api/plants", "api:POST /api/plants/{id}/water",
            "api:POST /api/dev/reset", "screen:home", "seen:home",
            "req:R1", "req:R2", "journey:J1", "note:plants#L3"} == set(items)
    assert items["api:POST /api/dev/reset"]["text"] == "(undescribed)"
    assert items["seen:home"]["text"] == "Fern · Water now · Basil later"
    assert "means: The plants to water today come first" in items["req:R1"]["text"]
    assert ground_sources.design_status(ws.folder("ground")) == "none"


def test_seen_words_leave_out_the_frame_and_wordless_runs():
    texts = {"a-1": {"all": ["Menu", "Sign out", "Net liq", "$5"]}, "b-1": {"all": ["Menu", "Cancel order"]},
             "c-1": {"all": ["Menu", "Sign out", "Run scan"]}}
    audit = {"screens": [{"id": "a-1", "screen": "a"}, {"id": "b-1", "screen": "b"}, {"id": "c-1", "screen": "c"}]}
    assert ground_sources.seen(texts, audit) == {"a": "Net liq", "b": "Cancel order", "c": "Run scan"}
    with pytest.raises(ground_sources.SourcesError, match="no text for capture d-1"):
        ground_sources.seen(texts, {"screens": [{"id": "d-1", "screen": "d"}]})


def test_collect_writes_sources_fixture_check_and_task(ws):
    out = ground.collect(ws, "")
    assert out["model"] == "yes" and out["fixture"] == "pass" and out["design_files"] == "none"
    assert (out["page"], out["api"], out["screen"], out["req"], out["note"]) == (2, 3, 1, 2, 1)
    assert out["seen"] == 1
    for words in ("page:/plants/:id", "refused with too_soon", "note:plants#L3", "seen:home: Fern · Water now", "Q1: Is a missed day shown?",
                  "Widths every screen is designed at: 1440, 390"):
        assert words in out["task"]
    assert contracts.validate("ground_collect", ws)


def test_collect_fails_loud_without_the_host_prep(tmp_path):
    (tmp_path / "empty").mkdir()
    w = Workspace(tmp_path / "empty")
    w.start("demo")
    with pytest.raises(ground.GroundError, match="ground-prep --product demo"):
        ground.collect(w, "")


def test_collect_fails_loud_when_the_fixture_was_changed_after_prep(ws):
    _write(ws.folder("ground") / "fixture.json", {**FIXTURE, "counts": {}})
    with pytest.raises(ground.GroundError, match="fixture.json differs from the copy ground-prep made"):
        ground.collect(ws, "")


# --- the fixture's invariants --------------------------------------------------------------------------------------

def test_invariants_pass_on_one_value_per_entity_and_totals_that_add_up():
    out = ground_fixture.check(FIXTURE, INVARIANTS)
    assert out == {"verdict": "pass", "checks": 2, "problems": []}


def test_invariants_fail_on_two_values_for_one_entity():
    bad = copy.deepcopy(FIXTURE)
    bad["today"]["plant"]["water"] = "tomorrow"
    out = ground_fixture.check(bad, INVARIANTS)
    assert out["verdict"] == "fail"
    assert "name Fern: water is 'tomorrow' here but 'today' at plants/0" in out["problems"][0]["problem"]


def test_invariants_fail_on_totals_that_do_not_add_up_and_on_paths_that_reach_nothing():
    bad = copy.deepcopy(FIXTURE)
    bad["counts"]["later"] = 3
    out = ground_fixture.check(bad, {**INVARIANTS, "totals": INVARIANTS["totals"] + [
        {"total": "counts.total", "plus": ["counts.missing"]}]})
    problems = [p["problem"] for p in out["problems"]]
    assert "is 2 but counts.today + counts.later is 4" in problems[0]
    assert "no field 'missing'" in problems[1]
    assert ground_fixture.check(FIXTURE, {"same_value": [{"key": "sku", "field": "price"}]})["verdict"] == "fail"


def test_fixture_states_are_every_states_field_at_any_depth():
    assert ground_fixture.states({"states": ["normal"], "x": {"states": {"too_soon": {}}}}) == {"normal", "too_soon"}
    assert ground_fixture.slug("Too soon!") == "too_soon"


# --- measured checks on the model's draft ------------------------------------------------------------------------

def test_good_draft_passes(ws):
    ground.collect(ws, "")
    found = _found(ws, GOOD)
    assert found["verdict"] == "ok", found["problems"]
    assert found["counts"]["required"] == found["counts"]["placed"] == 9


def test_a_knowledge_line_may_be_excluded_with_its_reason(ws):
    ground.collect(ws, "")
    draft = copy.deepcopy(GOOD)
    draft["screens"][0]["actions"][0]["sources"].remove("note:plants#L3")
    draft["excluded"].append({"source": "note:plants#L3", "reason": "names nothing the user sees"})
    found = _found(ws, draft)
    assert found["verdict"] == "ok", found["problems"]


def _broken(edit):
    draft = copy.deepcopy(GOOD)
    edit(draft)
    return draft


@pytest.mark.parametrize("name, edit, check", [
    ("cites an id no source has", lambda d: d["screens"][0]["sources"].append("page:/settings"), "invented"),
    ("action cites an invented route", lambda d: d["screens"][0]["actions"][0]["sources"].append(
        "api:DELETE /api/plants/{id}"), "invented"),
    ("extra state without a source", lambda d: d["screens"][1]["states"][5].pop("sources"), "unsourced"),
    ("page neither placed nor excluded", lambda d: d["screens"][1]["sources"].remove("page:/plants/:id")
     or d["screens"][1]["states"][5].update(sources=["req:R2"]), "coverage"),
    ("requirement not placed", lambda d: d["screens"][1]["sources"].remove("req:R2"), "coverage"),
    ("captured screen not cited", lambda d: d["screens"][0]["sources"].remove("screen:home"), "coverage"),
    ("knowledge line neither cited nor excluded", lambda d: d["screens"][0]["actions"][0]["sources"].remove(
        "note:plants#L3"), "coverage"),
    ("excluded route no reason can save", lambda d: d["excluded"].append(
        {"source": "api:GET /api/plants", "reason": "internal"}), "placed_and_excluded"),
    ("a captured screen excluded", lambda d: d["excluded"].append({"source": "screen:home", "reason": "old"}),
     "placed_and_excluded"),
    ("screen without a base state", lambda d: d["screens"][0]["states"].pop(4), "base_states"),
    ("action without its done state", lambda d: d["screens"][0]["actions"][0]["states"].remove("done"),
     "action_states"),
    ("named outcome drawn as a generic refusal", lambda d: d["screens"][0]["actions"][0]["states"].__setitem__(
        3, "refused"), "named_conditions"),
    ("screen id used twice", lambda d: d["screens"][1].update(id="today"), "ids"),
    ("state listed twice", lambda d: d["screens"][0]["states"].append({"name": "normal"}), "ids"),
    ("screen citing nothing", lambda d: d["screens"][0].update(sources=[]), "schema"),
    ("state that is not a slug", lambda d: d["screens"][1]["states"][5].update(name="Never watered"), "schema"),
    ("suggestion field", lambda d: d["screens"][0].update(layout="cards"), "schema"),
])
def test_broken_draft_fails_its_check(ws, name, edit, check):
    ground.collect(ws, "")
    found = _found(ws, _broken(edit))
    assert found["verdict"] == "retry", name
    assert check in _checks(found), (name, found["problems"])


def test_unreadable_reply_is_a_schema_problem_and_gets_a_revision_task(ws):
    ground.collect(ws, "")
    out = ground.check(ws, "```json\n{}\n```")
    assert out["verdict"] == "retry" and out["schema"] >= 1
    assert "previous draft" in out["revise_task"].casefold()
    assert (ws.folder("ground") / "draft-first.json").is_file()


def test_revision_text_lists_the_problems():
    text = ground_task.revise("TASK", "{}", [{"check": "coverage", "where": "req:R2", "problem": "not placed"}])
    assert "TASK" in text and "coverage at req:R2: not placed" in text


# --- the stage's script steps, end to end ----------------------------------------------------------------------

def test_check_then_final_write_the_inventory(ws):
    ground.collect(ws, "")
    assert ground.check(ws, json.dumps(GOOD))["verdict"] == "ok"
    out = ground.run(ws, "")
    assert out["revised"] is False and out["screens"] == 2
    inventory = json.loads((ws.folder("ground") / "inventory.json").read_text())
    assert contracts.validate("ground", ws)
    today, plant = inventory["screens"]
    assert today["widths"] == [1440, 390] and plant["state_sources"] == {"never-watered": ["page:/plants/:id"]}
    # too-soon and never-watered are in no fixture states field: build must add data for them
    assert today["data_needed"] == ["water: too-soon"] and plant["data_needed"] == ["never-watered"]
    assert inventory["excluded"][0]["source"] == "api:POST /api/dev/reset"
    assert inventory["source"]["capabilities"].endswith("sources/capabilities.md")
    assert ground_check.draft_from(inventory)["screens"][1]["states"][5] == GOOD["screens"][1]["states"][5]


def test_the_revised_reply_is_the_one_checked_last(ws):
    ground.collect(ws, "")
    first = _broken(lambda d: d["screens"][1]["sources"].remove("req:R2"))
    assert ground.check(ws, json.dumps(first))["verdict"] == "retry"
    assert ground.run(ws, json.dumps(GOOD))["revised"] is True
    with pytest.raises(ground.GroundError, match="coverage"):
        ground.run(ws, json.dumps(first))


def test_a_broken_invariant_fails_the_stage_after_the_inventory_is_written(tmp_path, store):
    bad = copy.deepcopy(FIXTURE)
    bad["today"]["plant"]["water"] = "tomorrow"
    _write(store / "demo/sources/fixture.json", bad)
    folder = tmp_path / "bad"
    folder.mkdir()
    ground_host.prep("demo", folder, store=store)
    _stage_inputs(folder)
    w = Workspace(folder)
    assert ground.collect(w, "")["fixture"] == "fail"
    ground.check(w, json.dumps(GOOD))
    with pytest.raises(ground.GroundError, match="breaks 1 invariant"):
        ground.run(w, "")
    assert (folder / "03-ground/inventory.json").is_file()


# --- step 4: over a stored ground (reuse, delta) -------------------------------------------------------------

def _stored_ground(tmp_path, ws) -> ProductStore:
    ground.collect(ws, "")
    assert ground.check(ws, json.dumps(GOOD))["verdict"] == "ok"
    ground.run(ws, "")
    ws.mark("ground", "done")
    ps = ProductStore("demo", tmp_path / "lab")
    assert ps.add("ground", ws.folder("ground"), {"fingerprint": {}, "run": "run-1"}) == (1, True)
    return ps


def _over_store(tmp_path, store, ps, name, requirements=REQUIREMENTS) -> Workspace:
    """A new run's workspace as prepare leaves it with ground pending: fresh prep, the stored copy beside it."""
    folder = tmp_path / name
    folder.mkdir()
    ground_host.prep("demo", folder, store=store)
    _stage_inputs(folder)
    _write(folder / "01-request/requirements.json", requirements)
    w = Workspace(folder)
    files = ps.copy_out("ground", 1, stored_copy.folder(w, "ground"))
    stored_copy.write(w, {"ground": {"version": 1, "source_run": "run-1", "files": files}})
    w.decide("ground", "pending", "stored v1", source_run="run-1", store_version=1)
    return w


def test_nothing_new_reuses_the_stored_inventory_without_the_model(tmp_path, store, ws):
    ps = _stored_ground(tmp_path, ws)
    w = _over_store(tmp_path, store, ps, "again")
    assert ground.collect(w, "")["model"] == "no"
    assert w.decision("ground")["decision"] == "reuse"
    assert ground.check(w, "")["verdict"] == "ok"
    out = ground.run(w, "")
    assert out["stage_status"] == "reused"
    assert (w.folder("ground") / "inventory.json").read_bytes() == \
        (ps.version_dir("ground", 1) / "inventory.json").read_bytes()
    contracts.validate("ground", w)


def test_a_new_requirement_is_placed_by_a_delta_and_the_stored_entries_stay(tmp_path, store, ws):
    ps = _stored_ground(tmp_path, ws)
    request = copy.deepcopy(REQUIREMENTS)
    request["items"].append({"id": "R3", "item": "S3", "owner_words": "remind me on the day", "kind": "feature",
                             "maps_to": ["home"]})
    w = _over_store(tmp_path, store, ps, "new-request", request)
    out = ground.collect(w, "")
    assert out["model"] == "yes" and out["unplaced"] == 1 and w.decision("ground")["decision"] == "delta"
    assert f"## {ground_task.PLACED_TITLE}" in out["task"] and "req:R3" in out["task"]
    assert "api:POST /api/dev/reset" not in out["task"].split(ground_task.PLACED_TITLE)[1].split("excluded already")[0]
    nothing = {"screens": [], "excluded": []}
    assert ground.check(w, json.dumps(nothing))["verdict"] == "retry"
    additions = {"screens": [{"id": "today", "name": "Today", "sources": ["req:R3"], "states": [],
                              "actions": [{"id": "remind", "what": "set a reminder for the day",
                                           "states": ["pending", "done", "error"], "sources": ["req:R3"]}]}],
                 "excluded": []}
    done = ground.run(w, json.dumps(additions))
    assert done["stage_status"] == "delta" and done["revised"] is True
    inventory = json.loads((w.folder("ground") / "inventory.json").read_text())
    stored = json.loads((ps.version_dir("ground", 1) / "inventory.json").read_text())
    today = inventory["screens"][0]
    assert "req:R3" in today["sources"] and [a["id"] for a in today["actions"]] == ["water", "remind"]
    assert inventory["screens"][1] == stored["screens"][1]
    assert (w.folder("ground") / "additions-first.json").is_file()


# --- the trial grader ------------------------------------------------------------------------------------------

def _case(tmp_path, ws, **expected):
    case = tmp_path / "case"
    base = {"case": "demo", "product": "demo", "design_files": "none", "fixture": {"invariants": "pass"},
            "pages": ["/", "/plants/:id"]}
    _write(case / "expected.json", {**base, **expected})
    return case


def _graded(tmp_path, ws, draft=GOOD, **expected):
    ground.collect(ws, "")
    ground.check(ws, json.dumps(draft))
    ground.run(ws, "")
    return ground_grade.grade(_case(tmp_path, ws, **expected), ws.path)


KEY = {"bar": 0.5, "items": [
    {"id": "water-first", "what": "what to water today", "screens": ["today"], "groups": [["water"], ["today"]]},
    {"id": "too-soon", "what": "too soon to water", "screens": [], "groups": [["too soon"]]},
    {"id": "water-action", "what": "water a plant", "screens": ["today"], "in": "action", "groups": [["watered"]]},
    {"id": "water-on-history", "what": "water from the history", "screens": ["plant"], "in": "action",
     "groups": [["water"]]},
    {"id": "history", "what": "watering history", "screens": ["plant"], "groups": [["history"]]},
    {"id": "missed", "what": "a missed day", "screens": [], "groups": [["missed"]]}]}


def test_grader_passes_a_good_run_and_counts_the_key(tmp_path, ws):
    out = _graded(tmp_path, ws, key=KEY)
    assert out["pass"], out["misses"]
    assert out["measures"]["key"] == "4/6" and out["measures"]["key_share"] == 0.667
    assert out["notes"] == ["key water-on-history (no group): water from the history",
                            "key missed (no group): a missed day"]
    assert out["measures"]["pages"] == "2/2" and out["measures"]["invented"] == 0


@pytest.mark.parametrize("expected, miss", [
    ({"design_files": "partial"}, "design_files"),
    ({"pages": ["/", "/plants/:id", "/settings"]}, "page /settings is on no screen"),
    ({"key": {**KEY, "bar": 0.9}}, "key"),
    ({"fixture": {"invariants": "fail"}}, "fixture"),
    ({"fixture": {"sha256": "0" * 64, "invariants": "pass"}}, "fixture"),
    ({"planted": [{"id": "G1", "what": "x", "measure": {"action_cites": "api:GET /api/plants"}}]}, "planted"),
    ({"clean": True, "false_gaps": [{"id": "F1", "what": "x", "measure": {"state_on": "api:POST /api/plants/{id}/water",
                                                                         "terms": ["too soon"]}}]}, "false gap F1"),
])
def test_grader_misses_what_the_case_expects_otherwise(tmp_path, ws, expected, miss):
    out = _graded(tmp_path, ws, **expected)
    assert not out["pass"]
    assert any(m.startswith(miss) for m in out["misses"]), out["misses"]


def test_grader_planted_measures_fire_on_the_good_run(tmp_path, ws):
    planted = [
        {"id": "G1", "what": "page on a screen", "measure": {"cited_by_screen": "page:/plants/:id"}},
        {"id": "G2", "what": "api action", "measure": {"action_cites": "api:POST /api/plants/{id}/water"}},
        {"id": "G3", "what": "state on the action", "measure": {"state_on": "api:POST /api/plants/{id}/water",
                                                                "terms": ["too soon"]}},
        {"id": "G4", "what": "new screen", "measure": {"new_screen": "req:R2", "terms": ["plant"], "not": ["home"]}},
        {"id": "G5", "what": "dev route excluded", "measure": {"excluded_only": "api:POST /api/dev/reset"}},
    ]
    out = _graded(tmp_path, ws, planted=planted)
    assert out["pass"], out["misses"]
    assert out["measures"]["planted"] == "5/5"


def test_grader_rechecks_the_final_inventory(tmp_path, ws):
    _graded(tmp_path, ws)
    path = ws.folder("ground") / "inventory.json"
    inventory = json.loads(path.read_text())
    inventory["screens"][0]["sources"].append("page:/invented")
    path.write_text(json.dumps(inventory))
    out = ground_grade.grade(tmp_path / "case", ws.path)
    assert not out["pass"] and any("invented" in m for m in out["misses"])


# --- workflows --------------------------------------------------------------------------------------------------

def _nodes(name: str) -> list[dict]:
    return yaml.safe_load((ROOT / f"configs/design/workflows/{name}.yaml").read_text())["workflow"]["nodes"]


def test_trial_workflow_runs_the_same_ground_nodes_as_the_whole_workflow():
    trial = _nodes("design_app_screen_v1_ground")
    whole = {n["name"]: n for n in _nodes("design_app_screen_v1")}
    stage = whole["ground"]
    assert stage["type"] == "stage" and stage["depends_on"] == ["existing"]
    children = {n["name"]: n for n in stage["nodes"]}
    assert list(children) == ["ground_collect", "ground_read", "ground_check", "ground_revise", "ground_finish"]
    for node in trial:
        child_name = "ground_finish" if node["name"] == "ground" else node["name"]
        expected = dict(children[child_name])
        expected["name"] = node["name"]
        assert node == expected, node["name"]
    assert [n["name"] for n in trial] == ["ground_collect", "ground_read", "ground_check", "ground_revise", "ground"]
    assert whole["directions"]["depends_on"] == ["ground"]


def test_reader_agent_is_tool_free_text_only_without_temperature():
    agent = yaml.safe_load((ROOT / "configs/design/agents/design_app_screen_ground_v1.yaml").read_text())["agent"]
    assert agent["type"] == "llm" and agent["provider"] == "anthropic" and agent["tools"] == []
    assert "image_input" not in agent and agent["task_template"] == "{{ task }}"
    assert "temperature" not in agent and "temperature" not in agent.get("provider_config", {})
    # the ceiling holds thinking and reply together: under it, RollCall's first drafts were cut off (H3-4)
    assert agent["provider_config"]["max_tokens"] >= 128000
