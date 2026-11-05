"""design_app_screen_v1 stage 2, existing (Design #207): the product file, the measures, the measured checks
around the model step, the stage's script steps and the trial grader.

Each check is shown one good fixed model output and broken copies of it. The app, screens and words here are
invented test data (the repository is public); the real cases (RollCall at a pinned commit, a planted app and
its clean twin) live in the lab (~/design-lab/app-screen-workflow/known-cases/existing/). The host's browser
capture and contact sheet need Playwright and Pillow on the host, so they are proven by the trial runs there.
"""
from __future__ import annotations

import base64
import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "configs/design/bin"
sys.path.insert(0, str(BIN))

from app_screen import (  # noqa: E402
    contracts,
    existing,
    existing_check,
    existing_grade,
    existing_host,
    existing_measures,
    existing_task,
    product_app,
)
from app_screen.workspace import Workspace  # noqa: E402

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")

APP_FILE = {
    "product": "demo", "name": "Demo", "job": "Demo shows a gardener which plants need water today.",
    "app": {"kind": "static", "root": "/tmp/demo-app", "port": 8199},
    "page": {"main": "main", "key_regions": {"main_status": "#status"}, "error_selector": "[role=alert]"},
    "sizes": {"390": {"height": 844, "phone": True}, "320": {"height": 568, "phone": True},
              "1440": {"height": 900, "phone": False}},
    "sheet_width": 390,
    "screens": [
        {"id": "home", "name": "Home", "route": "/index.html", "widths": [390, 320],
         "states": {"normal": {"what": "today's plants"}}},
        {"id": "list", "name": "Plants", "route": "/list.html", "widths": [390],
         "states": {"normal": {}, "error": {"query": "?state=error", "what": "the list fails to load"}}},
    ],
}


def _raw(w: int, h: int, *, under12: int = 0, targets: int = 0, status_top: int = 100, errors: list | None = None,
         runs: list[str] = ()) -> dict:
    return {"viewport": {"w": w, "h": h}, "pageHeight": h, "screensTall": 1,
            "chrome": {"tabbar": 60, "tabbarRows": 1, "contentLeftInFirstView": h - 60},
            "type": {"total": 10, "under12": under12, "under16": under12, "bodyLikeRuns": 2, "bodyLikeUnder16": 0,
                     "distinctSizes": 3, "smallestPx": 10 if under12 else 14},
            "targets": {"under24NotInline": targets}, "overflow": {"sideScrollers": []},
            "truncated": {"count": 0, "items": []}, "blocks": {"alwaysOpen": 2}, "errors": errors or [],
            "pageErrors": [], "keyRegions": {"main_status": {"top": status_top}},
            "runs": [{"text": t, "first": True} for t in runs]}


RAW = {
    "home-390-normal": _raw(390, 844, status_top=2532, runs=["Water today", "Fern needs water by noon"]),
    "home-320-normal": _raw(333, 568, status_top=2840, runs=["Water today", "Fern needs water by noon"]),
    "list-390-normal": _raw(390, 844, targets=4, runs=["Plants", "Fern", "Basil"]),
    "list-390-error": _raw(390, 844, errors=[{"text": "Could not load plants", "actions": []}],
                           runs=["Could not load plants"]),
}
REQUIREMENTS = {"source": "test", "items": [
    {"id": "R1", "item": "S1", "owner_words": "show what needs water first", "kind": "goal",
     "means": "The plants to water today come first.", "maps_to": ["home"]}]}

GOOD = {
    "journeys": [
        {"id": "J1", "name": "See what needs water", "goal": "Know which plant to water today",
         "screens": ["home"], "problems": ["P1", "P2"], "requirements": ["R1"],
         "keep": [{"what": "The home names the plant and the time",
                   "evidence": [{"capture": "home-390-normal", "text": "Fern needs water by noon"}]}]},
        {"id": "J2", "name": "Browse the plants", "goal": "Find one plant", "screens": ["list"],
         "problems": ["P3", "P4"], "keep": []},
    ],
    "problems": [
        {"id": "P1", "claim": "The status starts 3 screens down on the phone.", "severity": 3, "kind": "buried",
         "evidence": [{"capture": "home-390-normal", "measure": "main_status_screens_down", "value": 3.0}]},
        {"id": "P2", "claim": "At 320 the page is 333 px wide, wider than the phone.", "severity": 3,
         "kind": "layout-width",
         "evidence": [{"capture": "home-320-normal", "measure": "layout_width_px", "value": 333}]},
        {"id": "P3", "claim": "4 tap targets are under 24 px.", "severity": 2, "kind": "tap-target",
         "evidence": [{"capture": "list-390-normal", "measure": "targets_under_24px", "value": 4}]},
        {"id": "P4", "claim": "The error says it failed but offers nothing to do.", "severity": 3,
         "kind": "error-recovery",
         "evidence": [{"capture": "list-390-error", "measure": "error_messages_without_action", "value": 1},
                      {"capture": "list-390-error", "text": "Could not load plants"}]},
    ],
}


def _loaded(tmp_path: Path) -> dict:
    return product_app.load("demo", _store(tmp_path, APP_FILE))


def _audit(app: dict, raw: dict) -> tuple[dict, dict]:
    return existing_host.audit_from(app, product_app.captures(app), raw)


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data) if not isinstance(data, str) else data, encoding="utf-8")


@pytest.fixture()
def ws(tmp_path: Path) -> Workspace:
    """A workspace as the host's capture leaves it (its own audit and summary builders), with stage 1's
    requirements; the browser and the sheet are the host's part."""
    app = _loaded(tmp_path)
    (tmp_path / "ws").mkdir()
    w = Workspace(tmp_path / "ws")
    w.start("demo", "real")
    folder = w.folder("existing")
    audit, texts = _audit(app, RAW)
    for s in audit["screens"]:
        (folder / s["capture"]).parent.mkdir(parents=True, exist_ok=True)
        (folder / s["capture"]).write_bytes(PNG)
    _write(folder / "audit.json", audit)
    _write(folder / "texts.json", texts)
    _write(folder / "app.json", existing_host.app_summary(app))
    _write(folder / "capture.json", {"captures": len(audit["screens"]), "failed": {}})
    (folder / "sheet.png").write_bytes(PNG)
    _write(w.folder("intake") / "requirements.json", REQUIREMENTS)
    existing.collect(w, "")  # the workflow's first existing node: task.md, which a revision repeats
    return w


def _found(ws: Workspace, draft: dict) -> dict:
    return existing_check.check_draft(existing.context(ws), draft)


def _checks(found: dict) -> set[str]:
    return {p["check"] for p in found["problems"]}


# --- product file ---------------------------------------------------------------------------------------------

def _store(tmp_path: Path, app: dict) -> Path:
    store = tmp_path / "products"
    _write(store / app["product"] / "app.yaml", yaml.safe_dump(app, sort_keys=False))
    return store


def test_product_file_loads_and_expands_to_one_capture_per_screen_state_width(tmp_path):
    app = product_app.load("demo", _store(tmp_path, APP_FILE))
    assert app["base_url"] == "http://127.0.0.1:8199"
    caps = product_app.captures(app)
    assert [c["id"] for c in caps] == ["home-390-normal", "home-320-normal", "list-390-normal", "list-390-error"]
    assert caps[3]["steps"] == [{"goto": "/list.html?state=error"}]
    assert caps[1]["height"] == 568 and caps[1]["phone"] is True


@pytest.mark.parametrize("change, words", [
    (lambda a: a["screens"][0].pop("route"), "exactly one of route or steps"),
    (lambda a: a["screens"][1]["states"]["normal"].update(widths=[768]), "width 768 is not in sizes"),
    (lambda a: a.update(sheet_width=1280), "sheet_width"),
    (lambda a: a["screens"].append(copy.deepcopy(a["screens"][0])), "used twice"),
    (lambda a: a.update(login={"path": "/login", "fields": {"#e": "x"}, "submit": "b", "wait_for": "main"}),
     "needs an account"),
    (lambda a: a["screens"][0].update(steps=[{"click_first": {"text": "("}}]) or a["screens"][0].pop("route"),
     "not a regular expression"),
    (lambda a: a.update(colour="red"), "Additional properties"),
])
def test_product_file_fails_loud_naming_the_problem(tmp_path, change, words):
    app = copy.deepcopy(APP_FILE)
    change(app)
    with pytest.raises(product_app.AppFileError, match="problem") as err:
        product_app.load("demo", _store(tmp_path, app))
    assert words in str(err.value)


def test_server_checkout_never_inside_the_repo(tmp_path):
    app = copy.deepcopy(APP_FILE)
    app["app"] = {"kind": "server", "repo": "/srv/app", "commit": "81117dd", "checkout": "/srv/app/copy", "port": 8199,
                  "build": [], "seed": ["seed"], "serve": ["serve"], "ready": "/"}
    with pytest.raises(product_app.AppFileError, match="never inside the repo"):
        product_app.load("demo", _store(tmp_path, app))


def test_product_folder_must_match():
    with pytest.raises(product_app.AppFileError, match="not a readable app file"):
        product_app.load("missing", Path("/nonexistent-store"))


# --- measures -------------------------------------------------------------------------------------------------

def test_measures_flag_the_problem_side_and_totals_count_per_width(tmp_path):
    m = existing_measures.measures(RAW["home-320-normal"], 320)
    assert m["layout_width_px"] == 333 and m["wider_than_screen_px"] == 13
    assert m["main_status_screens_down"] == 5.0
    cap = {"width": 320, "height": 568}
    assert existing_measures.shows_problem("layout_width_px", 333, cap) is True
    assert existing_measures.shows_problem("layout_width_px", 320, cap) is False
    assert existing_measures.shows_problem("page_height_px", 9000, cap) is None
    audit, _ = _audit(_loaded(tmp_path), RAW)
    assert audit["totals"]["layout_width_px@320"] == {"value": 1, "of": 1}
    assert audit["totals"]["targets_under_24px@390"] == {"value": 1, "of": 3}
    assert existing_measures.measures(RAW["list-390-error"], 390)["error_messages_without_action"] == 1


# --- measured checks on the model's draft --------------------------------------------------------------------

def test_good_draft_passes(ws):
    found = _found(ws, GOOD)
    assert found["verdict"] == "ok", found["problems"]
    assert found["counts"]["problems"] == 4 and found["counts"]["severity"]["3"] == 3


def _broken(edit):
    draft = copy.deepcopy(GOOD)
    edit(draft)
    return draft


@pytest.mark.parametrize("name, edit, check", [
    ("number the audit doesn't hold", lambda d: d["problems"][1]["evidence"][0].update(value=360), "values"),
    ("number no ref shows", lambda d: d["problems"][2].update(claim="7 tap targets are under 24 px."), "invented"),
    ("capture that doesn't exist", lambda d: d["problems"][0]["evidence"][0].update(capture="home-768-normal"),
     "refs"),
    ("measure the capture lacks", lambda d: d["problems"][0]["evidence"][0].update(measure="attention_screens_down"),
     "refs"),
    ("text not on the screen", lambda d: d["problems"][3]["evidence"][1].update(text="Try again later"), "texts"),
    ("no capture cited", lambda d: d["problems"][3].update(evidence=[{"total": "targets_under_24px@390", "value": 1}]),
     "unsupported"),
    ("measured kind without its measure", lambda d: d["problems"][2].update(
        evidence=[{"capture": "list-390-normal", "text": "Basil"}]), "unsupported"),
    ("measure contradicts the claim", lambda d: d["problems"][1]["evidence"][0].update(
        capture="home-390-normal", value=390), "contradicted"),
    ("keep rests on a problem", lambda d: d["journeys"][0]["keep"][0].update(
        evidence=[{"capture": "home-320-normal", "measure": "layout_width_px", "value": 333}]), "contradicted"),
    ("unknown screen", lambda d: d["journeys"][1]["screens"].append("settings"), "screens"),
    ("journey names a missing problem", lambda d: d["journeys"][1]["problems"].append("P9"), "ids"),
    ("unknown requirement", lambda d: d["journeys"][0].update(requirements=["R7"]), "ids"),
    ("problem in no journey", lambda d: d["journeys"][1]["problems"].remove("P4"), "orphan"),
    ("suggestion field", lambda d: d["problems"][0].update(fix="move it up"), "schema"),
    ("severity off the scale", lambda d: d["problems"][0].update(severity=5), "schema"),
])
def test_broken_draft_fails_its_check(ws, name, edit, check):
    found = _found(ws, _broken(edit))
    assert found["verdict"] == "retry", name
    assert check in _checks(found), (name, found["problems"])


def test_unreadable_reply_is_a_schema_problem(ws):
    out = existing.check(ws, "```json\n{}\n```")
    assert out["verdict"] == "retry" and out["schema"] >= 1
    assert "draft" in out["revise_task"].casefold()


# --- the stage's script steps ----------------------------------------------------------------------------------

def test_collect_writes_the_task_and_sheet_passes_the_png(ws):
    out = existing.collect(ws, "")
    assert out["model"] == "yes" and out["captures"] == 4 and out["screens"] == 2
    task = out["task"]
    for words in ("Fern needs water by noon", "home-320-normal", "layout_width_px=333!", "R1"):
        assert words in task
    assert existing.sheet(ws, "")["sheet"] == base64.b64encode(PNG).decode()


def test_collect_fails_loud_without_the_capture(tmp_path):
    (tmp_path / "empty").mkdir()
    w = Workspace(tmp_path / "empty")
    w.start("demo", "real")
    with pytest.raises(existing.ExistingError, match="design_app_screen.py capture --product demo"):
        existing.collect(w, "")


def test_check_then_final_write_journeys_with_refs(ws):
    assert existing.check(ws, json.dumps(GOOD))["verdict"] == "ok"
    out = existing.run(ws, "")
    assert out["revised"] is False
    contracts.validate("existing", ws)
    journeys = json.loads((ws.folder("existing") / "journeys.json").read_text())
    p2 = journeys["journeys"][0]["problems"][1]
    assert p2["evidence"] == ["home-320-normal: layout_width_px = 333"] and p2["refs"][0]["value"] == 333
    assert existing_check.draft_from_journeys(journeys)["problems"] == GOOD["problems"]


def test_retry_keeps_the_first_draft_and_a_still_broken_revision_fails_loud(ws):
    bad = _broken(lambda d: d["problems"][1]["evidence"][0].update(value=360))
    out = existing.check(ws, json.dumps(bad))
    assert out["verdict"] == "retry" and "360" in out["revise_task"]
    assert (ws.folder("existing") / "draft-first.json").is_file()
    with pytest.raises(existing.ExistingError, match="breaks 2 check.*333, not 360"):
        existing.run(ws, json.dumps(bad))
    assert not (ws.folder("existing") / "journeys.json").exists()
    assert existing.run(ws, json.dumps(GOOD))["revised"] is True


def test_revise_task_carries_the_task_the_draft_and_each_problem():
    text = existing_task.revise("TASK TEXT", '{"a": 1}', [{"check": "values", "where": "problems/1", "problem": "X"}])
    assert "TASK TEXT" in text and '{"a": 1}' in text and "values at problems/1: X" in text


# --- grader ----------------------------------------------------------------------------------------------------

def _case(tmp_path: Path, bars: dict, **extra) -> Path:
    case = tmp_path / "case"
    _write(case / "requirements.json", REQUIREMENTS)
    _write(case / "expected.json", {"case": "demo", "product": "demo", "captures": 4, "bars": bars, **extra})
    return case


PLANTED = [
    {"id": "D1", "kind": "layout-width", "what": "wider than 320", "screens": ["home-320-normal"],
     "measures": ["layout_width_px"], "terms": ["wider"]},
    {"id": "D2", "kind": "error-recovery", "what": "error with no recovery", "screens": ["list-390-error"],
     "measures": ["error_messages_without_action"], "terms": ["nothing to do"]},
]
KEY = {
    "problems": {"P1": {"what": "status buried", "groups": [["status"], ["screens down", "below"]]},
                 "P2": {"what": "page too wide", "groups": [["wider", "too wide"]]}},
    "journeys": [{"id": "J1", "name": "Water", "screens": ["home"], "terms": ["water"], "problems": ["P1", "P2"]}],
}


def _final(ws: Workspace, draft: dict) -> None:
    existing.check(ws, json.dumps(draft))
    existing.run(ws, "")


def test_grader_passes_a_good_run(tmp_path, ws):
    _final(ws, GOOD)
    planted = existing_grade.grade(_case(tmp_path, {"capture_failed": 0, "unsupported": 0, "recall_min": 2},
                                         planted=PLANTED), ws.path)
    assert planted["pass"], planted["misses"]
    assert planted["measures"]["recall"] == "2/2" and planted["measures"]["other_findings"] == ["P1", "P3"]
    keyed = existing_grade.grade(_case(tmp_path, {"unsupported": 0, "key_recall_min": 2, "journeys_min": 1}, **KEY),
                                 ws.path)
    assert keyed["pass"], keyed["misses"]
    assert keyed["measures"]["key"] == "2/2" and keyed["measures"]["journeys_matched"] == "1/1"


def _tamper(ws: Workspace, edit) -> None:
    path = ws.folder("existing") / "journeys.json"
    journeys = json.loads(path.read_text())
    edit(journeys)
    path.write_text(json.dumps(journeys))


@pytest.mark.parametrize("name, edit, miss", [
    ("unsupported number", lambda j: j["journeys"][0]["problems"][1].update(
        claim="At 320 the page is 360 px wide, wider than the phone."), "unsupported: invented"),
    ("missing evidence id", lambda j: j["journeys"][0]["problems"][1]["refs"][0].update(capture="home-768-normal"),
     "unsupported: refs"),
    ("value off the audit", lambda j: j["journeys"][1]["problems"][0]["refs"][0].update(value=9),
     "unsupported: values"),
])
def test_grader_fails_broken_copies_of_a_good_run(tmp_path, ws, name, edit, miss):
    _final(ws, GOOD)
    _tamper(ws, edit)
    result = existing_grade.grade(_case(tmp_path, {"unsupported": 0, "recall_min": 0}, planted=PLANTED), ws.path)
    assert not result["pass"], name
    assert any(m.startswith(miss) for m in result["misses"]), result["misses"]


def test_grader_fails_a_claim_on_the_clean_twin(tmp_path, ws):
    clean = {"unsupported": 0, "severe_max": 0, "severe_from": 2, "low_need_measure": True}
    low = copy.deepcopy(GOOD)
    low["journeys"] = [dict(low["journeys"][0], problems=["P5"]), dict(low["journeys"][1], problems=[])]
    low["problems"] = [{"id": "P5", "claim": "The home's title reads as a heading.", "severity": 1, "kind": "wording",
                        "evidence": [{"capture": "home-390-normal", "text": "Water today"}]}]
    _final(ws, low)
    result = existing_grade.grade(_case(tmp_path, clean), ws.path)
    assert not result["pass"] and "cites no measure on its problem side" in " ".join(result["misses"])
    _final(ws, GOOD)
    result = existing_grade.grade(_case(tmp_path, clean), ws.path)
    assert not result["pass"] and result["measures"]["severe"] == 4


def test_grader_fails_a_missed_planted_defect_and_a_failed_capture(tmp_path, ws):
    draft = _broken(lambda d: (d["journeys"][1]["problems"].remove("P4"), d["problems"].pop(3)))
    _final(ws, draft)
    _write(ws.folder("existing") / "capture.json", {"captures": 4, "failed": {"list-390-error": "timeout"}})
    result = existing_grade.grade(_case(tmp_path, {"capture_failed": 0, "recall_min": 2}, planted=PLANTED), ws.path)
    assert not result["pass"]
    joined = " ".join(result["misses"])
    assert "planted D2" in joined and "recall 1/2" in joined and "capture failed 1" in joined


def test_grader_fails_a_run_without_final_output(tmp_path, ws):
    result = existing_grade.grade(_case(tmp_path, {"unsupported": 0}), ws.path)
    assert not result["pass"] and "did not write a clean final output" in result["misses"][-1]


# --- workflows --------------------------------------------------------------------------------------------------

def _nodes(name: str) -> list[dict]:
    return yaml.safe_load((ROOT / f"configs/design/workflows/{name}.yaml").read_text())["workflow"]["nodes"]


def test_trial_workflow_runs_the_same_existing_nodes_as_the_whole_workflow():
    trial = _nodes("design_app_screen_v1_existing")
    whole = {n["name"]: n for n in _nodes("design_app_screen_v1")}
    for node in trial:
        expected = dict(whole[node["name"]])
        if node["name"] == "existing_collect":
            expected.pop("depends_on")
        assert node == expected, node["name"]
    assert [n["name"] for n in trial] == ["existing_collect", "existing_sheet", "existing_read", "existing_check",
                                         "existing_revise", "existing"]


def test_reader_agent_is_tool_free_image_input_without_temperature():
    agent = yaml.safe_load((ROOT / "configs/design/agents/design_app_screen_existing_v1.yaml").read_text())["agent"]
    assert agent["type"] == "llm" and agent["provider"] == "anthropic" and agent["tools"] == []
    assert agent["image_input"] == {"key": "sheet", "media_type": "image/png"}
    assert "temperature" not in agent and "temperature" not in agent.get("provider_config", {})


def _cli():
    spec = importlib.util.spec_from_file_location("design_app_screen_cli", BIN / "design_app_screen.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_runs_the_existing_steps(ws, capsys):
    cli = _cli()
    cli.main(["existing_collect", "--workspace", str(ws.path), "--mode", "real"])
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["step"] == "existing_collect" and line["model"] == "yes" and line["valid"] is True
