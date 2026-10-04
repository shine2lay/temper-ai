"""Model-free small-size check of a logo symbol, from its saved vector geometry.

Input is the saved concept geometry in the 100-unit symbol box (the state the
native Penpot file is built from): rect (x, y, w, h, optional corner radius r),
ellipse (x, y, w, h) and closed M/L/C/Z paths, each part filled nonzero, every
part one colour (the monochrome silhouette). At a display size of S px one unit
is S/100 px.

Measured features:
- width: the typical stroke width of each visible part (length-weighted median
  of the inward-normal thickness through the inked silhouette, sampled along the
  part's visible outline);
- seam: the narrowest gap between two separate ink islands (exact minimum
  outline distance), e.g. a dovetail seam or an arc beside a fork tine;
- opening: a slot, counter or notch inside one island (median distance from a
  wall to the wall facing it, per run of facing outline at least 2 units long).

A feature is present at S px when it is at least `floor_px` wide (default 1 px)
and reads clearly at `clear_px` (default 2 px). The minimum size is the smallest
standard size where every feature is present. Px values are truncated to two
decimals and exact minimum sizes are rounded up, so nothing passes by rounding.

Not modelled: antialiasing and hinting, colour and contrast, and whether the
idea reads at all (the cold read covers that).
"""
from __future__ import annotations

import argparse
import json
import math
import sys

SIZES = (16, 24, 32, 48)
FLOOR_PX = 1.0
CLEAR_PX = 2.0
STEP = 0.5        # outline sampling step, units
TOLERANCE = 0.002  # curve flattening error, units
TOUCH = 0.05      # parts closer than this are one ink island
NEAR = 30.0       # wider seams and openings are not listed
MIN_RUN = 2.0     # facing outline shorter than this is a corner, not an opening
FACING = 0.7      # a wall faces back when the ray meets it within ~45 degrees
EPS = 0.01
METHOD = ("saved vector geometry, 100-unit box, nonzero fill, monochrome silhouette; curves flattened within "
          f"{TOLERANCE} units; widths = median inward thickness along each visible outline; seams = exact minimum "
          "distance between separate ink islands; openings = median distance between facing walls inside one island "
          f"(runs of at least {MIN_RUN:g} units); px truncated to 0.01, exact minimum sizes rounded up")
LIMITS = ("Geometry only: antialiasing, hinting, colour and contrast are not modelled, and a feature that is present "
          "is not proof that the idea reads (see the cold read).")


def trunc(value):
    return math.floor(value * 100 + 1e-7) / 100


def ceil2(value):
    return math.ceil(value * 100 - 1e-7) / 100


def _dedupe(ring):
    out = []
    for pt in ring:
        if not out or math.dist(out[-1], pt) > 1e-9:
            out.append(pt)
    while len(out) > 1 and math.dist(out[0], out[-1]) <= 1e-9:
        out.pop()
    return out


def _cubic(p0, p1, p2, p3):
    ddx = max(abs(p0[0] - 2 * p1[0] + p2[0]), abs(p1[0] - 2 * p2[0] + p3[0]))
    ddy = max(abs(p0[1] - 2 * p1[1] + p2[1]), abs(p1[1] - 2 * p2[1] + p3[1]))
    n = max(2, min(400, math.ceil(math.sqrt(6 * math.hypot(ddx, ddy) / (8 * TOLERANCE)))))
    pts = []
    for i in range(1, n + 1):
        t = i / n
        u = 1 - t
        a, b, cc, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
        pts.append((a * p0[0] + b * p1[0] + cc * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + cc * p2[1] + d * p3[1]))
    return pts


def rings(spec):
    """Closed polygon rings of one saved part, in symbol units."""
    kind = spec["kind"]
    if kind in ("rect", "ellipse"):
        x, y, w, h = (float(spec[k]) for k in ("x", "y", "w", "h"))
    if kind == "rect":
        r = min(float(spec.get("r", 0) or 0), w / 2, h / 2)
        if r <= 0:
            return [[(x, y), (x + w, y), (x + w, y + h), (x, y + h)]]
        ring = []
        for cx, cy, start in ((x + w - r, y + r, -90), (x + w - r, y + h - r, 0), (x + r, y + h - r, 90), (x + r, y + r, 180)):
            n = max(4, math.ceil(math.pi / 2 / math.acos(max(-1.0, 1 - TOLERANCE / r))))
            for i in range(n + 1):
                a = math.radians(start + 90 * i / n)
                ring.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        return [_dedupe(ring)]
    if kind == "ellipse":
        rx, ry = w / 2, h / 2
        n = max(16, math.ceil(math.pi / math.acos(max(-1.0, 1 - TOLERANCE / max(rx, ry)))))
        return [[(x + rx + rx * math.cos(2 * math.pi * i / n), y + ry + ry * math.sin(2 * math.pi * i / n)) for i in range(n)]]
    if kind != "path":
        raise ValueError("unsupported symbol part")
    out, ring = [], []
    for cmd in spec["commands"]:
        op = cmd[0]
        if op == "M":
            ring = [(float(cmd[1]), float(cmd[2]))]
        elif op == "L":
            ring.append((float(cmd[1]), float(cmd[2])))
        elif op == "C":
            ring.extend(_cubic(ring[-1], (float(cmd[1]), float(cmd[2])), (float(cmd[3]), float(cmd[4])),
                               (float(cmd[5]), float(cmd[6]))))
        elif op == "Z":
            ring = _dedupe(ring)
            if len(ring) >= 3:
                out.append(ring)
            ring = []
    return out


class Part:
    def __init__(self, index, spec):
        self.index = index
        self.name = str(spec.get("name", f"part {index + 1}"))
        self.rings = rings(spec)
        self.segs = [(ring[i], ring[(i + 1) % len(ring)]) for ring in self.rings for i in range(len(ring))]
        xs = [p[0] for ring in self.rings for p in ring]
        ys = [p[1] for ring in self.rings for p in ring]
        self.box = (min(xs), min(ys), max(xs), max(ys))

    def inside(self, pt):
        x, y = pt
        x0, y0, x1, y1 = self.box
        if x < x0 or x > x1 or y < y0 or y > y1:
            return False
        winding = 0
        for (ax, ay), (bx, by) in self.segs:
            if ay <= y:
                if by > y and (bx - ax) * (y - ay) - (x - ax) * (by - ay) > 0:
                    winding += 1
            elif by <= y and (bx - ax) * (y - ay) - (x - ax) * (by - ay) < 0:
                winding -= 1
        return winding != 0


def _point_segment(p, a, b):
    ex, ey = b[0] - a[0], b[1] - a[1]
    length = ex * ex + ey * ey
    t = 0.0 if length == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * ex + (p[1] - a[1]) * ey) / length))
    q = (a[0] + t * ex, a[1] + t * ey)
    return math.dist(p, q), q


def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _segments_cross(a, b, c, d):
    d1, d2, d3, d4 = _cross(c, d, a), _cross(c, d, b), _cross(a, b, c), _cross(a, b, d)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and d1 != 0 and d2 != 0 and d3 != 0 and d4 != 0


def outline_distance(left, right, limit=math.inf):
    """Exact minimum distance between two parts' outlines, with the closest points' midpoint."""
    best, where = limit, None
    for a, b in left.segs:
        ax0, ax1 = min(a[0], b[0]), max(a[0], b[0])
        ay0, ay1 = min(a[1], b[1]), max(a[1], b[1])
        for c, d in right.segs:
            if (min(c[0], d[0]) - ax1 > best or ax0 - max(c[0], d[0]) > best or
                    min(c[1], d[1]) - ay1 > best or ay0 - max(c[1], d[1]) > best):
                continue
            if _segments_cross(a, b, c, d):
                return 0.0, a
            for p, s, t in ((a, c, d), (b, c, d), (c, a, b), (d, a, b)):
                dist, q = _point_segment(p, s, t)
                if dist < best:
                    best, where = dist, ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
    return best, where


def _median(values):
    """Length-weighted median of (value, weight) pairs."""
    values = sorted(values)
    half = sum(w for _, w in values) / 2
    run = 0.0
    for value, weight in values:
        run += weight
        if run >= half:
            return value
    return values[-1][0]


class Silhouette:
    def __init__(self, symbol):
        self.parts = [Part(i, spec) for i, spec in enumerate(symbol)]
        n = len(self.parts)
        parent = list(range(n))

        def root(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        self.pair = {}
        for i in range(n):
            for j in range(i + 1, n):
                a, b = self.parts[i], self.parts[j]
                dist, where = outline_distance(a, b, NEAR)
                if dist > TOUCH and (any(b.inside(p) for ring in a.rings for p in ring[:1]) or
                                     any(a.inside(p) for ring in b.rings for p in ring[:1])):
                    dist = 0.0
                self.pair[i, j] = (dist, where)
                if dist <= TOUCH:
                    parent[root(i)] = root(j)
        self.island = [root(i) for i in range(n)]
        self.segs = [(seg, part.index) for part in self.parts for seg in part.segs]

    def ink(self, pt, among=None):
        """Index of a part whose ink covers pt (restricted to one island), else None."""
        for part in self.parts:
            if (among is None or self.island[part.index] == among) and part.inside(pt):
                return part.index
        return None

    def hits(self, origin, direction):
        ox, oy = origin
        dx, dy = direction
        out = []
        for ((ax, ay), (bx, by)), index in self.segs:
            ex, ey = bx - ax, by - ay
            den = dx * ey - dy * ex
            if abs(den) < 1e-12:
                continue
            wx, wy = ax - ox, ay - oy
            t = (wx * ey - wy * ex) / den
            u = (wx * dy - wy * dx) / den
            if t > 1e-7 and -1e-9 <= u <= 1 + 1e-9:
                out.append((t, abs(den) / math.hypot(ex, ey), index))
        out.sort()
        return out

    def samples(self, part):
        """Visible outline points of a part: (point, inward unit normal, weight), per ring in order."""
        result = []
        for ring in part.rings:
            row = []
            for i in range(len(ring)):
                a, b = ring[i], ring[(i + 1) % len(ring)]
                length = math.dist(a, b)
                if length < 1e-9:
                    continue
                k = max(1, round(length / STEP))
                nx, ny = (b[1] - a[1]) / length, -(b[0] - a[0]) / length
                for j in range(k):
                    f = (j + .5) / k
                    p = (a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1]))
                    normal = None
                    for sx, sy in ((nx, ny), (-nx, -ny)):
                        if part.inside((p[0] + EPS * sx, p[1] + EPS * sy)):
                            normal = (sx, sy)
                            break
                    if normal is None or self.ink((p[0] - EPS * normal[0], p[1] - EPS * normal[1])) is not None:
                        row.append(None)
                        continue
                    row.append((p, normal, length / k))
            result.append(row)
        return result

    def thickness(self, p, normal, island):
        for t, _, _ in self.hits(p, normal):
            probe = (p[0] + (t + 1e-4) * normal[0], p[1] + (t + 1e-4) * normal[1])
            if self.ink(probe, island) is None:
                return t
        return None

    def opening(self, p, normal, island):
        out = (-normal[0], -normal[1])
        for t, facing, _ in self.hits(p, out):
            if t > NEAR:
                return None
            probe = (p[0] + (t + 1e-4) * out[0], p[1] + (t + 1e-4) * out[1])
            index = self.ink(probe)
            if index is not None:
                return t if self.island[index] == island and facing >= FACING else None
        return None


def _px(units, sizes):
    return {str(size): trunc(units * size / 100) for size in sizes}


def _runs(seq):
    """Runs of consecutive openings along one closed ring (a run may wrap past the ring start)."""
    runs, current = [], []
    for item in seq:
        if item is None:
            if current:
                runs.append(current)
            current = []
        else:
            current.append(item)
    if current:
        if runs and seq[0] is not None:
            runs[0] = current + runs[0]
        else:
            runs.append(current)
    return runs


def _at(pt):
    return [round(pt[0], 1), round(pt[1], 1)] if pt else None


def measure(symbol, *, sizes=SIZES, floor_px=FLOOR_PX, clear_px=CLEAR_PX):
    """Size facts of one saved symbol (list of parts)."""
    shape = Silhouette(symbol)
    features = []
    for part in shape.parts:
        island = shape.island[part.index]
        widths, runs = [], []
        for row in shape.samples(part):
            seq = []
            for item in row:
                if item is None:
                    seq.append(None)
                    continue
                p, normal, weight = item
                thick = shape.thickness(p, normal, island)
                if thick is not None:
                    widths.append((thick, weight))
                gap = shape.opening(p, normal, island)
                seq.append(None if gap is None else (gap, weight, p))
            runs.extend(_runs(seq))
        if not widths:
            features.append({"kind": "covered", "part": part.name, "note": "no visible outline (covered by other parts)"})
            continue
        width = _median(widths)
        features.append({"kind": "width", "part": part.name, "units": round(width, 3), "px": _px(width, sizes)})
        best = None
        for run in runs:
            if sum(w for _, w, _ in run) < MIN_RUN:
                continue
            value = _median([(g, w) for g, w, _ in run])
            if best is None or value < best[0]:
                best = (value, run[len(run) // 2][2])
        if best:
            features.append({"kind": "opening", "part": part.name, "units": round(best[0], 3),
                             "px": _px(best[0], sizes), "at": _at(best[1])})
    islands = sorted(set(shape.island))
    for x, left in enumerate(islands):
        for right in islands[x + 1:]:
            pairs = [(shape.pair[min(i, j), max(i, j)], i, j) for i in range(len(shape.parts)) for j in range(len(shape.parts))
                     if shape.island[i] == left and shape.island[j] == right]
            (dist, where), i, j = min(pairs, key=lambda row: row[0][0])
            if dist < NEAR:
                features.append({"kind": "seam", "between": [shape.parts[i].name, shape.parts[j].name],
                                 "units": round(dist, 3), "px": _px(dist, sizes), "at": _at(where)})
    measured = [f for f in features if "units" in f]
    thinnest = min(measured, key=lambda f: f["units"]) if measured else None
    exact_min = floor_px * 100 / thinnest["units"] if thinnest else 0.0
    exact_clear = clear_px * 100 / thinnest["units"] if thinnest else 0.0

    def first(px):
        return next((size for size in sizes if all(f["units"] * size / 100 >= px - 1e-9 for f in measured)), None)

    failing = {str(size): [label(f, size) for f in sorted(measured, key=lambda f: f["units"])
                           if f["units"] * size / 100 < floor_px - 1e-9] for size in sizes}
    unclear = {str(size): [label(f, size) for f in sorted(measured, key=lambda f: f["units"])
                           if floor_px - 1e-9 <= f["units"] * size / 100 < clear_px - 1e-9] for size in sizes}
    return {"features": sorted(features, key=lambda f: f.get("units", math.inf)), "thinnest": thinnest,
            "minimum_px": first(floor_px), "exact_minimum_px": ceil2(exact_min),
            "clear_from_px": first(clear_px), "exact_clear_from_px": ceil2(exact_clear),
            "failing": failing, "faint": unclear, "islands": len(islands)}


def label(feature, size):
    px = trunc(feature["units"] * size / 100)
    if feature["kind"] == "seam":
        what = f'seam between "{feature["between"][0]}" and "{feature["between"][1]}"'
    elif feature["kind"] == "opening":
        what = f'opening in "{feature["part"]}"'
    else:
        what = f'width of "{feature["part"]}"'
    where = f' at {feature["at"][0]:g},{feature["at"][1]:g}' if feature.get("at") else ""
    return f'{what}{where}: {feature["units"]:g} units = {px:.2f} px at {size} px'


def summary(row, floor_px=FLOOR_PX, clear_px=CLEAR_PX, sizes=SIZES):
    smallest = str(sizes[0])
    head = (f'present (every feature >= {floor_px:g} px) from {row["minimum_px"]} px' if row["minimum_px"]
            else f'not present at any checked size (needs {row["exact_minimum_px"]:g} px)')
    clear = (f'; clear (>= {clear_px:g} px) from {row["clear_from_px"]} px' if row["clear_from_px"]
             else f'; clear only from {row["exact_clear_from_px"]:g} px')
    fails = row["failing"][smallest]
    tail = f'; fails at {smallest} px: ' + "; ".join(fails) if fails else f"; passes at {smallest} px"
    return head + clear + tail


def board_note(row, floor_px=FLOOR_PX, clear_px=CLEAR_PX):
    """One honest sentence for boards and BRAND.md: the claimed minimum and what was measured."""
    present = f'{row["minimum_px"]}px' if row["minimum_px"] else f'{row["exact_minimum_px"]:g}px (above every checked size)'
    clear = f'{row["clear_from_px"]}px' if row["clear_from_px"] else f'{row["exact_clear_from_px"]:g}px (above every checked size)'
    declared = row.get("declared_minimum_px")
    override = (f' The concept declared {declared}px; the measurement sets the minimum.'
                if declared and declared < row["claim_px"] else "")
    return (f'Symbol minimum: {row["claim_px"]}px. Measured from the saved vectors: every feature and gap is at '
            f'least {floor_px:g} px from {present} and at least {clear_px:g} px from {clear}.{override} '
            'Smaller sizes stay shown for inspection.')


def check(concepts, *, sizes=SIZES, floor_px=FLOOR_PX, clear_px=CLEAR_PX):
    """Size report for saved concepts ({id, name, symbol, minimum_symbol_px})."""
    if not 0 < floor_px <= clear_px <= 8:
        raise ValueError("size check floor and clear thresholds must be 0 < floor <= clear <= 8 px")
    rows = []
    for concept in concepts:
        row = measure(concept["symbol"], sizes=sizes, floor_px=floor_px, clear_px=clear_px)
        declared = concept.get("minimum_symbol_px")
        measured = row["minimum_px"] or math.ceil(row["exact_minimum_px"])
        rows.append({"id": concept["id"], "name": concept.get("name", concept["id"]), "declared_minimum_px": declared,
                     "claim_px": max(declared or 0, measured), **row,
                     "summary": summary(row, floor_px, clear_px, sizes)})
    return {"method": METHOD, "limits": LIMITS, "sizes": list(sizes), "floor_px": floor_px, "clear_px": clear_px,
            "symbols": rows}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("concepts", help="JSON file: a list of concepts or an object with 'concepts'")
    parser.add_argument("--floor", type=float, default=FLOOR_PX)
    parser.add_argument("--clear", type=float, default=CLEAR_PX)
    args = parser.parse_args(argv)
    with open(args.concepts, encoding="utf-8") as handle:
        data = json.load(handle)
    concepts = data["concepts"] if isinstance(data, dict) else data
    json.dump(check(concepts, floor_px=args.floor, clear_px=args.clear), sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
