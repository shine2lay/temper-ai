"""first_app_check's comparators on canned snapshots (System architecture, queues #91 and #92).

configs/architecture/bin/first_app_check.py drives temper's playwright-mcp browser through QA's frozen
critical journey (kit qa-first-app-critical-v1) and judges what the rendered page showed. The browser
part is proven by the workflow's controls mode on temper-dev; these tests pin the pure judging part:
a clean receipt PASSes, and each kind of broken one gets the verdict the kit's checker controls name
(K-CLEAN, K-BROKEN-RELOAD, K-WRONG-PIN, K-MISSING-STEP, K-RUNNER-FAIL, K-OBSERVER-MISSING,
K-FORBIDDEN-TRAFFIC, K-CRITICAL-ERROR, K-CLEANUP-UNKNOWN), plus wrong order and wrong focus.
#92 adds the profile input (a new build's origin, pins, kit and page wording; strict, refused before the
browser is contacted; left out = the first build exactly) and QA's three receipt suggestions: the "/"
document hashed against the index.html pin, the kit's NOT CHECKED list in the receipt, and outside
traffic as a traffic gate kept apart from the rows' app-state results.
"""

import argparse
import asyncio
import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "configs" / "architecture" / "bin" / "first_app_check.py"
spec = importlib.util.spec_from_file_location("first_app_check", SCRIPT)
fac = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fac)

ORIGIN = "https://app.example.test:8960"


def observed_for(step: dict) -> dict:
    """What a working page shows after one kit row, as the browser stage reports it."""
    exp = step["expected"]
    obs = {
        "headings": ["To-do list"],
        "textbox": {"count": 1, "visible": True, "enabled": True, "value": exp.get("input", ""), "focused": False},
        "add_button": {"count": 1, "visible": True, "enabled": True},
        "rows": copy.deepcopy(exp["rows"]),
        "focus": exp.get("focus", "body"),
        "empty_text_visible": not exp["rows"],
        "alerts": [],
        "body_text": "To-do list New item Add " + " ".join(r["text"] + " Delete" for r in exp["rows"]),
        "resource_refs": [ORIGIN + "/style.css", ORIGIN + "/app.js"],
    }
    return obs


def wire(step_id: str) -> dict:
    reqs = []
    if step_id in ("C1-1", "C1-5", "C1-8"):
        reqs = [{"method": "GET", "url": ORIGIN + p} for p in ("/", "/style.css", "/app.js")]
    return {"requests": reqs, "websockets": [], "pageerrors": [], "dialogs": [], "crashes": [], "popups": []}


def clean_receipt() -> dict:
    pins = {n: dict(p) for n, p in fac.FROZEN_PINS.items()}
    fetched = {n: {"status": 200, "bytes": p["bytes"], "sha256": p["sha256"]} for n, p in pins.items()}
    r = {
        "origin": ORIGIN,
        "reach": {"status": 200, "final_url": ORIGIN + "/"},
        "pins": fac.check_pins(pins, fetched, ORIGIN, ORIGIN + "/"),
        "observers": {"before_first_navigation": True},
        "steps": [],
        "steps_attempted": 0,
        "cleanup": {"confirmed": True},
        "screenshot": {"file": "after-reload.png"},
    }
    for step in fac.STEPS:
        v = fac.judge_step(step, observed_for(step), wire(step["id"]), ORIGIN)
        r["steps"].append({"id": step["id"], "status": v["status"], "reasons": v["reasons"], "traffic": v["traffic"]})
        r["steps_attempted"] += 1
    return r


def run_journey(mutate) -> dict:
    """The clean journey with one row's observation or wire changed; stops at the first failure, or at
    the first traffic outside the policy (as the checker does)."""
    r = clean_receipt()
    r["steps"], r["steps_attempted"] = [], 0
    for step in fac.STEPS:
        obs, new = observed_for(step), wire(step["id"])
        mutate(step["id"], obs, new)
        v = fac.judge_step(step, obs, new, ORIGIN)
        r["steps"].append({"id": step["id"], "status": v["status"], "reasons": v["reasons"], "traffic": v["traffic"]})
        r["steps_attempted"] += 1
        if v["status"] == "FAIL" or v["traffic"]:
            r.pop("screenshot", None) if step["id"] <= "C1-5" else None
            break
    return r


def failed_at(r: dict):
    return next((s["id"] for s in r["steps"] if s["status"] == "FAIL"), None)


def test_kit_rows_are_the_frozen_eight():
    assert [s["id"] for s in fac.STEPS] == [f"C1-{i}" for i in range(1, 9)]
    assert fac.STEPS[1]["input"] == "  Buy milk  " and fac.STEPS[2]["input"] == "Call Sam"
    assert fac.EMPTY_TEXT == "Your list is empty. Type an item above, then press Enter or Add."
    assert fac.KIT_SHA256.startswith("49813ec9") and fac.LIVE_ORIGIN == "https://spark.tailbb5055.ts.net:8960"


def test_clean_passes_all_eight():
    r = clean_receipt()
    assert [s["status"] for s in r["steps"]] == ["PASS"] * 8
    assert fac.final_verdict(r) == ("PASS", "all 8 rows observed as the kit expects")


def test_lost_on_reload_fails_c1_5():
    def m(sid, obs, new):
        if sid == "C1-5":
            obs["rows"] = [{"text": "Buy milk", "checked": False}, {"text": "Call Sam", "checked": False}]
    r = run_journey(m)
    assert failed_at(r) == "C1-5" and fac.final_verdict(r)[0] == "FAIL"


def test_wrong_order_fails_c1_3():
    def m(sid, obs, new):
        if sid == "C1-3":
            obs["rows"] = list(reversed(obs["rows"]))
    r = run_journey(m)
    assert failed_at(r) == "C1-3" and fac.final_verdict(r)[0] == "FAIL"


def test_wrong_focus_fails_c1_2():
    def m(sid, obs, new):
        if sid == "C1-2":
            obs["focus"] = 'button "Add"'
    r = run_journey(m)
    assert failed_at(r) == "C1-2"
    assert "focus on 'button \"Add\"', expected 'New item'" in r["steps"][-1]["reasons"][0]


def test_input_not_cleared_fails():
    def m(sid, obs, new):
        if sid == "C1-3":
            obs["textbox"]["value"] = "Call Sam"
    assert failed_at(run_journey(m)) == "C1-3"


def test_missing_observation_blocks_never_passes():
    r = clean_receipt()
    r["steps"] = r["steps"][:4]
    assert fac.final_verdict(r)[0] == "BLOCKED"
    assert fac.compare_step(fac.STEPS[4]["expected"], None) == ["no observation"]


def test_wrong_hash_is_refused_before_any_step():
    pins = {n: dict(p) for n, p in fac.FROZEN_PINS.items()}
    fetched = {n: {"status": 200, "bytes": p["bytes"], "sha256": p["sha256"]} for n, p in pins.items()}
    fetched["index.html"]["sha256"] = "0" * 64
    r = {"origin": ORIGIN, "reach": {"status": 200}, "pins": fac.check_pins(pins, fetched, ORIGIN, ORIGIN + "/"),
         "steps": [], "steps_attempted": 0}
    verdict, why = fac.final_verdict(r)
    assert verdict == "REFUSED" and "index.html" in why


def test_redirect_off_origin_is_refused():
    pins = {n: dict(p) for n, p in fac.FROZEN_PINS.items()}
    fetched = {n: {"status": 200, "bytes": p["bytes"], "sha256": p["sha256"]} for n, p in pins.items()}
    assert not fac.check_pins(pins, fetched, ORIGIN, "https://elsewhere.test/")["ok"]


def test_outside_request_fails_the_traffic_gate_even_with_correct_rows():
    # #92, QA's suggestion 3: the traffic gate fails (overall FAIL), not the row; the journey stops there.
    def m(sid, obs, new):
        if sid == "C1-1":
            new["requests"].append({"method": "GET", "url": "https://tracker.test/p.gif"})
    r = run_journey(m)
    assert failed_at(r) is None and [s["id"] for s in r["steps"]] == ["C1-1"]
    gate = fac.traffic_gate(r)
    assert gate["status"] == "FAIL" and gate["first_seen"] == "C1-1"
    assert any("outside the origin" in x for x in gate["findings"]) and r["steps"][0]["reasons"] == []
    verdict, why = fac.final_verdict(r)
    assert verdict == "FAIL" and why.startswith("traffic gate: C1-1: request outside the origin")


def test_unexpected_same_origin_path_query_and_post_fail():
    reqs = [{"method": "GET", "url": ORIGIN + "/api/items"}, {"method": "GET", "url": ORIGIN + "/app.js?v=2"},
            {"method": "POST", "url": ORIGIN + "/"}, {"method": "GET", "url": "data:image/png;base64,AA"}]
    found = fac.traffic_findings(reqs, [{"url": "wss://x.test/"}], ORIGIN)
    assert len(found) == 4 and found[-1] == "websocket: wss://x.test/"


def test_outside_resource_reference_fails_the_traffic_gate():
    def m(sid, obs, new):
        obs["resource_refs"].append("https://cdn.test/icon.png")
    r = run_journey(m)
    assert failed_at(r) is None and fac.traffic_gate(r)["first_seen"] == "C1-1"
    assert fac.final_verdict(r)[0] == "FAIL"


def test_page_error_fails_c1_4():
    def m(sid, obs, new):
        if sid == "C1-4":
            obs["rows"][0]["checked"] = False
            new["pageerrors"].append({"message": "toggle failed"})
    r = run_journey(m)
    assert failed_at(r) == "C1-4" and "page error: toggle failed" in r["steps"][-1]["reasons"]


def test_page_error_alone_fails_even_when_rows_are_right():
    def m(sid, obs, new):
        if sid == "C1-6":
            new["pageerrors"].append({"message": "late"})
    assert failed_at(run_journey(m)) == "C1-6"


def test_saving_warning_detected_but_info_text_is_not():
    obs = {"alerts": [], "body_text": "To-do list Your list could not be saved on this device. Add"}
    found = fac.saving_warning(obs)
    assert len(found) == 1 and found[0].endswith("Your list could not be saved on this device.")
    assert fac.saving_warning({"alerts": [], "body_text": "Your list is saved in this browser."}) == []
    assert fac.saving_warning({"alerts": ["Storage is full"], "body_text": ""}) == ["Storage is full"]
    assert fac.saving_warning({"alerts": ["Added Buy milk"], "body_text": ""}) == []

    def m(sid, obs, new):
        if sid == "C1-5":
            obs["body_text"] += " Changes couldn't be saved."
    assert failed_at(run_journey(m)) == "C1-5"


def test_cleanup_unknown_overrides_pass():
    r = clean_receipt()
    r["cleanup"] = {"confirmed": False, "error": "RuntimeError: gone"}
    assert fac.final_verdict(r)[0] == "BLOCKED"


def test_runner_failure_blocks_and_is_not_an_app_result():
    r = {"origin": ORIGIN, "runner_error": "stage A: OSError: Socket path too long", "steps": [], "steps_attempted": 0}
    assert fac.final_verdict(r)[0] == "BLOCKED"
    r = {"origin": ORIGIN, "reach": {"error": "net::ERR_CONNECTION_REFUSED"}, "steps": [], "steps_attempted": 0}
    assert fac.final_verdict(r) == ("BLOCKED", "app not reached: net::ERR_CONNECTION_REFUSED")


def test_runner_stop_mid_journey_blocks():
    r = clean_receipt()
    r["steps"] = r["steps"][:3]
    r["runner_error"] = "stage B-D: RuntimeError: browser gone"
    assert fac.final_verdict(r)[0] == "BLOCKED"


def test_observers_attached_late_block():
    r = clean_receipt()
    r["observers"] = {"before_first_navigation": False}
    assert fac.final_verdict(r)[0] == "BLOCKED"


def test_missing_screenshot_blocks():
    r = clean_receipt()
    del r["screenshot"]
    assert fac.final_verdict(r)[0] == "BLOCKED"


@pytest.mark.parametrize("key", ["heading", "textboxLabel", "button", "emptyText"])
def test_first_screen_controls_are_required(key):
    def m(sid, obs, new):
        if sid != "C1-1":
            return
        if key == "heading":
            obs["headings"] = ["Todo"]
        elif key == "textboxLabel":
            obs["textbox"]["count"] = 0
        elif key == "button":
            obs["add_button"]["enabled"] = False
        else:
            obs["empty_text_visible"] = False
    assert failed_at(run_journey(m)) == "C1-1"


def test_configs_fit_together():
    import yaml
    root = SCRIPT.parents[3]
    agent = yaml.safe_load((root / "configs/architecture/agents/first_app_check.yaml").read_text())["agent"]
    flow = yaml.safe_load((root / "configs/architecture/workflows/first_app_check.yaml").read_text())["workflow"]
    assert agent["type"] == "script" and "/app/configs/architecture/bin/first_app_check.py" in agent["script_template"]
    assert "${" not in agent["script_template"]
    assert [n["agent"] for n in flow["nodes"]] == ["first_app_check"]
    text = (root / "docs" / "departments.md").read_text()
    for name in ("architecture/workflows/first_app_check.yaml", "architecture/agents/first_app_check.yaml",
                 "architecture/bin/first_app_check.py"):
        assert name in text, f"docs/departments.md does not list {name}"


def test_controls_cover_the_planned_variants():
    # (verdict, first FAIL row, traffic gate); #92 moved outside_request to the gate and added the profile cases.
    want = {"clean": ("PASS", None, "PASS"), "outside_request": ("FAIL", None, "FAIL at C1-1"),
            "wrong_focus": ("FAIL", "C1-2", "NOT CHECKED"), "wrong_order": ("FAIL", "C1-3", "NOT CHECKED"),
            "page_error": ("FAIL", "C1-4", "NOT CHECKED"), "forget_reload": ("FAIL", "C1-5", "NOT CHECKED"),
            "wrong_pin": ("REFUSED", None, "NOT CHECKED"), "reworded_profile": ("PASS", None, "PASS"),
            "reworded_no_profile": ("FAIL", "C1-1", "NOT CHECKED"), "bad_profile": ("REFUSED", None, "NOT CHECKED")}
    assert {c["case"]: c["expect"] for c in fac.CONTROLS} == want
    src = (fac.FIXTURE / "app.js").read_text()
    assert src.count('const VARIANT = "clean";') == 1
    for c in fac.CONTROLS:
        assert c["variant"] == "clean" or f'VARIANT === "{c["variant"]}"' in src


# ---------------------------------------------------------------- #92: the profile input

DROP = object()
GOOD = fac.default_profile()
REWORDED = {"heading": "My tasks", "textbox": "Task", "add_button": "Add task", "delete_button": "Remove {item}",
            "empty_text": "No tasks yet. Write one above, then press Enter or Add task."}


def profile_text(**changes) -> str:
    p = copy.deepcopy(GOOD)
    for key, value in changes.items():
        if value is DROP:
            p.pop(key)
        else:
            p[key] = value
    return json.dumps(p)


def problems_of(text) -> list[str]:
    target, problems = fac.parse_profile(text)
    assert (target is None) == bool(problems)
    return problems


@pytest.mark.parametrize("text", [None, "", "  \n"])
def test_no_profile_is_the_first_build_exactly(text):
    target, problems = fac.parse_profile(text)
    assert problems == [] and target == fac.default_target()
    assert target["source"] == "default" and target["origin"] == fac.LIVE_ORIGIN == "https://spark.tailbb5055.ts.net:8960"
    assert target["pins"] == fac.FROZEN_PINS and target["kit_id"] == fac.KIT_ID and target["kit_sha256"] == fac.KIT_SHA256
    assert target["kit_not_checked"] == fac.KIT_NOT_CHECKED and target["wording"] == fac.DEFAULT_WORDING
    assert fac.DEFAULT_WORDING == {"heading": "To-do list", "textbox": "New item", "add_button": "Add",
                                   "delete_button": "Delete {item}", "empty_text": fac.EMPTY_TEXT}
    assert fac.kit_steps(target["wording"]) == fac.STEPS
    assert fac.STEPS[5]["action"] == "Activate the button with accessible name Delete Buy milk."
    assert fac.STEPS[0]["expected"] == {"heading": "To-do list", "textboxLabel": "New item", "button": "Add",
                                         "rows": [], "emptyText": fac.EMPTY_TEXT}
    assert fac.action_js("C1-6", ORIGIN) == fac.action_js("C1-6", ORIGIN, fac.DEFAULT_WORDING)
    assert fac.compare_step({"input": ""}, {"textbox": {"count": 1, "value": "x"}}) == ["New item holds 'x', expected ''"]


def test_profile_equal_to_the_constants_gives_the_same_target():
    target, problems = fac.parse_profile(json.dumps(GOOD))
    default = fac.default_target()
    assert problems == [] and target["source"] == "input" and len(target["profile_sha256"]) == 64
    for key in ("origin", "kit_id", "kit_sha256", "kit_not_checked", "wording"):
        assert target[key] == default[key]
    assert {n: p["sha256"] for n, p in target["pins"].items()} == {n: p["sha256"] for n, p in default["pins"].items()}


@pytest.mark.parametrize("origin", [
    "http://spark.tailbb5055.ts.net:8960", "https://spark.tailbb5055.ts.net", "https://spark.tailbb5055.ts.net:8960/",
    "https://spark.tailbb5055.ts.net:8960/app", "https://spark.tailbb5055.ts.net:8960?x=1",
    "https://spark.tailbb5055.ts.net:8960#x", "https://evil.test:8960", "https://spark.tailbb5055.ts.net.evil.test:8960",
    "https://user@spark.tailbb5055.ts.net:8960", "https://SPARK.tailbb5055.ts.net:8960", "https://127.0.0.1:8960",
    "https://spark.tailbb5055.ts.net:0", "https://spark.tailbb5055.ts.net:08960", "https://spark.tailbb5055.ts.net:65536",
    "https://spark.tailbb5055.ts.net:443", " https://spark.tailbb5055.ts.net:8960", "https://spark.tailbb5055.ts.net:8960\n",
    "https://spark.tailbb5055.ts.net:\uff18\uff19\uff16\uff10", "file:///etc/passwd", "javascript:alert(1)", 8960, None])
def test_origin_must_be_spark_over_https_with_a_port(origin):
    problems = problems_of(profile_text(origin=origin))
    assert len(problems) == 1 and problems[0].startswith("origin")


@pytest.mark.parametrize("origin", ["https://spark.tailbb5055.ts.net:1", "https://spark.tailbb5055.ts.net:8999",
                                    "https://spark.tailbb5055.ts.net:65535"])
def test_origin_any_port_on_spark_is_accepted(origin):
    assert problems_of(profile_text(origin=origin)) == []


GOOD_PINS = GOOD["pins"]


@pytest.mark.parametrize("pins", [
    {k: v for k, v in GOOD_PINS.items() if k != "app.js"},
    dict(GOOD_PINS, **{"favicon.ico": "a" * 64}),
    dict(GOOD_PINS, **{"app.js": GOOD_PINS["app.js"].upper()}),
    dict(GOOD_PINS, **{"app.js": "a" * 63}),
    dict(GOOD_PINS, **{"app.js": "a" * 65}),
    dict(GOOD_PINS, **{"app.js": "sha256:" + "a" * 64}),
    dict(GOOD_PINS, **{"app.js": {"sha256": "a" * 64}}),
    dict(GOOD_PINS, **{"style.css": None}),
    list(GOOD_PINS.values()),
    "a" * 64])
def test_pins_must_be_exactly_the_three_files_as_sha256(pins):
    problems = problems_of(profile_text(pins=pins))
    assert problems and all(x.startswith("pin") for x in problems)


@pytest.mark.parametrize("change", [
    {"kit_sha256": "49813ec9"}, {"kit_sha256": GOOD["kit_sha256"].upper()}, {"kit_id": ""}, {"kit_id": 7},
    {"kit_id": " padded"}, {"kit_not_checked": []}, {"kit_not_checked": "blank input"},
    {"kit_not_checked": ["ok", ""]}, {"kit_not_checked": ["ok", {"x": 1}]}, {"kit_not_checked": ["x"] * 51}])
def test_kit_fields_are_checked(change):
    problems = problems_of(profile_text(**change))
    assert len(problems) == 1 and problems[0].startswith(next(iter(change)))


@pytest.mark.parametrize("key", list(fac.WORDING_KEYS))
def test_every_wording_key_is_required(key):
    wording = {k: v for k, v in GOOD["wording"].items() if k != key}
    assert problems_of(profile_text(wording=wording)) == [f"wording is missing {key}"]


@pytest.mark.parametrize("wording", [
    dict(GOOD["wording"], note="x"), dict(GOOD["wording"], textbox=""), dict(GOOD["wording"], textbox=" New item"),
    dict(GOOD["wording"], textbox="New  item"), dict(GOOD["wording"], heading="To-do\nlist"),
    dict(GOOD["wording"], add_button=["Add"]), dict(GOOD["wording"], empty_text="x" * 301),
    dict(GOOD["wording"], delete_button="Delete"), dict(GOOD["wording"], delete_button="{item}: delete {item}"),
    dict(GOOD["wording"], delete_button="Delete {name}"), ["New item"], "New item"])
def test_wording_must_be_exact_one_line_text(wording):
    problems = problems_of(profile_text(wording=wording))
    assert problems and all(x.startswith("wording") for x in problems)


@pytest.mark.parametrize("key", list(fac.PROFILE_KEYS))
def test_every_profile_key_is_required(key):
    assert problems_of(profile_text(**{key: DROP})) == [f"profile is missing {key}"]


@pytest.mark.parametrize("text", [profile_text(note="x"), json.dumps([GOOD]), json.dumps("x"), "7", "{", "{'origin': 1}",
                                  "null", json.dumps(dict(GOOD, pad="x" * fac.PROFILE_MAX_CHARS))])
def test_profile_must_be_one_json_object_with_only_its_keys(text):
    assert problems_of(text)


def test_problems_are_all_listed_at_once():
    text = profile_text(origin="http://evil.test", pins={}, wording=dict(GOOD["wording"], delete_button="x"))
    problems = problems_of(text)
    assert len(problems) == 3 and [p.split()[0] for p in problems] == ["origin", "pins", "wording.delete_button"]


def test_delete_template_renders_each_items_name():
    w = dict(fac.DEFAULT_WORDING, delete_button="Remove {item}")
    steps = fac.kit_steps(w)
    assert steps[5]["action"] == "Activate the button with accessible name Remove Buy milk."
    assert steps[6]["action"] == "Activate the button with accessible name Remove Call Sam."
    assert '{name: "Remove Buy milk", exact: true}' in fac.action_js("C1-6", ORIGIN, w)
    assert '{name: "Remove Call Sam", exact: true}' in fac.action_js("C1-7", ORIGIN, w)
    w = dict(fac.DEFAULT_WORDING, delete_button="{item} \u2013 delete")
    assert '{name: "Call Sam \\u2013 delete", exact: true}' in fac.action_js("C1-7", ORIGIN, w)


def test_a_builds_wording_reaches_every_check_and_action():
    steps = fac.kit_steps(REWORDED)
    assert steps[0]["expected"] == {"heading": "My tasks", "textboxLabel": "Task", "button": "Add task", "rows": [],
                                    "emptyText": REWORDED["empty_text"]}
    assert steps[1]["expected"]["focus"] == steps[2]["expected"]["focus"] == steps[6]["expected"]["focus"] == "Task"
    assert steps[6]["expected"]["emptyText"] == steps[7]["expected"]["emptyText"] == REWORDED["empty_text"]
    assert steps[2]["action"] == "Enter Call Sam and activate Add task."
    # Only the controls' names change: the rows' items, inputs, order and checks are the kit's.
    for new, old in zip(steps, fac.STEPS, strict=True):
        assert new["id"] == old["id"] and new.get("input") == old.get("input")
        assert new["expected"].get("rows") == old["expected"].get("rows")
        assert new["expected"].get("savingWarning") == old["expected"].get("savingWarning")
    obs = fac.observe_js(REWORDED)
    assert '{name: "Task", exact: true}' in obs and '{name: "Add task", exact: true}' in obs
    assert json.dumps(REWORDED["empty_text"]) in obs and "New item" not in obs
    assert '{name: "Task", exact: true}' in fac.action_js("C1-2", ORIGIN, REWORDED)
    assert '{name: "Add task", exact: true}' in fac.action_js("C1-3", ORIGIN, REWORDED)
    assert fac.compare_step({"input": ""}, {"textbox": {"count": 1, "value": "x"}}, "Task") == ["Task holds 'x', expected ''"]


def test_wording_with_quotes_stays_a_js_string():
    w = dict(fac.DEFAULT_WORDING, textbox='New "item"', add_button="Add'); alert(1); ('")
    obs = fac.observe_js(w)
    assert '{name: "New \\"item\\"", exact: true}' in obs
    assert "{name: \"Add'); alert(1); ('\", exact: true}" in fac.action_js("C1-3", ORIGIN, w)


def test_profile_pins_compare_sha256_alone():
    pins = {n: {"sha256": p["sha256"]} for n, p in fac.FROZEN_PINS.items()}
    fetched = {n: {"status": 200, "bytes": 1, "sha256": p["sha256"]} for n, p in fac.FROZEN_PINS.items()}
    assert fac.check_pins(pins, fetched, ORIGIN, ORIGIN + "/")["ok"]
    fetched["app.js"]["sha256"] = "0" * 64
    assert not fac.check_pins(pins, fetched, ORIGIN, ORIGIN + "/")["ok"]


def test_root_document_must_be_the_index_pin():
    # #92, QA's suggestion 1: the "/" document the journey loads is hashed itself.
    pins = {n: dict(p) for n, p in fac.FROZEN_PINS.items()}
    fetched = {n: {"status": 200, "bytes": p["bytes"], "sha256": p["sha256"]} for n, p in pins.items()}
    root = dict(fetched["index.html"])
    ok = fac.pin_stage(pins, fetched, root, ORIGIN, ORIGIN + "/")
    assert ok["ok"] and ok["root"]["match"] and ok["root"]["pinned_as"] == "index.html"
    for bad_root in (dict(root, sha256="1" * 64), dict(root, status=404), {"error": "body unavailable"}, None):
        stage = fac.pin_stage(pins, fetched, bad_root, ORIGIN, ORIGIN + "/")
        assert not stage["ok"] and all(f["match"] for f in stage["files"])
        r = {"origin": ORIGIN, "reach": {"status": 200}, "pins": stage, "steps": [], "steps_attempted": 0}
        verdict, why = fac.final_verdict(r)
        assert verdict == "REFUSED" and '"/"' in why


def test_traffic_gate_passes_only_a_whole_clean_journey():
    r = clean_receipt()
    assert fac.traffic_gate(r) == {"status": "PASS", "first_seen": None, "findings": [],
                                   "rows_observed": [f"C1-{i}" for i in range(1, 9)]}

    def m(sid, obs, new):
        if sid == "C1-3":
            obs["rows"] = list(reversed(obs["rows"]))
    assert fac.traffic_gate(run_journey(m))["status"] == "NOT CHECKED"
    r = clean_receipt()
    r["observers"] = {"before_first_navigation": False}
    assert fac.traffic_gate(r)["status"] == "NOT CHECKED" and fac.final_verdict(r)[0] == "BLOCKED"


@pytest.mark.parametrize("where", ["C1-1", "C1-5", "C1-8", "late", "after a row FAIL", "websocket"])
def test_outside_traffic_never_gives_a_pass(where):
    r = clean_receipt()
    finding = "request outside the origin: GET https://tracker.test/p.gif"
    if where == "late":
        r["late_traffic"] = [finding]
        r["late_findings"] = [finding]
    elif where == "after a row FAIL":
        r["steps"] = r["steps"][:3]
        r["steps"][2] = dict(r["steps"][2], status="FAIL", reasons=["rows wrong"])
        r["late_traffic"] = [finding]
    elif where == "websocket":
        r["steps"][3]["traffic"] = fac.traffic_findings([], [{"url": "wss://x.test/"}], ORIGIN)
    else:
        step = next(s for s in r["steps"] if s["id"] == where)
        step["traffic"] = [finding]
    gate = fac.traffic_gate(r)
    verdict, why = fac.final_verdict(r)
    assert gate["status"] == "FAIL" and verdict == "FAIL" and "traffic gate: " in why


def test_receipt_carries_the_kits_not_checked_list_and_the_gate(tmp_path):
    r = fac.new_receipt("unit", dict(fac.default_target(), origin=ORIGIN))
    r.update(clean_receipt())
    for s in r["steps"]:
        s["observed"] = {}
    fac.finish(r, tmp_path)
    receipt = json.loads((tmp_path / "receipt.json").read_text())
    assert receipt["verdict"] == "PASS" and receipt["traffic_gate"]["status"] == "PASS"
    assert receipt["kit_not_checked"] == fac.KIT_NOT_CHECKED and len(fac.KIT_NOT_CHECKED) == 7
    assert receipt["profile"] == {"source": "default", "sha256": None, "wording": fac.DEFAULT_WORDING}
    summary = (tmp_path / "summary.md").read_text()
    assert "## Traffic gate" in summary and "## NOT CHECKED (the kit's list; not waived)" in summary
    assert all(f"- {x}" in summary for x in fac.KIT_NOT_CHECKED)


def test_bad_profile_is_refused_before_the_browser_is_contacted(tmp_path, capsys):
    # The browser address is unreachable: reaching for it would give BLOCKED, not REFUSED.
    args = argparse.Namespace(browser="http://127.0.0.1:9/mcp", profile=profile_text(origin="http://127.0.0.1:8000"))
    assert asyncio.run(fac.live(args, tmp_path)) == fac.EXIT["REFUSED"]
    r = json.loads((tmp_path / "receipt.json").read_text())
    assert r["verdict"] == "REFUSED" and r["why"].startswith("profile not valid, browser not contacted: origin")
    assert r["browser_contact"] is False and r["steps_attempted"] == 0 and r["traffic"]["requests"] == 0
    assert "reach" not in r and "pins" not in r and "observers" not in r and r["origin"] is None
    assert r["profile"]["sha256"] == fac.sha256(args.profile.encode()) and r["traffic_gate"]["status"] == "NOT CHECKED"
    last = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert last["verdict"] == "REFUSED" and last["browser_contact"] is False


def test_command_line(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(sys, "argv", ["first_app_check.py", "--print-default-profile"])
    assert fac.main() == 0
    printed = capsys.readouterr().out
    assert json.loads(printed) == GOOD and fac.parse_profile(printed)[1] == []
    monkeypatch.setattr(sys, "argv", ["first_app_check.py", "--mode", "controls", "--out", str(tmp_path),
                                      "--profile", json.dumps(GOOD)])
    with pytest.raises(SystemExit) as stop:
        fac.main()
    assert stop.value.code == 2


def test_reworded_fixture_is_the_page_its_profile_describes(tmp_path):
    target, problems = fac.parse_profile((fac.FIXTURE_REWORDED / "profile.json").read_text())
    assert problems == [] and target["wording"] == REWORDED
    assert all(REWORDED[k] != fac.DEFAULT_WORDING[k] for k in fac.WORDING_KEYS)
    site = fac.materialize("clean", tmp_path, fac.FIXTURE_REWORDED)
    assert {n: fac.sha256((site / n).read_bytes()) for n in fac.PIN_FILES} == \
        {n: p["sha256"] for n, p in target["pins"].items()}, "profile.json pins no longer match the served page"
    html = (site / "index.html").read_text()
    assert "<h1>My tasks</h1>" in html and '<label for="new-item">Task</label>' in html
    assert '<button type="submit">Add task</button>' in html and REWORDED["empty_text"] in html
    assert 'data-delete-word="Remove"' in html and 'list.dataset.deleteWord || "Delete"' in (site / "app.js").read_text()
    bad = fac.control_profile("served_origin", "http://10.0.0.5:41234")
    assert problems_of(bad)[0].startswith("origin 'http://10.0.0.5:41234'")


def test_configs_pass_the_profile():
    import yaml
    root = SCRIPT.parents[3]
    agent = yaml.safe_load((root / "configs/architecture/agents/first_app_check.yaml").read_text())["agent"]
    flow = yaml.safe_load((root / "configs/architecture/workflows/first_app_check.yaml").read_text())["workflow"]
    assert flow["inputs"]["profile"] == {"type": "string", "required": False}
    assert flow["nodes"][0]["input_map"] == {"mode": "input.mode", "profile": "input.profile"}
    template = agent["script_template"]
    assert 'os.environ.get("{{ profile | env }}")' in template and 'cmd += ["--profile", profile]' in template
    assert "architecture/fixtures/first_app_reworded/" in (root / "docs" / "departments.md").read_text()
