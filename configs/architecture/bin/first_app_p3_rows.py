"""Project 3 rows (#125): what the checker does on each row and what passes, from QA #32 and Product's FINAL v3.1.

H-125-ROWS-1 (written before this file): the provisional PENDING-SPEC rows (#124) cannot judge QA's canonical rows,
because their ids, people, data, actions and texts differ (for example C/U/L/N/X/S/W rows, Pat and Quinn, a profile
wording table). Change: one module that carries QA's 34 checker-judged non-host rows and four host rows word for
word (ids, engines, inputs, actions, oracles), Product's exact texts M1-M20/A1-A9 and test strings, the two run
orders and the expected data states, plus pure judges over typed observations. Expected: the clean synthetic page
passes every row in both engines and each planted fault fails its named row; a judge that passes a planted fault,
or a row that differs from specs-rows.json, proves this wrong.

Source of truth (precedence 1, read-only, never changed here): QA's coherent #32 delivery in
/home/shinelay/qa-lab/project3-critical-journey/specs/ (SPEC below), whose rows bind Product's FINAL v3.1
(FINAL_SHA256). Literals are copied here, so nothing is read at run time; tests compare them with the spec files.
Nothing here judges host evidence: host rows go through Ops' operation and the receiving-approved client only.
"""

from __future__ import annotations

SPEC = {
    "dir": "/home/shinelay/qa-lab/project3-critical-journey/specs",
    "ARCH-EXTENSION-SPEC.md": "49247ff8bdbd70e8998ccf8c9e9d9eeb1c78d10c5c0f468aeb753d4a2c420e5f",
    "specs-rows.json": "d7690a0e4fded4a733cb69f561b6eedd61805818474c59af9822e36de161d010",
    "SHA256SUMS": "dfb3f8e1ce914161a7437ae17b87dc8539a55a6609b7c7926773c4250e316626",
    "HOST-STEPS.md": "0c399eaed326ce2e3cd8e908e23432edb0b581911ca3289f5ea204ee3b4fd61f",
}
FINAL = "Product FINAL v3.1 (team-project3-proposal.md)"
FINAL_SHA256 = "c2a5ddbd924512e8888c6830bb7ae28141543576095ac9873508d500f55ef1c1"
JOURNEY = "p3-final-v3.1"  # the value of the profile's journey_p3 key

# ---------------------------------------------------------------- Product's exact texts (FINAL S3, S4)
TEXT = {
    "heading": "To-do list",
    "name_box": "Your name", "save_name": "Save name", "cancel": "Cancel", "change_name": "Change name",
    "item_box": "New item", "add": "Add", "try_again": "Try again", "yes_delete": "Yes, delete", "keep": "Keep",
    "list": "To-do items",
    "m1": "Type an item first.",
    "m2": "Too long: {n} characters. The limit is 200.",
    "m4": "Type your name first.",
    "m5": "Too long: {n} characters. The limit is 50.",
    "m6": "Can't reach the server. Your change could not be confirmed. Reload before retrying.",
    "m8": "That item was already deleted.",
    "m9": "Can't reach the server. The list couldn't be loaded.",
    "m10": "Loading the list\u2026",
    "m11": "No items yet. Add the first one above.",
    "m12": "Trying again\u2026",
    "m13": "Adding\u2026",
    "m16": "Shown next to the items you add. Up to 50 characters. This browser remembers it.",
    "m17": "Up to 200 characters.",
    "m18": "Delete \"{item}\"?",
    "m19": "Saving\u2026",
    "m20": "Deleting\u2026",
    "a1": "Item added.", "a2": "Item deleted.", "a3": "List loaded.", "a4": "Name saved.", "a5": "Adding\u2026",
    "a6": "Change saved.", "a7": "Loading the list again\u2026", "a8": "Saving\u2026", "a9": "Deleting\u2026",
    "who_prefix": "You are ", "added_by": "added by ",
    "delete_name": "Delete {item}", "yes_name": "Yes, delete {item}", "keep_name": "Keep {item}",
}
VIEWPORT_META = "width=device-width, initial-scale=1"
CONFIGURED_WIDTH = {"chromium": 1280, "webkit": 390}

# ---------------------------------------------------------------- QA's test strings and limits (specs-rows.json)
U = {
    "U01": "\u041f\u0440\u0438\u0432\u0435\u0442, \u043c\u0438\u0440",
    "U02": "\u039a\u03b1\u03bb\u03b7\u03bc\u03ad\u03c1\u03b1 \u03ba\u03cc\u03c3\u03bc\u03b5",
    "U03": "\u4f60\u597d\uff0c\u4e16\u754c",
    "U04": "\u3053\u3093\u306b\u3061\u306f\u3001\u30ab\u30bf\u30ab\u30ca\u6f22\u5b57",
    "U05": "\u0928\u092e\u0938\u094d\u0924\u0947 \u0926\u0941\u0928\u093f\u092f\u093e",
    "U06": "\u0645\u0631\u062d\u0628\u0627 \u0628\u0627\u0644\u0639\u0627\u0644\u0645",
    "U07": "\u05e9\u05dc\u05d5\u05dd \u05e2\u05d5\u05dc\u05dd",
    "U08": "\u05e9\u05dc\u05d5\u05dd Ana 123",
    "U09": "caf\u00e9",
    "U10": "cafe\u0301",
    "U11": "\U0001f469\U0001f3fd\u200d\U0001f4bb",
    "U12": "\U0001f1ef\U0001f1f5",
}
LIMITS = {
    "L1": ("\u4e2d", 200, "", True), "L2": ("\u4e2d", 201, "", False),
    "L3": ("a", 196, "\U0001f469\U0001f3fd\u200d\U0001f4bb", True),
    "L4": ("a", 197, "\U0001f469\U0001f3fd\u200d\U0001f4bb", False),
    "L5": ("\U0001f600", 200, "", True), "L6": ("\U0001f600", 201, "", False),
    "N3": ("\u0416", 50, "", True), "N4": ("\u0416", 51, "", False),
}
L = {k: rep * n + suffix for k, (rep, n, suffix, _ok) in LIMITS.items()}
N1, N2, N3, N4 = U["U06"], U["U07"], L["N3"], L["N4"]
PEOPLE = {"A": "Ana", "B": "Ben", "C": "<i>Cy</i>", "L": "Lia", "V": "Vic"}
UNI_ADDS = [U[f"U{i:02d}"] for i in range(1, 13)] + [L[k] for k in ("L1", "L2", "L3", "L4", "L5", "L6")]

# ---------------------------------------------------------------- expected data states (specs-rows.json states)
J15 = [["Buy milk", "Ana", False], ["Call Sam", "Ben", False]]
E5 = J15 + [["y" * 200, "Ana", False], ["<b>hi</b>", "<i>Cy</i>", False]]
UNI_ROWS = ([[U[f"U{i:02d}"], N1, False] for i in range(1, 13)] + [[L[k], N1, False] for k in ("L1", "L3", "L5")]
            + [["Name check 1", N3, False], ["Name check 2", N2, False]])
E5U = E5 + UNI_ROWS
AFTER_J9 = [["Buy milk", "Ana", True], ["Water plants", "Ana", False], ["Call Sam", "Ben", False],
            ["Pay rent", "Ben", False]]
AFTER_J10 = [["Buy milk", "Ana", True], ["Call Sam", "Ben", False], ["Pay rent", "Ben", False]]
AFTER_J12 = [["Buy milk", "Ana", False], ["Call Sam", "Ben", True]]
HOLD_MS = 3000          # V3-PEND/V3-BUSY: every held request is held at least this long
VISIBLE_WITHIN_MS = 1000  # busy text visible within 1 s of the press
POLL_MS = 100             # press-to-visible polls at most this far apart
RETRY_WITHIN_MS = 10000   # CR-3: after Try again the list is back and M9 gone within 10 s
ANNOUNCE_CLEAR_MS = 5000  # A1-A9 clear after 5 s (or the next replacement)

# ---------------------------------------------------------------- rows
# acts: the actions, in order, in the row's context unless an act names ctx. observe: contexts read after the acts.
# expect: what the judge compares (see judge()). Host rows carry host=<Ops operation>; nothing here judges them.

def _state(who=None, rows=None, name_form=False, app=True, **more) -> dict:
    return dict(who=who, rows=rows, name_form=name_form, app=app, **more)


def _uni_acts() -> list[dict]:
    acts = [{"do": "open"}, {"do": "name", "text": N1, "measure": "who_dir"}]
    for text in UNI_ADDS:
        acts.append({"do": "add", "text": text, "clear": True, "measure": "add_result"})
    acts += [{"do": "clear_item"},
             {"do": "change_name", "text": N4, "measure": "name_result"},
             {"do": "cancel_name"},
             {"do": "change_name", "text": N3, "measure": "name_result"},
             {"do": "add", "text": "Name check 1", "clear": True, "measure": "add_result"},
             {"do": "change_name", "text": N2, "measure": "who_dir"},
             {"do": "add", "text": "Name check 2", "clear": True, "measure": "add_result"},
             {"do": "open", "ctx": "V"}, {"do": "name", "text": "Vic", "ctx": "V"}, {"do": "reload", "ctx": "V"}]
    return acts


def _pend_acts(item: str, busy: bool) -> list[dict]:
    """V3-PEND and V3-BUSY: hold each write >= HOLD_MS, separately; press again while held (a second Enter for Add)."""
    hold = {"hold_ms": HOLD_MS, "watch_live": busy}
    return [{"do": "reload"}] + ([{"do": "watch_live"}] if busy else []) + [
            {"do": "held", "op": "add", "item": item, **hold},
            {"do": "held", "op": "tick", "item": item, **hold},
            {"do": "held", "op": "untick", "item": item, **hold},
            {"do": "delete_open", "item": item},
            {"do": "held", "op": "confirm", "item": item, **hold},
            {"do": "reload"}]


ROWS: list[dict] = [
    {"id": "J-1", "engines": ("chromium", "webkit"), "ctx": "A", "acts": [{"do": "open"}],
     "expect": _state(name_form=True, app=False, heading=True), "plants": ["PL-30"]},
    {"id": "J-2", "engines": ("chromium", "webkit"), "ctx": "A", "acts": [{"do": "name", "text": "Ana"}],
     "expect": _state(who="Ana", rows=[], m11=True), "plants": ["CF-NO-EMPTY-TEXT"]},
    {"id": "J-3", "engines": ("chromium", "webkit"), "ctx": "A", "acts": [{"do": "reload"}],
     "expect": _state(who="Ana", rows=[]), "plants": ["K-NAME-FORGOTTEN"]},
    {"id": "J-4", "engines": ("chromium", "webkit"), "ctx": "A",
     "acts": [{"do": "add", "text": "Buy milk", "submit": "button"}],
     "expect": _state(who="Ana", rows=[["Buy milk", "Ana", False]], item_value=""),
     "plants": ["A-AUTHOR-MISSING", "PL-36"]},
    {"id": "J-5", "engines": ("chromium", "webkit"), "ctx": "A",
     "acts": [{"do": "add", "text": "Water plants", "submit": "enter"}],
     "expect": _state(who="Ana", rows=[["Buy milk", "Ana", False], ["Water plants", "Ana", False]]),
     "plants": ["CF-ENTER-NO-ADD"]},
    {"id": "J-6", "engines": ("chromium", "webkit"), "ctx": "B", "acts": [{"do": "open"}],
     "expect": _state(name_form=True, app=False), "plants": ["CF-NAME-SERVER-WIDE"]},
    {"id": "J-7", "engines": ("chromium", "webkit"), "ctx": "B", "acts": [{"do": "name", "text": "Ben"}],
     "expect": _state(who="Ben", rows=[["Buy milk", "Ana", False], ["Water plants", "Ana", False]]),
     "plants": ["K-LOCAL-ONLY", "A-AUTHOR-VIEWER"]},
    {"id": "J-8", "engines": ("chromium", "webkit"), "ctx": "B",
     "acts": [{"do": "add", "text": "Call Sam", "clear": True}, {"do": "add", "text": "Pay rent", "clear": True}],
     "expect": _state(who="Ben", rows=[["Buy milk", "Ana", False], ["Water plants", "Ana", False],
                                       ["Call Sam", "Ben", False], ["Pay rent", "Ben", False]]),
     "plants": ["CF-FIRST-AUTHOR"]},
    {"id": "J-9", "engines": ("chromium", "webkit"), "ctx": "B", "acts": [{"do": "tick", "item": "Buy milk"}],
     "expect": _state(who="Ben", rows=AFTER_J9), "plants": ["CF-TICK-REVERTS"]},
    {"id": "V3-DEL", "engines": ("chromium", "webkit"), "ctx": "B",
     "acts": [{"do": "add", "text": "Return book", "clear": True},
              {"do": "delete_open", "item": "Return book", "measure": "step"},
              {"do": "keep", "item": "Return book", "measure": "closed"},
              {"do": "reload", "ctx": "A", "measure": "rows"},
              {"do": "delete_open", "item": "Return book", "measure": "step"},
              {"do": "escape", "item": "Return book", "measure": "closed"},
              {"do": "delete_open", "item": "Return book", "measure": "step"},
              {"do": "delete_open", "item": "Water plants", "measure": "step", "closed_item": "Return book"},
              {"do": "keep", "item": "Water plants", "measure": "closed"},
              {"do": "delete_open", "item": "Return book", "measure": "step"},
              {"do": "held", "op": "confirm", "item": "Return book", "hold_ms": HOLD_MS, "watch_live": False},
              {"do": "reload", "ctx": "A", "measure": "rows"}],
     "observe": ["B", "A"],
     "expect": _state(who="Ben", rows=AFTER_J9, also={"A": AFTER_J9}),
     "plants": ["W9", "PL-09", "CF-CANCEL-DELETES", "K-DELETE-LOCAL"]},
    {"id": "J-10", "engines": ("chromium", "webkit"), "ctx": "B",
     "acts": [{"do": "delete_open", "item": "Water plants"}, {"do": "confirm", "item": "Water plants"}],
     "expect": _state(who="Ben", rows=AFTER_J10), "plants": ["CF-DELETE-HIDES-NEXT"]},
    {"id": "J-11", "engines": ("chromium", "webkit"), "ctx": "A", "acts": [{"do": "reload"}],
     "expect": _state(who="Ana", rows=AFTER_J10), "plants": ["K-TICK-LOCAL"]},
    {"id": "J-12", "engines": ("chromium", "webkit"), "ctx": "A",
     "acts": [{"do": "untick", "item": "Buy milk"}, {"do": "tick", "item": "Call Sam"},
              {"do": "delete_open", "item": "Pay rent"}, {"do": "confirm", "item": "Pay rent"}],
     "expect": _state(who="Ana", rows=AFTER_J12), "plants": ["CF-UNTICK-IGNORED"]},
    {"id": "J-13", "engines": ("chromium", "webkit"), "ctx": "B", "acts": [{"do": "reload"}],
     "expect": _state(who="Ben", rows=AFTER_J12), "plants": ["CF-UNTICK-NOT-SENT"]},
    {"id": "J-14", "engines": ("chromium", "webkit"), "ctx": "B", "acts": [{"do": "untick", "item": "Call Sam"}],
     "expect": _state(who="Ben", rows=J15), "plants": ["CF-UNTICK-CALL-SAM"]},
    {"id": "J-15", "engines": ("chromium", "webkit"), "ctx": "A", "acts": [{"do": "reload"}],
     "expect": _state(who="Ana", rows=J15), "plants": ["CF-GET-CALL-SAM-STUCK"]},
    {"id": "E-1", "engines": ("chromium", "webkit"), "ctx": "A",
     "acts": [{"do": "add", "text": "   ", "clear": True, "measure": "add_result"}],
     "expect": _state(who="Ana", rows=J15, item_msg=TEXT["m1"], posts=0), "plants": ["K-BLANK-ADDED", "PL-13"]},
    {"id": "E-2", "engines": ("chromium", "webkit"), "ctx": "A",
     "acts": [{"do": "add", "text": "x" * 201, "clear": True, "measure": "add_result"}],
     "expect": _state(who="Ana", rows=J15, item_msg=TEXT["m2"].format(n=201), posts=0),
     "plants": ["K-201-ACCEPTED"]},
    {"id": "E-3", "engines": ("chromium", "webkit"), "ctx": "A",
     "acts": [{"do": "add", "text": "y" * 200, "clear": True, "measure": "add_result"}],
     "expect": _state(who="Ana", rows=J15 + [["y" * 200, "Ana", False]], posts=1), "plants": ["K-200-REFUSED"]},
    {"id": "E-4", "engines": ("chromium", "webkit"), "ctx": "C",
     "acts": [{"do": "open"}, {"do": "name", "text": "<i>Cy</i>"}],
     "expect": _state(who="<i>Cy</i>", rows=J15 + [["y" * 200, "Ana", False]], who_markup=0),
     "plants": ["K-HTML-RENDERED"]},
    {"id": "E-5", "engines": ("chromium", "webkit"), "ctx": "C",
     "acts": [{"do": "add", "text": "<b>hi</b>", "clear": True}],
     "expect": _state(who="<i>Cy</i>", rows=E5, row_markup=0, who_markup=0), "plants": ["W1", "PL-15"]},
    {"id": "E-6", "engines": ("chromium", "webkit"), "ctx": "A", "acts": [{"do": "reload"}],
     "expect": _state(who="Ana", rows=E5, row_markup=0), "plants": ["CF-MARKUP-STRIPPED"]},
    {"id": "V3-LIMITS", "engines": ("chromium",), "ctx": "L",
     "acts": [{"do": "open", "measure": "hints"}, {"do": "type_name", "text": "Li", "measure": "hints"},
              {"do": "name", "text": "Lia", "clear": True, "measure": "hints"},
              {"do": "type_item", "text": "Milk", "measure": "hints"},
              {"do": "open_change_name", "measure": "hints"},
              {"do": "type_name", "text": "Lia2", "clear": True, "measure": "hints"},
              {"do": "cancel_name", "measure": "hints"}, {"do": "clear_item"}],
     "expect": _state(who="Lia", rows=E5, posts=0), "plants": ["W8"]},
    {"id": "V3-PEND", "engines": ("chromium",), "ctx": "A", "acts": _pend_acts("Pending check", False),
     "expect": _state(who="Ana", rows=E5), "plants": ["W7"]},
    {"id": "V3-BUSY", "engines": ("chromium",), "ctx": "A", "acts": _pend_acts("Busy check", True),
     "expect": _state(who="Ana", rows=E5), "plants": ["W6"]},
    {"id": "UNI-UI", "engines": ("chromium", "webkit"), "ctx": "U", "acts": _uni_acts(), "observe": ["V"],
     "expect": _state(who="Vic", rows=E5U, uni=True), "plants": ["W2", "W3", "PL-14"]},
    {"id": "R-1", "engines": ("chromium",), "ctx": "A", "host": "restart", "signal": "TERM", "plants": ["H1", "H2", "PL-02"]},
    {"id": "R-2", "engines": ("chromium",), "ctx": "A", "acts": [{"do": "reload"}],
     "expect": _state(who="Ana", rows=E5U), "plants": ["K-MEMORY-ONLY", "PL-03"]},
    {"id": "R-3", "engines": ("chromium",), "ctx": "B", "acts": [{"do": "reload"}],
     "expect": _state(who="Ben", rows=E5U), "plants": ["CF-SECOND-LOAD-EMPTY"]},
    {"id": "R-1i", "engines": ("chromium",), "ctx": "A", "host": "restart", "signal": "INT", "after": [{"do": "reload"}],
     "expect": _state(who="Ana", rows=E5U), "plants": ["H3"]},
    {"id": "CR-3", "engines": ("chromium",), "ctx": "A",
     "acts": [{"do": "abort_list"}, {"do": "reload", "measure": "m9"}, {"do": "unabort"},
              {"do": "try_again", "measure": "retry"}],
     "expect": _state(who="Ana", rows=E5U, m9_gone=True), "plants": ["PL-26", "PL-42", "CF-RETRY-DEAD"]},
    {"id": "D-1", "engines": ("chromium",), "ctx": "A", "host": "crash", "plants": ["RF-NO-EXIT-D1"]},
    {"id": "D-2", "engines": ("chromium",), "ctx": "A",
     "acts": [{"do": "add", "text": "Feed cat", "clear": True, "measure": "add_result"}],
     "expect": _state(who="Ana", rows=E5U, banner=TEXT["m6"], item_msg="", item_value="Feed cat"),
     "plants": ["W5", "K-OPTIMISTIC", "PL-17", "PL-19", "PL-24", "PL-37"]},
    {"id": "D-3", "engines": ("chromium",), "ctx": "A", "acts": [{"do": "tick", "item": "Buy milk"}],
     "expect": _state(who="Ana", rows=E5U, banner=TEXT["m6"]), "plants": ["PL-39"]},
    {"id": "D-4", "engines": ("chromium",), "ctx": "A",
     "acts": [{"do": "delete_open", "item": "Call Sam"}, {"do": "confirm", "item": "Call Sam", "measure": "closed"}],
     "expect": _state(who="Ana", rows=E5U, banner=TEXT["m6"], step_closed="Call Sam"), "plants": ["PL-43", "PL-75"]},
    {"id": "D-5", "engines": ("chromium",), "ctx": "A", "host": "start", "plants": ["H5"]},
    {"id": "D-6", "engines": ("chromium",), "ctx": "A",
     "acts": [{"do": "tick", "item": "Buy milk", "measure": "tick_result"}, {"do": "untick", "item": "Buy milk"},
              {"do": "reload"}],
     "expect": _state(who="Ana", rows=E5U, banner=""), "plants": ["PL-27"]},
]
ROW = {r["id"]: r for r in ROWS}
HOST_ROWS = ("R-1", "R-1i", "D-1", "D-5")
JUDGED_ELSEWHERE = {"CR-1": "QA api_check", "API-D-1": "QA api_check", "API-D-5": "QA api_check",
                    "HOST-L": "QA runner (calibration)", "PH-1": "the WebKit run's meta row, judged in run_webkit()"}
CHROMIUM_ORDER = ["J-1", "J-2", "J-3", "J-4", "J-5", "J-6", "J-7", "J-8", "J-9", "V3-DEL", "J-10", "J-11", "J-12",
                  "J-13", "J-14", "J-15", "E-1", "E-2", "E-3", "E-4", "E-5", "E-6", "V3-LIMITS", "V3-PEND", "V3-BUSY",
                  "UNI-UI", "R-1", "R-2", "R-3", "R-1i", "CR-3", "D-1", "D-2", "D-3", "D-4", "D-5", "D-6"]
WEBKIT_ORDER = ["J-1", "J-2", "J-3", "J-4", "J-5", "J-6", "J-7", "J-8", "J-9", "V3-DEL", "J-10", "J-11", "J-12",
                "J-13", "J-14", "J-15", "E-1", "E-2", "E-3", "E-4", "E-5", "E-6", "UNI-UI"]
CONTEXTS = {"chromium": ("A", "B", "C", "L", "U", "V"), "webkit": ("A", "B", "C", "U", "V")}
# Rows the server is down for (between D-1 and D-5): failed /api/ requests are expected only here.
OUTAGE_ROWS = ("D-2", "D-3", "D-4")
PH1_RECORD = ("user_agent", "webkit_version", "viewport", "isMobile", "hasTouch", "maxTouchPoints", "image_id",
              "traffic_gate", "webkit_tree_sha256")


def order(engine: str) -> list[dict]:
    return [ROW[i] for i in (CHROMIUM_ORDER if engine == "chromium" else WEBKIT_ORDER)]


def m(key: str, **kw) -> str:
    return TEXT[key].format(**kw)


def cps(s) -> list[int] | None:
    return [ord(c) for c in s] if isinstance(s, str) else None


# ---------------------------------------------------------------- judges (pure; observations are UNTRUSTED data)

def _str(v) -> bool:
    return isinstance(v, str)


def _rows_seen(obs: dict) -> list | None:
    if not isinstance(obs, dict):
        return None
    rows = obs.get("rows")
    if not isinstance(rows, list):
        return None
    return rows


def rows_problems(obs: dict, expected: list[list], where: str) -> list[str]:
    """Exact rows: text (raw label textContent, code points), attribution, done, in order; raw, no normalising."""
    rows = _rows_seen(obs)
    if rows is None:
        return [f"{where}: rows not observed"]
    out = []
    if len(rows) != len(expected):
        out.append(f"{where}: {len(rows)} rows, expected {len(expected)}")
    for i, (seen, (text, by, done)) in enumerate(zip(rows, expected, strict=False)):  # count reported above
        if not isinstance(seen, dict):
            out.append(f"{where}: row {i + 1} unreadable")
            continue
        if seen.get("text") != text:
            out.append(f"{where}: row {i + 1} text {_show(seen.get('text'))}, expected {_show(text)}")
        if seen.get("by_name") != by:
            out.append(f"{where}: row {i + 1} .item-by-name {_show(seen.get('by_name'))}, expected {_show(by)}")
        if seen.get("desc") != TEXT["added_by"] + by:
            out.append(f"{where}: row {i + 1} checkbox description {_show(seen.get('desc'))}, "
                       f"expected {_show(TEXT['added_by'] + by)}")
        if seen.get("by_count") != 1:
            out.append(f"{where}: row {i + 1} has {seen.get('by_count')} .item-by-name elements, expected 1")
        if seen.get("checked") is not done:
            out.append(f"{where}: row {i + 1} done {seen.get('checked')}, expected {done}")
        if seen.get("name_from") not in ("label", "aria-labelledby"):
            out.append(f"{where}: row {i + 1} checkbox is not labelled by its item text ({seen.get('name_from')})")
    for i, seen in enumerate(rows[len(expected):], len(expected) + 1):
        out.append(f"{where}: unexpected row {i}: {_show(seen.get('text') if isinstance(seen, dict) else seen)}")
    return out


def _show(s) -> str:
    if not _str(s):
        return repr(s)
    if len(s) > 60:
        return f"{s[:40]!r}… ({len(s)} code points)"
    return repr(s)


def state_problems(obs, exp: dict, where: str) -> list[str]:
    if not isinstance(obs, dict):
        return [f"{where}: page not observed"]
    out = []
    if exp.get("heading") and obs.get("headings") != [TEXT["heading"]]:
        out.append(f"{where}: headings {obs.get('headings')!r}, expected one h1 {TEXT['heading']!r}")
    nf = obs.get("name_form") or {}
    if bool(nf.get("visible")) != bool(exp.get("name_form")):
        out.append(f"{where}: name form {'shown' if nf.get('visible') else 'not shown'}, expected "
                   f"{'shown' if exp.get('name_form') else 'not shown'}")
    add = obs.get("add") or {}
    if bool(add.get("box_visible")) != bool(exp.get("app")):
        out.append(f"{where}: item box {'shown' if add.get('box_visible') else 'not shown'}, expected "
                   f"{'shown' if exp.get('app') else 'not shown'}")
    if exp.get("app"):
        if add.get("button_count") != 1 or add.get("button_text") != TEXT["add"] or not add.get("button_visible"):
            out.append(f"{where}: #add-button {add.get('button_count')} found, text {add.get('button_text')!r}, "
                       f"expected one visible {TEXT['add']!r}")
    who = obs.get("who") or {}
    if exp.get("who") is not None:
        out += who_problems(who, exp["who"], where)
    if exp.get("rows") is not None:
        out += rows_problems(obs, exp["rows"], where)
    if exp.get("m11") and not obs.get("m11_visible"):
        out.append(f"{where}: M11 {TEXT['m11']!r} not shown")
    if "item_value" in exp and add.get("value") != exp["item_value"]:
        out.append(f"{where}: item box holds {_show(add.get('value'))}, expected {_show(exp['item_value'])}")
    if "item_msg" in exp and add.get("msg") != exp["item_msg"]:
        out.append(f"{where}: #item-msg {_show(add.get('msg'))}, expected {_show(exp['item_msg'])}")
    if "banner" in exp and obs.get("banner") != exp["banner"]:
        out.append(f"{where}: #banner {_show(obs.get('banner'))}, expected {_show(exp['banner'])}")
    if exp.get("row_markup") is not None and obs.get("row_markup") != exp["row_markup"]:
        out.append(f"{where}: {obs.get('row_markup')} b/i elements inside rows, expected none")
    if exp.get("who_markup") is not None and who.get("i_count") != exp["who_markup"]:
        out.append(f"{where}: {who.get('i_count')} i elements inside #whoami, expected none")
    if exp.get("m9_gone") and (obs.get("m9_visible") or obs.get("try_again_visible")):
        out.append(f"{where}: M9/Try again still shown")
    return out


def who_problems(who: dict, name: str, where: str) -> list[str]:
    out = []
    if who.get("whoami_count") != 1 or who.get("name_count") != 1:
        out.append(f"{where}: #whoami {who.get('whoami_count')} / #whoami-name {who.get('name_count')} found "
                   "(FINAL hook: one #whoami holding #whoami-name)")
        return out
    if not who.get("visible"):
        out.append(f"{where}: #whoami not visible")
    if who.get("name") != name:
        out.append(f"{where}: #whoami-name {_show(who.get('name'))}, expected {_show(name)}")
    if not _str(who.get("line")) or not who["line"].startswith(TEXT["who_prefix"] + name):
        out.append(f"{where}: who line {_show(who.get('line'))} does not start {_show(TEXT['who_prefix'] + name)}")
    if not who.get("inside"):
        out.append(f"{where}: #whoami-name is not inside #whoami")
    return out


def _acts(res: dict) -> list[dict]:
    acts = res.get("acts")
    return [a for a in acts if isinstance(a, dict)] if isinstance(acts, list) else []


def _ms(a: dict) -> dict:
    ms = a.get("measure")
    return ms if isinstance(ms, dict) else {}


def _measures(res: dict, kind: str) -> list[dict]:
    return [_ms(a) for a in _acts(res) if a.get("measure_kind") == kind]


def step_problems(ms: dict, item: str, where: str) -> list[str]:
    """V3-DEL: the open confirmation step (FINAL S4 C8, C10, C11, M18, F22)."""
    out = []
    want = m("m18", item=item)
    if ms.get("status") != want:
        out.append(f"{where}: row status {_show(ms.get('status'))}, expected M18 {_show(want)}")
    if ms.get("yes_text") != TEXT["yes_delete"] or ms.get("keep_text") != TEXT["keep"]:
        out.append(f"{where}: visible labels {ms.get('yes_text')!r}/{ms.get('keep_text')!r}, expected "
                   f"{TEXT['yes_delete']!r}/{TEXT['keep']!r}")
    if ms.get("yes_count") != 1 or ms.get("keep_count") != 1:
        out.append(f"{where}: buttons named {m('yes_name', item=item)!r}: {ms.get('yes_count')}, "
                   f"{m('keep_name', item=item)!r}: {ms.get('keep_count')}, expected one each")
    if ms.get("yes_desc") != want or ms.get("keep_desc") != want:
        out.append(f"{where}: C10/C11 descriptions {_show(ms.get('yes_desc'))}/{_show(ms.get('keep_desc'))}, "
                   f"expected M18")
    if not ms.get("yes_before_keep"):
        out.append(f"{where}: Yes, delete is not before Keep")
    if ms.get("delete_visible"):
        out.append(f"{where}: Delete still shown (C8 is replaced while the step is open)")
    if ms.get("focus") != m("keep_name", item=item):
        out.append(f"{where}: focus on {_show(ms.get('focus'))}, expected {m('keep_name', item=item)!r}")
    if ms.get("open_steps") != 1:
        out.append(f"{where}: {ms.get('open_steps')} open confirmation steps, expected exactly one")
    if ms.get("dialogs"):
        out.append(f"{where}: {ms.get('dialogs')} dialog element(s) or role=dialog/alertdialog")
    if ms.get("deletes"):
        out.append(f"{where}: {ms.get('deletes')} DELETE request(s) when opening the step, expected none")
    return out


def closed_problems(ms: dict, item: str, where: str, focus: bool = True) -> list[str]:
    out = []
    if ms.get("status") not in ("",):
        out.append(f"{where}: row status {_show(ms.get('status'))} after closing, expected empty")
    if ms.get("yes_count") or ms.get("keep_count"):
        out.append(f"{where}: Yes, delete/Keep still shown")
    if not ms.get("delete_visible"):
        out.append(f"{where}: Delete not back")
    if focus and ms.get("focus") != m("delete_name", item=item):
        out.append(f"{where}: focus on {_show(ms.get('focus'))}, expected {m('delete_name', item=item)!r}")
    if ms.get("item_present") is not True:
        out.append(f"{where}: {item!r} gone")
    return out


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def held_problems(ms: dict, op: str, item: str, where: str, busy_live: bool) -> tuple[list[str], list[str]]:
    """V3-PEND/V3-BUSY: one held write. Measured, never assumed: hold, press-to-visible, poll gaps, counts.
    Returns (FAIL reasons, BLOCKED reasons): a measurement that is not good enough is BLOCKED, not an app fault."""
    out, blocked = [], []
    if not isinstance(ms, dict) or not ms:
        return [], [f"{where}: {op} not measured"]
    if ms.get("error"):
        blocked.append(f"{where}: {op}: hold failed: {ms['error']}")
    if not _num(ms.get("hold_ms")) or ms["hold_ms"] < HOLD_MS:
        blocked.append(f"{where}: {op} held {ms.get('hold_ms')} ms, expected at least {HOLD_MS}")
    if not _num(ms.get("max_poll_gap_ms")) or ms["max_poll_gap_ms"] > POLL_MS:
        blocked.append(f"{where}: {op} polls up to {ms.get('max_poll_gap_ms')} ms apart, planned at most {POLL_MS}")
    busy = {"add": TEXT["m13"], "tick": TEXT["m19"], "untick": TEXT["m19"], "confirm": TEXT["m20"]}[op]
    v = ms.get("visible_ms")
    if v is None or v > VISIBLE_WITHIN_MS:
        out.append(f"{where}: {op}: {busy!r} visible after {v} ms, expected within {VISIBLE_WITHIN_MS} ms")
    if op != "add":
        if not ms.get("after_attribution"):
            out.append(f"{where}: {op}: busy text is not in the row's .item-status after the attribution")
        if not ms.get("aria_busy"):
            out.append(f"{where}: {op}: row not aria-busy=true while held")
        if not ms.get("aria_busy_cleared"):
            out.append(f"{where}: {op}: row still aria-busy after the response")
    if ms.get("requests") != 1:
        out.append(f"{where}: {op}: {ms.get('requests')} requests for one action and one repeat, expected exactly 1")
    if busy_live:
        live = {"add": (TEXT["a5"], TEXT["a1"]), "tick": (TEXT["a8"], TEXT["a6"]), "untick": (TEXT["a8"], TEXT["a6"]),
                "confirm": (TEXT["a9"], TEXT["a2"])}[op]
        seq = [x.get("text") for x in ms.get("announcer") or [] if isinstance(x, dict) and x.get("text")]
        if seq[:2] != list(live):
            out.append(f"{where}: {op}: #announcer said {seq!r}, expected {list(live)!r} in that order")
        late = [x for x in ms.get("live_texts") or [] if isinstance(x, dict) and x.get("text") and not x.get("region_predates")]
        if late:
            out.append(f"{where}: {op}: live region created with its text (not before it): {late[:3]!r}")
        if op != "add" and busy not in [x.get("text") for x in ms.get("row_status") or [] if isinstance(x, dict)]:
            out.append(f"{where}: {op}: row .item-status never said {busy!r}")
        c = ms.get("announce_cleared_ms")
        if not _num(c) or c > ANNOUNCE_CLEAR_MS + 1000:
            out.append(f"{where}: {op}: success announcement not cleared within about {ANNOUNCE_CLEAR_MS} ms ({c})")
    return out, blocked


def announcer_static(page_html: str | None) -> list[str]:
    """V3-BUSY: #announcer is a role=status region that exists, empty, in the page as served (it predates any text).
    Read from the pinned index.html bytes (stage A), not from an observer installed before load."""
    import html.parser

    if not isinstance(page_html, str):
        return ["V3-BUSY: the served index.html was not pinned, so #announcer's initial state is unknown"]

    class P(html.parser.HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.found, self.depth, self.text = [], 0, ""

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if self.depth:
                self.depth += 1
            elif a.get("id") == "announcer":
                self.found.append({"role": a.get("role"), "live": a.get("aria-live")})
                self.depth = 1

        def handle_endtag(self, tag):
            if self.depth:
                self.depth -= 1

        def handle_data(self, data):
            if self.depth:
                self.text += data

    p = P()
    p.feed(page_html)
    if len(p.found) != 1:
        return [f"V3-BUSY: {len(p.found)} #announcer elements in the served page, expected one"]
    if p.found[0]["role"] != "status":
        return [f"V3-BUSY: #announcer role {p.found[0]['role']!r}, expected status"]
    if p.text.strip():
        return [f"V3-BUSY: #announcer is not empty at load ({p.text.strip()[:60]!r})"]
    return []


def hints_problems(ms: dict, where: str, stage: int) -> list[str]:
    """V3-LIMITS: M16 in #name-hint whenever the name form shows; M17 in #item-hint whenever the add form shows."""
    out = []
    if ms.get("name_form_visible"):
        out += _hint(ms.get("name_hint") or {}, TEXT["m16"], "#name-hint", where)
    if ms.get("item_form_visible"):
        out += _hint(ms.get("item_hint") or {}, TEXT["m17"], "#item-hint", where)
    if stage in (0, 1, 4, 5) and not ms.get("name_form_visible"):
        out.append(f"{where}: name form not shown")
    if stage in (2, 3, 6) and not ms.get("item_form_visible"):
        out.append(f"{where}: add form not shown")
    if ms.get("posts"):
        out.append(f"{where}: {ms['posts']} POST request(s); no item may be added")
    return out


def _hint(h: dict, text: str, hook: str, where: str) -> list[str]:
    out = []
    if h.get("count") != 1 or h.get("text") != text or not h.get("visible"):
        out.append(f"{where}: {hook} {h.get('count')} found, text {_show(h.get('text'))}, visible "
                   f"{h.get('visible')}; expected one visible {text!r}")
    if not h.get("in_describedby"):
        out.append(f"{where}: {hook} not in its box's aria-describedby")
    if h.get("invalid"):
        out.append(f"{where}: box aria-invalid from the hint alone")
    return out


def uni_problems(res: dict, where: str) -> list[str]:
    """UNI-UI: each add sent (1 POST) or refused (M2, no request); names; directions; exact code points after reload."""
    out = []
    adds = _measures(res, "add_result")
    expected = UNI_ADDS + ["Name check 1", "Name check 2"]
    if len(adds) != len(expected):
        return [f"{where}: {len(adds)} adds measured, expected {len(expected)}"]
    for text, ms in zip(expected, adds, strict=True):
        ok = len(text) <= 200
        if ok and (ms.get("posts") != 1 or ms.get("msg") != ""):
            out.append(f"{where}: {_show(text)}: {ms.get('posts')} POSTs, message {_show(ms.get('msg'))}; expected 1, none")
        if not ok and (ms.get("posts") != 0 or ms.get("msg") != m("m2", n=len(text)) or ms.get("value") != text):
            out.append(f"{where}: {_show(text)}: {ms.get('posts')} POSTs, message {_show(ms.get('msg'))}, kept "
                       f"{ms.get('value') == text}; expected none, {m('m2', n=len(text))!r}, kept")
    names = _measures(res, "name_result")
    if len(names) != 2:
        out.append(f"{where}: {len(names)} name changes measured, expected 2")
    else:
        refused, n3 = names
        if refused.get("msg") != m("m5", n=51) or refused.get("who") != N1:
            out.append(f"{where}: N4 gave {_show(refused.get('msg'))}, who {_show(refused.get('who'))}; expected "
                       f"{m('m5', n=51)!r}, who unchanged")
        if n3.get("who") != N3 or n3.get("msg") != "":
            out.append(f"{where}: N3 save gave who {_show(n3.get('who'))}, message {_show(n3.get('msg'))}")
    dirs = _measures(res, "who_dir")
    if len(dirs) != 2 or [d.get("who") for d in dirs] != [N1, N2]:
        out.append(f"{where}: who under N1/N2 {[d.get('who') for d in dirs]!r}")
    for d in dirs:
        if d.get("direction") != "rtl":
            out.append(f"{where}: #whoami-name under {_show(d.get('who'))} has direction {d.get('direction')!r}, "
                       "expected rtl")
    obs = res.get("obs") if isinstance(res.get("obs"), dict) else {}
    for row in _rows_seen(obs.get("V")) or []:
        if not isinstance(row, dict):
            continue
        if row.get("text") in (U["U06"], U["U07"]) and row.get("text_direction") != "rtl":
            out.append(f"{where}: item {_show(row.get('text'))} direction {row.get('text_direction')!r}, expected rtl")
        if row.get("by_name") in (N1, N2) and row.get("by_direction") != "rtl":
            out.append(f"{where}: attributed name {_show(row.get('by_name'))} direction {row.get('by_direction')!r}, "
                       "expected rtl")
    return out


def judge(row: dict, res, engine: str, served_html: str | None = None) -> dict:
    """One browser row: PASS, FAIL (the page contradicts the oracle) or BLOCKED (no usable observation).
    Observations are untrusted data: a shape the judge cannot read is BLOCKED, never an exception or a PASS."""
    where = f"{row['id']} ({engine})"
    if not isinstance(res, dict):
        return {"status": "BLOCKED", "reasons": [f"{where}: the browser did not return an object"]}
    try:
        return _judge(row, res, engine, served_html, where)
    except Exception as exc:  # noqa: BLE001
        return {"status": "BLOCKED", "reasons": [f"{where}: observation unreadable: {type(exc).__name__}: "
                                                 f"{str(exc)[:200]}"]}


def _judge(row: dict, res: dict, engine: str, served_html: str | None, where: str) -> dict:
    rid = row["id"]
    reasons: list[str] = []
    blocked: list[str] = []
    if res.get("action_error"):
        reasons.append(f"{where}: action failed: {res['action_error']}")
    if res.get("observe_error"):
        blocked.append(f"{where}: observation failed: {res['observe_error']}")
    obs_all = res.get("obs") if isinstance(res.get("obs"), dict) else {}
    exp = row.get("expect") or {}
    ctxs = row.get("observe") or [row["ctx"]]
    main = ctxs[0]
    if main not in obs_all:
        blocked.append(f"{where}: context {main} not observed")
    else:
        reasons += state_problems(obs_all[main], exp, f"{where} {main}")
    for c, rows in (exp.get("also") or {}).items():
        if c in obs_all:
            reasons += rows_problems(obs_all[c], rows, f"{where} {c}")
        else:
            blocked.append(f"{where}: context {c} not observed")
    acts = _acts(res)
    if "posts" in exp:
        posts = sum(a.get("posts", 0) for a in acts if isinstance(a.get("posts"), int))
        if posts != exp["posts"]:
            reasons.append(f"{where}: {posts} POST request(s), expected {exp['posts']}")
    for a in acts:
        ms, kind, item = _ms(a), a.get("measure_kind"), a.get("item")
        if kind == "step":
            reasons += step_problems(ms, item, where)
            if a.get("closed_item"):
                reasons += closed_problems(ms.get("closed") or {}, a["closed_item"], where + " first step", focus=False)
        elif kind == "closed" and rid == "V3-DEL":
            reasons += closed_problems(ms, item, where)
            if ms.get("deletes"):
                reasons.append(f"{where}: {ms['deletes']} DELETE request(s) on Keep/Escape, expected none")
        elif kind == "closed" and rid == "D-4":
            if ms.get("yes_count") or ms.get("keep_count") or not ms.get("delete_visible") or ms.get("status"):
                reasons.append(f"{where}: confirmation step not closed after the failed delete")
        elif kind == "rows" and rid == "V3-DEL":
            want = AFTER_J9 + [["Return book", "Ben", False]] if a is acts[3] else AFTER_J9
            reasons += rows_problems(ms, want, where + " A after reload")
        elif kind == "held" or a.get("do") == "held":
            fails, blocks = held_problems(ms, a.get("op"), item, where, bool(a.get("watch_live")))
            reasons += fails
            blocked += blocks
        elif kind == "m9":
            if ms.get("m9_text") != TEXT["m9"] or not ms.get("try_again_visible"):
                reasons.append(f"{where}: aborted load showed {_show(ms.get('m9_text'))}, Try again "
                               f"{ms.get('try_again_visible')}; expected M9 with Try again")
            if ms.get("m11_visible") or ms.get("m10_visible"):
                reasons.append(f"{where}: aborted load shows M11/M10 (false empty or leftover loading)")
            if ms.get("aborted") is not True:
                blocked.append(f"{where}: the list GET was not aborted (abort route not hit)")
        elif kind == "retry":
            if ms.get("ms") is None or ms["ms"] > RETRY_WITHIN_MS:
                reasons.append(f"{where}: list not back within {RETRY_WITHIN_MS} ms of Try again ({ms.get('ms')})")
        elif kind == "tick_result" and rid == "D-6":
            if ms.get("patch_status") != [200]:
                reasons.append(f"{where}: PATCH statuses {ms.get('patch_status')!r}, expected [200]")
            if ms.get("banner") != "":
                reasons.append(f"{where}: M6 still shown after the tick succeeded ({_show(ms.get('banner'))})")
            if ms.get("checked") is not True:
                reasons.append(f"{where}: tick not applied")
    if rid == "V3-LIMITS":
        for stage, ms in enumerate(_measures(res, "hints")):
            reasons += hints_problems(ms, f"{where} step {stage + 1}", stage)
    if rid == "V3-DEL":
        confirm = [a for a in acts if a.get("op") == "confirm"]
        if len(confirm) != 1:
            blocked.append(f"{where}: confirm not measured")
    if rid == "V3-BUSY":
        if served_html is None:
            blocked.append(f"{where}: the served index.html was not pinned, so #announcer's initial state is unknown")
        else:
            reasons += announcer_static(served_html)
    if rid == "UNI-UI":
        reasons += uni_problems(res, where)
    if blocked and not reasons:
        return {"status": "BLOCKED", "reasons": blocked}
    return {"status": "FAIL" if reasons else "PASS", "reasons": reasons + blocked}


def ph1(engine_facts: dict, rows: list[dict], gate: dict, image: dict | None, tree: str | None) -> dict:
    """PH-1: the WebKit run's own row. Every WebKit journey/UNI-UI row passed, native UA (no override, no shims),
    exact viewport meta, measured overflow against the configured 390 px width, and the receipt fields."""
    reasons, blocked = [], []
    want = set(WEBKIT_ORDER)
    seen = {s.get("id"): s.get("status") for s in rows}
    missing = sorted(want - set(seen))
    if missing:
        blocked.append(f"PH-1: WebKit rows not run: {', '.join(missing)}")
    bad = sorted(i for i, st in seen.items() if i in want and st != "PASS")
    if bad:
        reasons.append(f"PH-1: WebKit rows not passing: {', '.join(bad)}")
    f = engine_facts or {}
    for k in ("user_agent", "webkit_version", "maxTouchPoints"):
        if f.get(k) in (None, ""):
            blocked.append(f"PH-1: {k} not recorded")
    if f.get("viewport") != {"width": 390, "height": 844} or f.get("isMobile") is not True or f.get("hasTouch") is not True:
        blocked.append(f"PH-1: context is not the configured 390x844 isMobile hasTouch ({f.get('viewport')}, "
                       f"{f.get('isMobile')}, {f.get('hasTouch')})")
    if f.get("viewport_meta") != VIEWPORT_META:
        reasons.append(f"PH-1: viewport meta {f.get('viewport_meta')!r}, expected exactly {VIEWPORT_META!r}")
    sw = f.get("scroll_width")
    if not isinstance(sw, int) or sw > 390:
        reasons.append(f"PH-1: page {sw} px wide at the configured 390 px (horizontal overflow)")
    if not gate or gate.get("status") != "PASS":
        blocked.append(f"PH-1: traffic gate {(gate or {}).get('status')}")
    if not image or image.get("status") != "PASS":
        blocked.append(f"PH-1: W1 engine image {(image or {}).get('status', 'not read')}")
    if not tree:
        blocked.append("PH-1: webkit_tree_sha256 not supplied (Security W1 addition; no guessed hash)")
    if reasons:
        return {"status": "FAIL", "reasons": reasons + blocked}
    return {"status": "BLOCKED" if blocked else "PASS", "reasons": blocked,
            "notes": ["Playwright WebKit on Linux, not a real iPhone or iOS Safari",
                      "wording 15-17 VERIFIED-PRESENT is QA's source check (FINAL lines 493/511/513), not measured here"]}


# ---------------------------------------------------------------- browser side (inlined in SETUP after the guard)
# Needs from SETUP: p3 (with log, users), T (TEXT), ORIGIN, t(). Controls are found by FINAL's roles and exact
# accessible names (S4) or FINAL's hooks (#add-button, #whoami, #whoami-name, .item-by-name, .item-status, #banner,
# #item-msg, #name-hint, #item-hint, #announcer). Presses are real taps in touch contexts, clicks otherwise; typing
# is keyboard.insertText (exact code points). No init script, no clock, no UA or touch shim.
ROWS_JS = r"""
  const norm = (s) => String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
  const pathOf = (s) => String(s).replace(/^[a-z]+:\/\/[^/]+/i, '').split(/[?#]/)[0] || '/';
  const one = async (loc, what) => { const n = await loc.count(); if (n !== 1) throw new Error(what + ': ' + n + ' found');
    return loc; };
  const role = (u, r, name) => u.p.getByRole(r, {name, exact: true});
  const box = (u, name) => one(role(u, 'textbox', name), 'textbox ' + name);
  const button = (u, name) => one(role(u, 'button', name), 'button ' + name);
  const fill = (tpl, item) => tpl.replace('{item}', item);
  p3.sent = (from, u, method) => p3.log.requests.slice(from).filter(r => r.ctx === u.name && r.method === method
    && pathOf(r.url).startsWith('/api/items')).length;
  p3.press = async (u, loc) => { if (u.touch) await loc.tap({timeout: 5000}); else await loc.click({timeout: 5000}); };
  p3.typeInto = async (u, loc, text, clear) => { await p3.press(u, loc); await loc.focus();
    if (clear) await loc.fill(''); if (text) await u.p.keyboard.insertText(text); };
  const isFocused = async (loc) => (await loc.count()) === 1 && await loc.evaluate(e => e === document.activeElement);
  const focusName = async (u) => u.p.evaluate(() => { const e = document.activeElement;
    return e ? (e.getAttribute('aria-label') || String(e.textContent || '').replace(/\s+/g, ' ').trim() || e.tagName) : null; });
  const ctl = async (loc) => { const n = await loc.count(); const o = {count: n, visible: false};
    if (n === 1) { o.visible = await loc.isVisible(); } return o; };
  // ---- the confirmation step of one row (FINAL S4 C8, C10, C11, M18, F22)
  p3.step = async (u, item) => {
    const yes = role(u, 'button', fill(T.yes_name, item)); const keep = role(u, 'button', fill(T.keep_name, item));
    const del = role(u, 'button', fill(T.delete_name, item));
    const out = {yes_count: 0, keep_count: 0};
    const y = await ctl(yes); const k = await ctl(keep); const d = await ctl(del);
    out.yes_count = y.visible ? y.count : 0; out.keep_count = k.visible ? k.count : 0; out.delete_visible = d.visible;
    const dom = await u.p.evaluate(({item}) => {
      const norm = (s) => String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
      const vis = (e) => !!e && (e.checkVisibility ? e.checkVisibility({opacityProperty: true, visibilityProperty: true})
        : e.getClientRects().length > 0);
      const li = [...document.querySelectorAll('li')].find(li => { const cb = li.querySelector('input[type=checkbox]');
        return cb && cb.labels && [...cb.labels].some(l => l.textContent === item); });
      const st = li ? li.querySelector('.item-status') : null;
      const open = [...document.querySelectorAll('button')].filter(b => vis(b) && norm(b.textContent) === 'Yes, delete').length;
      const dialogs = document.querySelectorAll('dialog, [role=dialog], [role=alertdialog]').length;
      return {item_present: !!li, status: st ? norm(st.textContent) : null, open_steps: open, dialogs};
    }, {item});
    Object.assign(out, dom);
    if (out.yes_count === 1) { out.yes_text = norm(await yes.innerText()); out.yes_desc = await yes.evaluate(e =>
      String((e.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean).map(id => document.getElementById(id))
        .filter(Boolean).map(x => x.textContent).join(' ')).replace(/\s+/g, ' ').trim()); }
    if (out.keep_count === 1) { out.keep_text = norm(await keep.innerText()); out.keep_desc = await keep.evaluate(e =>
      String((e.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean).map(id => document.getElementById(id))
        .filter(Boolean).map(x => x.textContent).join(' ')).replace(/\s+/g, ' ').trim()); }
    if (out.yes_count === 1 && out.keep_count === 1) {
      const kh = await keep.elementHandle(); out.yes_before_keep = await yes.evaluate((a, b) =>
        !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING), kh); }
    out.focus = await isFocused(keep) ? fill(T.keep_name, item) : await isFocused(del) ? fill(T.delete_name, item)
      : 'other: ' + await focusName(u);
    return out;
  };
  // ---- one held write (V3-PEND, V3-BUSY, V3-DEL's confirm): hold >= a.hold_ms, poll press-to-visible, press again
  p3.held = async (u, a) => {
    const p = u.p; const method = {add: 'POST', tick: 'PATCH', untick: 'PATCH', confirm: 'DELETE'}[a.op];
    const busyText = {add: T.m13, tick: T.m19, untick: T.m19, confirm: T.m20}[a.op];
    const r = {op: a.op, method, hold_ms: null, visible_ms: null, max_poll_gap_ms: null, polls: 0, aria_busy: false,
      after_attribution: null, requests: null};
    let holdStart = null; let holdEnd = null;
    // Security #105 R-1: only this origin's list, and pass-through by fallback(), so a control's context abort
    // route still sees every request this route does not hold.
    const match = (url) => url.origin === ORIGIN && url.pathname.startsWith('/api/items');
    const handler = async (route) => {
      if (route.request().method() !== method || holdStart !== null) return route.fallback();
      holdStart = Date.now(); await new Promise(res => setTimeout(res, a.hold_ms)); holdEnd = Date.now();
      try { await route.fallback(); } catch (e) { r.continue_error = String(e && e.message || e).slice(0, 200); }
    };
    await p.route(match, handler);
    try {
      let loc;
      if (a.op === 'add') { await p3.typeInto(u, await box(u, T.item_box), a.item, true);
        loc = await one(p.locator('#add-button'), '#add-button'); }
      else if (a.op === 'confirm') loc = await button(u, fill(T.yes_name, a.item));
      else loc = await one(role(u, 'checkbox', a.item), 'checkbox ' + a.item);
      if (a.watch_live) await p.evaluate(() => { if (window.__p3live) window.__p3live.rec.length = 0; });
      const from = p3.log.requests.length;
      const t0 = Date.now(); let last = t0; let gap = 0; let repeated = false;
      await p3.press(u, loc);
      while (Date.now() - t0 < a.hold_ms + 2000) {
        const s = await p.evaluate(({op, item, busyText}) => {
          const norm = (s) => String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
          const vis = (e) => !!e && (e.checkVisibility ? e.checkVisibility({opacityProperty: true, visibilityProperty: true})
            : e.getClientRects().length > 0);
          if (op === 'add') { const b = document.querySelectorAll('#add-button');
            return {visible: b.length === 1 && vis(b[0]) && norm(b[0].textContent) === busyText}; }
          const li = [...document.querySelectorAll('li')].find(li => { const cb = li.querySelector('input[type=checkbox]');
            return cb && cb.labels && [...cb.labels].some(l => l.textContent === item); });
          if (!li) return {visible: false, gone: true};
          const st = li.querySelector('.item-status'); const by = li.querySelector('.item-by-name');
          const busy = li.closest('[aria-busy="true"]') !== null || li.querySelector('[aria-busy="true"]') !== null;
          return {visible: !!st && vis(st) && norm(st.textContent) === busyText, aria_busy: busy,
            after_attribution: !!(st && by && (by.compareDocumentPosition(st) & Node.DOCUMENT_POSITION_FOLLOWING))};
        }, {op: a.op, item: a.item, busyText});
        const now = Date.now(); gap = Math.max(gap, now - last); last = now; r.polls++;
        if (s.aria_busy && holdEnd === null) r.aria_busy = true;
        if (s.visible && r.visible_ms === null) { r.visible_ms = now - t0; r.after_attribution = s.after_attribution; }
        if (!repeated && (r.visible_ms !== null || now - t0 > 1500)) {
          repeated = true;   // the same control again while held: Enter for Add, a press for the others
          if (a.op === 'add') await p.keyboard.press('Enter'); else await p3.press(u, loc).catch(() => {});
          last = Date.now();
        }
        if (holdEnd !== null && repeated) break;
        await p.waitForTimeout(40);
      }
      r.max_poll_gap_ms = gap;
      r.hold_ms = holdStart !== null && holdEnd !== null ? holdEnd - holdStart : null;
      r.settle = await p3.settle(u);
      r.requests = p3.sent(from, u, method);
      if (a.op !== 'add') r.aria_busy_cleared = await p.evaluate(() => !document.querySelector('[aria-busy="true"]'));
      if (a.watch_live) {
        const t1 = Date.now(); let cleared = null;
        while (Date.now() - t1 < 7000) { const txt = await p.evaluate(() => { const a = document.getElementById('announcer');
            return a ? a.textContent : null; });
          if (txt === '') { cleared = Date.now() - t1; break; } await p.waitForTimeout(100); }
        const live = await p.evaluate(() => window.__p3live ? window.__p3live.rec.slice() : null);
        r.live_texts = live; r.announcer = (live || []).filter(x => x.region_id === 'announcer');
        r.row_status = (live || []).filter(x => x.region_class === 'item-status');
        r.announce_cleared_ms = cleared === null ? null : cleared;
      }
    } catch (e) { r.error = String(e && e.message || e).split('\n')[0].slice(0, 300); }
    finally { await p.unroute(match, handler).catch(() => {}); }
    return r;
  };
  p3.watchLive = async (u) => u.p.evaluate(() => {
    if (window.__p3live) return {installed: false};
    const sel = '[role=status],[role=alert],[aria-live]'; const known = new WeakSet(); const rec = [];
    const scan = () => document.querySelectorAll(sel).forEach(e => known.add(e)); scan();
    const ob = new MutationObserver(muts => { const at = performance.now();
      for (const mu of muts) { const el = mu.target.nodeType === 1 ? mu.target : mu.target.parentElement;
        const region = el && el.closest(sel); if (!region) continue;
        rec.push({at, region_id: region.id || null, region_class: region.classList.contains('item-status') ? 'item-status'
          : (region.className || null), text: String(region.textContent).replace(/\s+/g, ' ').trim(),
          region_predates: known.has(region)}); }
      scan(); });
    ob.observe(document.documentElement, {subtree: true, childList: true, characterData: true});
    window.__p3live = {rec, ob}; return {installed: true};
  });
  p3.act = async (u, a) => {
    const p = u.p;
    if (a.do === 'open') { await p.goto(ORIGIN + '/', {waitUntil: 'load', timeout: 20000}); return null; }
    if (a.do === 'reload') { await p.reload({waitUntil: 'load', timeout: 20000}); return null; }
    if (a.do === 'name') { await p3.typeInto(u, await box(u, T.name_box), a.text, true);
      await p3.press(u, await button(u, T.save_name)); return null; }
    if (a.do === 'type_name') { await p3.typeInto(u, await box(u, T.name_box), a.text, !!a.clear); return null; }
    if (a.do === 'open_change_name') { await p3.press(u, await button(u, T.change_name)); return null; }
    if (a.do === 'change_name') { await p3.press(u, await button(u, T.change_name));
      await p3.typeInto(u, await box(u, T.name_box), a.text, true); await p3.press(u, await button(u, T.save_name));
      return null; }
    if (a.do === 'cancel_name') { await p3.press(u, await button(u, T.cancel)); return null; }
    if (a.do === 'add') {
      await p3.typeInto(u, await box(u, T.item_box), a.text, !!a.clear);
      if (a.submit === 'enter') await p.keyboard.press('Enter');
      else await p3.press(u, await one(p.locator('#add-button'), '#add-button'));
      return null;
    }
    if (a.do === 'type_item') { await p3.typeInto(u, await box(u, T.item_box), a.text, !!a.clear); return null; }
    if (a.do === 'clear_item') { await (await box(u, T.item_box)).fill(''); return null; }
    if (a.do === 'tick' || a.do === 'untick') {
      await p3.press(u, await one(role(u, 'checkbox', a.item), 'checkbox ' + a.item)); return null; }
    if (a.do === 'delete_open') {
      const closed = a.closed_item || null;
      await p3.press(u, await button(u, fill(T.delete_name, a.item)));
      return closed ? {closed_item: closed} : null;
    }
    if (a.do === 'keep') { await p3.press(u, await button(u, fill(T.keep_name, a.item))); return null; }
    if (a.do === 'escape') { await p.keyboard.press('Escape'); return null; }
    if (a.do === 'confirm') { await p3.press(u, await button(u, fill(T.yes_name, a.item))); return null; }
    if (a.do === 'held') return p3.held(u, a);
    if (a.do === 'watch_live') return p3.watchLive(u);
    if (a.do === 'abort_list') {
      u.aborted = 0; const match = (url) => url.origin === ORIGIN && url.pathname === '/api/items';  // R-1
      const handler = (route) => { if (route.request().method() !== 'GET') return route.fallback();
        u.aborted++; return route.abort('failed'); };
      await p.route(match, handler); u.abortRoute = {match, handler}; return null;
    }
    if (a.do === 'unabort') { const x = u.abortRoute; u.abortRoute = null; if (x) await p.unroute(x.match, x.handler);
      return {aborted: u.aborted}; }
    if (a.do === 'try_again') {
      const t0 = Date.now(); await p3.press(u, await button(u, T.try_again));
      while (Date.now() - t0 < 12000) {
        const s = await p.evaluate(() => ({rows: document.querySelectorAll('li input[type=checkbox]').length,
          m9: [...document.querySelectorAll('body *')].some(e => e.children.length === 0
            && String(e.textContent).replace(/\s+/g, ' ').trim() === "Can't reach the server. The list couldn't be loaded."
            && (e.checkVisibility ? e.checkVisibility() : e.getClientRects().length > 0))}));
        if (s.rows > 0 && !s.m9) return {ms: Date.now() - t0};
        await p.waitForTimeout(100);
      }
      return {ms: null};
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
  const domfn = (T) => {
    const norm = (s) => String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
    const vis = (e) => !!e && (e.checkVisibility ? e.checkVisibility({opacityProperty: true, visibilityProperty: true})
      : e.getClientRects().length > 0);
    const byIds = (ids) => String(ids || '').split(/\s+/).filter(Boolean).map(id => document.getElementById(id)).filter(Boolean);
    const descOf = (el) => norm(byIds(el.getAttribute('aria-describedby')).map(e => e.textContent).join(' '));
    const leaf = (text) => [...document.querySelectorAll('body *')].some(e => vis(e) && e.children.length === 0
      && norm(e.textContent) === text);
    const rows = [...document.querySelectorAll('li')].filter(li => vis(li) && li.querySelector('input[type=checkbox]')).map(li => {
      const cb = li.querySelector('input[type=checkbox]'); const lab = byIds(cb.getAttribute('aria-labelledby'));
      const el = lab.length === 1 ? lab[0] : (lab.length === 0 && cb.labels && cb.labels.length === 1 ? cb.labels[0] : null);
      const bys = li.querySelectorAll('.item-by-name'); const by = bys.length === 1 ? bys[0] : null;
      const st = li.querySelector('.item-status');
      return {text: el ? el.textContent : null, name_from: el ? (lab.length ? 'aria-labelledby' : 'label') : 'none',
        desc: descOf(cb), by_name: by ? by.textContent : null, by_count: bys.length, checked: cb.checked,
        text_direction: el ? getComputedStyle(el).direction : null, by_direction: by ? getComputedStyle(by).direction : null,
        markup: li.querySelectorAll('b,i').length, status: st ? norm(st.textContent) : null,
        busy: li.getAttribute('aria-busy')};
    });
    const ws = document.querySelectorAll('#whoami'); const ns = document.querySelectorAll('#whoami-name');
    const w = ws[0] || null; const n = ns[0] || null;
    const who = {whoami_count: ws.length, name_count: ns.length, visible: vis(w), name: n ? n.textContent : null,
      inside: !!(w && n && w.contains(n)), line: w ? norm(w.textContent) : null,
      direction: n ? getComputedStyle(n).direction : null, dir_attr: n ? n.getAttribute('dir') : null,
      i_count: w ? w.querySelectorAll('i').length : null};
    const hint = (id, boxId) => { const hs = document.querySelectorAll('#' + id); const h = hs[0];
      const bx = boxId ? document.getElementById(boxId) : null;
      return {count: hs.length, text: h ? norm(h.textContent) : null, visible: vis(h)}; };
    const ab = document.querySelectorAll('#add-button'); const im = document.getElementById('item-msg');
    const ban = document.getElementById('banner'); const ann = document.getElementById('announcer');
    const metas = document.querySelectorAll('meta[name=viewport]');
    return {rows, row_markup: rows.reduce((s, r) => s + r.markup, 0), who,
      add: {button_count: ab.length, button_text: ab[0] ? norm(ab[0].textContent) : null, button_visible: vis(ab[0]),
        msg: im ? norm(im.textContent) : null},
      name_hint: hint('name-hint'), item_hint: hint('item-hint'),
      banner: ban && vis(ban) ? norm(ban.textContent) : '', announcer: ann ? norm(ann.textContent) : null,
      m9_visible: leaf(T.m9), m10_visible: leaf(T.m10), m11_visible: leaf(T.m11),
      viewport_meta: metas.length === 1 ? metas[0].getAttribute('content') : (metas.length ? 'several' : null),
      scroll_width: document.documentElement.scrollWidth, client_width: document.documentElement.clientWidth,
      dialogs: document.querySelectorAll('dialog, [role=dialog], [role=alertdialog]').length,
      body_text: document.body ? norm(document.body.innerText).slice(0, 2000) : ''};
  };
  p3.observe = async (u) => {
    const p = u.p; await p.waitForTimeout(300);
    const headings = (await p.getByRole('heading', {level: 1}).allInnerTexts()).map(norm);
    const nb = role(u, 'textbox', T.name_box); const name_box = await ctl(nb);
    const ib = role(u, 'textbox', T.item_box); const item_box = await ctl(ib);
    const dom = await p.evaluate(domfn, T);
    dom.add.box_visible = item_box.count === 1 && item_box.visible;
    dom.add.value = item_box.count === 1 ? await ib.inputValue() : null;
    dom.name_form = {visible: name_box.count === 1 && name_box.visible,
      value: name_box.count === 1 ? await nb.inputValue() : null};
    const ta = await ctl(role(u, 'button', T.try_again)); dom.try_again_visible = ta.count === 1 && ta.visible;
    return Object.assign({at: t(), url: p.url(), headings}, dom);
  };
  // ---- measures taken after an act settles (the act's own request counts are added by ROW)
  p3.measure = async (u, a, got) => {
    const p = u.p; const kind = a.measure;
    if (kind === 'step') { const s = await p3.step(u, a.item); if (a.closed_item) s.closed = await p3.step(u, a.closed_item);
      return s; }
    if (kind === 'closed') return p3.step(u, a.item);
    if (kind === 'rows') { const o = await p3.observe(u); return {rows: o.rows}; }
    if (kind === 'm9') { const o = await p3.observe(u); return {m9_text: o.m9_visible ? T.m9 : null,
      try_again_visible: o.try_again_visible, m10_visible: o.m10_visible, m11_visible: o.m11_visible,
      aborted: (u.aborted || 0) > 0, body_text: o.body_text.slice(0, 400)}; }
    if (kind === 'retry') return Object.assign({}, got || {});
    if (kind === 'add_result') { const o = await p3.observe(u); return {msg: o.add.msg, value: o.add.value}; }
    if (kind === 'tick_result') { const o = await p3.observe(u); const row = o.rows.find(r => r.text === a.item);
      const st = p3.log.responses.filter(r => r.ctx === u.name && r.method === 'PATCH').slice(-1).map(r => r.status);
      return {patch_status: st, banner: o.banner, checked: row ? row.checked : null}; }
    if (kind === 'name_result' || kind === 'who_dir') {
      return p.evaluate(() => { const n = document.getElementById('whoami-name'); const bx = [...document.querySelectorAll('input')]
          .find(e => e.labels && [...e.labels].some(l => l.textContent.replace(/\s+/g, ' ').trim() === 'Your name'));
        const hint = document.getElementById('name-hint');
        const msg = bx ? (bx.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean)
          .map(id => document.getElementById(id)).filter(e => e && e !== hint).map(e => e.textContent.replace(/\s+/g, ' ').trim())
          .filter(Boolean).join(' ') : '';
        return {who: n ? n.textContent : null, direction: n ? getComputedStyle(n).direction : null, msg}; });
    }
    if (kind === 'hints') {
      return p.evaluate(() => { const vis = (e) => !!e && (e.checkVisibility ? e.checkVisibility() : e.getClientRects().length > 0);
        const norm = (s) => String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
        const boxOf = (label) => [...document.querySelectorAll('input')].find(e => e.labels
          && [...e.labels].some(l => norm(l.textContent) === label));
        const read = (id, label) => { const hs = document.querySelectorAll('#' + id); const h = hs[0]; const bx = boxOf(label);
          return {count: hs.length, text: h ? norm(h.textContent) : null, visible: vis(h),
            in_describedby: !!bx && (bx.getAttribute('aria-describedby') || '').split(/\s+/).includes(id),
            invalid: !!bx && bx.getAttribute('aria-invalid') === 'true'}; };
        const nb = boxOf('Your name'); const ib = boxOf('New item');
        return {name_form_visible: vis(nb), item_form_visible: vis(ib), name_hint: read('name-hint', 'Your name'),
          item_hint: read('item-hint', 'New item')}; });
    }
    throw new Error('unknown measure ' + kind);
  };
"""

# The row runner: acts in order (each settled), request counts per act, then observations of the named contexts.
ROW_JS = r"""async (page) => {
  const p3 = page.__p3; const acts = __ACTS__; const t = () => new Date().toISOString();
  const res = {started: t(), acts: []};
  for (const a of acts) {
    const u = p3.users[a.ctx || __CTX__];
    const one = {do: a.do, ctx: u.name, started: t(), op: a.op || null, item: a.item || null,
      closed_item: a.closed_item || null, watch_live: !!a.watch_live, measure_kind: a.do === 'held' ? 'held' : (a.measure || null)};
    const from = p3.log.requests.length; let got = null;
    try { got = await p3.act(u, a); } catch (e) { one.error = String(e && e.message || e).split('\n')[0].slice(0, 300); }
    one.settle = await p3.settle(u);
    one.posts = p3.sent(from, u, 'POST'); one.patches = p3.sent(from, u, 'PATCH'); one.deletes = p3.sent(from, u, 'DELETE');
    if (a.do === 'held') one.measure = got;
    else if (a.measure && !one.error) {
      try { one.measure = await p3.measure(u, a, got); }
      catch (e) { one.measure_error = String(e && e.message || e).split('\n')[0].slice(0, 300); }
    }
    if (one.measure && typeof one.measure === 'object') { one.measure.posts = one.posts; one.measure.deletes = one.deletes; }
    one.ended = t(); res.acts.push(one);
    if (one.error) { res.action_error = a.do + ' (' + u.name + '): ' + one.error; break; }
    if (one.measure_error) { res.observe_error = a.do + ' (' + u.name + ') measure: ' + one.measure_error; break; }
  }
  res.ended = t(); res.obs = {};
  for (const c of __OBSERVE__) {
    try { res.obs[c] = await p3.observe(p3.users[c]); }
    catch (e) { res.observe_error = c + ': ' + String(e && e.message || e).split('\n')[0].slice(0, 300); }
  }
  res.log = p3.drain();
  return res;
}"""
