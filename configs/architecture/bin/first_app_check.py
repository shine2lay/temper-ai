#!/usr/bin/env python3
"""first_app_check (System architecture, queue #91, 2026-10-16; profile input #92): QA's frozen critical
journey of the Team's first app, or of a new build of it, in a real browser, with no model.

The spec is QA's kit qa-first-app-critical-v1 (CASE-KIT.json, SHA256 49813ec9...6f180a): eight
action/observation rows at 1280x800, en-US, UTC, synthetic inputs only. Nothing is added or dropped;
wider cases (blank input, long text, storage faults, mobile, offline, accessibility, other browsers)
stay NOT CHECKED, not waived.

The browser is temper's playwright-mcp service (headless Chromium; --isolated, so each session's
profile lives in memory; the container is its sandbox), driven over MCP as design_capture.py does.

  A  reach and pin: one session opens the origin, fetches the three runtime files in the page
     (same origin, no cache) and this script hashes the bytes the browser received, and the "/"
     document itself, which must be the pinned index.html; a wrong or missing file REFUSES the
     check before any step. The session is closed.
  B  journey: a new session; a fresh browser context made at the kit's viewport, locale and time
     zone, with request, error, dialog and websocket observers attached before its first page
     exists. Each kit row: its action, then what the rendered page shows (roles, names, visible
     row text, checkbox state, order, focus, the empty-list sentence, any saving warning) read back
     and compared with the kit's expected values. The first failure stops the journey; the rows
     after it are NOT CHECKED. One viewport screenshot is taken after the C1-5 reload assertions
     pass, before any deletion.
  C  traffic and errors: every request the context made; one outside the origin, not a GET, a
     websocket, a same-origin path other than /, /index.html, /style.css and /app.js, or a page
     reference outside the origin fails the traffic gate, kept apart from the rows' app-state
     results: the overall verdict is FAIL and the journey stops there (the kit: record any other
     attempt and stop). Uncaught page errors, dialogs and crashes fail the row they happened in.
     Console errors and warnings are listed, not failed (the kit: harmless messages are reported,
     not promoted). Requests are observed, not blocked.
  D  cleanup: the context is closed and confirmed gone from the browser, then browser_close.
     Cleanup not confirmed turns a PASS into BLOCKED.

Verdicts and exit codes: PASS 0, FAIL 1 (the app was observed failing a row or the traffic gate),
REFUSED 2 (served files do not match the pins, or the profile is not valid), BLOCKED 3 (the app was
not reached or observed, or cleanup is unknown).

The target. Without a profile: the first build, exactly as frozen (LIVE_ORIGIN, FROZEN_PINS, the kit's
own wording). With one (mode=live only): a JSON object with exactly these keys, see
--print-default-profile for today's values in that form:
  origin           https://spark.tailbb5055.ts.net:<port>, nothing else (no path, no other host)
  pins             {"index.html": sha256, "style.css": sha256, "app.js": sha256}, 64 lowercase hex each
  kit_id, kit_sha256, kit_not_checked   the frozen kit's id, its SHA256, its NOT CHECKED list
  wording          {"heading", "textbox", "add_button", "delete_button" (with {item} once, as in
                   "Delete {item}"), "empty_text"}: the build's names for the kit's controls
Anything missing, extra or malformed REFUSES the run before the browser is contacted. The rows'
items, inputs, order, checks, viewport, locale, timing, allowed paths and cleanup never change.

  first_app_check.py --mode live --out DIR [--profile JSON]   the served app, against its pins
  first_app_check.py --mode controls --out DIR      the synthetic page in fixtures/first_app, its
                                                    broken copies and the reworded page in
                                                    fixtures/first_app_reworded (with its profile,
                                                    without one, and with a refused one), served
                                                    from this process; exit 0 only if every
                                                    control gets its expected verdict
  first_app_check.py --print-default-profile        today's constants, in the profile's form

Writes DIR/receipt.json, DIR/summary.md and DIR/after-reload.png (controls: one folder per case plus
DIR/controls.json); prints a one-line JSON summary last.
"""

import argparse
import asyncio
import base64
import datetime
import functools
import hashlib
import http.server
import json
import pathlib
import re
import shutil
import socket
import socketserver
import sys
import tempfile
import threading
import urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
FIXTURE = HERE.parent / "fixtures" / "first_app"
FIXTURE_REWORDED = HERE.parent / "fixtures" / "first_app_reworded"

KIT_ID = "qa-first-app-critical-v1"
KIT_SHA256 = "49813ec9b0d3890be27404f9e0e9f385a3e01ab78acac771ad428494f6d6180a"
LIVE_ORIGIN = "https://spark.tailbb5055.ts.net:8960"
# BASELINE-MANIFEST.json of Project d9f807c3 (commit 707ec4a4, tree 24101c3a), as frozen in the kit.
FROZEN_PINS = {
    "index.html": {"bytes": 1162, "sha256": "f9c5cc648a4875d791a44aec7b536d82d4cc7f4b2d9f89bd93e79d407da06237"},
    "style.css": {"bytes": 6438, "sha256": "2d45d3d0e32990249d79abfc3d74b4e8a52a1435ee9807e2c33e048ee9b292c5"},
    "app.js": {"bytes": 13771, "sha256": "de4484c7dc9035b7ad3242babc9f3f9b223fd090fa8253b638180ee601e8855e"},
}
VIEWPORT = {"width": 1280, "height": 800}
LOCALE = "en-US"
TIMEZONE = "UTC"
ALLOWED_PATHS = ("/", "/index.html", "/style.css", "/app.js")
EMPTY_TEXT = "Your list is empty. Type an item above, then press Enter or Add."
SCREENSHOT_AFTER = "C1-5"
# The kit's names for the page's controls (CASE-KIT.json "steps"); a profile's wording replaces them.
DEFAULT_WORDING = {"heading": "To-do list", "textbox": "New item", "add_button": "Add",
                   "delete_button": "Delete {item}", "empty_text": EMPTY_TEXT}
# The kit's NOT CHECKED list, word for word (CASE-KIT.json proposedLiveScope.additionalChecksRemainNotChecked).
KIT_NOT_CHECKED = ["blank/UTF16-200/320px", "literal HTML input", "seeded malformed storage",
                   "storage-fault injection", "long-directory browser negative",
                   "cross-browser/offline/accessibility/AT/multi-tab", "Design and owner observation"]

# The profile input (#92): exactly these keys, checked before anything contacts the browser.
PIN_FILES = ("index.html", "style.css", "app.js")
PROFILE_KEYS = ("origin", "pins", "kit_id", "kit_sha256", "kit_not_checked", "wording")
WORDING_KEYS = ("heading", "textbox", "add_button", "delete_button", "empty_text")
ORIGIN_RE = re.compile(r"https://spark\.tailbb5055\.ts\.net:([1-9][0-9]{0,4})")
HEX64_RE = re.compile(r"[0-9a-f]{64}")
PROFILE_MAX_CHARS = 16384

BUY = {"text": "Buy milk", "checked": False}
BUY_DONE = {"text": "Buy milk", "checked": True}
CALL = {"text": "Call Sam", "checked": False}


def kit_steps(w: dict) -> list[dict]:
    """The kit's eight rows (CASE-KIT.json "steps") with a build's page wording w. DEFAULT_WORDING gives the
    kit's own words, word for word; only the controls' names and the empty-list sentence follow w. The
    items, inputs, order, checks and focus targets are the kit's."""
    tb, add, empty = w["textbox"], w["add_button"], w["empty_text"]

    def delete(item: str) -> str:
        return w["delete_button"].replace("{item}", item)

    return [
        {"id": "C1-1", "action": "Navigate once in the admitted fresh context.",
         "expected": {"heading": w["heading"], "textboxLabel": tb, "button": add, "rows": [], "emptyText": empty}},
        {"id": "C1-2", "action": "Enter exactly two leading/trailing ASCII spaces around Buy milk, then submit by Enter.",
         "input": "  Buy milk  ", "expected": {"rows": [BUY], "input": "", "focus": tb}},
        {"id": "C1-3", "action": f"Enter Call Sam and activate {add}.", "input": "Call Sam",
         "expected": {"rows": [BUY, CALL], "input": "", "focus": tb}},
        {"id": "C1-4", "action": "Focus Buy milk native checkbox and press Space once.",
         "expected": {"rows": [BUY_DONE, CALL], "focus": "Buy milk checkbox"}},
        {"id": "C1-5", "action": "Reload and assert actual rendered text/order/check states. Capture one synthetic "
         "full-viewport screenshot only after these assertions and before deletion.",
         "expected": {"rows": [BUY_DONE, CALL], "savingWarning": False}},
        {"id": "C1-6", "action": f"Activate the button with accessible name {delete('Buy milk')}.",
         "expected": {"rows": [CALL], "focus": "Call Sam checkbox"}},
        {"id": "C1-7", "action": f"Activate the button with accessible name {delete('Call Sam')}.",
         "expected": {"rows": [], "focus": tb, "emptyText": empty}},
        {"id": "C1-8", "action": "Reload once and assert the rendered empty list. Cleanup later discards the complete "
         "isolated context/profile.",
         "expected": {"rows": [], "emptyText": empty, "savingWarning": False}},
    ]


# The kit's eight rows, word for word, as the first build is checked.
STEPS = kit_steps(DEFAULT_WORDING)

# Controls and what each must get: (verdict, first row that FAILs, traffic gate). Pages: fixtures/first_app
# (app.js variants) and fixtures/first_app_reworded (the same page in other words, with its profile.json).
CONTROLS = [
    {"case": "clean", "variant": "clean", "expect": ("PASS", None, "PASS")},
    {"case": "outside_request", "variant": "outside_request", "expect": ("FAIL", None, "FAIL at C1-1")},
    {"case": "wrong_focus", "variant": "wrong_focus", "expect": ("FAIL", "C1-2", "NOT CHECKED")},
    {"case": "wrong_order", "variant": "wrong_order", "expect": ("FAIL", "C1-3", "NOT CHECKED")},
    {"case": "page_error", "variant": "page_error", "expect": ("FAIL", "C1-4", "NOT CHECKED")},
    {"case": "forget_reload", "variant": "forget_reload", "expect": ("FAIL", "C1-5", "NOT CHECKED")},
    {"case": "wrong_pin", "variant": "clean", "wrong_pin": "index.html", "expect": ("REFUSED", None, "NOT CHECKED")},
    # A new build through the profile input: its own wording passes, the kit's own words fail it at the
    # first wording row, and a profile naming any other origin (here: this reachable page's) is refused
    # before the browser is contacted.
    {"case": "reworded_profile", "variant": "clean", "page": "reworded", "profile": "fixture",
     "expect": ("PASS", None, "PASS")},
    {"case": "reworded_no_profile", "variant": "clean", "page": "reworded",
     "expect": ("FAIL", "C1-1", "NOT CHECKED")},
    {"case": "bad_profile", "variant": "clean", "page": "reworded", "profile": "served_origin",
     "expect": ("REFUSED", None, "NOT CHECKED")},
]
EXIT = {"PASS": 0, "FAIL": 1, "REFUSED": 2, "BLOCKED": 3}

SAVE_RE = re.compile(r"\b(sav(e|ed|es|ing)|stor(e|ed|age|ing))\b", re.I)
NEG_RE = re.compile(r"\b(not|n't|cannot|couldn|unable|fail(ed|s|ure)?|error|unavailable|lost|won't)\b", re.I)


def now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="milliseconds")


# ---------------------------------------------------------------- the target: first build or profile (unit-tested)


def default_target() -> dict:
    """The first build, exactly as frozen: what a run without a profile checks."""
    return {"source": "default", "profile_sha256": None, "origin": LIVE_ORIGIN,
            "pins": {n: dict(p) for n, p in FROZEN_PINS.items()}, "kit_id": KIT_ID, "kit_sha256": KIT_SHA256,
            "kit_not_checked": list(KIT_NOT_CHECKED), "wording": dict(DEFAULT_WORDING)}


def default_profile() -> dict:
    """Today's constants in the profile's form (--print-default-profile): the shape a new build's profile takes."""
    return {"origin": LIVE_ORIGIN, "pins": {n: p["sha256"] for n, p in FROZEN_PINS.items()}, "kit_id": KIT_ID,
            "kit_sha256": KIT_SHA256, "kit_not_checked": list(KIT_NOT_CHECKED), "wording": dict(DEFAULT_WORDING)}


def _keys_problems(obj: dict, keys: tuple, where: str) -> list[str]:
    out = []
    missing = [k for k in keys if k not in obj]
    extra = sorted(str(k) for k in obj if k not in keys)
    if missing:
        out.append(f"{where} is missing {', '.join(missing)}")
    if extra:
        out.append(f"{where} has keys that are not allowed: {', '.join(extra)}")
    return out


def _text_problem(value, where: str, limit: int = 300) -> str | None:
    """One line of printable text, single spaces, no spaces at either end: how a rendered name reads."""
    if not isinstance(value, str) or not value:
        return f"{where} is not text"
    if " ".join(value.split()) != value or not value.isprintable() or len(value) > limit:
        return (f"{where} must be one line of printable text with single spaces and none at either end, "
                f"at most {limit} characters")
    return None


def origin_problems(origin) -> list[str]:
    if not isinstance(origin, str):
        return ["origin is not text"]
    m = ORIGIN_RE.fullmatch(origin)
    if not m:
        return [f"origin {origin[:120]!r} is not https://spark.tailbb5055.ts.net:<port> (no other scheme, host "
                "or path)"]
    port = int(m.group(1))
    if port > 65535:
        return [f"origin port {port} is not a port"]
    if port == 443:
        return ["origin port 443 is https's default, which browsers drop, so the page's origin would not match"]
    return []


def pins_problems(pins) -> list[str]:
    if not isinstance(pins, dict):
        return ["pins is not an object of file name to SHA256"]
    out = _keys_problems(pins, PIN_FILES, "pins")
    for name in PIN_FILES:
        if name in pins and not (isinstance(pins[name], str) and HEX64_RE.fullmatch(pins[name])):
            out.append(f"pin for {name} is not 64 lowercase hex characters")
    return out


def kit_problems(p: dict) -> list[str]:
    out = []
    if "kit_id" in p and (problem := _text_problem(p["kit_id"], "kit_id", 200)):
        out.append(problem)
    if "kit_sha256" in p and not (isinstance(p["kit_sha256"], str) and HEX64_RE.fullmatch(p["kit_sha256"])):
        out.append("kit_sha256 is not 64 lowercase hex characters")
    if "kit_not_checked" in p:
        items = p["kit_not_checked"]
        if not isinstance(items, list) or not items or len(items) > 50:
            out.append("kit_not_checked is not the kit's list of what stays NOT CHECKED (1 to 50 entries)")
        else:
            out += [x for i, item in enumerate(items) if (x := _text_problem(item, f"kit_not_checked[{i}]"))]
    return out


def wording_problems(w) -> list[str]:
    if not isinstance(w, dict):
        return ["wording is not an object"]
    out = _keys_problems(w, WORDING_KEYS, "wording")
    out += [x for k in WORDING_KEYS if k in w and (x := _text_problem(w[k], f"wording.{k}"))]
    d = w.get("delete_button")
    if isinstance(d, str) and d.count("{item}") != 1:
        out.append('wording.delete_button must hold {item} exactly once, as in "Delete {item}"')
    return out


def parse_profile(text: str | None) -> tuple[dict | None, list[str]]:
    """The run's target and the profile's problems. No profile (left out or blank): the first build's
    constants, exactly. Otherwise one JSON object with exactly PROFILE_KEYS, each checked strictly; any
    problem means the run is REFUSED before anything contacts the browser."""
    if text is None or not text.strip():
        return default_target(), []
    if len(text) > PROFILE_MAX_CHARS:
        return None, [f"profile is {len(text)} characters long; at most {PROFILE_MAX_CHARS}"]
    try:
        p = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, [f"profile is not JSON ({exc.msg} at character {exc.pos}); pass one JSON object as text"]
    if not isinstance(p, dict):
        return None, ["profile is not a JSON object"]
    problems = _keys_problems(p, PROFILE_KEYS, "profile")
    if "origin" in p:
        problems += origin_problems(p["origin"])
    if "pins" in p:
        problems += pins_problems(p["pins"])
    problems += kit_problems(p)
    if "wording" in p:
        problems += wording_problems(p["wording"])
    if problems:
        return None, problems
    return {"source": "input", "profile_sha256": sha256(text.encode()), "origin": p["origin"],
            "pins": {n: {"sha256": p["pins"][n]} for n in PIN_FILES}, "kit_id": p["kit_id"],
            "kit_sha256": p["kit_sha256"], "kit_not_checked": list(p["kit_not_checked"]),
            "wording": {k: p["wording"][k] for k in WORDING_KEYS}}, []


# ---------------------------------------------------------------- pure comparators (unit-tested)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_pins(pins: dict, fetched: dict, origin: str, final_url: str | None) -> dict:
    """Each pinned file fetched with status 200, its SHA-256 and (where pinned: the first build's
    pins) its exact length; the page not redirected off the origin. A profile pins SHA-256 alone,
    which fixes the length too. fetched: name -> {status, bytes, sha256, content_type} or {error}."""
    files, ok = [], True
    if not final_url or origin_of(final_url) != origin:
        ok = False
    for name, pin in pins.items():
        got = fetched.get(name) or {"error": "not fetched"}
        match = (got.get("status") == 200 and got.get("sha256") == pin["sha256"]
                 and ("bytes" not in pin or got.get("bytes") == pin["bytes"]))
        ok = ok and match
        files.append({"file": name, "pinned_sha256": pin["sha256"], "pinned_bytes": pin.get("bytes"),
                      "served_sha256": got.get("sha256"), "served_bytes": got.get("bytes"),
                      "status": got.get("status"), "content_type": got.get("content_type"),
                      "error": got.get("error"), "match": match})
    return {"ok": ok, "final_url": final_url, "files": files}


def check_root(root: dict | None, index_pin: dict) -> dict:
    """QA's suggestion 1: the "/" document the journey loads, hashed itself, must be the pinned index.html."""
    got = root or {"error": "not fetched"}
    match = got.get("status") == 200 and got.get("sha256") == index_pin["sha256"]
    return {"path": "/", "pinned_sha256": index_pin["sha256"], "pinned_as": "index.html",
            "served_sha256": got.get("sha256"), "served_bytes": got.get("bytes"), "status": got.get("status"),
            "content_type": got.get("content_type"), "url": got.get("url"), "error": got.get("error"),
            "match": match}


def pin_stage(pins: dict, fetched: dict, root: dict | None, origin: str, final_url: str | None) -> dict:
    """Stage A's result: the three pinned files and the "/" document; ok only when all four match."""
    res = check_pins(pins, fetched, origin, final_url)
    res["root"] = check_root(root, pins["index.html"])
    res["ok"] = res["ok"] and res["root"]["match"]
    return res


def origin_of(url: str) -> str:
    u = urllib.parse.urlsplit(url)
    return f"{u.scheme}://{u.netloc}"


def saving_warning(obs: dict) -> list[str]:
    """Visible text that warns the list was not saved: an alert/status region about saving or
    storage, or any visible sentence naming saving/storage together with a failure word."""
    found = []
    for text in obs.get("alerts") or []:
        if SAVE_RE.search(text):
            found.append(text)
    for sentence in re.split(r"(?<=[.!?])\s+", obs.get("body_text") or ""):
        if SAVE_RE.search(sentence) and NEG_RE.search(sentence) and sentence not in found:
            found.append(sentence)
    return found


def compare_step(expected: dict, obs: dict | None, textbox: str = DEFAULT_WORDING["textbox"]) -> list[str]:
    """What the rendered page showed that differs from the kit's expected values for one row."""
    if obs is None:
        return ["no observation"]
    out = []
    if obs.get("action_error"):
        out.append(f"action could not be done: {obs['action_error']}")
    for key, want in expected.items():
        if key == "heading":
            if want not in (obs.get("headings") or []):
                out.append(f"heading {want!r} not shown; headings {obs.get('headings')!r}")
        elif key == "textboxLabel":
            tb = obs.get("textbox") or {}
            if not (tb.get("count") == 1 and tb.get("visible") and tb.get("enabled")):
                out.append(f"one visible, enabled textbox named {want!r} expected; saw {tb!r}")
        elif key == "button":
            b = obs.get("add_button") or {}
            if not (b.get("count") == 1 and b.get("visible") and b.get("enabled")):
                out.append(f"one visible, enabled button named {want!r} expected; saw {b!r}")
        elif key == "rows":
            if obs.get("rows") != want:
                out.append(f"rows {obs.get('rows')!r}, expected {want!r}")
        elif key == "emptyText":
            if not obs.get("empty_text_visible"):
                out.append(f"empty-list sentence {want!r} not visible")
        elif key == "input":
            value = (obs.get("textbox") or {}).get("value")
            if value != want:
                out.append(f"{textbox} holds {value!r}, expected {want!r}")
        elif key == "focus":
            if obs.get("focus") != want:
                out.append(f"focus on {obs.get('focus')!r}, expected {want!r}")
        elif key == "savingWarning":
            warn = saving_warning(obs)
            if bool(warn) != want:
                out.append(f"saving warning shown: {warn!r}")
        else:
            out.append(f"unknown expectation {key!r}")
    return out


def traffic_findings(requests: list[dict], websockets: list[dict], origin: str) -> list[str]:
    """Requests outside the kit's policy: GET only, at the exact origin, for its four paths."""
    out = []
    for r in requests:
        url = r.get("url") or ""
        u = urllib.parse.urlsplit(url)
        if u.scheme in ("data", "blob", "about"):
            continue
        if origin_of(url) != origin:
            out.append(f"request outside the origin: {r.get('method')} {url}")
        elif r.get("method") != "GET":
            out.append(f"non-GET request: {r.get('method')} {url}")
        elif u.path not in ALLOWED_PATHS or u.query:
            out.append(f"same-origin request outside the four app paths: GET {url}")
    for w in websockets:
        out.append(f"websocket: {w.get('url')}")
    return out


def reference_findings(refs: list[str], origin: str) -> list[str]:
    """Resources the rendered page points at outside its origin (icons, scripts, images, frames).
    The browser fetches some of them, the favicon for one, without a request event the observers
    see, so the page's own references are checked too."""
    out = []
    for url in refs or []:
        if urllib.parse.urlsplit(url).scheme in ("data", "blob", "about"):
            continue
        if origin_of(url) != origin:
            out.append(f"page references a resource outside the origin: {url}")
    return out


def error_findings(log: dict) -> list[str]:
    """Critical: uncaught page errors, dialogs, crashes, extra pages. Console lines are notes only."""
    out = [f"page error: {e.get('message')}" for e in log.get("pageerrors") or []]
    out += [f"dialog {d.get('type')}: {d.get('message')}" for d in log.get("dialogs") or []]
    out += [f"page crashed at {c.get('t')}" for c in log.get("crashes") or []]
    out += [f"extra page opened: {p.get('url')}" for p in log.get("popups") or []]
    return out


def judge_step(step: dict, obs: dict | None, new_log: dict, origin: str, wording: dict | None = None) -> dict:
    """One row's app-state verdict from what the page showed and its page errors, and apart from it the
    traffic gate's findings while the row ran: requests or page references outside the kit's policy."""
    reasons = compare_step(step["expected"], obs, (wording or DEFAULT_WORDING)["textbox"]) + error_findings(new_log)
    traffic = reference_findings((obs or {}).get("resource_refs") or [], origin)
    traffic += traffic_findings(new_log.get("requests") or [], new_log.get("websockets") or [], origin)
    return {"status": "FAIL" if reasons else "PASS", "reasons": reasons, "traffic": traffic}


def traffic_gate(r: dict) -> dict:
    """The privacy/traffic gate (QA's suggestion 3), kept apart from the rows' app-state results. FAIL on
    anything outside the kit's traffic policy, in any row or after the last one; PASS only when the
    observers were on before the first navigation and all eight rows ran with nothing outside it;
    otherwise NOT CHECKED (rows_observed says how far it got). Outside traffic never gives a PASS."""
    findings, first = [], None
    for s in r.get("steps") or []:
        for x in s.get("traffic") or []:
            findings.append(f"{s['id']}: {x}")
            first = first or s["id"]
    for x in r.get("late_traffic") or []:
        findings.append(f"after the last row: {x}")
        first = first or "after the last row"
    rows = [s["id"] for s in r.get("steps") or []]
    if findings:
        status = "FAIL"
    elif (r.get("observers") or {}).get("before_first_navigation") and rows == [s["id"] for s in STEPS]:
        status = "PASS"
    else:
        status = "NOT CHECKED"
    return {"status": status, "first_seen": first, "findings": findings, "rows_observed": rows}


def final_verdict(r: dict) -> tuple[str, str]:
    """The receipt's verdict: (PASS|FAIL|REFUSED|BLOCKED, why)."""
    problems = (r.get("profile") or {}).get("problems")
    if problems:
        return "REFUSED", "profile not valid, browser not contacted: " + "; ".join(problems)
    if r.get("runner_error") and not r.get("steps_attempted"):
        return "BLOCKED", f"runner: {r['runner_error']}"
    reach = r.get("reach") or {}
    if reach.get("error"):
        return "BLOCKED", f"app not reached: {reach['error']}"
    pins = r.get("pins") or {}
    if not pins.get("ok"):
        bad = [f["file"] for f in pins.get("files") or [] if not f.get("match")]
        if "root" in pins and not pins["root"].get("match"):
            bad.append('"/" (the document the journey loads; must be the pinned index.html)')
        return "REFUSED", "served files do not match the pins: " + (", ".join(bad) or "origin/redirect")
    if not (r.get("observers") or {}).get("before_first_navigation"):
        return "BLOCKED", "observers were not attached before the first navigation"
    steps = r.get("steps") or []
    failed = [s for s in steps if s["status"] == "FAIL"]
    gate = traffic_gate(r)
    if failed or gate["status"] == "FAIL":
        why = [f"{failed[0]['id']}: " + "; ".join(failed[0]["reasons"])] if failed else []
        if gate["status"] == "FAIL":
            why.append("traffic gate: " + "; ".join(gate["findings"]))
        return "FAIL", " | ".join(why)
    if r.get("runner_error"):
        return "BLOCKED", f"runner stopped the journey: {r['runner_error']}"
    if len(steps) != len(STEPS) or any(s["status"] != "PASS" for s in steps):
        return "BLOCKED", "not every row was observed"
    late = r.get("late_findings") or []
    if late:
        return "FAIL", "after the last row: " + "; ".join(late)
    if not (r.get("cleanup") or {}).get("confirmed"):
        return "BLOCKED", "cleanup not confirmed: " + json.dumps(r.get("cleanup"))
    if not r.get("screenshot"):
        return "BLOCKED", "no screenshot after the reload assertions"
    return "PASS", f"all {len(STEPS)} rows observed as the kit expects"


# ---------------------------------------------------------------- browser (playwright-mcp)

VISIBLE_TEXT_FN = r"""(li) => { const parts = []; const w = document.createTreeWalker(li, NodeFilter.SHOW_TEXT);
  let n; while ((n = w.nextNode())) { const el = n.parentElement; if (!el) continue;
    if (el.closest('button,[role=button],select,textarea,input')) continue;
    if (el.checkVisibility && !el.checkVisibility({opacityProperty: true, visibilityProperty: true})) continue;
    const r = el.getBoundingClientRect(); if (r.width <= 1 || r.height <= 1) continue;
    parts.push(n.textContent); }
  return parts.join(' ').replace(/\s+/g, ' ').trim(); }"""

DESCRIBE_ACTIVE_FN = r"""() => { const e = document.activeElement;
  if (!e || e === document.body || e === document.documentElement) return 'body';
  const name = e.getAttribute('aria-label') || (e.labels && e.labels.length ? e.labels[0].innerText : '')
    || e.innerText || e.getAttribute('placeholder') || '';
  return e.tagName.toLowerCase() + (e.type ? '[' + e.type + ']' : '') + ' "' + name.replace(/\s+/g, ' ').trim().slice(0, 60) + '"'; }"""

ROWS_JS = "fa.p.getByRole('listitem').filter({has: fa.p.getByRole('checkbox')})"

def observe_js(w: dict) -> str:
    """What the rendered page shows now, read with the build's names for the controls (w)."""
    return (
        "async (page) => { const fa = page.__fa; const p = fa.p; await p.waitForTimeout(300);\n"
        f"const tb = p.getByRole('textbox', {{name: {json.dumps(w['textbox'])}, exact: true}}); "
        "const textbox = {count: await tb.count()};\n"
        "if (textbox.count === 1) { textbox.visible = await tb.isVisible(); textbox.enabled = await tb.isEnabled();\n"
        "  textbox.value = await tb.inputValue(); textbox.focused = await tb.evaluate(e => e === document.activeElement); }\n"
        f"const add = p.getByRole('button', {{name: {json.dumps(w['add_button'])}, exact: true}}); "
        "const add_button = {count: await add.count()};\n"
        "if (add_button.count === 1) { add_button.visible = await add.isVisible(); add_button.enabled = await add.isEnabled(); }\n"
        "const headings = (await p.getByRole('heading').allInnerTexts()).map(t => t.replace(/\\s+/g, ' ').trim());\n"
        f"const items = {ROWS_JS}; const n = await items.count(); const rows = []; let focus = null;\n"
        "for (let i = 0; i < n; i++) { const it = items.nth(i); const cb = it.getByRole('checkbox').first();\n"
        f"  const text = await it.evaluate({VISIBLE_TEXT_FN}); rows.push({{text, checked: await cb.isChecked()}});\n"
        "  if (await cb.evaluate(e => e === document.activeElement)) focus = text + ' checkbox'; }\n"
        f"if (!focus && textbox.focused) focus = {json.dumps(w['textbox'])};\n"
        f"if (!focus) focus = await p.evaluate({DESCRIBE_ACTIVE_FN});\n"
        "const body_text = await p.evaluate(() => document.body ? document.body.innerText.replace(/\\s+/g, ' ').trim() : '');\n"
        f"const empty_text_visible = body_text.includes({json.dumps(w['empty_text'])});\n"
        "const alerts = await p.locator('[role=alert],[role=status],[aria-live]').evaluateAll(els => els\n"
        "  .filter(e => !e.checkVisibility || e.checkVisibility()).map(e => e.innerText.replace(/\\s+/g, ' ').trim()).filter(Boolean));\n"
        "let aria = ''; try { aria = await p.locator('body').ariaSnapshot(); } catch (e) { aria = 'ariaSnapshot error: ' + e.message; }\n"
        "const resource_refs = await p.evaluate(() => [...document.querySelectorAll(\n"
        "  'link[href],script[src],img[src],iframe[src],source[src],video[src],audio[src],embed[src],object[data]')]\n"
        "  .filter(e => !(e.tagName === 'LINK' && /^(alternate|canonical|author|help|license|next|prev|search)$/i.test(e.rel)))\n"
        "  .map(e => e.href || e.src || e.data).filter(Boolean));\n"
        "return {at: new Date().toISOString(), url: p.url(), headings, textbox, add_button, rows, focus, empty_text_visible,\n"
        "  alerts, body_text: body_text.slice(0, 2000), aria: aria.slice(0, 4000), resource_refs}; }"
    )


def action_js(step_id: str, origin: str, w: dict | None = None) -> str:
    """The kit row's action, performed as a user would: keyboard and clicks on named controls (w: the
    build's names for them)."""
    w = w or DEFAULT_WORDING

    def named_button(name: str) -> str:
        return f"p.getByRole('button', {{name: {json.dumps(name)}, exact: true}})"
    load = "await p.waitForLoadState('networkidle', {timeout: 5000}).catch(() => {});"
    find_row = (
        f"const items = {ROWS_JS}; const n = await items.count(); let idx = [];\n"
        f"for (let i = 0; i < n; i++) {{ if ((await items.nth(i).evaluate({VISIBLE_TEXT_FN})) === 'Buy milk') idx.push(i); }}\n"
        "if (idx.length !== 1) throw new Error('rows with text Buy milk: ' + idx.length);\n"
    )
    tb = f"p.getByRole('textbox', {{name: {json.dumps(w['textbox'])}, exact: true}})"
    delete = w["delete_button"]
    body = {
        "C1-1": f"await p.goto({json.dumps(origin + '/')}, {{waitUntil: 'load', timeout: 20000}}); {load}",
        "C1-2": f"await {tb}.click({{timeout: 5000}}); await p.keyboard.type('  Buy milk  '); await p.keyboard.press('Enter');",
        "C1-3": f"await {tb}.click({{timeout: 5000}}); await p.keyboard.type('Call Sam'); "
                f"await {named_button(w['add_button'])}.click({{timeout: 5000}});",
        "C1-4": find_row + "await items.nth(idx[0]).getByRole('checkbox').first().focus({timeout: 5000}); "
                "await p.keyboard.press('Space');",
        "C1-5": f"await p.reload({{waitUntil: 'load', timeout: 20000}}); {load}",
        "C1-6": f"await {named_button(delete.replace('{item}', 'Buy milk'))}.click({{timeout: 5000}});",
        "C1-7": f"await {named_button(delete.replace('{item}', 'Call Sam'))}.click({{timeout: 5000}});",
        "C1-8": f"await p.reload({{waitUntil: 'load', timeout: 20000}}); {load}",
    }[step_id]
    return ("async (page) => { const fa = page.__fa; const p = fa.p; const started = new Date().toISOString();\n"
            f"try {{ {body} }} catch (e) {{ return {{started, ended: new Date().toISOString(), "
            "action_error: String(e && e.message || e).split('\\n')[0].slice(0, 300)}; }\n"
            "return {started, ended: new Date().toISOString()}; }")


SETUP = (
    "async (page) => { const browser = page.context().browser(); const t = () => new Date().toISOString();\n"
    f"const ctx = await browser.newContext({{viewport: {json.dumps(VIEWPORT)}, locale: {json.dumps(LOCALE)}, "
    f"timezoneId: {json.dumps(TIMEZONE)}}});\n"
    "const log = {requests: [], responses: [], failed: [], pageerrors: [], console: [], dialogs: [], websockets: [],\n"
    "  popups: [], crashes: [], serviceworkers: []};\n"
    "const fa = {ctx, log, seen: {}}; page.__fa = fa;\n"
    "ctx.on('request', r => log.requests.push({t: t(), method: r.method(), url: r.url(), type: r.resourceType(), "
    "navigation: r.isNavigationRequest()}));\n"
    "ctx.on('response', r => log.responses.push({t: t(), url: r.url(), status: r.status()}));\n"
    "ctx.on('requestfailed', r => log.failed.push({t: t(), url: r.url(), error: (r.failure() || {}).errorText}));\n"
    "ctx.on('serviceworker', w => log.serviceworkers.push({t: t(), url: w.url()}));\n"
    "ctx.on('page', pg => { if (fa.p && pg !== fa.p) log.popups.push({t: t(), url: pg.url()}); });\n"
    "const observers_at = t(); const p = await ctx.newPage(); fa.p = p;\n"
    "p.on('pageerror', e => log.pageerrors.push({t: t(), message: String(e && e.message || e).slice(0, 500)}));\n"
    "p.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') log.console.push({t: t(), type: m.type(), "
    "text: m.text().slice(0, 500)}); });\n"
    "p.on('dialog', d => { log.dialogs.push({t: t(), type: d.type(), message: d.message().slice(0, 300)}); d.dismiss().catch(() => {}); });\n"
    "p.on('websocket', w => log.websockets.push({t: t(), url: w.url()}));\n"
    "p.on('crash', () => log.crashes.push({t: t()}));\n"
    "const env = await p.evaluate(() => ({url: location.href, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,\n"
    "  locale: Intl.DateTimeFormat().resolvedOptions().locale, language: navigator.language, width: innerWidth, height: innerHeight,\n"
    "  storage_keys: (() => { try { return localStorage.length; } catch (e) { return 'n/a: ' + e.name; } })()}));\n"
    "return {observers_at, page_created: t(), browser_version: browser.version(), first_url: p.url(), env,\n"
    "  requests_before_navigation: log.requests.length}; }"
)

# Everything the observers saw since the last call (and the running totals).
DRAIN = (
    "async (page) => { const fa = page.__fa; const out = {};\n"
    "for (const [k, v] of Object.entries(fa.log)) { const from = fa.seen[k] || 0; out[k] = v.slice(from); fa.seen[k] = v.length; }\n"
    "return out; }"
)

SCREENSHOT = "async (page) => (await page.__fa.p.screenshot({type: 'png'})).toString('base64')"

CLOSE = (
    "async (page) => { const fa = page.__fa; const browser = page.context().browser(); let error = null;\n"
    "try { await fa.ctx.close(); } catch (e) { error = String(e).slice(0, 300); }\n"
    "return {at: new Date().toISOString(), error, page_closed: fa.p.isClosed(),\n"
    "  context_still_in_browser: browser.contexts().includes(fa.ctx)}; }"
)


def pin_js(origin: str, names: list[str]) -> str:
    return (
        "async (page) => { const out = {}; let final_url = null;\n"
        f"try {{ const r = await page.goto({json.dumps(origin + '/')}, {{waitUntil: 'load', timeout: 20000}});\n"
        "  final_url = page.url(); out.status = r ? r.status() : null;\n"
        "  if (r) { try { out.root = {status: r.status(), content_type: r.headers()['content-type'] || null, url: r.url(),\n"
        "    b64: (await r.body()).toString('base64')}; }\n"
        "    catch (e) { out.root = {error: String(e && e.message || e).split('\\n')[0].slice(0, 200)}; } } }\n"
        "catch (e) { return {error: String(e && e.message || e).split('\\n')[0].slice(0, 300)}; }\n"
        f"out.files = await page.evaluate(async (names) => {{ const res = {{}};\n"
        "  for (const n of names) { try { const r = await fetch(new URL(n, location.origin + '/').href, {cache: 'no-store'});\n"
        "    const b = new Uint8Array(await r.arrayBuffer()); let s = ''; for (let i = 0; i < b.length; i += 8192)\n"
        "      s += String.fromCharCode.apply(null, b.subarray(i, i + 8192));\n"
        "    res[n] = {status: r.status, content_type: r.headers.get('content-type'), b64: btoa(s), url: r.url}; }\n"
        "  catch (e) { res[n] = {error: String(e).slice(0, 200)}; } } return res; }, "
        f"{json.dumps(names)});\n"
        "out.final_url = final_url; return out; }"
    )


def mcp_result(res) -> object:
    """The JSON value a playwright-mcp tool returned, or raise with its error (as design_capture.py)."""
    text = "\n".join(getattr(c, "text", "") or "" for c in res.content)
    if getattr(res, "isError", False) or text.startswith("### Error"):
        raise RuntimeError(text[:800])
    m = re.search(r"### Result\n(.*?)(?:\n### |\Z)", text, re.S)
    if not m:
        return None
    body = m.group(1).strip()
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return body


def say(msg: str) -> None:
    print(f"[{now()}] {msg}", flush=True)


def new_receipt(label: str, target: dict | None) -> dict:
    """The receipt's opening fields. target None: a profile refused before anything ran."""
    t = target or {}
    r: dict = {"label": label, "kit_id": t.get("kit_id"), "kit_sha256": t.get("kit_sha256"), "origin": t.get("origin"),
               "checker_sha256": sha256(pathlib.Path(__file__).read_bytes()), "started_at": now(),
               "context": {"viewport": VIEWPORT, "locale": LOCALE, "timezone": TIMEZONE},
               "steps": [], "steps_attempted": 0, "browser_contact": False,
               "kit_not_checked": t.get("kit_not_checked")}
    if target:
        r["profile"] = {"source": t["source"], "sha256": t["profile_sha256"], "wording": t["wording"]}
        if t.get("control_note"):
            r["profile"]["control_note"] = t["control_note"]
    return r


def refuse_profile(text: str, problems: list[str], out: pathlib.Path, label: str) -> dict:
    """A profile that is not valid: REFUSED, and the receipt shows the browser was never contacted."""
    out.mkdir(parents=True, exist_ok=True)
    r = new_receipt(label, None)
    r["profile"] = {"source": "input", "sha256": sha256(text.encode()), "problems": problems}
    say(f"[{label}] profile not valid; the browser is not contacted: {'; '.join(problems)}")
    return finish(r, out)


async def check_profile(browser_url: str, text: str | None, out: pathlib.Path, label: str,
                        control_origin: str | None = None) -> dict:
    """mode=live's path: the profile (or none: the first build) is checked first, then stages A-D run on
    its target. control_origin, for the controls only: after the profile is accepted, the synthetic
    page's address stands in for its origin, so its wording and pins are tried on a page the run serves."""
    target, problems = parse_profile(text)
    if problems:
        return refuse_profile(text or "", problems, out, label)
    if control_origin:
        target["control_note"] = (f"control: the profile's origin {target['origin']} replaced, after the "
                                  f"profile was accepted, by the synthetic page's {control_origin}")
        target["origin"] = control_origin
    return await check_target(browser_url, target, out, label)


def hashed(f: dict) -> dict:
    """A body the browser received, as the receipt records it: status, length and SHA-256, not the bytes."""
    if f.get("error"):
        return {"error": f["error"]}
    data = base64.b64decode(f["b64"])
    return {"status": f["status"], "bytes": len(data), "sha256": sha256(data),
            "content_type": f.get("content_type"), "url": f.get("url")}


async def check_target(browser_url: str, target: dict, out: pathlib.Path, label: str) -> dict:
    """Stages A-D against one accepted target (origin, pins, kit, wording); writes out/receipt.json,
    out/summary.md, out/after-reload.png."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    out.mkdir(parents=True, exist_ok=True)
    origin, pins = target["origin"], target["pins"]
    r = new_receipt(label, target)

    async def call(s, code):
        return mcp_result(await s.call_tool("browser_run_code_unsafe", {"code": code}))

    # A: reach and pin, in a session of its own, closed before the journey.
    say(f"[{label}] A: open {origin}/ and fetch {', '.join(pins)} in the browser")
    r["browser_contact"] = True
    try:
        async with streamablehttp_client(browser_url) as (rd, wr, _):
            async with ClientSession(rd, wr) as s:
                await s.initialize()
                try:
                    got = await call(s, pin_js(origin, list(pins)))
                finally:
                    await s.call_tool("browser_close", {})
    except Exception as exc:  # noqa: BLE001 - the browser service itself: BLOCKED, not an app result
        r["runner_error"] = f"stage A: {exc.__class__.__name__}: {str(exc)[:400]}"
        return finish(r, out)
    if not isinstance(got, dict) or got.get("error"):
        r["reach"] = {"error": (got or {}).get("error") if isinstance(got, dict) else repr(got)[:300]}
        say(f"[{label}] A: not reached: {r['reach']['error']}")
        return finish(r, out)
    fetched = {name: hashed(f) for name, f in (got.get("files") or {}).items()}
    root = hashed(got["root"]) if got.get("root") else None
    r["reach"] = {"status": got.get("status"), "final_url": got.get("final_url")}
    r["pins"] = pin_stage(pins, fetched, root, origin, got.get("final_url"))
    for f in r["pins"]["files"]:
        say(f"[{label}] A: {f['file']} served {f['served_sha256']} ({f['served_bytes']} B) "
            f"{'matches' if f['match'] else 'DOES NOT MATCH'} pin {f['pinned_sha256'][:12]}...")
    rt = r["pins"]["root"]
    say(f'[{label}] A: "/" served {rt["served_sha256"]} ({rt["served_bytes"]} B) '
        f"{'matches' if rt['match'] else 'DOES NOT MATCH'} the index.html pin {rt['pinned_sha256'][:12]}...")
    if not r["pins"]["ok"]:
        say(f"[{label}] A: REFUSED before any step")
        return finish(r, out)

    # B-D: the journey in a fresh context, then traffic/errors, then cleanup.
    try:
        async with streamablehttp_client(browser_url) as (rd, wr, _):
            async with ClientSession(rd, wr) as s:
                await s.initialize()
                try:
                    await journey(s, call, r, target, out, label)
                finally:
                    await cleanup(s, call, r, label)
    except Exception as exc:  # noqa: BLE001
        r.setdefault("runner_error", f"stage B-D: {exc.__class__.__name__}: {str(exc)[:400]}")
    return finish(r, out)


async def journey(s, call, r: dict, target: dict, out: pathlib.Path, label: str) -> None:
    origin, w = target["origin"], target["wording"]
    observe = observe_js(w)
    setup = await call(s, SETUP)
    r["observers"] = {"attached_at": setup["observers_at"], "page_created_at": setup["page_created"],
                      "requests_before_navigation": setup["requests_before_navigation"],
                      "before_first_navigation": setup["first_url"] == "about:blank"
                      and setup["requests_before_navigation"] == 0}
    r["browser"] = {"version": setup["browser_version"], "env_before_navigation": setup["env"]}
    say(f"[{label}] B: fresh context, Chromium {setup['browser_version']}, env {json.dumps(setup['env'])}")
    r["log"] = {}
    try:
        for step in kit_steps(w):
            act = await call(s, action_js(step["id"], origin, w))
            obs = await call(s, observe)
            if isinstance(act, dict) and act.get("action_error"):
                obs["action_error"] = act["action_error"]
            new = await call(s, DRAIN)
            merge_log(r["log"], new)
            v = judge_step(step, obs, new, origin, w)
            r["steps_attempted"] += 1
            r["steps"].append({"id": step["id"], "action": step["action"], "expected": step["expected"],
                               "action_started": (act or {}).get("started"), "action_ended": (act or {}).get("ended"),
                               "observed": obs, "status": v["status"], "reasons": v["reasons"],
                               "traffic": v["traffic"]})
            say(f"[{label}] B: {step['id']} {v['status']}: rows {json.dumps(obs.get('rows'))}, focus {obs.get('focus')!r}"
                + (f" -- {'; '.join(v['reasons'])}" if v["reasons"] else "")
                + (f" -- traffic gate: {'; '.join(v['traffic'])}" if v["traffic"] else ""))
            # The first failure stops the journey; so does traffic outside the policy (the kit: record any
            # other attempt and stop), which fails the traffic gate, not the row.
            if v["status"] == "FAIL" or v["traffic"]:
                break
            if step["id"] == SCREENSHOT_AFTER:
                png = base64.b64decode(await call(s, SCREENSHOT))
                (out / "after-reload.png").write_bytes(png)
                r["screenshot"] = {"file": "after-reload.png", "taken_at": now(), "bytes": len(png),
                                   "sha256": sha256(png), "after": SCREENSHOT_AFTER, "viewport": VIEWPORT}
                say(f"[{label}] B: screenshot after {SCREENSHOT_AFTER} assertions ({len(png)} B)")
    finally:
        new = await call(s, DRAIN)
        merge_log(r["log"], new)
        late_traffic = traffic_findings(new.get("requests") or [], new.get("websockets") or [], origin)
        late = late_traffic + error_findings(new)
        if late:
            r["late_findings"] = late
        if late_traffic:
            r["late_traffic"] = late_traffic


async def cleanup(s, call, r: dict, label: str) -> None:
    c: dict = {}
    try:
        if "observers" in r:
            c["context"] = await call(s, CLOSE)
        await s.call_tool("browser_close", {})
        c["browser_close"] = "ok"
    except Exception as exc:  # noqa: BLE001
        c["error"] = f"{exc.__class__.__name__}: {str(exc)[:300]}"
    ctxc = c.get("context") or {}
    c["confirmed"] = bool(c.get("browser_close") == "ok" and ctxc and not ctxc.get("error")
                          and ctxc.get("page_closed") and not ctxc.get("context_still_in_browser"))
    r["cleanup"] = c
    say(f"[{label}] D: cleanup {'confirmed' if c['confirmed'] else 'NOT confirmed'}: {json.dumps(c)}")


def merge_log(total: dict, new: dict) -> None:
    for k, v in (new or {}).items():
        total.setdefault(k, []).extend(v)


def finish(r: dict, out: pathlib.Path) -> dict:
    r["finished_at"] = now()
    done = {s["id"] for s in r["steps"]}
    r["not_checked"] = [s["id"] for s in STEPS if s["id"] not in done]
    log = r.get("log") or {}
    r["traffic"] = {
        "requests": len(log.get("requests") or []),
        "outside_or_unexpected": traffic_findings(log.get("requests") or [], log.get("websockets") or [], r["origin"]),
        "critical_errors": error_findings(log),
        "console_notes": log.get("console") or [],
        "failed_requests": log.get("failed") or [],
    }
    r["traffic_gate"] = traffic_gate(r)
    r["verdict"], r["why"] = final_verdict(r)
    (out / "receipt.json").write_text(json.dumps(r, indent=1))
    (out / "summary.md").write_text(summary_md(r))
    say(f"[{r['label']}] VERDICT {r['verdict']}: {r['why']}")
    return r


def summary_md(r: dict) -> str:
    lines = [f"# first_app_check: {r['label']}", "",
             f"Verdict: **{r['verdict']}**: {r['why']}", "",
             f"Kit {r['kit_id']} (SHA256 {r['kit_sha256']}). Origin {r['origin']}. "
             f"Checker SHA256 {r['checker_sha256']}. {r['started_at']} to {r['finished_at']}.", ""]
    p = r.get("profile") or {}
    if p.get("problems"):
        lines += [f"Profile (SHA256 {p['sha256']}) REFUSED; the browser was not contacted:", ""]
        lines += [f"- {x}" for x in p["problems"]] + [""]
    else:
        lines += [("Profile: none; the first build's constants." if p.get("source") == "default"
                   else f"Profile: given, SHA256 {p.get('sha256')}.")
                  + f" Page wording: {json.dumps(p.get('wording'))}."
                  + (f" {p['control_note']}." if p.get("control_note") else ""), ""]
    lines += [f"Browser contacted: {'yes' if r.get('browser_contact') else 'no'}.", ""]
    if r.get("browser"):
        lines += [f"Browser: Chromium {r['browser']['version']}; context {json.dumps(r['browser']['env_before_navigation'])}.", ""]
    lines += ["## Served files", "", "| file | pinned | served | bytes | status | match |", "|---|---|---|---|---|---|"]
    pins = r.get("pins") or {}
    for f in pins.get("files") or []:
        lines.append(f"| {f['file']} | {f['pinned_sha256'][:16]}... | {(f['served_sha256'] or '-')[:16]}... | "
                     f"{f['served_bytes']} | {f['status']} | {'yes' if f['match'] else 'NO'} |")
    if pins.get("root"):
        f = pins["root"]
        lines.append(f"| / (as index.html) | {f['pinned_sha256'][:16]}... | {(f['served_sha256'] or '-')[:16]}... | "
                     f"{f['served_bytes']} | {f['status']} | {'yes' if f['match'] else 'NO'} |")
    lines += ["", "## Kit rows", "", "| row | result | rows seen | focus | notes |", "|---|---|---|---|---|"]
    for s in r["steps"]:
        o = s["observed"] or {}
        rows = ", ".join(f"{x['text']}{' [x]' if x['checked'] else ' [ ]'}" for x in o.get("rows") or []) or "(none)"
        lines.append(f"| {s['id']} | {s['status']} | {rows} | {o.get('focus')} | {'; '.join(s['reasons']) or '-'} |")
    for sid in r["not_checked"]:
        lines.append(f"| {sid} | NOT CHECKED | | | |")
    g = r["traffic_gate"]
    lines += ["", "## Traffic gate", "", f"**{g['status']}**" + (f", first seen at {g['first_seen']}" if g["first_seen"] else "")
              + f"; rows observed: {', '.join(g['rows_observed']) or 'none'}. Requests are observed, not blocked.", ""]
    lines += [f"- {x}" for x in g["findings"]]
    t = r["traffic"]
    lines += ["", "## Traffic and errors", "", f"Requests seen: {t['requests']}.",
              f"Outside the origin or the four paths: {t['outside_or_unexpected'] or 'none'}.",
              f"Critical errors: {t['critical_errors'] or 'none'}.",
              f"Console errors/warnings (notes): {[c['text'] for c in t['console_notes']] or 'none'}.",
              f"Failed requests: {t['failed_requests'] or 'none'}.", "",
              f"Screenshot: {(r.get('screenshot') or {}).get('file', 'none')}.",
              f"Cleanup: {json.dumps(r.get('cleanup'))}.", "",
              "## NOT CHECKED (the kit's list; not waived)", ""]
    lines += [f"- {x}" for x in r.get("kit_not_checked") or ["(no kit: the profile was refused)"]] + [""]
    if r.get("runner_error"):
        lines.append(f"Runner error: {r['runner_error']}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- controls: the synthetic page


def materialize(variant: str, root: pathlib.Path, page: pathlib.Path = FIXTURE) -> pathlib.Path:
    """One control's site: index.html from its page folder (fixtures/first_app, or first_app_reworded: the
    same page in other words), style.css and app.js from fixtures/first_app, app.js's VARIANT line set."""
    site = root / variant
    site.mkdir(parents=True)
    shutil.copy(page / "index.html", site / "index.html")
    shutil.copy(FIXTURE / "style.css", site / "style.css")
    src = (FIXTURE / "app.js").read_text()
    line = 'const VARIANT = "clean";'
    if src.count(line) != 1:
        raise SystemExit("fixtures/first_app/app.js: the VARIANT line is not there exactly once")
    (site / "app.js").write_text(src.replace(line, f"const VARIANT = {json.dumps(variant)};"))
    return site


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # noqa: D401 - silence the access log
        pass

    def log_request(self, code="-", size="-"):  # every answered request, counted for the controls
        self.server.hits.append(f"{self.command} {self.path} {code}")


def serve(site: pathlib.Path, browser_host: str, serve_ip: str | None):
    handler = functools.partial(Quiet, directory=str(site))
    srv = socketserver.ThreadingTCPServer(("0.0.0.0", 0), handler)
    srv.daemon_threads = True
    srv.hits = []
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    ip = serve_ip
    if not ip:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect((socket.gethostbyname(browser_host), 80))
            ip = probe.getsockname()[0]
        finally:
            probe.close()
    return f"http://{ip}:{srv.server_address[1]}", srv


def control_profile(kind: str, served_origin: str) -> str:
    """The profile text a control passes: the reworded page's own (fixtures/first_app_reworded/profile.json),
    or the same pointed at the synthetic page the run serves, an origin a profile may not name."""
    text = (FIXTURE_REWORDED / "profile.json").read_text()
    if kind == "fixture":
        return text
    if kind == "served_origin":
        return json.dumps(dict(json.loads(text), origin=served_origin))
    raise ValueError(f"unknown control profile {kind!r}")


def gate_result(r: dict) -> str:
    g = r["traffic_gate"]
    return g["status"] + (f" at {g['first_seen']}" if g["status"] == "FAIL" else "")


async def controls(args, out: pathlib.Path) -> int:
    host = urllib.parse.urlparse(args.browser).hostname
    results = []
    with tempfile.TemporaryDirectory(prefix="first-app-controls-") as tmp:
        for case in CONTROLS:
            page = FIXTURE_REWORDED if case.get("page") == "reworded" else FIXTURE
            site = materialize(case["variant"], pathlib.Path(tmp) / case["case"], page)
            origin, srv = serve(site, host, args.serve_ip)
            label = f"control {case['case']}"
            try:
                if case.get("profile"):
                    r = await check_profile(args.browser, control_profile(case["profile"], origin),
                                            out / case["case"], label, control_origin=origin)
                else:
                    target = default_target()
                    target["origin"] = origin
                    target["pins"] = {n: {"bytes": (site / n).stat().st_size, "sha256": sha256((site / n).read_bytes())}
                                      for n in PIN_FILES}
                    if case.get("wrong_pin"):
                        target["pins"][case["wrong_pin"]]["sha256"] = "0" * 64
                    r = await check_target(args.browser, target, out / case["case"], label)
            finally:
                srv.shutdown()
                srv.server_close()
            failed_at = next((s["id"] for s in r["steps"] if s["status"] == "FAIL"), None)
            got, gate = (r["verdict"], failed_at), gate_result(r)
            ok = (got == case["expect"][:2] and gate == case["expect"][2]
                  and (r["verdict"] != "REFUSED" or r["steps_attempted"] == 0))
            if (r.get("profile") or {}).get("problems"):
                ok = ok and not r["browser_contact"] and not srv.hits  # a refused profile reaches nothing
            results.append({"case": case["case"], "expected": list(case["expect"][:2]), "got": list(got),
                            "traffic_gate": {"expected": case["expect"][2], "got": gate},
                            "why": r["why"], "steps_attempted": r["steps_attempted"],
                            "browser_contact": r["browser_contact"], "page_requests": len(srv.hits), "ok": ok})
            say(f"control {case['case']}: expected {case['expect']}, got {got + (gate,)}, page requests "
                f"{len(srv.hits)}: {'OK' if ok else 'WRONG'}")
    summary = {"mode": "controls", "all_ok": all(x["ok"] for x in results), "cases": results,
               "checker_sha256": sha256(pathlib.Path(__file__).read_bytes())}
    (out / "controls.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps({"mode": "controls", "all_ok": summary["all_ok"],
                      "verdicts": {x["case"]: x["got"] for x in results},
                      "traffic_gates": {x["case"]: x["traffic_gate"]["got"] for x in results}, "out": str(out)}),
          flush=True)
    return 0 if summary["all_ok"] else 1


async def live(args, out: pathlib.Path) -> int:
    if (out / "receipt.json").exists():
        raise SystemExit(f"{out}/receipt.json exists: one live run per folder (no retry-until-green)")
    r = await check_profile(args.browser, args.profile, out, "live")
    print(json.dumps({"mode": "live", "verdict": r["verdict"], "why": r["why"],
                      "rows": {s["id"]: s["status"] for s in r["steps"]} | {x: "NOT CHECKED" for x in r["not_checked"]},
                      "pins_ok": (r.get("pins") or {}).get("ok"), "screenshot": bool(r.get("screenshot")),
                      "cleanup_confirmed": (r.get("cleanup") or {}).get("confirmed"),
                      "traffic_gate": r["traffic_gate"]["status"], "profile": r["profile"]["source"],
                      "browser_contact": r["browser_contact"], "receipt": str(out / "receipt.json")}), flush=True)
    return EXIT[r["verdict"]]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--mode", choices=("live", "controls"))
    ap.add_argument("--out")
    ap.add_argument("--profile", default=None, help="live: a new build's profile, one JSON object as text")
    ap.add_argument("--print-default-profile", action="store_true", help="print today's constants as a profile")
    ap.add_argument("--browser", default="http://playwright-mcp:8931/mcp")
    ap.add_argument("--serve-ip", default="", help="controls: the address the browser reaches this process at")
    a = ap.parse_args()
    if a.print_default_profile:
        print(json.dumps(default_profile(), indent=1))
        return 0
    if not a.mode or not a.out:
        ap.error("--mode and --out are required")
    if a.mode == "controls" and a.profile:
        ap.error("--profile is for --mode live; the controls bring their own profiles")
    out = pathlib.Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    return asyncio.run(live(a, out) if a.mode == "live" else controls(a, out))


if __name__ == "__main__":
    sys.exit(main())
