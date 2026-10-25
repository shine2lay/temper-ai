"""Project 3's row judges on fixed observations (System architecture, queue #125, 2026-10-24).

configs/architecture/bin/first_app_p3_rows.py holds QA #32's rows on Product FINAL v3.1 and their judges. The judges
are pure functions over what the browser code reports, so they are qualified here on fixed data (rule 16): a
correct observation of every non-host row passes in each of its engines, and each planted fault fails at its own
judge (or is BLOCKED when the measurement itself is not good enough, never PASS). The browser side is proven by
mode=controls_p3 on temper-dev; the byte-for-byte binding of every literal to QA's spec and Product's FINAL is the
#125 stage script (stage_spec_binding.py), because CI cannot read QA's files.
"""

import copy
import importlib.util
import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "configs" / "architecture" / "bin"
_spec = importlib.util.spec_from_file_location("first_app_p3_rows_under_test", BIN / "first_app_p3_rows.py")
kit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kit)
T = kit.TEXT
SERVED = (ROOT / "configs" / "architecture" / "fixtures" / "p3_app" / "index.html").read_text(encoding="utf-8")


def row_obs(text, by, done) -> dict:
    rtl = {kit.U["U06"], kit.U["U07"]}
    return {"text": text, "by_name": by, "desc": T["added_by"] + by, "by_count": 1, "checked": done,
            "name_from": "label", "text_direction": "rtl" if text in rtl else "ltr",
            "by_direction": "rtl" if by in (kit.N1, kit.N2) else "ltr"}


def page(exp: dict) -> dict:
    """What a correct page shows for one row's expectation."""
    app = bool(exp.get("app"))
    who = exp.get("who")
    return {"headings": [T["heading"]], "name_form": {"visible": bool(exp.get("name_form"))},
            "add": {"box_visible": app, "button_count": 1 if app else 0, "button_text": T["add"] if app else None,
                    "button_visible": app, "value": exp.get("item_value", ""), "msg": exp.get("item_msg", "")},
            "who": ({"whoami_count": 1, "name_count": 1, "visible": True, "name": who, "inside": True, "i_count": 0,
                     "line": T["who_prefix"] + who + " \u00b7 " + T["change_name"]} if who else {}),
            "rows": [row_obs(*r) for r in exp.get("rows") or []], "m11_visible": bool(exp.get("m11")),
            "banner": exp.get("banner", ""), "row_markup": 0, "m9_visible": False, "try_again_visible": False}


def step(item) -> dict:
    return {"status": kit.m("m18", item=item), "yes_text": T["yes_delete"], "keep_text": T["keep"], "yes_count": 1,
            "keep_count": 1, "yes_desc": kit.m("m18", item=item), "keep_desc": kit.m("m18", item=item),
            "yes_before_keep": True, "delete_visible": False, "focus": kit.m("keep_name", item=item),
            "open_steps": 1, "dialogs": 0, "deletes": 0}


def closed(item) -> dict:
    return {"status": "", "yes_count": 0, "keep_count": 0, "delete_visible": True,
            "focus": kit.m("delete_name", item=item), "item_present": True, "deletes": 0}


BUSY = {"add": (T["m13"], T["a5"], T["a1"]), "tick": (T["m19"], T["a8"], T["a6"]),
        "untick": (T["m19"], T["a8"], T["a6"]), "confirm": (T["m20"], T["a9"], T["a2"])}


def held(op, live) -> dict:
    busy, start, done = BUSY[op]
    return {"hold_ms": kit.HOLD_MS + 120, "max_poll_gap_ms": 60, "visible_ms": 140, "after_attribution": True,
            "aria_busy": True, "aria_busy_cleared": True, "requests": 1,
            "announcer": [{"text": start}, {"text": done}] if live else [], "live_texts": [],
            "row_status": [{"text": busy}], "announce_cleared_ms": kit.ANNOUNCE_CLEAR_MS + 50}


def hints(stage) -> dict:
    name = stage in (0, 1, 4, 5)
    good = lambda text: {"count": 1, "text": text, "visible": True, "in_describedby": True, "invalid": False}  # noqa: E731
    return {"name_form_visible": name, "item_form_visible": not name, "name_hint": good(T["m16"]),
            "item_hint": good(T["m17"]), "posts": 0}


def measure(row, i, a) -> tuple[str | None, dict]:
    """The measure a correct page gives for one act."""
    kind = a.get("measure") or ("held" if a.get("do") == "held" else None)
    item = a.get("item")
    if kind == "step":
        ms = step(item)
        if a.get("closed_item"):
            ms["closed"] = closed(a["closed_item"])
        return kind, ms
    if kind == "closed":
        return kind, closed(item)
    if kind == "rows":  # V3-DEL: A's reloads
        first = [x for x in row["acts"] if x.get("measure") == "rows"][0] is a
        rows = kit.AFTER_J9 + ([["Return book", "Ben", False]] if first else [])
        return kind, {"rows": [row_obs(*r) for r in rows]}
    if kind == "held":
        return kind, held(a["op"], a.get("watch_live"))
    if kind == "hints":
        return kind, hints(sum(1 for x in row["acts"][:i] if x.get("measure") == "hints"))
    if kind == "m9":
        return kind, {"m9_text": T["m9"], "try_again_visible": True, "m11_visible": False, "m10_visible": False,
                      "aborted": True}
    if kind == "retry":
        return kind, {"ms": 420}
    if kind == "tick_result":
        return kind, {"patch_status": [200], "banner": "", "checked": True}
    if kind == "add_result":
        text = a["text"]
        if not text.strip():
            return kind, {"posts": 0, "msg": T["m1"], "value": text}
        if len(text) > 200:
            return kind, {"posts": 0, "msg": kit.m("m2", n=len(text)), "value": text}
        return kind, {"posts": 0 if row["id"] == "D-2" else 1, "msg": "", "value": "" if row["id"] != "D-2" else text}
    if kind == "name_result":
        if len(a["text"]) > 50:
            return kind, {"msg": kit.m("m5", n=len(a["text"])), "who": kit.N1}
        return kind, {"msg": "", "who": a["text"]}
    if kind == "who_dir":
        return kind, {"who": a["text"], "direction": "rtl"}
    return kind, {}


def good(rid: str) -> dict:
    """A correct browser result for one row (the shape ROW_JS returns)."""
    row = kit.ROW[rid]
    acts = []
    for i, a in enumerate(row["acts"]):
        kind, ms = measure(row, i, a)
        one = {"do": a["do"], "op": a.get("op"), "item": a.get("item"), "closed_item": a.get("closed_item"),
               "watch_live": a.get("watch_live"), "measure_kind": kind, "measure": ms}
        if kind == "add_result":
            one["posts"] = ms["posts"]
        acts.append(one)
    exp = row["expect"]
    obs = {c: page(exp) for c in (row.get("observe") or [row["ctx"]])}
    for c, rows in (exp.get("also") or {}).items():
        obs[c] = page(dict(exp, rows=rows))
    if rid == "UNI-UI":
        obs = {"V": page(exp)}
    return {"started": 1, "ended": 2, "acts": acts, "obs": obs}


BROWSER_ROWS = [(r["id"], e) for r in kit.ROWS if not r.get("host") for e in r["engines"]]


@pytest.mark.parametrize("rid,engine", BROWSER_ROWS)
def test_a_correct_page_passes_every_browser_row_in_each_of_its_engines(rid, engine):
    v = kit.judge(kit.ROW[rid], good(rid), engine, SERVED)
    assert v == {"status": "PASS", "reasons": []}, v


def test_rows_orders_and_contexts_match_qa_and_host_rows_are_not_judged_here():
    assert [r for r in kit.CHROMIUM_ORDER if r not in kit.ROW] == []
    assert set(kit.WEBKIT_ORDER) <= set(kit.CHROMIUM_ORDER)
    assert all(kit.ROW[i]["engines"] == ("chromium", "webkit") for i in kit.WEBKIT_ORDER)
    assert {i for i in kit.CHROMIUM_ORDER if "webkit" not in kit.ROW[i]["engines"]} == {
        "V3-LIMITS", "V3-PEND", "V3-BUSY", "R-1", "R-2", "R-3", "R-1i", "CR-3", "D-1", "D-2", "D-3", "D-4", "D-5",
        "D-6"}
    assert kit.HOST_ROWS == ("R-1", "R-1i", "D-1", "D-5") and all(kit.ROW[i].get("host") for i in kit.HOST_ROWS)
    assert set(kit.JUDGED_ELSEWHERE) == {"CR-1", "API-D-1", "API-D-5", "HOST-L", "PH-1"}
    for engine in ("chromium", "webkit"):
        used = {kit.ROW[i]["ctx"] for i in kit.CHROMIUM_ORDER if engine in kit.ROW[i]["engines"]}
        used |= {c for i in kit.CHROMIUM_ORDER if engine in kit.ROW[i]["engines"]
                 for c in kit.ROW[i].get("observe") or []}
        assert used <= set(kit.CONTEXTS[engine])


def test_test_strings_are_exact_code_points_not_normalised():
    assert [ord(c) for c in kit.U["U09"]] == [0x63, 0x61, 0x66, 0xE9]
    assert [ord(c) for c in kit.U["U10"]] == [0x63, 0x61, 0x66, 0x65, 0x301]
    assert [ord(c) for c in kit.U["U11"]] == [0x1F469, 0x1F3FD, 0x200D, 0x1F4BB]
    assert len(kit.L["L3"]) == 200 and len(kit.L["L3"].encode("utf-16-le")) // 2 == 203
    assert len(kit.L["L4"]) == 201 and len(kit.L["L1"]) == 200 and len(kit.L["N4"]) == 51


def _fail(rid, res, engine="chromium", served=SERVED) -> dict:
    v = kit.judge(kit.ROW[rid], res, engine, served)
    assert v["status"] == "FAIL", v
    return v


def _blocked(rid, res, engine="chromium", served=SERVED) -> dict:
    v = kit.judge(kit.ROW[rid], res, engine, served)
    assert v["status"] == "BLOCKED", v
    return v


def test_nfd_text_stored_as_nfc_fails_on_its_code_points():
    res = good("UNI-UI")
    rows = res["obs"]["V"]["rows"]
    i = [r["text"] for r in rows].index(kit.U["U10"])
    rows[i]["text"] = kit.U["U09"]
    assert any("row " in x and "text" in x for x in _fail("UNI-UI", res)["reasons"])


def test_utf16_length_count_fails_the_l3_add():
    res = good("UNI-UI")
    a = [x for x in res["acts"] if x["measure_kind"] == "add_result"][kit.UNI_ADDS.index(kit.L["L3"])]
    a["measure"] = {"posts": 0, "msg": kit.m("m2", n=203), "value": kit.L["L3"]}
    assert any("1 POST" in x or "POSTs" in x for x in _fail("UNI-UI", res, "webkit")["reasons"])


def test_ltr_direction_for_an_rtl_item_or_name_fails():
    for key in ("U06", "U07"):  # Arabic and Hebrew, each on its own
        res = good("UNI-UI")
        for r in res["obs"]["V"]["rows"]:
            if r["text"] == kit.U[key]:
                r["text_direction"] = "ltr"
        assert any("direction 'ltr'" in x for x in _fail("UNI-UI", res)["reasons"]), key
    res = good("UNI-UI")
    for r in res["obs"]["V"]["rows"]:
        if r["by_name"] == kit.N2:
            r["by_direction"] = "ltr"
    assert any("attributed name" in x for x in _fail("UNI-UI", res)["reasons"])
    res = good("UNI-UI")
    [x for x in res["acts"] if x["measure_kind"] == "who_dir"][1]["measure"]["direction"] = "ltr"
    assert any("#whoami-name" in x for x in _fail("UNI-UI", res, "webkit")["reasons"])


def test_attribution_markup_and_who_faults_fail():
    res = good("J-4")
    res["obs"]["A"]["rows"][0]["desc"] = "added by "
    assert any("checkbox description" in x for x in _fail("J-4", res)["reasons"])
    res = good("E-5")
    res["obs"]["C"]["row_markup"] = 1
    assert any("b/i elements" in x for x in _fail("E-5", res)["reasons"])
    res = good("J-7")
    res["obs"]["B"]["who"]["name"] = "Ana"
    assert any("#whoami-name" in x for x in _fail("J-7", res)["reasons"])
    res = good("J-3")
    res["obs"]["A"]["who"] = {}
    assert any("#whoami 0" in x or "#whoami None" in x for x in _fail("J-3", res)["reasons"])


def test_immediate_delete_and_a_dialog_fail_v3_del_and_keep_must_send_nothing():
    res = good("V3-DEL")
    first = res["acts"][1]
    first["measure"] = dict(closed("Return book"), item_present=False, deletes=1)
    reasons = _fail("V3-DEL", res, "webkit")["reasons"]
    assert any("M18" in x for x in reasons) and any("DELETE request" in x for x in reasons)
    res = good("V3-DEL")
    res["acts"][1]["measure"]["dialogs"] = 1
    assert any("dialog" in x for x in _fail("V3-DEL", res)["reasons"])
    res = good("V3-DEL")
    res["acts"][2]["measure"]["deletes"] = 1
    assert any("on Keep/Escape" in x for x in _fail("V3-DEL", res)["reasons"])
    res = good("V3-DEL")
    res["acts"][1]["measure"]["focus"] = "other: Delete Return book"
    assert any("focus on" in x for x in _fail("V3-DEL", res)["reasons"])


def test_late_busy_text_fails_and_a_short_hold_is_blocked_not_pass():
    res = good("V3-PEND")
    held_acts = [a for a in res["acts"] if a["measure_kind"] == "held"]
    held_acts[1]["measure"]["visible_ms"] = 1400
    assert any("within 1000 ms" in x for x in _fail("V3-PEND", res)["reasons"])
    res = good("V3-PEND")
    [a for a in res["acts"] if a["measure_kind"] == "held"][0]["measure"]["hold_ms"] = 2000
    v = _blocked("V3-PEND", res)
    assert any("at least 3000" in x for x in v["reasons"])
    res = good("V3-PEND")
    [a for a in res["acts"] if a["measure_kind"] == "held"][2]["measure"]["requests"] = 2
    assert any("exactly 1" in x for x in _fail("V3-PEND", res)["reasons"])


def test_busy_announcements_must_come_in_order_from_a_region_that_predates_them():
    res = good("V3-BUSY")
    a = [x for x in res["acts"] if x["measure_kind"] == "held"][0]
    a["measure"]["announcer"] = [{"text": T["a1"]}]
    assert any("#announcer said" in x for x in _fail("V3-BUSY", res)["reasons"])
    res = good("V3-BUSY")
    [x for x in res["acts"] if x["measure_kind"] == "held"][1]["measure"]["live_texts"] = [
        {"text": T["a8"], "region_predates": False}]
    assert any("created with its text" in x for x in _fail("V3-BUSY", res)["reasons"])
    assert any("not pinned" in x for x in _blocked("V3-BUSY", good("V3-BUSY"), served=None)["reasons"])
    late = SERVED.replace('id="announcer"', 'id="not-announcer"')
    assert any("#announcer elements" in x for x in _fail("V3-BUSY", good("V3-BUSY"), served=late)["reasons"])


def test_announcer_must_be_an_empty_status_region_in_the_served_page():
    assert kit.announcer_static(SERVED) == []
    assert kit.announcer_static('<p id="announcer" role="status">Item added.</p>') == [
        "V3-BUSY: #announcer is not empty at load ('Item added.')"]
    assert "role 'alert'" in kit.announcer_static('<p id="announcer" role="alert"></p>')[0]


def test_missing_hints_fail_v3_limits():
    res = good("V3-LIMITS")
    res["acts"][0]["measure"]["name_hint"]["count"] = 0
    assert any("#name-hint" in x for x in _fail("V3-LIMITS", res)["reasons"])
    res = good("V3-LIMITS")
    res["acts"][3]["measure"]["item_hint"]["in_describedby"] = False
    assert any("aria-describedby" in x for x in _fail("V3-LIMITS", res)["reasons"])


def test_outage_rows_need_m6_and_cr3_needs_m9_never_the_empty_list():
    res = good("D-2")
    res["obs"]["A"]["banner"] = ""
    assert any("#banner" in x for x in _fail("D-2", res)["reasons"])
    res = good("D-6")
    res["acts"][0]["measure"]["banner"] = T["m6"]
    assert any("M6 still shown" in x for x in _fail("D-6", res)["reasons"])
    res = good("CR-3")
    m9 = [a for a in res["acts"] if a["measure_kind"] == "m9"][0]["measure"]
    m9.update(m9_text="", m11_visible=True, try_again_visible=False)
    reasons = _fail("CR-3", res)["reasons"]
    assert any("expected M9" in x for x in reasons) and any("false empty" in x for x in reasons)
    res = good("CR-3")
    [a for a in res["acts"] if a["measure_kind"] == "m9"][0]["measure"]["aborted"] = False
    assert any("not aborted" in x for x in _blocked("CR-3", res)["reasons"])
    res = good("CR-3")
    [a for a in res["acts"] if a["measure_kind"] == "retry"][0]["measure"]["ms"] = None
    assert any("Try again" in x for x in _fail("CR-3", res)["reasons"])


def test_no_observation_is_blocked_never_pass_and_an_action_error_fails():
    assert kit.judge(kit.ROW["J-1"], None, "chromium")["status"] == "BLOCKED"
    res = good("J-1")
    res["obs"] = {}
    assert _blocked("J-1", res)["reasons"] == ["J-1 (chromium): context A not observed"]
    res = good("J-1")
    res["observe_error"] = "open (A): Timeout"
    res["obs"] = {}
    assert _blocked("J-1", res)["status"] == "BLOCKED"
    res = good("J-2")
    res["action_error"] = "name (A): no Save name button"
    assert any("action failed" in x for x in _fail("J-2", res)["reasons"])
    res = good("V3-DEL")
    res["obs"].pop("A")
    assert _blocked("V3-DEL", res)["status"] == "BLOCKED"


def test_an_unrelated_earlier_fault_is_never_counted_as_a_plants_own_failure():
    # Each planted fault fails at its own judge with its own reason, not at an unrelated row's reason.
    res = good("E-5")
    res["obs"]["C"]["row_markup"] = 1
    reasons = _fail("E-5", res)["reasons"]
    assert all("b/i elements" in x for x in reasons)


def facts(**over) -> dict:
    f = {"user_agent": "Mozilla/5.0 (iPhone ...) AppleWebKit/605.1.15", "webkit_version": "26.0",
         "maxTouchPoints": 5, "viewport": {"width": 390, "height": 844}, "isMobile": True, "hasTouch": True,
         "viewport_meta": kit.VIEWPORT_META, "scroll_width": 390}
    f.update(over)
    return f


WEBKIT_STEPS = [{"id": i, "status": "PASS"} for i in kit.WEBKIT_ORDER]


def test_ph1_passes_only_with_every_webkit_row_native_facts_meta_width_gate_image_and_tree():
    ok = kit.ph1(facts(), WEBKIT_STEPS, {"status": "PASS"}, {"status": "PASS"}, "a" * 64)
    assert ok["status"] == "PASS" and "not a real iPhone" in ok["notes"][0]
    assert kit.ph1(facts(scroll_width=391), WEBKIT_STEPS, {"status": "PASS"}, {"status": "PASS"}, "a" * 64)[
        "status"] == "FAIL"
    assert kit.ph1(facts(viewport_meta=None), WEBKIT_STEPS, {"status": "PASS"}, {"status": "PASS"}, "a" * 64)[
        "status"] == "FAIL"
    bad_row = [dict(s, status="FAIL") if s["id"] == "E-5" else s for s in WEBKIT_STEPS]
    assert kit.ph1(facts(), bad_row, {"status": "PASS"}, {"status": "PASS"}, "a" * 64)["status"] == "FAIL"
    for args in ((facts(), WEBKIT_STEPS, {"status": "PASS"}, {"status": "PASS"}, None),
                 (facts(), WEBKIT_STEPS, {"status": "PASS"}, None, "a" * 64),
                 (facts(), WEBKIT_STEPS, {"status": "NOT CHECKED"}, {"status": "PASS"}, "a" * 64),
                 (facts(maxTouchPoints=None), WEBKIT_STEPS, {"status": "PASS"}, {"status": "PASS"}, "a" * 64),
                 (facts(viewport={"width": 980, "height": 844}), WEBKIT_STEPS, {"status": "PASS"},
                  {"status": "PASS"}, "a" * 64),
                 (facts(), WEBKIT_STEPS[:-1], {"status": "PASS"}, {"status": "PASS"}, "a" * 64)):
        assert kit.ph1(*args)["status"] == "BLOCKED", args


def test_browser_code_has_no_shims_and_types_exact_code_points():
    js = kit.ROWS_JS + kit.ROW_JS
    for banned in ("addInitScript", "userAgent =", "maxTouchPoints =", "Object.defineProperty(navigator",
                   "clock.install", "page.clock", "setExtraHTTPHeaders", "normalize("):
        assert banned not in js, banned
    assert "keyboard.insertText(" in js and "loc.tap(" in js
    assert re.search(r"T\.\w+", js)  # texts come from TEXT, not literals in the browser code


def test_judges_never_raise_on_garbage():
    for rid in [r["id"] for r in kit.ROWS if not r.get("host")]:
        for res in ({}, {"acts": "x", "obs": []}, {"acts": [None, 3, {"measure_kind": "held"}], "obs": {"A": 1}},
                    {"obs": {c: {"rows": [None, "x"], "who": None} for c in "ABCLUV"}}):
            v = kit.judge(kit.ROW[rid], copy.deepcopy(res), "chromium", SERVED)
            assert v["status"] in ("FAIL", "BLOCKED"), (rid, v)


# ---- #279 (Security #105 R-1, H-279-R1): the rows' page routes keep to the build's origin and fall back ----
# ROWS_JS runs in Node (no browser) against a fake page and a route chain modelled on Playwright's: page routes
# newest first, then context routes; fallback() hands the request to the next matching handler, continue() sends it
# and skips the rest, abort() aborts it. The context chain holds a recorder (it sees what a page route passed on)
# and the control abort route exactly as SETUP writes it.
R1_ROUTES_NODE = r"""
const fs = require('node:fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const ORIGIN = input.origin; const T = input.text; const t = () => 'fixed';
const p3 = {log: {requests: []}, users: {}};
new Function('p3', 'T', 'ORIGIN', 't', input.rows_js)(p3, T, ORIGIN, t);
const pageRoutes = [];
let current = null; const held = [];
const realSetTimeout = setTimeout;
globalThis.setTimeout = (fn, ms, ...rest) => { if (ms === input.hold_ms && current) held.push(current);
  return realSetTimeout(fn, ms, ...rest); };
const contextRoutes = [
  {match: () => true, handler: (route) => { current.seen_by_context = true; return route.fallback(); }},
  {match: (url) => (url.protocol === 'http:' || url.protocol === 'https:') && url.origin !== ORIGIN,
   handler: (route) => route.abort('blockedbyclient')},
];
async function send(name, method, url) {
  const req = {name, method, url, outcome: 'network', skipped_later_handlers: false, seen_by_context: false};
  current = req;
  const chain = [...pageRoutes.slice().reverse(), ...contextRoutes].filter(r => r.match(new URL(url)));
  let i = 0;
  const next = async () => {
    if (i >= chain.length) return;
    const r = chain[i++];
    await r.handler({
      request: () => ({method: () => method, url: () => url}),
      fallback: async () => next(),
      continue: async () => { req.skipped_later_handlers = i < chain.length; },
      abort: async (code) => { req.outcome = (r.page ? 'aborted by page route: ' : 'aborted by context route: ') + code; },
    });
  };
  await next();
  req.held = held.includes(req);
  current = null;
  return req;
}
const OTHER = 'https://elsewhere.invalid';
let scenario = null;
const locator = () => ({count: async () => { if (scenario) { const s = scenario; scenario = null; await s(); } return 0; }});
const page = {
  route: async (match, handler) => { pageRoutes.push({match, handler, page: true}); },
  unroute: async (match, handler) => { const k = pageRoutes.findIndex(r => r.match === match && r.handler === handler);
    if (k >= 0) pageRoutes.splice(k, 1); },
  getByRole: () => locator(), locator: () => locator(),
};
const u = {name: 'A', p: page, touch: false};
(async () => {
  const out = {held: [], list: []};
  scenario = async () => {
    for (const [name, method, url] of [['same GET', 'GET', ORIGIN + '/api/items'],
        ['same POST (first)', 'POST', ORIGIN + '/api/items'], ['same POST (again)', 'POST', ORIGIN + '/api/items'],
        ['cross POST', 'POST', OTHER + '/api/items'], ['cross GET', 'GET', OTHER + '/api/items']])
      out.held.push(await send(name, method, url));
  };
  const h = await p3.held(u, {op: 'add', item: 'x', hold_ms: input.hold_ms});
  out.held_error = h.error || null; out.routes_left_after_held = pageRoutes.length;
  await p3.act(u, {do: 'abort_list'});
  for (const [name, method, url] of [['same GET', 'GET', ORIGIN + '/api/items'], ['same POST', 'POST', ORIGIN + '/api/items'],
      ['cross GET', 'GET', OTHER + '/api/items'], ['cross POST', 'POST', OTHER + '/api/items']])
    out.list.push(await send(name, method, url));
  out.unabort = await p3.act(u, {do: 'unabort'}); out.routes_left = pageRoutes.length;
  console.log(JSON.stringify(out));
})().catch(e => { console.error(String(e && e.stack || e)); process.exitCode = 1; });
"""


def test_r1_page_routes_keep_to_the_origin_and_fall_back_to_the_control_abort_route():
    payload = {"origin": "http://100.110.162.4:8962", "text": T, "rows_js": kit.ROWS_JS, "hold_ms": 7}
    proc = subprocess.run(["node", "-e", R1_ROUTES_NODE], input=json.dumps(payload), text=True, capture_output=True,
                          timeout=20)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    held = {x["name"]: x for x in out["held"]}
    assert out["held_error"] and out["routes_left_after_held"] == 0  # the fake page ends the row; route removed
    # Same origin, unchanged: the first POST is held and then sent; the GET and the second POST are not held.
    assert [x["name"] for x in out["held"] if x["held"]] == ["same POST (first)"]
    for name in ("same GET", "same POST (first)", "same POST (again)"):
        assert held[name]["outcome"] == "network", held[name]
    lst = {x["name"]: x for x in out["list"]}
    assert lst["same GET"]["outcome"] == "aborted by page route: failed" and lst["same POST"]["outcome"] == "network"
    assert out["unabort"] == {"aborted": 1} and out["routes_left"] == 0  # only the same-origin list GET counted
    # Another origin's /api/items is never theirs: it falls through to the context abort route (the second witness).
    for x in (held["cross POST"], held["cross GET"], lst["cross GET"], lst["cross POST"]):
        assert x["outcome"] == "aborted by context route: blockedbyclient" and not x["held"], x
    # Whatever a page route does not abort itself goes on by fallback(): the context routes still see it.
    for x in out["held"] + out["list"]:
        if x["outcome"] != "aborted by page route: failed":
            assert x["seen_by_context"] and not x["skipped_later_handlers"], x
