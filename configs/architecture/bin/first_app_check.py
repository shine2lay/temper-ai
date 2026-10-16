#!/usr/bin/env python3
"""first_app_check (System architecture, queue #91, 2026-10-16): QA's frozen critical journey of the
Team's first app, in a real browser, with no model.

The spec is QA's kit qa-first-app-critical-v1 (CASE-KIT.json, SHA256 49813ec9...6f180a): eight
action/observation rows at 1280x800, en-US, UTC, synthetic inputs only. Nothing is added or dropped;
wider cases (blank input, long text, storage faults, mobile, offline, accessibility, other browsers)
stay NOT CHECKED, not waived.

The browser is temper's playwright-mcp service (headless Chromium; --isolated, so each session's
profile lives in memory; the container is its sandbox), driven over MCP as design_capture.py does.

  A  reach and pin: one session opens the origin, fetches the three runtime files in the page
     (same origin, no cache) and this script hashes the bytes the browser received; a wrong or
     missing file REFUSES the check before any step. The session is closed.
  B  journey: a new session; a fresh browser context made at the kit's viewport, locale and time
     zone, with request, error, dialog and websocket observers attached before its first page
     exists. Each kit row: its action, then what the rendered page shows (roles, names, visible
     row text, checkbox state, order, focus, the empty-list sentence, any saving warning) read back
     and compared with the kit's expected values. The first failure stops the journey; the rows
     after it are NOT CHECKED. One viewport screenshot is taken after the C1-5 reload assertions
     pass, before any deletion.
  C  traffic and errors: every request the context made; one outside the origin, not a GET, a
     websocket, or a same-origin path other than /, /index.html, /style.css and /app.js fails the
     row it happened in. So do uncaught page errors, dialogs and crashes. Console errors and
     warnings are listed, not failed (the kit: harmless messages are reported, not promoted).
     Requests are observed, not blocked.
  D  cleanup: the context is closed and confirmed gone from the browser, then browser_close.
     Cleanup not confirmed turns a PASS into BLOCKED.

Verdicts and exit codes: PASS 0, FAIL 1 (the app was observed failing a row), REFUSED 2 (served files
do not match the pins), BLOCKED 3 (the app was not reached or observed, or cleanup is unknown).

  first_app_check.py --mode live --out DIR          the served app, against the frozen pins
  first_app_check.py --mode controls --out DIR      the synthetic page in fixtures/first_app and its
                                                    broken copies, served from this process; exit 0
                                                    only if every control gets its expected verdict

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

BUY = {"text": "Buy milk", "checked": False}
BUY_DONE = {"text": "Buy milk", "checked": True}
CALL = {"text": "Call Sam", "checked": False}
# The kit's eight rows, word for word (CASE-KIT.json "steps").
STEPS = [
    {"id": "C1-1", "action": "Navigate once in the admitted fresh context.",
     "expected": {"heading": "To-do list", "textboxLabel": "New item", "button": "Add", "rows": [],
                  "emptyText": EMPTY_TEXT}},
    {"id": "C1-2", "action": "Enter exactly two leading/trailing ASCII spaces around Buy milk, then submit by Enter.",
     "input": "  Buy milk  ", "expected": {"rows": [BUY], "input": "", "focus": "New item"}},
    {"id": "C1-3", "action": "Enter Call Sam and activate Add.", "input": "Call Sam",
     "expected": {"rows": [BUY, CALL], "input": "", "focus": "New item"}},
    {"id": "C1-4", "action": "Focus Buy milk native checkbox and press Space once.",
     "expected": {"rows": [BUY_DONE, CALL], "focus": "Buy milk checkbox"}},
    {"id": "C1-5", "action": "Reload and assert actual rendered text/order/check states. Capture one synthetic "
     "full-viewport screenshot only after these assertions and before deletion.",
     "expected": {"rows": [BUY_DONE, CALL], "savingWarning": False}},
    {"id": "C1-6", "action": "Activate the button with accessible name Delete Buy milk.",
     "expected": {"rows": [CALL], "focus": "Call Sam checkbox"}},
    {"id": "C1-7", "action": "Activate the button with accessible name Delete Call Sam.",
     "expected": {"rows": [], "focus": "New item", "emptyText": EMPTY_TEXT}},
    {"id": "C1-8", "action": "Reload once and assert the rendered empty list. Cleanup later discards the complete "
     "isolated context/profile.",
     "expected": {"rows": [], "emptyText": EMPTY_TEXT, "savingWarning": False}},
]

# Controls: the synthetic page's variants (fixtures/first_app/app.js) and the verdict each must get.
CONTROLS = [
    {"case": "clean", "variant": "clean", "expect": ("PASS", None)},
    {"case": "outside_request", "variant": "outside_request", "expect": ("FAIL", "C1-1")},
    {"case": "wrong_focus", "variant": "wrong_focus", "expect": ("FAIL", "C1-2")},
    {"case": "wrong_order", "variant": "wrong_order", "expect": ("FAIL", "C1-3")},
    {"case": "page_error", "variant": "page_error", "expect": ("FAIL", "C1-4")},
    {"case": "forget_reload", "variant": "forget_reload", "expect": ("FAIL", "C1-5")},
    {"case": "wrong_pin", "variant": "clean", "wrong_pin": "index.html", "expect": ("REFUSED", None)},
]
EXIT = {"PASS": 0, "FAIL": 1, "REFUSED": 2, "BLOCKED": 3}

SAVE_RE = re.compile(r"\b(sav(e|ed|es|ing)|stor(e|ed|age|ing))\b", re.I)
NEG_RE = re.compile(r"\b(not|n't|cannot|couldn|unable|fail(ed|s|ure)?|error|unavailable|lost|won't)\b", re.I)


def now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="milliseconds")


# ---------------------------------------------------------------- pure comparators (unit-tested)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_pins(pins: dict, fetched: dict, origin: str, final_url: str | None) -> dict:
    """Each pinned file fetched with status 200, its exact length and SHA-256; the page not
    redirected off the origin. fetched: name -> {status, bytes, sha256, content_type} or {error}."""
    files, ok = [], True
    if not final_url or origin_of(final_url) != origin:
        ok = False
    for name, pin in pins.items():
        got = fetched.get(name) or {"error": "not fetched"}
        match = (got.get("status") == 200 and got.get("bytes") == pin["bytes"]
                 and got.get("sha256") == pin["sha256"])
        ok = ok and match
        files.append({"file": name, "pinned_sha256": pin["sha256"], "pinned_bytes": pin["bytes"],
                      "served_sha256": got.get("sha256"), "served_bytes": got.get("bytes"),
                      "status": got.get("status"), "content_type": got.get("content_type"),
                      "error": got.get("error"), "match": match})
    return {"ok": ok, "final_url": final_url, "files": files}


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


def compare_step(expected: dict, obs: dict | None) -> list[str]:
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
                out.append(f"New item holds {value!r}, expected {want!r}")
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


def judge_step(step: dict, obs: dict | None, new_log: dict, origin: str) -> dict:
    """One row's verdict from what the page showed and what happened on the wire while it ran."""
    reasons = compare_step(step["expected"], obs)
    reasons += reference_findings((obs or {}).get("resource_refs") or [], origin)
    reasons += traffic_findings(new_log.get("requests") or [], new_log.get("websockets") or [], origin)
    reasons += error_findings(new_log)
    return {"status": "FAIL" if reasons else "PASS", "reasons": reasons}


def final_verdict(r: dict) -> tuple[str, str]:
    """The receipt's verdict: (PASS|FAIL|REFUSED|BLOCKED, why)."""
    if r.get("runner_error") and not r.get("steps_attempted"):
        return "BLOCKED", f"runner: {r['runner_error']}"
    reach = r.get("reach") or {}
    if reach.get("error"):
        return "BLOCKED", f"app not reached: {reach['error']}"
    pins = r.get("pins") or {}
    if not pins.get("ok"):
        bad = [f["file"] for f in pins.get("files") or [] if not f.get("match")]
        return "REFUSED", "served files do not match the pins: " + (", ".join(bad) or "origin/redirect")
    if not (r.get("observers") or {}).get("before_first_navigation"):
        return "BLOCKED", "observers were not attached before the first navigation"
    steps = r.get("steps") or []
    failed = [s for s in steps if s["status"] == "FAIL"]
    if failed:
        s = failed[0]
        return "FAIL", f"{s['id']}: " + "; ".join(s["reasons"])
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

OBSERVE = (
    "async (page) => { const fa = page.__fa; const p = fa.p; await p.waitForTimeout(300);\n"
    "const tb = p.getByRole('textbox', {name: 'New item', exact: true}); const textbox = {count: await tb.count()};\n"
    "if (textbox.count === 1) { textbox.visible = await tb.isVisible(); textbox.enabled = await tb.isEnabled();\n"
    "  textbox.value = await tb.inputValue(); textbox.focused = await tb.evaluate(e => e === document.activeElement); }\n"
    "const add = p.getByRole('button', {name: 'Add', exact: true}); const add_button = {count: await add.count()};\n"
    "if (add_button.count === 1) { add_button.visible = await add.isVisible(); add_button.enabled = await add.isEnabled(); }\n"
    "const headings = (await p.getByRole('heading').allInnerTexts()).map(t => t.replace(/\\s+/g, ' ').trim());\n"
    f"const items = {ROWS_JS}; const n = await items.count(); const rows = []; let focus = null;\n"
    "for (let i = 0; i < n; i++) { const it = items.nth(i); const cb = it.getByRole('checkbox').first();\n"
    f"  const text = await it.evaluate({VISIBLE_TEXT_FN}); rows.push({{text, checked: await cb.isChecked()}});\n"
    "  if (await cb.evaluate(e => e === document.activeElement)) focus = text + ' checkbox'; }\n"
    "if (!focus && textbox.focused) focus = 'New item';\n"
    f"if (!focus) focus = await p.evaluate({DESCRIBE_ACTIVE_FN});\n"
    "const body_text = await p.evaluate(() => document.body ? document.body.innerText.replace(/\\s+/g, ' ').trim() : '');\n"
    f"const empty_text_visible = body_text.includes({json.dumps(EMPTY_TEXT)});\n"
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


def action_js(step_id: str, origin: str) -> str:
    """The kit row's action, performed as a user would: keyboard and clicks on named controls."""
    load = "await p.waitForLoadState('networkidle', {timeout: 5000}).catch(() => {});"
    find_row = (
        f"const items = {ROWS_JS}; const n = await items.count(); let idx = [];\n"
        f"for (let i = 0; i < n; i++) {{ if ((await items.nth(i).evaluate({VISIBLE_TEXT_FN})) === 'Buy milk') idx.push(i); }}\n"
        "if (idx.length !== 1) throw new Error('rows with text Buy milk: ' + idx.length);\n"
    )
    tb = "p.getByRole('textbox', {name: 'New item', exact: true})"
    body = {
        "C1-1": f"await p.goto({json.dumps(origin + '/')}, {{waitUntil: 'load', timeout: 20000}}); {load}",
        "C1-2": f"await {tb}.click({{timeout: 5000}}); await p.keyboard.type('  Buy milk  '); await p.keyboard.press('Enter');",
        "C1-3": f"await {tb}.click({{timeout: 5000}}); await p.keyboard.type('Call Sam'); "
                "await p.getByRole('button', {name: 'Add', exact: true}).click({timeout: 5000});",
        "C1-4": find_row + "await items.nth(idx[0]).getByRole('checkbox').first().focus({timeout: 5000}); "
                "await p.keyboard.press('Space');",
        "C1-5": f"await p.reload({{waitUntil: 'load', timeout: 20000}}); {load}",
        "C1-6": "await p.getByRole('button', {name: 'Delete Buy milk', exact: true}).click({timeout: 5000});",
        "C1-7": "await p.getByRole('button', {name: 'Delete Call Sam', exact: true}).click({timeout: 5000});",
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
        "  final_url = page.url(); out.status = r ? r.status() : null; }\n"
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


async def check_target(browser_url: str, origin: str, pins: dict, out: pathlib.Path, label: str) -> dict:
    """Stages A-D against one origin; writes out/receipt.json, out/summary.md, out/after-reload.png."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    out.mkdir(parents=True, exist_ok=True)
    r: dict = {"label": label, "kit_id": KIT_ID, "kit_sha256": KIT_SHA256, "origin": origin,
               "checker_sha256": sha256(pathlib.Path(__file__).read_bytes()), "started_at": now(),
               "context": {"viewport": VIEWPORT, "locale": LOCALE, "timezone": TIMEZONE},
               "steps": [], "steps_attempted": 0}

    async def call(s, code):
        return mcp_result(await s.call_tool("browser_run_code_unsafe", {"code": code}))

    # A: reach and pin, in a session of its own, closed before the journey.
    say(f"[{label}] A: open {origin}/ and fetch {', '.join(pins)} in the browser")
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
    fetched = {}
    for name, f in (got.get("files") or {}).items():
        if f.get("error"):
            fetched[name] = {"error": f["error"]}
            continue
        data = base64.b64decode(f["b64"])
        fetched[name] = {"status": f["status"], "bytes": len(data), "sha256": sha256(data),
                         "content_type": f.get("content_type"), "url": f.get("url")}
    r["reach"] = {"status": got.get("status"), "final_url": got.get("final_url")}
    r["pins"] = check_pins(pins, fetched, origin, got.get("final_url"))
    for f in r["pins"]["files"]:
        say(f"[{label}] A: {f['file']} served {f['served_sha256']} ({f['served_bytes']} B) "
            f"{'matches' if f['match'] else 'DOES NOT MATCH'} pin {f['pinned_sha256'][:12]}...")
    if not r["pins"]["ok"]:
        say(f"[{label}] A: REFUSED before any step")
        return finish(r, out)

    # B-D: the journey in a fresh context, then traffic/errors, then cleanup.
    try:
        async with streamablehttp_client(browser_url) as (rd, wr, _):
            async with ClientSession(rd, wr) as s:
                await s.initialize()
                try:
                    await journey(s, call, r, origin, out, label)
                finally:
                    await cleanup(s, call, r, label)
    except Exception as exc:  # noqa: BLE001
        r.setdefault("runner_error", f"stage B-D: {exc.__class__.__name__}: {str(exc)[:400]}")
    return finish(r, out)


async def journey(s, call, r: dict, origin: str, out: pathlib.Path, label: str) -> None:
    setup = await call(s, SETUP)
    r["observers"] = {"attached_at": setup["observers_at"], "page_created_at": setup["page_created"],
                      "requests_before_navigation": setup["requests_before_navigation"],
                      "before_first_navigation": setup["first_url"] == "about:blank"
                      and setup["requests_before_navigation"] == 0}
    r["browser"] = {"version": setup["browser_version"], "env_before_navigation": setup["env"]}
    say(f"[{label}] B: fresh context, Chromium {setup['browser_version']}, env {json.dumps(setup['env'])}")
    r["log"] = {}
    try:
        for step in STEPS:
            act = await call(s, action_js(step["id"], origin))
            obs = await call(s, OBSERVE)
            if isinstance(act, dict) and act.get("action_error"):
                obs["action_error"] = act["action_error"]
            new = await call(s, DRAIN)
            merge_log(r["log"], new)
            v = judge_step(step, obs, new, origin)
            r["steps_attempted"] += 1
            r["steps"].append({"id": step["id"], "action": step["action"], "expected": step["expected"],
                               "action_started": (act or {}).get("started"), "action_ended": (act or {}).get("ended"),
                               "observed": obs, "status": v["status"], "reasons": v["reasons"]})
            say(f"[{label}] B: {step['id']} {v['status']}: rows {json.dumps(obs.get('rows'))}, focus {obs.get('focus')!r}"
                + (f" -- {'; '.join(v['reasons'])}" if v["reasons"] else ""))
            if v["status"] == "FAIL":
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
        late = traffic_findings(new.get("requests") or [], new.get("websockets") or [], origin) + error_findings(new)
        if late:
            r["late_findings"] = late


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
    if r.get("browser"):
        lines += [f"Browser: Chromium {r['browser']['version']}; context {json.dumps(r['browser']['env_before_navigation'])}.", ""]
    lines += ["## Served files", "", "| file | pinned | served | bytes | status | match |", "|---|---|---|---|---|---|"]
    for f in (r.get("pins") or {}).get("files") or []:
        lines.append(f"| {f['file']} | {f['pinned_sha256'][:16]}... | {(f['served_sha256'] or '-')[:16]}... | "
                     f"{f['served_bytes']} | {f['status']} | {'yes' if f['match'] else 'NO'} |")
    lines += ["", "## Kit rows", "", "| row | result | rows seen | focus | notes |", "|---|---|---|---|---|"]
    for s in r["steps"]:
        o = s["observed"] or {}
        rows = ", ".join(f"{x['text']}{' [x]' if x['checked'] else ' [ ]'}" for x in o.get("rows") or []) or "(none)"
        lines.append(f"| {s['id']} | {s['status']} | {rows} | {o.get('focus')} | {'; '.join(s['reasons']) or '-'} |")
    for sid in r["not_checked"]:
        lines.append(f"| {sid} | NOT CHECKED | | | |")
    t = r["traffic"]
    lines += ["", "## Traffic and errors", "", f"Requests seen: {t['requests']}.",
              f"Outside the origin or the four paths: {t['outside_or_unexpected'] or 'none'}.",
              f"Critical errors: {t['critical_errors'] or 'none'}.",
              f"Console errors/warnings (notes): {[c['text'] for c in t['console_notes']] or 'none'}.",
              f"Failed requests: {t['failed_requests'] or 'none'}.", "",
              f"Screenshot: {(r.get('screenshot') or {}).get('file', 'none')}.",
              f"Cleanup: {json.dumps(r.get('cleanup'))}.", ""]
    if r.get("runner_error"):
        lines.append(f"Runner error: {r['runner_error']}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- controls: the synthetic page


def materialize(variant: str, root: pathlib.Path) -> pathlib.Path:
    site = root / variant
    site.mkdir(parents=True)
    for name in ("index.html", "style.css"):
        shutil.copy(FIXTURE / name, site / name)
    src = (FIXTURE / "app.js").read_text()
    line = 'const VARIANT = "clean";'
    if src.count(line) != 1:
        raise SystemExit("fixtures/first_app/app.js: the VARIANT line is not there exactly once")
    (site / "app.js").write_text(src.replace(line, f"const VARIANT = {json.dumps(variant)};"))
    return site


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # noqa: D401 - silence the access log
        pass


def serve(site: pathlib.Path, browser_host: str, serve_ip: str | None):
    handler = functools.partial(Quiet, directory=str(site))
    srv = socketserver.ThreadingTCPServer(("0.0.0.0", 0), handler)
    srv.daemon_threads = True
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


async def controls(args, out: pathlib.Path) -> int:
    host = urllib.parse.urlparse(args.browser).hostname
    results = []
    with tempfile.TemporaryDirectory(prefix="first-app-controls-") as tmp:
        for case in CONTROLS:
            site = materialize(case["variant"], pathlib.Path(tmp) / case["case"])
            pins = {n: {"bytes": (site / n).stat().st_size, "sha256": sha256((site / n).read_bytes())}
                    for n in FROZEN_PINS}
            if case.get("wrong_pin"):
                pins[case["wrong_pin"]] = dict(pins[case["wrong_pin"]], sha256="0" * 64)
            origin, srv = serve(site, host, args.serve_ip)
            try:
                r = await check_target(args.browser, origin, pins, out / case["case"], f"control {case['case']}")
            finally:
                srv.shutdown()
                srv.server_close()
            failed_at = next((s["id"] for s in r["steps"] if s["status"] == "FAIL"), None)
            got = (r["verdict"], failed_at)
            ok = got == case["expect"] and (r["verdict"] != "REFUSED" or r["steps_attempted"] == 0)
            results.append({"case": case["case"], "expected": list(case["expect"]), "got": list(got),
                            "why": r["why"], "steps_attempted": r["steps_attempted"], "ok": ok})
            say(f"control {case['case']}: expected {case['expect']}, got {got}: {'OK' if ok else 'WRONG'}")
    summary = {"mode": "controls", "all_ok": all(x["ok"] for x in results), "cases": results,
               "checker_sha256": sha256(pathlib.Path(__file__).read_bytes())}
    (out / "controls.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps({"mode": "controls", "all_ok": summary["all_ok"],
                      "verdicts": {x["case"]: x["got"] for x in results}, "out": str(out)}), flush=True)
    return 0 if summary["all_ok"] else 1


async def live(args, out: pathlib.Path) -> int:
    if (out / "receipt.json").exists():
        raise SystemExit(f"{out}/receipt.json exists: one live run per folder (no retry-until-green)")
    r = await check_target(args.browser, LIVE_ORIGIN, FROZEN_PINS, out, "live")
    print(json.dumps({"mode": "live", "verdict": r["verdict"], "why": r["why"],
                      "rows": {s["id"]: s["status"] for s in r["steps"]} | {x: "NOT CHECKED" for x in r["not_checked"]},
                      "pins_ok": (r.get("pins") or {}).get("ok"), "screenshot": bool(r.get("screenshot")),
                      "cleanup_confirmed": (r.get("cleanup") or {}).get("confirmed"),
                      "receipt": str(out / "receipt.json")}), flush=True)
    return EXIT[r["verdict"]]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--mode", choices=("live", "controls"), required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--browser", default="http://playwright-mcp:8931/mcp")
    ap.add_argument("--serve-ip", default="", help="controls: the address the browser reaches this process at")
    a = ap.parse_args()
    out = pathlib.Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    return asyncio.run(live(a, out) if a.mode == "live" else controls(a, out))


if __name__ == "__main__":
    sys.exit(main())
