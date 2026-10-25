"""first_app_check's Project 3 journey on canned data (System architecture, queue #125, 2026-10-24).

configs/architecture/bin/first_app_p3.py (loaded only for mode=controls_p3 or a profile with "journey_p3") runs QA
#32's rows on Product FINAL v3.1 in Chromium and in phone-sized WebKit. The rows and their judges are qualified in
test_first_app_p3_rows.py; disposal, W4 and admission in test_first_app_p3_safety.py and
test_first_app_p3_admission.py. These tests pin the rest of the pure part: the profile, the engines' contexts, the
browser code's placeholders and abort route, the agent's routing, the verdict, live host rows (BLOCKED until QA's
P5 receiving names #126's wire), the controls and their expectations, the gate plants' exact matching and G5
result, and the controls' fixture server. The browser part is proven only by mode=controls_p3 on temper-dev.
"""

import asyncio
import importlib.util
import json
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

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
fs, g, kit = p3.fs, p3.guard, p3.kit
ORIGIN = "http://100.110.162.4:8962"


def profile(**changes) -> dict:
    p = p3.default_p3_profile()
    p.update(changes)
    return p


def target(**changes) -> dict:
    t, problems = p3.parse_p3_profile(json.dumps(p3.default_p3_profile()))
    assert problems == []
    t.update(changes)
    return t


def problems(**changes) -> list:
    return p3.parse_p3_profile(json.dumps(profile(**changes)))[1]


# ---------------------------------------------------------------- the hypothesis, engines and browser code


def test_hypothesis_is_written_in_the_module_docstring():
    doc = p3.__doc__
    for part in ("H-125-INTEGRATION-2", "What is wrong", "The one change", "Expected result", "What proves it wrong"):
        assert part in doc, part


def test_each_engine_has_its_own_fresh_contexts_and_options():
    assert p3.ENGINES["chromium"]["contexts"] == kit.CONTEXTS["chromium"] == ("A", "B", "C", "L", "U", "V")
    assert p3.ENGINES["webkit"]["contexts"] == kit.CONTEXTS["webkit"] == ("A", "B", "C", "U", "V")
    w = p3.ENGINES["webkit"]["opts"]
    assert w["viewport"] == {"width": 390, "height": 844} and w["deviceScaleFactor"] == 3
    assert w["isMobile"] is True and w["hasTouch"] is True
    assert "userAgent" not in w and "userAgent" not in p3.ENGINES["chromium"]["opts"]  # native UA, no shim
    for e in p3.ENGINES:
        specs = p3.context_specs(e)
        assert set(specs) == set(p3.ENGINES[e]["contexts"])
        assert all(s["opts"]["serviceWorkers"] == "block" and s["touch"] == (e == "webkit") for s in specs.values())
    assert p3.EXPECTED_STEPS[-1] == ("webkit", "PH-1") and len(p3.EXPECTED_STEPS) == 37 + 23 + 1


def test_setup_and_probes_abort_off_origin_only_in_control_runs():
    for e in p3.ENGINES:
        build = p3.setup_js(target(), e)
        control = p3.setup_js(target(abort_off_origin=True), e)
        assert "const ABORT = false" in build.replace(" ", " ") or "ABORT = false" in build
        assert "ABORT = true" in control
        assert "__" + "ROWS_JS__" not in build and "__OBSERVERS__" not in build
        for kind in ("pins", "engine"):
            assert "ABORT = false" in p3.probe_js(target(), kind, e)
            assert "ABORT = true" in p3.probe_js(target(abort_off_origin=True), kind, e)
    with pytest.raises(ValueError):
        p3.probe_js(target(), "down")
    for banned in ("addInitScript", "routeWebSocket", "setExtraHTTPHeaders", "page.clock"):
        assert banned not in p3.SETUP + p3.PROBE, banned


def test_row_code_puts_typed_text_last_so_placeholders_in_data_stay_literal():
    row = dict(kit.ROW["J-4"], acts=[{"do": "add", "ctx": "A", "text": "__CTX__ __OBSERVE__"}])
    js = p3.row_js(row)
    assert '"__CTX__ __OBSERVE__"' in js and "__ACTS__" not in js


# ---------------------------------------------------------------- the profile


def test_profile_is_strict_and_separate_from_the_other_journeys():
    good = json.dumps(p3.default_p3_profile())
    t, bad = p3.parse_p3_profile(good)
    assert bad == [] and t["journey"] == "p3" and t["origin_webkit"] != t["origin"]
    assert t["kit_sha256"] == kit.SPEC["specs-rows.json"] and t["engine_image"] == p3.hc.ENGINE_PIN
    assert "not allowed: extra" in " ".join(problems(extra=1))
    assert problems(origin="http://10.0.0.5:8962")
    assert any("journey_p3 must be" in x for x in problems(journey_p3="p3-provisional"))
    assert any("origin_webkit must be" in x for x in problems(origin_webkit=ORIGIN))
    assert any("kit_sha256 must be" in x for x in problems(kit_sha256="0" * 64))
    assert any("kit_id must be" in x for x in problems(kit_id="qa-project3-critical-PENDING-SPEC"))
    assert any("full image ID" in x for x in problems(engine_image="sha256:b01cb863"))
    assert any("webkit_tree_sha256" in x for x in problems(webkit_tree_sha256="ABC"))
    assert problems(webkit_tree_sha256="a" * 64) == []
    hb = {"context_path": "/home/x/context.json", "context_sha256": "a" * 64, "uid": 1000}
    assert any("host_binding" in x for x in problems(host_binding=dict(hb, context_path="relative")))
    assert any("host_binding" in x for x in problems(host_binding={"context_path": "/x"}))
    assert any("host_binding" in x for x in problems(host_binding=dict(hb, uid=True)))
    assert any("host_binding" in x for x in problems(host_binding=dict(hb, context_sha256="A" * 64)))
    assert problems(host_binding=hb) == []
    for gone in ("wording", "host_wait_minutes"):
        assert any(f"not allowed: {gone}" in x for x in problems(**{gone: 1}))
    p = p3.default_p3_profile()
    del p["engine_image"]
    assert p3.parse_p3_profile(json.dumps(p))[1]
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


# ---------------------------------------------------------------- verdict


def passing() -> dict:
    r = p3.new_receipt("V", target())
    r.update(pins={"ok": True}, pins_webkit={"ok": True}, reach={},
             steps=[{"id": i, "engine": e, "status": "PASS", "traffic": [], "reasons": []}
                    for e, i in p3.EXPECTED_STEPS],
             sessions={e: {"status": "RAN", "before_first_navigation": True} for e in p3.ENGINES},
             cleanup={e: {"confirmed": True} for e in p3.ENGINES},
             engine_image={"compare": {"status": "PASS", "reasons": []}})
    return r


def test_verdict_pass_needs_every_row_in_both_engines_w1_and_both_cleanups():
    assert p3.final_verdict(passing())[0] == "PASS"
    r = passing()
    r["steps"] = [s for s in r["steps"] if s["id"] != "UNI-UI" or s["engine"] != "webkit"]
    assert p3.final_verdict(r)[0] != "PASS"
    r = passing()
    r["engine_image"]["compare"] = {"status": "BLOCKED", "reasons": ["engine container_id changed"]}
    assert p3.final_verdict(r)[0] == "BLOCKED"
    r = passing()
    r.pop("engine_image")
    assert p3.final_verdict(r)[0] != "PASS"
    r = passing()
    del r["cleanup"]["webkit"]
    assert p3.final_verdict(r)[0] != "PASS"
    r = passing()
    r["pins_webkit"] = {"ok": False, "bad": ["app.js"]}
    assert p3.final_verdict(r)[0] == "REFUSED"


def test_unqualified_host_rows_and_unrun_webkit_are_never_pass_and_fail_wins():
    r = passing()
    for s in r["steps"]:
        if s["id"] in kit.HOST_ROWS:
            s["status"] = "UNQUALIFIED"
    assert p3.final_verdict(r)[0] == "BLOCKED"
    r = passing()
    for s in r["steps"]:
        if s["engine"] == "webkit":
            s["status"] = "NOT RUN"
    assert p3.final_verdict(r)[0] == "BLOCKED"
    r["steps"][0]["status"] = "FAIL"
    assert p3.final_verdict(r)[0] == "FAIL"


def test_live_host_rows_without_a_host_wire_write_nothing_and_are_blocked():
    calls = []

    async def call(s, code):
        calls.append(code)
        return {}

    r, latch = p3.new_receipt("H", target()), g.StopLatch()
    orig = p3._call
    p3._call = call
    try:
        for rid in kit.HOST_ROWS:
            step = asyncio.run(p3.host_step(object(), r, kit.ROW[rid], ORIGIN, {}, latch, "chromium"))
            assert step["status"] == "BLOCKED" and step["reasons"] == [p3.HOST_WAIT]
    finally:
        p3._call = orig
    assert calls == [p3.DRAIN] * len(kit.HOST_ROWS)  # only the drain before the row; no host request anywhere
    assert "#126" in p3.HOST_WAIT and "P5" in p3.HOST_WAIT and "no host request" in p3.HOST_WAIT


# ---------------------------------------------------------------- controls


def test_every_plant_has_a_control_and_materializes(tmp_path):
    src = (p3.FIXTURE / "app.js").read_text()
    assert src.count('const VARIANT = "clean";') == 1
    variants = {c["variant"] for c in p3.CONTROLS}
    plants = {"inner_html", "utf16_length", "no_dir_auto", "idle_callback", "no_banner", "no_live_busy",
              "late_pending", "no_hints", "immediate_delete", "empty_on_failure"}
    assert variants == {"clean"} | plants | set(p3.GATE_PLANTS)
    for v in sorted(variants - {"clean"}):
        assert f'VARIANT === "{v}"' in src or f'VARIANT !== "{v}"' in src, v
        site = p3.materialize(v, tmp_path / v)
        assert f"const VARIANT = {json.dumps(v)};" in (site / "app.js").read_text()
        assert sorted(x.name for x in site.iterdir()) == ["app.js", "favicon.svg", "index.html", "style.css"]
    for c in p3.CONTROLS:
        if c.get("verdict") == "REFUSED":  # refused before any browser contact: no engine expectation
            assert c["expect"] == {"chromium": None, "webkit": None}
            continue
        for e, (status, row) in c["expect"].items():
            assert status in ("PASS", "FAIL") and (row is None or row in p3.ROW_IDS[e]), c
    cases = {c["case"]: c for c in p3.CONTROLS}
    assert cases["P3-IDLE-CALLBACK"]["expect"] == {"chromium": ("PASS", None), "webkit": ("FAIL", "J-1")}
    assert cases["P3-BAD-PROFILE"]["verdict"] == "REFUSED"
    assert "SIM" not in " ".join(cases) and "race" not in src.lower()  # SIM-5 is out


def test_gate_plants_are_literal_invalid_hosts_in_the_served_file():
    src = (p3.FIXTURE / "app.js").read_text()
    for variant, plant in p3.GATE_PLANTS.items():
        for url in plant["urls"]:
            assert url.split("/")[2].endswith(".invalid"), url
            assert url in src or (variant == "plant_redirect" and url == p3.REDIRECT_LOCATION), url
    assert p3.REDIRECT_ROUTE in src


def _engine_status(r, e, ids):
    r["sessions"][e] = {"status": "RAN", "engine_facts": {}}
    r["steps"] += [{"id": i, "engine": e, "status": "PASS"} for i in ids]


def test_control_status_ok_wrong_not_run_and_uncalibrated():
    case = {c["case"]: c for c in p3.CONTROLS}

    def receipt(webkit_ran=True, fail=None):
        r = {"verdict": "FAIL", "steps": [], "sessions": {}, "browser_contact": True,
             "traffic_gate": {"engines": {"chromium": "PASS", "webkit": "PASS"}}}
        _engine_status(r, "chromium", p3.ROW_IDS["chromium"])
        if webkit_ran:
            _engine_status(r, "webkit", p3.ROW_IDS["webkit"])
        else:
            r["sessions"]["webkit"] = {"status": "NOT RUN", "why": p3.W1_MISSING}
        if fail:
            e, rid = fail
            for s in r["steps"]:
                if s["engine"] == e and s["id"] == rid:
                    s["status"] = "FAIL"
            r["traffic_gate"]["engines"][e] = "NOT CHECKED"
        return r

    assert p3.control_status(case["P3-CLEAN"], receipt())[0] == "OK"
    assert p3.control_status(case["P3-CLEAN"], receipt(webkit_ran=False))[0] == "NOT RUN"
    assert p3.control_status(case["P3-INNERHTML"], receipt(fail=("chromium", "E-5")))[0] == "WRONG"
    assert p3.control_status(case["P3-INNERHTML"], receipt(fail=("chromium", "E-5")))[1]["webkit"] == ["PASS", None]
    r = receipt(fail=("webkit", "J-1"))
    assert p3.control_status(case["P3-IDLE-CALLBACK"], r)[0] == "OK"
    r["sessions"]["webkit"]["engine_facts"] = {"idle_callback": "function"}
    assert p3.control_status(case["P3-IDLE-CALLBACK"], r)[0] == "UNCALIBRATED"
    r = receipt()
    r["verdict"] = "W4 TRIPPED"
    assert p3.control_status(case["P3-CLEAN"], r)[0] == "W4 TRIPPED"
    r = receipt()
    r["traffic_gate"]["engines"]["webkit"] = "NOT CHECKED"
    assert p3.control_status(case["P3-CLEAN"], r)[0] == "WRONG"  # a clean PASS needs the engine's gate PASS


# ---------------------------------------------------------------- gate plants: exact matching and G5


def test_exact_key_fills_default_ports_and_keeps_path_and_query():
    k = g.exact_key
    assert k("https://beacon.invalid/b") == k("https://beacon.invalid:443/b") == k("HTTPS://beacon.invalid/b")
    assert k("wss://websocket.invalid/s") == k("wss://websocket.invalid:443/s")
    assert k("https://beacon.invalid/b") != k("https://beacon.invalid/b?x=1")
    assert k("https://beacon.invalid/b") != k("https://beacon.invalid:8443/b")
    assert k("https://beacon.invalid/b") != k("http://beacon.invalid/b")
    assert k("https://beacon.invalid/b") != k("https://beacon.invalid/bb")
    assert k("http://[::1") is None


@pytest.mark.parametrize("url,catch", [("https://beacon.invalid/b", True), ("https://beacon.invalid:443/b", True),
                                       ("https://beacon.invalid/b?n=1", False), ("https://beacon.invalid/c", False),
                                       ("https://worker.invalid/w", False), ("https://outside.example/b", False)])
def test_only_the_cases_own_plant_urls_are_caught_anything_else_off_origin_is_w4(url, catch):
    r, latch = {}, g.StopLatch()
    log = {"requests": [{"url": url, "ctx": "A"}]}
    latch.observe(r, log, ORIGIN, "chromium:J-1", allowed=p3.GATE_PLANTS["plant_beacon"]["urls"])
    assert latch.tripped is (not catch)
    assert bool(r.get("gate_catches")) is catch
    latch2 = g.StopLatch()
    latch2.observe({}, log, ORIGIN, "chromium:J-1")  # builds pass no list: everything off-origin is W4
    assert latch2.tripped


def test_g5_reports_caught_miss_and_not_exercised_per_engine():
    url = p3.GATE_PLANTS["plant_eventsource"]["urls"][0]
    r = {"profile": {"gate_plant": "plant_eventsource"},
         "sessions": {"chromium": {"status": "RAN"}, "webkit": {"status": "RAN"}},
         "gate_catches": [{"phase": "chromium:J-3", "kind": "requests", "url": url}],
         "engine_logs": {"webkit": {"aborted": [{"url": url}]}}, "plant_marks": {"chromium": "sent", "webkit": "sent"}}
    out = p3.gate_plant_result(r)
    assert out["engines"]["chromium"]["result"] == "caught"
    assert out["engines"]["webkit"]["result"] == "MISS"  # the abort route saw it, the gate did not: never caught
    r["engine_logs"] = {}
    r["plant_marks"]["webkit"] = "unsupported"
    assert p3.gate_plant_result(r)["engines"]["webkit"]["result"] == "not exercised"
    r["sessions"]["webkit"] = {"status": "NOT RUN", "why": p3.W1_MISSING}
    assert p3.gate_plant_result(r)["engines"]["webkit"]["result"] == "NOT RUN"
    assert p3.gate_plant_result({"profile": {}}) is None


# #279 (Security #105 G3-a, H-279-G3a): a URL with userinfo is never the plant.
@pytest.mark.parametrize("url", ["https://u:p@beacon.invalid/b", "https://u@beacon.invalid/b",
                                 "https://@beacon.invalid/b", "https://:@beacon.invalid/b"])
def test_g3a_a_plant_url_with_userinfo_is_not_the_plant_and_trips_w4(url):
    beacon = p3.GATE_PLANTS["plant_beacon"]["urls"]
    assert g.exact_key(url) != g.exact_key(beacon[0])
    r, latch = {}, g.StopLatch()
    latch.observe(r, {"requests": [{"url": url, "ctx": "A"}]}, ORIGIN, "chromium:J-1", allowed=beacon)
    assert latch.tripped and not r.get("gate_catches")
    assert p3.p3_findings({"requests": [{"url": url}]}, ORIGIN, beacon)  # a finding, not a dropped plant event
    plain, clean = {}, g.StopLatch()
    clean.observe(plain, {"requests": [{"url": beacon[0], "ctx": "A"}]}, ORIGIN, "chromium:J-1", allowed=beacon)
    assert not clean.tripped and plain["gate_catches"][0]["url"] == beacon[0]  # the exact plant is still caught
    g5 = p3.gate_plant_result({"profile": {"gate_plant": "plant_beacon"},
                               "sessions": {"chromium": {"status": "RAN"}, "webkit": {"status": "NOT RUN"}},
                               "gate_catches": [{"phase": "chromium:J-1", "kind": "requests", "url": url}],
                               "plant_marks": {"chromium": "sent"}})
    assert g5["engines"]["chromium"]["result"] == "MISS"


# #279 (Security #105 G5-Q, H-279-G5Q): a plant MISS or gap is never OK, never full qualification.
def _plant_receipt(variant, chromium, webkit):
    r = {"verdict": "PASS", "steps": [], "sessions": {}, "browser_contact": True,
         "traffic_gate": {"engines": {"chromium": "PASS", "webkit": "PASS"}}}
    _engine_status(r, "chromium", p3.ROW_IDS["chromium"])
    _engine_status(r, "webkit", p3.ROW_IDS["webkit"])
    r["gate_plant_result"] = {"plant": variant, "kind": p3.GATE_PLANTS[variant]["kind"],
                              "urls": p3.GATE_PLANTS[variant]["urls"],
                              "engines": {"chromium": {"result": chromium}, "webkit": {"result": webkit}}}
    return r


def test_g5q_a_plant_miss_is_wrong_and_a_gap_is_named_never_ok(monkeypatch):
    case = {c["case"]: c for c in p3.CONTROLS}["P3-PLANT-BEACON"]
    assert p3.G5_BLIND_SPOTS == {}  # none named by Security (DECISION-10 section 3)
    assert p3.control_status(case, _plant_receipt("plant_beacon", "caught", "caught"))[0] == "OK"
    status, got = p3.control_status(case, _plant_receipt("plant_beacon", "caught", "MISS"))
    assert status == "WRONG" and got["g5"] == {"chromium": "caught", "webkit": "MISS"}
    status, got = p3.control_status(case, _plant_receipt("plant_beacon", "not exercised", "caught"))
    assert status == "NOT EXERCISED" and got["gap"]["kind"] == "beacon" and got["gap"]["plant"] == "plant_beacon"
    assert got["gap"]["engines"] == {"chromium": "not exercised"} and "beacon" in got["gap"]["why"]
    r = _plant_receipt("plant_beacon", "caught", "caught")
    del r["gate_plant_result"]
    assert p3.control_status(case, r)[0] == "NOT EXERCISED"  # no G5 result at all is a gap, never OK
    for chromium, want in (("MISS", "WRONG"), ("not exercised", "NOT EXERCISED")):
        r = _plant_receipt("plant_beacon", chromium, "NOT RUN")
        r["sessions"]["webkit"] = {"status": "NOT RUN", "why": p3.W1_MISSING}  # the Chromium-only run
        assert p3.control_status(case, r)[0] == want, chromium
    clean = {c["case"]: c for c in p3.CONTROLS}["P3-CLEAN"]  # not a plant case: G5 is not read
    assert p3.control_status(clean, _plant_receipt("plant_beacon", "MISS", "MISS"))[0] == "OK"
    monkeypatch.setattr(p3, "G5_BLIND_SPOTS", {"beacon": "a Security record (test only)"})
    status, got = p3.control_status(case, _plant_receipt("plant_beacon", "caught", "MISS"))
    assert status == "OK" and got["g5_blind_spot"] == {"kind": "beacon", "named_by": "a Security record (test only)"}


def test_g5q_full_qualification_needs_every_plant_kind_caught_on_every_engine_that_ran(monkeypatch, tmp_path):
    plan = {}

    async def control(args, case, out, tmp, ip, latch):
        x = {"case": case["case"], "status": plan.get("status", "OK") if case.get("plant") else "OK"}
        if case.get("plant"):
            x["gate_plant"] = {"plant": case["variant"], "engines": {e: {"result": v} for e, v in plan["g5"].items()}}
        return x

    monkeypatch.setattr(p3, "CONTROLS", [p3._case("P3-CLEAN", "clean", p3.CLEAN, p3.CLEAN),
                                         p3._case("P3-PLANT-BEACON", "plant_beacon", p3.CLEAN, p3.CLEAN, plant=True)])
    monkeypatch.setattr(p3, "run_control", control)
    monkeypatch.setattr(p3.fs, "serve_ip", lambda *a: "100.110.162.4")

    def run(name, **kw):
        plan.clear()
        plan.update(kw)
        args = SimpleNamespace(only="", browser="fake:", serve_ip="100.110.162.4")
        code = asyncio.run(p3.controls(args, tmp_path / name))
        return code, json.loads((tmp_path / name / "controls.json").read_text())

    code, s = run("caught", g5={"chromium": "caught", "webkit": "caught"})
    assert code == 0 and s["all_ok"] and s["full_qualification"] and s["g5_gaps"] == []
    assert s["g5"] == {"P3-PLANT-BEACON": {"chromium": {"result": "caught"}, "webkit": {"result": "caught"}}}
    code, s = run("miss", g5={"chromium": "caught", "webkit": "MISS"})  # even if a status said OK
    assert s["all_ok"] and not s["full_qualification"]
    assert s["g5_gaps"] == ["P3-PLANT-BEACON (beacon): chromium caught, webkit MISS"]
    code, s = run("chromium_only", g5={"chromium": "caught", "webkit": "NOT RUN"})
    assert s["full_qualification"] and s["g5_gaps"] == []  # caught on every engine that ran
    code, s = run("none_ran", g5={"chromium": "NOT RUN", "webkit": "NOT RUN"})
    assert not s["full_qualification"] and s["g5_gaps"] == ["P3-PLANT-BEACON (beacon): no engine ran it"]
    code, s = run("gap", g5={"chromium": "not exercised", "webkit": "caught"}, status="NOT EXERCISED")
    assert code == 1 and not s["all_ok"] and not s["full_qualification"] and s["counts"]["NOT EXERCISED"] == 1
    monkeypatch.setattr(p3, "G5_BLIND_SPOTS", {"beacon": "a Security record (test only)"})
    code, s = run("blind", g5={"chromium": "caught", "webkit": "MISS"})
    assert code == 0 and s["full_qualification"] and s["g5_blind_spots"] == {"beacon": "a Security record (test only)"}


# ---------------------------------------------------------------- the controls' fixture server


def _req(port, method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json"})

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **kw):
            return None

    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=5) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


@pytest.mark.parametrize("variant", ["clean", "plant_redirect"])
def test_server_serves_only_its_allowlist_and_the_fixed_redirect_in_its_own_copy(tmp_path, variant):
    site = p3.materialize(variant, tmp_path / "s")
    data = tmp_path / "data"
    data.mkdir()
    srv = p3.P3Server(site, data, variant, bind_address="127.0.0.1")
    srv.start()
    try:
        for path in ("/", "/index.html", "/style.css", "/app.js", "/favicon.svg"):
            assert _req(srv.port, "GET", path)[0] == 200, path
        for path in ("/etc/passwd", "/app.js/", "/./app.js", "/%61pp.js", "/fixtures/", "/app.js?x=1", "/../app.js"):
            assert _req(srv.port, "GET", path)[0] == 404, path
        code, headers, _ = _req(srv.port, "GET", p3.REDIRECT_ROUTE)
        if variant == "plant_redirect":
            assert code == 302 and headers["Location"] == p3.REDIRECT_LOCATION
        else:
            assert code == 404
    finally:
        srv.stop()


def test_server_keeps_exact_utf8_across_a_crash_and_start(tmp_path):
    site = p3.materialize("clean", tmp_path / "c")
    data = tmp_path / "data"
    data.mkdir()
    srv = p3.P3Server(site, data, bind_address="127.0.0.1")
    srv.start()
    try:
        text = kit.U["U10"]  # NFD: must come back as the same code points
        code, _, raw = _req(srv.port, "POST", "/api/items", {"text": text, "added_by": kit.N2})
        assert code == 201
        crash = srv.host_action("crash")
        assert crash["action"] == "crash" and crash["done"] and "never a real app" in crash["fake"]
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", srv.port), timeout=1).close()
        assert srv.host_action("start")["done"]
        _, _, raw = _req(srv.port, "GET", "/api/items")
        items = json.loads(raw)["items"]
        assert [x["text"] for x in items] == [text] and [ord(c) for c in items[0]["text"]][-2:] == [0x65, 0x301]
        assert srv.host_action("restart")["done"]
        assert srv.host_action("kill")["done"] is False  # only restart, crash and start exist
    finally:
        srv.stop()


def test_tree_hash_is_stable_and_changes_with_any_byte(tmp_path):
    a = g.snapshot(p3.materialize("clean", tmp_path / "a"), p3.CTYPES)
    b = g.snapshot(p3.materialize("inner_html", tmp_path / "b"), p3.CTYPES)
    assert p3.tree_sha256(a) == p3.tree_sha256(dict(a)) and len(p3.tree_sha256(a)) == 64
    assert p3.tree_sha256(a) != p3.tree_sha256(b)
