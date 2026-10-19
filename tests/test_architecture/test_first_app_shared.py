"""first_app_check's shared journey on canned snapshots (System architecture, queue #97, 2026-10-18).

configs/architecture/bin/first_app_shared.py (loaded by first_app_check.py only for a profile with
"journey": "shared", or mode=controls_shared) runs QA's frozen kit qa-project2-critical-v1 on Team Project 2's
shared to-do list: three people in separate browser contexts, the host stopping and starting the app at R-1,
D-1 and D-5. The browser part is proven by mode=controls_shared on temper-dev (18 controls, run twice); these
tests pin the pure part: the strict profile and its refusals, host receipts, the row comparator, the traffic
policy, the list record across the restart, and the verdict. They also pin that the first app's path is
unchanged: only a JSON object with a "journey" key takes the shared path.
"""

import argparse
import asyncio
import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

BIN = Path(__file__).resolve().parents[2] / "configs" / "architecture" / "bin"
spec = importlib.util.spec_from_file_location("first_app_check", BIN / "first_app_check.py")
fac = importlib.util.module_from_spec(spec)
sys.modules["first_app_check"] = fac
spec.loader.exec_module(fac)
sh = fac.shared_module()

ORIGIN = "http://100.110.162.4:8961"
W = sh.KIT_WORDING
U = sh.USERS


def profile(**changes) -> dict:
    p = sh.default_shared_profile()
    for k, v in changes.items():
        if v is None:
            p.pop(k, None)
        else:
            p[k] = v
    return p


def problems(p) -> list[str]:
    target, probs = sh.parse_shared_profile(p if isinstance(p, str) else json.dumps(p))
    assert (target is None) == bool(probs)
    return probs


def observed_for(row: dict) -> dict:
    """What a working page shows after one browser row, as the browser stage reports it."""
    exp = row["expected"]
    ctx = row["ctx"]
    rows = exp.get("rows", [])
    return {
        "headings": [W["heading"]],
        "name_textbox": {"count": 1, "visible": bool(exp.get("name_form"))},
        "name_button": {"count": 1, "visible": bool(exp.get("name_form"))},
        "item_textbox": {"count": 1, "visible": exp.get("item_textbox", True), "enabled": True, "value": ""},
        "add_button": {"count": 1, "visible": True, "enabled": True},
        "whoami": {"visible": True, "name": U[ctx], "line": W["whoami"].replace("{name}", U[ctx]), "i_elements": 0},
        "rows": [{"text": t, "desc": W["added_by"].replace("{name}", by), "checked": c, "named": True,
                  "html_elements": 0} for t, by, c in rows],
        "empty_text_visible": bool(exp.get("empty_text")),
        "message": {"visible": "message" in exp, "text": exp.get("message", "")},
        "banner": {"visible": bool(exp.get("banner")), "text": exp.get("banner") or ""},
        "resource_refs": [],
    }


def clean_receipt() -> dict:
    steps = []
    for row in sh.shared_rows(W, U):
        if "host" in row:
            steps.append({"id": row["id"], "kind": "host", "status": "PASS", "reasons": [], "traffic": []})
            continue
        obs = observed_for(row)
        j = sh.judge_row(row, obs, None, {}, ORIGIN, W)
        steps.append({"id": row["id"], "ctx": row["ctx"], "observed": obs, **j})
    return {"profile": {"problems": []}, "reach": {}, "pins": {"ok": True}, "steps": steps,
            "observers": {"before_first_navigation": True}, "cleanup": {"confirmed": True},
            "screenshots": [{"after": k} for k in sh.SHOTS]}


# ---------------------------------------------------------------- the first app's path is unchanged


def test_only_a_json_object_with_journey_takes_the_shared_path():
    assert fac.wants_shared(json.dumps(profile()))
    assert not fac.wants_shared(None)
    assert not fac.wants_shared("")
    assert not fac.wants_shared("not json")
    assert not fac.wants_shared('["journey"]')
    assert not fac.wants_shared(json.dumps(fac.default_profile()))


def test_first_app_profile_still_refuses_a_journey_key():
    p = fac.default_profile()
    p["journey"] = "shared"
    _, probs = fac.parse_profile(json.dumps(p))
    assert probs


# ---------------------------------------------------------------- the profile


def test_kit_profile_is_accepted():
    target, probs = sh.parse_shared_profile(json.dumps(profile()))
    assert probs == []
    assert target["origin"] == ORIGIN and target["journey"] == "shared"
    assert target["users"] == U and target["host_wait_minutes"] == 15
    assert set(target["pins"]) == {"index.html", "style.css", "app.js", "favicon.svg"}  # the page links it


def test_kit_rows_are_the_frozen_thirty():
    assert len(sh.ROW_IDS) == 30
    assert sh.ROW_IDS[:3] == ["J-1", "J-2", "J-3"] and sh.ROW_IDS[-1] == "D-6"
    assert [r["id"] for r in sh.shared_rows(W, U) if "host" in r] == ["R-1", "D-1", "D-5"]


@pytest.mark.parametrize("origin", [
    "https://spark.tailbb5055.ts.net:8961", "http://100.110.162.4:8961", "http://100.110.162.4:1"])
def test_origin_rule_allows_spark_https_and_the_tailnet_address(origin):
    assert problems(profile(origin=origin)) == []


@pytest.mark.parametrize("origin", [
    "http://100.110.162.4", "http://100.110.162.4:80", "http://100.110.162.4:99999", "http://100.110.162.4:8961/",
    "https://100.110.162.4:8961", "http://100.110.162.5:8961", "http://spark.tailbb5055.ts.net:8961",
    "http://127.0.0.1:8961", "http://100.110.162.4:08961", 8961])
def test_origin_rule_refuses_everything_else(origin):
    assert problems(profile(origin=origin))


@pytest.mark.parametrize("key", list(sh.PROFILE_KEYS))
def test_each_missing_key_is_refused(key):
    assert problems(profile(**{key: None}))


def test_extra_key_and_unknown_journey_are_refused():
    p = profile()
    p["extra"] = 1
    assert problems(p)
    assert any("journey" in x for x in problems(profile(journey="other")))


@pytest.mark.parametrize("pins", [
    {"index.html": "0" * 64, "style.css": "0" * 64},
    {"index.html": "0" * 64, "style.css": "0" * 64, "app.js": "0" * 64, "server.py": "0" * 64},
    {"index.html": "0" * 64, "style.css": "0" * 64, "app.js": "ABC"},
    ["index.html"]])
def test_bad_pins_are_refused(pins):
    assert problems(profile(pins=pins))


def test_favicon_pin_is_optional():
    pins = dict(sh.BUILD_PINS)
    pins.pop("favicon.svg")
    assert problems(profile(pins=pins)) == []


@pytest.mark.parametrize("build", [{"commit": "38dab31e"}, {"commit": "XYZ", "sha256sums_sha256": "0" * 64},
                                   {"commit": "38dab31e", "sha256sums_sha256": "short"}, "38dab31e"])
def test_bad_build_is_refused(build):
    assert problems(profile(build=build))


@pytest.mark.parametrize("key,value", [("whoami", "You are"), ("added_by", "added by {name} {name}"),
                                       ("delete_button", "Delete"), ("item_too_long", "Too long."),
                                       ("heading", ""), ("unreachable", 3)])
def test_bad_wording_is_refused(key, value):
    w = dict(W)
    w[key] = value
    assert problems(profile(wording=w))


@pytest.mark.parametrize("users", [{"A": "Ana", "B": "Ana", "C": "Cy"}, {"A": "Ana", "B": "Ben"},
                                   {"A": "Ana", "B": "Ben", "C": "x" * 51}, {"A": "", "B": "Ben", "C": "Cy"}])
def test_bad_users_are_refused(users):
    assert problems(profile(users=users))


@pytest.mark.parametrize("h", [0, 61, 1.5, True, "15"])
def test_bad_host_wait_is_refused(h):
    assert problems(profile(host_wait_minutes=h))


def test_not_json_too_long_and_not_object_are_refused():
    assert problems("{")
    assert problems("[]")
    assert problems(" ")
    assert problems(json.dumps(profile()) + " " * fac.PROFILE_MAX_CHARS)


def test_bad_shared_profile_is_refused_without_contacting_the_browser(tmp_path):
    args = argparse.Namespace(browser="http://127.0.0.1:9/mcp", profile=json.dumps(profile(origin="http://x:1")),
                              serve_ip=None)
    code = asyncio.run(fac.live(args, tmp_path))
    r = json.loads((tmp_path / "receipt.json").read_text())
    assert r["verdict"] == "REFUSED" and "browser not contacted" in r["why"]
    assert not r.get("steps")
    assert code != 0


# ---------------------------------------------------------------- host receipts


def receipt(**kv) -> bytes:
    rec = {"row": "R-1", "done": True, "by": "ops", "at": "2026-10-19T07:00:00Z"}
    rec.update(kv)
    return json.dumps({k: v for k, v in rec.items() if v is not None}).encode()


def test_good_host_receipt_is_read():
    rec, problem = sh.parse_host_receipt(receipt(note="restarted", exit_code=0), "R-1")
    assert problem is None and rec["done"] is True


@pytest.mark.parametrize("raw", [b"not json", b"[]", receipt(row="D-1"), receipt(done="yes"), receipt(by=None),
                                 receipt(at=None), receipt(note=3), receipt(exit_code="0"), receipt(exit_code=True),
                                 b" " * (sh.RECEIPT_MAX + 1)])
def test_bad_host_receipts_are_not_receipts(raw):
    rec, problem = sh.parse_host_receipt(raw, "R-1")
    assert rec is None and problem


# ---------------------------------------------------------------- rows and verdict


def test_clean_receipt_passes():
    r = clean_receipt()
    assert all(s["status"] == "PASS" for s in r["steps"]), [s for s in r["steps"] if s["status"] != "PASS"]
    assert sh.final_verdict(r)[0] == "PASS"
    assert sh.traffic_gate(r)["status"] == "PASS"


def test_list_record_compares_the_list_before_and_after_the_restart():
    rec = sh.list_record(clean_receipt()["steps"], W)
    assert rec["before_restart"]["row"] == "E-6" and len(rec["before_restart"]["rows"]) == 4
    assert [x["row"] for x in rec["after"]] == ["R-2", "R-3", "D-6"]
    assert all(x["equal_to_before"] for x in rec["after"])
    assert rec["before_restart"]["sha256"] == sh.canon_sha256(rec["before_restart"]["rows"])


def judge(rid: str, mutate) -> dict:
    row = next(r for r in sh.shared_rows(W, U) if r["id"] == rid)
    obs = observed_for(row)
    mutate(obs)
    return sh.judge_row(row, obs, None, {}, ORIGIN, W)


def test_list_lost_on_restart_fails_r2():
    assert judge("R-2", lambda o: o.update(rows=[]))["status"] == "FAIL"


def test_wrong_author_fails():
    def wrong(o):
        o["rows"][0]["desc"] = W["added_by"].replace("{name}", "Ben")
    assert judge("J-7", wrong)["status"] == "FAIL"


def test_missing_author_fails():
    def missing(o):
        o["rows"][0]["desc"] = "added by"
    j = judge("J-4", missing)
    assert j["status"] == "FAIL" and "''" in j["reasons"][0]


def test_unticked_after_reload_fails_j11():
    def untick(o):
        o["rows"][0]["checked"] = False
    assert judge("J-11", untick)["status"] == "FAIL"


def test_checkbox_not_named_by_its_text_fails():
    def unnamed(o):
        o["rows"][0]["named"] = False
    j = judge("J-11", unnamed)
    assert j["status"] == "FAIL" and "accessible name" in j["reasons"][0]


def test_html_rendered_fails_e4_and_e5():
    assert judge("E-4", lambda o: o["whoami"].update(i_elements=1))["status"] == "FAIL"
    assert judge("E-5", lambda o: o["rows"][-1].update(html_elements=1))["status"] == "FAIL"


def test_name_form_back_after_reload_fails_j3():
    def back(o):
        o["name_textbox"]["visible"] = True
        o["name_button"]["visible"] = True
    assert judge("J-3", back)["status"] == "FAIL"


def test_missing_banner_fails_d2_and_banner_left_fails_d6():
    assert judge("D-2", lambda o: o.update(banner={"visible": False, "text": ""}))["status"] == "FAIL"
    assert judge("D-6", lambda o: o.update(banner={"visible": True, "text": W["unreachable"]}))["status"] == "FAIL"


def test_missing_observation_blocks_never_passes():
    j = judge("J-11", lambda o: o.pop("rows"))
    assert j["status"] == "BLOCKED"
    r = clean_receipt()
    r["steps"][10] = {**r["steps"][10], **j}
    assert sh.final_verdict(r)[0] == "BLOCKED"


def test_failed_api_request_is_expected_only_while_the_server_is_down():
    log = {"failed": [{"method": "POST", "url": ORIGIN + "/api/items", "error": "net::ERR_CONNECTION_REFUSED"}]}
    for rid, status in (("D-2", "PASS"), ("J-4", "FAIL")):
        row = next(r for r in sh.shared_rows(W, U) if r["id"] == rid)
        assert sh.judge_row(row, observed_for(row), None, log, ORIGIN, W)["status"] == status


def test_server_error_outside_the_outage_fails():
    log = {"responses": [{"method": "GET", "url": ORIGIN + "/api/items", "status": 500}]}
    row = next(r for r in sh.shared_rows(W, U) if r["id"] == "J-3")
    assert sh.judge_row(row, observed_for(row), None, log, ORIGIN, W)["status"] == "FAIL"


@pytest.mark.parametrize("method,path,ok", [
    ("GET", "/", True), ("GET", "/app.js", True), ("GET", "/api/items", True), ("POST", "/api/items", True),
    ("PATCH", "/api/items/12", True), ("DELETE", "/api/items/0", True), ("PUT", "/api/items/1", False),
    ("DELETE", "/api/items", False), ("PATCH", "/api/items/abc", False), ("GET", "/server.py", False),
    ("GET", "/api/items?x=1", False), ("POST", "/api/other", False)])
def test_traffic_policy_on_the_origin(method, path, ok):
    assert (sh.traffic_findings([{"method": method, "url": ORIGIN + path}], [], ORIGIN) == []) == ok


def test_outside_request_and_websocket_fail_the_traffic_gate_apart_from_rows():
    assert sh.traffic_findings([{"method": "GET", "url": "http://100.110.162.4:9999/font.woff2"}], [], ORIGIN)
    assert sh.traffic_findings([], [{"url": "ws://100.110.162.4:8961/ws"}], ORIGIN)
    r = clean_receipt()
    r["steps"][0]["traffic"] = ["request outside the origin: GET https://fonts.example/x"]
    assert sh.traffic_gate(r)["status"] == "FAIL" and sh.traffic_gate(r)["first_seen"] == "J-1"
    assert sh.final_verdict(r)[0] == "FAIL"


def test_host_step_blocked_blocks_the_verdict():
    r = clean_receipt()
    i = sh.ROW_IDS.index("R-1")
    r["steps"] = r["steps"][:i] + [{"id": "R-1", "kind": "host", "status": "BLOCKED",
                                    "reasons": ["no host receipt within 900 s"], "traffic": []}]
    v, why = sh.final_verdict(r)
    assert v == "BLOCKED" and why.startswith("R-1")


def test_wrong_pin_or_unpinned_file_is_refused():
    r = clean_receipt()
    r["pins"] = {"ok": False, "files": [{"file": "app.js", "match": False}]}
    assert sh.final_verdict(r) == ("REFUSED", "served files do not match the pins: app.js")
    refs = [ORIGIN + "/app.js", ORIGIN + "/extra.js", ORIGIN + "/favicon.svg", "data:image/png;base64,AA"]
    assert sh.unpinned_refs(refs, ORIGIN, {"app.js": {}}) == [ORIGIN + "/extra.js", ORIGIN + "/favicon.svg"]


def test_cleanup_unknown_and_missing_screenshot_block():
    r = clean_receipt()
    r["cleanup"] = {"confirmed": False}
    assert sh.final_verdict(r)[0] == "BLOCKED"
    r = clean_receipt()
    r["screenshots"] = r["screenshots"][:1]
    assert sh.final_verdict(r)[0] == "BLOCKED"


def test_parse_by_reads_the_name_from_the_added_by_wording():
    t = W["added_by"]
    assert sh.parse_by("added by Ana", t) == "Ana"
    assert sh.parse_by("added by <i>Cy</i>", t) == "<i>Cy</i>"
    assert sh.parse_by("added by", t) == ""
    assert sh.parse_by("by Ana", t) is None
    assert sh.parse_by(None, t) is None


def test_controls_cover_each_kit_control_and_the_architecture_extras():
    names = [c["case"] for c in sh.CONTROLS]
    assert len(names) == len(set(names)) == 18
    assert {"K-CLEAN", "K-LOCAL-ONLY", "K-DELETE-LOCAL", "K-MEMORY-ONLY", "K-OUTSIDE-FONT", "K-WRONG-PIN",
            "A-AUTHOR-MISSING", "A-AUTHOR-VIEWER", "A-BAD-PROFILE"} <= set(names)
    copy.deepcopy(sh.CONTROLS)
