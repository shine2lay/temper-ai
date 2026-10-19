"""first_app_shared (System architecture, queue #97, 2026-10-18): first_app_check's second journey, QA's
frozen critical journey of Team Project 2's shared to-do list (kit qa-project2-critical-v1, CASE-KIT.json
SHA256 174d7772...a129c), in real browsers, with no model.

first_app_check.py loads this module only for a profile with "journey": "shared" (mode=live) and for
mode=controls_shared; a run without that key never imports it, so the first app's check is unchanged.

  The origin: https://spark.tailbb5055.ts.net:<port> as for the first app, or http://100.110.162.4:<port>,
  spark's tailnet address, where Ops hosts Project 2 (Ops rm-f85721b1, QA's HOSTING-RULING-1).

  A  reach and pin: a fresh context opens the origin with every /api/ request held back (aborted before
     it is sent), fetches the pinned files in the page (same origin, no cache) and hashes the bytes the
     browser received and the "/" document itself (must be the pinned index.html). A wrong or missing
     file, or a same-origin file the page asks for that is not pinned (favicon.svg when the page links
     it), REFUSES the check before any row. The server's own code cannot be seen from a browser: the
     receipt records the profile's build commit and SHA256SUMS digest, attested by the host's record.
  B  journey: one browser session, three fresh contexts A, B and C (separate cookies and storage: the
     browser's own isolation), each with request, error, dialog and websocket observers attached before
     its first page exists. The kit's rows in order: J-1..J-15 (A adds, B reloads and sees it; B ticks
     and deletes, A sees it), E-1..E-6 (blank, 201 and 200 characters, typed HTML), R-1 (host restart),
     R-2, R-3, D-1 (host stop), D-2..D-4 (the page open while the server is down), D-5 (host start),
     D-6. Actions are done as a user would, on controls named by the profile's wording; after each one
     the check waits until the context has no request in flight, the document is complete and no
     element is aria-busy (three quiet polls 100 ms apart, at most 15 s), then reads the rendered page:
     rows as [text (the checkbox's name), added-by name (from its description), ticked], top to
     bottom; who am I; the item message; the banner; the empty-list sentence; typed-HTML elements. A
     row whose observation is missing is BLOCKED, never PASS or FAIL. The first FAIL or BLOCKED stops
     the journey; later rows are NOT CHECKED.
     Host rows (R-1, D-1, D-5): the check writes out/host/WAITING-<row>.json and waits, the contexts
     kept open, for the host's receipt out/host/<row>.json ({"row", "done", "by", "at", "note"}). The
     check never stops or starts anything itself: in a live run the host (Ops, on Architecture's word)
     does; in the controls this module's own synthetic server is stopped and started on the same port
     and data folder. A missing, late or "done": false receipt is BLOCKED, and so is a stop whose
     exit_code is not 0. Then, in a browser session of its own (never through A, B or C): after R-1
     and D-5 the served files are pinned again; after D-1 the origin must give no HTTP answer.
  C  traffic and errors: the kit's traffic gate, apart from the rows: only the exact origin, and only
     GET /, /index.html, /style.css, /app.js, /favicon.svg, /api/items; POST /api/items; PATCH and
     DELETE /api/items/<digits>. Anything else (origin, path, method, query, websocket, an outside
     font) FAILs the gate and stops the journey. Page errors, dialogs and crashes fail their row; a
     failed /api/items request (network error or 5xx) fails its row except in D-2..D-4.
  D  cleanup: the three contexts closed and confirmed gone, then browser_close; unknown = BLOCKED.

The list record: E-6's rows (the saved list before the restart) and R-2's, R-3's and D-6's rows after
it, each with the SHA256 of its canonical JSON and whether it equals E-6's.

Not checked here (QA's or the host's): S-1's 16-file SHA256SUMS part, S-2, H-1, H-2, the server's bytes.
"""

import asyncio
import base64
import hashlib
import http.server
import json
import os
import pathlib
import re
import shutil
import socket
import tempfile
import threading
import time
import urllib.parse

import first_app_check as fac

HERE = pathlib.Path(__file__).resolve().parent
FIXTURE = HERE.parent / "fixtures" / "shared_app"

KIT_ID = "qa-project2-critical-v1"
KIT_SHA256 = "174d77726c02b9fd45adc19896b2840b8b954617339d877f61f25932bf3a129c"
# The kit's "notChecked" list, word for word.
KIT_NOT_CHECKED = [
    "Two people acting at the same moment (races), and acting on an item the other already deleted "
    "(That item was already deleted.)",
    "Blank or over-50-character names; changing a name",
    "Text beyond ASCII: emoji, combining marks, right-to-left; counting in code points",
    "Reloading or first opening the page while the server is down",
    "Server edge cases: bad JSON, wrong content type, oversized bodies, other HTTP methods, IPv6, bad PORT or "
    "DATA_DIR, HOST other than 127.0.0.1, sharing on a network",
    "Data after a crash (kill -9) rather than a clean stop; writes outside DATA_DIR; running without a network",
    "Other browsers, phone widths, keyboard-only and screen-reader use, contrast and visual design",
    "The team's own tests, qa/ checks and REPORT.md (not run, not trusted)",
]
NOT_CHECKED_HERE = [
    "S-1's other half: all 16 build files against build-de580ff2.SHA256SUMS (static, QA's)",
    "S-2: the modules server.py imports (static, QA's)",
    "H-1 and H-2: the host's start receipt and its read of DATA_DIR (QA reads the host's receipts)",
    "The server's bytes: a browser cannot see them; the build commit and SHA256SUMS digest in this receipt are "
    "the profile's, attested by the host's record, not checked",
]
# The pinned build (kit "build"), as --print-shared-profile gives it.
BUILD_PINS = {
    "index.html": "c381e9d09c1a89364c1cd8460282608af58d5c069ca0384f242159dbe4623f3b",
    "style.css": "f69df4eeb80ddb908e13329ccee90f1dbc358f9e4afc86e864837ec6fd6be011",
    "app.js": "87940e9708c75e3ab0e3b0289039c6451f3e6f78778111ee2cbebbe61be44f14",
    "favicon.svg": "f90ceda87f48da2719538d70c1d8cb4436543e385c2f808ecb457648538200f2",
}
BUILD = {"commit": "38dab31e", "sha256sums_sha256": "09d4facf1fa9654d5c43bd78835c014a5cb0ebcaf1d80bfeee24612286709b28"}
# The kit's wording, in the profile's keys.
KIT_WORDING = {
    "heading": "To-do list",
    "name_textbox": "Your name",
    "name_button": "Save name",
    "whoami": "You are {name}",
    "item_textbox": "New item",
    "add_button": "Add",
    "delete_button": "Delete {item}",
    "added_by": "added by {name}",
    "empty_text": "No items yet. Add the first one above.",
    "item_blank": "Type an item first.",
    "item_too_long": "Too long: {n} characters. The limit is 200.",
    "unreachable": "Can't reach the server. Your change was not saved.",
}
WORDING_KEYS = tuple(KIT_WORDING)
PLACEHOLDERS = {"whoami": "{name}", "added_by": "{name}", "delete_button": "{item}", "item_too_long": "{n}"}
USERS = {"A": "Ana", "B": "Ben", "C": "<i>Cy</i>"}
# Where Ops hosts Project 2 (Ops rm-f85721b1; QA's HOSTING-RULING-1 replaces the kit's spark name with it):
# spark's own tailnet address, plain http, because Security's must 5 rules out Tailscale Serve, tunnels and proxies.
PROJECT2_ORIGIN = "http://100.110.162.4:8961"
TAILNET_ORIGIN_RE = re.compile(r"http://100\.110\.162\.4:([1-9][0-9]{0,4})")
PROFILE_KEYS = ("journey", "origin", "pins", "build", "kit_id", "kit_sha256", "kit_not_checked", "wording", "users",
                "host_wait_minutes")
REQUIRED_PINS = ("index.html", "style.css", "app.js")
OPTIONAL_PINS = ("favicon.svg",)
COMMIT_RE = re.compile(r"[0-9a-f]{7,40}")
API_ITEM_RE = re.compile(r"/api/items/[0-9]+")
GET_PATHS = ("/", "/index.html", "/style.css", "/app.js", "/favicon.svg", "/api/items")
CONTEXT_OPTS = {"viewport": fac.VIEWPORT, "locale": fac.LOCALE, "timezoneId": fac.TIMEZONE}
SETTLE_RULE = ("after each action: no request in flight in the acting context (request events minus finished and "
               "failed ones), document complete, no aria-busy element, the Add button (#add-button, when shown) "
               "reading add_button again; three quiet polls 100 ms apart, at most 15 s; then 300 ms before reading "
               "the page")
OUTAGE_ROWS = ("D-2", "D-3", "D-4")  # failed /api/items requests are expected only here (between D-1 and D-5)
SHOTS = {"E-6": "A-after-E-6.png", "D-4": "A-server-down-D-4.png"}
LIVE_BUDGET_S = 3300  # the agent runs the script for at most 3500 s; host waits are cut to fit
RESERVE_S = 300
CONTROL_HOST_WAIT_S = 120
CONTROL_BUDGET_S = 900
RECEIPT_MAX = 16384
RECEIPT_FORMAT = {"row": "the row id, as in the WAITING file", "done": "true once done and confirmed; false if it "
                  "could not be done", "by": "who did it", "at": "ISO time it was done",
                  "exit_code": "optional: the stopped app's exit code (QA's ruling: a stop counts only with 0)",
                  "note": "optional: what was done (the host's own receipt: commands, times, data folder, answers)"}

BM, WP, CS, PR, FC = "Buy milk", "Water plants", "Call Sam", "Pay rent", "Feed cat"


# ---------------------------------------------------------------- the kit's rows (CASE-KIT.json "rows")


def shared_rows(w: dict, users: dict) -> list[dict]:
    """The kit's browser and host rows in order, with the build's wording w and the users' names. Rows are
    [text, added by, ticked]; "unchanged from J-15" and "exactly E-5's rows" are the kit's expected lists."""
    a, b, c = users["A"], users["B"], users["C"]
    y200 = "y" * 200
    j15 = [[BM, a, False], [CS, b, False]]
    e5 = j15 + [[y200, a, False], ["<b>hi</b>", c, False]]
    too_long = w["item_too_long"].replace("{n}", "201")

    def add(text, submit="button", clear=False):
        return {"do": "add", "text": text, "submit": submit, "clear": clear}

    return [
        {"id": "J-1", "ctx": "A", "action": "Open the origin.", "acts": [{"do": "open"}],
         "expected": {"heading": w["heading"], "name_form": True, "item_textbox": False}},
        {"id": "J-2", "ctx": "A", "action": f"Type {a} in {w['name_textbox']}, activate {w['name_button']}.",
         "acts": [{"do": "name", "text": a}],
         "expected": {"whoami": a, "item_textbox": True, "add_button": True, "rows": [], "empty_text": True}},
        {"id": "J-3", "ctx": "A", "action": "Reload.", "acts": [{"do": "reload"}],
         "expected": {"name_form": False, "whoami": a, "rows": []}},
        {"id": "J-4", "ctx": "A", "action": f"Type {BM} in {w['item_textbox']}, activate {w['add_button']}.",
         "acts": [add(BM)], "expected": {"rows": [[BM, a, False]], "item_value": ""}},
        {"id": "J-5", "ctx": "A", "action": f"Type {WP}, press Enter.", "acts": [add(WP, "enter")],
         "expected": {"rows": [[BM, a, False], [WP, a, False]]}},
        {"id": "J-6", "ctx": "B", "action": "Open the origin in fresh context B.", "acts": [{"do": "open"}],
         "expected": {"name_form": True, "item_textbox": False}},
        {"id": "J-7", "ctx": "B", "action": f"Type {b}, activate {w['name_button']}.",
         "acts": [{"do": "name", "text": b}],
         "expected": {"whoami": b, "rows": [[BM, a, False], [WP, a, False]]}},
        {"id": "J-8", "ctx": "B", "action": f"Add {CS}, then add {PR}.", "acts": [add(CS), add(PR)],
         "expected": {"rows": [[BM, a, False], [WP, a, False], [CS, b, False], [PR, b, False]]}},
        {"id": "J-9", "ctx": "B", "action": f"Tick the {BM} checkbox.", "acts": [{"do": "tick", "item": BM}],
         "expected": {"rows": [[BM, a, True], [WP, a, False], [CS, b, False], [PR, b, False]]}},
        {"id": "J-10", "ctx": "B", "action": f"Activate {w['delete_button'].replace('{item}', WP)}.",
         "acts": [{"do": "delete", "item": WP}],
         "expected": {"rows": [[BM, a, True], [CS, b, False], [PR, b, False]]}},
        {"id": "J-11", "ctx": "A", "action": "Reload.", "acts": [{"do": "reload"}],
         "expected": {"rows": [[BM, a, True], [CS, b, False], [PR, b, False]]}},
        {"id": "J-12", "ctx": "A", "action": f"Untick {BM}, tick {CS}, activate "
         f"{w['delete_button'].replace('{item}', PR)}.",
         "acts": [{"do": "untick", "item": BM}, {"do": "tick", "item": CS}, {"do": "delete", "item": PR}],
         "expected": {"rows": [[BM, a, False], [CS, b, True]]}},
        {"id": "J-13", "ctx": "B", "action": "Reload.", "acts": [{"do": "reload"}],
         "expected": {"rows": [[BM, a, False], [CS, b, True]]}},
        {"id": "J-14", "ctx": "B", "action": f"Untick {CS}.", "acts": [{"do": "untick", "item": CS}],
         "expected": {"rows": j15}},
        {"id": "J-15", "ctx": "A", "action": "Reload.", "acts": [{"do": "reload"}], "expected": {"rows": j15}},
        {"id": "E-1", "ctx": "A", "action": f"Type three spaces in {w['item_textbox']}, activate {w['add_button']}.",
         "acts": [add("   ")], "expected": {"message": w["item_blank"], "rows": j15}},
        {"id": "E-2", "ctx": "A", "action": f"Clear {w['item_textbox']}, type 201 x characters, activate "
         f"{w['add_button']}.", "acts": [add("x" * 201, clear=True)], "expected": {"message": too_long, "rows": j15}},
        {"id": "E-3", "ctx": "A", "action": f"Clear {w['item_textbox']}, type 200 y characters, activate "
         f"{w['add_button']}.", "acts": [add(y200, clear=True)], "expected": {"rows": j15 + [[y200, a, False]]}},
        {"id": "E-4", "ctx": "C", "action": f"Open the origin in fresh context C, type {c} in {w['name_textbox']}, "
         f"activate {w['name_button']}.", "acts": [{"do": "open"}, {"do": "name", "text": c}],
         "expected": {"whoami": c, "no_whoami_html": True}},
        {"id": "E-5", "ctx": "C", "action": "Add <b>hi</b>.", "acts": [add("<b>hi</b>")],
         "expected": {"rows": e5, "no_list_html": True}},
        {"id": "E-6", "ctx": "A", "action": "Reload.", "acts": [{"do": "reload"}], "expected": {"rows": e5}},
        {"id": "R-1", "host": "restart", "action": "Stop the server (stopMethod); start it again with the same "
         "command and the same DATA_DIR.", "expected": "Host receipt: old process exited, port closed between, new "
         "process listening, same DATA_DIR path, served pins unchanged. Missing receipt or no way to stop and start "
         "= BLOCKED."},
        {"id": "R-2", "ctx": "A", "action": "Reload.", "acts": [{"do": "reload"}], "expected": {"whoami": a, "rows": e5}},
        {"id": "R-3", "ctx": "B", "action": "Reload.", "acts": [{"do": "reload"}], "expected": {"whoami": b, "rows": e5}},
        {"id": "D-1", "host": "stop", "action": "Stop the server (stopMethod). Do not reload A.",
         "expected": "Host receipt: process exited, port closed. Missing = BLOCKED."},
        {"id": "D-2", "ctx": "A", "action": f"Type {FC} in {w['item_textbox']}, activate {w['add_button']}.",
         "acts": [add(FC)], "expected": {"banner": w["unreachable"], "rows": e5}},
        {"id": "D-3", "ctx": "A", "action": f"Tick {BM}.", "acts": [{"do": "tick", "item": BM}],
         "expected": {"banner": w["unreachable"], "rows": e5}},
        {"id": "D-4", "ctx": "A", "action": f"Activate {w['delete_button'].replace('{item}', CS)}.",
         "acts": [{"do": "delete", "item": CS}], "expected": {"banner": w["unreachable"], "rows": e5}},
        {"id": "D-5", "host": "start", "action": "Start the server again with the same command and DATA_DIR.",
         "expected": "Host receipt as R-1."},
        {"id": "D-6", "ctx": "A", "action": "Reload.", "acts": [{"do": "reload"}],
         "expected": {"rows": e5, "banner": False}},
    ]


ROW_IDS = [x["id"] for x in shared_rows(KIT_WORDING, USERS)]


# ---------------------------------------------------------------- the profile (unit-tested)


def default_shared_profile(origin: str = PROJECT2_ORIGIN, pins: dict | None = None) -> dict:
    """The kit's values and Ops' origin in the shared profile's form (--print-shared-profile)."""
    return {"journey": "shared", "origin": origin, "pins": dict(pins or BUILD_PINS), "build": dict(BUILD),
            "kit_id": KIT_ID, "kit_sha256": KIT_SHA256, "kit_not_checked": list(KIT_NOT_CHECKED),
            "wording": dict(KIT_WORDING), "users": dict(USERS), "host_wait_minutes": 15}


def shared_origin_problems(origin) -> list[str]:
    """The first app's rule (https://spark.tailbb5055.ts.net:<port>) or, narrowly widened for Project 2's hosting,
    spark's tailnet address over plain http (http://100.110.162.4:<port>); nothing else."""
    if isinstance(origin, str) and (m := TAILNET_ORIGIN_RE.fullmatch(origin)):
        port = int(m.group(1))
        if port > 65535:
            return [f"origin port {port} is not a port"]
        if port == 80:
            return ["origin port 80 is http's default, which browsers drop, so the page's origin would not match"]
        return []
    if fac.origin_problems(origin):
        return [f"origin {str(origin)[:120]!r} is neither https://spark.tailbb5055.ts.net:<port> nor "
                "http://100.110.162.4:<port> (no other scheme, host or path)"]
    return []


def shared_pins_problems(pins) -> list[str]:
    if not isinstance(pins, dict):
        return ["pins is not an object of file name to SHA256"]
    out = []
    missing = [n for n in REQUIRED_PINS if n not in pins]
    extra = sorted(str(n) for n in pins if n not in REQUIRED_PINS + OPTIONAL_PINS)
    if missing:
        out.append(f"pins is missing {', '.join(missing)}")
    if extra:
        out.append(f"pins has files that are not allowed: {', '.join(extra)} (only {', '.join(REQUIRED_PINS)} "
                   f"and, if the page links it, {', '.join(OPTIONAL_PINS)})")
    for name in REQUIRED_PINS + OPTIONAL_PINS:
        if name in pins and not (isinstance(pins[name], str) and fac.HEX64_RE.fullmatch(pins[name])):
            out.append(f"pin for {name} is not 64 lowercase hex characters")
    return out


def build_problems(build) -> list[str]:
    if not isinstance(build, dict):
        return ["build is not an object with commit and sha256sums_sha256"]
    out = fac._keys_problems(build, ("commit", "sha256sums_sha256"), "build")
    if "commit" in build and not (isinstance(build["commit"], str) and COMMIT_RE.fullmatch(build["commit"])):
        out.append("build.commit is not 7 to 40 lowercase hex characters")
    if "sha256sums_sha256" in build and not (isinstance(build["sha256sums_sha256"], str)
                                             and fac.HEX64_RE.fullmatch(build["sha256sums_sha256"])):
        out.append("build.sha256sums_sha256 is not 64 lowercase hex characters")
    return out


def shared_wording_problems(w) -> list[str]:
    if not isinstance(w, dict):
        return ["wording is not an object"]
    out = fac._keys_problems(w, WORDING_KEYS, "wording")
    out += [x for k in WORDING_KEYS if k in w and (x := fac._text_problem(w[k], f"wording.{k}"))]
    for key, mark in PLACEHOLDERS.items():
        if isinstance(w.get(key), str) and w[key].count(mark) != 1:
            out.append(f"wording.{key} must hold {mark} exactly once, as in {KIT_WORDING[key]!r}")
    return out


def users_problems(users) -> list[str]:
    if not isinstance(users, dict):
        return ["users is not an object with the names of A, B and C"]
    out = fac._keys_problems(users, ("A", "B", "C"), "users")
    out += [x for k in ("A", "B", "C") if k in users and (x := fac._text_problem(users[k], f"users.{k}", 50))]
    names = [users.get(k) for k in ("A", "B", "C") if isinstance(users.get(k), str)]
    if len(set(names)) != len(names):
        out.append("users must have three different names")
    return out


def parse_shared_profile(text: str | None) -> tuple[dict | None, list[str]]:
    """The shared journey's target and the profile's problems: one JSON object with exactly PROFILE_KEYS,
    "journey": "shared", each key checked strictly. Any problem REFUSES the run before the browser is
    contacted."""
    if text is None or not text.strip():
        return None, ["the shared journey needs a profile"]
    if len(text) > fac.PROFILE_MAX_CHARS:
        return None, [f"profile is {len(text)} characters long; at most {fac.PROFILE_MAX_CHARS}"]
    try:
        p = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, [f"profile is not JSON ({exc.msg} at character {exc.pos}); pass one JSON object as text"]
    if not isinstance(p, dict):
        return None, ["profile is not a JSON object"]
    problems = fac._keys_problems(p, PROFILE_KEYS, "profile")
    if "journey" in p and p["journey"] != "shared":
        problems.append(f"journey {str(p['journey'])[:40]!r} is not known; the only journey is \"shared\"")
    if "origin" in p:
        problems += shared_origin_problems(p["origin"])
    if "pins" in p:
        problems += shared_pins_problems(p["pins"])
    if "build" in p:
        problems += build_problems(p["build"])
    problems += fac.kit_problems(p)
    if "wording" in p:
        problems += shared_wording_problems(p["wording"])
    if "users" in p:
        problems += users_problems(p["users"])
    if "host_wait_minutes" in p:
        h = p["host_wait_minutes"]
        if not (isinstance(h, int) and not isinstance(h, bool) and 1 <= h <= 60):
            problems.append("host_wait_minutes is not a whole number of minutes from 1 to 60")
    if problems:
        return None, problems
    return {"source": "input", "journey": "shared", "profile_sha256": fac.sha256(text.encode()),
            "origin": p["origin"], "pins": {n: {"sha256": h} for n, h in p["pins"].items()},
            "build": dict(p["build"]), "kit_id": p["kit_id"], "kit_sha256": p["kit_sha256"],
            "kit_not_checked": list(p["kit_not_checked"]), "wording": {k: p["wording"][k] for k in WORDING_KEYS},
            "users": {k: p["users"][k] for k in ("A", "B", "C")}, "host_wait_minutes": p["host_wait_minutes"]}, []


def parse_host_receipt(raw: bytes, row: str) -> tuple[dict | None, str | None]:
    """A host's receipt for one host row: (the receipt, None) or (None, why it is not one)."""
    if len(raw) > RECEIPT_MAX:
        return None, f"host receipt is {len(raw)} bytes; at most {RECEIPT_MAX}"
    try:
        rec = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "host receipt is not JSON"
    if not isinstance(rec, dict):
        return None, "host receipt is not a JSON object"
    if rec.get("row") != row:
        return None, f"host receipt names row {str(rec.get('row'))[:20]!r}, not {row}"
    if not isinstance(rec.get("done"), bool):
        return None, "host receipt has no done: true or false"
    if not (isinstance(rec.get("by"), str) and rec["by"].strip() and len(rec["by"]) <= 200):
        return None, "host receipt does not say who did it (by)"
    if not (isinstance(rec.get("at"), str) and rec["at"].strip() and len(rec["at"]) <= 64):
        return None, "host receipt does not say when (at)"
    if "note" in rec and not isinstance(rec["note"], str):
        return None, "host receipt's note is not text"
    if "exit_code" in rec and not (isinstance(rec["exit_code"], int) and not isinstance(rec["exit_code"], bool)):
        return None, "host receipt's exit_code is not a whole number"
    return rec, None


# ---------------------------------------------------------------- pure comparators (unit-tested)


def parse_by(desc, template: str) -> str | None:
    """The name in a row's description read with the added-by wording ("added by {name}"); None when the
    description does not have that form."""
    if not isinstance(desc, str):
        return None
    pre, suf = template.split("{name}", 1)
    if desc.startswith(pre) and desc.endswith(suf) and len(desc) >= len(pre) + len(suf):
        return desc[len(pre):len(desc) - len(suf)]
    if desc == " ".join((pre + suf).split()):
        return ""
    return None


def seen_rows(obs: dict, w: dict) -> list[list]:
    return [[x.get("text"), parse_by(x.get("desc"), w["added_by"]), bool(x.get("checked"))] for x in obs["rows"]]


def canon_sha256(rows) -> str:
    return fac.sha256(json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode())


NEEDS = {"heading": ("headings",), "name_form": ("name_textbox", "name_button"), "item_textbox": ("item_textbox",),
         "item_value": ("item_textbox",), "add_button": ("add_button",), "whoami": ("whoami",), "rows": ("rows",),
         "empty_text": ("empty_text_visible",), "message": ("message",), "banner": ("banner",),
         "no_whoami_html": ("whoami",), "no_list_html": ("rows",)}


def _shown(c) -> bool:
    return isinstance(c, dict) and c.get("count") == 1 and bool(c.get("visible"))


def compare_row(expected: dict, obs, w: dict) -> tuple[list[str], list[str]]:
    """(what the rendered page showed that differs from the kit's expected values, observations missing)."""
    if not isinstance(obs, dict):
        return [], ["no observation"]
    missing = sorted({k for key in expected for k in NEEDS.get(key, ()) if k not in obs})
    if missing:
        return [], [f"no observation of {', '.join(missing)}"]
    out = []
    for key, want in expected.items():
        if key == "heading":
            if want not in (obs["headings"] or []):
                out.append(f"heading {want!r} not shown; headings {obs['headings']!r}")
        elif key == "name_form":
            shown = _shown(obs["name_textbox"]) and _shown(obs["name_button"])
            if shown != want:
                out.append(f"name form ({w['name_textbox']} and {w['name_button']}) "
                           f"{'not shown' if want else 'still shown'}")
        elif key == "item_textbox":
            tb = obs["item_textbox"]
            shown = _shown(tb) and (not want or bool(tb.get("enabled")))
            if shown != want:
                out.append(f"{w['item_textbox']} {'not shown and usable' if want else 'shown'}: {tb!r}")
        elif key == "item_value":
            value = (obs["item_textbox"] or {}).get("value")
            if value != want:
                out.append(f"{w['item_textbox']} holds {value!r}, expected {want!r}")
        elif key == "add_button":
            b = obs["add_button"]
            if (_shown(b) and bool(b.get("enabled"))) != want:
                out.append(f"button {w['add_button']} {'not shown and usable' if want else 'shown'}: {b!r}")
        elif key == "whoami":
            o = obs["whoami"] or {}
            line = " ".join(w["whoami"].replace("{name}", want).split())
            if not (o.get("visible") and o.get("name") == want and str(o.get("line") or "").startswith(line)):
                out.append(f"who-am-I shows {o.get('line')!r} (name {o.get('name')!r}, visible "
                           f"{bool(o.get('visible'))}), expected {line!r}")
        elif key == "rows":
            got = seen_rows(obs, w)
            if got != want:
                out.append(f"rows {got!r}, expected {want!r}")
            unnamed = [x.get("text") for x in obs["rows"] if x.get("named") is False]
            if unnamed:
                out.append(f"checkbox not named by its text (the browser's accessible name): {unnamed!r}")
        elif key == "empty_text":
            if bool(obs["empty_text_visible"]) != want:
                out.append(f"empty-list sentence {w['empty_text']!r} {'not shown' if want else 'shown'}")
        elif key == "message":
            m = obs["message"] or {}
            if not (m.get("visible") and m.get("text") == want):
                out.append(f"item message {m.get('text')!r}, expected {want!r}")
        elif key == "banner":
            b = obs["banner"] or {}
            if want is False and b.get("visible"):
                out.append(f"banner still shown: {b.get('text')!r}")
            elif want is not False and not (b.get("visible") and b.get("text") == want):
                out.append(f"banner {b.get('text')!r} (shown {bool(b.get('visible'))}), expected {want!r}")
        elif key == "no_whoami_html":
            n = (obs["whoami"] or {}).get("i_elements")
            if n != 0:
                out.append(f"typed text became {n} i element(s) inside who-am-I")
        elif key == "no_list_html":
            n = sum(int(x.get("html_elements") or 0) for x in obs["rows"])
            if n:
                out.append(f"typed text became {n} b or i element(s) inside the list")
        else:
            out.append(f"unknown expectation {key!r}")
    return out, []


def _is_api(url: str, origin: str) -> bool:
    u = urllib.parse.urlsplit(url or "")
    return fac.origin_of(url or "") == origin and (u.path == "/api/items" or bool(API_ITEM_RE.fullmatch(u.path)))


def api_failures(log: dict, origin: str) -> list[str]:
    """/api/items requests that failed: a network error (no answer) or a 5xx answer."""
    out = [f"{f.get('method')} {urllib.parse.urlsplit(f.get('url') or '').path}: {f.get('error')}"
           for f in log.get("failed") or [] if _is_api(f.get("url"), origin)]
    out += [f"{x.get('method')} {urllib.parse.urlsplit(x.get('url') or '').path}: HTTP {x.get('status')}"
            for x in log.get("responses") or [] if _is_api(x.get("url"), origin) and (x.get("status") or 0) >= 500]
    return out


def traffic_findings(requests: list[dict], websockets: list[dict], origin: str) -> list[str]:
    """Requests outside the kit's traffic policy (gates.traffic, F3)."""
    out = []
    for r in requests:
        url, method = r.get("url") or "", r.get("method")
        u = urllib.parse.urlsplit(url)
        if u.scheme in ("data", "blob", "about"):
            continue
        if fac.origin_of(url) != origin:
            out.append(f"request outside the origin: {method} {url}")
        elif u.query:
            out.append(f"same-origin request with a query: {method} {url}")
        elif method == "GET" and u.path in GET_PATHS:
            continue
        elif method == "POST" and u.path == "/api/items":
            continue
        elif method in ("PATCH", "DELETE") and API_ITEM_RE.fullmatch(u.path):
            continue
        else:
            out.append(f"same-origin request outside the kit's paths and methods: {method} {url}")
    for w in websockets:
        out.append(f"websocket: {w.get('url')}")
    return out


def unpinned_refs(refs: list[str], origin: str, pins: dict) -> list[str]:
    """Same-origin files the "/" page asks for that the profile does not pin (favicon.svg when linked)."""
    known = {"/", "/index.html"} | {"/" + n for n in pins}
    out = []
    for url in refs or []:
        u = urllib.parse.urlsplit(url)
        if u.scheme in ("data", "blob", "about") or fac.origin_of(url) != origin:
            continue
        if u.path not in known or u.query:
            out.append(url)
    return out


def judge_row(row: dict, obs, action_error: str | None, new_log: dict, origin: str, w: dict) -> dict:
    """One browser row: FAIL on what the page showed wrong, on page errors, dialogs, crashes, popups, or a
    failed /api/items request outside D-2..D-4; BLOCKED when an observation is missing and nothing failed;
    and apart from it the traffic gate's findings while the row ran."""
    reasons, missing = compare_row(row["expected"], obs, w)
    if action_error:
        reasons.insert(0, f"action could not be done: {action_error}")
    reasons += fac.error_findings(new_log)
    failures = api_failures(new_log, origin)
    notes = []
    if failures and row["id"] in OUTAGE_ROWS:
        notes = [f"expected while the server is down: {x}" for x in failures]
    elif failures:
        reasons += [f"failed /api/items request outside D-2..D-4: {x}" for x in failures]
    traffic = fac.reference_findings((obs or {}).get("resource_refs") or [] if isinstance(obs, dict) else [], origin)
    traffic += traffic_findings(new_log.get("requests") or [], new_log.get("websockets") or [], origin)
    status = "FAIL" if reasons else "BLOCKED" if missing else "PASS"
    return {"status": status, "reasons": reasons + missing, "traffic": traffic, "notes": notes}


def traffic_gate(r: dict) -> dict:
    """The kit's traffic gate, apart from the rows: FAIL on anything outside the policy; PASS only when the
    observers were on before the first navigation and every row ran with nothing outside it; otherwise
    NOT CHECKED."""
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
    elif (r.get("observers") or {}).get("before_first_navigation") and rows == ROW_IDS:
        status = "PASS"
    else:
        status = "NOT CHECKED"
    return {"status": status, "first_seen": first, "findings": findings, "rows_observed": rows}


def pin_result(got, pins: dict, origin: str) -> dict:
    """A pin check's result from what the browser fetched: pins and "/" (first_app_check's comparators), plus
    same-origin files the page asks for that are not pinned."""
    if not isinstance(got, dict) or got.get("error"):
        return {"ok": False, "error": (got or {}).get("error") if isinstance(got, dict) else repr(got)[:300],
                "context_closed": (got or {}).get("closed") if isinstance(got, dict) else None}
    fetched = {name: fac.hashed(f) for name, f in (got.get("files") or {}).items()}
    root = fac.hashed(got["root"]) if got.get("root") else None
    res = fac.pin_stage(pins, fetched, root, origin, got.get("final_url"))
    res["refs"] = got.get("refs") or []
    res["unpinned_refs"] = unpinned_refs(res["refs"], origin, pins)
    res["api_requests_held_back"] = got.get("api_blocked") or []
    res["context_closed"] = got.get("closed")
    res["ok"] = res["ok"] and not res["unpinned_refs"]
    return res


def list_record(steps: list[dict], w: dict) -> dict:
    """The saved list, exactly: E-6's rows before the restart, and R-2's, R-3's and D-6's after it."""
    by_id = {s["id"]: s for s in steps}

    def rec(rid):
        s = by_id.get(rid)
        obs = (s or {}).get("observed")
        if not s or not isinstance(obs, dict) or not isinstance(obs.get("rows"), list):
            return None
        rows = seen_rows(obs, w)
        return {"row": rid, "context": s.get("ctx"), "rows": rows, "sha256": canon_sha256(rows), "status": s["status"]}

    before = rec("E-6")
    after = [x for x in (rec("R-2"), rec("R-3"), rec("D-6")) if x]
    for x in after:
        x["equal_to_before"] = bool(before) and x["rows"] == before["rows"]
    return {"before_restart": before, "after": after,
            "note": "rows as [text, added by, ticked] read from the rendered page; sha256 of the rows as compact "
                    "JSON (ensure_ascii false)"}


def final_verdict(r: dict) -> tuple[str, str]:
    """The receipt's verdict: (PASS|FAIL|REFUSED|BLOCKED, why)."""
    problems = (r.get("profile") or {}).get("problems")
    if problems:
        return "REFUSED", "profile not valid, browser not contacted: " + "; ".join(problems)
    if r.get("runner_error") and not r.get("steps"):
        return "BLOCKED", f"runner: {r['runner_error']}"
    reach = r.get("reach") or {}
    if reach.get("error"):
        return "BLOCKED", f"app not reached: {reach['error']}"
    pins = r.get("pins") or {}
    if not pins.get("ok"):
        bad = [f["file"] for f in pins.get("files") or [] if not f.get("match")]
        if pins.get("root") and not pins["root"].get("match"):
            bad.append('"/" (must be the pinned index.html)')
        bad += [f"{u} (asked for by the page, not pinned)" for u in pins.get("unpinned_refs") or []]
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
    blocked = [s for s in steps if s["status"] == "BLOCKED"]
    if blocked:
        return "BLOCKED", f"{blocked[0]['id']}: " + "; ".join(blocked[0]["reasons"])
    if r.get("runner_error"):
        return "BLOCKED", f"runner stopped the journey: {r['runner_error']}"
    if [s["id"] for s in steps] != ROW_IDS or any(s["status"] != "PASS" for s in steps):
        return "BLOCKED", "not every row was observed"
    if r.get("late_findings"):
        return "FAIL", "after the last row: " + "; ".join(r["late_findings"])
    if not (r.get("cleanup") or {}).get("confirmed"):
        return "BLOCKED", "cleanup not confirmed: " + json.dumps(r.get("cleanup"))
    shots = {x.get("after") for x in r.get("screenshots") or []}
    if shots != set(SHOTS):
        return "BLOCKED", f"screenshots missing: {sorted(set(SHOTS) - shots)}"
    return "PASS", f"all {len(ROW_IDS)} rows observed as the kit expects (browser rows and host steps)"


# ---------------------------------------------------------------- browser code (playwright-mcp)


def _js(template: str, **values) -> str:
    for key, value in values.items():
        template = template.replace(f"__{key}__", json.dumps(value))
    return template


SETUP = r"""async (page) => {
  const browser = page.context().browser(); const t = () => new Date().toISOString();
  const W = __WORDING__; const ORIGIN = __ORIGIN__; const OPTS = __OPTS__;
  const norm = (s) => String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
  const log = {requests: [], responses: [], failed: [], pageerrors: [], console: [], dialogs: [], websockets: [],
    popups: [], crashes: [], serviceworkers: []};
  const fs = {log, seen: {}, users: {}}; page.__fs = fs;
  const observers_at = t(); const contexts = {};
  for (const name of ['A', 'B', 'C']) {
    const ctx = await browser.newContext(OPTS); const u = {name, ctx, inflight: 0, p: null}; fs.users[name] = u;
    ctx.on('request', r => { u.inflight++; log.requests.push({t: t(), ctx: name, method: r.method(), url: r.url(),
      type: r.resourceType(), navigation: r.isNavigationRequest()}); });
    ctx.on('requestfinished', () => { u.inflight = Math.max(0, u.inflight - 1); });
    ctx.on('requestfailed', r => { u.inflight = Math.max(0, u.inflight - 1); log.failed.push({t: t(), ctx: name,
      method: r.method(), url: r.url(), error: (r.failure() || {}).errorText || null}); });
    ctx.on('response', r => log.responses.push({t: t(), ctx: name, method: r.request().method(), url: r.url(),
      status: r.status()}));
    ctx.on('serviceworker', w => log.serviceworkers.push({t: t(), ctx: name, url: w.url()}));
    ctx.on('page', pg => { if (u.p && pg !== u.p) log.popups.push({t: t(), ctx: name, url: pg.url()}); });
    const p = await ctx.newPage(); u.p = p;
    p.on('pageerror', e => log.pageerrors.push({t: t(), ctx: name, message: String(e && e.message || e).slice(0, 500)}));
    p.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') log.console.push({t: t(), ctx: name,
      type: m.type(), text: m.text().slice(0, 500)}); });
    p.on('dialog', d => { log.dialogs.push({t: t(), ctx: name, type: d.type(), message: d.message().slice(0, 300)});
      d.dismiss().catch(() => {}); });
    p.on('websocket', w => log.websockets.push({t: t(), ctx: name, url: w.url()}));
    p.on('crash', () => log.crashes.push({t: t(), ctx: name}));
    const st = await ctx.storageState();
    contexts[name] = {created_at: t(), first_url: p.url(), cookies: st.cookies.length, storage_origins: st.origins.length};
  }
  fs.drain = () => { const out = {}; for (const [k, v] of Object.entries(log)) { const from = fs.seen[k] || 0;
    out[k] = v.slice(from); fs.seen[k] = v.length; } return out; };
  const one = async (loc, what) => { const n = await loc.count(); if (n !== 1) throw new Error(what + ': ' + n + ' found');
    return loc; };
  fs.act = async (u, a) => {
    const p = u.p;
    if (a.do === 'open') { await p.goto(ORIGIN + '/', {waitUntil: 'load', timeout: 20000}); return; }
    if (a.do === 'reload') { await p.reload({waitUntil: 'load', timeout: 20000}); return; }
    if (a.do === 'name') {
      await (await one(p.getByRole('textbox', {name: W.name_textbox, exact: true}), 'textbox ' + W.name_textbox)).click({timeout: 5000});
      await p.keyboard.type(a.text);
      await (await one(p.getByRole('button', {name: W.name_button, exact: true}), 'button ' + W.name_button)).click({timeout: 5000});
      return;
    }
    if (a.do === 'add') {
      await (await one(p.getByRole('textbox', {name: W.item_textbox, exact: true}), 'textbox ' + W.item_textbox)).click({timeout: 5000});
      if (a.clear) { await p.keyboard.press('Control+A'); await p.keyboard.press('Backspace'); }
      await p.keyboard.type(a.text);
      if (a.submit === 'enter') await p.keyboard.press('Enter');
      else await (await one(p.getByRole('button', {name: W.add_button, exact: true}), 'button ' + W.add_button)).click({timeout: 5000});
      return;
    }
    if (a.do === 'tick' || a.do === 'untick') {
      await (await one(p.getByRole('checkbox', {name: a.item, exact: true}), 'checkbox ' + a.item)).click({timeout: 5000});
      return;
    }
    if (a.do === 'delete') {
      const name = W.delete_button.replace('{item}', a.item);
      await (await one(p.getByRole('button', {name, exact: true}), 'button ' + name)).click({timeout: 5000});
      return;
    }
    throw new Error('unknown action ' + a.do);
  };
  fs.settle = async (u) => {
    const t0 = Date.now(); let quiet = 0; let polls = 0;
    while (Date.now() - t0 < 15000) {
      await u.p.waitForTimeout(100); polls++;
      let busy = true;
      try { busy = await u.p.evaluate((add) => { if (document.readyState !== 'complete' || document.querySelector('[aria-busy="true"]')) return true;
        const b = document.getElementById('add-button');
        return !!(b && b.offsetParent !== null && b.innerText.replace(/\s+/g, ' ').trim() !== add); }, W.add_button); }
      catch (e) { busy = true; }
      if (u.inflight === 0 && !busy) { quiet++; if (quiet >= 3) return {ms: Date.now() - t0, polls, timed_out: false}; }
      else quiet = 0;
    }
    return {ms: Date.now() - t0, polls, timed_out: true, inflight: u.inflight};
  };
  const rowfn = (li) => {
    const norm = (s) => String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
    const byIds = (ids) => norm(String(ids || '').split(/\s+/).filter(Boolean).map(id => {
      const e = document.getElementById(id); return e ? e.textContent : ''; }).join(' '));
    const cb = li.querySelector('input[type=checkbox]'); let text = ''; let name_from = 'none';
    if (cb && cb.getAttribute('aria-labelledby')) { text = byIds(cb.getAttribute('aria-labelledby')); name_from = 'aria-labelledby'; }
    else if (cb && cb.getAttribute('aria-label')) { text = norm(cb.getAttribute('aria-label')); name_from = 'aria-label'; }
    else if (cb && cb.labels && cb.labels.length) { text = norm([...cb.labels].map(l => l.textContent).join(' ')); name_from = 'label'; }
    const byEl = li.querySelector('.item-by-name');
    return {text, name_from, desc: cb ? byIds(cb.getAttribute('aria-describedby')) : '',
      by_name_element: byEl ? byEl.textContent : null, checked: !!(cb && cb.checked),
      html_elements: li.querySelectorAll('b,i').length, visible_text: norm(li.innerText).slice(0, 400)};
  };
  const domfn = (W) => {
    const norm = (s) => String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
    const vis = (e) => !!e && (e.checkVisibility ? e.checkVisibility({opacityProperty: true, visibilityProperty: true})
      : e.getClientRects().length > 0);
    const who = document.getElementById('whoami'); const whoName = document.getElementById('whoami-name');
    const msg = document.getElementById('item-msg'); const ban = document.getElementById('banner');
    const body_text = document.body ? norm(document.body.innerText) : '';
    const banText = ban && vis(ban) ? norm(ban.innerText) : '';
    return {
      whoami: {present: !!who, visible: vis(who), name: whoName ? whoName.textContent : null,
        line: who && vis(who) ? norm(who.innerText) : '', i_elements: who ? who.querySelectorAll('i').length : 0},
      message: {present: !!msg, visible: vis(msg), text: msg && vis(msg) ? norm(msg.innerText) : ''},
      banner: {present: !!ban, visible: banText !== '', text: banText},
      empty_text_visible: body_text.includes(W.empty_text), body_text: body_text.slice(0, 2000),
      resource_refs: [...document.querySelectorAll(
        'link[href],script[src],img[src],iframe[src],source[src],video[src],audio[src],embed[src],object[data]')]
        .filter(e => !(e.tagName === 'LINK' && /^(alternate|canonical|author|help|license|next|prev|search)$/i.test(e.rel)))
        .map(e => e.href || e.src || e.data).filter(Boolean)};
  };
  fs.observe = async (u) => {
    const p = u.p; await p.waitForTimeout(300);
    const ctl = async (loc) => { const n = await loc.count(); const o = {count: n, visible: false, enabled: false};
      if (n === 1) { o.visible = await loc.isVisible(); o.enabled = await loc.isEnabled(); } return o; };
    const headings = (await p.getByRole('heading').allInnerTexts()).map(norm);
    const name_textbox = await ctl(p.getByRole('textbox', {name: W.name_textbox, exact: true}));
    const name_button = await ctl(p.getByRole('button', {name: W.name_button, exact: true}));
    const itl = p.getByRole('textbox', {name: W.item_textbox, exact: true}); const item_textbox = await ctl(itl);
    if (item_textbox.count === 1) item_textbox.value = await itl.inputValue();
    const add_button = await ctl(p.getByRole('button', {name: W.add_button, exact: true}));
    const items = p.getByRole('listitem').filter({has: p.getByRole('checkbox')}); const n = await items.count();
    const rows = []; for (let i = 0; i < n; i++) { const it = items.nth(i); const row = await it.evaluate(rowfn);
      // the browser's own accessible-name lookup must find this row's checkbox by the text read above
      row.named = row.text ? (await it.getByRole('checkbox', {name: row.text, exact: true}).count()) === 1 : false;
      rows.push(row); }
    const dom = await p.evaluate(domfn, W);
    return Object.assign({at: t(), url: p.url(), headings, name_textbox, name_button, item_textbox, add_button, rows}, dom);
  };
  return {observers_at, browser_version: browser.version(), contexts, requests_before_navigation: log.requests.length,
    distinct_contexts: new Set(Object.values(fs.users).map(x => x.ctx)).size};
}"""

ROW = r"""async (page) => {
  const fs = page.__fs; const u = fs.users[__CTX__]; const acts = __ACTS__; const t = () => new Date().toISOString();
  const res = {started: t(), acts: []};
  for (const a of acts) {
    const one = {do: a.do, started: t()};
    try { await fs.act(u, a); } catch (e) { one.error = String(e && e.message || e).split('\n')[0].slice(0, 300); }
    one.settle = await fs.settle(u); one.ended = t(); res.acts.push(one);
    if (one.error) { res.action_error = a.do + ': ' + one.error; break; }
  }
  res.ended = t();
  try { res.obs = await fs.observe(u); } catch (e) { res.observe_error = String(e && e.message || e).split('\n')[0].slice(0, 300); }
  res.log = fs.drain();
  return res;
}"""

DRAIN = "async (page) => page.__fs.drain()"
KEEPALIVE = "async (page) => ({at: new Date().toISOString(), contexts: page.context().browser().contexts().length})"
SHOT = "async (page) => (await page.__fs.users[__CTX__].p.screenshot({type: 'png'})).toString('base64')"

CLOSE = r"""async (page) => {
  const fs = page.__fs; const browser = page.context().browser(); const out = {contexts: {}};
  for (const [name, u] of Object.entries(fs.users)) { let error = null;
    try { await u.ctx.close(); } catch (e) { error = String(e).slice(0, 300); }
    out.contexts[name] = {error, page_closed: u.p.isClosed(), context_still_in_browser: browser.contexts().includes(u.ctx)}; }
  out.at = new Date().toISOString(); out.other_contexts_left = browser.contexts().filter(c => c !== page.context()).length;
  return out;
}"""

# A pin check in a context of its own, every /api/ request held back (aborted before it is sent).
PIN = r"""async (page) => {
  const browser = page.context().browser(); const ctx = await browser.newContext(__OPTS__); const blocked = []; const out = {};
  try {
    await ctx.route(u => u.pathname.startsWith('/api/'), route => { blocked.push({method: route.request().method(),
      url: route.request().url()}); return route.abort(); });
    const p = await ctx.newPage(); let r = null;
    try { r = await p.goto(__ORIGIN__ + '/', {waitUntil: 'load', timeout: 20000}); }
    catch (e) { out.error = String(e && e.message || e).split('\n')[0].slice(0, 300); }
    if (!out.error) {
      out.final_url = p.url(); out.status = r ? r.status() : null;
      if (r) { try { out.root = {status: r.status(), content_type: r.headers()['content-type'] || null, url: r.url(),
        b64: (await r.body()).toString('base64')}; } catch (e) { out.root = {error: String(e && e.message || e).slice(0, 200)}; } }
      out.files = await p.evaluate(async (names) => { const res = {};
        for (const n of names) { try { const r = await fetch(new URL(n, location.origin + '/').href, {cache: 'no-store'});
          const b = new Uint8Array(await r.arrayBuffer()); let s = ''; for (let i = 0; i < b.length; i += 8192)
            s += String.fromCharCode.apply(null, b.subarray(i, i + 8192));
          res[n] = {status: r.status, content_type: r.headers.get('content-type'), b64: btoa(s), url: r.url}; }
        catch (e) { res[n] = {error: String(e).slice(0, 200)}; } } return res; }, __NAMES__);
      out.refs = await p.evaluate(() => [...document.querySelectorAll(
        'link[href],script[src],img[src],iframe[src],source[src],video[src],audio[src],embed[src],object[data]')]
        .filter(e => !(e.tagName === 'LINK' && /^(alternate|canonical|author|help|license|next|prev|search)$/i.test(e.rel)))
        .map(e => e.href || e.src || e.data).filter(Boolean));
    }
  } finally {
    out.api_blocked = blocked;
    try { await ctx.close(); } catch (e) { out.close_error = String(e).slice(0, 200); }
    out.closed = !browser.contexts().includes(ctx);
  }
  return out;
}"""

# After the host's stop: the origin must give no HTTP answer at all (QA's ruling: port closed = 000). Any answer,
# a 5xx included, means something still listens there.
DOWN = r"""async (page) => {
  const browser = page.context().browser(); const ctx = await browser.newContext(__OPTS__); const out = {at: new Date().toISOString()};
  try {
    await ctx.route(u => u.pathname.startsWith('/api/'), route => route.abort());
    const p = await ctx.newPage();
    try { const r = await p.goto(__ORIGIN__ + '/', {waitUntil: 'load', timeout: 15000}); out.status = r ? r.status() : null;
      out.down = false; }
    catch (e) { out.error = String(e && e.message || e).split('\n')[0].slice(0, 300); out.down = /net::ERR_/.test(out.error); }
  } finally {
    try { await ctx.close(); } catch (e) { out.close_error = String(e).slice(0, 200); }
    out.closed = !browser.contexts().includes(ctx);
  }
  return out;
}"""


def setup_js(target: dict) -> str:
    return _js(SETUP, WORDING=target["wording"], ORIGIN=target["origin"], OPTS=CONTEXT_OPTS)


def row_js(row: dict) -> str:
    return _js(ROW, CTX=row["ctx"], ACTS=row["acts"])


def pin_js(target: dict) -> str:
    return _js(PIN, OPTS=CONTEXT_OPTS, ORIGIN=target["origin"], NAMES=list(target["pins"]))


def down_js(target: dict) -> str:
    return _js(DOWN, OPTS=CONTEXT_OPTS, ORIGIN=target["origin"])


# ---------------------------------------------------------------- the check


def new_receipt(label: str, target: dict | None) -> dict:
    t = target or {}
    r: dict = {"label": label, "journey": "shared", "kit_id": t.get("kit_id"), "kit_sha256": t.get("kit_sha256"),
               "origin": t.get("origin"), "checker_sha256": fac.sha256(pathlib.Path(fac.__file__).read_bytes()),
               "shared_module_sha256": fac.sha256(pathlib.Path(__file__).read_bytes()), "started_at": fac.now(),
               "context": {"viewport": fac.VIEWPORT, "locale": fac.LOCALE, "timezone": fac.TIMEZONE},
               "settle": SETTLE_RULE, "steps": [], "steps_attempted": 0, "browser_contact": False,
               "kit_not_checked": t.get("kit_not_checked"), "not_checked_here": list(NOT_CHECKED_HERE)}
    if target:
        r["profile"] = {"source": t["source"], "sha256": t["profile_sha256"], "wording": t["wording"],
                        "users": t["users"], "host_wait_minutes": t["host_wait_minutes"]}
        r["build"] = dict(t["build"], server_bytes="attested by the host's record (H-1), not checked: a browser "
                          "cannot see the server's code")
        for key in ("control_note", "control_hooks"):
            if t.get(key):
                r["profile"][key] = t[key]
    return r


def refuse_profile(text: str, problems: list[str], out: pathlib.Path, label: str) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    r = new_receipt(label, None)
    r["profile"] = {"source": "input", "sha256": fac.sha256(text.encode()), "problems": problems}
    fac.say(f"[{label}] profile not valid; the browser is not contacted: {'; '.join(problems)}")
    return finish(r, out)


async def check_profile(browser_url: str, text: str | None, out: pathlib.Path, label: str,
                        budget_s: float = LIVE_BUDGET_S) -> dict:
    target, problems = parse_shared_profile(text)
    if problems:
        return refuse_profile(text or "", problems, out, label)
    return await check_target(browser_url, target, out, label, out / "host", budget_s)


async def probe_session(browser_url: str, code: str):
    """One browser call in an MCP session of its own, closed after it: the pin checks and the down probe, never
    through the journey's contexts A, B and C (QA's hosting ruling)."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(browser_url) as (rd, wr, _):
        async with ClientSession(rd, wr) as s:
            await s.initialize()
            try:
                return fac.mcp_result(await s.call_tool("browser_run_code_unsafe", {"code": code}))
            finally:
                await s.call_tool("browser_close", {})


async def check_target(browser_url: str, target: dict, out: pathlib.Path, label: str, host_dir: pathlib.Path,
                       budget_s: float, hooks: dict | None = None) -> dict:
    """Stages A-D against one accepted target; writes out/receipt.json, out/summary.md, the screenshots."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    out.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + budget_s
    r = new_receipt(label, target)
    if host_dir.exists() and any(host_dir.iterdir()):
        r["runner_error"] = f"{host_dir} is not empty: a host receipt must come after the check asks for it"
        return finish(r, out)
    host_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(host_dir, 0o777)  # the host side (another user on the machine) writes its receipts here
    r["host_dir"] = str(host_dir)

    async def call(s, code):
        return fac.mcp_result(await s.call_tool("browser_run_code_unsafe", {"code": code}))

    fac.say(f"[{label}] A: open {target['origin']}/ and fetch {', '.join(target['pins'])} in the browser")
    r["browser_contact"] = True
    try:
        got = await probe_session(browser_url, pin_js(target))
    except Exception as exc:  # noqa: BLE001 - the browser service itself: BLOCKED, not an app result
        r["runner_error"] = f"stage A: {exc.__class__.__name__}: {str(exc)[:400]}"
        return finish(r, out)
    pins = pin_result(got, target["pins"], target["origin"])
    if pins.get("error"):
        r["reach"] = {"error": pins["error"]}
        fac.say(f"[{label}] A: not reached: {pins['error']}")
        return finish(r, out)
    r["reach"] = {"status": got.get("status"), "final_url": got.get("final_url")}
    r["pins"] = pins
    for f in pins["files"]:
        fac.say(f"[{label}] A: {f['file']} served {f['served_sha256']} ({f['served_bytes']} B) "
                f"{'matches' if f['match'] else 'DOES NOT MATCH'} pin {f['pinned_sha256'][:12]}...")
    fac.say(f'[{label}] A: "/" {"matches" if pins["root"]["match"] else "DOES NOT MATCH"} the index.html pin; '
            f"page refs {pins['refs']}; not pinned: {pins['unpinned_refs'] or 'none'}; /api/ requests held back: "
            f"{len(pins['api_requests_held_back'])}")
    if not pins["ok"]:
        fac.say(f"[{label}] A: REFUSED before any row")
        return finish(r, out)

    try:
        async with streamablehttp_client(browser_url) as (rd, wr, _):
            async with ClientSession(rd, wr) as s:
                await s.initialize()
                try:
                    await journey(s, call, r, target, out, label, host_dir, deadline, hooks or {}, browser_url)
                finally:
                    await cleanup(s, call, r, label)
    except Exception as exc:  # noqa: BLE001
        r.setdefault("runner_error", f"stage B-D: {exc.__class__.__name__}: {str(exc)[:400]}")
    return finish(r, out)


def _short(rows) -> str:
    if not isinstance(rows, list):
        return repr(rows)
    return "; ".join(f"{(t if len(t or '') <= 24 else t[:12] + '...(' + str(len(t)) + ')')} by {b} "
                     f"[{'x' if c else ' '}]" for t, b, c in rows) or "(none)"


async def journey(s, call, r: dict, target: dict, out: pathlib.Path, label: str, host_dir: pathlib.Path,
                  deadline: float, hooks: dict, browser_url: str) -> None:
    origin, w = target["origin"], target["wording"]
    setup = await call(s, setup_js(target))
    ctxs = setup["contexts"]
    r["observers"] = {"attached_at": setup["observers_at"], "requests_before_navigation": setup["requests_before_navigation"],
                      "before_first_navigation": setup["requests_before_navigation"] == 0
                      and all(c["first_url"] == "about:blank" for c in ctxs.values())}
    r["browser"] = {"version": setup["browser_version"]}
    r["isolation"] = {"contexts": ctxs, "distinct_contexts": setup["distinct_contexts"],
                      "how": "three browser contexts made by browser.newContext in one session: separate cookies, "
                             "storage and cache by the browser's design; each empty when made"}
    fac.say(f"[{label}] B: contexts {json.dumps(ctxs)}, Chromium {setup['browser_version']}")
    r["log"], r["screenshots"] = {}, []
    try:
        for row in shared_rows(w, target["users"]):
            if row.get("host"):
                step = await host_row(s, call, r, row, target, host_dir, deadline, label, browser_url)
                r["steps"].append(step)
                if step["status"] != "PASS":
                    break
                continue
            res = await call(s, row_js(row))
            if not isinstance(res, dict):
                raise RuntimeError(f"{row['id']}: the browser returned {repr(res)[:200]}")
            obs = res.get("obs")
            if hooks.get("drop_observation") == row["id"] and isinstance(obs, dict):
                obs.pop("rows", None)  # control K-MISSING-OBSERVATION only
            new = res.get("log") or {}
            fac.merge_log(r["log"], new)
            v = judge_row(row, obs, res.get("action_error"), new, origin, w)
            if res.get("observe_error"):
                v["reasons"].append(f"observation failed: {res['observe_error']}")
            r["steps_attempted"] += 1
            r["steps"].append({"id": row["id"], "kind": "browser", "ctx": row["ctx"], "action": row["action"],
                               "expected": row["expected"], "acts": res.get("acts"), "action_started": res.get("started"),
                               "action_ended": res.get("ended"), "observed": obs, "status": v["status"],
                               "reasons": v["reasons"], "traffic": v["traffic"], "notes": v["notes"]})
            seen = seen_rows(obs, w) if isinstance(obs, dict) and isinstance(obs.get("rows"), list) else None
            fac.say(f"[{label}] B: {row['id']} ({row['ctx']}) {v['status']}: rows {_short(seen)}"
                    + (f" -- {'; '.join(v['reasons'])}" if v["reasons"] else "")
                    + (f" -- traffic gate: {'; '.join(v['traffic'])}" if v["traffic"] else "")
                    + (f" -- {'; '.join(v['notes'])}" if v["notes"] else ""))
            if v["status"] != "PASS" or v["traffic"]:
                break
            if row["id"] in SHOTS:
                png = base64.b64decode(await call(s, _js(SHOT, CTX="A")))
                name = SHOTS[row["id"]]
                (out / name).write_bytes(png)
                r["screenshots"].append({"file": name, "after": row["id"], "context": "A", "taken_at": fac.now(),
                                         "bytes": len(png), "sha256": fac.sha256(png), "viewport": fac.VIEWPORT})
                fac.say(f"[{label}] B: screenshot {name} ({len(png)} B)")
    finally:
        new = await call(s, DRAIN)
        fac.merge_log(r["log"], new or {})
        late_traffic = traffic_findings((new or {}).get("requests") or [], (new or {}).get("websockets") or [], origin)
        late = late_traffic + fac.error_findings(new or {})
        if late:
            r["late_findings"] = late
        if late_traffic:
            r["late_traffic"] = late_traffic


async def host_row(s, call, r: dict, row: dict, target: dict, host_dir: pathlib.Path, deadline: float,
                   label: str, browser_url: str) -> dict:
    """A host step: ask for it in host_dir, keep the contexts open while waiting, read the receipt, then probe
    the origin in a separate session: after a start the served files are pinned again; after a stop the origin
    must give no HTTP answer."""
    rid = row["id"]
    wait_s = min(target["host_wait_minutes"] * 60, deadline - time.monotonic() - RESERVE_S)
    step = {"id": rid, "kind": "host", "host_action": row["host"], "action": row["action"], "expected": row["expected"],
            "traffic": [], "notes": []}
    if wait_s <= 0:
        step.update(status="BLOCKED", reasons=["no time left in the run to wait for the host"])
        return step
    asked = time.time()
    waiting = {"row": rid, "host_action": row["host"], "action": row["action"], "expected": row["expected"],
               "origin": target["origin"], "since": fac.now(), "wait_seconds": int(wait_s),
               "receipt_file": str(host_dir / f"{rid}.json"), "receipt_format": RECEIPT_FORMAT,
               "write": "write the receipt to a temporary name in this folder, then rename it to receipt_file"}
    wf = host_dir / f"WAITING-{rid}.json"
    wf.write_text(json.dumps(waiting, indent=1))
    os.chmod(wf, 0o666)
    step.update(waiting_file=str(wf), asked_at=waiting["since"])
    fac.say(f"[{label}] host: {rid} asked ({row['host']}); waiting up to {int(wait_s)} s for {waiting['receipt_file']}")
    f = host_dir / f"{rid}.json"
    t0 = time.monotonic()
    last_keep = t0
    raw, rec, problem = None, None, None
    while time.monotonic() - t0 < wait_s:
        if f.exists():
            raw = f.read_bytes()
            rec, problem = parse_host_receipt(raw, rid)
            if problem == "host receipt is not JSON":  # still being written: read once more
                await asyncio.sleep(1)
                raw = f.read_bytes()
                rec, problem = parse_host_receipt(raw, rid)
            if not problem and f.stat().st_mtime < asked - 1:
                problem = "host receipt is older than the check's request"
            break
        if time.monotonic() - last_keep >= 20:
            await call(s, KEEPALIVE)
            last_keep = time.monotonic()
        await asyncio.sleep(0.5)
    step.update(waited_s=round(time.monotonic() - t0, 1), receipt=rec,
                receipt_sha256=fac.sha256(raw) if raw is not None else None, answered_at=fac.now())
    if raw is None:
        step.update(status="BLOCKED", reasons=[f"no host receipt within {int(wait_s)} s"])
    elif problem:
        step.update(status="BLOCKED", reasons=[problem])
    elif not rec["done"]:
        step.update(status="BLOCKED", reasons=[f"the host could not do it: {rec.get('note') or '(no note)'}"])
    elif rec.get("exit_code") not in (None, 0):
        step.update(status="BLOCKED", reasons=[f"the stopped app exited {rec['exit_code']}, not 0 (QA's ruling: a "
                                               "stop counts only with exit 0)"])
    elif row["host"] in ("restart", "start"):
        probe = pin_result(await probe_session(browser_url, pin_js(target)), target["pins"], target["origin"])
        step["probe"] = probe
        if probe.get("error") or not probe.get("ok"):
            step.update(status="BLOCKED", reasons=["after the host step the served files do not match the pins or the "
                                                   f"origin does not answer: {probe.get('error') or 'pins'}"])
        else:
            step.update(status="PASS", reasons=[])
    else:
        probe = await probe_session(browser_url, down_js(target))
        step["probe"] = probe
        if not (isinstance(probe, dict) and probe.get("down")):
            step.update(status="BLOCKED", reasons=[f"after the host's stop the origin still answers: {probe!r}"[:300]])
        else:
            step.update(status="PASS", reasons=[])
    r["host_state_at_end"] = {"after": rid, "host_action": row["host"], "status": step["status"]}
    fac.say(f"[{label}] host: {rid} {step['status']} after {step['waited_s']} s"
            + (f" -- {'; '.join(step['reasons'])}" if step["reasons"] else "") + f"; receipt {json.dumps(rec)}")
    return step


async def cleanup(s, call, r: dict, label: str) -> None:
    c: dict = {}
    try:
        if "observers" in r:
            c["contexts"] = await call(s, CLOSE)
        await s.call_tool("browser_close", {})
        c["browser_close"] = "ok"
    except Exception as exc:  # noqa: BLE001
        c["error"] = f"{exc.__class__.__name__}: {str(exc)[:300]}"
    got = (c.get("contexts") or {}).get("contexts") or {}
    # Only our own three contexts count: playwright-mcp's sessions share one browser, so another run's context may
    # be open there at the same time (other_contexts_left is a note).
    c["confirmed"] = bool(c.get("browser_close") == "ok" and set(got) == {"A", "B", "C"}
                          and all(not x.get("error") and x.get("page_closed") and not x.get("context_still_in_browser")
                                  for x in got.values()))
    r["cleanup"] = c
    fac.say(f"[{label}] D: cleanup {'confirmed' if c['confirmed'] else 'NOT confirmed'}: {json.dumps(c)}")


def finish(r: dict, out: pathlib.Path) -> dict:
    r["finished_at"] = fac.now()
    done = {s["id"] for s in r["steps"]}
    r["not_checked"] = [x for x in ROW_IDS if x not in done]
    log = r.get("log") or {}
    r["traffic"] = {
        "requests": len(log.get("requests") or []),
        "outside_or_unexpected": traffic_findings(log.get("requests") or [], log.get("websockets") or [], r["origin"]),
        "critical_errors": fac.error_findings(log),
        "api_failures": api_failures(log, r["origin"]) if r.get("origin") else [],
        "console_notes": log.get("console") or [],
        "failed_requests": log.get("failed") or [],
    }
    wording = (r.get("profile") or {}).get("wording") or KIT_WORDING
    r["list_record"] = list_record(r["steps"], wording)
    r["traffic_gate"] = traffic_gate(r)
    r["verdict"], r["why"] = final_verdict(r)
    (out / "receipt.json").write_text(json.dumps(r, indent=1, ensure_ascii=False))
    (out / "summary.md").write_text(summary_md(r))
    fac.say(f"[{r['label']}] VERDICT {r['verdict']}: {r['why']}")
    return r


def summary_md(r: dict) -> str:
    lines = [f"# first_app_check, shared journey: {r['label']}", "", f"Verdict: **{r['verdict']}**: {r['why']}", "",
             f"Kit {r['kit_id']} (SHA256 {r['kit_sha256']}). Origin {r['origin']}. Checker SHA256 "
             f"{r['checker_sha256']}; shared module SHA256 {r['shared_module_sha256']}. {r['started_at']} to "
             f"{r['finished_at']}.", ""]
    p = r.get("profile") or {}
    if p.get("problems"):
        lines += [f"Profile (SHA256 {p['sha256']}) REFUSED; the browser was not contacted:", ""]
        lines += [f"- {x}" for x in p["problems"]] + [""]
    else:
        b = r.get("build") or {}
        lines += [f"Profile SHA256 {p.get('sha256')}; users {json.dumps(p.get('users'), ensure_ascii=False)}; wording "
                  f"{json.dumps(p.get('wording'), ensure_ascii=False)}." + (f" {p['control_note']}." if p.get("control_note")
                                                                             else ""), "",
                  f"Build: commit {b.get('commit')}, SHA256SUMS digest {b.get('sha256sums_sha256')}; server bytes "
                  f"{b.get('server_bytes')}.", ""]
    lines += [f"Browser contacted: {'yes' if r.get('browser_contact') else 'no'}. Settle: {r.get('settle')}.", ""]
    if r.get("isolation"):
        lines += [f"Contexts: {json.dumps(r['isolation']['contexts'])}; distinct: "
                  f"{r['isolation']['distinct_contexts']}.", ""]
    lines += ["## Served files", "", "| file | pinned | served | bytes | status | match |", "|---|---|---|---|---|---|"]
    pins = r.get("pins") or {}
    for f in pins.get("files") or []:
        lines.append(f"| {f['file']} | {f['pinned_sha256'][:16]}... | {(f['served_sha256'] or '-')[:16]}... | "
                     f"{f['served_bytes']} | {f['status']} | {'yes' if f['match'] else 'NO'} |")
    if pins.get("root"):
        f = pins["root"]
        lines.append(f"| / (as index.html) | {f['pinned_sha256'][:16]}... | {(f['served_sha256'] or '-')[:16]}... | "
                     f"{f['served_bytes']} | {f['status']} | {'yes' if f['match'] else 'NO'} |")
    if pins:
        lines += ["", f"Page refs: {pins.get('refs')}; not pinned: {pins.get('unpinned_refs') or 'none'}; /api/ "
                      f"requests held back during the pin check: {len(pins.get('api_requests_held_back') or [])}."]
    lines += ["", "## Rows", "", "| row | where | result | rows seen [text by name, ticked] | notes |",
              "|---|---|---|---|---|"]
    w = p.get("wording") or KIT_WORDING
    for s in r["steps"]:
        if s["kind"] == "host":
            seen = f"host receipt {json.dumps(s.get('receipt'), ensure_ascii=False)}"
            where = "host"
        else:
            o = s.get("observed")
            seen = _short(seen_rows(o, w)) if isinstance(o, dict) and isinstance(o.get("rows"), list) else "(no rows)"
            where = s["ctx"]
        notes = "; ".join(s["reasons"] + s.get("notes", []) + [f"traffic: {x}" for x in s.get("traffic") or []]) or "-"
        lines.append(f"| {s['id']} | {where} | {s['status']} | {seen.replace('|', '/')} | {notes.replace('|', '/')} |")
    for sid in r["not_checked"]:
        lines.append(f"| {sid} | | NOT CHECKED | | |")
    lr = r.get("list_record") or {}
    lines += ["", "## The list before and after the restart", ""]
    if lr.get("before_restart"):
        lines.append(f"- before (E-6, A): {_short(lr['before_restart']['rows'])}; sha256 {lr['before_restart']['sha256']}")
    for x in lr.get("after") or []:
        lines.append(f"- {x['row']} ({x['context']}): sha256 {x['sha256']}; equal to before: "
                     f"{'yes' if x['equal_to_before'] else 'NO'}")
    if not lr.get("before_restart"):
        lines.append("- not reached")
    g = r["traffic_gate"]
    lines += ["", "## Traffic gate", "", f"**{g['status']}**" + (f", first seen at {g['first_seen']}" if g["first_seen"]
                                                                else "")
              + f"; rows observed: {', '.join(g['rows_observed']) or 'none'}. Requests are observed, not blocked.", ""]
    lines += [f"- {x}" for x in g["findings"]]
    t = r["traffic"]
    lines += ["", "## Traffic and errors", "", f"Requests seen: {t['requests']}.",
              f"Outside the policy: {t['outside_or_unexpected'] or 'none'}.",
              f"Critical errors: {t['critical_errors'] or 'none'}.",
              f"Failed /api/items requests: {t['api_failures'] or 'none'}.",
              f"Console errors/warnings (notes): {[c['text'] for c in t['console_notes']] or 'none'}.", "",
              f"Screenshots: {[x['file'] for x in r.get('screenshots') or []] or 'none'}.",
              f"Cleanup: {json.dumps(r.get('cleanup'))}.", "",
              "## NOT CHECKED (the kit's list; not waived)", ""]
    lines += [f"- {x}" for x in r.get("kit_not_checked") or ["(no kit: the profile was refused)"]]
    lines += ["", "## Not checked by this check (QA's or the host's)", ""] + [f"- {x}" for x in NOT_CHECKED_HERE] + [""]
    if r.get("runner_error"):
        lines.append(f"Runner error: {r['runner_error']}")
    return "\n".join(lines) + "\n"


async def live(args, out: pathlib.Path) -> int:
    if (out / "receipt.json").exists():
        raise SystemExit(f"{out}/receipt.json exists: one live run per folder (no retry-until-green)")
    r = await check_profile(args.browser, args.profile, out, "live")
    lr = r.get("list_record") or {}
    print(json.dumps({"mode": "live", "journey": "shared", "verdict": r["verdict"], "why": r["why"],
                      "rows": {s["id"]: s["status"] for s in r["steps"]} | {x: "NOT CHECKED" for x in r["not_checked"]},
                      "pins_ok": (r.get("pins") or {}).get("ok"),
                      "screenshots": [x["file"] for x in r.get("screenshots") or []],
                      "list_equal_after_restart": [x["equal_to_before"] for x in lr.get("after") or []],
                      "cleanup_confirmed": (r.get("cleanup") or {}).get("confirmed"),
                      "traffic_gate": r["traffic_gate"]["status"], "profile": r["profile"]["source"],
                      "browser_contact": r["browser_contact"], "host_dir": r.get("host_dir"),
                      "receipt": str(out / "receipt.json")}), flush=True)
    return fac.EXIT[r["verdict"]]


# ---------------------------------------------------------------- controls: the synthetic shared server


class Store:
    """The synthetic server's list: a JSON file in the data folder (kept across restarts), or memory only."""

    def __init__(self, path: pathlib.Path | None):
        self.path, self.lock = path, threading.Lock()
        self.mem = {"next_id": 1, "items": []}

    def _load(self) -> dict:
        if self.path is None:
            return self.mem
        if not self.path.exists():
            return {"next_id": 1, "items": []}
        return json.loads(self.path.read_text())

    def _save(self, d: dict) -> None:
        if self.path is None:
            self.mem = d
            return
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(d))
        os.replace(tmp, self.path)

    def items(self) -> list[dict]:
        with self.lock:
            return self._load()["items"]

    def add(self, text: str, added_by: str) -> dict:
        with self.lock:
            d = self._load()
            item = {"id": d["next_id"], "text": text, "added_by": added_by, "done": False}
            d["next_id"] += 1
            d["items"].append(item)
            self._save(d)
            return item

    def set_done(self, item_id: int, done: bool) -> dict | None:
        with self.lock:
            d = self._load()
            for item in d["items"]:
                if item["id"] == item_id:
                    item["done"] = done
                    self._save(d)
                    return item
            return None

    def delete(self, item_id: int, keep: bool = False) -> bool:
        with self.lock:
            d = self._load()
            found = any(x["id"] == item_id for x in d["items"])
            if found and not keep:
                d["items"] = [x for x in d["items"] if x["id"] != item_id]
                self._save(d)
            return found


STATIC = {"/": ("index.html", "text/html; charset=utf-8"), "/index.html": ("index.html", "text/html; charset=utf-8"),
          "/style.css": ("style.css", "text/css; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/favicon.svg": ("favicon.svg", "image/svg+xml")}


class Handler(http.server.BaseHTTPRequestHandler):
    """HTTP/1.0, one request per connection, so a stopped server is really gone for the browser."""

    def log_message(self, *args):  # noqa: D401 - silence the access log
        pass

    def log_request(self, code="-", size="-"):
        self.server.hits.append(f"{self.command} {self.path} {code}")

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json")

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"null")
        except json.JSONDecodeError:
            return None

    def _item_id(self) -> int | None:
        m = re.fullmatch(r"/api/items/([0-9]+)", self.path)
        return int(m.group(1)) if m else None

    def do_GET(self):  # noqa: N802 - http.server's names
        if self.path in STATIC:
            name, ctype = STATIC[self.path]
            return self._send(200, (self.server.site / name).read_bytes(), ctype)
        if self.path == "/api/items":
            return self._json(200, {"items": self.server.store.items()})
        return self._json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if self.path != "/api/items":
            return self._json(404, {"error": "not found"})
        b = self._body()
        if not (isinstance(b, dict) and isinstance(b.get("text"), str) and isinstance(b.get("added_by"), str)):
            return self._json(400, {"error": "text and added_by are needed"})
        added_by = "" if self.server.variant == "author_missing" else b["added_by"]
        return self._json(201, {"item": self.server.store.add(b["text"], added_by)})

    def do_PATCH(self):  # noqa: N802
        item_id, b = self._item_id(), self._body()
        if item_id is None or not (isinstance(b, dict) and isinstance(b.get("done"), bool)):
            return self._json(404 if item_id is None else 400, {"error": "not found" if item_id is None else "done"})
        item = self.server.store.set_done(item_id, b["done"])
        return self._json(200, {"item": item}) if item else self._json(404, {"error": "That item was already deleted."})

    def do_DELETE(self):  # noqa: N802
        item_id = self._item_id()
        if item_id is None:
            return self._json(404, {"error": "not found"})
        if self.server.store.delete(item_id, keep=self.server.variant == "delete_unsaved"):
            return self._json(200, {"deleted": item_id})
        return self._json(404, {"error": "That item was already deleted."})


class SyntheticServer:
    """The controls' shared-list server: the fixture page and /api/items, stopped and started on the same port
    and data folder by the control host. variant: file (clean), memory_only, delete_unsaved, author_missing."""

    def __init__(self, site: pathlib.Path, data_dir: pathlib.Path, variant: str = "file"):
        self.site, self.data_dir, self.variant = site, data_dir, variant
        self.port, self.srv, self.hits, self.starts = 0, None, [], 0

    def start(self) -> None:
        store = Store(None if self.variant == "memory_only" else self.data_dir / "items.json")
        srv = http.server.ThreadingHTTPServer(("0.0.0.0", self.port), Handler)
        srv.daemon_threads = True
        srv.site, srv.store, srv.variant, srv.hits = self.site, store, self.variant, self.hits
        self.port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.srv = srv
        self.starts += 1

    def stop(self) -> None:
        if self.srv:
            self.srv.shutdown()
            self.srv.server_close()
            self.srv = None

    def port_open(self) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=1):
                return True
        except OSError:
            return False

    def host_action(self, kind: str) -> dict:
        """What a host does for a host row, confirmed the way the kit asks (port closed, listening again)."""
        rec = {"action": kind, "port": self.port, "data_dir": "(memory only)" if self.variant == "memory_only"
               else str(self.data_dir)}
        if kind in ("restart", "stop"):
            self.stop()
            rec["port_closed"] = not self.port_open()
        if kind in ("restart", "start"):
            self.start()
            rec["listening"] = self.port_open()
        rec["done"] = rec.get("port_closed", True) and rec.get("listening", True)
        rec["starts"] = self.starts
        return rec


def materialize(variant: str, root: pathlib.Path, outside: str = "") -> pathlib.Path:
    """One control's site: fixtures/shared_app with app.js's VARIANT (and OUTSIDE) lines set."""
    site = root / "site"
    site.mkdir(parents=True)
    for name in ("index.html", "style.css", "favicon.svg"):
        shutil.copy(FIXTURE / name, site / name)
    src = (FIXTURE / "app.js").read_text()
    for line, new in (('const VARIANT = "clean";', f"const VARIANT = {json.dumps(variant)};"),
                      ('const OUTSIDE = "";', f"const OUTSIDE = {json.dumps(outside)};")):
        if src.count(line) != 1:
            raise SystemExit(f"fixtures/shared_app/app.js: the line {line!r} is not there exactly once")
        src = src.replace(line, new)
    (site / "app.js").write_text(src)
    return site


async def control_host(host_dir: pathlib.Path, server: SyntheticServer, refuse: tuple = ()) -> None:
    """The controls' host: answers each WAITING file by stopping/starting the synthetic server, as Ops would
    the real one; refuse names rows it says it cannot do (K-NO-RESTART)."""
    handled: set[str] = set()
    while True:
        for wf in sorted(host_dir.glob("WAITING-*.json")):
            rid = wf.name[len("WAITING-"):-len(".json")]
            if rid in handled:
                continue
            handled.add(rid)
            ask = json.loads(wf.read_text())
            if rid in refuse:
                rec = {"done": False, "note": "control K-NO-RESTART: this host has no way to stop and start the server"}
            else:
                did = await asyncio.to_thread(server.host_action, ask["host_action"])
                rec = {"done": did.pop("done"), "note": json.dumps(did)}
            rec = {"row": rid, "by": "control host: the check's own synthetic server", "at": fac.now(), **rec}
            tmp = host_dir / f".{rid}.json.tmp"
            tmp.write_text(json.dumps(rec))
            os.replace(tmp, host_dir / f"{rid}.json")
        await asyncio.sleep(0.2)


# Controls and what each must get: (verdict, first row that FAILs or is BLOCKED, traffic gate). The K- names
# are the kit's checkerControls; A- are Architecture's own. variant: the page's app.js; server: the server's.
CONTROLS = [
    {"case": "K-CLEAN", "variant": "clean", "expect": ("PASS", None, "PASS")},
    {"case": "K-LOCAL-ONLY", "variant": "local_only", "expect": ("FAIL", "J-7", "NOT CHECKED")},
    {"case": "K-NAME-FORGOTTEN", "variant": "name_forgotten", "expect": ("FAIL", "J-3", "NOT CHECKED")},
    {"case": "K-TICK-LOCAL", "variant": "tick_local", "expect": ("FAIL", "J-11", "NOT CHECKED")},
    {"case": "K-DELETE-LOCAL", "variant": "clean", "server": "delete_unsaved", "expect": ("FAIL", "J-11", "NOT CHECKED")},
    {"case": "K-BLANK-ADDED", "variant": "blank_added", "expect": ("FAIL", "E-1", "NOT CHECKED")},
    {"case": "K-201-ACCEPTED", "variant": "accept_201", "expect": ("FAIL", "E-2", "NOT CHECKED")},
    {"case": "K-200-REFUSED", "variant": "refuse_200", "expect": ("FAIL", "E-3", "NOT CHECKED")},
    {"case": "K-HTML-RENDERED", "variant": "html_rendered", "expect": ("FAIL", "E-4", "NOT CHECKED")},
    {"case": "K-MEMORY-ONLY", "variant": "clean", "server": "memory_only", "expect": ("FAIL", "R-2", "NOT CHECKED")},
    {"case": "K-OPTIMISTIC", "variant": "optimistic", "expect": ("FAIL", "D-2", "NOT CHECKED")},
    {"case": "K-OUTSIDE-FONT", "variant": "outside_font", "expect": ("FAIL", None, "FAIL at J-1")},
    {"case": "K-WRONG-PIN", "variant": "clean", "wrong_pin": "app.js", "expect": ("REFUSED", None, "NOT CHECKED")},
    {"case": "K-NO-RESTART", "variant": "clean", "refuse": ("R-1",), "expect": ("BLOCKED", "R-1", "NOT CHECKED")},
    {"case": "K-MISSING-OBSERVATION", "variant": "clean", "hooks": {"drop_observation": "J-11"},
     "expect": ("BLOCKED", "J-11", "NOT CHECKED")},
    {"case": "A-AUTHOR-MISSING", "variant": "clean", "server": "author_missing", "expect": ("FAIL", "J-4", "NOT CHECKED")},
    {"case": "A-AUTHOR-VIEWER", "variant": "author_viewer", "expect": ("FAIL", "J-7", "NOT CHECKED")},
    {"case": "A-BAD-PROFILE", "variant": "clean", "profile": "served_origin", "expect": ("REFUSED", None, "NOT CHECKED")},
]


def site_pins(site: pathlib.Path) -> dict:
    return {n: hashlib.sha256((site / n).read_bytes()).hexdigest() for n in REQUIRED_PINS + OPTIONAL_PINS}


def serve_ip(browser_host: str, given: str | None) -> str:
    if given:
        return given
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect((socket.gethostbyname(browser_host), 80))
        return probe.getsockname()[0]
    finally:
        probe.close()


async def run_control(args, case: dict, out: pathlib.Path, tmp: pathlib.Path, ip: str) -> dict:
    base = tmp / case["case"]
    outside = f"http://{ip}:9/font.woff2" if case["variant"] == "outside_font" else ""
    site = materialize(case["variant"], base, outside)
    data = base / "data"
    data.mkdir(mode=0o700)
    server = SyntheticServer(site, data, case.get("server", "file"))
    server.start()
    origin = f"http://{ip}:{server.port}"
    case_out, label = out / case["case"], f"control {case['case']}"
    host_dir = case_out / "host"
    pins = site_pins(site)
    if case.get("wrong_pin"):
        pins[case["wrong_pin"]] = "0" * 64
    host = asyncio.create_task(control_host(host_dir, server, case.get("refuse", ())))
    try:
        if case.get("profile") == "served_origin":
            text = json.dumps(default_shared_profile(origin=origin, pins=pins))
            r = await check_profile(args.browser, text, case_out, label, CONTROL_BUDGET_S)
        else:
            profile = default_shared_profile(pins=pins)
            profile["host_wait_minutes"] = 1
            target, problems = parse_shared_profile(json.dumps(profile))
            if problems:
                raise SystemExit(f"control profile refused: {problems}")
            target["control_note"] = (f"control: the profile's origin {target['origin']} replaced, after the profile was "
                                      f"accepted, by the synthetic server's {origin}")
            target["host_wait_minutes"] = CONTROL_HOST_WAIT_S / 60
            if case.get("hooks"):
                target["control_hooks"] = case["hooks"]
            target["origin"] = origin
            r = await check_target(args.browser, target, case_out, label, host_dir, CONTROL_BUDGET_S, case.get("hooks"))
    finally:
        host.cancel()
        try:
            await host
        except asyncio.CancelledError:
            pass
        await asyncio.to_thread(server.stop)
    stopped_at = next((s["id"] for s in r["steps"] if s["status"] in ("FAIL", "BLOCKED")), None)
    got = (r["verdict"], stopped_at)
    gate = r["traffic_gate"]["status"] + (f" at {r['traffic_gate']['first_seen']}"
                                          if r["traffic_gate"]["status"] == "FAIL" else "")
    api_hits = [h for h in server.hits if " /api/" in h]
    ok = got == case["expect"][:2] and gate == case["expect"][2]
    if r["verdict"] == "REFUSED":
        ok = ok and r["steps_attempted"] == 0 and not api_hits
    if (r.get("profile") or {}).get("problems"):
        ok = ok and not r["browser_contact"] and not server.hits  # a refused profile reaches nothing
    if case["case"] == "K-CLEAN":
        lr = r["list_record"]
        ok = ok and bool(lr["before_restart"]) and len(lr["after"]) == 3 and all(x["equal_to_before"] for x in lr["after"])
    res = {"case": case["case"], "expected": list(case["expect"][:2]), "got": list(got),
           "traffic_gate": {"expected": case["expect"][2], "got": gate}, "why": r["why"],
           "steps_attempted": r["steps_attempted"], "browser_contact": r["browser_contact"],
           "server_requests": len(server.hits), "api_requests": len(api_hits), "server_starts": server.starts, "ok": ok}
    fac.say(f"control {case['case']}: expected {case['expect']}, got {got + (gate,)}, server requests "
            f"{len(server.hits)} (api {len(api_hits)}), starts {server.starts}: {'OK' if ok else 'WRONG'}")
    return res


async def controls(args, out: pathlib.Path) -> int:
    ip = serve_ip(urllib.parse.urlparse(args.browser).hostname, args.serve_ip)
    results = []
    with tempfile.TemporaryDirectory(prefix="first-app-shared-controls-") as tmp:
        for case in CONTROLS:
            results.append(await run_control(args, case, out, pathlib.Path(tmp), ip))
    summary = {"mode": "controls_shared", "all_ok": all(x["ok"] for x in results), "cases": results,
               "checker_sha256": fac.sha256(pathlib.Path(fac.__file__).read_bytes()),
               "shared_module_sha256": fac.sha256(pathlib.Path(__file__).read_bytes())}
    (out / "controls.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps({"mode": "controls_shared", "all_ok": summary["all_ok"],
                      "verdicts": {x["case"]: x["got"] for x in results},
                      "traffic_gates": {x["case"]: x["traffic_gate"]["got"] for x in results}, "out": str(out)}),
          flush=True)
    return 0 if summary["all_ok"] else 1


def print_profile() -> int:
    print(json.dumps(default_shared_profile(), indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover - run through first_app_check.py
    raise SystemExit("run first_app_check.py (--mode controls_shared, or --mode live with a shared profile)")
