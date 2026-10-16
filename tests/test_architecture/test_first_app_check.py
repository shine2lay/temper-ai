"""first_app_check's comparators on canned snapshots (System architecture, queue #91).

configs/architecture/bin/first_app_check.py drives temper's playwright-mcp browser through QA's frozen
critical journey (kit qa-first-app-critical-v1) and judges what the rendered page showed. The browser
part is proven by the workflow's controls mode on temper-dev; these tests pin the pure judging part:
a clean receipt PASSes, and each kind of broken one gets the verdict the kit's checker controls name
(K-CLEAN, K-BROKEN-RELOAD, K-WRONG-PIN, K-MISSING-STEP, K-RUNNER-FAIL, K-OBSERVER-MISSING,
K-FORBIDDEN-TRAFFIC, K-CRITICAL-ERROR, K-CLEANUP-UNKNOWN), plus wrong order and wrong focus.
"""

import copy
import importlib.util
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
        r["steps"].append({"id": step["id"], "status": v["status"], "reasons": v["reasons"]})
        r["steps_attempted"] += 1
    return r


def run_journey(mutate) -> dict:
    """The clean journey with one row's observation or wire changed; stops at the first failure."""
    r = clean_receipt()
    r["steps"], r["steps_attempted"] = [], 0
    for step in fac.STEPS:
        obs, new = observed_for(step), wire(step["id"])
        mutate(step["id"], obs, new)
        v = fac.judge_step(step, obs, new, ORIGIN)
        r["steps"].append({"id": step["id"], "status": v["status"], "reasons": v["reasons"]})
        r["steps_attempted"] += 1
        if v["status"] == "FAIL":
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


def test_outside_request_fails_even_with_correct_rows():
    def m(sid, obs, new):
        if sid == "C1-1":
            new["requests"].append({"method": "GET", "url": "https://tracker.test/p.gif"})
    r = run_journey(m)
    assert failed_at(r) == "C1-1"
    assert any("outside the origin" in x for x in r["steps"][0]["reasons"])


def test_unexpected_same_origin_path_query_and_post_fail():
    reqs = [{"method": "GET", "url": ORIGIN + "/api/items"}, {"method": "GET", "url": ORIGIN + "/app.js?v=2"},
            {"method": "POST", "url": ORIGIN + "/"}, {"method": "GET", "url": "data:image/png;base64,AA"}]
    found = fac.traffic_findings(reqs, [{"url": "wss://x.test/"}], ORIGIN)
    assert len(found) == 4 and found[-1] == "websocket: wss://x.test/"


def test_outside_resource_reference_fails():
    def m(sid, obs, new):
        obs["resource_refs"].append("https://cdn.test/icon.png")
    assert failed_at(run_journey(m)) == "C1-1"


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
    want = {"clean": ("PASS", None), "outside_request": ("FAIL", "C1-1"), "wrong_focus": ("FAIL", "C1-2"),
            "wrong_order": ("FAIL", "C1-3"), "page_error": ("FAIL", "C1-4"), "forget_reload": ("FAIL", "C1-5"),
            "wrong_pin": ("REFUSED", None)}
    assert {c["case"]: c["expect"] for c in fac.CONTROLS} == want
    src = (fac.FIXTURE / "app.js").read_text()
    assert src.count('const VARIANT = "clean";') == 1
    for c in fac.CONTROLS:
        assert c["variant"] == "clean" or f'VARIANT === "{c["variant"]}"' in src
