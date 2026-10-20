#!/usr/bin/env python3
"""design_homepage_bar_interact: the homepage A-bar meter, part 2 (Design, queue #79).

Measures the interaction and speed lines of ~/design-lab/homepage-workflow/BAR.md that part 1
(design_homepage_bar, queue #78) leaves out: keyboard reach and order, visible and unhidden focus,
3:1 UI parts and focus indicators, reduced motion (A4); hover and focus states and motion present
(A7); Lighthouse LCP, CLS and TBT (A8). No model anywhere (AGENTS rule 17).

Definitions, limits and the output contract: docs/design-homepage-bar-interaction.md.

    design_homepage_bar_interact.py --site DIR [--page index.html] --out DIR [--browser URL]
        [--serve-host HOST] [--lighthouse DIR] [--chrome PATH] [--raw-only | --from-raw DIR]
    design_homepage_bar_interact.py --fixture-proof --out DIR [--record] [--from-raw DIR] [...]

The browser is temper's playwright-mcp (pages served and driven with design_capture's serve and
run, imported unchanged). Reduced motion is emulated there with page.emulateMedia. Speed uses the
pinned local tool in ~/design-lab/tools/bar-interact/ (Lighthouse 13.5.0) on the local Chromium.
The scorer (score) is pure: raw JSON in, rows out; every limit lives there.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import pathlib
import statistics
import struct
import subprocess
import sys
import tempfile
import time
import urllib.parse
import zlib

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

METER = "design_homepage_bar_interact"
# 2: UI parts per WCAG 1.4.11 (H3c, #96); 3: speed only on a quiet machine (H3d, #110)
VERSION = 3
HELPERS = HERE / "design_homepage_bar_interact.js"
FIXTURES = HERE.parent / "testpages" / "bar-interact-v1"
# Fixture sets of the proof: version 1's key, then version 2's UI-part cases (H3c).
FIXTURE_SETS = ("bar-interact-v1", "bar-interact-v2")
# Version 2's inside pixels: centres at least this far (CSS px) inside the padding box and its rounded corners.
ICON_INSET = 1.0
WIDTHS = {"1440x900": (1440, 900), "390x844": (390, 844)}
SPEED_WIDTH = "412x823"
ALL_WIDTHS = list(WIDTHS) + [SPEED_WIDTH]
MAX_STOPS = 200
# Focus clip margin: the focused element's box grown by this many CSS px on each side. 16, not the 4 first
# written: a ring drawn outside the box (3 px at a 4 px offset on the baseline pages) lies 4 to 7 px out
# and a 4 px clip never saw it (doc, "Changes to definitions", 2026-10-19).
FOCUS_GROW = 16
MAX_EVIDENCE = 5
TOOL_DIR = pathlib.Path.home() / "design-lab" / "tools" / "bar-interact"
CHROME = (
    pathlib.Path.home() / ".cache/ms-playwright/chromium-1243/chrome-linux-arm64/chrome"
)
SPEED_RUNS = 3
# H3d (queue #110): a speed run counts only on a quiet machine. The 1-minute load (the first
# number in /proc/loadavg) must be under LOAD_GATE before and after each run; while it isn't, the
# step reads it again every LOAD_POLL_S, for at most LOAD_WAIT_S per page.
LOAD_GATE = 6.0
LOAD_POLL_S = 15
LOAD_WAIT_S = 600

# (bar, check, limit); the limit text is BAR.md's, word for word, after the measured threshold.
CHECKS = [
    (
        "A4",
        "keyboard-reach",
        "0 unreached (every interactive element is reached by Tab)",
    ),
    ("A4", "keyboard-order", "0 inversions (reached by Tab in reading order)"),
    ("A4", "focus-visible", "0 stops (with a visible, unhidden focus (2.4.7, 2.4.11))"),
    (
        "A4",
        "focus-not-obscured",
        "0 stops (with a visible, unhidden focus (2.4.7, 2.4.11))",
    ),
    (
        "A4",
        "focus-contrast",
        "0 stops under 3:1 (UI parts and focus indicators meet 3:1)",
    ),
    ("A4", "ui-contrast", "0 parts under 3:1 (UI parts and focus indicators meet 3:1)"),
    (
        "A7",
        "hover-states",
        "100% (hover and focus states exist for every interactive element)",
    ),
    (
        "A7",
        "focus-states",
        "100% (hover and focus states exist for every interactive element)",
    ),
    (
        "A4",
        "reduced-motion-animation",
        "0 (prefers-reduced-motion stops all non-essential motion)",
    ),
    (
        "A4",
        "reduced-motion-video",
        "0 (prefers-reduced-motion stops all non-essential motion)",
    ),
    (
        "A4",
        "reduced-motion-scroll",
        "0 (prefers-reduced-motion stops all non-essential motion)",
    ),
    ("A7", "motion-present", "1 or more (the concept's motion idea is present)"),
]
SPEED_CHECKS = [
    ("A8", "lcp", "LCP 2.5 s or less (2500 ms or less)"),
    ("A8", "cls", "CLS 0.1 or less"),
    ("A8", "tbt", "total blocking time 200 ms or less"),
]


# ---------------------------------------------------------------- colour and pixel maths (pure)


def rel_lum(rgb) -> float:
    def ch(v: float) -> float:
        v = v / 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = rgb[:3]
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a, b) -> float:
    la, lb = rel_lum(a), rel_lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def composite(fg, bg) -> tuple[int, int, int]:
    """fg [r, g, b, a] (a 0..1) over an opaque bg [r, g, b]."""
    a = fg[3] if len(fg) > 3 else 1.0
    r, g, b = (int(round(fg[i] * a + bg[i] * (1 - a))) for i in range(3))
    return r, g, b


def differs(a, b, tol: int = 2) -> bool:
    return any(abs(int(a[i]) - int(b[i])) > tol for i in range(3))


def changed_pairs(focused, unfocused, tol: int = 2) -> list[tuple[tuple, tuple]]:
    """Pixels (same index in two equal-size pixel lists) that differ by more than tol in a channel."""
    return [
        (f, u) for f, u in zip(focused, unfocused, strict=False) if differs(f, u, tol)
    ]


def indicator_contrast(pairs, perimeter: int) -> float:
    """The perimeter-th highest focused-vs-unfocused contrast among changed pixels, else 1."""
    if perimeter < 1 or len(pairs) < perimeter:
        return 1.0
    ratios = sorted((contrast(f, u) for f, u in pairs), reverse=True)
    return ratios[perimeter - 1]


def perimeter_of(vbox, vw: float, vh: float) -> int:
    """2 x (w + h) of the box cut to the viewport, at least 4."""
    x, y, w, h = vbox
    left, t = max(0.0, x), max(0.0, y)
    r, b = min(vw, x + w), min(vh, y + h)
    cw, chh = max(0.0, r - left), max(0.0, b - t)
    if cw <= 0 or chh <= 0:  # wholly outside the viewport: nothing of it is drawn
        return 4
    return max(4, int(round(2 * (cw + chh))))


def median_lum_pixel(pixels):
    """The pixel of median relative luminance (lower median for an even count)."""
    if not pixels:
        return None
    ranked = sorted(pixels, key=lambda p: (rel_lum(p), tuple(p[:3])))
    return tuple(ranked[(len(ranked) - 1) // 2][:3])


def _outside_corners(cx, cy, pad, inner, inset):
    """True when (cx, cy) lies less than inset px inside one of the padding box's rounded corners."""
    x0, y0, x1, y1 = pad
    for (rx, ry), (left, top) in zip(
        inner, ((True, True), (False, True), (False, False), (True, False)), strict=True
    ):
        if rx <= inset or ry <= inset:
            continue  # the straight-edge inset already keeps this corner's curve out
        ccx = x0 + rx if left else x1 - rx
        ccy = y0 + ry if top else y1 - ry
        if (cx < ccx if left else cx > ccx) and (cy < ccy if top else cy > ccy):
            if ((cx - ccx) / (rx - inset)) ** 2 + ((cy - ccy) / (ry - inset)) ** 2 > 1:
                return True
    return False


def inside_pixels(pixels, img_w, img_h, clip, box, borders, radii, inset=ICON_INSET):
    """The pixels of a shot (row by row) whose centres lie at least inset px inside the element's padding box
    and inside its rounded corners (version 2's icon reading).

    clip: the shot's {x, y, width, height}; box: the element's border box [x, y, w, h] in the same (viewport)
    coordinates; borders: [top, right, bottom, left] widths; radii: [rx, ry] for the top-left, top-right,
    bottom-right and bottom-left corners (outer edge, as resolved by the helpers)."""
    if img_w < 1 or img_h < 1:
        return []
    bt, br, bb, bl = borders
    pad = (box[0] + bl, box[1] + bt, box[0] + box[2] - br, box[1] + box[3] - bb)
    sides = ((bl, bt), (br, bt), (br, bb), (bl, bb))
    inner = [
        (max(0.0, rx - sx), max(0.0, ry - sy))
        for (rx, ry), (sx, sy) in zip(radii, sides, strict=True)
    ]
    sx, sy = clip["width"] / img_w, clip["height"] / img_h
    out = []
    for k, p in enumerate(pixels):
        cx = clip["x"] + (k % img_w + 0.5) * sx
        cy = clip["y"] + (k // img_w + 0.5) * sy
        if not (
            pad[0] + inset <= cx <= pad[2] - inset
            and pad[1] + inset <= cy <= pad[3] - inset
        ):
            continue
        if _outside_corners(cx, cy, pad, inner, inset):
            continue
        out.append(p)
    return out


def icon_reading(pixels, ref):
    """(number of icon pixels, the 90th-percentile icon pixel or None). Icon pixels: the given (inside) pixels
    that differ from ref by more than 2 in a channel. They are ranked by contrast with ref, lowest first, and
    the pixel at nearest rank ceil(0.9 x n) is returned."""
    icon = [tuple(p[:3]) for p in pixels if differs(p, ref)]
    if not icon:
        return 0, None
    ranked = sorted(icon, key=lambda p: (contrast(p, ref), p))
    return len(icon), ranked[(9 * len(icon) + 9) // 10 - 1]


def decode_png(data: bytes) -> tuple[int, int, list[tuple[int, int, int]]]:
    """8-bit, non-interlaced greyscale/RGB/RGBA PNG to (width, height, RGB pixels row by row)."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos, idat = 8, b""
    w = h = depth = ctype = interlace = -1
    while pos < len(data):
        (n,) = struct.unpack(">I", data[pos : pos + 4])
        kind = data[pos + 4 : pos + 8]
        body = data[pos + 8 : pos + 8 + n]
        pos += 12 + n
        if kind == b"IHDR":
            w, h, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
    if depth != 8 or interlace != 0 or ctype not in (0, 2, 4, 6):
        raise ValueError(
            f"unsupported PNG (depth {depth}, colour type {ctype}, interlace {interlace})"
        )
    bpp = {0: 1, 2: 3, 4: 2, 6: 4}[ctype]
    raw = zlib.decompress(idat)
    stride = w * bpp
    prev = bytearray(stride)
    pixels: list[tuple[int, int, int]] = []
    i = 0
    for _ in range(h):
        f = raw[i]
        line = bytearray(raw[i + 1 : i + 1 + stride])
        i += 1 + stride
        if f == 1:
            for x in range(bpp, stride):
                line[x] = (line[x] + line[x - bpp]) & 255
        elif f == 2:
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 255
        elif f == 3:
            for x in range(stride):
                left = line[x - bpp] if x >= bpp else 0
                line[x] = (line[x] + ((left + prev[x]) >> 1)) & 255
        elif f == 4:
            for x in range(stride):
                a = line[x - bpp] if x >= bpp else 0
                b = prev[x]
                c = prev[x - bpp] if x >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + pr) & 255
        if ctype in (2, 6):
            pixels.extend(
                (line[x], line[x + 1], line[x + 2]) for x in range(0, stride, bpp)
            )
        else:
            pixels.extend((line[x], line[x], line[x]) for x in range(0, stride, bpp))
        prev = line
    return w, h, pixels


# ---------------------------------------------------------------- the scorer (pure)


def _ev(sel: str, text: str, box) -> dict:
    return {
        "selector": sel,
        "text": (text or "")[:80],
        "box": [round(v, 2) for v in (box or [0, 0, 0, 0])],
    }


def _row(bar, check, width, value, limit, ok, evidence=()) -> dict:
    return {
        "bar": bar,
        "check": check,
        "width": width,
        "value": value,
        "limit": limit,
        "pass": ok,
        "evidence": list(evidence)[:MAX_EVIDENCE],
    }


def same_row(p, c) -> bool:
    """Vertical spans overlap by at least half the shorter box's height."""
    top, bottom = max(p[1], c[1]), min(p[1] + p[3], c[1] + c[3])
    return (bottom - top) >= 0.5 * min(p[3], c[3])


def is_inversion(p, c) -> bool:
    """p, c: boxes [x, y, w, h] of consecutive stops, in one coordinate space."""
    wholly_right = c[0] >= p[0] + p[2]
    if c[1] < p[1] - 24 and not wholly_right:
        return True
    return same_row(p, c) and c[0] + c[2] <= p[0]


def inversions(stops) -> list[int]:
    """Indexes i (stop i follows stop i-1) that are order inversions."""
    out = []
    for i in range(1, len(stops)):
        p, c = stops[i - 1], stops[i]
        if p.get("fixed") != c.get("fixed"):
            continue
        key = "vbox" if p.get("fixed") else "box"
        if is_inversion(p[key], c[key]):
            out.append(i)
    return out


def _distinct(stops):
    seen, out = set(), []
    for s in stops:
        if s["id"] not in seen:
            seen.add(s["id"])
            out.append(s)
    return out


def score_walk(walk: dict, width: str, limits: dict) -> list[dict]:
    rows = []
    stops = walk.get("stops") or []
    reached = {s.get("key") for s in stops}
    unreached, seen = [], set()
    for el in walk.get("interactive") or []:
        if el["key"] not in reached and el["key"] not in seen:
            seen.add(el["key"])
            unreached.append(el)
    rows.append(
        _row(
            "A4",
            "keyboard-reach",
            width,
            len(unreached),
            limits["keyboard-reach"],
            not unreached,
            [_ev(e["sel"], e["text"], e["box"]) for e in unreached],
        )
    )
    inv = inversions(stops)
    rows.append(
        _row(
            "A4",
            "keyboard-order",
            width,
            len(inv),
            limits["keyboard-order"],
            not inv,
            [_ev(stops[i]["sel"], stops[i]["text"], stops[i]["box"]) for i in inv],
        )
    )
    distinct = _distinct(stops)
    hidden = [s for s in distinct if all(p["hidden"] for p in s["points"])]
    shown = [s for s in distinct if not all(p["hidden"] for p in s["points"])]
    faint = [s for s in shown if s["changed"] < s["perimeter"]]
    low = [s for s in shown if s["changed"] >= s["perimeter"] and s["contrast"] < 3.0]
    rows.append(
        _row(
            "A4",
            "focus-visible",
            width,
            len(faint),
            limits["focus-visible"],
            not faint,
            [_ev(s["sel"], s["text"], s["box"]) for s in faint],
        )
    )
    rows.append(
        _row(
            "A4",
            "focus-not-obscured",
            width,
            len(hidden),
            limits["focus-not-obscured"],
            not hidden,
            [_ev(s["sel"], s["text"], s["box"]) for s in hidden],
        )
    )
    rows.append(
        _row(
            "A4",
            "focus-contrast",
            width,
            len(low),
            limits["focus-contrast"],
            not low,
            [
                _ev(s["sel"], s["text"] + f" ({s['contrast']:.2f}:1)", s["box"])
                for s in low
            ],
        )
    )
    return rows


def part_fill(part: dict):
    """A UI candidate's fill over its behind colour (with a background image: that image's median pixel)."""
    st = part["style"]
    if (
        part.get("fill_image") is not None
        and st.get("background_image", "none") != "none"
    ):
        return tuple(part["fill_image"])
    return composite(st["background_rgba"], part["behind"])


def icon_reference(part: dict):
    """What is directly behind a control's icon: its fill when that differs from the behind colour, else the
    behind colour (version 2)."""
    behind = tuple(part["behind"][:3])
    fill = part_fill(part)
    return fill if differs(fill, behind) else behind


def part_contrast(part: dict):
    """(is a UI part, part contrast) from one raw UI candidate: version 1's reading, which version 2 keeps for
    fields, for controls with no text and no icon, and for raw files measured before version 2."""
    behind = part.get("behind")
    if behind is None:
        return None, None
    st = part["style"]
    fill = part_fill(part)
    border = composite(st["border_rgba"], behind) if st.get("full_border") else None
    is_part = part["kind"] == "field" or differs(fill, behind) or border is not None
    best = contrast(fill, behind)
    if border is not None:
        best = max(best, contrast(border, behind))
    return is_part, best


def ui_reading(part: dict):
    """(how a UI candidate is read, its value), version 2 (H3c, WCAG 1.4.11).

    how: "text" (a control identified by its visible text: part 1's text-contrast row, not measured here),
    "icon" (a control with no visible text: icon contrast), "part" (a field, or a control with no text and no
    icon: part contrast), "none" (not measured: a link with no fill and no full border, or a control that draws
    nothing) or "unknown" (no behind colour: could not be measured). Candidates from raw files measured before
    version 2 (no "vtext") are read as in version 1."""
    v2 = "vtext" in part and part["kind"] != "field"
    if v2 and part["vtext"]:
        return "text", None
    if part.get("behind") is None:
        return "unknown", None
    if v2:
        behind = tuple(part["behind"][:3])
        if part["kind"] == "link" and not (
            differs(part_fill(part), behind) or part["style"].get("full_border")
        ):
            return "none", None
        icon = part.get("icon") or {}
        if icon.get("pixels"):
            return "icon", contrast(icon["p90"], icon["ref"])
    is_part, c = part_contrast(part)
    return ("part" if is_part else "none"), c


def score_ui(parts: list, width: str, limit: str) -> dict:
    fails, unknown = [], 0
    for p in parts:
        how, c = ui_reading(p)
        if how == "unknown":
            unknown += 1
        elif how in ("part", "icon") and c < 3.0:
            what = "icon " if how == "icon" else ""
            fails.append(_ev(p["sel"], f"{p['text']} ({what}{c:.2f}:1)", p["box"]))
    if unknown:
        return _row(
            "A4",
            "ui-contrast",
            width,
            None,
            limit,
            None,
            fails + [_ev("", f"{unknown} part(s) could not be measured", None)],
        )
    return _row("A4", "ui-contrast", width, len(fails), limit, not fails, fails)


_GATES = {
    "outline-color": ("outline-style",),
    "outline-width": ("outline-style",),
    "outline-offset": ("outline-style",),
    "text-decoration-color": ("text-decoration-line",),
    "text-decoration-style": ("text-decoration-line",),
    "text-decoration-thickness": ("text-decoration-line",),
}
for _side in ("top", "right", "bottom", "left"):
    _GATES[f"border-{_side}-color"] = (f"border-{_side}-style",)
    _GATES[f"border-{_side}-width"] = (f"border-{_side}-style",)


def _draws(prop: str, value: str) -> bool:
    if prop.endswith("-style"):
        return value not in ("none", "hidden", "")
    return value not in ("none", "")


def has_state(diff: dict) -> bool:
    """diff: {node: {rest: props|None, state: props|None}} with only nodes that differ."""
    for node in diff.values():
        rest, state = node.get("rest"), node.get("state")
        if rest is None or state is None:
            return True
        for prop, before in rest.items():
            after = state.get(prop)
            if before == after:
                continue
            gate = _GATES.get(prop)
            if gate and not any(
                _draws(gate[0], v.get(gate[0], "none")) for v in (rest, state)
            ):
                continue
            return True
    return False


def score_states(items: list, check: str, width: str, limit: str) -> dict:
    if not items:
        return _row("A7", check, width, 100.0, limit, True)
    missing = []
    for it in items:
        if it.get("note") or not has_state(it.get("diff") or {}):
            missing.append(
                _ev(
                    it["sel"],
                    (it["text"] + (f" ({it['note']})" if it.get("note") else ""))[:80],
                    it["box"],
                )
            )
    share = round(100.0 * (len(items) - len(missing)) / len(items), 1)
    return _row("A7", check, width, share, limit, share >= 100.0, missing)


def _tdiff(before: dict, after: dict) -> list[str]:
    return sorted(
        k
        for k in set(before) | set(after)
        if (before.get(k) or {}).get("v", "none")
        != (after.get(k) or {}).get("v", "none")
    )


def _tinfo(sel, before, after):
    i = after.get(sel) or before.get(sel) or {}
    return _ev(sel, i.get("text", ""), i.get("box"))


def score_motion(normal: dict, reduced: dict, width: str, limits: dict) -> list[dict]:
    rows = []
    r_anims = (reduced.get("r1") or []) + [
        a for s in reduced.get("r2") or [] for a in s
    ]
    long_ = {}
    for a in r_anims:
        if (a.get("infinite") or (a.get("active_ms") or 0) > 200) and a[
            "key"
        ] not in long_:
            long_[a["key"]] = a
    rows.append(
        _row(
            "A4",
            "reduced-motion-animation",
            width,
            len(long_),
            limits["reduced-motion-animation"],
            not long_,
            [
                _ev(
                    a.get("target") or "",
                    f"{a['key'].split('|')[-1]} "
                    f"({'infinite' if a.get('infinite') else str(a.get('active_ms')) + ' ms'})",
                    a.get("box"),
                )
                for a in long_.values()
            ],
        )
    )
    vids = [
        v
        for v in reduced.get("videos") or []
        if v["sized"] and not v["paused"] and not v["ended"]
    ]
    rows.append(
        _row(
            "A4",
            "reduced-motion-video",
            width,
            len(vids),
            limits["reduced-motion-video"],
            not vids,
            [_ev(v["sel"], v["text"] or "video", v["box"]) for v in vids],
        )
    )
    animated = {a.get("target") for a in r_anims}
    tb, ta = reduced.get("t_before") or {}, reduced.get("t_after") or {}
    moved = [s for s in _tdiff(tb, ta) if s not in animated]
    rows.append(
        _row(
            "A4",
            "reduced-motion-scroll",
            width,
            len(moved),
            limits["reduced-motion-scroll"],
            not moved,
            [_tinfo(s, tb, ta) for s in moved],
        )
    )
    movers: dict[str, dict] = {}
    for e in normal.get("events") or []:
        if e.get("target"):
            movers.setdefault(
                e["target"], _ev(e["target"], e.get("text", ""), e.get("box"))
            )
    for sample in normal.get("samples") or []:
        for a in sample:
            if a.get("target"):
                movers.setdefault(
                    a["target"], _ev(a["target"], a.get("text", ""), a.get("box"))
                )
    nb, na = normal.get("t_before") or {}, normal.get("t_after") or {}
    for s in _tdiff(nb, na):
        movers.setdefault(s, _tinfo(s, nb, na))
    ev = [movers[k] for k in sorted(movers)]
    rows.append(
        _row(
            "A7",
            "motion-present",
            width,
            len(movers),
            limits["motion-present"],
            len(movers) >= 1,
            ev,
        )
    )
    return rows


def median_or_none(values):
    if not values or any(v is None for v in values):
        return None
    return statistics.median(values)


def score_speed(speed: dict) -> list[dict]:
    runs = (speed or {}).get("runs") or []
    rows = []
    for bar, check, limit in SPEED_CHECKS:
        vals = [r.get(check) for r in runs] if len(runs) == SPEED_RUNS else []
        med = median_or_none(vals)
        if med is None:
            err = (speed or {}).get(
                "error"
            ) or f"{len(runs)} of {SPEED_RUNS} runs gave a value"
            rows.append(
                _row(
                    bar,
                    check,
                    SPEED_WIDTH,
                    None,
                    limit,
                    None,
                    [_ev("", str(err)[:80], None)],
                )
            )
            continue
        if check == "cls":
            value, ok = round(med, 4), med <= 0.1
        elif check == "lcp":
            value, ok = int(round(med)), med <= 2500
        else:
            value, ok = int(round(med)), med <= 200
        ev = (
            [
                _ev(n.get("selector", ""), n.get("text", ""), n.get("box"))
                for n in (speed.get("nodes") or {}).get(check, [])
            ]
            if not ok
            else []
        )
        rows.append(_row(bar, check, SPEED_WIDTH, value, limit, ok, ev))
    return rows


def _null_rows(width: str, checks, err: str) -> list[dict]:
    lim = {c: limit for _, c, limit in CHECKS}
    bars = {c: b for b, c, _ in CHECKS}
    return [
        _row(
            bars[c],
            c,
            width,
            None,
            lim[c],
            None,
            [_ev("", ("error: " + err)[:80], None)],
        )
        for c in checks
    ]


def score(raw: dict) -> dict:
    """Raw measurements to the bars-interact.json document. Pure: no browser, no files."""
    limits = {c: limit for _, c, limit in CHECKS}
    by_check: dict[tuple[str, str], dict] = {}
    for width in WIDTHS:
        ph = (raw.get("phases") or {}).get(width) or {}
        rows: list[dict] = []
        walk = ph.get("walk") or {}
        if walk.get("error") or "stops" not in walk:
            rows += _null_rows(
                width,
                [
                    "keyboard-reach",
                    "keyboard-order",
                    "focus-visible",
                    "focus-not-obscured",
                    "focus-contrast",
                ],
                walk.get("error") or "no walk",
            )
        else:
            rows += score_walk(walk, width, limits)
        ui = ph.get("ui") or {}
        rows.append(
            score_ui(ui["parts"], width, limits["ui-contrast"])
            if "parts" in ui
            else _null_rows(width, ["ui-contrast"], ui.get("error") or "no ui")[0]
        )
        for check, key in (("hover-states", "hover"), ("focus-states", "focus")):
            st = ph.get(key) or {}
            rows.append(
                score_states(st["items"], check, width, limits[check])
                if "items" in st
                else _null_rows(width, [check], st.get("error") or f"no {key}")[0]
            )
        normal, reduced = ph.get("normal") or {}, ph.get("reduced") or {}
        if (
            normal.get("error")
            or reduced.get("error")
            or "t_before" not in normal
            or "t_before" not in reduced
        ):
            rows += _null_rows(
                width,
                [
                    "reduced-motion-animation",
                    "reduced-motion-video",
                    "reduced-motion-scroll",
                    "motion-present",
                ],
                normal.get("error") or reduced.get("error") or "no motion",
            )
        else:
            rows += score_motion(normal, reduced, width, limits)
        for r in rows:
            by_check[(r["check"], width)] = r
    ordered = [by_check[(c, w)] for _, c, _ in CHECKS for w in WIDTHS]
    ordered += score_speed(raw.get("speed") or {})
    return {
        "meter": METER,
        "version": VERSION,
        "page": raw.get("page"),
        "page_sha256": raw.get("page_sha256"),
        "widths": ALL_WIDTHS,
        "rows": ordered,
    }


def failing(doc: dict) -> set[tuple[str, str, str]]:
    return {
        (r["bar"], r["check"], r["width"]) for r in doc["rows"] if r["pass"] is not True
    }


# A row's outcome by its pass (H3d): null is "could not measure", never met and never not met.
OUTCOME = {True: "met", False: "not met", None: "could not measure"}


def unmeasured(doc: dict) -> set[tuple[str, str, str]]:
    return {
        (r["bar"], r["check"], r["width"]) for r in doc["rows"] if r["pass"] is None
    }


def page_verdict(doc: dict, want: set) -> str:
    """A page's rows against its key: match, differ or could not measure (H3d).

    differ: a row the key doesn't name was not met, or a row it names was met. A row that
    could not be measured is never counted as either; when no row differs but some could not
    be measured, the page proves nothing either way.
    """
    got, nulls = failing(doc), unmeasured(doc)
    if (got - nulls) - want or want - got:
        return "differ"
    return "could not measure" if nulls else "match"


def tally(doc: dict) -> dict:
    """Rows counted apart as met, not met and could not measure, and each bar's outcome."""
    rows = dict.fromkeys(OUTCOME.values(), 0)
    passes: dict[str, list] = {}
    for r in doc["rows"]:
        rows[OUTCOME[r["pass"]]] += 1
        passes.setdefault(r["bar"], []).append(r["pass"])
    bars = {}
    for bar, ps in sorted(passes.items()):
        if any(p is False for p in ps):
            bars[bar] = "not met"
        elif any(p is None for p in ps):
            bars[bar] = "could not measure"
        else:
            bars[bar] = "met"
    return {"rows": rows, "bars": bars}


def _reason(row: dict) -> str:
    """Why a row could not be measured: its evidence texts that name no element."""
    why = [e["text"] for e in row["evidence"] if not e["selector"]]
    return "; ".join(why) or "no value"


def _ev_line(e: dict) -> str:
    return f'  - `{e["selector"]}` "{e["text"]}" box {e["box"]}'


def _fmt(v) -> str:
    if v is None:
        return "n/a"
    return str(v)


def to_md(doc: dict) -> str:
    lines = [
        f"# {METER} v{doc['version']}: {doc['page']}",
        "",
        f"page_sha256 `{doc['page_sha256']}`",
        "",
        "| bar | check | width | value | limit | pass |",
        "|---|---|---|---|---|---|",
    ]
    for r in doc["rows"]:
        ok = {True: "yes", False: "no", None: "could not measure"}[r["pass"]]
        lines.append(
            f"| {r['bar']} | {r['check']} | {r['width']} | {_fmt(r['value'])} | {r['limit']} | {ok} |"
        )
    lines += ["", "## Bars (part 2 rows only)", ""]
    for bar in ("A4", "A7", "A8"):
        rows = [r for r in doc["rows"] if r["bar"] == bar]
        parts = []
        for outcome in (False, None):
            named = [f"{r['check']} {r['width']}" for r in rows if r["pass"] is outcome]
            if named:
                parts.append(f"{OUTCOME[outcome]} ({', '.join(named)})")
        lines.append(f"- {bar}: {'; '.join(parts) or 'met'}")
    n = tally(doc)["rows"]
    lines += [
        "",
        f"Rows: {n['met']} met, {n['not met']} not met,"
        f" {n['could not measure']} could not measure.",
        "",
        "## Evidence for rows not met",
        "",
    ]
    for r in doc["rows"]:
        if r["pass"] is False:
            lines.append(f"- {r['check']} {r['width']}:")
            lines += [_ev_line(e) for e in r["evidence"]]
    lines += ["", "## Rows that could not be measured", ""]
    for r in doc["rows"]:
        if r["pass"] is None:
            lines.append(f"- {r['check']} {r['width']}: {_reason(r)}")
            lines += [_ev_line(e) for e in r["evidence"] if e["selector"]]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- the browser driver

MOTION_INIT = r"""(() => {
  if (window.__biEv) return;
  window.__biEv = {events: [], load: []};
  const rec = (e) => window.__biEv.events.push({type: e.type, t: e.target,
    name: e.animationName || e.propertyName || '', pseudo: e.pseudoElement || ''});
  addEventListener('animationstart', rec, {capture: true, passive: true});
  addEventListener('transitionstart', rec, {capture: true, passive: true});
  addEventListener('load', () => {
    window.__biEv.load = document.getAnimations().filter((a) => a.playState === 'running')
      .map((a) => a.effect && a.effect.target).filter(Boolean);
  });
})()"""


def _clip(vbox, vw, vh, grow=4):
    x, y, w, h = vbox
    left, t = max(0.0, x - grow), max(0.0, y - grow)
    r, b = min(float(vw), x + w + grow), min(float(vh), y + h + grow)
    if r - left < 1 or b - t < 1:
        return None
    return {
        "x": round(left, 2),
        "y": round(t, 2),
        "width": round(r - left, 2),
        "height": round(b - t, 2),
    }


class Driver:
    def __init__(self, session, url: str, helpers: str, shots: pathlib.Path | None):
        import design_capture as dc

        self.dc, self.s, self.url, self.helpers, self.shots = (
            dc,
            session,
            url,
            helpers,
            shots,
        )

    async def run(self, code: str):
        return await self.dc.run(self.s, code)

    async def open(self, width: str, motion: str = "no-preference", init: bool = False):
        w, h = WIDTHS[width]
        await self.run(
            "async (page) => { "
            + (f"await page.addInitScript({json.dumps(MOTION_INIT)}); " if init else "")
            + "try { await page.mouse.move(-20, -20); } catch (e) { await page.mouse.move(0, 0); } "
            f"await page.setViewportSize({{width: {w}, height: {h}}}); "
            f"await page.emulateMedia({{reducedMotion: {json.dumps(motion)}, colorScheme: 'light'}}); "
            f"await page.goto({json.dumps(self.url)}, {{waitUntil: 'networkidle'}}); "
            "await page.evaluate(() => document.fonts.ready.then(() => true)); "
            f"await page.evaluate({json.dumps('(' + self.helpers.strip() + ')()')}); "
            "try { await page.mouse.move(-20, -20); } catch (e) { await page.mouse.move(0, 0); } "
            "return true; }"
        )

    async def shot(self, clip) -> bytes | None:
        if clip is None:
            return None
        b64 = await self.run(
            "async (page) => (await page.screenshot({type: 'png', scale: 'css', clip: "
            + json.dumps(clip)
            + "})).toString('base64')"
        )
        return base64.b64decode(b64)

    def keep(self, name: str, data: bytes | None) -> str | None:
        if data is None or self.shots is None:
            return None
        self.shots.mkdir(parents=True, exist_ok=True)
        (self.shots / name).write_bytes(data)
        return f"shots/{name}"

    async def walk(self, width: str) -> dict:
        await self.open(width)
        await self.run(
            "async (page) => { await page.waitForTimeout(500); return true; }"
        )
        interactive = await self.run(
            "async (page) => await page.evaluate(() => { __bi.settle(); "
            "if (document.activeElement && document.activeElement.blur) document.activeElement.blur(); "
            "window.scrollTo({left: 0, top: 0, behavior: 'instant'}); return __bi.interactive(); })"
        )
        stops, first, truncated = [], None, False
        for n in range(MAX_STOPS):
            # One call per stop: Tab, read, focused shot, blur, rest shot, focus again (no scroll).
            got = await self.run(
                "async (page) => { await page.keyboard.press('Tab'); const a = await page.evaluate(async () => { "
                "await __bi.waitScroll(); __bi.settle(); return __bi.active(); }); "
                f"if (!a || a.id === {json.dumps(first)}) return {{a, end: true}}; "
                f"const [x, y, w, h] = a.vbox; const l = Math.max(0, x - {FOCUS_GROW}), t = Math.max(0, y - {FOCUS_GROW}); "
                f"const r = Math.min(a.vw, x + w + {FOCUS_GROW}), b = Math.min(a.vh, y + h + {FOCUS_GROW}); "
                "const rd = (v) => Math.round(v * 100) / 100; "
                "const clip = (r - l < 1 || b - t < 1) ? null : {x: rd(l), y: rd(t), width: rd(r - l), height: rd(b - t)}; "
                "if (!clip) return {a, clip}; "
                "const f = (await page.screenshot({type: 'png', scale: 'css', clip})).toString('base64'); "
                "await page.evaluate((id) => { __bi.el(id).blur(); __bi.settle(); return true; }, a.id); "
                "const u = (await page.screenshot({type: 'png', scale: 'css', clip})).toString('base64'); "
                "await page.evaluate((id) => { __bi.el(id).focus({preventScroll: true}); __bi.settle(); return true; }, a.id); "
                "return {a, clip, f, u}; }"
            )
            a = got.get("a") if got else None
            if not a or got.get("end"):
                break
            if first is None:
                first = a["id"]
            clip = got.get("clip")
            f_png = base64.b64decode(got["f"]) if got.get("f") else None
            u_png = base64.b64decode(got["u"]) if got.get("u") else None
            per = perimeter_of(a["vbox"], a["vw"], a["vh"])
            if f_png and u_png:
                _, _, fp = decode_png(f_png)
                _, _, up = decode_png(u_png)
                pairs = changed_pairs(fp, up) if len(fp) == len(up) else []
            else:
                pairs = []
            a.update(
                {
                    "clip": clip,
                    "perimeter": per,
                    "changed": len(pairs),
                    "contrast": round(indicator_contrast(pairs, per), 2),
                    "shots": [
                        self.keep(f"{width}-stop{n + 1:03d}-focus.png", f_png),
                        self.keep(f"{width}-stop{n + 1:03d}-rest.png", u_png),
                    ],
                }
            )
            a.pop("vw", None)
            a.pop("vh", None)
            stops.append(a)
        else:
            truncated = True
        return {"interactive": interactive, "stops": stops, "truncated": truncated}

    async def ui(self, width: str) -> dict:
        await self.open(width)
        await self.run(
            "async (page) => { await page.waitForTimeout(500); return true; }"
        )
        cands = await self.run(
            "async (page) => await page.evaluate(() => { __bi.settle(); "
            "if (document.activeElement && document.activeElement.blur) document.activeElement.blur(); "
            "return __bi.uiCandidates(); })"
        )
        parts = []
        for c in cands:
            # A field is read by its boundary, never by an icon.
            icon = c["kind"] != "field"
            d = await self._ui_part(c["id"], reveal=False, icon=icon)
            via = None
            if not d.get("behind"):
                # Not on screen at rest (for example a skip link kept off the page until it has focus):
                # measure it where it shows, with focus on it, the way a keyboard user reveals it.
                d2 = await self._ui_part(c["id"], reveal=True, icon=icon)
                if d2.get("behind"):
                    d, via = d2, "focus"
                else:
                    await self._blur(c["id"])
            behind_png = base64.b64decode(d["behind"]) if d.get("behind") else None
            behind = median_lum_pixel(decode_png(behind_png)[2]) if behind_png else None
            fill_image = None
            if d["st"].get("background_image", "none") != "none":
                bw = d["st"]["border_widths"]
                x, y, w, h = d["vb"]
                pad = [x + bw[3], y + bw[0], w - bw[1] - bw[3], h - bw[0] - bw[2]]
                png = await self.shot(_clip(pad, d["vw"], d["vh"], grow=0))
                fill_image = list(median_lum_pixel(decode_png(png)[2])) if png else None
            if via:
                await self._blur(c["id"])
            part = {
                "sel": c["sel"],
                "text": c["text"],
                "box": c["box"],
                "kind": c["kind"],
                "style": d["st"],
                "behind": list(behind) if behind else None,
                "fill_image": fill_image,
                "vtext": bool(d.get("vtext")),
            }
            if icon and not part["vtext"] and behind is not None and d.get("self"):
                # Version 2: a control with no visible text is read by its icon (see icon_reading).
                w, h, px = decode_png(base64.b64decode(d["self"]))
                st = d["st"]
                inside = inside_pixels(
                    px, w, h, d["selfclip"], d["vb"], st["border_widths"], st["radii"]
                )
                ref = icon_reference(part)
                n, p90 = icon_reading(inside, ref)
                part["icon"] = {
                    "ref": list(ref),
                    "pixels": n,
                    "p90": list(p90) if p90 else None,
                }
            if via:
                part["via"] = via
            parts.append(part)
        return {"parts": parts}

    async def _blur(self, eid: int) -> None:
        await self.run(
            f"async (page) => page.evaluate(() => {{ const el = __bi.el({eid}); if (document.activeElement === el) "
            "el.blur(); __bi.settle(); return true; })"
        )

    async def _ui_part(self, eid: int, reveal: bool, icon: bool = True) -> dict:
        """One call per part: bring it into view (centre it, or focus it when reveal), read its style and visible
        text, shoot it as it is when it has no visible text (version 2), hide it for the behind shot, restore it.
        With reveal the element is left focused for the caller to blur."""
        bring = (
            (
                "el.focus(); if (document.activeElement !== el) return {st: __bi.uiStyle(el), vb: [0, -1e6, 0, 0], "
                "vw: innerWidth, vh: innerHeight}; await __bi.waitScroll(); "
            )
            if reveal
            else "__bi.centreTo(el); "
        )
        refocus = "el.focus({preventScroll: true}); " if reveal else ""
        return await self.run(
            "async (page) => { "
            f"const d = await page.evaluate(async () => {{ const el = __bi.el({eid}); {bring}"
            "__bi.settle(); const st = __bi.uiStyle(el); const vb = __bi.viewBox(el); "
            "const vtext = __bi.hasVisibleText(el); "
            "return {st, vb, vtext, vw: innerWidth, vh: innerHeight}; }); "
            "const [x, y, w, h] = d.vb; const l = Math.max(0, x), t = Math.max(0, y); "
            "const r = Math.min(d.vw, x + w), b = Math.min(d.vh, y + h); "
            "const rd = (v) => Math.round(v * 100) / 100; "
            "const clip = (r - l < 1 || b - t < 1) ? null : {x: rd(l), y: rd(t), width: rd(r - l), height: rd(b - t)}; "
            f"if (clip && !d.vtext && {json.dumps(icon)}) {{ d.selfclip = {{x: Math.floor(l), y: Math.floor(t), "
            "width: Math.ceil(r) - Math.floor(l), height: Math.ceil(b) - Math.floor(t)}; "
            "d.self = (await page.screenshot({type: 'png', scale: 'css', clip: d.selfclip})).toString('base64'); } "
            f"await page.evaluate(() => {{ const el = __bi.el({eid}); "
            "el.__biVis = [el.style.getPropertyValue('visibility'), el.style.getPropertyPriority('visibility')]; "
            "el.style.setProperty('visibility', 'hidden', 'important'); return true; }); "
            "d.behind = clip ? (await page.screenshot({type: 'png', scale: 'css', clip})).toString('base64') : null; "
            f"await page.evaluate(() => {{ const el = __bi.el({eid}); "
            "const [v, p] = el.__biVis; if (v) el.style.setProperty('visibility', v, p); "
            f"else el.style.removeProperty('visibility'); {refocus}__bi.settle(); return true; }}); "
            "return d; }"
        )

    async def hover(self, width: str) -> dict:
        await self.open(width)
        await self.run(
            "async (page) => { await page.waitForTimeout(500); return true; }"
        )
        els = await self.run(
            "async (page) => await page.evaluate(() => { __bi.settle(); "
            "if (document.activeElement && document.activeElement.blur) document.activeElement.blur(); "
            "return __bi.interactive(); })"
        )
        items = []
        for e in els:
            eid = e["id"]
            # Not hoverable at rest (for example a skip link kept off the page until it has focus): reveal it
            # the way a keyboard user does, then compare focused with focused and hovered.
            r = await self.run(
                "async (page) => { await page.mouse.move(-20, -20); "
                f"let pt = await page.evaluate(async () => {{ const el = __bi.el({eid}); __bi.centreTo(el); "
                "await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))); "
                "__bi.settle(); __bi.rest = __bi.readState(el); return __bi.hoverPoint(el); }); "
                "let focused = false; "
                "if (!pt) { focused = true; "
                f"pt = await page.evaluate(async () => {{ const el = __bi.el({eid}); el.focus(); "
                "if (document.activeElement !== el) return null; await __bi.waitScroll(); "
                "await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))); "
                "__bi.settle(); __bi.rest = __bi.readState(el); return __bi.hoverPoint(el); }); } "
                f"const unfocus = () => page.evaluate(() => {{ const el = __bi.el({eid}); "
                "if (document.activeElement === el) el.blur(); __bi.settle(); return true; }); "
                "if (!pt) { if (focused) await unfocus(); return {covered: true}; } "
                "await page.mouse.move(pt[0], pt[1]); "
                f"const res = await page.evaluate(async () => {{ const el = __bi.el({eid}); "
                "await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))); "
                "getComputedStyle(el).color; __bi.settle(); "
                "return {diff: __bi.stateDiff(__bi.rest, __bi.readState(el))}; }); "
                "if (focused) { await page.mouse.move(-20, -20); await unfocus(); res.via = 'focus'; } "
                "return res; }"
            )
            item = {"sel": e["sel"], "text": e["text"], "box": e["box"]}
            if r.get("covered"):
                item["note"] = "covered"
            else:
                item["diff"] = r["diff"]
                if r.get("via"):
                    item["via"] = r["via"]
            items.append(item)
        await self.run(
            "async (page) => { await page.mouse.move(-20, -20); return true; }"
        )
        return {"items": items}

    async def focus(self, width: str) -> dict:
        await self.open(width)
        await self.run(
            "async (page) => { await page.waitForTimeout(500); return true; }"
        )
        res = await self.run(
            "async (page) => { await page.keyboard.press('Tab'); return await page.evaluate(async () => { "
            "if (document.activeElement && document.activeElement.blur) document.activeElement.blur(); "
            "__bi.settle(); const out = []; "
            "for (const e of __bi.interactive()) { const el = __bi.el(e.id); el.focus(); await __bi.waitScroll(); "
            "__bi.settle(); const ok = document.activeElement === el; const f = __bi.readState(el); "
            "el.blur(); __bi.settle(); const r = __bi.readState(el); "
            "out.push(ok ? {sel: e.sel, text: e.text, box: e.box, diff: __bi.stateDiff(r, f)} "
            ": {sel: e.sel, text: e.text, box: e.box, note: 'not focusable'}); } return out; }); }"
        )
        return {"items": res}

    async def normal_motion(self, width: str) -> dict:
        await self.open(width, "no-preference", init=True)
        return await self.run(
            "async (page) => { await page.waitForTimeout(500); return await page.evaluate(async () => { "
            "const sel = (t) => t && t.nodeType === 1 ? __bi.selector(t) : null; "
            "const load = (window.__biEv ? window.__biEv.load : []).map((t) => ({target: sel(t), "
            "text: __bi.text(t), box: __bi.layoutBox(t)})); "
            "const s0 = __bi.running(); const t_before = __bi.transforms(); __bi.scrollOne(); "
            "await __bi.sleep(100); const s1 = __bi.running(); await __bi.sleep(200); const s2 = __bi.running(); "
            "await __bi.sleep(300); const s3 = __bi.running(); await __bi.sleep(400); const t_after = __bi.transforms(); "
            "const events = (window.__biEv ? window.__biEv.events : []).filter((e) => e.t && e.t.nodeType === 1)"
            ".map((e) => ({type: e.type, name: e.name, target: sel(e.t), text: __bi.text(e.t), box: __bi.layoutBox(e.t)})); "
            "return {samples: [load, s0, s1, s2, s3], t_before, t_after, events}; }); }"
        )

    async def reduced_motion(self, width: str) -> dict:
        await self.open(width, "reduce", init=True)
        return await self.run(
            "async (page) => { await page.waitForTimeout(2000); return await page.evaluate(async () => { "
            "const r1 = __bi.running(); const videos = __bi.videos(); const t_before = __bi.transforms(); "
            "__bi.scrollOne(); await __bi.sleep(100); const a = __bi.running(); await __bi.sleep(200); "
            "const b = __bi.running(); await __bi.sleep(300); const c = __bi.running(); await __bi.sleep(400); "
            "const t_after = __bi.transforms(); return {r1, r2: [a, b, c], videos, t_before, t_after}; }); }"
        )


def _sorted_motion(m: dict) -> dict:
    """Stable order for samples and events so two runs compare equal."""

    def key(a: dict) -> tuple:
        return (
            a.get("target") or "",
            a.get("key") or a.get("name") or "",
            a.get("type") or "",
        )

    out = dict(m)
    for k in ("samples", "r2"):
        if k in out:
            out[k] = [sorted(s, key=key) for s in out[k]]
    if "r1" in out:
        out["r1"] = sorted(out["r1"], key=key)
    if "events" in out:
        uniq = {(e["type"], e["name"], e["target"]): e for e in out["events"]}
        out["events"] = [uniq[k] for k in sorted(uniq)]
    return out


async def measure_browser(url: str, browser: str, shots: pathlib.Path | None) -> dict:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    helpers = HELPERS.read_text(encoding="utf-8")
    phases: dict[str, dict] = {}
    async with streamablehttp_client(browser) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            d = Driver(s, url, helpers, shots)
            for width in WIDTHS:
                ph: dict[str, dict] = {}
                for name, fn in (
                    ("walk", d.walk),
                    ("ui", d.ui),
                    ("hover", d.hover),
                    ("focus", d.focus),
                    ("normal", d.normal_motion),
                    ("reduced", d.reduced_motion),
                ):
                    try:
                        ph[name] = await fn(width)
                        if name in ("normal", "reduced"):
                            ph[name] = _sorted_motion(ph[name])
                    except (
                        Exception
                    ) as e:  # recorded as a could-not-measure row, never a pass
                        ph[name] = {"error": f"{type(e).__name__}: {e}"[:300]}
                phases[width] = ph
            try:
                await s.call_tool("browser_close", {})
            except Exception:
                pass
    return phases


# ---------------------------------------------------------------- speed (pinned local Lighthouse)


def lighthouse_once(url: str, tool: pathlib.Path, chrome: pathlib.Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="bi-lh-") as tmp:
        out = pathlib.Path(tmp) / "lh.json"
        cmd = [
            str(tool / "node_modules" / ".bin" / "lighthouse"),
            url,
            "--quiet",
            "--only-categories=performance",
            "--output=json",
            f"--output-path={out}",
            "--chrome-flags=--headless=new --no-sandbox --disable-gpu",
        ]
        env = dict(os.environ, CHROME_PATH=str(chrome))
        p = subprocess.run(
            cmd, cwd=tool, env=env, capture_output=True, text=True, timeout=300
        )
        if p.returncode != 0 or not out.exists():
            raise RuntimeError(
                f"lighthouse exit {p.returncode}: {(p.stderr or p.stdout)[-300:]}"
            )
        lhr = json.loads(out.read_text())
    audits = lhr.get("audits") or {}

    def num(k):
        v = (audits.get(k) or {}).get("numericValue")
        return float(v) if isinstance(v, (int, float)) else None

    nodes: dict[str, list] = {}
    # Lighthouse 13 keeps the LCP element in its lcp-breakdown insight and shifted nodes in layout-shifts.
    for check, audit in (("lcp", "lcp-breakdown-insight"), ("cls", "layout-shifts")):
        found: list[dict] = []
        _lighthouse_nodes((audits.get(audit) or {}).get("details") or {}, found)
        nodes[check] = found[:MAX_EVIDENCE]
    return {
        "lcp": num("largest-contentful-paint"),
        "cls": num("cumulative-layout-shift"),
        "tbt": num("total-blocking-time"),
        "nodes": nodes,
        "lighthouse": lhr.get("lighthouseVersion"),
        "chrome": (lhr.get("environment") or {}).get("hostUserAgent"),
    }


def _lighthouse_nodes(o, found: list[dict]) -> None:
    """Every node item (selector, label, box) inside a Lighthouse audit's details, in order."""
    if isinstance(o, dict):
        if o.get("type") == "node" and o.get("selector"):
            r = o.get("boundingRect") or {}
            found.append(
                {
                    "selector": o["selector"],
                    "text": (o.get("nodeLabel") or "")[:80],
                    "box": [
                        r.get("left", 0),
                        r.get("top", 0),
                        r.get("width", 0),
                        r.get("height", 0),
                    ],
                }
            )
        for v in o.values():
            _lighthouse_nodes(v, found)
    elif isinstance(o, list):
        for v in o:
            _lighthouse_nodes(v, found)


def read_load() -> float:
    """The 1-minute load average: the first number in /proc/loadavg."""
    return float(pathlib.Path("/proc/loadavg").read_text().split()[0])


def gated_runs(once, load=None, clock=None, sleep=None) -> dict:
    """SPEED_RUNS Lighthouse runs, each on a quiet machine (H3d, queue #110).

    once() is one Lighthouse run; load, clock and sleep default to read_load,
    time.monotonic and time.sleep. Before each run the 1-minute load must be under
    LOAD_GATE, or the step waits LOAD_POLL_S and reads it again. A run whose after-reading
    is LOAD_GATE or more is thrown away (kept under "dropped") and redone. LOAD_WAIT_S from
    the step's start, checked before each wait and each run, ends the step: with fewer than
    SPEED_RUNS quiet runs, "error" says why, and score_speed makes the speed rows null
    (could not measure), never met or not met.
    """
    load = load or read_load
    clock = clock or time.monotonic
    sleep = sleep or time.sleep
    runs: list[dict] = []
    dropped: list[dict] = []
    nodes: dict = {}
    meta: dict = {}
    waited, polls = 0.0, 0
    busy: float | None = None
    error: str | None = None
    start = clock()
    try:
        while len(runs) < SPEED_RUNS:
            if clock() - start >= LOAD_WAIT_S:
                error = (
                    f"could not measure: machine busy (load {busy:.2f})"
                    if busy is not None
                    else f"could not measure: {len(runs)} of {SPEED_RUNS} quiet runs"
                    f" in {LOAD_WAIT_S} s"
                )
                break
            before = load()
            if before >= LOAD_GATE:
                busy = before
                t0 = clock()
                sleep(LOAD_POLL_S)
                waited += clock() - t0
                polls += 1
                continue
            r = once()
            after = load()
            run_nodes = r.pop("nodes", None) or {}
            meta = {
                "lighthouse": r.pop("lighthouse", None),
                "chrome": r.pop("chrome", None),
            }
            rec = {
                k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()
            }
            rec.update(load_before=before, load_after=after)
            if after >= LOAD_GATE:
                busy = after
                dropped.append(rec)
                continue
            nodes = nodes or run_nodes
            runs.append(rec)
    except Exception as e:
        error = f"{type(e).__name__}: {e}"[:300]
    speed = {
        "runs": runs,
        "dropped": dropped,
        "gate": {
            "load_limit": LOAD_GATE,
            "poll_s": LOAD_POLL_S,
            "cap_s": LOAD_WAIT_S,
            "waited_s": round(waited, 1),
            "polls": polls,
            "redone": len(dropped),
            "elapsed_s": round(clock() - start, 1),
            "busy_load": busy,
        },
        "nodes": nodes,
        **meta,
    }
    if error:
        speed["error"] = error
    return speed


def measure_speed(
    site: pathlib.Path, page: str, tool: pathlib.Path, chrome: pathlib.Path
) -> dict:
    import design_capture as dc

    base, srv = dc.serve(site, "127.0.0.1")
    url = base + "/" + urllib.parse.quote(page.lstrip("/"))
    try:
        return gated_runs(lambda: lighthouse_once(url, tool, chrome))
    finally:
        srv.shutdown()


# ---------------------------------------------------------------- CLI


def measure(site: pathlib.Path, page: str, args, shots: pathlib.Path | None) -> dict:
    import design_capture as dc

    html = (site / page).read_bytes()
    browser = urllib.parse.urlparse(args.browser)
    base, srv = dc.serve(site, args.serve_host or browser.hostname)
    try:
        url = base + "/" + urllib.parse.quote(page.lstrip("/"))
        phases = asyncio.run(measure_browser(url, args.browser, shots))
    finally:
        srv.shutdown()
    speed = (
        measure_speed(
            site, page, pathlib.Path(args.lighthouse), pathlib.Path(args.chrome)
        )
        if not args.no_speed
        else {"runs": [], "error": "speed not measured (--no-speed)"}
    )
    return {
        "meter": METER,
        "version": VERSION,
        "page": str(site / page),
        "page_sha256": hashlib.sha256(html).hexdigest(),
        "phases": phases,
        "speed": speed,
    }


def write_outputs(out: pathlib.Path, raw: dict | None, doc: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    if raw is not None:
        (out / "raw-interact.json").write_text(
            json.dumps(raw, indent=1, sort_keys=True) + "\n"
        )
    (out / "bars-interact.json").write_text(json.dumps(doc, indent=1) + "\n")
    (out / "bars-interact.md").write_text(to_md(doc))


def fixture_proof(args) -> int:
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = []
    for name in FIXTURE_SETS:
        fixtures = FIXTURES.parent / name
        key = json.loads((fixtures / "expected.json").read_text())
        for page, spec in key["pages"].items():
            stem = page.rsplit(".", 1)[0]
            if args.from_raw:
                raw = json.loads(
                    (
                        pathlib.Path(args.from_raw) / name / "raw" / f"{stem}.json"
                    ).read_text()
                )
            else:
                raw = measure(fixtures, page, args, out / name / stem / "shots")
                raw["page"] = f"{name}/{page}"
                if args.record:
                    (fixtures / "raw").mkdir(exist_ok=True)
                    (fixtures / "raw" / f"{stem}.json").write_text(
                        json.dumps(raw, indent=1, sort_keys=True) + "\n"
                    )
            doc = score(raw)
            write_outputs(out / name / stem, raw, doc)
            got, nulls = failing(doc), unmeasured(doc)
            want = {tuple(x) for x in spec["failing"]}
            verdict = page_verdict(doc, want)
            extra, missing = sorted((got - nulls) - want), sorted(want - got)
            report.append(
                {
                    "set": name,
                    "page": page,
                    "match": verdict == "match",
                    "verdict": verdict,
                    "extra": extra,
                    "missing": missing,
                    "unmeasured": sorted(nulls),
                }
            )
            if verdict == "match":
                line = f"MATCH {name}/{page}"
            elif verdict == "differ":
                line = f"DIFF  {name}/{page}  extra={extra} missing={missing}"
            else:
                why = sorted({_reason(r) for r in doc["rows"] if r["pass"] is None})
                line = (
                    f"COULD NOT MEASURE {name}/{page}  rows={sorted(nulls)}:"
                    f" {'; '.join(why)}"
                )
            print(line, flush=True)
    counts = {
        v: sum(p["verdict"] == v for p in report)
        for v in ("match", "differ", "could not measure")
    }
    (out / "fixture-proof.json").write_text(
        json.dumps(
            {
                "all_match": counts["match"] == len(report),
                "match": counts["match"],
                "differ": counts["differ"],
                "could_not_measure": counts["could not measure"],
                "pages": report,
            },
            indent=1,
        )
        + "\n"
    )
    print(
        f"fixture proof: {counts['match']}/{len(report)} pages match,"
        f" {counts['differ']} differ, {counts['could not measure']} could not measure",
        flush=True,
    )
    if counts["differ"]:
        return 1
    return 3 if counts["could not measure"] else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--site")
    ap.add_argument("--page", default="index.html")
    ap.add_argument("--out", required=True)
    ap.add_argument("--browser", default="http://playwright-mcp:8931/mcp")
    ap.add_argument(
        "--serve-host",
        default="",
        help="host whose route picks the address the browser loads pages from",
    )
    ap.add_argument("--lighthouse", default=str(TOOL_DIR))
    ap.add_argument("--chrome", default=str(CHROME))
    ap.add_argument(
        "--no-speed",
        action="store_true",
        help="skip Lighthouse (the speed rows could not be measured)",
    )
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--raw-only", action="store_true")
    g.add_argument("--from-raw")
    ap.add_argument("--fixture-proof", action="store_true")
    ap.add_argument("--record", action="store_true")
    args = ap.parse_args(argv)
    if args.fixture_proof:
        return fixture_proof(args)
    out = pathlib.Path(args.out)
    if args.from_raw:
        raw = json.loads(
            (pathlib.Path(args.from_raw) / "raw-interact.json").read_text()
        )
        write_outputs(out, None, score(raw))
        return 0
    if not args.site:
        ap.error("--site is required")
    site = pathlib.Path(args.site).resolve()
    raw = measure(site, args.page, args, out / "shots")
    if args.raw_only:
        out.mkdir(parents=True, exist_ok=True)
        (out / "raw-interact.json").write_text(
            json.dumps(raw, indent=1, sort_keys=True) + "\n"
        )
        return 0
    doc = score(raw)
    write_outputs(out, raw, doc)
    print(to_md(doc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
