"""Carry a page's CSS layout into Penpot 2.18.1 flex and grid layouts (HTML -> Penpot converter).

The browser tells us how every element was laid out (display, flex and grid properties, gaps,
padding, margins, natural sizes; html_dom_extract.js) and where everything ended up. For each
board this module picks the Penpot layout that reproduces that arrangement, checks it with a
model of Penpot's own flex and grid algorithms (common/geom/shapes/{flex,grid}_layout in Penpot
2.18.1), and otherwise falls back step by step:

  semantic   CSS flex -> Penpot flex, CSS grid -> Penpot grid (same gaps, alignment, sizing)
  column     block flow -> a Penpot column, with the measured spacing as gap and margins
  row        side-by-side children -> a Penpot row with measured margins
  positioned no layout: layers keep their positions (reported: that board won't reflow)

So a designer can edit the result naturally: texts grow (auto-height, or auto-width for one-line
labels), boards hug their content, and a longer text pushes its siblings and the sections below.
Penpot only passes a text's growth up through boards that hug, so in a row of stretched items the
tallest one hugs (it sets the row height, as in CSS) and the others fill.

Pure functions; the plan is written onto the scene nodes as n["pp"]:
  boards:   mode ("flex" | "grid" | None), attrs (Penpot container attrs, kebab-case), order (flow
            children in layout order), cells (grid placements), kind (how it was mapped), why
            (fallback reasons), notes, hug [w | None, h | None] (sizes the board hugs at, if it can)
  children: item (layout-item attrs) when the parent has a layout
  texts:    grow ("auto-height" | "auto-width"), box (planned [x, y, w, h]), delta (how far the
            planned box reaches past the browser's on each side: left, top, right, bottom)
"""
from __future__ import annotations

import math
import re
from typing import Any

TOL = 1.01      # px: how close Penpot's layout must land to the browser's
HUG_TOL = 1.5   # px: a board hugs its content when Penpot's hug size is this close
SLACK = 2.0     # extra width for wrapping texts (task #5): Penpot breaks lines a hair wider
WRAP_MARGIN = 2.0  # px kept from both ends of the widths at which Penpot breaks a text as the browser did
INF = float("inf")
JUSTIFY = {"flex-start": "start", "start": "start", "left": "start", "normal": "start", "stretch": "start",
           "center": "center", "flex-end": "end", "end": "end", "right": "end",
           "space-between": "space-between", "space-around": "space-around", "space-evenly": "space-evenly"}
ALIGN = {"flex-start": "start", "start": "start", "self-start": "start", "normal": "start", "stretch": "start",
         "baseline": "start", "first baseline": "start", "last baseline": "end",
         "center": "center", "flex-end": "end", "end": "end", "self-end": "end"}
LINES = {"normal": "stretch", "stretch": "stretch", "flex-start": "start", "start": "start",
         "center": "center", "flex-end": "end", "end": "end"}
TRACKS = {**JUSTIFY, "normal": "stretch", "stretch": "stretch"}


def _r(v: float) -> float:
    return round(float(v), 2)


def _box(n: dict) -> list[float]:
    b = n["box"]
    return [float(b["x"]), float(b["y"]), float(b["w"]), float(b["h"])]


def _kw(v: str | None, table: dict, default: str) -> str:
    v = re.sub(r"^(safe|unsafe)\s+", "", (v or "").strip())
    return table.get(v, default)


def _pp(n: dict) -> dict:
    return n.setdefault("pp", {})


def _ceil(v: float) -> float:
    return max(1.0, float(math.ceil(v - 0.05)))


# --------------------------------------------------------------------------
# Texts
# --------------------------------------------------------------------------

def _rows(frags: list[dict], lh: float) -> list[dict]:
    """Line rows of a text's glyph boxes (a frag's y is its bottom, as in Penpot's position-data)."""
    rows: list[dict] = []
    for f in sorted(frags, key=lambda f: float(f["y"])):
        if rows and abs(float(f["y"]) - rows[-1]["bottom"]) <= lh / 2:
            if float(f["h"]) > rows[-1]["h"]:
                rows[-1].update(h=float(f["h"]), bottom=float(f["y"]))
            continue
        rows.append({"bottom": float(f["y"]), "h": float(f["h"])})
    return rows


def line_boxes(n: dict) -> tuple[float, float] | None:
    """(top, height) of a text's CSS line boxes. The browser reports glyph boxes, which overflow
    tight line-heights (display type) and underfill loose ones (body text); Penpot lays a re-measured
    text out line box by line box, so the text's box must be its line boxes. Each glyph box is
    centred on its line box (half-leading), so the rows' centres give the line boxes."""
    t = n.get("text") or {}
    lh = float(t.get("lineHeight") or 0)
    frags = [f for f in t.get("lines") or [] if f.get("h")]
    if lh <= 0 or not frags:
        return None
    rows = _rows(frags, lh)
    first, last = rows[0]["bottom"] - rows[0]["h"] / 2, rows[-1]["bottom"] - rows[-1]["h"] / 2
    return first - lh / 2, last - first + lh


def wrap_width(t: dict, w: float) -> tuple[float, bool] | None:
    """The text box width nearest `w` at which Penpot breaks the lines where the browser did, and
    whether one exists. Penpot lays text out like CSS `white-space: break-spaces`: the space at a
    line's end must fit on that line (the browser drops it), and the next line's first word comes
    up once it fits with its own space. `t["wrap"]` holds the browser's facts per line (from the
    extractor): ink width w, what ended it k (space | end | char), that space's width sp, and the
    first word fw with the space after it fsp. None when the text has no such facts."""
    rows = t.get("wrap") or []
    if not rows:
        return None
    lo, hi = 0.0, INF
    for i, r in enumerate(rows):
        sp = float(r.get("sp") or 0) if r.get("k") == "space" else 0.0
        lo = max(lo, float(r.get("w") or 0) + sp)
        nxt = rows[i + 1] if i + 1 < len(rows) else None
        if r.get("k") == "space" and nxt and nxt.get("fw") is not None:
            after = nxt.get("fsp")
            if after is None:  # a one-word line: the space after its word is the one at its end
                after = nxt.get("sp") if nxt.get("k") == "space" else 0.0
            hi = min(hi, float(r.get("w") or 0) + sp + float(nxt["fw"]) + float(after or 0))
    if hi <= lo:
        return lo + WRAP_MARGIN / 2, False
    m = min(WRAP_MARGIN, (hi - lo) / 2)
    return min(max(w, lo + m), hi - m), True


def text_plan(n: dict) -> dict:
    """How a text grows when edited, and its box: its CSS line boxes (as Penpot measures it), width as
    in task #5. Penpot's editor sizes auto texts to whole pixels (ceil), so the plan does too; how
    far the box reaches past the browser's on each side is kept in `delta` for the margins."""
    t = n.get("text") or {}
    x, y, w, h = _box(n)
    fit = n.get("fit") or "height"
    lines = t.get("lines") or []
    if fit == "width" and not (n.get("item") or {}).get("anon") and lines:
        tight = max(f["x"] + f["w"] for f in lines) - min(f["x"] for f in lines)
        if w - tight > 1.5:  # one line in a wider block: keep the block width, alignment stays inside
            fit = "height"
    frags = [f for f in lines if f.get("h")]
    if fit == "width" and frags and len(_rows(frags, float(t.get("lineHeight") or 0) or min(float(f["h"]) for f in frags))) > 1:
        fit = "height"  # it wraps in the browser: an auto-width text would never wrap
    top, lh_h = line_boxes(n) or (y, h)
    h2 = _ceil(lh_h)
    # the browser lays a text out by its line boxes; display type's glyphs overflow them, and that
    # must not turn into margins: only Penpot's whole-pixel height reaches past them
    dt, db = 0.0, h2 - lh_h
    if fit == "width":
        w2 = _ceil(w)
        return {"grow": "auto-width", "box": [x, top, w2, h2], "delta": [0.0, dt, w2 - w, db]}
    align = t.get("align", "left")
    slack, ok = 0.0 if align == "justify" else SLACK, True
    ww = wrap_width(t, w) if align != "justify" else None
    if ww:  # the width at which Penpot breaks the lines as the browser did, kept centred as aligned
        slack, ok = _r(ww[0] - w), ww[1]
    left = slack / 2 if align == "center" else slack if align in ("right", "end") else 0.0
    plan = {"grow": "auto-height", "box": [x - left, top, w + slack, h2], "delta": [left, dt, slack - left, db]}
    if not ok:  # no width keeps every line: Penpot rewraps it on edit (reported)
        plan["rewrap"] = True
    return plan


# --------------------------------------------------------------------------
# Penpot's flex layout (flex_layout/layout_data.cljc + positions.cljc), main/cross coordinates
# --------------------------------------------------------------------------

def _distribute(mins: list[float], maxs: list[float], total: float) -> list[float]:
    """Penpot's distribute-space: share what is left over equally, capped at each max."""
    sizes = list(mins)
    rest = total - sum(sizes)
    for _ in range(len(sizes) + 1):
        open_ = [i for i in range(len(sizes)) if sizes[i] < maxs[i] - 1e-9]
        if rest <= 1e-9 or not open_:
            break
        share = rest / len(open_)
        rest = 0.0
        for i in open_:
            add = min(share, maxs[i] - sizes[i])
            sizes[i] += add
            rest += share - add
    return sizes


def sim_flex(content: tuple, row: bool, wrap: bool, gap: tuple, justify: str, align: str, lines_align: str,
             items: list[dict], auto_main: bool = False, auto_cross: bool = False) -> tuple[list[tuple], float, float]:
    """Where Penpot puts each item. items: s/t (main/cross size), fm/fc (fill), minm/maxm/minc/maxc,
    ms/me/cs/ce (margins: main start/end, cross start/end), self (align-self or None).
    gap = (row-gap, column-gap). Returns ([(x, y, w, h)], hug width, hug height) of the content box."""
    x0, y0, W, H = content
    m0, c0, M, C = (x0, y0, W, H) if row else (y0, x0, H, W)
    gm, gc = (gap[1], gap[0]) if row else (gap[0], gap[1])
    for i in items:
        i["mn"] = max(0.01, i.get("minm") or 0.01) if i["fm"] else i["s"]
        i["mx"] = (i.get("maxm") or INF) if i["fm"] else i["s"]
        i["cn"] = max(0.01, i.get("minc") or 0.01) if i["fc"] else i["t"]
        i["cx"] = (i.get("maxc") or INF) if i["fc"] else i["t"]
    do_wrap = wrap and not auto_main
    lines: list[list[dict]] = []
    cur: list[dict] = []
    used = 0.0
    for i in items:
        need = i["mn"] + i["ms"] + i["me"]
        if cur and do_wrap and not (used + need + gm * len(cur) < M or abs(used + need + gm * len(cur) - M) <= 0.5):
            lines.append(cur)
            cur, used = [], 0.0
        cur.append(i)
        used += need
    if cur:
        lines.append(cur)
    data = []
    for ln in lines:
        n = len(ln)
        mn = sum(i["mn"] + i["ms"] + i["me"] for i in ln)
        mx = sum(i["mx"] + i["ms"] + i["me"] for i in ln)
        main = mn if auto_main else max(mn, min(M - gm * (n - 1), mx))
        data.append({"items": ln, "n": n, "mn": mn, "main": main,
                     "cmn": max(i["cn"] + i["cs"] + i["ce"] for i in ln),
                     "cmx": max(i["cx"] + i["cs"] + i["ce"] for i in ln)})
    nl = len(data)
    rest = C - gc * (nl - 1)
    tmin, tmax = sum(d["cmn"] for d in data), sum(d["cmx"] for d in data)
    fix = (rest - tmax) / nl if (lines_align == "stretch" and not auto_cross and tmax <= rest) else 0.0
    if auto_cross or tmin >= rest:
        for d in data:
            d["cross"] = d["cmn"]
    if not auto_cross and tmax <= rest:
        for d in data:
            d["cross"] = d["cmx"] + fix
    if not auto_cross and tmin < rest < tmax:
        for d, s in zip(data, _distribute([d["cmn"] for d in data], [d["cmx"] for d in data], rest), strict=True):
            d["cross"] = s
    total = sum(d["cross"] for d in data)
    cpos = c0
    key = lines_align if do_wrap else align
    if not auto_cross:
        free = C - total - gc * (nl - 1)
        cpos += free / 2 if key == "center" else free if key == "end" else 0.0
    line_gap = gc if (auto_cross or lines_align != "stretch") else max(gc, (C - total) / nl)
    out: dict[int, tuple] = {}
    for d in data:
        ln, n = d["items"], d["n"]
        sizes = {id(i): i["mn"] for i in ln}
        fills = [i for i in ln if i["fm"]]
        if fills and d["main"] > d["mn"]:
            grown = _distribute([i["mn"] for i in fills], [i["mx"] for i in fills],
                                sum(i["mn"] for i in fills) + d["main"] - d["mn"])
            for i, s in zip(fills, grown, strict=True):
                sizes[id(i)] = s
        g, lead, start = gm, 0.0, m0
        if justify == "center":
            start = m0 + M / 2 - (d["main"] + gm * (n - 1)) / 2
        elif justify == "end":
            start = m0 + M - (d["main"] + gm * (n - 1))
        elif auto_main and justify in ("space-around", "space-evenly"):
            lead, g = gm, 0.0
        elif justify == "space-between" and not auto_main and n > 1:
            g = max(gm, (M - d["main"]) / (n - 1))
        elif justify == "space-around":
            lead = max(gm, (M - d["main"]) / n) / 2
            g = lead
        elif justify == "space-evenly":
            lead, g = max(gm, (M - d["main"]) / (n + 1)), 0.0
        pos = start
        for i in ln:
            s = sizes[id(i)]
            t = min(max(d["cross"] - i["cs"] - i["ce"], i["cn"]), i["cx"]) if i["fc"] else i["t"]
            a = i.get("self") or align
            if a == "center":
                cp = cpos + d["cross"] / 2 - t / 2 + (i["cs"] - i["ce"]) / 2
            elif a == "end":
                cp = cpos + d["cross"] - t - i["ce"]
            else:
                cp = cpos + i["cs"]
            mp = pos + i["ms"] + lead  # Penpot's margin-x/-y: once before each item
            out[id(i)] = (mp, cp, s, t) if row else (cp, mp, t, s)
            pos = mp + s + i["me"] + g
        cpos += d["cross"] + line_gap
    hug_main = max(d["mn"] + gm * (d["n"] - 1) for d in data)
    hug_cross = sum(d["cmn"] for d in data) + gc * (nl - 1)
    hw, hh = (hug_main, hug_cross) if row else (hug_cross, hug_main)
    return [out[id(i)] for i in items], hw, hh


# --------------------------------------------------------------------------
# Penpot's grid layout (grid_layout/layout_data.cljc + positions.cljc)
# --------------------------------------------------------------------------

def _tracks_px(tracks: list[dict], total: float, gap: float, needs: list[tuple], auto: bool, content: str) -> list[float]:
    """Track sizes. needs: (start index, span, min size incl. margins) of each child."""
    size, mx = [], []
    for t in tracks:
        if t["type"] == "fixed":
            size.append(float(t["value"]))
        elif t["type"] == "percent":
            size.append(total * t["value"] / 100)
        else:
            size.append(0.01)
        mx.append(size[-1] if t["type"] in ("fixed", "percent") else INF)
    for start, span, need in needs:
        if span == 1 and tracks[start]["type"] in ("flex", "auto"):
            size[start] = max(size[start], need)
    for start, span, need in needs:  # spanning children with no flex track: grow the auto tracks
        idx = list(range(start, min(start + span, len(tracks))))
        if span > 1 and not any(tracks[k]["type"] == "flex" for k in idx):
            have = sum(size[k] for k in idx) + gap * (span - 1)
            autos = [k for k in idx if tracks[k]["type"] == "auto"]
            if need > have and autos:
                for k in autos:
                    size[k] += (need - have) / len(autos)
    gaps = gap * (len(tracks) - 1)
    flex = [k for k, t in enumerate(tracks) if t["type"] == "flex"]
    if flex and auto:
        fr = max([0.01] + [size[k] / tracks[k]["value"] for k in flex])
        for k in flex:
            size[k] = max(size[k], fr * tracks[k]["value"])
    elif flex:  # Penpot's set-fr-value: fr from sum(max(1, fr)); tracks below their minimum keep it
        space = max(0.0, total - sum(size[k] for k in range(len(tracks)) if k not in flex) - gaps)
        fr = space / sum(max(1.0, float(tracks[k]["value"])) for k in flex)
        assign = {k: fr * tracks[k]["value"] for k in flex}
        for _ in range(len(flex) + 1):
            pending, free_frs = 0.0, 0.0
            for k in flex:
                if assign[k] <= size[k]:
                    pending += size[k] - assign[k]
                    assign[k] = size[k]
                else:
                    free_frs += tracks[k]["value"]
            if free_frs == 0 or abs(pending) < 1e-9:
                break
            for k in flex:
                if assign[k] > size[k]:
                    assign[k] -= pending / free_frs * tracks[k]["value"]
        for k in flex:
            size[k] = max(size[k], assign[k])
    if content == "stretch" and not auto:
        autos = [k for k, t in enumerate(tracks) if t["type"] == "auto"]
        if autos:
            add = max(0.0, total - sum(size) - gaps) / len(autos)
            for k in autos:
                size[k] = min(size[k] + add, mx[k])
    return size


def _track_starts(size: list[float], start: float, total: float, gap: float, content: str, auto: bool) -> list[float]:
    used = sum(size) + gap * (len(size) - 1)
    g, pos = gap, start
    if not auto:
        free = total - used
        n = len(size)
        if content == "center":
            pos += free / 2
        elif content == "end":
            pos += free
        elif content == "space-between" and n > 1:
            g = max(gap, (total - sum(size)) / (n - 1))
        elif content == "space-around":
            g = max(gap, (total - sum(size)) / n)
            pos += g / 2
        elif content == "space-evenly":
            g = max(gap, (total - sum(size)) / (n + 1))
            pos += g
    out = []
    for s in size:
        out.append(pos)
        pos += s + g
    return out


def _grid_pos(a: str, a0: float, asz: float, size: float, ms: float, me: float, vertical: bool) -> float:
    """A child's position in its grid area (Penpot's quirk: vertical centering doesn't halve margins)."""
    if a == "end":
        return a0 + asz - me - size
    if a == "center":
        return a0 + asz / 2 + (ms - me if vertical else ms / 2 - me / 2) - size / 2
    return a0 + ms


def sim_grid(content: tuple, cols: list[dict], rows: list[dict], gap: tuple, justify_c: str, align_c: str,
             cells: list[dict], auto_w: bool = False, auto_h: bool = False) -> tuple[list[tuple], float, float]:
    """cells: r, c (0-based), rs, cs (spans), w, h, fw, fh (fill), minw/minh (Penpot's min incl. content),
    maxw/maxh, m [t, r, b, l], js/al (start | center | end). Returns boxes and hug size of the content box."""
    x0, y0, W, H = content
    cw = _tracks_px(cols, W, gap[1], [(c["c"], c["cs"], (c["minw"] if c["fw"] else c["w"]) + c["m"][1] + c["m"][3])
                                     for c in cells], auto_w, justify_c)
    rh = _tracks_px(rows, H, gap[0], [(c["r"], c["rs"], (c["minh"] if c["fh"] else c["h"]) + c["m"][0] + c["m"][2])
                                     for c in cells], auto_h, align_c)
    xs = _track_starts(cw, x0, W, gap[1], justify_c, auto_w)
    ys = _track_starts(rh, y0, H, gap[0], align_c, auto_h)
    out = []
    for c in cells:
        ax, ay = xs[c["c"]], ys[c["r"]]
        aw = sum(cw[c["c"]:c["c"] + c["cs"]]) + gap[1] * (c["cs"] - 1)
        ah = sum(rh[c["r"]:c["r"] + c["rs"]]) + gap[0] * (c["rs"] - 1)
        mt, mr, mb, ml = c["m"]
        w = min(max(aw - ml - mr, c.get("minw") or 0.01), c.get("maxw") or INF) if c["fw"] else c["w"]
        h = min(max(ah - mt - mb, c.get("minh") or 0.01), c.get("maxh") or INF) if c["fh"] else c["h"]
        x = _grid_pos("start" if c["fw"] else c["js"], ax, aw, w, ml, mr, False)
        y = _grid_pos("start" if c["fh"] else c["al"], ay, ah, h, mt, mb, True)
        out.append((x, y, w, h))
    hug_w = sum(cw) + gap[1] * (len(cw) - 1)
    hug_h = sum(rh) + gap[0] * (len(rh) - 1)
    return out, hug_w, hug_h


def _split_top(s: str) -> list[str]:
    out, depth, cur = [], 0, ""
    for ch in s:
        depth += (ch == "(") - (ch == ")")
        if ch.isspace() and depth == 0:
            if cur:
                out.append(cur)
            cur = ""
        else:
            cur += ch
    if cur:
        out.append(cur)
    return [t for t in out if not t.startswith("[")]


def _track(tok: str) -> dict | None:
    tok = tok.strip()
    m = re.fullmatch(r"([\d.]+)fr", tok)
    if m:
        return {"type": "flex", "value": float(m.group(1))}
    m = re.fullmatch(r"([\d.]+)px", tok)
    if m:
        return {"type": "fixed", "value": float(m.group(1))}
    m = re.fullmatch(r"([\d.]+)%", tok)
    if m:
        return {"type": "percent", "value": float(m.group(1))}
    if tok in ("auto", "min-content", "max-content") or tok.startswith("fit-content("):
        return {"type": "auto", "value": 1}
    m = re.fullmatch(r"minmax\((.+)\)", tok)
    if m:
        parts = [p.strip() for p in m.group(1).split(",")]
        hi = _track(parts[-1]) if len(parts) == 2 else None
        if hi and hi["type"] in ("flex", "fixed"):
            return hi
        return {"type": "auto", "value": 1} if hi else None
    return None


def parse_tracks(spec: str | None, count: int) -> list[dict] | None:
    """An author's grid-template list -> Penpot tracks, or None when it can't say it in `count` tracks."""
    if not spec or spec.strip() in ("none", "") or "var(" in spec or "calc(" in spec or "subgrid" in spec:
        return None
    fixed: list[Any] = []
    for tok in _split_top(spec):
        m = re.fullmatch(r"repeat\(\s*([^,]+),(.+)\)", tok, re.S)
        if m:
            inner = [_track(x) for x in _split_top(m.group(2))]
            if not inner or None in inner:
                return None
            n = m.group(1).strip()
            if n.isdigit():
                fixed += inner * int(n)
            elif n in ("auto-fit", "auto-fill"):
                fixed.append(("auto-repeat", inner))
            else:
                return None
            continue
        t = _track(tok)
        if t is None:
            return None
        fixed.append(t)
    autos = [x for x in fixed if isinstance(x, tuple)]
    if len(autos) > 1:
        return None
    if autos:
        inner = autos[0][1]
        reps, left = divmod(count - (len(fixed) - 1), len(inner))
        if left or reps < 1:
            return None
        out: list[dict] = []
        for x in fixed:
            out += inner * reps if isinstance(x, tuple) else [x]
        fixed = out
    if len(fixed) != count:
        return None
    out = [dict(t) for t in fixed]
    # Penpot shares the free space by sum(max(1, fr)), so a track under 1fr leaves space unused;
    # scaled so the smallest is 1fr, the tracks keep CSS's ratios (CSS only differs below 1fr in all)
    frs = [t["value"] for t in out if t["type"] == "flex"]
    if frs and min(frs) < 1 <= sum(frs) and min(frs) > 0:
        k = 1 / min(frs)
        for t in out:
            if t["type"] == "flex":
                t["value"] = round(t["value"] * k, 4)
    return out


# --------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------

def width_spec(spec: str | None) -> tuple[bool, float | None, float | None]:
    """An author's width rule -> (follows its parent, px cap inside min(), px gutter of a 100% - Npx)."""
    if not spec:
        return False, None, None
    s = re.sub(r"\s+", "", spec)
    fluid = "%" in s or s in ("auto", "stretch", "-webkit-fill-available", "fill-available")
    cap = gutter = None
    g = re.search(r"(?:^|[(,])(?:calc\()?100%-([\d.]+)px\)?(?:$|[),])", s)
    if g:
        gutter = float(g.group(1))
    m = re.fullmatch(r"min\((.*)\)", s)
    if m:
        depth, cur, args = 0, "", []
        for ch in m.group(1):
            depth += (ch == "(") - (ch == ")")
            if ch == "," and depth == 0:
                args.append(cur)
                cur = ""
            else:
                cur += ch
        args.append(cur)
        caps = [float(a[:-2]) for a in args if re.fullmatch(r"[\d.]+px", a)]
        cap = min(caps) if caps else None
    return fluid, cap, gutter


def _is_zero(c: dict) -> bool:
    return c["kind"] == "board" and (c["box"]["w"] < 0.5 or c["box"]["h"] < 0.5)


def _promoted(c: dict) -> list[dict]:
    """Layers the Builder lifts out of a zero-size board into its parent."""
    out = []
    for g in c.get("children", []):
        out += _promoted(g) if _is_zero(g) else [g]
    return out


def _split(n: dict) -> tuple[list[dict], list[dict]]:
    """Children that take part in the layout, and the ones that keep their own position."""
    flow, other = [], []
    for c in n.get("children", []):
        it = c.get("item") or {}
        if _is_zero(c) or c.get("deco") or it.get("pos") in ("absolute", "fixed") or it.get("float") or it.get("offset"):
            other.append(c)
        else:
            flow.append(c)
    return flow, other


def _info(c: dict, css_margins: bool) -> dict:
    pp = c.get("pp") or {}
    it = c.get("item") or {}
    m = [float(v) for v in (it.get("margin") or [0, 0, 0, 0])] if css_margins else [0.0, 0.0, 0.0, 0.0]
    if css_margins:  # the planned text box keeps the browser's margin box: its margins absorb the extra reach
        dl, dt, dr, db = pp.get("delta") or [0.0, 0.0, 0.0, 0.0]
        m = [m[0] - dt, m[1] - dr, m[2] - db, m[3] - dl]
    return {"n": c, "box": list(pp["box"]) if "box" in pp else _box(c), "it": it, "m": m,
            "hug": pp.get("hug") or [None, None], "text": pp.get("grow"), "layout": pp.get("mode") is not None,
            "delta": list(pp.get("delta") or [0.0, 0.0, 0.0, 0.0]), "align": None, "minmax": {}}


def _hugs(f: dict, axis: int) -> bool:
    return f["layout"] and f["hug"][axis] is not None


def _stretched(f: dict, row: bool) -> bool:
    """Grown on the cross axis by the parent (its natural size is smaller)."""
    nat = f["it"].get("nat")
    if not nat:
        return False
    b = _box(f["n"])
    return (nat["h"] if row else nat["w"]) < (b[3] if row else b[2]) - 0.5


def _main_sizing(f: dict, row: bool, grow: bool = True) -> str:
    if grow and float(f["it"].get("grow") or 0) > 0:
        return "fill"
    if f["text"] == "auto-width":
        return "auto"
    if f["text"] == "auto-height":
        return "fix" if row else "auto"
    return "auto" if _hugs(f, 0 if row else 1) else "fix"


def _cross_sizing(f: dict, row: bool) -> str:
    if f["text"] == "auto-width" or (f["text"] and row):
        return "auto"
    if _stretched(f, row):
        return "fill"
    if f["text"]:
        return "fix"
    return "auto" if _hugs(f, 1 if row else 0) else "fix"


def _cross_align(pos: float, size: float, c0: float, csz: float, ms: float, me: float, prefer: str) -> tuple[str, float, float]:
    """Penpot flex cross alignment that puts a child where the browser did (else start + margin)."""
    for a in [prefer] + [x for x in ("start", "center", "end") if x != prefer]:
        p = c0 + ms if a == "start" else c0 + csz / 2 - size / 2 + (ms - me) / 2 if a == "center" else c0 + csz - size - me
        if abs(p - pos) <= TOL:
            return a, ms, me
    return "start", pos - c0, me


def _grid_align(pos: float, size: float, a0: float, asz: float, ms: float, me: float, vertical: bool) -> tuple[str, float, float]:
    for a in ("start", "center", "end"):
        if abs(_grid_pos(a, a0, asz, size, ms, me, vertical) - pos) <= TOL:
            return a, ms, me
    return "start", pos - a0, me


def _pad(L: dict) -> list[float]:
    return [float(v) for v in (L.get("pad") or [0, 0, 0, 0])]


def _content(n: dict) -> tuple[float, float, float, float]:
    x, y, w, h = _box(n)
    t, r, b, lft = _pad(n.get("layout") or {})
    return x + lft, y + t, w - lft - r, h - t - b


def _container(mode: str, L: dict, **kw: Any) -> dict:
    t, r, b, lft = _pad(L)
    gap = kw.get("gap", (0.0, 0.0))
    a: dict[str, Any] = {"layout": mode, "layout-gap-type": "multiple",
                         "layout-gap": {"row-gap": _r(gap[0]), "column-gap": _r(gap[1])},
                         "layout-padding-type": "multiple",
                         "layout-padding": {"p1": _r(t), "p2": _r(r), "p3": _r(b), "p4": _r(lft)},
                         "layout-justify-content": kw.get("justify", "start"),
                         "layout-align-items": kw.get("align", "start"), "layout-align-content": kw.get("lines", "start")}
    if mode == "flex":
        a.update({"layout-flex-dir": kw["dir"], "layout-wrap-type": "wrap" if kw.get("wrap") else "nowrap"})
    else:
        a.update({"layout-grid-dir": "row", "layout-grid-columns": kw["cols"], "layout-grid-rows": kw["rows"],
                  "layout-justify-items": "start"})
    return a


def _item(f: dict, absolute: bool = False, z: int = 0) -> dict:
    m = f["m"]
    a: dict[str, Any] = {"layout-item-h-sizing": f["hs"], "layout-item-v-sizing": f["vs"],
                         "layout-item-margin-type": "multiple",
                         "layout-item-margin": {"m1": _r(m[0]), "m2": _r(m[1]), "m3": _r(m[2]), "m4": _r(m[3])}}
    if f.get("align"):
        a["layout-item-align-self"] = f["align"]
    if absolute:
        a["layout-item-absolute"] = True
    if z:
        a["layout-item-z-index"] = z
    for k, v in (f.get("minmax") or {}).items():
        a[f"layout-item-{k}"] = _r(v)
    return a


def _z_ranks(children: list[dict]) -> dict[int, int]:
    keys = sorted({float(c.get("z") or 0) for c in children})
    ranks = {0.0: 0}
    for i, k in enumerate(k for k in keys if k > 0):
        ranks[k] = i + 1
    for i, k in enumerate(k for k in reversed(keys) if k < 0):
        ranks[k] = -(i + 2)
    return {id(c): ranks.get(float(c.get("z") or 0), 0) for c in children}


def _close(a: list | tuple, b: list | tuple) -> bool:
    return all(abs(float(p) - float(q)) <= TOL for p, q in zip(a, b, strict=False))


def _check(infos: list[dict], boxes: list[tuple]) -> str | None:
    for f, b in zip(infos, boxes, strict=False):
        if not _close(b, f["box"]):
            name = str(f["n"].get("name") or f["n"]["kind"])[:60]
            return f"{name} would land at {[_r(v) for v in b]}, browser {[_r(v) for v in f['box']]}"
    return None


def _sizes(f: dict, hug: bool) -> tuple[float, float]:
    w, h = f["box"][2], f["box"][3]
    if hug and f["layout"]:
        if f["hs"] == "auto" and f["hug"][0] is not None:
            w = f["hug"][0]
        if f["vs"] == "auto" and f["hug"][1] is not None:
            h = f["hug"][1]
    return w, h


def _content_min(f: dict, strict: bool) -> list[float] | None:
    """Penpot's minimum for a filling board with a layout (min_size_layout): a grid board never
    shrinks below its content; a flex board doesn't either in a grid cell (strict), but in a flex
    parent it shrinks to its min-width like a board without a layout."""
    pp = f["n"].get("pp") or {}
    mode = pp.get("mode") if f["layout"] else None
    return pp.get("content") if mode == "grid" or (strict and mode == "flex") else None


def _floor_min(css_min: float | None, content: float, size: float) -> float:
    """A fill item's minimum: its CSS min-size and its content, which Penpot keeps whole; content
    within rounding of the planned size counts as fitting."""
    low = content if content > size + TOL else min(content, size)
    return max(float(css_min or 0), low)


def _flex_items(infos: list[dict], row: bool, hug: bool = False) -> list[dict]:
    out = []
    for f in infos:
        w, h = _sizes(f, hug)
        m = f["m"]
        mm = f.get("minmax") or {}
        fm, fc = (f["hs"] if row else f["vs"]) == "fill", (f["vs"] if row else f["hs"]) == "fill"
        minm, minc = mm.get("min-w" if row else "min-h"), mm.get("min-h" if row else "min-w")
        cm = _content_min(f, False)
        if cm:
            if fm:
                minm = _floor_min(minm, cm[0] if row else cm[1], w if row else h)
            if fc:
                minc = _floor_min(minc, cm[1] if row else cm[0], h if row else w)
        out.append({"s": w if row else h, "t": h if row else w, "fm": fm, "fc": fc,
                    "ms": m[3] if row else m[0], "me": m[1] if row else m[2],
                    "cs": m[0] if row else m[3], "ce": m[2] if row else m[1], "self": f.get("align"),
                    "minm": minm, "maxm": mm.get("max-w" if row else "max-h"),
                    "minc": minc, "maxc": mm.get("max-h" if row else "max-w")})
    return out


def _full(n: dict, hw: float, hh: float) -> list[float]:
    """The size a board's content needs, padding included (what Penpot keeps it at, at least)."""
    t, r, b, lft = _pad(n.get("layout") or {})
    return [hw + lft + r, hh + t + b]


def _browser_lines(infos: list[dict], row: bool) -> list[list[dict]]:
    """The lines a wrapping flex container put its items on: a line ends where the next item
    starts before the previous one ends."""
    lines: list[list[dict]] = []
    end = None
    for f in infos:
        b = f["box"]
        start = b[0] if row else b[1]
        if not lines or (end is not None and start < end - TOL):
            lines.append([])
        lines[-1].append(f)
        end = start + (b[2] if row else b[3])
    return lines


def _wraps(n: dict) -> bool:
    """A text that can break onto more lines (a normal space in it, white-space not nowrap/pre)."""
    t = n.get("text") or {}
    if t.get("nowrap"):
        return False
    return any(" " in str(leaf.get("text", "")).strip() for para in t.get("paragraphs") or [] for leaf in para)


def _constraints(g: dict, n: dict) -> dict:
    """How a layer that keeps its place follows its board when the board is resized: a border along
    the top spans it, a badge in a corner or hung past the right edge keeps to that side, a layer
    centred on the board stays centred (Penpot constraints; left/top are the defaults and stay unset)."""
    if not g.get("box") or not n.get("box"):
        return {}
    x, y, w, h = (g.get("pp") or {}).get("box") or _box(g)
    px, py, pw, ph = _box(n)

    def side(a0: float, asz: float, p0: float, psz: float, both: str, end: str) -> str | None:
        near0, near1 = abs(a0 - p0) <= TOL, abs(a0 + asz - (p0 + psz)) <= TOL
        spans = asz >= psz / 2 and abs(a0 - p0) <= 8 and abs(a0 + asz - (p0 + psz)) <= 8
        if (near0 and near1) or spans:
            return both
        if near1 or (a0 >= p0 - TOL and a0 + asz > p0 + psz + TOL):
            return end  # at the end edge, or hung past it (right: -10px)
        if asz < psz - TOL and not near0 and abs(a0 + asz / 2 - (p0 + psz / 2)) <= TOL:
            return "center"  # e.g. top: calc(50% - 44px) for an 88-px badge
        return None
    out = {}
    ch, cv = side(x, w, px, pw, "leftright", "right"), side(y, h, py, ph, "topbottom", "bottom")
    if ch:
        out["constraints-h"] = ch
    if cv:
        out["constraints-v"] = cv
    return out


def _hug(n: dict, hw: float, hh: float) -> list[float | None]:
    t, r, b, lft = _pad(n.get("layout") or {})
    x, y, w, h = _box(n)
    fw, fh = hw + lft + r, hh + t + b
    return [fw if abs(fw - w) <= HUG_TOL else None, fh if abs(fh - h) <= HUG_TOL else None]


def _row_setter(infos: list[dict], content: tuple) -> None:
    """Penpot passes a text's growth up only through boards that hug: in a row of stretched items the
    tallest one hugs (and sets the row height, as in CSS); the others fill."""
    if not any(f["vs"] == "fill" for f in infos):
        return

    def natural(f: dict) -> float:
        nat = f["it"].get("nat")
        return (nat["h"] if nat else f["box"][3]) + f["m"][0] + f["m"][2]
    top = max(infos, key=natural)
    if top["vs"] != "fill" or abs(natural(top) - content[3]) > TOL:
        return
    top["vs"] = "auto" if _hugs(top, 1) else "fix"


def _held_at_max(f: dict) -> bool:
    """Width auto, held at its max-width and free to shrink: CSS narrows it with its row, so in
    Penpot it fills up to that max-width (e.g. a 22em blockquote beside an icon)."""
    it = f["it"]
    mx = it.get("maxW")
    if not mx or f["text"] == "auto-width" or float(it.get("shrink", 1) or 0) <= 0:
        return False
    if (it.get("wspec") or "auto").strip() != "auto":
        return False
    dl, _, dr, _ = f["delta"]
    return abs(float(mx) - (f["box"][2] - dl - dr)) <= TOL


def _hangs_past_end(n: dict) -> float:
    """How far a positioned layer of the board (a badge) hangs past its right edge."""
    if n.get("kind") != "board" or not n.get("box"):
        return 0.0
    x, _, w, _ = _box(n)
    hang = 0.0
    for c in n.get("children", []):
        if (c.get("item") or {}).get("pos") in ("absolute", "fixed") and c.get("box"):
            cx, _, cw, _ = _box(c)
            hang = max(hang, cx + cw - (x + w))
    return hang


def _badge_room(f: dict, space_r: float, dr: float) -> None:
    """A box that fills up to its width keeps the room its design leaves after it for a badge hung
    past its right edge (max-width: calc(100% - 128px)): a right margin as wide as the badge hangs,
    so a narrower parent narrows the box and the badge stays inside."""
    hang = _hangs_past_end(f["n"])
    if hang > TOL and space_r >= hang - TOL:
        f["m"][1] = max(f["m"][1], hang - dr)


def _basis_min(f: dict, row: bool) -> float | None:
    """CSS flex: 1 (basis 0) grows every item from its padding and border; Penpot grows fill items
    from their minimum, so that minimum reproduces the browser's split."""
    basis = str(f["it"].get("basis") or "auto").strip()
    if not re.fullmatch(r"0(px|%)?", basis):
        return None
    t, r, b, lft = _pad(f["n"].get("layout") or {}) if f["n"]["kind"] == "board" else (0.0, 0.0, 0.0, 0.0)
    css = f["it"].get("minW" if row else "minH")
    return max(float(css or 0), (lft + r) if row else (t + b))


def _slack_side(t: dict) -> float:
    """How much of a refitted text's slack goes on its left: none, half or all, as it is aligned."""
    align = (t.get("text") or {}).get("align", "left")
    return SLACK / 2 if align == "center" else SLACK if align in ("right", "end") else 0.0


def _refit_text(f: dict) -> None:
    """A one-line text that CSS wraps when its box narrows: auto-height, filling up to today's width
    plus the slack Penpot needs, taken out of its margins (its margin box stays the browser's)."""
    left = _slack_side(f["n"])
    b = f["box"]
    f["box"] = [b[0] - left, b[1], b[2] + SLACK, b[3]]
    f["delta"][0] += left
    f["delta"][2] += SLACK - left
    f["m"][3] -= left
    f["m"][1] -= SLACK - left
    f["text"], f["capped"], f["refit"] = "auto-height", True, True


def _label_text(f: dict) -> dict | None:
    """The text of a label board: a board that hugs one wrappable one-line text (a dd, a div around a
    note). CSS narrows such a box with its container and wraps the text; this returns that text."""
    if f["text"] or f["n"]["kind"] != "board" or not _hugs(f, 0):
        return None
    order = (f["n"].get("pp") or {}).get("order") or []
    if len(order) != 1 or order[0]["kind"] != "text":
        return None
    t = order[0]
    return t if (t.get("pp") or {}).get("grow") == "auto-width" and _wraps(t) else None


def _refit_label(t: dict, board: dict) -> None:
    """A label board that now narrows with its container: its text fills it and wraps, with Penpot's
    slack taken out of the text's margins as _refit_text does (the board keeps its box)."""
    pp = _pp(t)
    left = _slack_side(t)
    x, y, w, h = pp["box"]
    pp["box"] = [x - left, y, w + SLACK, h]
    d = pp.get("delta") or [0.0, 0.0, 0.0, 0.0]
    pp["delta"] = [d[0] + left, d[1], d[2] + SLACK - left, d[3]]
    pp["grow"] = "auto-height"
    item = pp.setdefault("item", {})
    item["layout-item-h-sizing"] = "fill"
    mg = dict(item.get("layout-item-margin") or {"m1": 0.0, "m2": 0.0, "m3": 0.0, "m4": 0.0})
    mg["m4"] = _r(float(mg.get("m4") or 0) - left)
    mg["m2"] = _r(float(mg.get("m2") or 0) - (SLACK - left))
    item["layout-item-margin"], item["layout-item-margin-type"] = mg, "multiple"
    bp = _pp(board)
    if bp.get("content"):  # its words wrap now: only its padding stays as wide as it is
        _, pr, _, pl_ = _pad(board.get("layout") or {})
        bp["content"] = [pl_ + pr, bp["content"][1]]


def _refit_texts(infos: list[dict], cw: float, gap: float) -> None:
    """One-line texts in a row with room to spare: CSS shrinks them (their words wrap) when the row
    narrows, so in Penpot they fill the row up to today's width and grow downwards. A label board
    (a dd around its words) does the same: it fills up to today's width and its text wraps."""
    for line in _browser_lines(infos, True):
        used = sum(f["box"][2] + f["m"][1] + f["m"][3] for f in line) + gap * (len(line) - 1)
        if cw - used <= TOL:
            continue
        for f in line:
            if float(f["it"].get("shrink", 1) or 0) <= 0:
                continue
            if f["text"] == "auto-width" and _wraps(f["n"]):
                _refit_text(f)
            elif _label_text(f) is not None:
                f["capped"], f["label"] = True, _label_text(f)


def _try_flex(n: dict, flow: list[dict], kind: str, shrink_fill: bool = False, grow: bool = True,
              text_fill: bool = False) -> dict | str:
    L = n.get("layout") or {}
    content = _content(n)
    cx, cy, cw, ch = content
    semantic = kind == "semantic"
    grow = grow and semantic  # measured rows and columns copy sizes, not the CSS rules
    if semantic:
        d = L.get("dir") or "row"
        if d not in ("row", "column"):
            return f"flex-direction {d}"
        wrap_css = L.get("wrap") or "nowrap"
        if wrap_css not in ("nowrap", "wrap"):
            return f"flex-wrap {wrap_css}"
        row, wrap = d == "row", wrap_css == "wrap"
        gap = (float((L.get("gap") or [0, 0])[0]), float((L.get("gap") or [0, 0])[1]))
        justify = _kw(L.get("justify"), JUSTIFY, "")
        align = _kw(L.get("alignItems"), ALIGN, "")
        lines = _kw(L.get("alignContent"), LINES, "") if wrap else "stretch"
        if not justify or not align or not lines:
            return f"justify-content {L.get('justify')} / align-items {L.get('alignItems')} / align-content {L.get('alignContent')}"
        infos = [_info(c, True) for c in flow]
    else:
        row = kind == "row"
        wrap, justify, align, lines = False, "start", "start", "stretch"
        infos = sorted((_info(c, False) for c in flow), key=lambda f: f["box"][0 if row else 1])
        a0, a1 = (0, 2) if row else (1, 3)
        for p, q in zip(infos, infos[1:], strict=False):
            if q["box"][a0] < p["box"][a0] + p["box"][a1] - TOL:
                return "children overlap" if row else "children overlap vertically"
        gap = (0.0, 0.0)
    if semantic and row and text_fill:
        _refit_texts(infos, cw, gap[1])
    for f in infos:
        main, cross = _main_sizing(f, row, grow), _cross_sizing(f, row)
        if f.get("capped") or (semantic and row and not wrap and main != "fill" and _held_at_max(f)):
            main = "fill"
        f["hs"], f["vs"] = (main, cross) if row else (cross, main)
        if main == "fill":
            low = _basis_min(f, row)
            css_min, css_max = f["it"].get("minW" if row else "minH"), f["it"].get("maxW" if row else "maxH")
            if low is not None or css_min:
                f["minmax"]["min-w" if row else "min-h"] = max(float(css_min or 0), low or 0.0)
            if css_max:  # the planned box reaches past the browser's by delta: so does its cap
                d_ = f["delta"]
                f["minmax"]["max-w" if row else "max-h"] = float(css_max) + ((d_[0] + d_[2]) if row else (d_[1] + d_[3]))
            if f.get("capped"):
                f["minmax"]["max-w"] = f["box"][2]
    growers = [f for f in infos if (f["hs"] if row else f["vs"]) == "fill" and not f.get("capped")]
    if len(growers) > 1 and len({float(f["it"].get("grow") or 0) for f in growers}) > 1:
        return "flex-grow factors differ (Penpot shares free space equally)"
    ms_i, me_i, cs_i, ce_i = (3, 1, 0, 2) if row else (0, 2, 3, 1)
    if not semantic:
        # measured spacing: the most common gap (when it is also the smallest), the rest in margins
        prev = cx if row else cy
        spaces = []
        for f in infos:
            b = f["box"]
            spaces.append((b[0] if row else b[1]) - prev)
            prev = (b[0] + b[2]) if row else (b[1] + b[3])
        inner = [round(s * 2) / 2 for s in spaces[1:]]
        gm = 0.0
        if inner:
            common = max(set(inner), key=inner.count)
            if inner.count(common) >= 2 and common > 0 and common <= min(inner) + 0.01:
                gm = common
        gap = (0.0, gm) if row else (gm, 0.0)
        for k, f in enumerate(infos):
            f["m"][ms_i] = spaces[k] - (gm if k else 0.0)
        infos[-1]["m"][me_i] = ((cx + cw) if row else (cy + ch)) - prev
    elif shrink_fill and row and not wrap and justify == "start":
        used = sum(f["box"][2] + f["m"][1] + f["m"][3] for f in infos) + gap[1] * (len(infos) - 1)
        if abs(used - cw) <= TOL and not any(f["hs"] == "fill" for f in infos):
            for f in infos:
                shrinks = float(f["it"].get("shrink", 1) or 0) > 0
                if shrinks and (f["text"] == "auto-height" or (f["n"]["kind"] == "board" and not _hugs(f, 0))):
                    f["hs"] = "fill"
    # cross axis: fill what spans (block flow) or was stretched; align the rest from the geometry
    c0, csz = (cy, ch) if row else (cx, cw)
    line_top: dict[int, float] = {}
    if semantic and row and wrap and "baseline" in str(L.get("alignItems") or ""):
        for line in _browser_lines(infos, True):  # baseline: each item's offset from its line's top
            top = min(f["box"][1] - f["m"][0] for f in line)
            line_top.update({id(f): top for f in line})
    for f in infos:
        b, m = f["box"], f["m"]
        pos, size = (b[1], b[3]) if row else (b[0], b[2])
        if not semantic and f["text"]:
            # a text box reaches past the browser's by Penpot's whole pixels; across the board its
            # margins absorb that too, so a board that hugs it is as wide as in the browser (else
            # the excess adds up along a row of such boards and their wrapping parent breaks a
            # line the browser didn't, or can't hug and keeps a fixed size)
            dl, dt, dr, db = f["delta"]
            m[cs_i], m[ce_i] = (-dt, -db) if row else (-dl, -dr)
        if not row and f["hs"] != "fill" and f["text"] != "auto-width":
            dl, _, dr, _ = f["delta"]
            epos, esize = pos + dl, size - dl - dr          # the browser's own box
            if semantic:
                ml, mr = m[3] + dl, m[1] + dr                # back to CSS margins
            else:
                css = f["it"].get("margin") or [0, 0, 0, 0]
                ml, mr = float(css[3]), float(css[1])
            centered = abs(ml - mr) <= TOL and ml > TOL and not f["text"]
            space_l, space_r = epos - c0, c0 + csz - epos - esize
            mid = abs(space_l - space_r) <= TOL and space_l > TOL
            fluid, cap, gutter = width_spec(f["it"].get("wspec"))
            if centered and fluid:  # e.g. width: min(100% - 48px, 1200px); margin: 0 auto
                f["hs"], f["align"] = "fill", "center"
                if cap is not None and abs(cap - esize) <= TOL:
                    # at its cap: keep the gutters it gets below the cap (a vw gutter: today's space)
                    f["minmax"]["max-w"] = cap + dl + dr
                    side = min(gutter / 2, space_l) if gutter is not None else space_l
                    m[3], m[1] = side - dl, side - dr
                else:  # below its cap: the side spaces are its gutters
                    if cap is not None and cap > esize:
                        f["minmax"]["max-w"] = cap + dl + dr
                    m[3], m[1] = pos - c0, c0 + csz - pos - size
                continue
            maxw = f["it"].get("maxW")
            if maxw and abs(maxw - esize) <= TOL and (mid or abs(space_l - ml) <= TOL):
                # held at its max-width: fill up to that width, so a narrower parent narrows it too
                f["hs"] = "fill"
                f["minmax"]["max-w"] = maxw + dl + dr
                if mid:
                    f["align"], m[3], m[1] = "center", -dl, -dr
                else:
                    f["align"] = None if align == "start" else "start"
                    m[3], m[1] = pos - c0, (mr - dr if semantic else 0.0)
                    _badge_room(f, space_r, dr)
                continue
            if not centered and abs(epos - ml - c0) <= TOL and abs(epos + esize + mr - (c0 + csz)) <= TOL:
                f["hs"] = "fill"
                m[3], m[1] = pos - c0, c0 + csz - pos - size
                continue
            if semantic and f["layout"] and (f["it"].get("wspec") or "auto").strip() == "auto" and not maxw:
                # width auto in a flex column that doesn't stretch it: CSS gives it its content's width,
                # at most the column's, so in Penpot it fills up to today's width and narrows with it
                f["hs"], f["minmax"]["max-w"], f["label"] = "fill", size, _label_text(f)
                a, m[3], m[1] = _cross_align(pos, size, c0, csz, m[3], m[1], align)
                f["align"] = a if a != align else None
                if a == "start":
                    _badge_room(f, space_r, dr)
                continue
        if (f["vs"] if row else f["hs"]) == "fill":
            if not semantic:
                m[cs_i], m[ce_i] = pos - c0, c0 + csz - pos - size
            continue
        if wrap:  # aligned within its own line, as Penpot does too: the simulation checks it
            if id(f) in line_top:
                m[cs_i] = pos - line_top[id(f)]
            continue
        a, m[cs_i], m[ce_i] = _cross_align(pos, size, c0, csz, m[cs_i], m[ce_i], align)
        f["align"] = a if a != align else None
    if semantic and row and not wrap:
        _row_setter(infos, content)
    boxes, _, _ = sim_flex(content, row, wrap, gap, justify, align, lines, _flex_items(infos, row))
    bad = _check(infos, boxes)
    if bad:
        return bad
    _, hw1, hh1 = sim_flex(content, row, wrap, gap, justify, align, lines, _flex_items(infos, row, True), True, True)
    _, hw2, hh2 = sim_flex(content, row, wrap, gap, justify, align, lines, _flex_items(infos, row, True), False, True)
    hw, hh = (hw1, hh2) if row else (hw2, hh1)
    attrs = _container("flex", L, dir="row" if row else "column", wrap=wrap, gap=gap, justify=justify, align=align, lines=lines)
    label = {"semantic": "flex " + ("row" if row else "column"), "column": "column (measured)", "row": "row (measured)"}[kind]
    cw_, ch_ = hw, hh
    if wrap:  # what a wrapping board needs is its widest line, not all items on one line
        widest = max(sum((f["box"][2] + f["m"][1] + f["m"][3]) if row else (f["box"][3] + f["m"][0] + f["m"][2])
                         for f in line) + (gap[1] if row else gap[0]) * (len(line) - 1)
                     for line in _browser_lines(infos, row))
        cw_, ch_ = (min(hw, widest), hh) if row else (hw, min(hh, widest))
    return {"mode": "flex", "attrs": attrs, "infos": infos, "hug": _hug(n, hw, hh), "kind": label,
            "content": _full(n, cw_, ch_)}


def _place(lo: float, hi: float, starts: list[float], sizes: list[float]) -> tuple[int, int] | None:
    first = [k for k, s in enumerate(starts) if s <= lo + TOL]
    if not first:
        return None
    i = first[-1]
    ends = [k for k in range(i, len(starts)) if starts[k] + sizes[k] >= hi - TOL]
    return (i, ends[0] - i + 1) if ends else None


def _try_grid(n: dict, flow: list[dict]) -> dict | str:
    L = n.get("layout") or {}
    content = _content(n)
    cx, cy, cw, ch = content
    colpx, rowpx = [float(v) for v in L.get("cols") or []], [float(v) for v in L.get("rows") or []]
    if not colpx or not rowpx:
        return "grid tracks unknown"
    gap = (float((L.get("gap") or [0, 0])[0]), float((L.get("gap") or [0, 0])[1]))
    notes = []
    unset = {None, "", "none"}  # no template written: the tracks are implicit
    cols = parse_tracks(L.get("colsSpec"), len(colpx))
    if cols is None and (L.get("colsSpec") or "").strip() in unset:
        cols = [{"type": "flex", "value": 1}] if len(colpx) == 1 else parse_tracks(L.get("autoCols"), len(colpx))
    if cols is None:
        cols = [{"type": "fixed", "value": _r(v)} for v in colpx]
        notes.append(f"columns '{L.get('colsSpec') or 'implicit'}' kept as fixed widths")
    rows = parse_tracks(L.get("rowsSpec"), len(rowpx))
    if rows is None and (L.get("rowsSpec") or "").strip() in unset:
        auto = _track(L.get("autoRows") or "auto")
        rows = [dict(auto) for _ in rowpx] if auto else None
    if rows is None:
        rows = [{"type": "auto", "value": 1} for _ in rowpx]
        notes.append(f"rows '{L.get('rowsSpec')}' kept as auto heights")
    jc = _kw(L.get("justify"), TRACKS, "")
    ac = _kw(L.get("alignContent"), TRACKS, "")
    if not jc or not ac:
        return f"grid content alignment {L.get('justify')} / {L.get('alignContent')}"
    xs = _track_starts(colpx, cx, cw, gap[1], "start" if jc == "stretch" else jc, False)
    ys = _track_starts(rowpx, cy, ch, gap[0], "start" if ac == "stretch" else ac, False)
    infos = [_info(c, True) for c in flow]
    taken: set[tuple[int, int]] = set()
    for f in infos:
        b, m = f["box"], f["m"]
        pc = _place(b[0] - m[3], b[0] + b[2] + m[1], xs, colpx)
        pr = _place(b[1] - m[0], b[1] + b[3] + m[2], ys, rowpx)
        if not pc or not pr:
            return f"{str(f['n'].get('name', ''))[:60]} is outside the grid tracks"
        f["cell"] = {"r": pr[0], "rs": pr[1], "c": pc[0], "cs": pc[1]}
        spots = {(r_, c_) for r_ in range(pr[0], pr[0] + pr[1]) for c_ in range(pc[0], pc[0] + pc[1])}
        if spots & taken:
            return "two items share a grid cell"
        taken |= spots
    for f in infos:
        cell, b, m = f["cell"], f["box"], f["m"]
        aw = sum(colpx[cell["c"]:cell["c"] + cell["cs"]]) + gap[1] * (cell["cs"] - 1)
        ah = sum(rowpx[cell["r"]:cell["r"] + cell["rs"]]) + gap[0] * (cell["rs"] - 1)
        ax, ay = xs[cell["c"]], ys[cell["r"]]
        if f["text"] == "auto-width":
            f["hs"], f["vs"] = "auto", "auto"
        else:
            f["hs"] = "fill" if abs(b[2] + m[1] + m[3] - aw) <= TOL else ("auto" if _hugs(f, 0) else "fix")
            if f["hs"] != "fill" and _held_at_max(f) and abs(b[0] - m[3] - ax) <= TOL:
                # held at its max-width at the start of its area: fill up to it, so a narrower
                # column narrows it too (e.g. an intro paragraph capped at 40ch)
                dl, _, dr, _ = f["delta"]
                f["hs"], f["minmax"]["max-w"] = "fill", float(f["it"]["maxW"]) + dl + dr
            spans_h = abs(b[3] + m[0] + m[2] - ah) <= TOL
            if f["text"]:
                f["vs"] = "auto"
            elif spans_h and (_stretched(f, True) or not _hugs(f, 1)):
                f["vs"] = "fill"
            else:
                f["vs"] = "auto" if _hugs(f, 1) else "fix"
        sized = all(cols[k]["type"] != "auto" for k in range(cell["c"], cell["c"] + cell["cs"]))
        if (f["hs"] != "fill" and sized and aw - (b[2] + m[1] + m[3]) > TOL and abs(b[0] - m[3] - ax) <= TOL
                and (f["it"].get("wspec") or "auto").strip() == "auto"):
            # narrower than its column, at its start (justify-self start): CSS fits it to its content,
            # at most the column's width, so its words wrap when the column narrows; in Penpot it
            # fills up to today's width (a column sized by its items, auto, would follow it instead)
            if f["text"] == "auto-width" and _wraps(f["n"]):
                _refit_text(f)
                f["hs"], f["minmax"]["max-w"] = "fill", f["box"][2]
            elif f["layout"] and not f["it"].get("maxW"):
                f["hs"], f["minmax"]["max-w"], f["label"] = "fill", b[2], _label_text(f)
        f["js"], f["al"] = "start", "start"
        if f["hs"] != "fill":
            f["js"], m[3], m[1] = _grid_align(b[0], b[2], ax, aw, m[3], m[1], False)
        if f["vs"] != "fill":
            f["al"], m[0], m[2] = _grid_align(b[1], b[3], ay, ah, m[0], m[2], True)
    # each auto row needs one item that hugs (the tallest), so text growth reaches the grid
    for r_ in range(len(rowpx)):
        members = [f for f in infos if f["cell"]["r"] == r_ and f["cell"]["rs"] == 1]
        if rows[r_]["type"] != "fixed" and members and all(f["vs"] == "fill" for f in members):
            top = max(members, key=lambda f: (f["it"].get("nat") or {}).get("h", f["box"][3]))
            top["vs"] = "auto" if _hugs(top, 1) else "fix"
            top["al"] = "start"

    def cells_for(hug: bool) -> list[dict]:
        out = []
        for f in infos:
            w, h = _sizes(f, hug)
            nat = f["it"].get("nat") or {}
            cm = _content_min(f, True)
            if cm:  # Penpot keeps a board with a layout at least as big as its content
                minw, minh = _floor_min(None, cm[0], w), _floor_min(None, cm[1], h)
            else:
                minw = min((f["hug"][0] or nat.get("w") or 0.01) if f["layout"] else 0.01, w)
                minh = min((f["hug"][1] or nat.get("h") or 0.01) if f["layout"] else 0.01, h)
            out.append({**f["cell"], "w": w, "h": h, "fw": f["hs"] == "fill", "fh": f["vs"] == "fill",
                        "minw": minw, "minh": minh, "maxw": (f.get("minmax") or {}).get("max-w"),
                        "m": list(f["m"]), "js": f["js"], "al": f["al"]})
        return out
    boxes, _, _ = sim_grid(content, cols, rows, gap, jc, ac, cells_for(False))
    bad = _check(infos, boxes)
    if bad:
        return bad
    _, hw, _ = sim_grid(content, cols, rows, gap, jc, ac, cells_for(True), auto_w=True, auto_h=False)
    _, _, hh = sim_grid(content, cols, rows, gap, jc, ac, cells_for(True), auto_w=False, auto_h=True)
    attrs = _container("grid", L, gap=gap, cols=cols, rows=rows, justify=jc, align="start", lines=ac)
    cells = [{"child": f["n"], "row": f["cell"]["r"] + 1, "row-span": f["cell"]["rs"],
              "column": f["cell"]["c"] + 1, "column-span": f["cell"]["cs"],
              "justify-self": "auto" if f["js"] == "start" else f["js"],
              "align-self": "auto" if f["al"] == "start" else f["al"]} for f in infos]
    for r_ in range(len(rowpx)):
        for c_ in range(len(colpx)):
            if (r_, c_) not in taken:
                cells.append({"child": None, "row": r_ + 1, "row-span": 1, "column": c_ + 1, "column-span": 1,
                              "justify-self": "auto", "align-self": "auto"})
    return {"mode": "grid", "attrs": attrs, "infos": infos, "hug": _hug(n, hw, hh), "kind": "grid", "notes": notes,
            "cells": cells, "content": _full(n, hw, hh)}


def _plan_board(n: dict) -> None:
    pp = _pp(n)
    pp.update({"mode": None, "attrs": {}, "order": [], "cells": None, "kind": "positioned", "why": None,
               "hug": [None, None], "notes": []})
    flow, other = _split(n)
    if not flow or n.get("formControl"):
        pp["kind"] = "no flow children"
        _keep_in_place(n)  # its borders and badges follow it when a layout resizes it
        return
    d = (n.get("layout") or {}).get("display") or "block"
    disp = d[7:] if d in ("inline-flex", "inline-grid") else d
    tries: list[tuple[str, Any]] = []
    if disp == "flex":
        # flex-grow first; then without it (a column whose height comes from its content gives
        # growing items nothing to share, and Penpot would shrink fill items to their minimum)
        # and first with one-line texts that wrap when the row narrows, as in CSS (see _refit_texts)
        for text_fill in (True, False):
            tries += [("flex", lambda tf=text_fill: _try_flex(n, flow, "semantic", True, text_fill=tf)),
                      ("flex", lambda tf=text_fill: _try_flex(n, flow, "semantic", text_fill=tf)),
                      ("flex", lambda tf=text_fill: _try_flex(n, flow, "semantic", grow=False, text_fill=tf))]
    elif disp == "grid":
        tries.append(("grid", lambda: _try_grid(n, flow)))
    tries += [("column", lambda: _try_flex(n, flow, "column")), ("row", lambda: _try_flex(n, flow, "row"))]
    reasons: list[str] = []
    for name, fn in tries:
        res = fn()
        if isinstance(res, str):
            if f"{name}: {res}" not in reasons:
                reasons.append(f"{name}: {res}")
            continue
        _apply(n, res, other)
        if disp in ("flex", "grid") and name not in ("flex", "grid"):
            pp["why"] = "; ".join(reasons)
        return
    res = _try_lines(n, flow)
    if not isinstance(res, str):
        _apply(n, res, _split(n)[1])
        pp["kind"] = "column of lines (measured)"
        if disp in ("flex", "grid"):
            pp["why"] = "; ".join(reasons)
        return
    reasons.append(f"lines: {res}")
    pp["why"] = "; ".join(reasons)
    _keep_in_place(n)


def _keep_in_place(n: dict) -> None:
    """Layers of a board without a layout keep their place: they follow it when it is resized."""
    for c in n.get("children", []):
        for g in (_promoted(c) if _is_zero(c) else [c]):
            cons = _constraints(g, n)
            if cons:
                _pp(g)["item"] = cons


def _try_lines(n: dict, flow: list[dict]) -> dict | str:
    """Inline-blocks side by side in a block (a price and its unit, badges): one measured row board
    per line, stacked in a measured column. Adds the line boards to the scene only if it fits."""
    def pbox(c: dict) -> list[float]:
        return list((c.get("pp") or {}).get("box") or _box(c))
    lines: list[dict] = []
    for c in sorted(flow, key=lambda c: pbox(c)[1]):
        x, y, w, h = pbox(c)
        for ln in lines:
            if y < ln["y1"] - TOL and y + h > ln["y0"] + TOL:
                ln["items"].append(c)
                ln["y0"], ln["y1"] = min(ln["y0"], y), max(ln["y1"], y + h)
                break
        else:
            lines.append({"items": [c], "y0": y, "y1": y + h})
    if all(len(ln["items"]) == 1 for ln in lines):
        return "no side-by-side children"
    children = list(n.get("children", []))
    for ln in lines:
        if len(ln["items"]) < 2:
            continue
        items = sorted(ln["items"], key=lambda c: pbox(c)[0])
        for p_, q in zip(items, items[1:], strict=False):
            if pbox(q)[0] < pbox(p_)[0] + pbox(p_)[2] - TOL:
                return "children overlap"
        x0 = min(pbox(c)[0] for c in items)
        x1 = max(pbox(c)[0] + pbox(c)[2] for c in items)
        line = {"kind": "board", "name": "Line", "synthetic": True, "z": 0, "fills": [], "children": items,
                "box": {"x": x0, "y": ln["y0"], "w": x1 - x0, "h": ln["y1"] - ln["y0"]},
                "layout": {"display": "block", "pad": [0, 0, 0, 0]},
                "item": {"pos": "static", "grow": 0, "margin": [0, 0, 0, 0]}}
        res = _try_flex(line, items, "row")
        if isinstance(res, str):
            return f"line: {res}"
        at = min(k for k, c in enumerate(children) if any(c is i for i in items))
        children = [c for c in children if not any(c is i for i in items)]
        children.insert(min(at, len(children)), line)
        _apply(line, res, [])
    keep = n.get("children")
    n["children"] = children
    res = _try_flex(n, _split(n)[0], "column")
    if isinstance(res, str):
        n["children"] = keep
        for c in keep or []:
            _pp(c).pop("item", None)
    return res


def _apply(n: dict, res: dict, other: list[dict]) -> None:
    pp = _pp(n)
    infos = res["infos"]
    pp.update({"mode": res["mode"], "attrs": res["attrs"], "kind": res["kind"], "hug": res["hug"],
               "notes": res.get("notes", []), "order": [f["n"] for f in infos], "cells": res.get("cells"),
               "content": res.get("content")})
    ranks = _z_ranks([f["n"] for f in infos] + other)
    for f in infos:
        _pp(f["n"])["item"] = _item(f, z=ranks[id(f["n"])])
        if f.get("refit"):  # a one-line text that now wraps with its row
            _pp(f["n"]).update({"grow": "auto-height", "box": list(f["box"]), "delta": list(f["delta"])})
        if f.get("label") is not None:  # a label board that now narrows: its words wrap inside it
            _refit_label(f["label"], f["n"])
    for c in other:
        for g in (_promoted(c) if _is_zero(c) else [c]):
            # background layers lie under all else, the lowest first; other layers drawn under at -1
            z = (-50 + int(g["bg"])) if g.get("bg") is not None else -1 if g.get("deco") == "under" else ranks.get(id(c), 0)
            _pp(g)["item"] = {**_item({"hs": "fix", "vs": "fix", "m": [0, 0, 0, 0]}, absolute=True, z=z),
                              **_constraints(g, n)}


def _drawn(n: dict) -> list[float] | None:
    """What a group covers in Penpot: its layers' boxes (an inline SVG's paths sit inside its box)."""
    if n["kind"] != "group":
        return _box(n) if n.get("box") else None
    boxes = [b for b in (_drawn(c) for c in n.get("children", [])) if b]
    if not boxes:
        return None
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[0] + b[2] for b in boxes), max(b[1] + b[3] for b in boxes)
    return [x0, y0, x1 - x0, y1 - y0]


def group_plan(n: dict) -> dict:
    """A group's box in Penpot (its layers' union) and how far it reaches past the browser's box
    (negative: an SVG's paths inside its box), so its margins keep the browser's spacing."""
    x, y, w, h = _box(n)
    gx, gy, gw, gh = _drawn(n) or [x, y, w, h]
    return {"box": [gx, gy, gw, gh], "delta": [x - gx, y - gy, gx + gw - (x + w), gy + gh - (y + h)]}


def plan_tree(n: dict) -> None:
    """Plan a board and everything under it (children first: a parent needs their hug sizes)."""
    for c in n.get("children", []):
        if c["kind"] == "board":
            plan_tree(c)
        elif c["kind"] == "text":
            _pp(c).update(text_plan(c))
        elif c["kind"] == "group" and c.get("box"):
            _pp(c).update(group_plan(c))
        _pp(c).pop("item", None)
    if n["kind"] == "board" and not _is_zero(n):
        _plan_board(n)


def page_node(scene: dict) -> dict:
    """The page board as a node: the body's content box inside the full page."""
    W, H = float(scene["width"]), float(scene["height"])
    body = scene.get("body") or {}
    bb = body.get("box") or {"x": 0, "y": 0, "w": W, "h": H}
    L = dict(body.get("layout") or {"display": "block"})
    t, r, b, lft = [float(v) for v in (L.get("pad") or [0, 0, 0, 0])]
    top, left = bb["y"] + t, bb["x"] + lft
    right, bottom = bb["x"] + bb["w"] - r, bb["y"] + bb["h"] - b
    L["pad"] = [max(0.0, top), max(0.0, W - right), max(0.0, H - bottom), max(0.0, left)]
    return {"kind": "board", "name": "Page", "box": {"x": 0, "y": 0, "w": W, "h": H}, "layout": L,
            "children": scene["nodes"]}


def plan_scene(scene: dict) -> dict:
    """Plan one width's scene; returns the page board's plan (its nodes get theirs in n["pp"])."""
    page = page_node(scene)
    plan_tree(page)
    return page["pp"]


def _tally(nodes: list[dict], width: Any, boards: list[tuple[str, dict]], texts: dict[str, int],
           notes: list[dict]) -> None:
    """The boards and texts of one width's scene, for summary()."""
    for c in nodes:
        if c["kind"] == "board" and not _is_zero(c):
            boards.append((c.get("name", "board"), c.get("pp") or {}))
        if c["kind"] == "text":
            g = (c.get("pp") or {}).get("grow", "fixed")
            texts[g] = texts.get(g, 0) + 1
            if (c.get("pp") or {}).get("rewrap"):
                notes.append({"width": width, "board": str(c.get("name", "text"))[:80],
                              "note": "no box width breaks its lines in Penpot as in the browser: "
                                      "a line may rewrap when the editor re-measures it"})
        _tally(c.get("children", []), width, boards, texts, notes)


def summary(scenes: dict, pages: dict) -> dict:
    """What was carried over, per width: boards by mapping, texts by growth, and every fallback."""
    out: dict[str, Any] = {"widths": {}, "fallbacks": [], "notes": []}
    for width in sorted(scenes):
        kinds: dict[str, int] = {}
        texts: dict[str, int] = {}
        boards: list[tuple[str, dict]] = [("Page", pages[width])]
        _tally(scenes[width]["nodes"], width, boards, texts, out["notes"])
        for name, pp in boards:
            k = pp.get("kind", "positioned")
            kinds[k] = kinds.get(k, 0) + 1
            if pp.get("why"):
                out["fallbacks"].append({"width": width, "board": str(name)[:80], "mapped": k, "why": str(pp["why"])[:400]})
            for note in pp.get("notes", []):
                out["notes"].append({"width": width, "board": str(name)[:80], "note": note})
        laid = sum(v for k, v in kinds.items() if k not in ("positioned", "no flow children"))
        out["widths"][width] = {"boards": kinds, "texts": texts, "with_layout": laid,
                                "positioned": kinds.get("positioned", 0)}
    return out
