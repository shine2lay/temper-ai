#!/usr/bin/env python3
"""first_app_check's Project 3 journey: a phone in WebKit, exact typed text, the app killed (Architecture #124).

Hypothesis H-P3-CHECK-1 (rule 20), written before this code:
- What is wrong, with evidence: first_app_check is two fixed journeys (Project 1's eight rows; Project 2's 30
  in three Chromium contexts at 1280x800). It is not a kit interpreter (rm-5df2e9bc). QA's raised bar for
  Project 3 (QA rm-bc2cedc5, proposal QA-PROPOSAL-raised-bar.md) needs browser checks it cannot do: the
  journey in WebKit at phone size with touch (PH-1), typed non-English text read back exactly after a reload
  in another context and right-to-left items rendered rtl (UNI-UI), M6 and M9 while the app is killed and
  recovery after it starts again (CR-3), two people pressing Add at once (SIM-5), and host receipts that
  must carry exit_code.
- The one change: a separate Project 3 journey module (this file), loaded only for mode=controls_p3 or a
  profile with "journey_p3". Its contexts know their engine (Chromium 1280x800 clicks; WebKit 390x844, touch,
  taps), it types with keyboard.insertText and compares textContent code point by code point, it asks the
  host for a kill as its own host action and requires exit_code, and it presses Add in two contexts in one
  tick. first_app_check.py and first_app_shared.py are imported, not changed.
- Expected result, and how it is measured: on temper-dev's own browser service, run twice, the clean
  synthetic page (fixtures/p3_app) passes every row and each planted fault is caught at its own row with
  its expected verdict; WebKit rows agree across the two runs or are NOT RUN with the reason (never PASS);
  the first_app and Project 2 test files pass unchanged.
- What proves it wrong: a plant passes, a clean row fails, or the two runs differ.

Everything Project-3-specific here is PROVISIONAL and marked PENDING-SPEC: the row ids, the rows, the
users, the expected exit codes and the profile key. #125 wires QA's exact spec once QA freezes its kit; the
mechanics (engines, typing, exact compare, outage rows, kill receipts, SIM-5) are what this file proves.
Test strings are the proposal's (sha256 PROPOSAL_SHA256); M6/M9 and the other page words come from the
profile, as in Project 2.

    first_app_p3.py --mode controls_p3 --out DIR [--browser URL] [--browser-webkit URL] [--serve-ip IP]
    first_app_p3.py --mode live --out DIR --profile JSON [--browser URL] [--browser-webkit URL]
    first_app_p3.py --print-p3-profile
"""

from __future__ import annotations

import argparse
import asyncio
import base64
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
import unicodedata
import urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
fac = sys.modules.get("first_app_check")
if fac is None:
    import first_app_check as fac  # noqa: E402
fs = fac.shared_module()
import first_app_p3_guard as guard  # noqa: E402

FIXTURE = HERE.parent / "fixtures" / "p3_app"
PROPOSAL = "/home/shinelay/qa-lab/project3-critical-journey/brief/QA-PROPOSAL-raised-bar.md"
PROPOSAL_SHA256 = "7d6ed11275b06df887f5c2fb32693f6bafba5e309a17de071c45433dae96c34e"
BRIEF = "FINAL-13ccada4.md (qa-lab/project3-critical-journey/brief)"
JOURNEY = "p3-provisional"  # PENDING-SPEC: the value of the profile's "journey_p3" key
KIT_ID = "qa-project3-critical-PENDING-SPEC"
KIT_NOT_CHECKED = ["PENDING-SPEC: QA's kit for Project 3 is not frozen; these rows are Architecture's provisional "
                   "mechanics rows, not QA's"]
NOT_CHECKED_HERE = [
    "the server's own API cases (SIM-1..4, UNI round trips, CR-1, CR-2): QA's api_check.py",
    "PH-2 at 320 px and axe target-size: scan v1.3",
    "the 70 score and every planned screen scanned: format v3",
    "the host's own records (commands, DATA_DIR, the Stopped line): Ops' receipts, attested not observed",
]

WORDING_KEYS = ("heading", "name_textbox", "name_button", "change_name", "item_textbox", "add_button",
                "delete_button", "added_by", "empty_text", "item_blank", "item_too_long", "name_blank",
                "name_too_long", "unreachable", "load_failed", "try_again", "list_name")
# From Product's FINAL-13ccada4 (S3 messages, S4 controls); PENDING-SPEC until QA's kit freezes them.
KIT_WORDING = {
    "heading": "To-do list", "name_textbox": "Your name", "name_button": "Save name", "change_name": "Change name",
    "item_textbox": "New item", "add_button": "Add", "delete_button": "Delete {item}", "added_by": "added by {name}",
    "empty_text": "No items yet. Add the first one above.", "item_blank": "Type an item first.",
    "item_too_long": "Too long: {n} characters. The limit is 200.", "name_blank": "Type your name first.",
    "name_too_long": "Too long: {n} characters. The limit is 50.",
    "unreachable": "Can't reach the server. Your change could not be confirmed. Reload before retrying.",
    "load_failed": "Can't reach the server. The list couldn't be loaded.", "try_again": "Try again",
    "list_name": "To-do items"}
PLACEHOLDERS = {"delete_button": "{item}", "added_by": "{name}", "item_too_long": "{n}", "name_too_long": "{n}"}
PROFILE_KEYS = ("journey_p3", "origin", "pins", "build", "kit_id", "kit_sha256", "kit_not_checked", "wording",
                "host_wait_minutes")

# ---------------------------------------------------------------- engines and contexts

CHROMIUM_OPTS = dict(fs.CONTEXT_OPTS, serviceWorkers="block")  # P3 only; legacy options unchanged
WEBKIT_OPTS = {"viewport": {"width": 390, "height": 844}, "deviceScaleFactor": 3, "isMobile": True,
               "hasTouch": True, "locale": fac.LOCALE, "timezoneId": fac.TIMEZONE, "serviceWorkers": "block"}
ENGINES = {"chromium": {"opts": CHROMIUM_OPTS, "touch": False, "contexts": ("A", "B")},
           "webkit": {"opts": WEBKIT_OPTS, "touch": True, "contexts": ("P", "Q")}}
CTX_ENGINE = {c: e for e, spec in ENGINES.items() for c in spec["contexts"]}
WEBKIT_URL = "http://playwright-mcp-webkit:8931/mcp"
WEBKIT_PROBE_S = 30


def context_specs(engine: str) -> dict:
    """What SETUP makes for one engine: each context's newContext options and whether it taps."""
    spec = ENGINES[engine]
    return {c: {"opts": dict(spec["opts"]), "touch": spec["touch"]} for c in spec["contexts"]}


# ---------------------------------------------------------------- test strings (QA's proposal, exact code points)

S = {
    "cyrillic": "\u041f\u0440\u0438\u0432\u0435\u0442, \u043c\u0438\u0440",
    "greek": "\u039a\u03b1\u03bb\u03b7\u03bc\u03ad\u03c1\u03b1 \u03ba\u03cc\u03c3\u03bc\u03b5",
    "chinese": "\u4f60\u597d\uff0c\u4e16\u754c",
    "japanese": "\u3053\u3093\u306b\u3061\u306f\u3001\u30ab\u30bf\u30ab\u30ca\u6f22\u5b57",
    "hindi": "\u0928\u092e\u0938\u094d\u0924\u0947 \u0926\u0941\u0928\u093f\u092f\u093e",
    "arabic": "\u0645\u0631\u062d\u0628\u0627 \u0628\u0627\u0644\u0639\u0627\u0644\u0645",
    "hebrew": "\u05e9\u05dc\u05d5\u05dd \u05e2\u05d5\u05dc\u05dd",
    "mixed": "\u05e9\u05dc\u05d5\u05dd Ana 123",
    "cafe_nfc": "caf\u00e9",
    "cafe_nfd": "cafe\u0301",
    "technologist": "\U0001F469\U0001F3FD\u200D\U0001F4BB",
    "flag_jp": "\U0001F1EF\U0001F1F5",
    # FINAL F11 (literal markup), not in the proposal's list: PENDING-SPEC
    "markup": "<b>hi</b>",
    "lt_gt_amp": "A < B > C & D",
}
L200_ZH = "\u4e2d" * 200
L201_ZH = "\u4e2d" * 201
L200_EMOJI = "a" * 196 + S["technologist"]
L201_EMOJI = "a" * 197 + S["technologist"]
NAME_50 = "\u0416" * 50
NAME_51 = "\u0416" * 51
USERS = {"A": "Ana", "B": NAME_50, "P": "Pat", "Q": "Quinn"}  # PENDING-SPEC
SIM_A, SIM_B = "SIM-5 from Ana", "SIM-5 from B"
DOWN_TEXT = "\u041f\u043e\u043a\u043e\u0440\u043c\u0438\u0442\u044c \u043a\u043e\u0442\u0430"  # typed while killed

# ---------------------------------------------------------------- the provisional rows (PENDING-SPEC)

# Exit codes a host receipt must carry, per host action (PENDING-SPEC: QA's spec gives the final values). A
# graceful stop exits 0 (QA's R-1); a killed app cannot exit 0: SIGKILL is 137 from a shell, -9 from Python.
EXIT_CODES = {"restart": (0,), "stop": (0,), "kill": (137, -9), "start": (0,)}
OUTAGE_ROWS = ("D-2", "D-3")  # failed /api/items requests are expected only here (between D-1 and D-4)
SHOTS = {"U-3": ("A", "A-after-U-3.png"), "D-3": ("B", "B-load-failed-D-3.png"), "W-4": ("Q", "Q-phone-W-4.png")}


def p3_rows(w: dict, users: dict) -> list[dict]:
    """The provisional rows in order. Browser rows: {id, ctx, action, acts, expected[, observe]}; host rows:
    {id, host, action, expected}. Rows are [text, added by, ticked]; every text is compared exactly."""
    a, b, p, q = users["A"], users["B"], users["P"], users["Q"]

    def add(text, submit="button", clear=False):
        return {"do": "add", "text": text, "submit": submit, "clear": clear}

    def rows_of(texts, by):
        return [[t, by, False] for t in texts]

    ltr = [S["cyrillic"], S["greek"], S["chinese"], S["japanese"], S["hindi"]]
    rtl = [S["arabic"], S["mixed"]]
    other = [S["cafe_nfc"], S["cafe_nfd"], S["technologist"], S["flag_jp"], S["markup"], S["lt_gt_amp"]]
    u1 = rows_of(ltr, a)
    u2 = u1 + rows_of(rtl, a)
    u3 = u2 + rows_of(other, a)
    base = u3 + rows_of([L200_ZH, L200_EMOJI], a)
    sim = base + [[SIM_A, a, False], [SIM_B, b, False]]
    d6 = base + [[DOWN_TEXT, a, False]]
    he = d6 + [[S["hebrew"], p, True]]
    too_long_201 = w["item_too_long"].replace("{n}", "201")
    return [
        {"id": "C-1", "ctx": "A", "action": "Open the origin.", "acts": [{"do": "open"}],
         "expected": {"heading": w["heading"], "name_form": True, "app": False}},
        {"id": "C-2", "ctx": "A", "action": f"Type {a}, press {w['name_button']}.", "acts": [{"do": "name", "text": a}],
         "expected": {"whoami": a, "app": True, "rows": [], "empty_text": True, "load_failed": False}},
        {"id": "U-1", "ctx": "A", "action": "Type and add five left-to-right strings (UNI-UI).",
         "acts": [add(t) for t in ltr], "expected": {"rows": u1, "item_value": "", "item_msg": ""}},
        {"id": "U-2", "ctx": "A", "action": "Add the Arabic and the mixed Hebrew strings (rtl).",
         "acts": [add(t, "enter") for t in rtl], "expected": {"rows": u2, "item_value": ""}},
        {"id": "U-3", "ctx": "A", "action": "Add cafe NFC and NFD, two emoji, literal markup and < > &.",
         "acts": [add(t) for t in other], "expected": {"rows": u3, "item_value": ""}},
        {"id": "L-1", "ctx": "A", "action": "Add 200 x U+4E2D, then 196 a + the 4-code-point emoji (200 each).",
         "acts": [add(L200_ZH), add(L200_EMOJI)], "expected": {"rows": base, "item_value": "", "item_msg": ""}},
        {"id": "L-2", "ctx": "A", "action": "Add 201 x U+4E2D; clear; add 197 a + the emoji (201 each).",
         "acts": [add(L201_ZH), add(L201_EMOJI, clear=True)],
         "expected": {"rows": base, "item_msg": too_long_201, "item_value": L201_EMOJI}},
        {"id": "N-1", "ctx": "B", "action": "Open in fresh context B; type 51 x U+0416 as the name.",
         "acts": [{"do": "open"}, {"do": "name", "text": NAME_51}],
         "expected": {"name_form": True, "app": False, "name_msg": w["name_too_long"].replace("{n}", "51")}},
        {"id": "N-2", "ctx": "B", "action": "Clear; type 50 x U+0416; save. B reads A's typed text back.",
         "acts": [{"do": "name", "text": b, "clear": True}],
         "expected": {"whoami": b, "app": True, "rows": base, "name_form": False}},
        {"id": "X-1", "ctx": "A", "action": "Reload.", "acts": [{"do": "reload"}],
         "expected": {"whoami": a, "rows": base}},
        {"id": "S-1", "ctx": "A", "action": "SIM-5: A and B type, press Add in the same tick; both reload.",
         "acts": [{"do": "sim_add", "texts": {"A": SIM_A, "B": SIM_B}}, {"do": "reload", "ctx": "A"},
                  {"do": "reload", "ctx": "B"}], "observe": ["A", "B"],
         "expected": {"rows": sim, "rows_tail_any_order": 2, "same_rows": True}},
        {"id": "S-2", "ctx": "A", "action": "Delete both SIM-5 items.",
         "acts": [{"do": "delete", "item": SIM_A}, {"do": "delete", "item": SIM_B}], "expected": {"rows": base}},
        {"id": "R-1", "host": "restart", "action": "Stop the app gracefully (SIGTERM), start it again with the same "
         "DATA_DIR.", "expected": "Receipt with exit_code 0 (a graceful stop), dated; then the pins match again."},
        {"id": "R-2", "ctx": "B", "action": "Reload.", "acts": [{"do": "reload"}], "expected": {"whoami": b, "rows": base}},
        {"id": "D-1", "host": "kill", "action": "Kill the app (SIGKILL). Do not reload A or B.",
         "expected": "Receipt with the killed app's exit_code (137 from a shell, -9 from Python), dated; then the "
                     "origin gives no answer."},
        {"id": "D-2", "ctx": "A", "action": f"Type {DOWN_TEXT}, press {w['add_button']} while the app is down.",
         "acts": [add(DOWN_TEXT)], "expected": {"banner": w["unreachable"], "item_value": DOWN_TEXT, "rows": base}},
        {"id": "D-3", "ctx": "B", "action": "Reload B with the page files served from the pinned copy; the list "
         "request goes to the killed app (through the driver, until B's next reload: Chromium's Private Network "
         "Access blocks a served-from-copy page's own fetches).", "acts": [{"do": "reload_cached"}],
         "expected": {"load_failed": True, "empty_text": False, "whoami": b, "rows": []}},
        {"id": "D-4", "host": "start", "action": "Start the app again with the same command and DATA_DIR.",
         "expected": "Receipt with exit_code 0 (the start), dated; then the pins match again."},
        {"id": "D-5", "ctx": "B", "action": f"Press {w['try_again']}.", "acts": [{"do": "try_again"}],
         "expected": {"load_failed": False, "rows": base, "banner": False}},
        {"id": "D-6", "ctx": "A", "action": f"Press {w['add_button']} (the put-back text is still in the box).",
         "acts": [{"do": "submit"}], "expected": {"rows": d6, "banner": False, "item_value": ""}},
        {"id": "W-1", "ctx": "P", "action": "Phone (WebKit 390x844, touch): open the origin.", "acts": [{"do": "open"}],
         "expected": {"heading": w["heading"], "name_form": True, "app": False, "no_hscroll": True}},
        {"id": "W-2", "ctx": "P", "action": f"Tap {w['name_textbox']}, type {p}, tap {w['name_button']}.",
         "acts": [{"do": "name", "text": p}], "expected": {"whoami": p, "rows": d6, "no_hscroll": True}},
        {"id": "W-3", "ctx": "P", "action": "Add the Hebrew string; tap its checkbox.",
         "acts": [add(S["hebrew"]), {"do": "tick", "item": S["hebrew"]}],
         "expected": {"rows": he, "item_value": "", "no_hscroll": True}},
        {"id": "W-4", "ctx": "Q", "action": f"Open in fresh WebKit context Q; name {q}: the Hebrew item read back.",
         "acts": [{"do": "open"}, {"do": "name", "text": q}], "expected": {"whoami": q, "rows": he, "no_hscroll": True}},
        {"id": "W-5", "ctx": "P", "action": "Reload.", "acts": [{"do": "reload"}],
         "expected": {"whoami": p, "rows": he, "no_hscroll": True}},
        {"id": "W-6", "ctx": "P", "action": "Untick the Hebrew item; delete it.",
         "acts": [{"do": "untick", "item": S["hebrew"]}, {"do": "delete", "item": S["hebrew"]}],
         "expected": {"rows": d6, "no_hscroll": True}},
    ]


ROW_IDS = [x["id"] for x in p3_rows(KIT_WORDING, USERS)]


def row_engine(row: dict) -> str:
    return "host" if row.get("host") else CTX_ENGINE[row["ctx"]]


# ---------------------------------------------------------------- the profile (unit-tested)


def default_p3_profile(origin: str = "http://100.110.162.4:8962", pins: dict | None = None) -> dict:
    """A shape example (and the controls' base); a live run needs the build's own origin, pins and kit."""
    pins = pins or {n: "0" * 64 for n in fs.REQUIRED_PINS}
    return {"journey_p3": JOURNEY, "origin": origin, "pins": dict(pins),
            "build": {"commit": "0000000", "sha256sums_sha256": "0" * 64}, "kit_id": KIT_ID, "kit_sha256": "0" * 64,
            "kit_not_checked": list(KIT_NOT_CHECKED), "wording": dict(KIT_WORDING), "host_wait_minutes": 30}


def wording_problems(w) -> list[str]:
    if not isinstance(w, dict):
        return ["wording is not an object"]
    out = fac._keys_problems(w, WORDING_KEYS, "wording")
    for k in WORDING_KEYS:
        if k in w and (problem := fac._text_problem(w[k], f"wording.{k}")):
            out.append(problem)
        elif k in PLACEHOLDERS and k in w and w[k].count(PLACEHOLDERS[k]) != 1:
            out.append(f"wording.{k} must hold {PLACEHOLDERS[k]} exactly once")
    return out


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
    problems = fac._keys_problems(p, PROFILE_KEYS, "profile")
    if "journey_p3" in p and p["journey_p3"] != JOURNEY:
        problems.append(f"journey_p3 must be {JOURNEY!r} (PENDING-SPEC)")
    if "origin" in p:
        problems += fs.shared_origin_problems(p["origin"])
    if "pins" in p:
        problems += fs.shared_pins_problems(p["pins"])
    if "build" in p:
        problems += fs.build_problems(p["build"])
    problems += fac.kit_problems(p)
    if "wording" in p:
        problems += wording_problems(p["wording"])
    if "host_wait_minutes" in p:
        h = p["host_wait_minutes"]
        if not (isinstance(h, int) and not isinstance(h, bool) and 1 <= h <= 60):
            problems.append("host_wait_minutes is not a whole number of minutes from 1 to 60")
    if problems:
        return None, problems
    return {"source": "input", "journey": "p3", "profile_sha256": fac.sha256(text.encode()), "origin": p["origin"],
            "pins": {n: {"sha256": h} for n, h in p["pins"].items()}, "build": dict(p["build"]),
            "kit_id": p["kit_id"], "kit_sha256": p["kit_sha256"], "kit_not_checked": list(p["kit_not_checked"]),
            "wording": {k: p["wording"][k] for k in WORDING_KEYS}, "users": dict(USERS),
            "host_wait_minutes": p["host_wait_minutes"]}, []


# ---------------------------------------------------------------- exact text, direction, rows (unit-tested)


def cp_list(s) -> str:
    """A string as its code points: 'U+0063 U+0061 ...'."""
    if not isinstance(s, str):
        return repr(s)
    return " ".join(f"U+{ord(c):04X}" for c in s) or "(empty)"


def text_diff(seen, expected: str, where: str) -> str | None:
    """None when seen is exactly expected (no normalization, no trimming); else both as U+ lists. Long strings
    show the first differing code point and a window around it; the full lists go in step text_diffs."""
    if seen == expected:
        return None
    if not isinstance(seen, str):
        return f"{where}: nothing read, expected {cp_list(expected)}"
    if len(seen) + len(expected) <= 48:
        return f"{where}: seen [{cp_list(seen)}], expected [{cp_list(expected)}]"
    i = next((k for k in range(min(len(seen), len(expected))) if seen[k] != expected[k]),
             min(len(seen), len(expected)))
    lo = max(0, i - 3)
    return (f"{where}: {len(seen)} code points seen, {len(expected)} expected; first difference at code point "
            f"{i + 1}: seen [{cp_list(seen[lo:i + 5])}], expected [{cp_list(expected[lo:i + 5])}]")


def strong_direction(s) -> str | None:
    """The direction dir=auto gives a text: from its first strong character (L -> ltr; R, AL -> rtl); None
    when it has none (digits, emoji, punctuation only), which is not checked."""
    for ch in s if isinstance(s, str) else "":
        k = unicodedata.bidirectional(ch)
        if k == "L":
            return "ltr"
        if k in ("R", "AL"):
            return "rtl"
    return None


def seen_rows(obs: dict, w: dict) -> list[list]:
    return [[x.get("text"), fs.parse_by(x.get("desc"), w["added_by"]), bool(x.get("checked"))] for x in obs["rows"]]


def rows_problems(seen: list[list], expected: list[list], tail_any_order: int = 0) -> tuple[list[str], list[str]]:
    """(reasons, full text diffs): the rows must be exactly the expected ones, in order; the last
    tail_any_order may come in either order (two adds in the same tick)."""
    reasons, full = [], []
    if tail_any_order and len(seen) == len(expected):
        k = tail_any_order
        head_s, head_e, tail_s, tail_e = seen[:-k], expected[:-k], seen[-k:], expected[-k:]
        key = lambda x: json.dumps(x, ensure_ascii=False)  # noqa: E731
        if sorted(tail_s, key=key) == sorted(tail_e, key=key):
            seen, expected = head_s, head_e
        else:
            reasons.append(f"the last {k} rows are not the {k} expected, in any order: seen "
                           f"{json.dumps(tail_s, ensure_ascii=False)[:300]}")
    if len(seen) != len(expected):
        reasons.append(f"rows: {len(seen)} seen, {len(expected)} expected")
    for i, (s, e) in enumerate(zip(seen, expected, strict=False)):
        if s == e:
            continue
        if s[0] != e[0]:
            reasons.append(text_diff(s[0], e[0], f"row {i + 1} text"))
            full.append({"row": i + 1, "seen": cp_list(s[0]), "expected": cp_list(e[0])})
        if s[1] != e[1]:
            reasons.append(text_diff(s[1], e[1], f"row {i + 1} added by"))
        if s[2] != e[2]:
            reasons.append(f"row {i + 1} ({e[0][:20]}): {'ticked' if s[2] else 'not ticked'}, expected "
                           f"{'ticked' if e[2] else 'not ticked'}")
        if len(reasons) >= 8:
            reasons.append("(more differences not listed)")
            break
    if len(seen) > len(expected):
        reasons += [f"extra row {i + 1}: {cp_list(r[0])[:200]}" for i, r in enumerate(seen[len(expected):],
                                                                                         len(expected))][:3]
    return reasons, full


def _msg_patterns(w: dict) -> list[re.Pattern]:
    out = []
    for k in ("item_blank", "item_too_long", "name_blank", "name_too_long"):
        out.append(re.compile(re.escape(w[k]).replace(re.escape("{n}"), "[0-9]+")))
    return out


def _message_problem(parts, expected: str, where: str, w: dict) -> str | None:
    """A text box's error message, read as its accessible description parts: expected among them, or (for
    "") none of them is one of the page's error messages."""
    if not isinstance(parts, list):
        return None
    if expected:
        return None if expected in parts else f"{where}: {expected!r} not shown; description parts {parts}"
    shown = [x for x in parts if any(p.fullmatch(x) for p in _msg_patterns(w))]
    return f"{where}: an error message is shown: {shown}" if shown else None


def _shown(c) -> bool:
    return isinstance(c, dict) and c.get("count") == 1 and bool(c.get("visible"))


NEEDS = {"heading": ("headings",), "name_form": ("name_textbox", "name_button"), "app": ("item_textbox",),
         "whoami": ("who",), "rows": ("rows",), "item_value": ("item_textbox",), "item_msg": ("item_msg_parts",),
         "name_msg": ("name_msg_parts",), "banner": ("banner",), "load_failed": ("m9_visible", "try_again"),
         "empty_text": ("empty_visible",), "no_hscroll": ("scroll",)}


def compare_obs(expected: dict, obs, w: dict) -> tuple[list[str], list[str], list[dict]]:
    """One context's observation against a row's expected: (reasons it fails, missing observations, full
    text diffs). Every row text with a strong character must also have the computed direction dir=auto
    gives it."""
    if not isinstance(obs, dict):
        return [], ["no observation"], []
    reasons, missing, full = [], [], []
    for key, value in expected.items():
        if key in ("rows_tail_any_order", "same_rows"):
            continue
        if any(n not in obs for n in NEEDS.get(key, ())):
            missing.append(f"no observation of {key}")
            continue
        if key == "heading" and value not in (obs.get("headings") or []):
            reasons.append(f"heading {value!r} not shown; headings {obs.get('headings')}")
        elif key == "name_form" and (_shown(obs["name_textbox"]) and _shown(obs["name_button"])) != value:
            reasons.append(f"name form {'not ' if value else ''}expected, {'shown' if not value else 'not shown'}")
        elif key == "app" and _shown(obs["item_textbox"]) != value:
            reasons.append(f"item box {w['item_textbox']!r} {'not shown' if value else 'shown before a name'}")
        elif key == "whoami":
            who = obs["who"] or {}
            if not who.get("visible"):
                reasons.append(f"who line with {w['change_name']!r} not shown")
            elif (d := text_diff(who.get("name"), value, "who-name")):
                reasons.append(d)
                full.append({"row": "who-name", "seen": cp_list(who.get("name")), "expected": cp_list(value)})
            elif strong_direction(value) and who.get("dir") != strong_direction(value):
                reasons.append(f"who-name computed direction {who.get('dir')}, expected {strong_direction(value)}")
        elif key == "rows":
            if any(not isinstance(x.get("text"), str) for x in obs["rows"]):
                missing.append("a row's text element (aria-labelledby or label) was not found")
                continue
            r2, f2 = rows_problems(seen_rows(obs, w), value, expected.get("rows_tail_any_order", 0))
            reasons += r2
            full += f2
        elif key == "item_value" and (d := text_diff((obs["item_textbox"] or {}).get("value"), value, "item box value")):
            reasons.append(d)
        elif key == "item_msg" and (d := _message_problem(obs["item_msg_parts"], value, "item message", w)):
            reasons.append(d)
        elif key == "name_msg" and (d := _message_problem(obs["name_msg_parts"], value, "name message", w)):
            reasons.append(d)
        elif key == "banner":
            got = obs["banner"] or ""
            if value is False and got:
                reasons.append(f"banner still shown: {got!r}")
            elif value and got != value:
                reasons.append(f"banner {value!r} expected, seen {got!r}")
        elif key == "load_failed":
            on = bool(obs["m9_visible"]) and _shown(obs["try_again"])
            if value and not on:
                reasons.append(f"load-failed state expected ({w['load_failed']!r} with {w['try_again']!r}); seen "
                               f"M9 {bool(obs['m9_visible'])}, Try again {obs['try_again']}")
            elif not value and (obs["m9_visible"] or _shown(obs["try_again"])):
                reasons.append("load-failed state still shown")
        elif key == "empty_text" and bool(obs["empty_visible"]) != value:
            reasons.append(f"empty-list text {'not shown' if value else 'shown'}" + ("" if value else
                                                                                      " (a false empty list)"))
        elif key == "no_hscroll":
            sc = obs["scroll"] or {}
            if not (isinstance(sc.get("scroll_width"), int) and sc["scroll_width"] <= (sc.get("inner_width") or 0)):
                reasons.append(f"horizontal scroll at phone size: scrollWidth {sc.get('scroll_width')} > innerWidth "
                               f"{sc.get('inner_width')}")
    for i, x in enumerate(obs.get("rows") or []):
        want = strong_direction(x.get("text"))
        if want and x.get("dir") != want:
            t = x.get("text")
            label = cp_list(t[:8]) + (" ..." if len(t) > 8 else "") if isinstance(t, str) else cp_list(t)
            reasons.append(f"row {i + 1} ({label}): computed direction {x.get('dir')}, "
                           f"expected {want} (dir=auto)")
    return [x for x in reasons if x], missing, full


def judge_row(row: dict, obs_by_ctx: dict, action_error: str | None, new_log: dict, origin: str, w: dict) -> dict:
    """One browser row over every context it observes: FAIL on what a page showed wrong, page errors, dialogs,
    crashes, popups, or a failed /api/items request outside the outage rows; BLOCKED when an observation is
    missing and nothing failed; the traffic findings apart."""
    reasons, missing, full = [], [], []
    for ctx in row.get("observe") or [row["ctx"]]:
        r2, m2, f2 = compare_obs(row["expected"], (obs_by_ctx or {}).get(ctx), w)
        tag = f"{ctx}: " if len(row.get("observe") or []) > 1 else ""
        reasons += [tag + x for x in r2]
        missing += [tag + x for x in m2]
        full += [dict(x, ctx=ctx) for x in f2]
    if row["expected"].get("same_rows"):
        got = [seen_rows(o, w) for o in (obs_by_ctx or {}).values() if isinstance(o, dict) and isinstance(o.get("rows"),
                                                                                                          list)]
        if len(got) >= 2 and any(g != got[0] for g in got[1:]):
            reasons.append("the contexts see different lists after both reloaded")
    if action_error:
        reasons.insert(0, f"action could not be done: {action_error}")
    reasons += fac.error_findings(new_log)
    failures = fs.api_failures(new_log, origin)
    notes = []
    if failures and row["id"] in OUTAGE_ROWS:
        notes = [f"expected while the app is down: {x}" for x in failures]
    elif failures:
        reasons += [f"failed /api/items request outside {', '.join(OUTAGE_ROWS)}: {x}" for x in failures]
    traffic = []
    for o in (obs_by_ctx or {}).values():
        if isinstance(o, dict):
            traffic += fac.reference_findings(o.get("resource_refs") or [], origin)
    traffic += fs.traffic_findings(new_log.get("requests") or [], new_log.get("websockets") or [], origin)
    status = "FAIL" if reasons else "BLOCKED" if missing else "PASS"
    return {"status": status, "reasons": reasons + missing, "traffic": sorted(set(traffic), key=traffic.index),
            "notes": notes, "text_diffs": full}


def sim_timing(new_log: dict) -> dict:
    """SIM-5's two POSTs: when each context sent its add (a note, not a pass condition)."""
    posts = [x for x in new_log.get("requests") or [] if x.get("method") == "POST"]
    sent = {x.get("ctx"): x.get("t") for x in posts}
    return {"posts": len(posts), "sent_at": sent}


# ---------------------------------------------------------------- host receipts (unit-tested)

RECEIPT_FORMAT = dict(fs.RECEIPT_FORMAT, exit_code="REQUIRED for Project 3: the exit status of the app this row "
                      "stopped or killed (0 for a graceful stop, 137 or -9 for a kill), or of the start command; "
                      "a receipt without it is BLOCKED")


def receipt_problem(rec: dict, action: str) -> str | None:
    """Project 3's receipt rules on top of first_app_shared.parse_host_receipt: done, and exit_code present
    and one of the values for this host action (PENDING-SPEC: QA's spec gives them)."""
    if not rec.get("done"):
        return f"the host could not do it: {rec.get('note') or '(no note)'}"
    if "exit_code" not in rec:
        return "the receipt has no exit_code: Project 3 requires it (QA's raised bar)"
    allowed = EXIT_CODES[action]
    if rec["exit_code"] not in allowed:
        return (f"exit_code {rec['exit_code']} for a {action}; expected {' or '.join(map(str, allowed))}"
                + (" (a killed app cannot exit 0)" if action == "kill" else ""))
    return None


def waiting_record(row: dict, origin: str, wait_s: float, receipt_file: str) -> dict:
    return {"row": row["id"], "host_action": row["host"], "action": row["action"], "expected": row["expected"],
            "exit_codes": list(EXIT_CODES[row["host"]]), "origin": origin, "since": fac.now(),
            "wait_seconds": int(wait_s), "receipt_file": receipt_file, "receipt_format": RECEIPT_FORMAT,
            "write": "write the receipt to a temporary name in this folder, then rename it to receipt_file"}


# ---------------------------------------------------------------- browser code (playwright-mcp)

SETUP = r"""async (page) => {
  const browser = page.context().browser();
  __OBSERVERS__
  const W = __WORDING__; const ORIGIN = __ORIGIN__; const CTXS = __CTXS__;
  const norm = (s) => String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
  const observers_at = t(); const contexts = {};
  for (const [name, spec] of Object.entries(CTXS)) {
    const ctx = await browser.newContext({...spec.opts, serviceWorkers: 'block'});
    const u = p3.attach(ctx, name, spec.touch);  // track before newPage, storageState or any navigation
    const p = await ctx.newPage(); u.p = p; u.attachPage(p);
    const st = await ctx.storageState();
    contexts[name] = {created_at: t(), first_url: p.url(), cookies: st.cookies.length, storage_origins: st.origins.length,
      touch: u.touch, viewport: p.viewportSize(), is_mobile: !!spec.opts.isMobile,
      device_scale_factor: spec.opts.deviceScaleFactor || 1};
  }
  const one = async (loc, what) => { const n = await loc.count(); if (n !== 1) throw new Error(what + ': ' + n + ' found');
    return loc; };
  // Touch contexts tap, the others click (PH-1).
  p3.press = async (u, loc) => { if (u.touch) await loc.tap({timeout: 5000}); else await loc.click({timeout: 5000}); };
  // Typing: focus the box, empty it when asked, then keyboard.insertText: the exact code points, no key mapping.
  p3.typeInto = async (u, loc, text, clear) => { await p3.press(u, loc); await loc.focus();
    if (clear) await loc.fill(''); await u.p.keyboard.insertText(text); };
  const box = (u, name) => one(u.p.getByRole('textbox', {name, exact: true}), 'textbox ' + name);
  const button = (u, name) => one(u.p.getByRole('button', {name, exact: true}), 'button ' + name);
  p3.uncache = async (u) => { if (u.cached) { const c = u.cached; u.cached = null; await u.p.unroute(c.match, c.handler); } };
  p3.act = async (u, a) => {
    const p = u.p;
    if (a.do === 'open') { await p3.uncache(u); await p.goto(ORIGIN + '/', {waitUntil: 'load', timeout: 20000}); return; }
    if (a.do === 'reload') { await p3.uncache(u); await p.reload({waitUntil: 'load', timeout: 20000}); return; }
    if (a.do === 'reload_cached') {
      // The page files from the copy pinned at stage A (same bytes), while the app is down. Chromium gives a
      // fulfilled document no address, so its fetches to the app's private address are blocked (Private Network
      // Access); the document's /api/ requests therefore go out through the driver (route.fetch), until this
      // context's next open or reload. A refused connection reaches the page as net::ERR_CONNECTION_REFUSED.
      await p3.uncache(u);
      const files = a.files || {}; const match = (url) => url.origin === ORIGIN;
      // (no URL global in this sandbox: the path is cut from the request's URL text)
      const pathOf = (s) => s.replace(/^[a-z]+:\/\/[^/]+/i, '').split(/[?#]/)[0] || '/';
      const handler = async (route) => {
        const req = route.request(); const path = pathOf(req.url());
        if (!path.startsWith('/api/')) {
          const f = files[path];
          if (f && req.method() === 'GET') return route.fulfill({status: 200, contentType: f.ctype, body: f.text});
          return route.continue();
        }
        let resp;
        try { resp = await route.fetch({timeout: 15000, maxRedirects: 0}); }
        catch (e) { const m = String((e && e.message) || e);
          return route.abort(/ECONNREFUSED|refused/i.test(m) ? 'connectionrefused'
            : /timed? ?out|ETIMEDOUT/i.test(m) ? 'timedout' : /ECONNRESET|reset/i.test(m) ? 'connectionreset' : 'failed'); }
        return route.fulfill({response: resp});
      };
      await p.route(match, handler); u.cached = {match, handler};
      await p.reload({waitUntil: 'load', timeout: 20000}); await p3.settle(u);
      return;
    }
    if (a.do === 'name') {
      await p3.typeInto(u, await box(u, W.name_textbox), a.text, !!a.clear);
      await p3.press(u, await button(u, W.name_button)); return;
    }
    if (a.do === 'add') {
      await p3.typeInto(u, await box(u, W.item_textbox), a.text, !!a.clear);
      if (a.submit === 'enter') await p.keyboard.press('Enter'); else await p3.press(u, await button(u, W.add_button));
      return;
    }
    if (a.do === 'submit') { await p3.press(u, await button(u, W.add_button)); return; }
    if (a.do === 'tick' || a.do === 'untick') {
      await p3.press(u, await one(p.getByRole('checkbox', {name: a.item, exact: true}), 'checkbox ' + a.item)); return;
    }
    if (a.do === 'delete') { await p3.press(u, await button(u, W.delete_button.replace('{item}', a.item))); return; }
    if (a.do === 'try_again') { await p3.press(u, await button(u, W.try_again)); return; }
    if (a.do === 'sim_add') {
      // SIM-5: type in every context first, then press every Add in the same tick (Promise.all).
      const us = Object.keys(a.texts).map(n => p3.users[n]);
      for (const v of us) await p3.typeInto(v, await box(v, W.item_textbox), a.texts[v.name], true);
      const buttons = []; for (const v of us) buttons.push(await button(v, W.add_button));
      const t0 = Date.now();
      await Promise.all(us.map((v, i) => p3.press(v, buttons[i])));
      p3.last_sim = {pressed_within_ms: Date.now() - t0, contexts: us.map(v => v.name)};
      for (const v of us) await p3.settle(v);
      return;
    }
    throw new Error('unknown action ' + a.do);
  };
  p3.settle = async (u) => {
    const t0 = Date.now(); let quiet = 0; let polls = 0;
    while (Date.now() - t0 < 15000) {
      await u.p.waitForTimeout(100); polls++;
      let busy = true;
      try { busy = await u.p.evaluate(() => document.readyState !== 'complete' || !!document.querySelector('[aria-busy="true"]')
        || [...document.querySelectorAll('button[aria-disabled="true"]')].some(b => b.offsetParent !== null)); }
      catch (e) { busy = true; }
      if (u.inflight === 0 && !busy) { quiet++; if (quiet >= 3) return {ms: Date.now() - t0, polls, timed_out: false}; }
      else quiet = 0;
    }
    return {ms: Date.now() - t0, polls, timed_out: true, inflight: u.inflight};
  };
  const domfn = (W) => {
    const norm = (s) => String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
    const vis = (e) => !!e && (e.checkVisibility ? e.checkVisibility({opacityProperty: true, visibilityProperty: true})
      : e.getClientRects().length > 0);
    const byIds = (ids) => String(ids || '').split(/\s+/).filter(Boolean).map(id => document.getElementById(id)).filter(Boolean);
    const parts = (el) => el ? byIds(el.getAttribute('aria-describedby')).filter(vis).map(e => norm(e.textContent)).filter(Boolean) : [];
    const leaf = (text) => [...document.querySelectorAll('body *')].some(e => vis(e) && e.children.length === 0
      && norm(e.textContent) === text);
    const rows = [...document.querySelectorAll('li')].filter(li => vis(li) && li.querySelector('input[type=checkbox]')).map(li => {
      const cb = li.querySelector('input[type=checkbox]'); const lab = byIds(cb.getAttribute('aria-labelledby'));
      const el = lab.length === 1 ? lab[0] : (lab.length === 0 && cb.labels && cb.labels.length === 1 ? cb.labels[0] : null);
      return {text: el ? el.textContent : null, text_from: el ? (lab.length ? 'aria-labelledby' : 'label') : 'none',
        desc: norm(byIds(cb.getAttribute('aria-describedby')).map(e => e.textContent).join(' ')), checked: cb.checked,
        dir: el ? getComputedStyle(el).direction : null, html_elements: el ? el.querySelectorAll('*').length : 0};
    });
    const change = [...document.querySelectorAll('button')].find(b => vis(b) && norm(b.textContent) === W.change_name);
    let who = {visible: false};
    if (change && change.parentElement) {   // PENDING-SPEC: the name is the bdi (or dir=auto, or bold) beside Change name
      const line = change.parentElement; const n = line.querySelector('bdi') || line.querySelector('[dir=auto]') || line.querySelector('b,strong');
      who = {visible: true, name: n ? n.textContent : null, dir: n ? getComputedStyle(n).direction : null, line: norm(line.textContent)};
    }
    const nameBox = [...document.querySelectorAll('input')].find(e => e.labels && [...e.labels].some(l => norm(l.textContent) === W.name_textbox));
    const itemBox = [...document.querySelectorAll('input')].find(e => e.labels && [...e.labels].some(l => norm(l.textContent) === W.item_textbox));
    const ban = document.getElementById('banner');
    return {rows, who, name_msg_parts: parts(nameBox), item_msg_parts: parts(itemBox),
      banner: ban && vis(ban) ? norm(ban.textContent) : '', m9_visible: leaf(W.load_failed), empty_visible: leaf(W.empty_text),
      scroll: {scroll_width: document.documentElement.scrollWidth, inner_width: window.innerWidth},
      body_text: document.body ? norm(document.body.innerText).slice(0, 2000) : '',
      resource_refs: [...document.querySelectorAll(
        'link[href],script[src],img[src],iframe[src],source[src],video[src],audio[src],embed[src],object[data]')]
        .filter(e => !(e.tagName === 'LINK' && /^(alternate|canonical|author|help|license|next|prev|search)$/i.test(e.rel)))
        .map(e => e.href || e.src || e.data).filter(Boolean)};
  };
  p3.observe = async (u) => {
    const p = u.p; await p.waitForTimeout(300);
    const ctl = async (loc) => { const n = await loc.count(); const o = {count: n, visible: false, enabled: false};
      if (n === 1) { o.visible = await loc.isVisible(); o.enabled = await loc.isEnabled(); } return o; };
    const headings = (await p.getByRole('heading').allInnerTexts()).map(norm);
    const nb = p.getByRole('textbox', {name: W.name_textbox, exact: true}); const name_textbox = await ctl(nb);
    if (name_textbox.count === 1) name_textbox.value = await nb.inputValue();
    const name_button = await ctl(p.getByRole('button', {name: W.name_button, exact: true}));
    const itl = p.getByRole('textbox', {name: W.item_textbox, exact: true}); const item_textbox = await ctl(itl);
    if (item_textbox.count === 1) item_textbox.value = await itl.inputValue();
    const add_button = await ctl(p.getByRole('button', {name: W.add_button, exact: true}));
    const try_again = await ctl(p.getByRole('button', {name: W.try_again, exact: true}));
    const dom = await p.evaluate(domfn, W);
    return Object.assign({at: t(), url: p.url(), headings, name_textbox, name_button, item_textbox, add_button, try_again}, dom);
  };
  return {observers_at, browser_type: browser.browserType().name(), browser_version: browser.version(), contexts,
    requests_before_navigation: log.requests.length, distinct_contexts: new Set(Object.values(p3.users).map(x => x.ctx)).size};
}"""

ROW = r"""async (page) => {
  const p3 = page.__p3; const acts = __ACTS__; const t = () => new Date().toISOString();
  const res = {started: t(), acts: []};
  for (const a of acts) {
    const u = p3.users[a.ctx || __CTX__]; const one = {do: a.do, ctx: u.name, started: t()};
    try { await p3.act(u, a); } catch (e) { one.error = String(e && e.message || e).split('\n')[0].slice(0, 300); }
    one.settle = await p3.settle(u); one.ended = t(); res.acts.push(one);
    if (one.error) { res.action_error = a.do + ' (' + u.name + '): ' + one.error; break; }
  }
  if (p3.last_sim) { res.sim = p3.last_sim; p3.last_sim = null; }
  res.ended = t(); res.obs = {};
  for (const c of __OBSERVE__) {
    try { res.obs[c] = await p3.observe(p3.users[c]); }
    catch (e) { res.observe_error = c + ': ' + String(e && e.message || e).split('\n')[0].slice(0, 300); }
  }
  res.log = p3.drain();
  return res;
}"""

DRAIN = guard.DRAIN
SHOT = "async (page) => (await page.__p3.users[__CTX__].p.screenshot({type: 'png'})).toString('base64')"
CLOSE = guard.CLOSE

# These probes preserve pin/refusal data AND event observations, even on navigation/creation/close errors.
PROBE = r"""async (page) => {
  const browser = page.context().browser();
  __OBSERVERS__
  const out = {observers_at: t(), type: browser.browserType().name(), version: browser.version()};
  const blocked = []; const ORIGIN = __ORIGIN__; const kind = __KIND__;
  try {
    const ctx = await browser.newContext({...__OPTS__, serviceWorkers: 'block'});
    const u = p3.attach(ctx, 'probe', false);
    await ctx.route(u => u.pathname.startsWith('/api/'), route => { blocked.push({method: route.request().method(),
      url: route.request().url()}); return route.abort(); });
    const p = await ctx.newPage(); u.p = p; u.attachPage(p);
    if (kind !== 'engine') {
      let r = null;
      try { r = await p.goto(ORIGIN + '/', {waitUntil: 'load', timeout: 20000}); }
      catch (e) { out.error = String(e && e.message || e); }
      if (kind === 'down') out.down = !!out.error && /net::ERR_/.test(out.error);
      if (!out.error) {
        out.final_url = p.url(); out.status = r ? r.status() : null;
        if (kind === 'pins') {
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
    }
  } catch (e) { out.error = String(e && e.message || e); }
  finally { out.api_blocked = blocked; out.disposal = await p3.close(); out.log = out.disposal.log;
    out.closed = out.disposal.other_contexts_left === 0
      && Object.values(out.disposal.contexts).every(x => !x.error && x.page_closed && !x.context_still_in_browser); }
  return out;
}"""


def setup_js(target: dict, engine: str) -> str:
    return fs._js(SETUP.replace('__OBSERVERS__', guard.OBSERVERS), WORDING=target["wording"],
                  ORIGIN=target["origin"], CTXS=context_specs(engine))


def probe_js(target: dict, kind: str, engine: str = "chromium") -> str:
    if kind not in ("pins", "down", "engine"):
        raise ValueError("unknown P3 probe kind: " + kind)
    return fs._js(PROBE.replace('__OBSERVERS__', guard.OBSERVERS), ORIGIN=target["origin"], KIND=kind,
                  OPTS=ENGINES[engine]["opts"], NAMES=list(target["pins"]))


def row_js(row: dict, cached: dict | None = None) -> str:
    acts = [dict(a, files=cached or {}) if a["do"] == "reload_cached" else a for a in row["acts"]]
    # ACTS last: it may carry the page's own files (D-3), whose text must not be searched for placeholders
    return fs._js(ROW, OBSERVE=row.get("observe") or [row["ctx"]], CTX=row["ctx"], ACTS=acts)


CTYPES = {"index.html": "text/html; charset=utf-8", "style.css": "text/css; charset=utf-8",
          "app.js": "text/javascript; charset=utf-8", "favicon.svg": "image/svg+xml"}


def cached_files(got: dict) -> dict:
    """The page files as fetched and pinned at stage A, for D-3's reload: path -> {text, ctype}."""
    out = {}
    root = got.get("root") or {}
    if root.get("b64"):
        out["/"] = {"text": base64.b64decode(root["b64"]).decode("utf-8"), "ctype": CTYPES["index.html"]}
    for name, f in (got.get("files") or {}).items():
        if f.get("b64") is not None and name in CTYPES:
            out["/" + name] = {"text": base64.b64decode(f["b64"]).decode("utf-8"), "ctype": CTYPES[name]}
    return out


# ---------------------------------------------------------------- the check


SETTLE_RULE = ("after each action: no request in flight in the acting context, document complete, nothing "
               "aria-busy=true and no visible aria-disabled=true button, three quiet 100 ms polls in a row (15 s at "
               "most); then 300 ms before reading the page")


def new_receipt(label: str, target: dict | None) -> dict:
    t = target or {}
    r: dict = {"label": label, "journey": "p3", "pending_spec": "rows, ids, users, exit codes and the profile key are "
               "Architecture's provisional ones (#124); QA's kit for Project 3 is not frozen",
               "kit_id": t.get("kit_id"), "kit_sha256": t.get("kit_sha256"), "origin": t.get("origin"),
               "checker_sha256": fac.sha256(pathlib.Path(fac.__file__).read_bytes()),
               "shared_module_sha256": fac.sha256(pathlib.Path(fs.__file__).read_bytes()),
               "p3_module_sha256": fac.sha256(pathlib.Path(__file__).read_bytes()),
               "p3_guard_sha256": fac.sha256(pathlib.Path(guard.__file__).read_bytes()),
               "test_strings_from": {"file": PROPOSAL, "sha256": PROPOSAL_SHA256}, "started_at": fac.now(),
               "engines": {e: {"contexts": list(s["contexts"]), "options": s["opts"], "presses": "tap" if s["touch"]
                               else "click"} for e, s in ENGINES.items()},
               "settle": SETTLE_RULE, "steps": [], "steps_attempted": 0, "browser_contact": False,
               "sessions": {}, "log": {}, "kit_not_checked": t.get("kit_not_checked"),
               "not_checked_here": list(NOT_CHECKED_HERE)}
    if target:
        r["profile"] = {"source": t["source"], "sha256": t["profile_sha256"], "wording": t["wording"],
                        "users": t["users"], "host_wait_minutes": t["host_wait_minutes"]}
        r["build"] = dict(t["build"], server_bytes="attested by the host's record, not checked: a browser cannot see "
                          "the server's code")
        for key in ("control_note", "control_hooks"):
            if t.get(key):
                r["profile"][key] = t[key]
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
    return await check_target(args.browser, args.browser_webkit, target, out, label, out / "host", budget_s,
                              latch=latch, persist=persist)


@contextlib.asynccontextmanager
async def open_session(url: str):
    """P3's transport seam. Imports/connects only when explicitly invoked, never at import time."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    async with streamablehttp_client(url) as (rd, wr, _):
        async with ClientSession(rd, wr) as session:
            yield session


def collect(r: dict, new: dict, origin: str, latch: guard.StopLatch, phase: str) -> None:
    fac.merge_log(r.setdefault("log", {}), new or {})
    latch.observe(r, new or {}, origin, phase)


async def settled_cleanup(s, r, engine, label, latch, origin, *, probe=False):
    """Cancellation cannot abandon an in-flight disposal. It is re-raised after disposal settles."""
    task = asyncio.create_task(cleanup(s, r, engine, label, latch, origin, probe=probe))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


async def probe_session(browser_url: str, code: str, *, r: dict, latch: guard.StopLatch,
                        phase: str) -> dict:
    """Keep probe observations even when its final MCP close or transport exit fails."""
    got = {}
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
                collect(r, got.get("log") or {}, r["origin"], latch, phase)
                r.setdefault("probes", {})[phase] = got
                if got.get("error") and not got.get("down"):
                    latch.block(phase + ": probe did not complete: " + got["error"])
            finally:
                await settled_cleanup(s, r, phase, r.get("label", "probe"), latch, r["origin"], probe=True)
    except asyncio.CancelledError:
        r.setdefault("runner_error", phase + ": cancelled")
        raise
    except Exception as exc:  # transport exit must not discard the already captured result/log
        got.setdefault("error", exc_text(exc))
        latch.block(phase + ": probe/transport failed: " + exc_text(exc))
    latch.bind(r)
    return got


async def engine_probe(browser_url: str, target: dict, r: dict, latch: guard.StopLatch) -> dict:
    return await asyncio.wait_for(probe_session(browser_url, probe_js(target, "engine", "webkit"),
                                                r=r, latch=latch, phase="webkit-probe"), WEBKIT_PROBE_S)


async def check_target(browser_url: str, webkit_url: str, target: dict, out: pathlib.Path, label: str,
                       host_dir: pathlib.Path, budget_s: float, hooks: dict | None = None,
                       latch: guard.StopLatch | None = None, *, persist: bool = True,
                       receipt: dict | None = None) -> dict:
    """Return only after final drain/disposal, never a pending True across cleanup."""
    latch = latch if latch is not None else guard.StopLatch()
    r = receipt if receipt is not None else new_receipt(label, target)
    try:
        await _check_target(browser_url, webkit_url, target, out, label, host_dir, budget_s, hooks or {}, r, latch)
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


async def _check_target(browser_url, webkit_url, target, out, label, host_dir, budget_s, hooks, r, latch):
    if latch.stopped:
        r["runner_error"] = "invocation stopped before target"
        return
    out.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + budget_s
    if host_dir.exists() and any(host_dir.iterdir()):
        r["runner_error"] = f"{host_dir} is not empty: a host receipt must come after the check asks for it"
        return
    host_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(host_dir, 0o777)  # existing provisional host wire; #125/#126 own compatibility
    r["host_dir"] = str(host_dir)
    r["browser_contact"] = True
    got = await probe_session(browser_url, probe_js(target, "pins"), r=r, latch=latch, phase="stage-A")
    r["pins"] = fs.pin_result(got, target["pins"], target["origin"])
    r["reach"] = {"status": got.get("status"), "final_url": got.get("final_url")}
    if r["pins"].get("error"):
        r["reach"]["error"] = r["pins"]["error"]
    if latch.stopped or not r["pins"].get("ok"):
        return
    cached = cached_files(got)
    rows = p3_rows(target["wording"], target["users"])
    r["screenshots"] = []
    ok = True
    for engine, url in (("chromium", browser_url), ("webkit", webkit_url)):
        section = [x for x in rows if row_engine(x) in ((engine, "host") if engine == "chromium" else (engine,))]
        sess = r["sessions"][engine] = {"url": url, "rows": [x["id"] for x in section]}
        if not ok or latch.stopped:
            sess.update(status="NOT REACHED", why="earlier row, W4 or disposal stopped the invocation")
            continue
        if engine == "webkit":
            try:
                probe = await engine_probe(url, target, r, latch)
            except TimeoutError as exc:
                probe = {"error": exc_text(exc)}
                latch.block("WebKit probe timed out; final state unresolved")
            sess["probe"] = probe
            if latch.stopped or probe.get("type") != "webkit" or probe.get("error"):
                why = "WebKit not available or invocation stopped: " + str(probe.get("error") or probe.get("type"))
                sess.update(status="NOT RUN", why=why)
                for x in section:
                    r["steps"].append({"id": x["id"], "kind": "browser", "engine": engine, "ctx": x["ctx"],
                                       "action": x["action"], "expected": x["expected"], "status": "NOT RUN",
                                       "reasons": [why], "traffic": [], "notes": []})
                continue
        try:
            async with open_session(url) as s:
                try:
                    await s.initialize()
                    ok = await run_section(s, r, engine, section, target, out, label, host_dir, deadline,
                                           hooks, browser_url, cached, latch)
                finally:
                    await settled_cleanup(s, r, engine, label, latch, target["origin"])
            ok = ok and not latch.stopped and r["cleanup"][engine]["confirmed"]
            sess["status"] = "RAN"
        except Exception as exc:
            r.setdefault("runner_error", f"{engine}: {exc_text(exc)}")
            sess["status"] = "ERROR"
            latch.block("unresolved " + engine + " session: " + exc_text(exc))
            ok = False


def exc_text(exc: BaseException) -> str:
    """An error as one line, with the first error inside an exception group (the MCP client's task groups)."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return f"{exc.__class__.__name__}: {str(exc)[:400]}"


async def _call(s, code):
    return fac.mcp_result(await s.call_tool("browser_run_code_unsafe", {"code": code}))


async def run_section(s, r: dict, engine: str, rows: list[dict], target: dict, out: pathlib.Path, label: str,
                      host_dir: pathlib.Path, deadline: float, hooks: dict, browser_url: str, cached: dict,
                      latch: guard.StopLatch | None = None) -> bool:
    latch = latch if latch is not None else guard.StopLatch()
    if latch.stopped:
        return False
    result = False
    try:
        result = await _section_rows(s, r, engine, rows, target, out, label, host_dir, deadline, hooks,
                                     browser_url, cached, latch)
    finally:
        try:
            new = await _call(s, DRAIN)
            collect(r, new or {}, target["origin"], latch, engine + ":final-drain")
            late_traffic = fs.traffic_findings((new or {}).get("requests") or [], (new or {}).get("websockets") or [],
                                               target["origin"])
            late = late_traffic + fac.error_findings(new or {})
            if late:
                r.setdefault("late_findings", []).extend(f"{engine}: {x}" for x in late)
            if late_traffic:
                r.setdefault("late_traffic", []).extend(f"{engine}: {x}" for x in late_traffic)
        except Exception as exc:
            latch.block(engine + ": final observation drain failed: " + exc_text(exc))
    latch.bind(r)
    return result and not latch.stopped and not r.get("late_findings")


async def _section_rows(s, r, engine, rows, target, out, label, host_dir, deadline, hooks,
                        browser_url, cached, latch) -> bool:
    """Rows only. The enclosing section and session own drain and unconditional disposal."""
    origin, w = target["origin"], target["wording"]
    setup = await _call(s, setup_js(target, engine))
    ctxs = setup["contexts"]
    sess = r["sessions"][engine]
    sess.update(browser_type=setup["browser_type"], browser_version=setup["browser_version"], contexts=ctxs,
                distinct_contexts=setup["distinct_contexts"], observers_at=setup["observers_at"],
                before_first_navigation=setup["requests_before_navigation"] == 0
                and all(c["first_url"] == "about:blank" for c in ctxs.values()))
    fac.say(f"[{label}] {engine}: {setup['browser_type']} {setup['browser_version']}, contexts {json.dumps(ctxs)}")
    if setup["browser_type"] != engine:
        r["runner_error"] = f"{engine} session is {setup['browser_type']}"
        return False
    for row in rows:
        if latch.stopped:
            return False
        if row.get("host"):
            step = await host_row(s, r, row, target, host_dir, deadline, label, browser_url, latch)
            r["steps"].append(step)
            collect(r, await _call(s, DRAIN), origin, latch, engine + ":host-return")
            if step["status"] != "PASS" or latch.stopped:
                return False
            continue
        res = await _call(s, row_js(row, cached))
        if not isinstance(res, dict):
            raise RuntimeError(f"{row['id']}: the browser did not return an object")
        obs = res.get("obs") or {}
        if hooks.get("drop_observation") == row["id"]:
            for o in obs.values():
                if isinstance(o, dict):
                    o.pop("rows", None)
        new = res.get("log") or {}
        collect(r, new, origin, latch, engine + ":" + row["id"])
        v = judge_row(row, obs, res.get("action_error"), new, origin, w)
        if res.get("observe_error"):
            v["reasons"].append(f"observation failed: {res['observe_error']}")
            v["status"] = "FAIL" if v["status"] == "FAIL" else "BLOCKED"
        notes = v["notes"] + ([f"SIM-5: {json.dumps(res['sim'])}; {json.dumps(sim_timing(new))}"]
                              if res.get("sim") else [])
        r["steps_attempted"] += 1
        r["steps"].append({"id": row["id"], "kind": "browser", "engine": engine, "ctx": row["ctx"],
                           "action": row["action"], "expected": row["expected"], "acts": res.get("acts"),
                           "action_started": res.get("started"), "action_ended": res.get("ended"),
                           "observed": obs, "status": v["status"], "reasons": v["reasons"],
                           "traffic": v["traffic"], "notes": notes, "text_diffs": v["text_diffs"]})
        fac.say(f"[{label}] {row['id']} ({row['ctx']}, {engine}) {v['status']}")
        if v["status"] != "PASS" or v["traffic"] or latch.stopped:
            return False
        if row["id"] in SHOTS:
            ctx, name = SHOTS[row["id"]]
            png = base64.b64decode(await _call(s, fs._js(SHOT, CTX=ctx)))
            guard.write_private(out / name, png)
            r["screenshots"].append({"file": name, "after": row["id"], "context": ctx, "engine": engine,
                                     "taken_at": fac.now(), "bytes": len(png), "sha256": fac.sha256(png),
                                     "viewport": ENGINES[engine]["opts"]["viewport"]})
    return True


async def host_row(s, r: dict, row: dict, target: dict, host_dir: pathlib.Path, deadline: float, label: str,
                   browser_url: str, latch: guard.StopLatch | None = None) -> dict:
    """A host step, as Project 2's (WAITING-<row>.json, then <row>.json), with Project 3's receipt rules: a kill
    is its own host action, exit_code is required and must be one of the action's values. After a restart or
    start the pins are checked again; after a stop or kill the origin must give no answer (both in Chromium,
    in a session of their own)."""
    latch = latch if latch is not None else guard.StopLatch()
    r.setdefault("origin", target["origin"])
    r.setdefault("label", label)
    # Drain the still-open journey session before asking for a host operation or a fresh probe.
    collect(r, await _call(s, DRAIN), target["origin"], latch, row["id"] + ":before-host")
    rid = row["id"]
    wait_s = min(target["host_wait_minutes"] * 60, deadline - time.monotonic() - fs.RESERVE_S)
    step = {"id": rid, "kind": "host", "host_action": row["host"], "action": row["action"], "expected": row["expected"],
            "exit_codes": list(EXIT_CODES[row["host"]]), "traffic": [], "notes": []}
    if wait_s <= 0 or latch.stopped:
        step.update(status="BLOCKED", reasons=["invocation stopped or no time left to wait for the host"])
        return step
    asked = time.time()
    f = host_dir / f"{rid}.json"
    waiting = waiting_record(row, target["origin"], wait_s, str(f))
    wf = host_dir / f"WAITING-{rid}.json"
    wf.write_text(json.dumps(waiting, indent=1, ensure_ascii=False))
    os.chmod(wf, 0o666)
    step.update(waiting_file=str(wf), asked_at=waiting["since"])
    fac.say(f"[{label}] host: {rid} asked ({row['host']}); waiting up to {int(wait_s)} s for {f}")
    t0 = time.monotonic()
    raw, rec, problem = None, None, None
    while time.monotonic() - t0 < wait_s:
        collect(r, await _call(s, DRAIN), target["origin"], latch, rid + ":host-wait")
        if latch.stopped:
            break
        if f.exists():
            raw = f.read_bytes()
            rec, problem = fs.parse_host_receipt(raw, rid)
            if problem == "host receipt is not JSON":  # still being written: read once more
                await asyncio.sleep(1)
                raw = f.read_bytes()
                rec, problem = fs.parse_host_receipt(raw, rid)
            if not problem and f.stat().st_mtime < asked - 1:
                problem = "host receipt is older than the check's request"
            break
        await asyncio.sleep(0.5)
    collect(r, await _call(s, DRAIN), target["origin"], latch, rid + ":host-answer")
    step.update(waited_s=round(time.monotonic() - t0, 1), receipt=rec,
                receipt_sha256=fac.sha256(raw) if raw is not None else None, answered_at=fac.now())
    if latch.stopped:
        step.update(status="BLOCKED", reasons=["invocation stopped during host wait"])
    elif raw is None:
        step.update(status="BLOCKED", reasons=[f"no host receipt within {int(wait_s)} s"])
    elif problem or (problem := receipt_problem(rec, row["host"])):
        step.update(status="BLOCKED", reasons=[problem])
    elif row["host"] in ("restart", "start"):
        got = await probe_session(browser_url, probe_js(target, "pins"), r=r, latch=latch, phase=rid + ":pins")
        probe = fs.pin_result(got, target["pins"], target["origin"])
        step["probe"] = probe
        if latch.stopped or probe.get("error") or not probe.get("ok"):
            step.update(status="BLOCKED", reasons=["after the host step the served files do not match the pins or the "
                                                   f"origin does not answer: {probe.get('error') or 'pins'}"])
        else:
            step.update(status="PASS", reasons=[])
    else:
        probe = await probe_session(browser_url, probe_js(target, "down"), r=r, latch=latch, phase=rid + ":down")
        step["probe"] = probe
        if latch.stopped or not (isinstance(probe, dict) and probe.get("down")):
            step.update(status="BLOCKED", reasons=[f"after the host's {row['host']} the origin still answers: "
                                                   f"{probe!r}"[:300]])
        else:
            step.update(status="PASS", reasons=[])
    r["host_state_at_end"] = {"after": rid, "host_action": row["host"], "status": step["status"]}
    fac.say(f"[{label}] host: {rid} {step['status']} after {step['waited_s']} s"
            + (f" -- {'; '.join(step['reasons'])}" if step["reasons"] else "")
            + f"; receipt {json.dumps(rec, ensure_ascii=False)}")
    return step


async def cleanup(s, r: dict, engine: str, label: str, latch: guard.StopLatch | None = None,
                  origin: str | None = None, *, probe: bool = False) -> None:
    """CLOSE owns the last disposal AND drain. Never address its closed carrier again.

    The unconditional MCP fallback has no observable journal channel; incomplete stays incomplete.
    """
    latch = latch if latch is not None else guard.StopLatch()
    origin = origin or r["origin"]
    c: dict = {"errors": []}
    cancelled = False
    try:
        closed = await _call(s, CLOSE)  # unconditional: SETUP may have failed before returning metadata
        if not isinstance(closed, dict) or not isinstance(closed.get("contexts"), dict):
            c["close_result"] = closed
            raise RuntimeError("terminal CLOSE did not return context/journal metadata")
        c["contexts"] = closed
        collect(r, closed.get("log") or {}, origin, latch, engine + ":close")
    except (Exception, asyncio.CancelledError) as exc:
        cancelled = cancelled or isinstance(exc, asyncio.CancelledError)
        c["errors"].append("CLOSE: " + exc_text(exc))
    terminal = c.get("contexts") or {}
    got = terminal.get("contexts") or {}
    expected = {"probe"} if probe else set(ENGINES[engine]["contexts"])
    journal = terminal.get("journal") or {}
    reasons = list(journal.get("reasons") or [])
    if journal.get("status") != "complete":
        reasons.append("terminal journal not complete")
    if not terminal.get("guard_page_closed"):
        reasons.append("guard page closure unconfirmed")
    if not terminal.get("guard_context_closed"):
        reasons.append("guard context closure unconfirmed")
    if set(got) != expected or terminal.get("untracked") or terminal.get("other_contexts_left") != 0:
        reasons.append("untracked or unresolved contexts/pages")
    if any(not x.get("page_closed") or x.get("context_still_in_browser") for x in got.values()):
        reasons.append("page/context still live at terminal drain")
    for name, state in got.items():
        errors = state.get("errors") or []
        if state.get("error") and not errors:
            c["errors"].append(f"CLOSE {name}: " + state["error"])
        for error in errors:
            c["errors"].append(f"CLOSE {name} {error['step']}: " + error["error"])
        if any(error["step"] != "context-close" for error in errors):
            reasons.append(name + ": escalation raised")
    for error in terminal.get("errors") or []:
        c["errors"].append("CLOSE " + error["step"] + ": " + error["error"])
        reasons.append("terminal disposal raised")
    if c["errors"] and not terminal:
        reasons.append("CLOSE/disposal result unavailable")
    prefix = "terminal observation not established: "
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
    c["confirmed"] = bool(c["journal"]["status"] == "complete" and not c["errors"]
                          and c.get("browser_close") == "ok" and set(got) == expected
                          and terminal.get("guard_context_closed") and not terminal.get("untracked")
                          and terminal.get("other_contexts_left") == 0
                          and all(not x.get("error") and x.get("page_closed") and not x.get("context_still_in_browser")
                                  for x in got.values()))
    r.setdefault("probe_cleanup" if probe else "cleanup", {})[engine] = c
    if c["journal"]["status"] == "incomplete":
        latch.block(engine + ": " + "; ".join(c["journal"]["reasons"]))
    elif not c["confirmed"]:
        latch.block(engine + ": disposal or terminal observations unresolved")
    latch.bind(r)
    fac.say(f"[{label}] {engine}: cleanup {'confirmed' if c['confirmed'] else 'NOT confirmed'}")
    if cancelled:
        raise asyncio.CancelledError


def traffic_gate(r: dict) -> dict:
    findings, first = [], None
    if r.get("origin"):
        log = r.get("log") or {}
        findings += fs.traffic_findings(log.get("requests") or [], log.get("websockets") or [], r["origin"])
        if findings:
            first = "event journal (probe/row/disposal)"
    if (r.get("w4") or {}).get("status") == "TRIPPED":
        findings.append("W4 TRIPPED: native Security hold required")
        first = first or "event journal"
    for s in r.get("steps") or []:
        for x in s.get("traffic") or []:
            findings.append(f"{s['id']}: {x}")
            first = first or s["id"]
    for x in r.get("late_traffic") or []:
        findings.append(f"after the last row: {x}")
        first = first or "after the last row"
    observed = [s["id"] for s in r.get("steps") or [] if s["status"] != "NOT RUN"]
    sessions = [x for x in (r.get("sessions") or {}).values() if x.get("status") == "RAN"]
    incomplete = any((x.get("journal") or {}).get("status") == "incomplete"
                     for section in ("cleanup", "probe_cleanup") for x in (r.get(section) or {}).values())
    if findings:
        status = "FAIL"
    elif not incomplete and observed == ROW_IDS and sessions and all(x.get("before_first_navigation") for x in sessions):
        status = "PASS"
    else:
        status = "NOT CHECKED"
    # Per engine, so a run whose WebKit rows are NOT RUN still shows whether its Chromium traffic was clean (host
    # rows count as Chromium: only the Chromium contexts are open while they run).
    engine_of = {x["id"]: ("chromium" if row_engine(x) == "host" else row_engine(x)) for x in p3_rows(KIT_WORDING, USERS)}
    engines = {}
    for eng in ("chromium", "webkit"):
        ids = [i for i in ROW_IDS if engine_of[i] == eng]
        dirty = any(s.get("traffic") for s in r.get("steps") or [] if engine_of.get(s["id"]) == eng)
        sess = (r.get("sessions") or {}).get(eng) or {}
        if dirty or r.get("late_traffic"):
            engines[eng] = "FAIL"
        elif not incomplete and all(i in observed for i in ids) and sess.get("status") == "RAN" and sess.get("before_first_navigation"):
            engines[eng] = "PASS"
        else:
            engines[eng] = "NOT CHECKED"
    return {"status": status, "first_seen": first, "findings": findings, "rows_observed": observed,
            "engines": engines}


def final_verdict(r: dict) -> tuple[str, str]:
    """W4 takes priority, then unresolved disposal. NOT RUN is never success.

    Ordinary row FAIL still wins over row BLOCKED when the lifetime boundary is confirmed.
    """
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
    pins = r.get("pins") or {}
    if not pins.get("ok"):
        bad = [f["file"] for f in pins.get("files") or [] if not f.get("match")]
        if pins.get("root") and not pins["root"].get("match"):
            bad.append('"/" (must be the pinned index.html)')
        bad += [f"{u} (asked for by the page, not pinned)" for u in pins.get("unpinned_refs") or []]
        return "REFUSED", "served files do not match the pins: " + (", ".join(bad) or "origin/redirect")
    late_obs = [e for e, x in (r.get("sessions") or {}).items() if x.get("status") == "RAN"
                and not x.get("before_first_navigation")]
    if late_obs:
        return "BLOCKED", f"observers were not attached before the first navigation ({', '.join(late_obs)})"
    failed = [s for s in steps if s["status"] == "FAIL"]
    gate = traffic_gate(r)
    if failed or gate["status"] == "FAIL":
        why = [f"{failed[0]['id']}: " + "; ".join(failed[0]["reasons"])] if failed else []
        if gate["status"] == "FAIL":
            why.append("traffic gate: " + "; ".join(gate["findings"]))
        return "FAIL", " | ".join(why)
    blocked = [s for s in steps if s["status"] == "BLOCKED"]
    if blocked:
        return "BLOCKED", f"{blocked[0]['id']}: " + "; ".join(blocked[0]["reasons"])
    not_run = [s for s in steps if s["status"] == "NOT RUN"]
    if not_run:
        return "BLOCKED", (f"{len(not_run)} WebKit rows NOT RUN ({not_run[0]['id']}..{not_run[-1]['id']}): "
                           + "; ".join(not_run[0]["reasons"]))
    if r.get("runner_error"):
        return "BLOCKED", f"runner stopped the journey: {r['runner_error']}"
    if [s["id"] for s in steps] != ROW_IDS or any(s["status"] != "PASS" for s in steps):
        return "BLOCKED", "not every row was observed"
    if r.get("late_findings"):
        return "FAIL", "after the last row: " + "; ".join(r["late_findings"])
    cl = r.get("cleanup") or {}
    if set(cl) != set(ENGINES) or not all(x.get("confirmed") for x in cl.values()):
        return "BLOCKED", "cleanup not confirmed: " + json.dumps(cl)
    shots = {x.get("after") for x in r.get("screenshots") or []}
    if shots != set(SHOTS):
        return "BLOCKED", f"screenshots missing: {sorted(set(SHOTS) - shots)}"
    return "PASS", f"all {len(ROW_IDS)} rows observed as expected (Chromium, WebKit phone and host rows)"


def finish(r: dict, out: pathlib.Path, *, persist: bool = True) -> dict:
    r["finished_at"] = fac.now()
    done = {s["id"] for s in r["steps"]}
    r["not_checked"] = [x for x in ROW_IDS if x not in done]
    log = r.get("log") or {}
    r["traffic"] = {
        "requests": len(log.get("requests") or []),
        "outside_or_unexpected": fs.traffic_findings(log.get("requests") or [], log.get("websockets") or [],
                                                     r["origin"]) if r.get("origin") else [],
        "critical_errors": fac.error_findings(log),
        "api_failures": fs.api_failures(log, r["origin"]) if r.get("origin") else [],
        "console_notes": log.get("console") or [],
        "failed_requests": log.get("failed") or [],
    }
    r["traffic_gate"] = traffic_gate(r)
    r["verdict"], r["why"] = final_verdict(r)
    r["exit_code"] = exit_status(r)
    if persist:
        guard.write_json(out / "observations.json", log)  # exact events, not abbreviated findings/DOM refs
        guard.write_json(out / "receipt.json", r)
        guard.write_private(out / "summary.md", summary_md(r))
    fac.say(f"[{r['label']}] VERDICT {r['verdict']}: {r['why'][:600]}")
    return r


def _short(rows) -> str:
    if not isinstance(rows, list):
        return repr(rows)
    return "; ".join(f"{(t if len(t or '') <= 24 else t[:12] + '...(' + str(len(t)) + ')')} by "
                     f"{b if len(b or '') <= 12 else b[:6] + '...(' + str(len(b)) + ')'} [{'x' if c else ' '}]"
                     for t, b, c in rows) or "(none)"


def summary_md(r: dict) -> str:
    lines = [f"# first_app_check, Project 3 journey (PENDING-SPEC rows): {r['label']}", "",
             f"Verdict: **{r['verdict']}**: {r['why']}", "",
             f"Kit {r['kit_id']} (SHA256 {r['kit_sha256']}). Origin {r['origin']}. Checker {r['checker_sha256'][:12]}, "
             f"shared module {r['shared_module_sha256'][:12]}, P3 module {r['p3_module_sha256']}. "
             f"{r['started_at']} to {r['finished_at']}.", "", f"{r['pending_spec']}.", ""]
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
                     + f"; options {json.dumps(r['engines'][e]['options'])}; presses {r['engines'][e]['presses']}")
    lines += ["", "## Rows", "", "| row | where | result | rows seen [text by name, ticked] | notes |",
              "|---|---|---|---|---|"]
    w = p.get("wording") or KIT_WORDING
    for s in r["steps"]:
        if s["kind"] == "host":
            seen, where = f"host receipt {json.dumps(s.get('receipt'), ensure_ascii=False)}", "host"
        else:
            o = (s.get("observed") or {}).get(s["ctx"])
            seen = (_short(seen_rows(o, w)) if isinstance(o, dict) and isinstance(o.get("rows"), list)
                    and all(isinstance(x.get("text"), str) for x in o["rows"]) else "(no rows)")
            where = f"{s['ctx']} ({s.get('engine')})"
        notes = "; ".join(s["reasons"] + s.get("notes", []) + [f"traffic: {x}" for x in s.get("traffic") or []]) or "-"
        lines.append(f"| {s['id']} | {where} | {s['status']} | {seen.replace('|', '/')[:400]} | "
                     f"{notes.replace('|', '/')[:600]} |")
    for sid in r["not_checked"]:
        lines.append(f"| {sid} | | NOT CHECKED | | |")
    g = r["traffic_gate"]
    t = r["traffic"]
    lines += ["", "## Traffic gate", "", f"**{g['status']}**" + (f", first seen at {g['first_seen']}" if g["first_seen"]
                                                                else ""), ""]
    lines += [f"- {x}" for x in g["findings"]]
    lines += ["", "## Traffic and errors", "", f"Requests seen: {t['requests']}.",
              f"Outside the policy: {t['outside_or_unexpected'] or 'none'}.",
              f"Critical errors: {t['critical_errors'] or 'none'}.",
              f"Failed /api/items requests: {t['api_failures'] or 'none'}.", "",
              f"Screenshots: {[x['file'] for x in r.get('screenshots') or []] or 'none'}.",
              f"Cleanup: {json.dumps(r.get('cleanup'))}.", "", "## NOT CHECKED (the kit's list; not waived)", ""]
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
                      "rows": {s["id"]: s["status"] for s in r["steps"]} | {x: "NOT CHECKED" for x in r["not_checked"]},
                      "webkit": (r.get("sessions") or {}).get("webkit", {}).get("status"),
                      "pins_ok": (r.get("pins") or {}).get("ok"), "traffic_gate": r["traffic_gate"]["status"],
                      "browser_contact": r["browser_contact"], "host_dir": r.get("host_dir"),
                      "receipt": str(out / "receipt.json")}, ensure_ascii=False), flush=True)
    return exit_status(r)


# ---------------------------------------------------------------- controls: the synthetic Project 3 server


class P3Handler(fs.Handler):
    """Project 2's synthetic handler, answering in UTF-8 JSON (ensure_ascii=False, as the FINAL asks)."""

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):  # noqa: N802
        if self.path in fs.STATIC:  # literal route map; queries/escapes are not normalized into fixture paths
            name, ctype = fs.STATIC[self.path]
            return self._send(200, self.server.files[name], ctype)
        if self.path == "/api/items":
            return self._json(200, {"items": self.server.store.items()})
        return self._json(404, {"error": "not found"})


class RaceStore(fs.Store):
    """The plant P-SIM-RACE: unlocked stale reads lose one add; only final publication is locked."""

    def add(self, text: str, added_by: str) -> dict:
        d = self._load()
        time.sleep(0.4)
        item = {"id": d["next_id"], "text": text, "added_by": added_by, "done": False}
        d["next_id"] += 1
        d["items"].append(item)
        # Protect the shared temporary pathname, not the deliberately stale read.
        with self.lock:
            self._save(d)
        return item


class P3Server(fs.SyntheticServer):
    """The controls' Project 3 server: Project 2's synthetic server with UTF-8 JSON, a kill host action
    (closed at once; a real kill is SIGKILL) and the exit code a host would report. variant: file (clean),
    race_add."""

    def __init__(self, site: pathlib.Path, data_dir: pathlib.Path, variant: str = "file", *,
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
            store = (RaceStore if self.variant == "race_add" else fs.Store)(self.data_dir / "items.json")
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
        self._retired.set()  # before waiting for a possibly in-flight host-action thread

    def shutdown(self) -> None:
        self.retire()
        self.stop()  # same lifetime lock: any earlier action settles before terminal stop completes

    def host_action(self, kind: str) -> dict:
        with self._lifetime:
            if self._retired.is_set():
                return {"action": kind, "done": False, "exit_code": 1, "note": "P3 server retired"}
            rec = super().host_action("stop" if kind == "kill" else kind)
            rec["action"] = kind
            rec["exit_code"] = 137 if kind == "kill" else 0
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


async def control_host(host_dir: pathlib.Path, server: P3Server, receipts: str = "") -> None:
    """The controls' host: answers each WAITING file by acting on the synthetic server, as Ops would on the
    real app. receipts: "" (exit_code as a host reports it), "no_exit_code", "kill_exit_0" (plants)."""
    handled: set[str] = set()
    while True:
        for wf in sorted(host_dir.glob("WAITING-*.json")):
            rid = wf.name[len("WAITING-"):-len(".json")]
            if rid in handled:
                continue
            handled.add(rid)
            ask = json.loads(wf.read_text())
            did = await asyncio.to_thread(server.host_action, ask["host_action"])
            rec = {"row": rid, "by": "control host: the check's own synthetic server", "at": fac.now(),
                   "done": did.pop("done"), "exit_code": did.pop("exit_code"), "note": json.dumps(did)}
            if receipts == "no_exit_code":
                rec.pop("exit_code")
            if receipts == "kill_exit_0" and ask["host_action"] == "kill":
                rec["exit_code"] = 0
            tmp = host_dir / f".{rid}.json.tmp"
            tmp.write_text(json.dumps(rec))
            os.replace(tmp, host_dir / f"{rid}.json")
        await asyncio.sleep(0.2)


# Controls and what each must get: (verdict, first row that FAILs or is BLOCKED). webkit: the case's verdict
# needs the WebKit rows (NOT RUN when the WebKit service does not answer).
CONTROLS = [
    {"case": "P3-CLEAN", "variant": "clean", "expect": ("PASS", None), "webkit": True},
    {"case": "P3-INNERHTML", "variant": "inner_html", "expect": ("FAIL", "U-3")},
    {"case": "P3-UTF16-LENGTH", "variant": "utf16_length", "expect": ("FAIL", "L-1")},
    {"case": "P3-NO-DIR-AUTO", "variant": "no_dir_auto", "expect": ("FAIL", "U-2")},
    {"case": "P3-FIXED-600", "variant": "fixed_600", "expect": ("FAIL", "W-1"), "webkit": True},
    {"case": "P3-IDLE-CALLBACK", "variant": "idle_callback", "expect": ("FAIL", "W-1"), "webkit": True},
    {"case": "P3-NO-BANNER", "variant": "no_banner", "expect": ("FAIL", "D-2")},
    {"case": "P3-NO-PUT-BACK", "variant": "no_put_back", "expect": ("FAIL", "D-2")},
    {"case": "P3-SIM-RACE", "variant": "clean", "server": "race_add", "expect": ("FAIL", "S-1")},
    {"case": "P3-NO-EXIT-CODE", "variant": "clean", "receipts": "no_exit_code", "expect": ("BLOCKED", "R-1")},
    {"case": "P3-KILL-EXIT-0", "variant": "clean", "receipts": "kill_exit_0", "expect": ("BLOCKED", "D-1")},
    {"case": "P3-BAD-PROFILE", "variant": "clean", "profile": "served_origin", "expect": ("REFUSED", None)},
]


def control_status(case: dict, r: dict) -> tuple[str, list]:
    """OK, WRONG or NOT RUN (a WebKit case while WebKit does not answer: every Chromium and host row passed and
    the WebKit rows are NOT RUN)."""
    stop = next((s for s in r["steps"] if s["status"] in ("FAIL", "BLOCKED", "NOT RUN")), None)
    got = [r["verdict"], stop["id"] if stop else None]
    if r["verdict"] == "W4 TRIPPED":
        return "W4 TRIPPED", got
    if (r.get("invocation_stop") or {}).get("blocked"):
        return "BLOCKED", got
    gate = r["traffic_gate"]["status"]
    webkit = (r.get("sessions") or {}).get("webkit", {}).get("status")
    if case.get("webkit") and webkit == "NOT RUN":
        chromium_gate = (r["traffic_gate"].get("engines") or {}).get("chromium")
        ok = (r["verdict"] == "BLOCKED" and stop is not None and stop["status"] == "NOT RUN" and stop["id"] == "W-1"
              and all(s["status"] == "PASS" for s in r["steps"] if s["status"] != "NOT RUN") and gate != "FAIL"
              and chromium_gate == "PASS")
        return ("NOT RUN" if ok else "WRONG"), got
    ok = got == list(case["expect"]) and (gate == "PASS" if case["expect"][0] == "PASS" else gate != "FAIL")
    return ("OK" if ok else "WRONG"), got


async def dispose_control(server, host) -> list[str]:
    errors = []
    if server is not None:
        server.retire()  # disallow late threaded actions before awaiting/cancelling the host
    try:
        if host is not None:
            host.cancel()
            try:
                await host
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                errors.append("host task: " + exc_text(exc))
    finally:
        if server is not None:
            try:
                await asyncio.to_thread(server.shutdown)
            except Exception as exc:
                errors.append("server shutdown: " + exc_text(exc))
    return errors


async def run_control(args, case: dict, out: pathlib.Path, tmp: pathlib.Path, ip: str,
                      latch: guard.StopLatch | None = None) -> dict:
    latch = latch if latch is not None else guard.StopLatch()
    case_out, label = out / case["case"], f"control {case['case']}"
    r = new_receipt(label, None)
    server, host, cancelled = None, None, False
    try:
        if latch.stopped:
            raise RuntimeError("invocation already stopped: no new case")
        base = tmp / case["case"]
        site = materialize(case["variant"], base)
        data = base / "data"
        data.mkdir(mode=0o700)
        server = P3Server(site, data, case.get("server", "file"), bind_address="0.0.0.0")
        server.start()
        origin = f"http://{ip}:{server.port}"
        # Pin and serve precisely the same captured regular-file bytes, never reopen site paths.
        pins = {n: fac.sha256(data) for n, data in server.files.items()}
        host_dir = case_out / "host"
        host = asyncio.create_task(control_host(host_dir, server, case.get("receipts", "")))
        if case.get("profile") == "served_origin":
            r = await check_profile(args, json.dumps(default_p3_profile(origin=origin, pins=pins)), case_out, label,
                                    fs.CONTROL_BUDGET_S, latch, persist=False)
        else:
            profile = default_p3_profile(pins=pins)
            profile["host_wait_minutes"] = 1
            target, problems = parse_p3_profile(json.dumps(profile))
            if problems:
                raise ValueError(f"control profile refused: {problems}")
            target["control_note"] = (f"control: the profile's origin {target['origin']} replaced, after the profile "
                                      f"was accepted, by the synthetic server's {origin}")
            target["host_wait_minutes"] = fs.CONTROL_HOST_WAIT_S / 60
            target["origin"] = origin
            r = new_receipt(label, target)
            await check_target(args.browser, args.browser_webkit, target, case_out, label, host_dir,
                               fs.CONTROL_BUDGET_S, latch=latch, persist=False, receipt=r)
    except asyncio.CancelledError:
        cancelled = True
        r["runner_error"] = "control cancelled"
        latch.block(r["runner_error"])
    except Exception as exc:
        r.setdefault("runner_error", exc_text(exc))
        latch.block("control lifetime failure: " + exc_text(exc))
    finally:
        task = asyncio.create_task(dispose_control(server, host))
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
    finish(r, case_out)  # receipt is final only after host and server disposal
    if cancelled:
        raise asyncio.CancelledError
    status, got = control_status(case, r)
    hits = server.hits if server is not None else []
    api_hits = [h for h in hits if " /api/" in h]
    if r["verdict"] == "REFUSED" and (r["steps_attempted"] or api_hits):
        status = "WRONG"
    if (r.get("profile") or {}).get("problems") and (r["browser_contact"] or hits):
        status = "WRONG"
    return {"case": case["case"], "expected": list(case["expect"]), "got": got, "status": status,
            "traffic_gate": r["traffic_gate"]["status"], "gate_engines": r["traffic_gate"].get("engines"),
            "webkit": (r.get("sessions") or {}).get("webkit", {}).get("status"), "why": r["why"],
            "steps_attempted": r["steps_attempted"], "browser_contact": r["browser_contact"],
            "server_requests": len(hits), "api_requests": len(api_hits),
            "server_starts": server.starts if server is not None else 0,
            "rows": {s["id"]: s["status"] for s in r["steps"]}, "receipt": str(case_out / "receipt.json")}


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
    summary = {"mode": "controls_p3", "journey": "p3", "all_ok": all_ok and not latch.stopped,
               "full_qualification": all_ok and not latch.stopped and {x["case"] for x in results} == names,
               "selection_error": "empty/unmatched selection" if invalid or not selected else None,
               "not_reached": [c["case"] for c in selected if c["case"] not in {x["case"] for x in results}],
               "not_run": [x["case"] for x in results if x["status"] == "NOT RUN"], "cases": results,
               "checker_sha256": fac.sha256(pathlib.Path(fac.__file__).read_bytes()),
               "shared_module_sha256": fac.sha256(pathlib.Path(fs.__file__).read_bytes()),
               "p3_module_sha256": fac.sha256(pathlib.Path(__file__).read_bytes()),
               "p3_guard_sha256": fac.sha256(pathlib.Path(guard.__file__).read_bytes())}
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
    a = ap.parse_args()
    if a.print_p3_profile:
        print(json.dumps(default_p3_profile(), indent=1, ensure_ascii=False))
        return 0
    if not a.mode or not a.out:
        ap.error("--mode and --out are required")
    if a.mode != "live" and a.profile:
        ap.error("--profile is for --mode live; the controls bring their own profiles")
    out = pathlib.Path(os.path.abspath(a.out))  # preserve literal components; never resolve and follow a symlink
    with guard.directory_fd(out, create=True) as fd:
        os.fchmod(fd, 0o700)
    return asyncio.run(live(a, out) if a.mode == "live" else controls(a, out))


if __name__ == "__main__":
    sys.exit(main())
