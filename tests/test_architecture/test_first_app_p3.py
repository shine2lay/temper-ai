"""first_app_check's Project 3 journey on canned data (System architecture, queue #124, 2026-10-20).

configs/architecture/bin/first_app_p3.py (loaded only for mode=controls_p3 or a profile with "journey_p3") adds
what the fixed checker could not check for Project 3's raised bar: WebKit at phone size with touch, typed text
read back exactly, right-to-left items rendered rtl, the app killed and started again with exit codes in the host
receipts, and two adds in the same tick. The browser part is proven by mode=controls_p3 on temper-dev (run twice);
these tests pin the pure part: the engines' context options, the exact compare and its U+ lists, the direction
rule, the receipt rules, the kill action, SIM-5's compare, the profile, the verdict, the controls' synthetic server
and the agent's routing. The rows, ids and exit codes are provisional (PENDING-SPEC) until QA freezes its kit.
"""

import asyncio
import hashlib
import importlib.util
import json
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "configs" / "architecture" / "bin"
if "first_app_check" not in sys.modules:
    _spec = importlib.util.spec_from_file_location("first_app_check", BIN / "first_app_check.py")
    _fac = importlib.util.module_from_spec(_spec)
    sys.modules["first_app_check"] = _fac
    _spec.loader.exec_module(_fac)
fac = sys.modules["first_app_check"]
spec = importlib.util.spec_from_file_location("first_app_p3", BIN / "first_app_p3.py")
p3 = importlib.util.module_from_spec(spec)
sys.modules["first_app_p3"] = p3
spec.loader.exec_module(p3)
fs = p3.fs

W = p3.KIT_WORDING
ORIGIN = "http://100.110.162.4:8962"


def target(**changes) -> dict:
    t, problems = p3.parse_p3_profile(json.dumps(p3.default_p3_profile()))
    assert problems == []
    t.update(changes)
    return t


def obs(rows=None, **over) -> dict:
    """One context's observation as SETUP's observe returns it; rows as [text, by, ticked]."""
    o = {"headings": [W["heading"]], "name_textbox": {"count": 0, "visible": False},
         "name_button": {"count": 0, "visible": False},
         "item_textbox": {"count": 1, "visible": True, "enabled": True, "value": ""},
         "add_button": {"count": 1, "visible": True}, "try_again": {"count": 0, "visible": False},
         "rows": [{"text": t, "desc": W["added_by"].replace("{name}", b), "checked": c,
                   "dir": p3.strong_direction(t) or "ltr"} for t, b, c in (rows or [])],
         "who": {"visible": True, "name": "Ana", "dir": "ltr"}, "name_msg_parts": [], "item_msg_parts": [],
         "banner": "", "m9_visible": False, "empty_visible": not rows, "scroll": {"scroll_width": 390,
                                                                                 "inner_width": 390},
         "resource_refs": [], "body_text": ""}
    o.update(over)
    return o


# ---------------------------------------------------------------- the hypothesis and the strings


def test_hypothesis_is_written_in_the_module_docstring():
    doc = p3.__doc__
    assert "H-P3-CHECK-1" in doc
    for part in ("What is wrong", "The one change", "Expected result", "What proves it wrong", "rm-5df2e9bc",
                 "PENDING-SPEC"):
        assert part in doc, part


def test_test_strings_are_the_proposals_exact_code_points():
    assert len(p3.S["technologist"]) == 4 and len(p3.S["flag_jp"]) == 2
    assert p3.S["cafe_nfc"] != p3.S["cafe_nfd"] and len(p3.S["cafe_nfc"]) == 4 and len(p3.S["cafe_nfd"]) == 5
    assert len(p3.L200_ZH) == 200 and len(p3.L201_ZH) == 201
    assert len(p3.L200_EMOJI) == 200 and len(p3.L201_EMOJI) == 201
    assert len(p3.L200_EMOJI.encode("utf-16-le")) // 2 == 203  # what an s.length page counts
    assert len(p3.NAME_50) == 50 and len(p3.NAME_51) == 51
    assert p3.S["chinese"][2] == "\uff0c"
    proposal = Path(p3.PROPOSAL)
    if not proposal.exists():
        pytest.skip("QA's proposal is not on this machine")
    data = proposal.read_bytes()
    assert hashlib.sha256(data).hexdigest() == p3.PROPOSAL_SHA256
    text = data.decode()
    for key in ("cyrillic", "greek", "chinese", "japanese", "hindi", "arabic", "hebrew", "mixed"):
        assert p3.S[key] in text, key


# ---------------------------------------------------------------- engines and the browser code


def test_each_engine_has_its_own_context_options():
    assert p3.context_specs("chromium") == {
        c: {"opts": dict(fs.CONTEXT_OPTS, serviceWorkers="block"), "touch": False} for c in ("A", "B")}
    assert fs.CONTEXT_OPTS == {"viewport": {"width": 1280, "height": 800}, "locale": "en-US", "timezoneId": "UTC"}
    want = {"viewport": {"width": 390, "height": 844}, "deviceScaleFactor": 3, "isMobile": True, "hasTouch": True,
            "locale": "en-US", "timezoneId": "UTC", "serviceWorkers": "block"}
    assert p3.context_specs("webkit") == {c: {"opts": want, "touch": True} for c in ("P", "Q")}
    js = p3.setup_js(target(), "webkit")
    assert '"isMobile": true' in js and '"hasTouch": true' in js and '"deviceScaleFactor": 3' in js
    assert '"P"' in js and '"A"' not in js.split("const CTXS =")[1].split(";")[0]


def test_browser_code_taps_on_touch_types_with_insert_text_and_adds_in_one_tick():
    s = p3.SETUP
    assert "if (u.touch) await loc.tap(" in s and "else await loc.click(" in s
    assert "keyboard.insertText(text)" in s and "keyboard.type(" not in s
    assert "await Promise.all(us.map((v, i) => p3.press(v, buttons[i])))" in s
    assert "getComputedStyle(el).direction" in s
    assert "text: el ? el.textContent : null" in s  # exact: the row text is not normalized or trimmed


def test_row_code_puts_the_pinned_files_last():
    row = next(r for r in p3.p3_rows(W, p3.USERS) if r["id"] == "D-3")
    js = p3.row_js(row, {"/app.js": {"text": "x('__OBSERVE__')", "ctype": "text/javascript"}})
    assert "__OBSERVE__" in js  # the page's own text is left alone
    assert js.count('["B"]') >= 1


def test_cached_files_come_from_the_pin_stage_bytes():
    import base64
    got = {"root": {"b64": base64.b64encode("<p>שלום</p>".encode()).decode()},
           "files": {"app.js": {"b64": base64.b64encode(b"1;").decode()}, "favicon.svg": {"error": "x"}}}
    c = p3.cached_files(got)
    assert c["/"]["text"] == "<p>שלום</p>" and c["/"]["ctype"].startswith("text/html")
    assert c["/app.js"]["text"] == "1;" and "/favicon.svg" not in c


# ---------------------------------------------------------------- exact text and direction


def test_text_diff_is_exact_and_lists_code_points():
    assert p3.text_diff("caf\u00e9", "caf\u00e9", "x") is None
    d = p3.text_diff("caf\u00e9", "cafe\u0301", "row 1 text")
    assert "U+0063 U+0061 U+0066 U+00E9" in d and "U+0065 U+0301" in d
    assert p3.text_diff(" a", "a", "x") is not None and p3.text_diff("a\n", "a", "x") is not None
    assert p3.cp_list("\U0001F1EF\U0001F1F5") == "U+1F1EF U+1F1F5" and p3.cp_list("") == "(empty)"
    long = p3.text_diff("\u4e2d" * 199 + "x", "\u4e2d" * 200, "row 9 text")
    assert "first difference at code point 200" in long and "U+0078" in long
    assert "nothing read" in p3.text_diff(None, "a", "x")


def test_direction_comes_from_the_first_strong_character():
    for k in ("arabic", "hebrew", "mixed"):
        assert p3.strong_direction(p3.S[k]) == "rtl", k
    for k in ("cyrillic", "greek", "chinese", "japanese", "hindi", "cafe_nfd", "markup", "lt_gt_amp"):
        assert p3.strong_direction(p3.S[k]) == "ltr", k
    assert p3.strong_direction(p3.S["technologist"]) is None and p3.strong_direction("123 !") is None
    assert p3.strong_direction("123 \u05e9") == "rtl"


def test_rows_compare_exactly_and_report_both_strings():
    exp = [[p3.S["cafe_nfc"], "Ana", False]]
    reasons, full = p3.rows_problems([[p3.S["cafe_nfd"], "Ana", False]], exp)
    assert len(reasons) == 1 and "U+0301" in reasons[0] and full[0]["expected"] == "U+0063 U+0061 U+0066 U+00E9"
    assert p3.rows_problems([["<b>hi</b>", "Ana", False]], [["<b>hi</b>", "Ana", False]]) == ([], [])
    reasons, _ = p3.rows_problems([["hi", "Ana", False]], [["<b>hi</b>", "Ana", False]])
    assert "U+003C U+0062" in reasons[0]
    reasons, _ = p3.rows_problems([["a", "Ana", True]], [["a", "Ana", False]])
    assert "ticked, expected not ticked" in reasons[0]
    assert "1 seen, 2 expected" in p3.rows_problems([["a", "Ana", False]], [["a", "Ana", False]] * 2)[0][0]


def test_sim5_tail_may_come_in_either_order_but_not_short():
    base = [["x", "Ana", False]]
    exp = base + [["A", "Ana", False], ["B", "Bo", False]]
    assert p3.rows_problems(base + [["B", "Bo", False], ["A", "Ana", False]], exp, 2) == ([], [])
    assert p3.rows_problems(base + [["B", "Bo", False], ["A", "Ana", False]], exp, 0)[0]
    lost = p3.rows_problems(base + [["B", "Bo", False]], exp, 2)[0]
    assert lost and "2 seen, 3 expected" in lost[0]
    dup = p3.rows_problems(base + [["B", "Bo", False], ["B", "Bo", False]], exp, 2)[0]
    assert dup and "in any order" in dup[0]


# ---------------------------------------------------------------- the rows' comparator


def test_compare_checks_direction_of_every_row():
    rows = [[p3.S["arabic"], "Ana", False]]
    o = obs(rows)
    assert p3.compare_obs({"rows": rows}, o, W) == ([], [], [])
    o["rows"][0]["dir"] = "ltr"  # no dir=auto
    reasons, _, _ = p3.compare_obs({"rows": rows}, o, W)
    assert len(reasons) == 1 and "computed direction ltr, expected rtl" in reasons[0]


def test_compare_outage_states():
    banner_ok = obs(banner=W["unreachable"], item_textbox={"count": 1, "visible": True, "value": "abc"})
    exp = {"banner": W["unreachable"], "item_value": "abc", "rows": []}
    assert p3.compare_obs(exp, banner_ok, W)[0] == []
    assert "banner" in p3.compare_obs(exp, obs(item_textbox={"count": 1, "visible": True, "value": "abc"}), W)[0][0]
    no_put_back = obs(banner=W["unreachable"])
    assert "item box value" in p3.compare_obs(exp, no_put_back, W)[0][0]
    m9 = obs(m9_visible=True, try_again={"count": 1, "visible": True}, empty_visible=False)
    assert p3.compare_obs({"load_failed": True, "empty_text": False, "rows": []}, m9, W)[0] == []
    false_empty = obs(m9_visible=False, empty_visible=True)
    reasons = p3.compare_obs({"load_failed": True, "empty_text": False}, false_empty, W)[0]
    assert any("load-failed state expected" in x for x in reasons) and any("false empty list" in x for x in reasons)
    assert "banner still shown" in p3.compare_obs({"banner": False}, obs(banner="x"), W)[0][0]


def test_compare_phone_width_messages_and_missing():
    wide = obs(scroll={"scroll_width": 632, "inner_width": 390})
    assert "scrollWidth 632 > innerWidth 390" in p3.compare_obs({"no_hscroll": True}, wide, W)[0][0]
    msg = W["item_too_long"].replace("{n}", "201")
    assert p3.compare_obs({"item_msg": msg}, obs(item_msg_parts=[msg]), W)[0] == []
    assert p3.compare_obs({"item_msg": msg}, obs(item_msg_parts=["Too long: 203 characters. The limit is 200."]),
                          W)[0]
    assert p3.compare_obs({"item_msg": ""}, obs(item_msg_parts=[msg]), W)[0]
    o = obs()
    del o["scroll"]
    assert p3.compare_obs({"no_hscroll": True}, o, W) == ([], ["no observation of no_hscroll"], [])
    who = obs(who={"visible": True, "name": " Ana", "dir": "ltr"})
    assert "U+0020 U+0041" in p3.compare_obs({"whoami": "Ana"}, who, W)[0][0]


def test_judge_row_reads_every_observed_context_and_the_outage_rows():
    rows = [["a", "Ana", False]]
    row = {"id": "S-1", "ctx": "A", "observe": ["A", "B"], "expected": {"rows": rows, "same_rows": True}}
    v = p3.judge_row(row, {"A": obs(rows), "B": obs(rows)}, None, {}, ORIGIN, W)
    assert v["status"] == "PASS"
    v = p3.judge_row(row, {"A": obs(rows), "B": obs([])}, None, {}, ORIGIN, W)
    assert v["status"] == "FAIL" and any(x.startswith("B: ") for x in v["reasons"])
    assert "different lists" in " ".join(v["reasons"])
    failed = {"failed": [{"method": "POST", "url": ORIGIN + "/api/items", "error": "net::ERR_CONNECTION_REFUSED"}]}
    d2 = {"id": "D-2", "ctx": "A", "expected": {"rows": []}}
    v = p3.judge_row(d2, {"A": obs([])}, None, failed, ORIGIN, W)
    assert v["status"] == "PASS" and v["notes"]
    v = p3.judge_row(dict(d2, id="D-6"), {"A": obs([])}, None, failed, ORIGIN, W)
    assert v["status"] == "FAIL" and "outside D-2, D-3" in v["reasons"][0]
    v = p3.judge_row(d2, {"A": obs([])}, None, {"pageerrors": [{"message": "requestIdleCallback is not defined"}]},
                     ORIGIN, W)
    assert v["status"] == "FAIL" and "requestIdleCallback" in v["reasons"][0]
    v = p3.judge_row(d2, {}, None, {}, ORIGIN, W)
    assert v["status"] == "BLOCKED"


def test_rows_are_unique_with_webkit_last_and_kill_its_own_host_action():
    rows = p3.p3_rows(W, p3.USERS)
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids)) == len(p3.ROW_IDS)
    engines = [p3.row_engine(r) for r in rows]
    assert engines.index("webkit") == len(engines) - engines.count("webkit")
    host = {r["id"]: r["host"] for r in rows if r.get("host")}
    assert host == {"R-1": "restart", "D-1": "kill", "D-4": "start"}
    assert all(r["ctx"] in ("A", "B") for r in rows if p3.row_engine(r) == "chromium")
    s1 = next(r for r in rows if r["id"] == "S-1")
    assert s1["acts"][0]["do"] == "sim_add" and s1["observe"] == ["A", "B"]


# ---------------------------------------------------------------- host receipts


def test_receipt_rules_require_exit_code_and_the_actions_value():
    ok = {"row": "R-1", "done": True, "by": "ops", "at": "2026-10-20T10:00:00Z", "note": "", "exit_code": 0}
    assert p3.receipt_problem(ok, "restart") is None
    missing = dict(ok)
    missing.pop("exit_code")
    assert "no exit_code" in p3.receipt_problem(missing, "restart")
    assert "a killed app cannot exit 0" in p3.receipt_problem(ok, "kill")
    assert p3.receipt_problem(dict(ok, exit_code=137), "kill") is None
    assert p3.receipt_problem(dict(ok, exit_code=-9), "kill") is None
    assert "expected 0" in p3.receipt_problem(dict(ok, exit_code=1), "start")
    assert "could not do it" in p3.receipt_problem(dict(ok, done=False, note="busy"), "stop")
    # Project 2's parser still checks the shape (and still accepts a missing exit_code itself)
    rec, problem = fs.parse_host_receipt(json.dumps(missing).encode(), "R-1")
    assert problem is None and "exit_code" not in rec


def test_waiting_file_names_the_kill_and_its_exit_codes():
    row = next(r for r in p3.p3_rows(W, p3.USERS) if r["id"] == "D-1")
    w = p3.waiting_record(row, ORIGIN, 120, "/x/D-1.json")
    assert w["host_action"] == "kill" and w["exit_codes"] == [137, -9] and w["row"] == "D-1"
    assert "REQUIRED" in w["receipt_format"]["exit_code"]


class FakeSession:
    async def call_tool(self, name, args):
        raise AssertionError("no keepalive needed in this test")


def _host_row(tmp_path, monkeypatch, row_id, receipt, probe):
    async def fake_probe(url, code, **kwargs):
        return probe

    async def fake_drain(session, code):
        assert code == p3.DRAIN
        return {}

    # P3 now owns its observed probe lifetime; keep the same fixed result and every assertion.
    monkeypatch.setattr(p3, "probe_session", fake_probe)
    monkeypatch.setattr(p3, "_call", fake_drain)
    row = next(r for r in p3.p3_rows(W, p3.USERS) if r["id"] == row_id)
    host = tmp_path / "host"
    host.mkdir(parents=True)

    async def go():
        async def answer():
            while not (host / f"WAITING-{row_id}.json").exists():
                await asyncio.sleep(0.05)
            await asyncio.sleep(1.1)  # after the request, so the mtime check passes
            (host / f"{row_id}.json").write_text(json.dumps(receipt))

        task = asyncio.create_task(answer())
        r = {}
        step = await p3.host_row(FakeSession(), r, row, target(host_wait_minutes=1), host, time.monotonic() + 900,
                                 "t", "http://browser")
        await task
        return step, json.loads((host / f"WAITING-{row_id}.json").read_text())

    return asyncio.run(go())


def test_host_row_blocks_a_receipt_without_exit_code(tmp_path, monkeypatch):
    rec = {"row": "D-1", "done": True, "by": "ops", "at": "2026-10-20T10:00:00Z", "note": ""}
    step, waiting = _host_row(tmp_path, monkeypatch, "D-1", rec, {"down": True})
    assert waiting["host_action"] == "kill"
    assert step["status"] == "BLOCKED" and "no exit_code" in step["reasons"][0]


def test_host_row_passes_a_kill_with_its_exit_code_when_the_origin_is_down(tmp_path, monkeypatch):
    rec = {"row": "D-1", "done": True, "by": "ops", "at": "2026-10-20T10:00:00Z", "note": "", "exit_code": 137}
    step, _ = _host_row(tmp_path, monkeypatch, "D-1", rec, {"down": True})
    assert step["status"] == "PASS" and step["exit_codes"] == [137, -9]
    step, _ = _host_row(tmp_path / "again", monkeypatch, "D-1", rec, {"down": False, "status": 200})
    assert step["status"] == "BLOCKED" and "still answers" in step["reasons"][0]


# ---------------------------------------------------------------- the profile and the routing


def test_profile_is_strict_and_separate_from_the_other_journeys():
    good = json.dumps(p3.default_p3_profile())
    t, problems = p3.parse_p3_profile(good)
    assert problems == [] and t["journey"] == "p3" and t["wording"]["unreachable"] == W["unreachable"]
    p = p3.default_p3_profile()
    p["extra"] = 1
    assert "not allowed: extra" in p3.parse_p3_profile(json.dumps(p))[1][0]
    p = p3.default_p3_profile(origin="http://10.0.0.5:8962")
    assert p3.parse_p3_profile(json.dumps(p))[1]
    p = p3.default_p3_profile()
    p["journey_p3"] = "v2"
    assert "journey_p3 must be" in p3.parse_p3_profile(json.dumps(p))[1][0]
    p = p3.default_p3_profile()
    p["wording"]["delete_button"] = "Delete"
    assert "exactly once" in p3.parse_p3_profile(json.dumps(p))[1][0]
    assert p3.parse_p3_profile(None)[1] and p3.parse_p3_profile("[1]")[1]
    # the first app and Project 2 paths do not take it
    assert fac.wants_shared(good) is False
    assert fac.parse_profile(good)[1]
    assert fs.parse_shared_profile(good)[1]


def test_agent_routes_controls_p3_and_journey_p3_to_the_new_script():
    import yaml
    agent = yaml.safe_load((ROOT / "configs/architecture/agents/first_app_check.yaml").read_text())["agent"]
    tpl = agent["script_template"]
    assert "/app/configs/architecture/bin/first_app_p3.py" in tpl and "/app/configs/architecture/bin/first_app_check.py" in tpl
    assert '"controls_p3"' in tpl and '"journey_p3" in json.loads(profile)' in tpl
    assert "timeout=3500 if shared or p3 else 840" in tpl and "${" not in tpl
    flow = yaml.safe_load((ROOT / "configs/architecture/workflows/first_app_check.yaml").read_text())["workflow"]
    assert "controls_p3" in flow["inputs"]["mode"].get("description", "") or "controls_p3" in \
        (ROOT / "configs/architecture/workflows/first_app_check.yaml").read_text()
    docs = (ROOT / "docs" / "departments.md").read_text()
    assert "architecture/bin/first_app_p3.py" in docs and "architecture/fixtures/p3_app/" in docs


# ---------------------------------------------------------------- verdict and control status


def _passing_receipt() -> dict:
    steps = [{"id": i, "status": "PASS", "traffic": [], "reasons": []} for i in p3.ROW_IDS]
    return {"steps": steps, "pins": {"ok": True}, "reach": {}, "profile": {},
            "sessions": {"chromium": {"status": "RAN", "before_first_navigation": True},
                         "webkit": {"status": "RAN", "before_first_navigation": True}},
            "cleanup": {"chromium": {"confirmed": True}, "webkit": {"confirmed": True}},
            "screenshots": [{"after": k} for k in p3.SHOTS]}


def test_verdict_pass_needs_every_row_both_cleanups_and_the_shots():
    r = _passing_receipt()
    assert p3.final_verdict(r)[0] == "PASS" and p3.traffic_gate(r)["status"] == "PASS"
    r["cleanup"].pop("webkit")
    assert p3.final_verdict(r)[0] == "BLOCKED"
    r = _passing_receipt()
    r["screenshots"] = r["screenshots"][:1]
    assert p3.final_verdict(r)[0] == "BLOCKED"


def test_webkit_not_run_is_blocked_never_pass_and_fail_wins():
    r = _passing_receipt()
    for s in r["steps"]:
        if s["id"].startswith("W-"):
            s.update(status="NOT RUN", reasons=["the WebKit browser service did not answer"])
    r["sessions"]["webkit"] = {"status": "NOT RUN"}
    verdict, why = p3.final_verdict(r)
    assert verdict == "BLOCKED" and "WebKit rows NOT RUN" in why and "did not answer" in why
    assert p3.traffic_gate(r)["status"] == "NOT CHECKED"
    assert p3.traffic_gate(r)["engines"] == {"chromium": "PASS", "webkit": "NOT CHECKED"}
    r["steps"][0]["traffic"] = ["GET http://evil.example/"]
    assert p3.traffic_gate(r)["engines"]["chromium"] == "FAIL" and p3.traffic_gate(r)["status"] == "FAIL"
    r["steps"][0]["traffic"] = []
    r["steps"][2].update(status="FAIL", reasons=["x"])
    assert p3.final_verdict(r)[0] == "FAIL"


def test_control_status_ok_wrong_and_not_run():
    clean = {"case": "P3-CLEAN", "expect": ("PASS", None), "webkit": True}
    r = _passing_receipt()
    r["traffic_gate"] = p3.traffic_gate(r)
    r["verdict"], r["why"] = p3.final_verdict(r)
    assert p3.control_status(clean, r) == ("OK", ["PASS", None])
    nr = _passing_receipt()
    for s in nr["steps"]:
        if s["id"].startswith("W-"):
            s.update(status="NOT RUN", reasons=["down"])
    nr["sessions"]["webkit"] = {"status": "NOT RUN"}
    nr["traffic_gate"] = p3.traffic_gate(nr)
    nr["verdict"], nr["why"] = p3.final_verdict(nr)
    assert p3.control_status(clean, nr) == ("NOT RUN", ["BLOCKED", "W-1"])
    late = dict(nr, sessions={"chromium": {"status": "RAN", "before_first_navigation": False},
                              "webkit": {"status": "NOT RUN"}})
    late["traffic_gate"] = p3.traffic_gate(late)
    assert p3.control_status(clean, late)[0] == "WRONG"  # Chromium's traffic must be proven clean
    assert p3.control_status({"case": "P3-NO-BANNER", "expect": ("FAIL", "D-2")}, nr)[0] == "WRONG"
    nr["steps"][5].update(status="FAIL")
    nr["verdict"], _ = p3.final_verdict(nr)
    assert p3.control_status(clean, nr)[0] == "WRONG"  # a Chromium row failing is never NOT RUN


def test_every_plant_has_a_control_and_materializes(tmp_path):
    src = (p3.FIXTURE / "app.js").read_text()
    assert src.count('const VARIANT = "clean";') == 1
    variants = {c["variant"] for c in p3.CONTROLS}
    assert variants == {"clean", "inner_html", "utf16_length", "fixed_600", "no_dir_auto", "idle_callback",
                        "no_banner", "no_put_back"}
    for v in variants - {"clean"}:
        assert f'VARIANT === "{v}"' in src or f'VARIANT !== "{v}"' in src, v
        site = p3.materialize(v, tmp_path / v)
        assert f"const VARIANT = {json.dumps(v)};" in (site / "app.js").read_text()
        assert sorted(x.name for x in site.iterdir()) == ["app.js", "favicon.svg", "index.html", "style.css"]
    cases = {c["case"]: c for c in p3.CONTROLS}
    assert cases["P3-NO-EXIT-CODE"]["expect"] == ("BLOCKED", "R-1")
    assert cases["P3-KILL-EXIT-0"]["expect"] == ("BLOCKED", "D-1")
    assert cases["P3-SIM-RACE"]["server"] == "race_add"
    for c in p3.CONTROLS:
        assert c["expect"][1] is None or c["expect"][1] in p3.ROW_IDS


# ---------------------------------------------------------------- the controls' synthetic server


def _req(port, method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, r.read()


def test_server_answers_utf8_keeps_items_across_a_kill_and_reports_exit_codes(tmp_path):
    site = p3.materialize("clean", tmp_path / "c")
    data = tmp_path / "data"
    data.mkdir()
    srv = p3.P3Server(site, data, bind_address="127.0.0.1")
    srv.start()
    try:
        code, raw = _req(srv.port, "POST", "/api/items", {"text": p3.S["hebrew"], "added_by": "Pat"})
        assert code == 201 and p3.S["hebrew"].encode() in raw
        kill = srv.host_action("kill")
        assert kill["action"] == "kill" and kill["exit_code"] == 137 and kill["done"] and not srv.port_open()
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", srv.port), timeout=1).close()
        start = srv.host_action("start")
        assert start["exit_code"] == 0 and start["done"]
        _, raw = _req(srv.port, "GET", "/api/items")
        assert [x["text"] for x in json.loads(raw)["items"]] == [p3.S["hebrew"]]
        assert srv.host_action("restart")["exit_code"] == 0
    finally:
        srv.stop()


def test_race_server_loses_one_of_two_adds_at_once(tmp_path):
    site = p3.materialize("clean", tmp_path / "c")
    for variant, want in (("file", 2), ("race_add", 1)):
        data = tmp_path / variant
        data.mkdir()
        srv = p3.P3Server(site, data, variant, bind_address="127.0.0.1")
        srv.start()
        try:
            threads = [threading.Thread(target=_req, args=(srv.port, "POST", "/api/items",
                                                           {"text": t, "added_by": "x"})) for t in ("a", "b")]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            _, raw = _req(srv.port, "GET", "/api/items")
            assert len(json.loads(raw)["items"]) == want, variant
        finally:
            srv.stop()
