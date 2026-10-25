#!/usr/bin/env python3
"""first_app_check's Project 3 journey (#125): QA's canonical rows in Chromium and in phone-sized WebKit.

Hypothesis H-125-INTEGRATION-2 (rule 20), written before this rewrite:
- What is wrong, with evidence: this journey still ran #124's provisional PENDING-SPEC rows (C/U/L/N/X/S/W, Pat and
  Quinn, SIM-5, a profile wording table and a WAITING-file host wire), not QA's #32 rows bound to Product's FINAL
  v3.1 (ARCH-EXTENSION-SPEC 49247ff8..., specs-rows d7690a0e...). Its W4 latch trips on any off-origin URL, so
  Security's gate plants (G1-G5) could not be told apart from a real escape.
- The one change: the rows, texts and judges come from first_app_p3_rows.py (QA's rows word for word); this file
  keeps how they run safely: fresh contexts per engine on separate fresh data copies, the traffic gate and W4 latch
  (now with each control plant's exact URL list, G3), W1 admission and image readings, terminal cleanup, receipts
  and the controls. Host rows go only through #126's ops_host_client: until QA's P5 receiving names that wire, a
  live host row is BLOCKED with no request written, and in controls a fake controller acts on the fixture server
  so the browser half is stage-tested while the host verdict stays UNQUALIFIED (never PASS).
- Expected result, and how it is measured: on temper-dev's browser services, twice, the clean fixture passes every
  non-host row in both engines; each planted fault fails at its own row; each gate plant is caught by the gate's own
  event record, or is reported as MISS or not exercised; the first_app and Project 2 tests pass unchanged.
- What proves it wrong: a plant passes, a clean row fails, the two runs differ, a gate plant trips W4, or a kind the
  page sent is neither caught nor reported as a MISS.

    first_app_p3.py --mode controls_p3 --out DIR [--browser URL] [--browser-webkit URL] [--serve-ip IP] [--only ...]
    first_app_p3.py --mode live --out DIR --profile JSON [--browser URL] [--browser-webkit URL]
    first_app_p3.py --print-p3-profile
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import http.server
import json
import os
import pathlib
import re
import sys
import tempfile
import threading
import time
import urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
fac = sys.modules.get("first_app_check")
if fac is None:
    import first_app_check as fac  # noqa: E402
fs = fac.shared_module()
import first_app_p3_admission as admission  # noqa: E402
import first_app_p3_guard as guard  # noqa: E402
import first_app_p3_host as host_wire  # noqa: E402
import first_app_p3_rows as kit  # noqa: E402
import ops_host_client as hc  # noqa: E402

FIXTURE = HERE.parent / "fixtures" / "p3_app"
JOURNEY = kit.JOURNEY  # the value of the profile's "journey_p3" key
KIT_ID = "qa-project3-critical-32"
KIT_SHA256 = kit.SPEC["specs-rows.json"]  # a profile bound to another rows version is REFUSED
KIT_NOT_CHECKED = ["QA's own list: specs-rows.json gaps G1-G9 and pending_runtime"]
NOT_CHECKED_HERE = [
    "CR-1, API-D-1 and API-D-5: QA's api_check, not this browser check",
    "HOST-L and the host's own records (commands, DATA_DIR, the Stopped line): Ops' receipts, read only through "
    "#126's ops_host_client once QA's P5 receiving names that wire",
    "QA #31's larger name/space/API/restart corpus, all-state Add/IME/style matrices and D-6's newer-failure and "
    "automatic-reload guard recipes: separate scope, not covered here",
    "wording rows 15-17 (VERIFIED-PRESENT): QA's source check of FINAL, not measured here",
    "DNS-only lookups (dns-prefetch, preconnect): no HTTP-level gate sees them; Security's file read covers them",
    "Playwright WebKit on Linux is not a real iPhone or iOS Safari",
]
HOST_WAIT = ("host wire not opened for this run (host rows go only through #126's request side and P5's judge): "
             "no host request was written")
W1_MISSING = ("W1: no engine-image reading: the W-IMG engine-image operation (Ops) is not wired here yet, so the "
              "WebKit rows are NOT RUN and no WebKit MCP call is made")
PROFILE_KEYS = ("journey_p3", "origin", "origin_webkit", "pins", "build", "kit_id", "kit_sha256", "kit_not_checked",
                "engine_image", "webkit_tree_sha256", "host_binding")
OPTIONAL_KEYS = ("w2_recreation",)  # Ops' W2 recreation receipts for W1 admission (#125 4b), only when needed
IMAGE_RE = re.compile(r"sha256:[0-9a-f]{64}")

# Security G1/G3 (rm-4774fae1): one control plant per request kind, literal *.invalid URLs in the served files. In
# a control run only that plant's exact URLs are expected; anything else off the origin is W4. Builds get no list.
GATE_PLANTS = {
    "plant_worker": {"kind": "dedicated worker", "urls": ["https://worker.invalid/w"]},
    "plant_websocket": {"kind": "WebSocket", "urls": ["wss://websocket.invalid/s"]},
    "plant_eventsource": {"kind": "EventSource", "urls": ["https://eventsource.invalid/e"]},
    "plant_beacon": {"kind": "beacon", "urls": ["https://beacon.invalid/b"]},
    "plant_redirect": {"kind": "redirect to another origin", "urls": ["https://redirect.invalid/r"]},
    "plant_prefetch": {"kind": "prefetch", "urls": ["https://prefetch.invalid/p"]},
}
REDIRECT_ROUTE = "/plant-redirect"  # the fixture server's one fixed route, served only in the plant_redirect copy
REDIRECT_LOCATION = "https://redirect.invalid/r"
# Security #105 G5-Q: plant kinds Security has named a blind spot, as {kind: the Security record that names it}. None
# is named (DECISION-10 section 3). DNS-only lookups are a stated residual, not a plant kind.
G5_BLIND_SPOTS: dict[str, str] = {}

# ---------------------------------------------------------------- engines and contexts

CHROMIUM_OPTS = dict(fs.CONTEXT_OPTS, serviceWorkers="block")  # P3 only; legacy options unchanged
WEBKIT_OPTS = {"viewport": {"width": 390, "height": 844}, "deviceScaleFactor": 3, "isMobile": True,
               "hasTouch": True, "locale": fac.LOCALE, "timezoneId": fac.TIMEZONE, "serviceWorkers": "block"}
ENGINES = {"chromium": {"opts": CHROMIUM_OPTS, "touch": False, "contexts": kit.CONTEXTS["chromium"]},
           "webkit": {"opts": WEBKIT_OPTS, "touch": True, "contexts": kit.CONTEXTS["webkit"]}}
WEBKIT_URL = "http://playwright-mcp-webkit:8931/mcp"
WEBKIT_PROBE_S = 30
ROW_IDS = {"chromium": list(kit.CHROMIUM_ORDER), "webkit": list(kit.WEBKIT_ORDER)}
EXPECTED_STEPS = [(e, i) for e in ENGINES for i in ROW_IDS[e]] + [("webkit", "PH-1")]


def context_specs(engine: str) -> dict:
    """What SETUP makes for one engine: each context's newContext options and whether it taps."""
    spec = ENGINES[engine]
    return {c: {"opts": dict(spec["opts"]), "touch": spec["touch"]} for c in spec["contexts"]}


# ---------------------------------------------------------------- the profile (unit-tested)


def default_p3_profile(origin: str = "http://100.110.162.4:8962", pins: dict | None = None,
                       origin_webkit: str = "http://100.110.162.4:8963") -> dict:
    """A shape example (and the controls' base); a live run needs the build's own origins, pins and window."""
    pins = pins or {n: "0" * 64 for n in fs.REQUIRED_PINS}
    return {"journey_p3": JOURNEY, "origin": origin, "origin_webkit": origin_webkit, "pins": dict(pins),
            "build": {"commit": "0000000", "sha256sums_sha256": "0" * 64}, "kit_id": KIT_ID,
            "kit_sha256": KIT_SHA256, "kit_not_checked": list(KIT_NOT_CHECKED), "engine_image": hc.ENGINE_PIN,
            "webkit_tree_sha256": None, "host_binding": None}


def parse_p3_profile(text: str | None) -> tuple[dict | None, list[str]]:
    """A Project 3 profile: (target, []) or (None, the problems). Strict: exact keys, nothing guessed."""
    if text is None or not text.strip():
        return None, ["a Project 3 check needs a profile (one JSON object as text)"]
    if len(text) > fac.PROFILE_MAX_CHARS:
        return None, [f"profile is longer than {fac.PROFILE_MAX_CHARS} characters"]
    try:
        p = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, [f"profile is not JSON: {exc.msg}"]
    if not isinstance(p, dict):
        return None, ["profile is not a JSON object"]
    problems = fac._keys_problems({k: v for k, v in p.items() if k not in OPTIONAL_KEYS}, PROFILE_KEYS, "profile")
    if "w2_recreation" in p:
        problems += admission.w2_problems(p["w2_recreation"])
    if "journey_p3" in p and p["journey_p3"] != JOURNEY:
        problems.append(f"journey_p3 must be {JOURNEY!r} (QA #32 rows on Product FINAL v3.1)")
    for key in ("origin", "origin_webkit"):
        if key in p:
            problems += [f"{key}: {x}" for x in fs.shared_origin_problems(p[key])]
    if "origin" in p and "origin_webkit" in p and p["origin"] == p["origin_webkit"]:
        problems.append("origin_webkit must be the WebKit copy's own origin (fresh data), not origin")
    if "pins" in p:
        problems += fs.shared_pins_problems(p["pins"])
    if "build" in p:
        problems += fs.build_problems(p["build"])
    problems += fac.kit_problems(p)
    if "kit_id" in p and p["kit_id"] != KIT_ID:
        problems.append(f"kit_id must be {KIT_ID!r}")
    if "kit_sha256" in p and p["kit_sha256"] != KIT_SHA256:
        problems.append("kit_sha256 must be the sha256 of QA's specs-rows.json these rows were wired from "
                        f"({KIT_SHA256}); another version needs its own wiring")
    if "engine_image" in p and not (isinstance(p["engine_image"], str) and IMAGE_RE.fullmatch(p["engine_image"])):
        problems.append("engine_image is not a full image ID (sha256: and 64 lowercase hex), never a prefix")
    if "webkit_tree_sha256" in p and p["webkit_tree_sha256"] is not None and not (
            isinstance(p["webkit_tree_sha256"], str) and fac.HEX64_RE.fullmatch(p["webkit_tree_sha256"])):
        problems.append("webkit_tree_sha256 is not null or 64 lowercase hex characters")
    if "host_binding" in p:
        problems += host_wire.binding_problems(p["host_binding"])
    if problems:
        return None, problems
    return {"source": "input", "journey": "p3", "profile_sha256": fac.sha256(text.encode()), "origin": p["origin"],
            "origin_webkit": p["origin_webkit"], "pins": {n: {"sha256": h} for n, h in p["pins"].items()},
            "build": dict(p["build"]), "kit_id": p["kit_id"], "kit_sha256": p["kit_sha256"],
            "kit_not_checked": list(p["kit_not_checked"]), "engine_image": p["engine_image"],
            "webkit_tree_sha256": p["webkit_tree_sha256"], "host_binding": p["host_binding"],
            **({"w2_recreation": p["w2_recreation"]} if "w2_recreation" in p else {})}, []


# ---------------------------------------------------------------- browser code (playwright-mcp)

# SETUP makes this engine's fresh contexts (observers before the first page) and loads kit.ROWS_JS. In a control
# run (__ABORT__ true) every request off the origin is aborted by context.route before it leaves; that route's
# log (log.aborted) is a second witness only: a plant counts as caught only from the gate's own event record (G2).
# Builds never get the abort. The engine facts are read on about:blank: nothing is shimmed or overridden.
SETUP = r"""async (page) => {
  const browser = page.context().browser();
  __OBSERVERS__
  const ORIGIN = __ORIGIN__; const CTXS = __CTXS__; const ABORT = __ABORT__; const T = __TEXT__;
  log.aborted = [];
  const observers_at = t(); const contexts = {};
  for (const [name, spec] of Object.entries(CTXS)) {
    const ctx = await browser.newContext({...spec.opts, serviceWorkers: 'block'});
    const u = p3.attach(ctx, name, spec.touch);  // track before any route, newPage, storageState or navigation
    if (ABORT) await ctx.route(url => (url.protocol === 'http:' || url.protocol === 'https:') && url.origin !== ORIGIN,
      route => { const q = route.request(); log.aborted.push({t: t(), ctx: name, method: q.method(), url: q.url(),
        type: q.resourceType()}); return route.abort('blockedbyclient'); });
    const p = await ctx.newPage(); u.p = p; u.attachPage(p);
    const st = await ctx.storageState();
    contexts[name] = {created_at: t(), first_url: p.url(), cookies: st.cookies.length, storage_origins: st.origins.length,
      touch: u.touch, viewport: p.viewportSize(), is_mobile: !!spec.opts.isMobile, has_touch: !!spec.opts.hasTouch,
      device_scale_factor: spec.opts.deviceScaleFactor || 1,
      user_agent: await p.evaluate(() => navigator.userAgent),
      max_touch_points: await p.evaluate(() => navigator.maxTouchPoints),
      idle_callback: await p.evaluate(() => typeof requestIdleCallback)};
  }
  __ROWS_JS__
  return {observers_at, browser_type: browser.browserType().name(), browser_version: browser.version(), contexts,
    requests_before_navigation: log.requests.length, abort_route: ABORT,
    distinct_contexts: new Set(Object.values(p3.users).map(x => x.ctx)).size};
}"""

DRAIN = guard.DRAIN
CLOSE = guard.CLOSE
PLANT_MARK = ("async (page) => page.__p3.users[__CTX__].p.evaluate(() => "
              "document.documentElement.dataset.plant || null)")

# Probes keep pin data and event observations, even on navigation/creation/close errors.
PROBE = r"""async (page) => {
  const browser = page.context().browser();
  __OBSERVERS__
  const out = {observers_at: t(), type: browser.browserType().name(), version: browser.version()};
  const blocked = []; const ORIGIN = __ORIGIN__; const kind = __KIND__; const ABORT = __ABORT__;
  log.aborted = [];
  try {
    const ctx = await browser.newContext({...__OPTS__, serviceWorkers: 'block'});
    const u = p3.attach(ctx, 'probe', false);
    if (ABORT) await ctx.route(url => (url.protocol === 'http:' || url.protocol === 'https:') && url.origin !== ORIGIN,
      route => { const q = route.request(); log.aborted.push({t: t(), ctx: 'probe', method: q.method(), url: q.url(),
        type: q.resourceType()}); return route.abort('blockedbyclient'); });
    await ctx.route(x => x.pathname.startsWith('/api/'), route => { blocked.push({method: route.request().method(),
      url: route.request().url()}); return route.abort(); });
    const p = await ctx.newPage(); u.p = p; u.attachPage(p);
    if (kind === 'engine') {
      out.user_agent = await p.evaluate(() => navigator.userAgent);
      out.idle_callback = await p.evaluate(() => typeof requestIdleCallback);
    } else {
      let r = null;
      try { r = await p.goto(ORIGIN + '/', {waitUntil: 'load', timeout: 20000}); }
      catch (e) { out.error = String(e && e.message || e); }
      if (!out.error) {
        out.final_url = p.url(); out.status = r ? r.status() : null;
        if (r) { try { out.root = {status: r.status(), content_type: r.headers()['content-type'] || null, url: r.url(),
          b64: (await r.body()).toString('base64')}; } catch (e) { out.root = {error: String(e)}; } }
        out.files = await p.evaluate(async (names) => { const res = {};
          for (const n of names) { try { const r = await fetch(new URL(n, location.origin + '/').href, {cache: 'no-store'});
            const b = new Uint8Array(await r.arrayBuffer()); let s = ''; for (let i = 0; i < b.length; i += 8192)
              s += String.fromCharCode.apply(null, b.subarray(i, i + 8192));
            res[n] = {status: r.status, content_type: r.headers.get('content-type'), b64: btoa(s), url: r.url}; }
            catch (e) { res[n] = {error: String(e)}; } } return res; }, __NAMES__);
        out.refs = await p.evaluate(() => [...document.querySelectorAll(
          'link[href],script[src],img[src],iframe[src],source[src],video[src],audio[src],embed[src],object[data]')]
          .filter(e => !(e.tagName === 'LINK' && /^(alternate|canonical|author|help|license|next|prev|search)$/i.test(e.rel)))
          .map(e => e.href || e.src || e.data).filter(Boolean));
      }
    }
  } catch (e) { out.error = String(e && e.message || e); }
  finally { out.api_blocked = blocked; out.disposal = await p3.close(); out.log = out.disposal.log;
    out.closed = out.disposal.other_contexts_left === 0
      && Object.values(out.disposal.contexts).every(x => !x.error && x.page_closed && !x.context_still_in_browser); }
  return out;
}"""


def setup_js(target: dict, engine: str, origin: str | None = None) -> str:
    code = SETUP.replace('__OBSERVERS__', guard.OBSERVERS).replace('__ROWS_JS__', kit.ROWS_JS)
    # TEXT last: data must not be searched for placeholders
    return fs._js(code, ORIGIN=origin or target["origin"], CTXS=context_specs(engine),
                  ABORT=bool(target.get("abort_off_origin")), TEXT=kit.TEXT)


def probe_js(target: dict, kind: str, engine: str = "chromium", origin: str | None = None) -> str:
    if kind not in ("pins", "engine"):
        raise ValueError("unknown P3 probe kind: " + kind)
    return fs._js(PROBE.replace('__OBSERVERS__', guard.OBSERVERS), ORIGIN=origin or target["origin"], KIND=kind,
                  ABORT=bool(target.get("abort_off_origin")), OPTS=ENGINES[engine]["opts"],
                  NAMES=list(target["pins"]))


def row_js(row: dict, acts: list | None = None) -> str:
    # ACTS last: typed test strings must not be searched for placeholders
    return fs._js(kit.ROW_JS, OBSERVE=row.get("observe") or [row["ctx"]], CTX=row["ctx"],
                  ACTS=row.get("acts", []) if acts is None else acts)


CTYPES = {"index.html": "text/html; charset=utf-8", "style.css": "text/css; charset=utf-8",
          "app.js": "text/javascript; charset=utf-8", "favicon.svg": "image/svg+xml"}


# ---------------------------------------------------------------- the check


SETTLE_RULE = ("after each action: no request in flight in the acting context, document complete, nothing "
               "aria-busy=true and no visible aria-disabled=true button, three quiet 100 ms polls in a row (15 s at "
               "most); then 300 ms before reading the page")


def _sha(path) -> str:
    return fac.sha256(pathlib.Path(path).read_bytes())


def module_pins() -> dict:
    return {"checker_sha256": _sha(fac.__file__), "shared_module_sha256": _sha(fs.__file__),
            "p3_module_sha256": _sha(__file__), "p3_guard_sha256": _sha(guard.__file__),
            "p3_rows_sha256": _sha(kit.__file__), "p3_admission_sha256": _sha(admission.__file__),
            "ops_host_client_sha256": _sha(hc.__file__)}


def new_receipt(label: str, target: dict | None) -> dict:
    t = target or {}
    r: dict = {"label": label, "journey": "p3", "rows_from": {"spec": dict(kit.SPEC), "final": kit.FINAL,
                                                              "final_sha256": kit.FINAL_SHA256, "journey": JOURNEY},
               "kit_id": t.get("kit_id"), "kit_sha256": t.get("kit_sha256"), "origin": t.get("origin"),
               "origin_webkit": t.get("origin_webkit"), **module_pins(), "started_at": fac.now(),
               "engines": {e: {"contexts": list(s["contexts"]), "options": s["opts"], "presses": "tap" if s["touch"]
                               else "click", "order": ROW_IDS[e]} for e, s in ENGINES.items()},
               "settle": SETTLE_RULE, "steps": [], "steps_attempted": 0, "browser_contact": False,
               "sessions": {}, "log": {}, "kit_not_checked": t.get("kit_not_checked"),
               "not_checked_here": list(NOT_CHECKED_HERE)}
    if target:
        r["profile"] = {"source": t["source"], "sha256": t["profile_sha256"], "engine_image": t["engine_image"],
                        "webkit_tree_sha256": t["webkit_tree_sha256"], "host_binding": t["host_binding"]}
        if t.get("w2_recreation") is not None:
            r["profile"]["w2_recreation"] = t["w2_recreation"]
        r["build"] = dict(t["build"], server_bytes="attested by the host's record, not checked: a browser cannot see "
                          "the server's code")
        for key in ("control_note", "gate_plant"):
            if t.get(key):
                r["profile"][key] = t[key]
        if t.get("abort_off_origin"):
            r["abort_off_origin"] = "control run: every off-origin request aborted by context.route (second witness)"
        plant = GATE_PLANTS.get(t.get("gate_plant") or "")
        if plant:
            r["gate_allowed"] = list(plant["urls"])
    return r


def refuse_profile(text: str, problems: list[str], out: pathlib.Path, label: str, *, persist: bool = True) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    r = new_receipt(label, None)
    r["profile"] = {"source": "input", "sha256": fac.sha256(text.encode()), "problems": problems}
    fac.say(f"[{label}] profile not valid; the browser is not contacted: {'; '.join(problems)}")
    return finish(r, out, persist=persist)


async def check_profile(args, text: str | None, out: pathlib.Path, label: str, budget_s: float,
                        latch: guard.StopLatch | None = None, *, persist: bool = True) -> dict:
    target, problems = parse_p3_profile(text)
    if problems:
        r = refuse_profile(text or "", problems, out, label, persist=persist)
        if latch:
            latch.bind(r)
        return r
    bind_admission(target, args)
    return await check_target(args.browser, args.browser_webkit, target, out, label, budget_s, latch=latch,
                              persist=persist)


def bind_admission(target: dict, args) -> None:
    """The invocation's receipts root (derived in main, never a flag) and, for controls, the W2 receipts the
    --w2-recreation argument names (a live profile names them itself)."""
    root = getattr(args, "receipts_root", None)
    if root is not None:
        target["receipts_root"] = str(root)
        target["receipts_out_name"] = args.receipts_out_name
    w2 = getattr(args, "w2_recreation", None)
    if w2 is not None and "w2_recreation" not in target:
        target["w2_recreation"] = w2


@contextlib.asynccontextmanager
async def open_session(url: str):
    """P3's transport seam. Imports/connects only when explicitly invoked, never at import time."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    async with streamablehttp_client(url) as (rd, wr, _):
        async with ClientSession(rd, wr) as session:
            yield session


def log_parts(new) -> tuple[dict, list[str]]:
    """Any shape -> (event lists holding only objects, problems). Total: never raises (Security N1)."""
    if new is None:
        return {}, []
    if not isinstance(new, dict):
        return {}, ["event log is not an object: " + _brief(new)]
    clean, problems = {}, []
    for kind, events in new.items():
        if not isinstance(kind, str) or not isinstance(events, list):
            problems.append(f"event log {_brief(kind)} is not a list: " + _brief(events))
            continue
        kept = clean[kind] = []
        for event in events:
            if not isinstance(event, dict):
                problems.append(f"event log {kind} holds a non-object event: " + _brief(event))
                continue
            kept.append(event)
            if kind in WATCHED and not isinstance(event.get("url"), str):
                # Every watched event the observers record carries its URL; one without is not a clean event.
                problems.append(f"event log {kind} holds an event without a URL: " + _brief(event))
    return clean, problems


WATCHED = ("requests", "responses", "failed", "websockets", "serviceworkers", "popups")  # = guard.StopLatch.observe


def _brief(value) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=repr)
    except Exception:  # noqa: BLE001  (a reader of untrusted results must not raise)
        text = "<" + type(value).__name__ + ">"
    return text if len(text) <= 400 else text[:400] + "..."


def allowed_urls(r: dict, origin: str) -> list[str]:
    """A control plant's exact URLs (G3), plus, for the redirect plant, its one fixed same-origin route."""
    urls = list(r.get("gate_allowed") or [])
    if REDIRECT_LOCATION in urls:
        urls.append(origin.rstrip("/") + REDIRECT_ROUTE)
    return urls


def p3_findings(log: dict, origin: str, allowed=()) -> list[str]:
    """The kit's request policy (fs.traffic_findings) over every event except exact plant URLs (G3)."""
    keys = {guard.exact_key(u) for u in allowed or ()}

    def keep(events):
        return [e for e in events or [] if not (keys and guard.exact_key(e.get("url")) in keys)]
    return fs.traffic_findings(keep(log.get("requests")), keep(log.get("websockets")), origin)


def engine_of(phase: str) -> str:
    """Phases are '<engine or service>:<what>'; probes run in Chromium except the WebKit engine probe."""
    head = phase.split(":", 1)[0]
    return head if head in ENGINES else "chromium"


def collect(r: dict, new: dict, origin: str, latch: guard.StopLatch, phase: str) -> None:
    """Every event object reaches the log and the W4 latch; a malformed log blocks, it never raises."""
    clean, problems = log_parts(new)
    fac.merge_log(r.setdefault("log", {}), clean)
    fac.merge_log(r.setdefault("engine_logs", {}).setdefault(engine_of(phase), {}), clean)
    allowed = allowed_urls(r, origin)
    latch.observe(r, clean, origin, phase, allowed=[u for u in allowed if not u.startswith(origin)])
    try:
        found = p3_findings(clean, origin, allowed)
    except Exception as exc:  # noqa: BLE001  (the gate reads untrusted events)
        found = ["gate could not read the events: " + exc_text(exc)]
    if found:
        r.setdefault("phase_findings", {}).setdefault(phase, []).extend(found)
    for problem in problems:
        latch.block(phase + ": malformed event log: " + problem)
    if problems:
        r.setdefault("malformed_logs", []).append({"phase": phase, "problems": problems})
        latch.bind(r)


def read_terminal(closed, expected: set, errors: list) -> tuple[dict, dict, list[str]]:
    """The terminal CLOSE result -> (result, context states, reasons). Total (Security N1): every malformed
    field becomes an incomplete reason, never an exception, so browser_close always follows."""
    reasons: list[str] = []
    terminal = closed if isinstance(closed, dict) else {}
    if closed is not None and not isinstance(closed, dict):
        reasons.append("terminal CLOSE result is not an object")
    raw = terminal.get("contexts")
    if terminal and not isinstance(raw, dict):
        reasons.append("terminal CLOSE contexts are not an object")
    if terminal and "log" not in terminal:
        reasons.append("terminal CLOSE returned no event log")
    elif terminal:
        reasons += ["terminal event log malformed: " + x for x in log_parts(terminal.get("log"))[1]]
    got = {}
    for name, state in (raw.items() if isinstance(raw, dict) else ()):
        if isinstance(state, dict):
            got[name] = state
        else:
            got[name] = {}
            reasons.append(f"{_brief(name)}: context state is not an object")
    journal = terminal.get("journal")
    if not isinstance(journal, dict):
        reasons.append("terminal journal missing or not an object")
        journal = {}
    listed = journal.get("reasons")
    if listed is not None and not isinstance(listed, list):
        reasons.append("terminal journal reasons are not a list")
        listed = []
    for x in listed or []:
        reasons.append(x if isinstance(x, str) else "terminal journal reason is not text: " + _brief(x))
    if journal.get("status") != "complete":
        reasons.append("terminal journal not complete")
    if terminal.get("guard_page_closed") is not True:
        reasons.append("guard page closure unconfirmed")
    if terminal.get("guard_context_closed") is not True:
        reasons.append("guard context closure unconfirmed")
    left = terminal.get("other_contexts_left")
    if set(got) != expected or terminal.get("untracked") or not (type(left) is int and left == 0):
        reasons.append("untracked or unresolved contexts/pages")
    if any(x.get("page_closed") is not True or x.get("context_still_in_browser") is not False for x in got.values()):
        reasons.append("page/context still live at terminal drain")

    def entries(value, where: str) -> list:
        if value is None:
            return []
        if not isinstance(value, list):
            reasons.append(where + ": errors are not a list")
            errors.append(where + ": malformed errors " + _brief(value))
            return []
        out = []
        for e in value:
            if isinstance(e, dict) and isinstance(e.get("step"), str) and isinstance(e.get("error"), str):
                out.append(e)
            else:
                reasons.append(where + ": error entry without step/error text")
                errors.append(where + ": malformed error entry " + _brief(e))
        return out

    for name, state in got.items():
        listed_errors = entries(state.get("errors"), f"CLOSE {name}")
        single = state.get("error")
        if single is not None and not isinstance(single, str):
            reasons.append(f"{name}: error is not text")
            errors.append(f"CLOSE {name}: malformed error " + _brief(single))
        elif single and not state.get("errors"):
            errors.append(f"CLOSE {name}: " + single)
        for error in listed_errors:
            errors.append(f"CLOSE {name} {error['step']}: " + error["error"])
        if any(error["step"] != "context-close" for error in listed_errors):
            reasons.append(f"{name}: escalation raised")
    for error in entries(terminal.get("errors"), "CLOSE"):
        errors.append("CLOSE " + error["step"] + ": " + error["error"])
        reasons.append("terminal disposal raised")
    if errors and not terminal:
        reasons.append("CLOSE/disposal result unavailable")
    return terminal, got, reasons


async def settled_cleanup(s, r, engine, label, latch, origin, *, probe=False):
    """Cancellation cannot abandon an in-flight disposal. It is re-raised after disposal settles."""
    task = asyncio.create_task(cleanup(s, r, engine, label, latch, origin, probe=probe))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


async def probe_session(browser_url: str, code: str, *, r: dict, latch: guard.StopLatch, phase: str,
                        origin: str | None = None) -> dict:
    """Keep probe observations even when its final MCP close or transport exit fails."""
    got = {}
    origin = origin or r["origin"]
    if latch.stopped:
        return {"error": "invocation already stopped"}
    r.setdefault("probe_services", {})[phase] = browser_url
    try:
        async with open_session(browser_url) as s:
            try:
                await s.initialize()
                got = await _call(s, code)
                if not isinstance(got, dict):
                    got = {"error": "P3 probe did not return an object", "result_type": type(got).__name__}
                collect(r, got.get("log") or {}, origin, latch, phase)
                r.setdefault("probes", {})[phase] = {k: v for k, v in got.items() if k not in ("log", "files")}
                if got.get("error"):
                    latch.block(phase + ": probe did not complete: " + str(got["error"]))
            finally:
                await settled_cleanup(s, r, phase, r.get("label", "probe"), latch, origin, probe=True)
    except asyncio.CancelledError:
        r.setdefault("runner_error", phase + ": cancelled")
        raise
    except Exception as exc:  # transport exit must not discard the already captured result/log
        got.setdefault("error", exc_text(exc))
        latch.block(phase + ": probe/transport failed: " + exc_text(exc))
    latch.bind(r)
    return got


async def engine_probe(browser_url: str, target: dict, r: dict, latch: guard.StopLatch) -> dict:
    return await asyncio.wait_for(probe_session(browser_url, probe_js(target, "engine", "webkit"), r=r, latch=latch,
                                                phase="webkit:probe", origin=target["origin_webkit"]), WEBKIT_PROBE_S)


async def check_target(browser_url: str, webkit_url: str, target: dict, out: pathlib.Path, label: str,
                       budget_s: float, hooks: dict | None = None, latch: guard.StopLatch | None = None, *,
                       persist: bool = True, receipt: dict | None = None) -> dict:
    """Return only after final drain/disposal, never a pending True across cleanup."""
    latch = latch if latch is not None else guard.StopLatch()
    r = receipt if receipt is not None else new_receipt(label, target)
    try:
        await _check_target(browser_url, webkit_url, target, out, label, budget_s, hooks or {}, r, latch)
    except asyncio.CancelledError:
        r["runner_error"] = "journey cancelled after disposal"
        latch.block(r["runner_error"])
        latch.bind(r)
        finish(r, out, persist=persist)
        raise
    except Exception as exc:
        r.setdefault("runner_error", exc_text(exc))
        latch.block("unresolved journey/transport error: " + exc_text(exc))
    latch.bind(r)
    return finish(r, out, persist=persist)


def admitted(r: dict, latch: guard.StopLatch, target: dict, url: str, *, webkit: bool) -> bool:
    """W1 admission (#125 4b, Security #16 condition 4): before the first MCP call to a browser service, the
    newest earlier P3 receipt in the receipts root that used it must not hold mcp_service_recreation_required,
    unless the named Ops W2 recreation receipt shows a new, later container (and, for WebKit, the fresh W1
    before-reading is that container). Refusal -> BLOCKED, with no MCP call to the service."""
    seen = r.setdefault("admission", {})
    if url in seen:
        return seen[url]["status"] == "ADMITTED"
    root = target.get("receipts_root")
    if not isinstance(root, str) or not os.path.isabs(root):
        result = {"service": url, "status": "BLOCKED", "reasons": ["no absolute receipts root: earlier receipts "
                                                                "cannot be read, so the service is not admitted"]}
    else:
        w1 = (r.get("engine_image") or {}).get("before") if webkit else None
        result = admission.admit(pathlib.Path(root), url, out_name=target.get("receipts_out_name", "check"),
                                 w2=target.get("w2_recreation"), w1_before=w1, need_w1=webkit,
                                 own_marker=(r.get("started_marker") or {}).get("path"))
    seen[url] = result
    if result["status"] != "ADMITTED":
        latch.block("W1 admission refused for " + url + ": " + "; ".join(result["reasons"]))
        latch.bind(r)
        return False
    return True


MARKER_RULE = ("Security #105 A6: written before this unit's first MCP call. With no final receipt.json beside it, "
               "the unit ended without one (killed, timed out, crashed): every service named here needs Ops' W2 "
               "recreation, newer than this marker, before any further P3 use. W1 admission enforces it; the "
               "checker never deletes or rewrites this file.")


def write_started_marker(r: dict, latch: guard.StopLatch, out: pathlib.Path, browser_url: str,
                         webkit_url: str) -> bool:
    """A6: before the unit's first MCP call, a create-once 0600 fsync'd marker beside where its receipt.json will
    go, naming the services and phases about to be contacted (both engines: WebKit may follow). False (nothing
    written, or not created by this call) -> no MCP call. No signal handler or timeout: a SIGKILL leaves it too."""
    services: dict = {}
    for url, phases in ((browser_url, [f"chromium:pins-{c}-copy" for c in ("chromium", "webkit")] + ["chromium"]),
                        (webkit_url, ["webkit:probe", "webkit"])):
        services.setdefault(url, []).extend(phases)
    path = out / admission.STARTED_MARKER
    marker = {"journey": "p3", "marker": "started", "label": r.get("label"), "started_at": fac.now(),
              "services": services, "receipt": str(out / "receipt.json"), "rule": MARKER_RULE}
    try:
        guard.write_json(path, marker)
    except Exception as exc:  # noqa: BLE001 (an existing marker included: create-once, never overwritten)
        r["started_marker"] = {"path": None, "error": exc_text(exc)}
        latch.block("A6: started marker not written, so no MCP call: " + exc_text(exc))
        latch.bind(r)
        return False
    r["started_marker"] = {"path": str(path), "started_at": marker["started_at"], "services": services}
    return True


def _skip(r: dict, engine: str, ids, why: str) -> None:
    """Rows that did not run, each with the reason (never a pass)."""
    for i in ids:
        row = kit.ROW.get(i) or {"ctx": None}
        r["steps"].append({"id": i, "kind": "meta" if i == "PH-1" else ("host" if row.get("host") else "browser"),
                           "engine": engine, "ctx": row.get("ctx"), "status": "NOT RUN", "reasons": [why],
                           "traffic": [], "notes": []})


def compare_w1(before, after, expected: str) -> dict:
    """#126's compare_engine on untrusted readings: a reading it cannot read (no facts, a missing key) is BLOCKED,
    never an exception that skips the receipt."""
    try:
        return hc.compare_engine(before, after, expected=expected)
    except Exception as exc:  # noqa: BLE001
        return {"status": "BLOCKED", "reasons": ["W1 reading unreadable: " + exc_text(exc)], "expected": expected}


async def engine_reading(r: dict, hooks: dict, phase: str) -> dict | None:
    """One judged W1 engine-image reading (#126's shape), or None. Only Ops' W-IMG operation gives a real one;
    tests pass a fake through hooks."""
    reader = hooks.get("engine_image")
    reading = None
    if reader is not None:
        try:
            reading = await reader(phase)
        except Exception as exc:  # noqa: BLE001
            reading = {"operation": "engine-image", "status": "BLOCKED", "reasons": [exc_text(exc)]}
    r.setdefault("engine_image", {})[phase] = reading
    return reading


async def _check_target(browser_url, webkit_url, target, out, label, budget_s, hooks, r, latch):
    if latch.stopped:
        r["runner_error"] = "invocation stopped before target"
        return
    if not admitted(r, latch, target, browser_url, webkit=False):
        r["runner_error"] = "Chromium service not admitted (W1 admission); no MCP call made"
        return
    out.mkdir(parents=True, exist_ok=True)
    if not write_started_marker(r, latch, out, browser_url, webkit_url):
        r["runner_error"] = "A6 started marker not written; no MCP call made"
        return
    deadline = time.monotonic() + budget_s
    r["browser_contact"] = True
    pins = {}
    for copy, origin in (("chromium", target["origin"]), ("webkit", target["origin_webkit"])):
        got = await probe_session(browser_url, probe_js(target, "pins", origin=origin), r=r, latch=latch,
                                  phase=f"chromium:pins-{copy}-copy", origin=origin)
        pins[copy] = fs.pin_result(got, target["pins"], origin)
        root = got.get("root") if isinstance(got, dict) else None
        if isinstance(root, dict) and isinstance(root.get("b64"), str):
            r.setdefault("served_html", {})[copy] = fac.hashed(root).get("sha256")
            with contextlib.suppress(Exception):
                r.setdefault("_served_html", {})[copy] = __import__("base64").b64decode(root["b64"]).decode("utf-8")
        if latch.stopped or not pins[copy].get("ok"):
            break
    r["pins"] = pins.get("chromium") or {}
    r["pins_webkit"] = pins.get("webkit") or {}
    r["reach"] = {"status": None}
    for p in (r["pins"], r["pins_webkit"]):
        if p.get("error"):
            r["reach"]["error"] = p["error"]
    if latch.stopped or not r["pins"].get("ok") or not r["pins_webkit"].get("ok"):
        return
    if "fake_host" not in hooks:  # live: the run's host wire (P5 window, own pending requests settled first)
        session = host_wire.open_host(target.get("host_binding"))
        await host_wire.settle(session)
        hooks["host_session"] = session
        r["host"] = session.record
    served = r.pop("_served_html", {})
    for engine, url, origin in (("chromium", browser_url, target["origin"]),
                                ("webkit", webkit_url, target["origin_webkit"])):
        ids = ROW_IDS[engine] + (["PH-1"] if engine == "webkit" else [])
        sess = r["sessions"][engine] = {"url": url, "origin": origin, "rows": ids}
        if latch.stopped:
            sess.update(status="NOT REACHED", why="W4, disposal or a safety stop ended the invocation")
            _skip(r, engine, ids, sess["why"])
            continue
        if engine == "webkit":
            if not await _webkit_gate(r, target, hooks, latch, url, sess, ids):
                continue
        try:
            async with open_session(url) as s:
                try:
                    await s.initialize()
                    await run_section(s, r, engine, origin, target, out, label, deadline, hooks, latch,
                                      served.get(engine))
                finally:
                    await settled_cleanup(s, r, engine, label, latch, origin)
            sess["status"] = "RAN"
        except Exception as exc:
            r.setdefault("runner_error", f"{engine}: {exc_text(exc)}")
            sess["status"] = "ERROR"
            latch.block("unresolved " + engine + " session: " + exc_text(exc))
        if engine == "webkit":
            after = await engine_reading(r, hooks, "after")
            cmp = compare_w1(r["engine_image"].get("before"), after, target["engine_image"])
            r["engine_image"]["compare"] = cmp
            if cmp["status"] != "PASS":
                latch.block("W1: " + "; ".join(cmp["reasons"]))
            for st in r["steps"]:
                if st.get("engine") == "webkit":
                    st["engine_image"] = {"before": r["engine_image"].get("before"), "after": after,
                                          "compare": cmp["status"]}


async def _webkit_gate(r, target, hooks, latch, url, sess, ids) -> bool:
    """W1 before-reading, then admission, then the engine probe. False -> WebKit NOT RUN (no MCP call before the
    reading and admission pass)."""
    expected = target["engine_image"]
    if expected != hc.ENGINE_PIN:
        r["security_fyi"] = {"new_image_id": expected, "why": "W1: a new image ID is BLOCKED until Security reads it"}
        why = f"W1: profile names a new engine image {expected} (pin {hc.ENGINE_PIN}); Security reads it first"
        latch.block(why)
        sess.update(status="NOT RUN", why=why)
        _skip(r, "webkit", ids, why)
        return False
    before = await engine_reading(r, hooks, "before")
    if before is None:
        sess.update(status="NOT RUN", why=W1_MISSING)
        _skip(r, "webkit", ids, W1_MISSING)
        return False
    single = compare_w1(before, before, expected)
    if single["status"] != "PASS":
        why = "W1 before-reading: " + "; ".join(single["reasons"])
        if "new image" in why:
            r["security_fyi"] = {"new_image_id": (before.get("facts") or {}).get("image_id"), "why": why}
            latch.block(why)
        sess.update(status="NOT RUN", why=why)
        _skip(r, "webkit", ids, why)
        return False
    if not admitted(r, latch, target, url, webkit=True):
        why = "WebKit service not admitted (W1 admission); no MCP call made"
        sess.update(status="NOT RUN", why=why)
        _skip(r, "webkit", ids, why)
        return False
    try:
        probe = await engine_probe(url, target, r, latch)
    except TimeoutError as exc:
        probe = {"error": exc_text(exc)}
        latch.block("WebKit probe timed out; final state unresolved")
    sess["probe"] = {k: v for k, v in probe.items() if k not in ("log", "disposal")}
    if latch.stopped or probe.get("type") != "webkit" or probe.get("error"):
        why = "WebKit not available or invocation stopped: " + str(probe.get("error") or probe.get("type"))
        sess.update(status="NOT RUN", why=why)
        _skip(r, "webkit", ids, why)
        return False
    return True


def exc_text(exc: BaseException) -> str:
    """An error as one line, with the first error inside an exception group (the MCP client's task groups)."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return f"{exc.__class__.__name__}: {str(exc)[:400]}"


async def _call(s, code):
    return fac.mcp_result(await s.call_tool("browser_run_code_unsafe", {"code": code}))


async def run_section(s, r: dict, engine: str, origin: str, target: dict, out: pathlib.Path, label: str,
                      deadline: float, hooks: dict, latch: guard.StopLatch, served_html: str | None = None) -> bool:
    if latch.stopped:
        return False
    result = False
    try:
        result = await _section_rows(s, r, engine, origin, target, label, deadline, hooks, latch, served_html)
    finally:
        try:
            if target.get("gate_plant"):
                r.setdefault("plant_marks", {})[engine] = await _call(s, fs._js(PLANT_MARK, CTX="A"))
        except Exception as exc:  # noqa: BLE001
            r.setdefault("plant_marks", {})[engine] = "unread: " + exc_text(exc)
        try:
            new = await _call(s, DRAIN)
            collect(r, new or {}, origin, latch, engine + ":final-drain")
            late = p3_findings(new or {}, origin, allowed_urls(r, origin)) + fac.error_findings(new or {})
            if late:
                r.setdefault("late_findings", []).extend(f"{engine}: {x}" for x in late)
        except Exception as exc:
            latch.block(engine + ": final observation drain failed: " + exc_text(exc))
    latch.bind(r)
    return result and not latch.stopped


def row_traffic(row_id: str, new: dict, origin: str, allowed) -> list[str]:
    """What a row's own events show against the kit: off-policy requests, page errors, and failed /api/ requests
    outside the rows where they are expected (the server is down, or CR-3 aborts the list GET)."""
    found = p3_findings(new, origin, allowed) + fac.error_findings(new)
    if row_id not in kit.OUTAGE_ROWS + ("CR-3",):
        found += [f"/api/ request failed: {x}" for x in fs.api_failures(new, origin)]
    return found


def engine_facts(setup: dict) -> dict:
    a = (setup.get("contexts") or {}).get("A") or {}
    return {"user_agent": a.get("user_agent"), "webkit_version": setup.get("browser_version"),
            "viewport": a.get("viewport"), "isMobile": a.get("is_mobile"), "hasTouch": a.get("has_touch"),
            "maxTouchPoints": a.get("max_touch_points"), "idle_callback": a.get("idle_callback"),
            "configured": {"viewport": {"width": 390, "height": 844}, "deviceScaleFactor": 3, "isMobile": True,
                           "hasTouch": True}}


async def _section_rows(s, r, engine, origin, target, label, deadline, hooks, latch, served_html) -> bool:
    """Rows only. The enclosing section and session own drain and unconditional disposal."""
    setup = await _call(s, setup_js(target, engine, origin))
    if not isinstance(setup, dict) or not isinstance(setup.get("contexts"), dict):
        raise RuntimeError(f"{engine}: SETUP did not return its contexts")
    ctxs = setup["contexts"]
    sess = r["sessions"][engine]
    sess.update(browser_type=setup.get("browser_type"), browser_version=setup.get("browser_version"), contexts=ctxs,
                distinct_contexts=setup.get("distinct_contexts"), observers_at=setup.get("observers_at"),
                abort_route=setup.get("abort_route"), engine_facts=engine_facts(setup),
                before_first_navigation=setup.get("requests_before_navigation") == 0
                and all(c.get("first_url") == "about:blank" for c in ctxs.values()))
    fac.say(f"[{label}] {engine}: {setup.get('browser_type')} {setup.get('browser_version')}, {len(ctxs)} contexts")
    order = ROW_IDS[engine]
    if setup.get("browser_type") != engine:
        r["runner_error"] = f"{engine} session is {setup.get('browser_type')}"
        _skip(r, engine, order, r["runner_error"])
        return False
    allowed = allowed_urls(r, origin)
    for n, rid in enumerate(order):
        row = kit.ROW[rid]
        if latch.stopped:
            _skip(r, engine, order[n:], "the invocation stopped (W4, disposal or a safety stop)")
            return False
        if time.monotonic() > deadline - fs.RESERVE_S:
            _skip(r, engine, order[n:], "no time left in the check's budget")
            return False
        if row.get("host"):
            step = await host_step(s, r, row, origin, hooks, latch, engine)
        else:
            step = await browser_step(s, r, row, origin, engine, served_html, allowed, latch)
        r["steps"].append(step)
        fac.say(f"[{label}] {rid} ({row['ctx']}, {engine}) {step['status']}")
        if step["status"] not in ("PASS", "UNQUALIFIED") or step.get("traffic") or latch.stopped:
            _skip(r, engine, order[n + 1:], f"an earlier row ({rid}) did not pass")
            return False
    return True


async def browser_step(s, r, row, origin, engine, served_html, allowed, latch, acts=None) -> dict:
    res = await _call(s, row_js(row, acts))
    if not isinstance(res, dict):
        raise RuntimeError(f"{row['id']}: the browser did not return an object")
    new = res.get("log") or {}
    collect(r, new, origin, latch, engine + ":" + row["id"])
    v = kit.judge(row, res, engine, served_html)
    r["steps_attempted"] += 1
    traffic = row_traffic(row["id"], log_parts(new)[0], origin, allowed)
    return {"id": row["id"], "kind": "browser", "engine": engine, "ctx": row["ctx"], "plants": row.get("plants", []),
            "acts": res.get("acts"), "action_started": res.get("started"), "action_ended": res.get("ended"),
            "observed": res.get("obs"), "status": v["status"], "reasons": v["reasons"], "traffic": traffic,
            "notes": v.get("notes", [])}


async def host_step(s, r: dict, row: dict, origin: str, hooks: dict, latch: guard.StopLatch, engine: str) -> dict:
    """A host row, never PASS. Live: first_app_p3_host writes the request (#126) and P5 judges the receipt:
    UNQUALIFIED "P5 assessment: <verdict>, not counted", or BLOCKED without a receipt. Controls: hooks["fake_host"]
    acts on the fixture server (never a real host), UNQUALIFIED with no receipt judged. R-1i's browser half
    (reload, then the expected list) is judged as usual after either."""
    rid = row["id"]
    collect(r, await _call(s, DRAIN), origin, latch, f"{engine}:{rid}:before-host")
    step = {"id": rid, "kind": "host", "engine": engine, "ctx": row["ctx"], "host_action": row["host"],
            "signal": row.get("signal"), "plants": row.get("plants", []), "traffic": [], "notes": []}
    fake = hooks.get("fake_host")
    if fake is None:
        session = hooks.get("host_session")
        if session is None:
            step.update(status="BLOCKED", reasons=[HOST_WAIT])
            return step
        wire = await host_wire.run_row(session, rid)
        step["host"] = {k: v for k, v in wire.items() if k not in ("status", "reasons")}
        collect(r, await _call(s, DRAIN), origin, latch, f"{engine}:{rid}:host-return")
        step.update(status=wire["status"], reasons=list(wire["reasons"]))
        if wire["status"] != "UNQUALIFIED":
            return step
    else:
        did = await asyncio.to_thread(fake, row["host"])
        step["fake_host"] = did
        collect(r, await _call(s, DRAIN), origin, latch, f"{engine}:{rid}:host-return")
        if not (isinstance(did, dict) and did.get("done")):
            step.update(status="BLOCKED",
                        reasons=[f"control host could not {row['host']} the fixture server: {did!r}"[:300]])
            return step
        step.update(status="UNQUALIFIED", reasons=["control fake host acted on the fixture server; no Ops-format "
                                                   "receipt was judged"])
    if row.get("after"):
        part = await browser_step(s, r, row, origin, engine, None, allowed_urls(r, origin), latch, acts=row["after"])
        step["browser"] = part
        step["traffic"] = part["traffic"]
        if part["status"] != "PASS":
            step.update(status=part["status"], reasons=step["reasons"] + part["reasons"])
    return step


async def cleanup(s, r: dict, engine: str, label: str, latch: guard.StopLatch | None = None,
                  origin: str | None = None, *, probe: bool = False) -> None:
    """CLOSE owns the last disposal AND drain. Never address its closed carrier again.

    The unconditional MCP fallback has no observable journal channel; incomplete stays incomplete.
    """
    latch = latch if latch is not None else guard.StopLatch()
    origin = origin or r["origin"]
    c: dict = {"errors": []}
    cancelled = close_raised = False
    closed = None
    try:
        closed = await _call(s, CLOSE)  # unconditional: SETUP may have failed before returning metadata
    except (Exception, asyncio.CancelledError) as exc:
        cancelled = cancelled or isinstance(exc, asyncio.CancelledError)
        close_raised = True
        c["errors"].append("CLOSE: " + exc_text(exc))
    expected = {"probe"} if probe else set(ENGINES[engine]["contexts"])
    prefix = "terminal observation not established: "
    got: dict = {}
    terminal: dict = {}
    try:
        # Security N1: any log object reaches collect before (and whatever) the shape check says.
        if isinstance(closed, dict) and "log" in closed:
            collect(r, closed.get("log"), origin, latch, engine + ":close")
        terminal, got, reasons = read_terminal(closed, expected, c["errors"])
        if isinstance(closed, dict) and isinstance(closed.get("contexts"), dict):
            c["contexts"] = {k: v for k, v in closed.items() if k != "log"}
        elif not close_raised:
            c["close_result"] = _brief(closed)
            c["errors"].append("CLOSE: RuntimeError: terminal CLOSE did not return context/journal metadata")
    except Exception as exc:  # noqa: BLE001  (defence in depth: nothing may skip browser_close)
        reasons = ["terminal CLOSE result unreadable: " + exc_text(exc)]
        c["errors"].append("CLOSE reader: " + exc_text(exc))
    c["journal"] = {"status": "incomplete" if reasons else "complete",
                    "reasons": list(dict.fromkeys(x if x.startswith(prefix) else prefix + x for x in reasons)),
                    "boundary": "terminal CLOSE; subsequent MCP browser_close is unobserved"}
    c["browser_close"] = "unknown"
    try:
        result = await s.call_tool("browser_close", {})  # last MCP call, on every path (including cancellation)
        if getattr(result, "isError", None) is None:
            raise RuntimeError("browser_close returned no known outcome")
        if result.isError:
            c["browser_close"] = "error"
        fac.mcp_result(result)
        c["browser_close"] = "ok"
    except (Exception, asyncio.CancelledError) as exc:
        cancelled = cancelled or isinstance(exc, asyncio.CancelledError)
        reason = "browser_close " + c["browser_close"] + ": " + exc_text(exc)
        c["errors"].append(reason)
        c["journal"]["status"] = "incomplete"
        c["journal"]["reasons"].append(prefix + reason)
        service = ((r.get("probe_services") or {}).get(engine) if probe
                   else ((r.get("sessions") or {}).get(engine) or {}).get("url"))
        required = {"service": service or "unknown MCP service for " + engine, "phase": engine, "reason": reason,
                    "enforcer": "Architecture calling lead: no further P3 invocation on this service",
                    "required_receipt": "Ops reviewed W2 recreation: new container id/StartedAt; receipts to Security"}
        c["mcp_service_recreation_required"] = required
        r.setdefault("mcp_service_recreation_required", []).append(required)
    try:
        c["confirmed"] = bool(c["journal"]["status"] == "complete" and not c["errors"]
                              and c.get("browser_close") == "ok" and set(got) == expected
                              and terminal.get("guard_context_closed") is True and not terminal.get("untracked")
                              and type(terminal.get("other_contexts_left")) is int
                              and terminal.get("other_contexts_left") == 0
                              and all(not x.get("error") and x.get("page_closed") is True
                                      and x.get("context_still_in_browser") is False for x in got.values()))
    except Exception as exc:  # noqa: BLE001
        c["confirmed"] = False
        c["journal"]["status"] = "incomplete"
        c["journal"]["reasons"].append(prefix + "confirmation unreadable: " + exc_text(exc))
    r.setdefault("probe_cleanup" if probe else "cleanup", {})[engine] = c
    if c["journal"]["status"] == "incomplete":
        latch.block(engine + ": " + "; ".join(c["journal"]["reasons"]))
    elif not c["confirmed"]:
        latch.block(engine + ": disposal or terminal observations unresolved")
    latch.bind(r)
    fac.say(f"[{label}] {engine}: cleanup {'confirmed' if c['confirmed'] else 'NOT confirmed'}")
    if cancelled:
        raise asyncio.CancelledError


# ---------------------------------------------------------------- the gate, PH-1 and the verdict


def _incomplete(r: dict, engine: str) -> bool:
    for section in ("cleanup", "probe_cleanup"):
        for phase, x in (r.get(section) or {}).items():
            if engine_of(phase) == engine and (x.get("journal") or {}).get("status") == "incomplete":
                return True
    return False


def traffic_gate(r: dict) -> dict:
    """Per engine: FAIL on any finding in that engine's events (probes, rows, host drains, closes, final drains);
    PASS only when every row of the engine ran, its observers were attached before any navigation and its
    disposal journals are complete; else NOT CHECKED. W4 makes the whole gate FAIL."""
    by_engine: dict = {e: [] for e in ENGINES}
    for phase, found in (r.get("phase_findings") or {}).items():
        by_engine[engine_of(phase)].extend(f"{phase}: {x}" for x in found)
    for s in r.get("steps") or []:
        by_engine[s.get("engine", "chromium")].extend(f"{s['id']}: {x}" for x in s.get("traffic") or [])
    engines = {}
    # An incomplete disposal journal anywhere leaves the invocation's events unproven: no engine's gate is PASS.
    incomplete = any(_incomplete(r, e) for e in ENGINES)
    for e in ENGINES:
        sess = (r.get("sessions") or {}).get(e) or {}
        observed = [s["id"] for s in r.get("steps") or [] if s.get("engine") == e and s["status"] != "NOT RUN"
                    and s["id"] != "PH-1"]
        if by_engine[e]:
            engines[e] = "FAIL"
        elif (not incomplete and observed == ROW_IDS[e] and sess.get("status") == "RAN"
              and sess.get("before_first_navigation")):
            engines[e] = "PASS"
        else:
            engines[e] = "NOT CHECKED"
    findings = [x for e in ENGINES for x in by_engine[e]]
    tripped = (r.get("w4") or {}).get("status") == "TRIPPED"
    if tripped:
        findings.append("W4 TRIPPED: native Security hold required")
    status = ("FAIL" if tripped or "FAIL" in engines.values()
              else "PASS" if all(v == "PASS" for v in engines.values()) else "NOT CHECKED")
    return {"status": status, "findings": findings, "engines": engines,
            "per_context": context_gates(r)}


def context_gates(r: dict) -> dict:
    """Each WebKit context's own gate result (Security: every WebKit row's receipt carries it)."""
    out = {}
    log = (r.get("engine_logs") or {}).get("webkit") or {}
    origin = r.get("origin_webkit")
    if not origin:
        return out
    allowed = allowed_urls(r, origin)
    for c in ENGINES["webkit"]["contexts"]:
        mine = {k: [e for e in v if e.get("ctx") == c] for k, v in log.items() if isinstance(v, list)}
        found = p3_findings(mine, origin, allowed)
        out[c] = {"status": "FAIL" if found else "PASS", "findings": found,
                  "requests": len(mine.get("requests") or [])}
    return out


def gate_plant_result(r: dict) -> dict | None:
    """G5 for a control plant: per engine, caught (the gate's own event record has the exact URL), MISS (the page
    sent it, or the abort route saw it, and the gate did not) or not exercised (the engine never sent it)."""
    plant = (r.get("profile") or {}).get("gate_plant")
    if plant not in GATE_PLANTS:
        return None
    spec = GATE_PLANTS[plant]
    keys = {guard.exact_key(u) for u in spec["urls"]}
    out = {"plant": plant, "kind": spec["kind"], "urls": spec["urls"], "engines": {}}
    for e in ENGINES:
        sess = (r.get("sessions") or {}).get(e) or {}
        if sess.get("status") != "RAN":
            out["engines"][e] = {"result": "NOT RUN", "why": sess.get("why")}
            continue
        caught = [c for c in r.get("gate_catches") or [] if engine_of(c["phase"]) == e
                  and guard.exact_key(c["url"]) in keys]
        witness = [a for a in ((r.get("engine_logs") or {}).get(e) or {}).get("aborted") or []
                   if guard.exact_key(a.get("url")) in keys]
        mark = (r.get("plant_marks") or {}).get(e)
        if caught:
            result = "caught"
        elif witness or mark == "sent":
            result = "MISS"
        else:
            result = "not exercised"
        out["engines"][e] = {"result": result, "gate_events": len(caught), "abort_witness": len(witness),
                             "page_mark": mark, "kinds_seen": sorted({c["kind"] for c in caught})}
    return out


def ph1_step(r: dict, target_tree) -> dict:
    """PH-1: the WebKit run's own row (kit.ph1), from the engine facts, the WebKit rows, the gate and W1."""
    sess = (r.get("sessions") or {}).get("webkit") or {}
    facts = dict(sess.get("engine_facts") or {})
    metas, widths = set(), []
    for s in r["steps"]:
        if s.get("engine") != "webkit" or not isinstance(s.get("observed"), dict):
            continue
        for o in s["observed"].values():
            if isinstance(o, dict):
                metas.add(json.dumps(o.get("viewport_meta")))
                if isinstance(o.get("scroll_width"), int):
                    widths.append(o["scroll_width"])
    facts["viewport_meta"] = json.loads(metas.pop()) if len(metas) == 1 else ("differs between rows" if metas else None)
    facts["scroll_width"] = max(widths) if widths else None
    gate = {"status": traffic_gate(r)["engines"]["webkit"]}
    image = (r.get("engine_image") or {}).get("compare")
    v = kit.ph1(facts, [s for s in r["steps"] if s.get("engine") == "webkit"], gate, image, target_tree)
    return {"id": "PH-1", "kind": "meta", "engine": "webkit", "ctx": None, "status": v["status"],
            "reasons": v["reasons"], "notes": v.get("notes", []), "traffic": [],
            "record": {**facts, "image_id": (image or {}).get("image_id"), "traffic_gate": gate["status"],
                       "webkit_tree_sha256": target_tree}}


def final_verdict(r: dict) -> tuple[str, str]:
    """W4 first, then refusal and unresolved disposal. NOT RUN and UNQUALIFIED are never success."""
    if (r.get("w4") or {}).get("status") == "TRIPPED":
        return "W4 TRIPPED", guard.HOLD
    problems = (r.get("profile") or {}).get("problems")
    if problems:
        return "REFUSED", "profile not valid, browser not contacted: " + "; ".join(problems)
    if (r.get("invocation_stop") or {}).get("blocked"):
        return "BLOCKED", "; ".join(r["invocation_stop"]["reasons"])
    steps = r.get("steps") or []
    if r.get("runner_error") and not steps:
        return "BLOCKED", f"runner: {r['runner_error']}"
    if (r.get("reach") or {}).get("error"):
        return "BLOCKED", f"app not reached: {r['reach']['error']}"
    for name, key in (("Chromium copy", "pins"), ("WebKit copy", "pins_webkit")):
        pins = r.get(key) or {}
        if not pins.get("ok"):
            bad = [f["file"] for f in pins.get("files") or [] if not f.get("match")]
            if pins.get("root") and not pins["root"].get("match"):
                bad.append('"/" (must be the pinned index.html)')
            bad += [f"{u} (asked for by the page, not pinned)" for u in pins.get("unpinned_refs") or []]
            return "REFUSED", f"{name}: served files do not match the pins: " + (", ".join(bad) or "origin/redirect")
    late_obs = [e for e, x in (r.get("sessions") or {}).items() if x.get("status") == "RAN"
                and not x.get("before_first_navigation")]
    if late_obs:
        return "BLOCKED", f"observers were not attached before the first navigation ({', '.join(late_obs)})"
    failed = [s for s in steps if s["status"] == "FAIL"]
    gate = r.get("traffic_gate") or traffic_gate(r)
    if failed or gate["status"] == "FAIL":
        why = [f"{failed[0]['id']} ({failed[0].get('engine')}): " + "; ".join(failed[0]["reasons"])] if failed else []
        if gate["status"] == "FAIL":
            why.append("traffic gate: " + "; ".join(gate["findings"][:20]))
        return "FAIL", " | ".join(why)
    for status in ("BLOCKED", "UNQUALIFIED", "NOT RUN"):
        hit = [s for s in steps if s["status"] == status]
        if hit:
            return "BLOCKED", (f"{len(hit)} row(s) {status} ({hit[0]['id']} {hit[0].get('engine')}): "
                               + "; ".join(hit[0]["reasons"]))
    if r.get("runner_error"):
        return "BLOCKED", f"runner stopped the journey: {r['runner_error']}"
    if [(s.get("engine"), s["id"]) for s in steps] != EXPECTED_STEPS or any(s["status"] != "PASS" for s in steps):
        return "BLOCKED", "not every row was observed"
    if r.get("late_findings"):
        return "FAIL", "after the last row: " + "; ".join(r["late_findings"])
    if ((r.get("engine_image") or {}).get("compare") or {}).get("status") != "PASS":
        return "BLOCKED", "W1 engine image not confirmed before and after the WebKit rows"
    cl = r.get("cleanup") or {}
    if set(cl) != set(ENGINES) or not all(x.get("confirmed") for x in cl.values()):
        return "BLOCKED", "cleanup not confirmed: " + json.dumps(cl)[:600]
    return "PASS", f"all {len(EXPECTED_STEPS)} rows observed as expected (Chromium, WebKit phone and PH-1)"


def finish(r: dict, out: pathlib.Path, *, persist: bool = True) -> dict:
    sess = (r.get("sessions") or {}).get("webkit") or {}
    if sess.get("status") == "RAN" and not any(s["id"] == "PH-1" for s in r["steps"]):
        r["steps"].append(ph1_step(r, (r.get("profile") or {}).get("webkit_tree_sha256")))
    r["finished_at"] = fac.now()
    done = {(s.get("engine"), s["id"]) for s in r["steps"]}
    r["not_checked"] = [f"{i} ({e})" for e, i in EXPECTED_STEPS if (e, i) not in done]
    log = r.get("log") or {}
    r["traffic"] = {
        "requests": len(log.get("requests") or []),
        "critical_errors": fac.error_findings(log),
        "api_failures": fs.api_failures(log, r["origin"]) if r.get("origin") else [],
        "console_notes": log.get("console") or [],
        "failed_requests": log.get("failed") or [],
        "aborted_by_control_route": log.get("aborted") or [],
    }
    r["traffic_gate"] = traffic_gate(r)
    plant = gate_plant_result(r)
    if plant:
        r["gate_plant_result"] = plant
    r["verdict"], r["why"] = final_verdict(r)
    r["exit_code"] = exit_status(r)
    r.pop("engine_logs", None)
    if persist:
        guard.write_json(out / "observations.json", log)  # exact events, private (0600)
        guard.write_json(out / "receipt.json", r)
        guard.write_private(out / "summary.md", summary_md(r))
    fac.say(f"[{r['label']}] VERDICT {r['verdict']}: {r['why'][:600]}")
    return r


def summary_md(r: dict) -> str:
    lines = [f"# first_app_check, Project 3 journey ({JOURNEY}): {r['label']}", "",
             f"Verdict: **{r['verdict']}**: {r['why']}", "",
             f"Rows from QA specs-rows.json {kit.SPEC['specs-rows.json']} on {kit.FINAL} {kit.FINAL_SHA256}. "
             f"Origins {r.get('origin')} (Chromium copy), {r.get('origin_webkit')} (WebKit copy). "
             f"P3 module {r['p3_module_sha256']}, rows {r['p3_rows_sha256']}. {r['started_at']} to {r['finished_at']}.",
             ""]
    p = r.get("profile") or {}
    if p.get("problems"):
        lines += [f"Profile (SHA256 {p['sha256']}) REFUSED; the browser was not contacted:", ""]
        lines += [f"- {x}" for x in p["problems"]] + [""]
    elif p.get("control_note"):
        lines += [p["control_note"] + ".", ""]
    lines += ["## Engines", ""]
    for e, sess in (r.get("sessions") or {}).items():
        lines.append(f"- {e}: {sess.get('status')}" + (f" ({sess.get('why')})" if sess.get("why") else "")
                     + (f"; {sess.get('browser_type')} {sess.get('browser_version')}" if sess.get("browser_type") else "")
                     + f"; presses {r['engines'][e]['presses']}")
    lines += ["", "## Rows", "", "| engine | row | ctx | result | reasons and notes |", "|---|---|---|---|---|"]
    for s in r["steps"]:
        notes = "; ".join(s["reasons"] + s.get("notes", []) + [f"traffic: {x}" for x in s.get("traffic") or []]) or "-"
        lines.append(f"| {s.get('engine')} | {s['id']} | {s.get('ctx') or ''} | {s['status']} | "
                     f"{notes.replace('|', '/')[:600]} |")
    for x in r["not_checked"]:
        lines.append(f"| | {x} | | NOT CHECKED | |")
    g = r["traffic_gate"]
    lines += ["", "## Traffic gate", "", f"**{g['status']}** (per engine {json.dumps(g['engines'])})", ""]
    lines += [f"- {x}" for x in g["findings"][:50]]
    if r.get("gate_plant_result"):
        lines += ["", "## Gate plant (G5)", "", "```", json.dumps(r["gate_plant_result"], indent=1), "```"]
    lines += ["", f"W1: {json.dumps((r.get('engine_image') or {}).get('compare'))}",
              f"Cleanup: {json.dumps({k: v.get('confirmed') for k, v in (r.get('cleanup') or {}).items()})}.",
              f"Service recreation required: {json.dumps(r.get('mcp_service_recreation_required') or [])}.",
              "", "## NOT CHECKED (the kit's list; not waived)", ""]
    lines += [f"- {x}" for x in r.get("kit_not_checked") or ["(no kit: the profile was refused)"]]
    lines += ["", "## Not checked by this check", ""] + [f"- {x}" for x in NOT_CHECKED_HERE] + [""]
    if r.get("runner_error"):
        lines.append(f"Runner error: {r['runner_error']}")
    return "\n".join(lines) + "\n"


def exit_status(r: dict) -> int:
    # Preserve ordinary legacy codes, including BLOCKED=3; W4 has its own unused code.
    return guard.W4_EXIT if r["verdict"] == "W4 TRIPPED" else fac.EXIT[r["verdict"]]


async def live(args, out: pathlib.Path) -> int:
    if (out / "receipt.json").exists():
        raise SystemExit(f"{out}/receipt.json exists: one live run per folder (no retry-until-green)")
    r = await check_profile(args, args.profile, out, "live", fs.LIVE_BUDGET_S)
    print(json.dumps({"mode": "live", "journey": "p3", "verdict": r["verdict"], "why": r["why"],
                      "rows": {f"{s.get('engine')}:{s['id']}": s["status"] for s in r["steps"]},
                      "webkit": (r.get("sessions") or {}).get("webkit", {}).get("status"),
                      "traffic_gate": r["traffic_gate"]["status"], "browser_contact": r["browser_contact"],
                      "receipt": str(out / "receipt.json")}, ensure_ascii=False), flush=True)
    return exit_status(r)


# ---------------------------------------------------------------- controls: the synthetic Project 3 server


class P3Handler(fs.Handler):
    """Project 2's synthetic handler, answering in UTF-8 JSON (ensure_ascii=False, as the FINAL asks). It serves an
    allowlist of exact paths (no listing, no symlinks, nothing else), plus, only in the redirect plant's copy, one
    fixed route with a fixed Location."""

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):  # noqa: N802
        if self.path in fs.STATIC:  # literal route map; queries/escapes are not normalized into fixture paths
            name, ctype = fs.STATIC[self.path]
            if name not in self.server.files:
                return self._json(404, {"error": "not found"})
            return self._send(200, self.server.files[name], ctype)
        if self.path == REDIRECT_ROUTE and self.server.variant == "plant_redirect":
            self.send_response(302)
            self.send_header("Location", REDIRECT_LOCATION)
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return None
        if self.path == "/api/items":
            return self._json(200, {"items": self.server.store.items()})
        return self._json(404, {"error": "not found"})


class P3Server(fs.SyntheticServer):
    """The controls' Project 3 server: Project 2's synthetic server with UTF-8 JSON, the served bytes captured once,
    and the fake host's actions: restart, crash (closed at once, as a real SIGKILL would) and start."""

    def __init__(self, site: pathlib.Path, data_dir: pathlib.Path, variant: str = "clean", *,
                 bind_address: str = "0.0.0.0"):
        if bind_address not in ("0.0.0.0", "127.0.0.1"):
            raise ValueError("P3 fixture listener must be literal 0.0.0.0 or 127.0.0.1")
        super().__init__(site, data_dir, variant)
        self.bind_address = bind_address
        self.files = guard.snapshot(site, CTYPES)
        self._lifetime = threading.RLock()
        self._retired = threading.Event()

    def start(self) -> None:
        with self._lifetime:
            if self._retired.is_set():
                raise RuntimeError("P3 server retired: late start refused")
            if self.srv is not None:
                raise RuntimeError("P3 server already started")
            store = fs.Store(self.data_dir / "items.json")
            srv = http.server.ThreadingHTTPServer((self.bind_address, self.port), P3Handler)
            self.srv = srv  # own the resource before any later start step can fail
            try:
                srv.daemon_threads = True
                srv.files, srv.store, srv.variant, srv.hits = self.files, store, self.variant, self.hits
                self.port = srv.server_address[1]
                threading.Thread(target=srv.serve_forever, daemon=True).start()
                self.starts += 1
            except BaseException:
                srv.server_close()  # no shutdown wait: serve_forever may not have started
                self.srv = None
                raise

    def stop(self) -> None:
        with self._lifetime:
            srv = self.srv
            if srv is not None:
                try:
                    srv.shutdown()
                finally:
                    try:
                        srv.server_close()
                    finally:
                        self.srv = None

    def retire(self) -> None:
        self._retired.set()  # before waiting for a possibly in-flight host action

    def shutdown(self) -> None:
        self.retire()
        self.stop()  # same lifetime lock: any earlier action settles before terminal stop completes

    def host_action(self, kind: str) -> dict:
        with self._lifetime:
            if self._retired.is_set():
                return {"action": kind, "done": False, "note": "P3 server retired"}
            if kind not in ("restart", "crash", "start"):
                return {"action": kind, "done": False, "note": "unknown fake host action"}
            rec = super().host_action("stop" if kind == "crash" else kind)
            rec["action"] = kind
            rec["fake"] = "control fake host: the check's own fixture server, never a real app or host"
            return rec


def materialize(variant: str, root: pathlib.Path) -> pathlib.Path:
    """One control's site: fixtures/p3_app with app.js's VARIANT line set."""
    captured = guard.snapshot(FIXTURE, CTYPES)
    src = captured["app.js"].decode("utf-8")
    line = 'const VARIANT = "clean";'
    if src.count(line) != 1:
        raise SystemExit(f"fixtures/p3_app/app.js: the line {line!r} is not there exactly once")
    captured["app.js"] = src.replace(line, f"const VARIANT = {json.dumps(variant)};").encode("utf-8")
    site = root / "site"
    for name, data in captured.items():
        guard.write_private(site / name, data)
    return site


def tree_sha256(files: dict) -> str:
    """The served tree's hash: sha256 of 'sha256  name' lines, sorted by name (a control's webkit_tree_sha256)."""
    return fac.sha256("".join(f"{fac.sha256(files[n])}  {n}\n" for n in sorted(files)).encode())


CLEAN = ("PASS", None)


def _case(case, variant, chromium, webkit, **kw) -> dict:
    return {"case": case, "variant": variant, "expect": {"chromium": chromium, "webkit": webkit}, **kw}


# Controls and what each engine must get: (PASS, None) or (status, first row that is not PASS). Host rows count
# as passing when UNQUALIFIED (the fake host acted; no receipt judged). Expectations are hypotheses until the
# controls have run; a WRONG is investigated, never edited away.
CONTROLS = [
    _case("P3-CLEAN", "clean", CLEAN, CLEAN),
    _case("P3-IDLE-CALLBACK", "idle_callback", CLEAN, ("FAIL", "J-1"), native="idle_callback"),
    _case("P3-INNERHTML", "inner_html", ("FAIL", "E-5"), ("FAIL", "E-5")),
    _case("P3-UTF16-LENGTH", "utf16_length", ("FAIL", "UNI-UI"), ("FAIL", "UNI-UI")),
    _case("P3-NO-DIR-AUTO", "no_dir_auto", ("FAIL", "UNI-UI"), ("FAIL", "UNI-UI")),
    _case("P3-NO-BANNER", "no_banner", ("FAIL", "D-2"), CLEAN),
    _case("P3-NO-LIVE-BUSY", "no_live_busy", ("FAIL", "V3-BUSY"), CLEAN),
    _case("P3-LATE-PENDING", "late_pending", ("FAIL", "V3-PEND"), CLEAN),
    _case("P3-NO-HINTS", "no_hints", ("FAIL", "V3-LIMITS"), CLEAN),
    _case("P3-IMMEDIATE-DELETE", "immediate_delete", ("FAIL", "V3-DEL"), ("FAIL", "V3-DEL")),
    _case("P3-EMPTY-ON-FAILURE", "empty_on_failure", ("FAIL", "CR-3"), CLEAN),
    *[_case("P3-" + v.upper().replace("_", "-"), v, CLEAN, CLEAN, plant=True) for v in GATE_PLANTS],
    _case("P3-BAD-PROFILE", "clean", None, None, profile="old_journey", verdict="REFUSED"),
]


def engine_got(r: dict, engine: str) -> tuple:
    """(PASS, None) when every row of the engine passed (host rows UNQUALIFIED), else (status, first row)."""
    steps = [s for s in r["steps"] if s.get("engine") == engine and s["id"] != "PH-1"]
    for s in steps:
        if s["status"] not in ("PASS", "UNQUALIFIED"):
            return s["status"], s["id"]
    if [s["id"] for s in steps] != ROW_IDS[engine]:
        return "NOT RUN", None
    return CLEAN


def _g5_result(engines, engine: str):
    v = engines.get(engine) if isinstance(engines, dict) else None
    return v.get("result") if isinstance(v, dict) else None


def control_status(case: dict, r: dict) -> tuple[str, dict]:
    """OK, WRONG, NOT EXERCISED (a gate plant not sent on an engine that ran: a named coverage gap, never OK), NOT
    RUN (an engine did not run: never OK), UNCALIBRATED (the plant needs a capability the native engine has), BLOCKED
    or W4 TRIPPED. Security #105 G5-Q: a gate plant is OK only when caught on every engine that ran; a MISS is
    WRONG; a kind Security named a blind spot (G5_BLIND_SPOTS) keeps its row status and is noted."""
    got = {"verdict": r["verdict"]}
    if r["verdict"] == "W4 TRIPPED":
        return "W4 TRIPPED", got
    if case.get("verdict") == "REFUSED":
        return ("OK" if r["verdict"] == "REFUSED" and not r["browser_contact"] else "WRONG"), got
    if (r.get("invocation_stop") or {}).get("blocked"):
        return "BLOCKED", got
    gates = r["traffic_gate"]["engines"]
    states = []
    plant = GATE_PLANTS.get(case.get("variant")) if case.get("plant") else None
    blind = G5_BLIND_SPOTS.get(plant["kind"]) if plant else None
    g5 = ((r.get("gate_plant_result") or {}).get("engines") or {}) if plant else {}
    gaps = {}
    for e in ENGINES:
        sess = (r.get("sessions") or {}).get(e) or {}
        g = got[e] = list(engine_got(r, e))
        if sess.get("status") != "RAN":
            states.append("NOT RUN")
            got[e] = ["NOT RUN", sess.get("why")]
            continue
        want = list(case["expect"][e])
        if case.get("native") == "idle_callback" and e == "webkit" and \
                (sess.get("engine_facts") or {}).get("idle_callback") == "function":
            states.append("UNCALIBRATED")  # native WebKit has requestIdleCallback: the plant cannot fail here
            continue
        ok = g == want and (gates[e] == "PASS" if want[0] == "PASS" else gates[e] != "FAIL")
        states.append("OK" if ok else "WRONG")
        if plant:
            result = _g5_result(g5, e)
            got.setdefault("g5", {})[e] = result
            if blind is not None or result == "caught":
                continue
            if result == "MISS":
                states.append("WRONG")  # the page sent it (or the abort route saw it) and the gate did not
            else:
                states.append("NOT EXERCISED")
                gaps[e] = result or "no G5 result recorded"
    if blind is not None:
        got["g5_blind_spot"] = {"kind": plant["kind"], "named_by": blind}
    if gaps:
        got["gap"] = {"plant": case.get("variant"), "kind": plant["kind"], "engines": gaps,
                      "why": f"G5 coverage gap: the {plant['kind']} plant was not exercised on {', '.join(gaps)} "
                             "(no gate event, abort witness or page mark); never OK, never full qualification"}
    for status in ("WRONG", "NOT EXERCISED", "NOT RUN", "UNCALIBRATED"):
        if status in states:
            return status, got
    return "OK", got


def g5_qualification(results: list) -> tuple[bool, list[str]]:
    """G5-Q for full qualification: every plant control in CONTROLS caught on every engine that ran (at least one),
    unless Security named its kind a blind spot (G5_BLIND_SPOTS). (qualified, the gaps)."""
    by_case = {x.get("case"): x for x in results if isinstance(x, dict)}
    gaps = []
    for c in CONTROLS:
        if not c.get("plant"):
            continue
        kind = GATE_PLANTS[c["variant"]]["kind"]
        if kind in G5_BLIND_SPOTS:
            continue
        engines = ((by_case.get(c["case"]) or {}).get("gate_plant") or {}).get("engines") or {}
        ran = {e: _g5_result(engines, e) for e in ENGINES if _g5_result(engines, e) != "NOT RUN"}
        if not ran or any(x != "caught" for x in ran.values()):
            gaps.append(f"{c['case']} ({kind}): " + (", ".join(f"{e} {x}" for e, x in ran.items())
                                                     or "no engine ran it"))
    return not gaps, gaps


async def dispose_control(servers) -> list[str]:
    errors = []
    for server in servers:
        if server is not None:
            server.retire()  # disallow late threaded actions
    for server in servers:
        if server is not None:
            try:
                await asyncio.to_thread(server.shutdown)
            except Exception as exc:
                errors.append("server shutdown: " + exc_text(exc))
    return errors


async def run_control(args, case: dict, out: pathlib.Path, tmp: pathlib.Path, ip: str,
                      latch: guard.StopLatch | None = None, hooks: dict | None = None) -> dict:
    """One case: two fresh fixture servers (Chromium copy a, WebKit copy b, own data, the same captured bytes), the
    abort route on, the case's plant list, a fake host on copy a. Never a real app or host."""
    latch = latch if latch is not None else guard.StopLatch()
    case_out, label = out / case["case"], f"control {case['case']}"
    r = new_receipt(label, None)
    servers: list = [None, None]
    cancelled = False
    try:
        if latch.stopped:
            raise RuntimeError("invocation already stopped: no new case")
        base = tmp / case["case"]
        site = materialize(case["variant"], base)
        for n, copy in enumerate(("a", "b")):
            data = base / f"data-{copy}"
            data.mkdir(mode=0o700)
            servers[n] = P3Server(site, data, case["variant"], bind_address="0.0.0.0")
            servers[n].start()
        a, b = servers
        origin, origin_webkit = f"http://{ip}:{a.port}", f"http://{ip}:{b.port}"
        # Pin and serve precisely the same captured regular-file bytes, never reopen site paths.
        pins = {n: fac.sha256(data) for n, data in a.files.items()}
        profile = default_p3_profile(pins=pins)
        if case.get("profile") == "old_journey":
            profile["journey_p3"] = "p3-provisional"
            r = await check_profile(args, json.dumps(profile), case_out, label, fs.CONTROL_BUDGET_S, latch,
                                    persist=False)
        else:
            target, problems = parse_p3_profile(json.dumps(profile))
            if problems:
                raise ValueError(f"control profile refused: {problems}")
            target["control_note"] = (f"control: the profile's origins replaced, after the profile was accepted, by "
                                      f"the fixture servers' {origin} (Chromium) and {origin_webkit} (WebKit)")
            target.update(origin=origin, origin_webkit=origin_webkit, abort_off_origin=True,
                          webkit_tree_sha256=tree_sha256(a.files))
            if case.get("plant"):
                target["gate_plant"] = case["variant"]
            bind_admission(target, args)
            r = new_receipt(label, target)
            r["fixture_files"] = {n: fac.sha256(d) for n, d in a.files.items()}
            r["case_expect"] = case["expect"]
            await check_target(args.browser, args.browser_webkit, target, case_out, label, fs.CONTROL_BUDGET_S,
                               dict(hooks or {}, fake_host=a.host_action), latch=latch, persist=False, receipt=r)
    except asyncio.CancelledError:
        cancelled = True
        r["runner_error"] = "control cancelled"
        latch.block(r["runner_error"])
    except Exception as exc:
        r.setdefault("runner_error", exc_text(exc))
        latch.block("control lifetime failure: " + exc_text(exc))
    finally:
        task = asyncio.create_task(dispose_control(servers))
        try:
            errors = await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
            errors = await task
            latch.block("control cancelled during disposal")
        r["server_cleanup"] = {"confirmed": not errors, "errors": errors}
        for error in errors:
            latch.block(error)
    latch.bind(r)
    finish(r, case_out)  # receipt is final only after server disposal
    if cancelled:
        raise asyncio.CancelledError
    status, got = control_status(case, r)
    hits = [h for s in servers if s is not None for h in s.hits]
    if case.get("verdict") == "REFUSED" and (r["browser_contact"] or hits):
        status = "WRONG"
    return {"case": case["case"], "expected": case["expect"], "got": got, "status": status,
            "traffic_gate": r["traffic_gate"]["status"], "gate_engines": r["traffic_gate"].get("engines"),
            "gate_plant": r.get("gate_plant_result"), "why": r["why"], "steps_attempted": r["steps_attempted"],
            "browser_contact": r["browser_contact"], "server_requests": len(hits),
            "server_starts": [s.starts for s in servers if s is not None],
            "recreation_required": r.get("mcp_service_recreation_required") or [],
            "rows": {f"{s.get('engine')}:{s['id']}": s["status"] for s in r["steps"]},
            "receipt": str(case_out / "receipt.json")}


async def controls(args, out: pathlib.Path) -> int:
    latch = guard.StopLatch()
    only = [x.strip() for x in (args.only or "").split(",") if x.strip()]
    names = {x["case"] for x in CONTROLS}
    invalid = bool(args.only and (not only or set(only) - names))
    selected = [] if invalid else [c for c in CONTROLS if not only or c["case"] in only]
    results = []
    if selected:
        ip = fs.serve_ip(urllib.parse.urlparse(args.browser).hostname, args.serve_ip)
        with tempfile.TemporaryDirectory(prefix="first-app-p3-controls-") as tmp:
            for case in selected:
                if latch.stopped:
                    break
                results.append(await run_control(args, case, out, pathlib.Path(tmp), ip, latch))
    all_ok = bool(selected) and len(results) == len(selected) and all(x["status"] == "OK" for x in results)
    counts = {k: sum(1 for x in results if x["status"] == k)
              for k in ("OK", "WRONG", "NOT EXERCISED", "NOT RUN", "UNCALIBRATED", "BLOCKED", "W4 TRIPPED")}
    g5 = {x["case"]: (x.get("gate_plant") or {}).get("engines") for x in results if x.get("gate_plant")}
    g5_ok, g5_gaps = g5_qualification(results)
    summary = {"mode": "controls_p3", "journey": "p3", "all_ok": all_ok and not latch.stopped,
               "full_qualification": all_ok and not latch.stopped and {x["case"] for x in results} == names
               and g5_ok, "g5_gaps": g5_gaps, "g5_blind_spots": dict(G5_BLIND_SPOTS),
               "selection_error": "empty/unmatched selection" if invalid or not selected else None,
               "counts": counts, "g5": g5,
               "not_reached": [c["case"] for c in selected if c["case"] not in {x["case"] for x in results}],
               "not_run": [x["case"] for x in results if x["status"] == "NOT RUN"], "cases": results,
               "recreation_required": [y for x in results for y in x.get("recreation_required") or []],
               **module_pins()}
    latch.bind(summary)
    summary["exit_code"] = guard.W4_EXIT if latch.tripped else (0 if summary["all_ok"] else 1)
    guard.write_json(out / "controls.json", summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return summary["exit_code"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--mode", choices=("live", "controls_p3"))
    ap.add_argument("--out")
    ap.add_argument("--profile", default=None, help="live: the Project 3 build's profile, one JSON object as text")
    ap.add_argument("--print-p3-profile", action="store_true", help="print the profile's shape (placeholder values)")
    ap.add_argument("--browser", default="http://playwright-mcp:8931/mcp", help="the Chromium MCP endpoint")
    ap.add_argument("--browser-webkit", default=WEBKIT_URL, help="the WebKit MCP endpoint (phone rows)")
    ap.add_argument("--serve-ip", default="", help="controls: the address the browsers reach this process at")
    ap.add_argument("--only", default="", help="controls: run only these cases (comma-separated)")
    ap.add_argument("--w2-recreation", default=None,
                    help="controls: Ops' W2 recreation receipts for a service an earlier receipt says needs "
                         "recreation, as JSON {service URL: {path, sha256[, before]}} (live: the profile's key)")
    a = ap.parse_args()
    if a.print_p3_profile:
        print(json.dumps(default_p3_profile(), indent=1, ensure_ascii=False))
        return 0
    if not a.mode or not a.out:
        ap.error("--mode and --out are required")
    if a.mode != "live" and a.profile:
        ap.error("--profile is for --mode live; the controls bring their own profiles")
    if a.w2_recreation is not None:
        if a.mode == "live":
            ap.error("--w2-recreation is for the controls; a live profile names its W2 receipts itself")
        try:
            a.w2_recreation = json.loads(a.w2_recreation)
        except json.JSONDecodeError as exc:
            ap.error(f"--w2-recreation is not JSON: {exc.msg}")
        if admission.w2_problems(a.w2_recreation):
            ap.error("--w2-recreation: " + "; ".join(admission.w2_problems(a.w2_recreation)))
    out = pathlib.Path(os.path.abspath(a.out))  # preserve literal components; never resolve and follow a symlink
    # Earlier receipts of this workflow live beside this run: <root>/<run>/check[/<case>]/receipt.json.
    a.receipts_root, a.receipts_out_name = out.parent.parent, out.name
    with guard.directory_fd(out, create=True) as fd:
        os.fchmod(fd, 0o700)
    return asyncio.run(live(a, out) if a.mode == "live" else controls(a, out))


if __name__ == "__main__":
    sys.exit(main())
