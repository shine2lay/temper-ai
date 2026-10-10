/**
 * The glance map's lines, their counts and the dots' paths (Design's map
 * contract: DECISION-MAP-LINES-2026-10-09, D42-D58). A port of Design's
 * reference router (glance.mjs: LINE, routeLines, bridgeLine) and badge
 * spots (page.mjs), with the same constants and the same cost order.
 *
 * A line never crosses a card or the You/Temper hub. It is straight when
 * the two facing sides overlap and nothing is between them; otherwise it
 * runs along the gutters' midlines (and, in a gutter at least 52 px wide,
 * tracks 18 px either side) on the cheapest path. Each line has its own
 * port, 30 px from the next and 28 px from a card's corner. Every order of
 * the lines is tried (at most 6) and the one with the fewest failures, then
 * shared stretches, then the lowest crossings x 700 + px beside a card x 6
 * + px in a bundle x 6 + length wins. A crossing that remains is drawn with
 * a hop, and the dot follows the painted path. You/Temper hub lines are
 * later lines (D81, hubPaths): routed after the drawn ones, clear of the
 * counts, hopped where they cross. Pure geometry: the page measures the
 * cards.
 */

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Point {
  x: number;
  y: number;
}

type Side = 'left' | 'right' | 'top' | 'bottom';
type Seg = [Point, Point];
type Dir = readonly [number, number];

/** Design's router constants (glance.mjs LINE, D52 and D58). */
export const LINE = {
  pad: 8,
  port: 30,
  corner: 28,
  track: 18,
  bend: 60,
  reuse: 100000,
  cross: 700,
  near: 400,
  radius: 8,
  hug: 28,
  hugCost: 6,
  nearCost: 6,
} as const;

/** Length of p-q that runs alongside one of rs, closer than LINE.hug (28 px) but outside it. */
export function hugLength(p: Point, q: Point, rs: Rect[]): number {
  let len = 0;
  const v = Math.abs(p.x - q.x) < 0.01;
  for (const r of rs) {
    const c = v ? p.x : p.y;
    const lo = v ? r.x : r.y;
    const hi = v ? r.x + r.w : r.y + r.h;
    const d = c < lo ? lo - c : c > hi ? c - hi : 0;
    if (d <= 0 || d >= LINE.hug) continue;
    const a0 = v ? Math.min(p.y, q.y) : Math.min(p.x, q.x);
    const a1 = v ? Math.max(p.y, q.y) : Math.max(p.x, q.x);
    const b0 = v ? r.y : r.x;
    const b1 = v ? r.y + r.h : r.x + r.w;
    const ov = Math.min(a1, b1) - Math.max(a0, b0);
    if (ov > 1) len += ov;
  }
  return len;
}

/** The side of r that faces o. */
export function facingSide(r: Rect, o: Rect): Side {
  const gx = Math.max(o.x - (r.x + r.w), r.x - (o.x + o.w));
  const gy = Math.max(o.y - (r.y + r.h), r.y - (o.y + o.h));
  if (gx >= gy) return o.x + o.w / 2 >= r.x + r.w / 2 ? 'right' : 'left';
  return o.y + o.h / 2 >= r.y + r.h / 2 ? 'bottom' : 'top';
}

const horizSide = (s: Side) => s === 'left' || s === 'right';

/** The side of r on the other axis toward o, when the two don't overlap on that axis (D58); else null. */
function altSide(r: Rect, o: Rect, s: Side): Side | null {
  if (horizSide(s)) return o.y >= r.y + r.h ? 'bottom' : o.y + o.h <= r.y ? 'top' : null;
  return o.x >= r.x + r.w ? 'right' : o.x + o.w <= r.x ? 'left' : null;
}

const OUT: Record<Side, Dir> = { left: [-1, 0], right: [1, 0], top: [0, -1], bottom: [0, 1] };

function sideSpan(r: Rect, s: Side): [number, number] {
  return horizSide(s) ? [r.y, r.y + r.h] : [r.x, r.x + r.w];
}

function portPoint(r: Rect, s: Side, c: number): Point {
  if (s === 'left') return { x: r.x, y: c };
  if (s === 'right') return { x: r.x + r.w, y: c };
  if (s === 'top') return { x: c, y: r.y };
  return { x: c, y: r.y + r.h };
}

const inflate = (r: Rect, d: number): Rect => ({ x: r.x - d, y: r.y - d, w: r.w + 2 * d, h: r.h + 2 * d });
const inside = (p: Point, r: Rect) => p.x > r.x && p.x < r.x + r.w && p.y > r.y && p.y < r.y + r.h;

/**
 * Does p-q run alongside one of segs, closer than gap? slack > 0 also counts
 * two collinear stretches that nearly touch end to end (they read as one).
 */
function parallelClose(p: Point, q: Point, segs: Seg[], gap: number, slack = 0): boolean {
  const vert = Math.abs(p.x - q.x) < 0.01;
  const horiz = Math.abs(p.y - q.y) < 0.01;
  const ov = (a0: number, a1: number, b0: number, b1: number) =>
    Math.min(Math.max(a0, a1), Math.max(b0, b1)) - Math.max(Math.min(a0, a1), Math.min(b0, b1)) > -slack;
  return segs.some(([a, b]) => {
    if (vert && Math.abs(a.x - b.x) < 0.01 && Math.abs(a.x - p.x) < gap) return ov(a.y, b.y, p.y, q.y);
    if (horiz && Math.abs(a.y - b.y) < 0.01 && Math.abs(a.y - p.y) < gap) return ov(a.x, b.x, p.x, q.x);
    return false;
  });
}

/**
 * The midlines of the gaps between the edges; with tracks (D58), a gap wide
 * enough also gets a track 18 px either side of its midline.
 */
function midlines(edges: number[], max: number, tracks = false): number[] {
  const v = [...new Set([0, max, ...edges].map((e) => Math.round(e * 2) / 2))].sort((a, b) => a - b);
  const out: number[] = [];
  for (let i = 0; i < v.length - 1; i++) {
    const g = v[i + 1] - v[i];
    const c = (v[i] + v[i + 1]) / 2;
    if (g < 2 * LINE.pad + 4) continue;
    out.push(c);
    if (tracks && g >= 2 * (LINE.pad + LINE.track)) out.push(c - LINE.track, c + LINE.track);
  }
  return out;
}

function simplify(pts: Point[]): Point[] {
  const out = [pts[0]];
  for (let i = 1; i < pts.length; i++) {
    const p = pts[i];
    const a = out[out.length - 1];
    if (Math.abs(p.x - a.x) < 0.01 && Math.abs(p.y - a.y) < 0.01) continue;
    if (out.length >= 2) {
      const b = out[out.length - 2];
      if (
        (Math.abs(b.x - a.x) < 0.01 && Math.abs(a.x - p.x) < 0.01) ||
        (Math.abs(b.y - a.y) < 0.01 && Math.abs(a.y - p.y) < 0.01)
      ) {
        out[out.length - 1] = p;
        continue;
      }
    }
    out.push(p);
  }
  return out;
}

/** Where a corner's rounding starts and ends (radius 8, at most half of either stretch). */
function cornerCut(a: Point, p: Point, b: Point, radius: number): { p1: Point; p2: Point } | null {
  const la = Math.hypot(p.x - a.x, p.y - a.y);
  const lb = Math.hypot(b.x - p.x, b.y - p.y);
  if (la === 0 || lb === 0) return null;
  const r = Math.min(radius, la / 2, lb / 2);
  return {
    p1: { x: p.x - ((p.x - a.x) / la) * r, y: p.y - ((p.y - a.y) / la) * r },
    p2: { x: p.x + ((b.x - p.x) / lb) * r, y: p.y + ((b.y - p.y) / lb) * r },
  };
}

/** Rounded-corner SVG path for a polyline (the same path carries the moving dot). */
export function roundedPath(pts: Point[], radius: number = LINE.radius): string {
  if (pts.length < 3) return 'M ' + pts.map((p) => `${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' L ');
  let d = `M ${pts[0].x.toFixed(1)} ${pts[0].y.toFixed(1)}`;
  for (let i = 1; i < pts.length - 1; i++) {
    const p = pts[i];
    const cut = cornerCut(pts[i - 1], p, pts[i + 1], radius);
    if (!cut) continue;
    const { p1, p2 } = cut;
    d += ` L ${p1.x.toFixed(1)} ${p1.y.toFixed(1)} Q ${p.x.toFixed(1)} ${p.y.toFixed(1)} ${p2.x.toFixed(1)} ${p2.y.toFixed(1)}`;
  }
  const z = pts[pts.length - 1];
  return d + ` L ${z.x.toFixed(1)} ${z.y.toFixed(1)}`;
}

/**
 * The points a dot passes through on roundedPath(pts): each rounded corner
 * sampled, so the dot follows the painted line (D29).
 */
export function flightPoints(pts: Point[], radius: number = LINE.radius, steps = 4): Point[] {
  if (pts.length < 3) return pts.map((p) => ({ x: p.x, y: p.y }));
  const out: Point[] = [{ x: pts[0].x, y: pts[0].y }];
  for (let i = 1; i < pts.length - 1; i++) {
    const p = pts[i];
    const cut = cornerCut(pts[i - 1], p, pts[i + 1], radius);
    if (!cut) continue;
    const { p1, p2 } = cut;
    out.push(p1);
    for (let k = 1; k < steps; k++) {
      const t = k / steps;
      const u = 1 - t;
      out.push({ x: u * u * p1.x + 2 * u * t * p.x + t * t * p2.x, y: u * u * p1.y + 2 * u * t * p.y + t * t * p2.y });
    }
    out.push(p2);
  }
  const z = pts[pts.length - 1];
  out.push({ x: z.x, y: z.y });
  return out;
}

const intersects = (a: Rect, b: Rect) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

/**
 * A visible hop at a perpendicular crossing with an earlier line (D29):
 * lines crossing are not a junction. Cards, the hub and the count badges
 * stay clear of the hop's whole box; a hop that can't clear them is skipped
 * (and counted). The result also carries the dot.
 */
export function bridgeLine(
  pts: Point[],
  previous: Point[][] = [],
  boxes: Rect[] = [],
): { pts: Point[]; path: string; bridges: Point[]; skipped: Point[] } {
  const out = [pts[0]];
  const bridges: Point[] = [];
  const skipped: Point[] = [];
  for (let i = 0; i < pts.length - 1; i++) {
    const a = pts[i];
    const b = pts[i + 1];
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const length = Math.hypot(dx, dy);
    const horizontal = Math.abs(dy) < 0.01;
    const vertical = Math.abs(dx) < 0.01;
    if (!length || (!horizontal && !vertical)) {
      out.push(b);
      continue;
    }
    const u = { x: dx / length, y: dy / length };
    const hits = new Map<string, { c: Point; along: number }>();
    for (const line of previous) {
      for (let k = 0; k < line.length - 1; k++) {
        const p = line[k];
        const q = line[k + 1];
        if (horizontal ? Math.abs(p.x - q.x) >= 0.01 : Math.abs(p.y - q.y) >= 0.01) continue;
        const c = horizontal ? { x: p.x, y: a.y } : { x: a.x, y: p.y };
        const along = (c.x - a.x) * u.x + (c.y - a.y) * u.y;
        const other = horizontal ? c.y : c.x;
        const p0 = horizontal ? p.y : p.x;
        const q0 = horizontal ? q.y : q.x;
        if (along <= 14 || along >= length - 14 || other <= Math.min(p0, q0) + 3 || other >= Math.max(p0, q0) - 3) continue;
        hits.set(`${c.x.toFixed(2)},${c.y.toFixed(2)}`, { c, along });
      }
    }
    let last = -Infinity;
    for (const { c, along } of [...hits.values()].sort((p, q) => p.along - q.along)) {
      if (along - last < 20) {
        skipped.push(c);
        continue;
      }
      const before = { x: c.x - u.x * 8, y: c.y - u.y * 8 };
      const after = { x: c.x + u.x * 8, y: c.y + u.y * 8 };
      let peak: Point | null = null;
      for (const side of [-1, 1]) {
        const p = horizontal ? { x: c.x, y: c.y + side * 14 } : { x: c.x + side * 14, y: c.y };
        const x = Math.min(before.x, after.x, p.x) - 3;
        const y = Math.min(before.y, after.y, p.y) - 3;
        const bound = { x, y, w: Math.max(before.x, after.x, p.x) + 3 - x, h: Math.max(before.y, after.y, p.y) + 3 - y };
        if (!boxes.some((box) => intersects(bound, box))) {
          peak = p;
          break;
        }
      }
      if (!peak) {
        skipped.push(c);
        continue;
      }
      out.push(before, peak, after);
      bridges.push(c);
      last = along;
    }
    out.push(b);
  }
  return { pts: out, path: roundedPath(out), bridges, skipped };
}

const DIRS: Dir[] = [
  [1, 0],
  [-1, 0],
  [0, 1],
  [0, -1],
];
const dirIdx = (d: Dir) => DIRS.findIndex((v) => v[0] === d[0] && v[1] === d[1]);
/** Each direction's U-turn (no U-turn on the grid). */
const BACK = [1, 0, 3, 2];

/**
 * gridPath's working arrays, kept from call to call (one call at a time) and grown for a bigger grid. A slot
 * counts in a call only when its stamp is that call's number, so nothing needs clearing between calls.
 */
const scratch = {
  cap: 0,
  gen: 0,
  /** Per state: stamp, cost so far, previous state. */
  seen: new Int32Array(0),
  dist: new Float64Array(0),
  prev: new Int32Array(0),
  /** Per directed edge: stamp, length (Infinity: blocked), cost of the placed lines on it. */
  asked: new Int32Array(0),
  step: new Float64Array(0),
  extra: new Float64Array(0),
  /** Per node: stamp, free (1) or not (0). */
  nodeSeen: new Int32Array(0),
  free: new Uint8Array(0),
  /** The open list's entries: cost, push number, state. */
  hc: new Float64Array(0),
  hs: new Int32Array(0),
  hk: new Int32Array(0),
};

function gridScratch(states: number): typeof scratch {
  const s = scratch;
  if (states > s.cap) {
    const cap = Math.max(states, 2 * s.cap);
    s.cap = cap;
    s.gen = 0;
    s.seen = new Int32Array(cap);
    s.dist = new Float64Array(cap);
    s.prev = new Int32Array(cap);
    s.asked = new Int32Array(cap);
    s.step = new Float64Array(cap);
    s.extra = new Float64Array(cap);
    s.nodeSeen = new Int32Array(cap);
    s.free = new Uint8Array(cap);
    // A state is settled once and then pushes at most 3 entries: 1 + 3 * states bounds the open list.
    s.hc = new Float64Array(1 + 3 * cap);
    s.hs = new Int32Array(1 + 3 * cap);
    s.hk = new Int32Array(1 + 3 * cap);
  }
  if (s.gen >= 0x3fffffff) {
    s.seen.fill(0);
    s.asked.fill(0);
    s.nodeSeen.fill(0);
    s.gen = 0;
  }
  s.gen += 1;
  return s;
}

/**
 * Shortest orthogonal path on the midline grid (Dijkstra over node + direction, no U-turn, 60 px a bend).
 *
 * The open list pops the lowest cost, ties first in first out (the reference's stable sort): (cost, push number)
 * orders every entry, so any heap pops them in the same order. Costs never go down along a path, so the search
 * stops once the cheapest open entry costs no less than the best route found: nothing after it can be strictly
 * cheaper, the only way the best changes. A node's and an edge's checks are asked once each (they are pure for
 * the call); the sums keep the reference's order, so every cost is the same number.
 *
 * `beaten`: the caller needs this route only if it costs less than one it has. Asked with the cheapest open cost
 * (no route found here can cost less), true gives up (null); asked with the least any route through an entry can
 * cost, true leaves that entry unexpanded. A route that wins keeps every entry on it and on every route as cheap,
 * so it is the route found without `beaten`.
 */
function gridPath(
  start: Point,
  startDir: Dir,
  end: Point,
  endDir: Dir,
  xs: number[],
  ys: number[],
  grid: GridAsk,
  beaten?: (cost: number) => boolean,
): { pts: Point[]; cost: number } | null {
  const X = [...new Set(xs)].sort((a, b) => a - b);
  const Y = [...new Set(ys)].sort((a, b) => a - b);
  const xi = X.indexOf(start.x);
  const yi = Y.indexOf(start.y);
  const xe = X.indexOf(end.x);
  const ye = Y.indexOf(end.y);
  if (xi < 0 || yi < 0 || xe < 0 || ye < 0) return null;
  const nx = X.length;
  const ny = Y.length;
  const xk = X.map(grid.xNum);
  const yk = Y.map(grid.yNum);
  // A state is (i * ny + j) * 4 + d; a directed edge is its from-node * 4 + its direction.
  const { gen, seen, dist, prev, asked, step, extra, nodeSeen, free, hc, hs, hk } = gridScratch(nx * ny * 4);
  // The open list: a binary heap on (cost, push number).
  let size = 0;
  const push = (c: number, s: number, k: number) => {
    let at = size++;
    while (at > 0) {
      const up = (at - 1) >> 1;
      if (!(c < hc[up] || (c === hc[up] && s < hs[up]))) break;
      hc[at] = hc[up];
      hs[at] = hs[up];
      hk[at] = hk[up];
      at = up;
    }
    hc[at] = c;
    hs[at] = s;
    hk[at] = k;
  };
  // Remove the top entry (read it first).
  const pop = () => {
    size -= 1;
    if (size === 0) return;
    const c = hc[size];
    const s = hs[size];
    const k = hk[size];
    let at = 0;
    for (;;) {
      const l = 2 * at + 1;
      if (l >= size) break;
      const r = l + 1;
      const m = r < size && (hc[r] < hc[l] || (hc[r] === hc[l] && hs[r] < hs[l])) ? r : l;
      if (!(hc[m] < c || (hc[m] === c && hs[m] < s))) break;
      hc[at] = hc[m];
      hs[at] = hs[m];
      hk[at] = hk[m];
      at = m;
    }
    hc[at] = c;
    hs[at] = s;
    hk[at] = k;
  };
  const d0 = dirIdx(startDir);
  const dEnd = dirIdx(endDir);
  const ex = X[xe];
  const ey = Y[ye];
  const s0 = (xi * ny + yi) * 4 + d0;
  seen[s0] = gen;
  dist[s0] = 0;
  prev[s0] = -1;
  let seq = 0;
  push(0, seq++, s0);
  let bestCost = Infinity;
  let bestK = -1;
  while (size > 0) {
    const c = hc[0];
    const k = hk[0];
    pop();
    if (bestK >= 0 && c >= bestCost) break;
    // Every route still to be found here, and the one found (it costs more than c), costs at least c.
    if (beaten?.(c)) return null;
    if (c > dist[k]) continue;
    const d = k & 3;
    const node = k >> 2;
    const i = Math.floor(node / ny);
    const j = node - i * ny;
    if (beaten) {
      // The least the rest can cost: its length is at least the distance across and up, and it bends at least
      // twice when it heads as it must end but the end isn't straight ahead, once when it heads otherwise (an end
      // met on another heading costs a bend too). Less a margin, as sums of the same numbers may round lower.
      const [ux, uy] = DIRS[d];
      const di = xe - i;
      const dj = ye - j;
      const ahead = ux !== 0 ? dj === 0 && (di === 0 || Math.sign(di) === ux) : di === 0 && (dj === 0 || Math.sign(dj) === uy);
      const bends = d === dEnd ? (ahead ? 0 : 2) : 1;
      const least = c + Math.abs(ex - X[i]) + Math.abs(ey - Y[j]) + bends * LINE.bend;
      if (beaten(least * (1 - 1e-9) - 1e-6)) continue;
    }
    if (i === xe && j === ye) {
      const total = c + (d === dEnd ? 0 : LINE.bend);
      if (bestK < 0 || total < bestCost) {
        bestCost = total;
        bestK = k;
      }
      continue;
    }
    for (let nd = 0; nd < 4; nd++) {
      if (nd === BACK[d]) continue; // no U-turn
      const ni = i + DIRS[nd][0];
      const nj = j + DIRS[nd][1];
      if (ni < 0 || nj < 0 || ni >= nx || nj >= ny) continue;
      // The edge's length (Infinity: blocked) and what running near or crossing the placed lines costs on it.
      const e = node * 4 + nd;
      if (asked[e] !== gen) {
        asked[e] = gen;
        const qn = ni * ny + nj;
        if (nodeSeen[qn] !== gen) {
          nodeSeen[qn] = gen;
          free[qn] = grid.free(X[ni], Y[nj], xk[ni], yk[nj]) ? 1 : 0;
        }
        const price = free[qn] ? grid.price(X[i], Y[j], X[ni], Y[nj], xk[i], yk[j], xk[ni], yk[nj]) : Infinity;
        if (price === Infinity) step[e] = Infinity;
        else {
          step[e] = Math.hypot(X[ni] - X[i], Y[nj] - Y[j]);
          extra[e] = price;
        }
      }
      const len = step[e];
      if (len === Infinity) continue;
      const nc = c + len + (nd === d ? 0 : LINE.bend) + extra[e];
      const nk = (ni * ny + nj) * 4 + nd;
      if (seen[nk] !== gen || nc < dist[nk]) {
        seen[nk] = gen;
        dist[nk] = nc;
        prev[nk] = k;
        push(nc, seq++, nk);
      }
    }
  }
  if (bestK < 0) return null;
  const pts: Point[] = [];
  for (let k = bestK; k !== -1; k = prev[k]) {
    const n = k >> 2;
    pts.push({ x: X[Math.floor(n / ny)], y: Y[n % ny] });
    if (k === s0) break;
  }
  return { pts: pts.reverse(), cost: bestCost };
}

/**
 * What a grid search asks of the map: numbers for the grid's coordinates (the same for every search of a map),
 * whether a node is free, and an edge p-q's price apart from its length (Infinity: it can't be run). The numbers
 * are given so the answers can be kept by them.
 */
interface GridAsk {
  xNum: (x: number) => number;
  yNum: (y: number) => number;
  free: (x: number, y: number, xn: number, yn: number) => boolean;
  price: (px: number, py: number, qx: number, qy: number, pxn: number, pyn: number, qxn: number, qyn: number) => number;
}

/** Does segment p-q touch rect r? (Liang-Barsky clip.) */
export function segRect(p: Point, q: Point, r: Rect): boolean {
  let t0 = 0;
  let t1 = 1;
  const dx = q.x - p.x;
  const dy = q.y - p.y;
  // The four clip checks [pp, qq], in order: [-dx, p.x - r.x], [dx, r.x + r.w - p.x], [-dy, p.y - r.y], [dy, r.y + r.h - p.y].
  for (let k = 0; k < 4; k++) {
    const pp = k === 0 ? -dx : k === 1 ? dx : k === 2 ? -dy : dy;
    const qq = k === 0 ? p.x - r.x : k === 1 ? r.x + r.w - p.x : k === 2 ? p.y - r.y : r.y + r.h - p.y;
    if (pp === 0) {
      if (qq < 0) return false;
      continue;
    }
    const t = qq / pp;
    if (pp < 0) {
      if (t > t1) return false;
      if (t > t0) t0 = t;
    } else {
      if (t < t0) return false;
      if (t < t1) t1 = t;
    }
  }
  return t0 < t1;
}

function crossesStrict(p: Point, q: Point, a: Point, b: Point): boolean {
  const v1 = Math.abs(p.x - q.x) < 0.01;
  const v2 = Math.abs(a.x - b.x) < 0.01;
  if (v1 === v2) return false;
  const [V, H] = v1 ? [[p, q], [a, b]] : [[a, b], [p, q]];
  const x = V[0].x;
  const y = H[0].y;
  return (
    x > Math.min(H[0].x, H[1].x) + 1 &&
    x < Math.max(H[0].x, H[1].x) - 1 &&
    y > Math.min(V[0].y, V[1].y) + 1 &&
    y < Math.max(V[0].y, V[1].y) - 1
  );
}

function* permutations<T>(xs: T[]): Generator<T[]> {
  if (xs.length <= 1) {
    yield xs;
    return;
  }
  for (let i = 0; i < xs.length; i++) {
    for (const rest of permutations([...xs.slice(0, i), ...xs.slice(i + 1)])) yield [xs[i], ...rest];
  }
}

const segsOf = (pts: Point[]): Seg[] => pts.slice(1).map((q, i) => [pts[i], q]);

/** The point at fraction f of a polyline's length. */
export function pathPoint(pts: Point[], f: number): Point {
  const segs = pts.slice(1).map((p, i) => ({ a: pts[i], b: p, l: Math.hypot(p.x - pts[i].x, p.y - pts[i].y) }));
  const total = segs.reduce((s, x) => s + x.l, 0);
  let d = f * total;
  for (const s of segs) {
    if (d <= s.l || s === segs[segs.length - 1]) {
      const t = s.l ? Math.min(1, d / s.l) : 0;
      return { x: s.a.x + (s.b.x - s.a.x) * t, y: s.a.y + (s.b.y - s.a.y) * t };
    }
    d -= s.l;
  }
  return pts[0];
}

export interface RoutedPair {
  a: string;
  b: string;
  /** From a's port to b's port. */
  pts: Point[];
  path: string;
  straight: boolean;
}

export interface RouteResult {
  /** "a\u0000b" -> the pair's route. */
  lines: Map<string, RoutedPair>;
  /** Pairs with no route ("a–b"). */
  failed: string[];
  /** Stretches two lines still share ("a–b / c–d"); the bar is none. */
  shared: string[];
  /** Runs within 28 px of a card a line doesn't join ("a–b: 12 px"). */
  hugs: string[];
  crossings: number;
  /** px where two lines run parallel closer than three tracks (54 px). */
  near: number;
  /** px within 28 px of a card, all lines. */
  hug: number;
  length: number;
  /** The order the lines were routed in ("a\u0000b"): a later line is routed round the earlier ones. */
  order: string[];
  /** With `vary`: that line's tries, in the router's order (D83): index 0 is the route it gets anyway. */
  tries?: Point[][];
}

export interface RouteOptions {
  width: number;
  height: number;
  /** Rects the lines avoid but never join (the You/Temper hub). */
  obstacles?: Rect[];
  /**
   * Polylines already drawn (D81): a new line pays to cross or run near them,
   * never runs within LINE.track beside them and never takes their ports.
   * Empty for the map's own lines.
   */
  placed?: Point[][];
  /** Rects a new line keeps clear of without adding grid midlines (count badges, D81). */
  avoid?: Rect[];
  /** Prices over LINE's (D81: a hub line pays less to cross or run near a line, as it hops and lasts one cue). */
  cost?: Partial<Record<keyof typeof LINE, number>>;
  /**
   * D83: lines ("a\u0000b") routed by another of the router's tries for them: the index into that line's tries
   * (0 = the route it gets anyway; its straight heights in the router's order, then its routes through the gaps,
   * cheapest first). The chosen order stays; the lines after a pinned one are routed round it as usual.
   */
  pins?: ReadonlyMap<string, number>;
  /** D83: route in this order (a result's `order`) instead of choosing one. */
  order?: string[];
  /** D83: also return this line's ("a\u0000b") tries, as it would take them where it is routed. */
  vary?: string;
}

interface Job {
  a: string;
  b: string;
  A: Rect;
  B: Rect;
  sa: Side;
  sb: Side;
  overlap: [number, number];
  straightable: boolean;
  dist: number;
}

const OPPOSITE: Record<Side, Side> = { left: 'right', right: 'left', top: 'bottom', bottom: 'top' };

/**
 * Route the map's lines (pairs of names in rects) as a whole. Mirrors
 * Design's routeLines (glance.mjs) step for step, so the same cards give the
 * same routes.
 */
export function routeLines(pairs: Array<{ a: string; b: string }>, rects: Map<string, Rect>, options: RouteOptions): RouteResult {
  return lineRouter(pairs, rects, options)(options);
}

/** One line's route where the lines before it lie (lineRouter keeps them); failed: it has none. */
type Placement =
  | { kind: 'straight'; c: number; p: Point; q: Point }
  | { kind: 'gap'; sA: Side; ca: number; sB: Side; cb: number; pts: Point[] }
  | { kind: 'failed' };

/** A line's tries where the lines before it lie: its straight heights, then its routes through the gaps, cheapest first. */
interface Tries {
  straights: Array<{ c: number; p: Point; q: Point }>;
  gaps: Array<{ sA: Side; ca: number; sB: Side; cb: number; pts: Point[] }>;
}

/** Try n of a line's tries; failed past the last. */
function tryOf(t: Tries, n: number): Placement {
  if (n < t.straights.length) {
    const s = t.straights[n];
    return { kind: 'straight', c: s.c, p: s.p, q: s.q };
  }
  const g = t.gaps[n - t.straights.length];
  return g ? { kind: 'gap', ...g } : { kind: 'failed' };
}

/**
 * routeLines in two steps: what stays the same for one map (its cards, grid, lines and prices), then any number
 * of routings of it, each with its own pins, order and listed line (mapGeometry's D83 re-routes share one).
 *
 * A line's route depends only on its pin and on the lines placed before it (their routes and ports). So each
 * line's route is kept per state of the lines before it: another order (D52 tries every one) or a re-route that
 * brings the line to the same state takes it from there instead of routing it again. With whole-number prices
 * the order those lines were placed in doesn't matter (a run's price is a sum of whole numbers, and every other
 * check is yes or no for each line), so the state is the set of them; otherwise it is the sequence. The listed
 * line (`vary`) is always routed, for its tries.
 */
function lineRouter(
  pairs: Array<{ a: string; b: string }>,
  rects: Map<string, Rect>,
  { width, height, obstacles = [], placed: fixedLines = [], avoid = [], cost: prices = {} }: RouteOptions,
): (ask?: Pick<RouteOptions, 'pins' | 'order' | 'vary'>) => RouteResult {
  const P: Record<keyof typeof LINE, number> = { ...LINE, ...prices };
  const all = [...rects.values(), ...obstacles];
  // D58: vertical midlines come from the cards only (not the hub).
  const cardsOnly = [...rects.values()];
  const xMid = midlines(cardsOnly.flatMap((r) => [r.x, r.x + r.w]), width);
  const yMid = midlines(all.flatMap((r) => [r.y, r.y + r.h]), height);
  const xGrid = midlines(cardsOnly.flatMap((r) => [r.x, r.x + r.w]), width, true);
  const yGrid = midlines(all.flatMap((r) => [r.y, r.y + r.h]), height, true);
  let taken = new Map<string, number[]>();
  let out = new Map<string, RoutedPair>();
  let failed: string[] = [];
  // The lines placed so far, as ids (`place`): the state the next line is routed in; and their segments.
  let placedIds: string[] = [];
  let segsNow: Seg[] | null = null;
  // The placed lines' price on each directed edge a grid search asked (see `grid`), while they stay as they are.
  let placedPrice = [new Map<number, number>(), new Map<number, number>()];
  // Per line and state: the route it takes unpinned, and (once asked for) all its tries.
  const firstTry = new Map<string, Placement>();
  const everyTry = new Map<string, Tries>();
  const asSet = Object.values(P).every((v) => Number.isInteger(v));
  const isFree = (name: string, s: Side, c: number) => (taken.get(`${name}|${s}`) ?? []).every((t) => Math.abs(t - c) >= P.port);
  const take = (name: string, s: Side, c: number) => {
    const k = `${name}|${s}`;
    taken.set(k, [...(taken.get(k) ?? []), c]);
  };
  const pickPort = (name: string, r: Rect, s: Side, ideal: number, ok: (c: number) => boolean = () => true) => {
    const [a, b] = sideSpan(r, s);
    const min = a + P.corner;
    const max = b - P.corner;
    // A side too short for corner margins (the You/Temper hub's 24 px ends, D5): one port, in its middle.
    if (min > max) {
      const c = (a + b) / 2;
      return isFree(name, s, c) && ok(c) ? c : null;
    }
    const c0 = Math.min(max, Math.max(min, ideal));
    for (let k = 0; k < 80; k++) {
      for (const c of k === 0 ? [c0] : [c0 + 3 * k, c0 - 3 * k]) {
        if (c >= min && c <= max && isFree(name, s, c) && ok(c)) return c;
      }
    }
    return null;
  };
  const fixedSegs: Seg[] = fixedLines.flatMap((pts) => segsOf(pts));
  const placedSegs = (): Seg[] => (segsNow ??= [...fixedSegs, ...[...out.values()].flatMap((o) => segsOf(o.pts))]);
  // D81: a placed line's ends keep their ports, so a later line (a hub line) never lands on a socket.
  const seedTaken = () => {
    for (const pts of fixedLines) {
      for (const p of [pts[0], pts[pts.length - 1]]) {
        for (const [name, r] of rects) {
          for (const s of ['left', 'right', 'top', 'bottom'] as const) {
            const c = horizSide(s) ? p.y : p.x;
            const q = portPoint(r, s, c);
            const [lo, hi] = sideSpan(r, s);
            if (Math.hypot(q.x - p.x, q.y - p.y) < 0.6 && c >= lo && c <= hi) take(name, s, c);
          }
        }
      }
    }
  };
  // A run alongside a placed line closer than three tracks reads as one bundle (near); one on the same stretch is
  // forbidden in effect (reuse); a crossing costs a short detour (cross).
  const used = (p: Point, q: Point) => {
    let cost = 0;
    const pv = Math.abs(p.x - q.x) < 0.01;
    for (const [a, b] of placedSegs()) {
      const av = Math.abs(a.x - b.x) < 0.01;
      const ah = Math.abs(a.y - b.y) < 0.01;
      const ovY = Math.min(Math.max(a.y, b.y), Math.max(p.y, q.y)) - Math.max(Math.min(a.y, b.y), Math.min(p.y, q.y));
      const ovX = Math.min(Math.max(a.x, b.x), Math.max(p.x, q.x)) - Math.max(Math.min(a.x, b.x), Math.min(p.x, q.x));
      if (pv && av && Math.abs(a.x - p.x) >= P.track && Math.abs(a.x - p.x) < 3 * P.track && ovY > 1) cost += P.near;
      if (!pv && ah && Math.abs(a.y - p.y) >= P.track && Math.abs(a.y - p.y) < 3 * P.track && ovX > 1) cost += P.near;
      if (pv && av && Math.abs(a.x - p.x) < P.track && ovY > 1) cost += P.reuse;
      else if (!pv && ah && Math.abs(a.y - p.y) < P.track && ovX > 1) cost += P.reuse;
      else if (
        pv &&
        ah &&
        p.x > Math.min(a.x, b.x) + 1 &&
        p.x < Math.max(a.x, b.x) - 1 &&
        a.y > Math.min(p.y, q.y) + 1 &&
        a.y < Math.max(p.y, q.y) - 1
      )
        cost += P.cross;
      else if (
        !pv &&
        av &&
        a.x > Math.min(p.x, q.x) + 1 &&
        a.x < Math.max(p.x, q.x) - 1 &&
        p.y > Math.min(a.y, b.y) + 1 &&
        p.y < Math.max(a.y, b.y) - 1
      )
        cost += P.cross;
    }
    return cost;
  };
  const others = (A: Rect, B: Rect) => all.filter((r) => r !== A && r !== B);
  const stubEnd = (p: Point, s: Side): Point | null => {
    const [dx, dy] = OUT[s];
    if (dx) {
      const c =
        dx > 0
          ? xMid.filter((x) => x > p.x + P.pad).sort((a, b) => a - b)[0]
          : xMid.filter((x) => x < p.x - P.pad).sort((a, b) => b - a)[0];
      return c === undefined ? null : { x: c, y: p.y };
    }
    const c =
      dy > 0
        ? yMid.filter((y) => y > p.y + P.pad).sort((a, b) => a - b)[0]
        : yMid.filter((y) => y < p.y - P.pad).sort((a, b) => b - a)[0];
    return c === undefined ? null : { x: p.x, y: c };
  };

  const jobs = pairs
    .map((p): Job | null => {
      const A = rects.get(p.a);
      const B = rects.get(p.b);
      if (!A || !B) return null;
      const sa = facingSide(A, B);
      const sb = facingSide(B, A);
      const [a0, a1] = sideSpan(A, sa);
      const [b0, b1] = sideSpan(B, sb);
      const overlap: [number, number] = [Math.max(a0, b0) + P.corner, Math.min(a1, b1) - P.corner];
      const straightable = sb === OPPOSITE[sa] && overlap[0] <= overlap[1];
      const dist = Math.abs(A.x + A.w / 2 - B.x - B.w / 2) + Math.abs(A.y + A.h / 2 - B.y - B.h / 2);
      return { a: p.a, b: p.b, A, B, sa, sb, overlap, straightable, dist };
    })
    .filter((j): j is Job => j !== null)
    .sort((x, y) => Number(y.straightable) - Number(x.straightable) || x.dist - y.dist);

  // What a route through the gaps keeps clear of (the cards, the hub, the counts) and what a run of it costs: the
  // same for every line (the cost reads the lines placed when it is asked).
  const allObs = [...all, ...avoid].map((r) => inflate(r, P.pad - 0.5));
  const nodeFree = (p: Point) => !allObs.some((r) => inside(p, r));
  const fullBlocked = (p: Point, q: Point) => allObs.some((r) => segRect(p, q, r));
  const cost = (p: Point, q: Point) => used(p, q) + hugLength(p, q, all) * P.hugCost;
  // The grid searches' answers, kept by the coordinates' numbers (as first met; past NUMS of them, asked afresh):
  // whether a node is free, and a directed edge's own price (blocked, else running beside a card) for the map; the
  // placed lines' price on it for the lines placed now (emptied whenever they change). An edge's price is the sum
  // cost() makes of the same two parts.
  const NUMS = 1024;
  const xNums = new Map<number, number>();
  const yNums = new Map<number, number>();
  const numOf = (nums: Map<number, number>, v: number) => {
    let n = nums.get(v);
    if (n === undefined) {
      n = nums.size;
      nums.set(v, n);
    }
    return n;
  };
  const freeAt = new Map<number, boolean>();
  // [across, up and down]
  const ownPrice = [new Map<number, number>(), new Map<number, number>()];
  const grid: GridAsk = {
    xNum: (x) => numOf(xNums, x),
    yNum: (y) => numOf(yNums, y),
    free: (x, y, xn, yn) => {
      if (xn >= NUMS || yn >= NUMS) return nodeFree({ x, y });
      const key = xn * NUMS + yn;
      let f = freeAt.get(key);
      if (f === undefined) {
        f = nodeFree({ x, y });
        freeAt.set(key, f);
      }
      return f;
    },
    price: (px, py, qx, qy, pxn, pyn, qxn, qyn) => {
      const upDown = pxn === qxn;
      const at = upDown ? pxn : pyn;
      const from = upDown ? pyn : pxn;
      const to = upDown ? qyn : qxn;
      if (at >= NUMS || from >= NUMS || to >= NUMS) {
        const p = { x: px, y: py };
        const q = { x: qx, y: qy };
        return fullBlocked(p, q) ? Infinity : cost(p, q);
      }
      const key = (at * NUMS + from) * NUMS + to;
      const way = upDown ? 1 : 0;
      let own = ownPrice[way].get(key);
      if (own === undefined) {
        const p = { x: px, y: py };
        const q = { x: qx, y: qy };
        own = fullBlocked(p, q) ? Infinity : hugLength(p, q, all) * P.hugCost;
        ownPrice[way].set(key, own);
      }
      if (own === Infinity) return Infinity;
      let lines = placedPrice[way].get(key);
      if (lines === undefined) {
        lines = used({ x: px, y: py }, { x: qx, y: qy });
        placedPrice[way].set(key, lines);
      }
      return lines + own;
    },
  };

  /**
   * Place a line's route: its ports taken, its route drawn. A route kept for later is drawn as a copy, as pulling
   * shared stretches apart moves a drawn route's points; the listed line's route is drawn as found, so its tries
   * share those points as the reference's do.
   */
  const place = (j: Job, key: string, at: Placement, copy: boolean) => {
    if (at.kind === 'failed') {
      failed.push(`${j.a}\u2013${j.b}`);
      return;
    }
    if (at.kind === 'straight') {
      take(j.a, j.sa, at.c);
      take(j.b, j.sb, at.c);
      out.set(key, { a: j.a, b: j.b, pts: copy ? [{ ...at.p }, { ...at.q }] : [at.p, at.q], path: '', straight: true });
    } else {
      take(j.a, at.sA, at.ca);
      take(j.b, at.sB, at.cb);
      out.set(key, { a: j.a, b: j.b, pts: copy ? at.pts.map((p) => ({ ...p })) : at.pts, path: '', straight: false });
    }
    const ends = at.kind === 'straight' ? `${j.sa} ${at.c} ${j.sb} ${at.c}` : `${at.sA} ${at.ca} ${at.sB} ${at.cb}`;
    placedIds.push(`${key}\u0003${ends}\u0003${out.get(key)!.pts.map((p) => `${p.x},${p.y}`).join(' ')}`);
    segsNow = null;
    placedPrice = [new Map(), new Map()];
  };

  /**
   * One line's tries where the lines placed so far lie. every: all of them, in the router's order (a pinned or
   * listed line); else only the one it takes unpinned (the first), found without the rest.
   */
  const tryLine = (j: Job, lineCount: number, every: boolean): Tries => {
    const { A, B, sa, sb } = j;
    const obs = [...others(A, B), ...avoid].map((r) => inflate(r, P.pad - 0.5));
    const segBlocked = (p: Point, q: Point) => obs.some((r) => segRect(p, q, r));
    // 1. Straight, when the facing sides overlap and nothing is between.
    const straights: Tries['straights'] = [];
    if (j.straightable) {
      const [lo, hi] = j.overlap;
      const mid = (lo + hi) / 2;
      // SPEC [D58]: a line stays 28 px from a card it doesn't join. glance.mjs takes the first free
      // height from the middle out, which can pass a card 10 px off when card heights differ (the app's
      // cards grow with their words); so the nearest height that keeps 28 px wins, else glance.mjs's pick.
      const unrelated = others(A, B);
      const clean: typeof straights = [];
      const hugging: typeof straights = [];
      for (let k = 0; k < 80 && (every || !clean.length); k++) {
        for (const c of k === 0 ? [mid] : [mid + 3 * k, mid - 3 * k]) {
          if (c < lo || c > hi || !isFree(j.a, sa, c) || !isFree(j.b, sb, c)) continue;
          const p = portPoint(A, sa, c);
          const q = portPoint(B, sb, c);
          if (segBlocked(p, q) || parallelClose(p, q, placedSegs(), P.track)) continue;
          (hugLength(p, q, unrelated) > 0.5 ? hugging : clean).push({ c, p, q });
          if (!every && clean.length) break;
        }
      }
      straights.push(...clean, ...hugging);
    }
    if (!every && straights.length) return { straights: [straights[0]], gaps: [] };
    {
      // 2. Through the gaps.
      const ideal = (s: Side, o: Rect) => (horizSide(s) ? o.y + o.h / 2 : o.x + o.w / 2);
      // A port whose stub would run along another line reads as that line: skip it.
      const stubOk = (r: Rect, s: Side) => (c: number) => {
        const p = portPoint(r, s, c);
        const e = stubEnd(p, s);
        return !!e && !parallelClose(p, e, placedSegs(), P.port, 16);
      };
      const idA = ideal(sa, B);
      const idB = ideal(sb, A);
      // D58: the port facing the other card and the two ends of the side (page maps only: at most 6 lines).
      const portsOf = (name: string, r: Rect, s: Side, id: number) => {
        const [s0, s1] = sideSpan(r, s);
        const tries = lineCount <= 6 ? [id, s0 + P.corner, s1 - P.corner] : [id];
        return [...new Set(tries.map((c) => pickPort(name, r, s, c, stubOk(r, s))).filter((c): c is number => c !== null))];
      };
      type Combo = [Side, number, number, Side, number, number];
      const combos: Combo[] = [];
      for (const ca of portsOf(j.a, A, sa, idA)) for (const cb of portsOf(j.b, B, sb, idB)) combos.push([sa, ca, idA, sb, cb, idB]);
      if (lineCount <= 6) {
        const one = (name: string, r: Rect, s: Side | null, o: Rect): [Side, number, number] | null => {
          if (!s) return null;
          const id = ideal(s, o);
          const c = pickPort(name, r, s, id, stubOk(r, s));
          return c === null ? null : [s, c, id];
        };
        const fa = one(j.a, A, sa, B);
        const fb = one(j.b, B, sb, A);
        const xa = one(j.a, A, altSide(A, B, sa), B);
        const xb = one(j.b, B, altSide(B, A, sb), A);
        if (xa && fb) combos.push([...xa, ...fb]);
        if (fa && xb) combos.push([...fa, ...xb]);
        if (xa && xb) combos.push([...xa, ...xb]);
      }
      const gaps: Array<{ total: number; sA: Side; ca: number; sB: Side; cb: number; pa: Point; pb: Point; mid: Point[] }> = [];
      // Only the cheapest route is wanted when not every try is: of equal ones the first found, so a later one
      // counts only if it costs less than the cheapest so far. A route's total grows with its middle's cost (each
      // sum of the total does), so its search gives up once even the cheapest open cost can't win.
      let cheapest = Infinity;
      for (const [sA, ca, iA, sB, cb, iB] of combos) {
        const pa = portPoint(A, sA, ca);
        const pb = portPoint(B, sB, cb);
        const ea = stubEnd(pa, sA);
        const eb = stubEnd(pb, sB);
        if (!ea || !eb || segBlocked(pa, ea) || segBlocked(pb, eb)) continue;
        const xs = [...xGrid, ea.x, eb.x];
        const ys = [...yGrid, ea.y, eb.y];
        const [odx, ody] = OUT[sB];
        const toA = Math.hypot(ea.x - pa.x, ea.y - pa.y);
        const toB = Math.hypot(pb.x - eb.x, pb.y - eb.y);
        const stubA = cost(pa, ea);
        const stubB = cost(eb, pb);
        const off = 0.5 * (Math.abs(ca - iA) + Math.abs(cb - iB));
        const totalOf = (midCost: number) => midCost + toA + toB + stubA + stubB + off;
        // (Nothing to beat yet: no bound.)
        const beaten = every || cheapest === Infinity ? undefined : (c: number) => totalOf(c) >= cheapest;
        const mid = gridPath(ea, OUT[sA], eb, [-odx, -ody], xs, ys, grid, beaten);
        if (!mid) continue;
        const total = totalOf(mid.cost);
        if (total < cheapest) cheapest = total;
        gaps.push({ total, sA, ca, sB, cb, pa, pb, mid: mid.pts });
      }
      // Cheapest first; the sort is stable, so of equal ones the first found stays first, as the router picks.
      gaps.sort((x, y) => x.total - y.total);
      return {
        straights,
        gaps: (every ? gaps : gaps.slice(0, 1)).map((g) => ({ sA: g.sA, ca: g.ca, sB: g.sB, cb: g.cb, pts: simplify([g.pa, ...g.mid, g.pb]) })),
      };
    }
  };

  /**
   * Route the lines in this order. A pinned line (D83) takes its try of that index; `count` names the line whose
   * tries are listed.
   */
  const attempt = (order: Job[], pinned: ReadonlyMap<string, number> = new Map(), count?: string) => {
    taken = new Map();
    out = new Map();
    failed = [];
    placedIds = [];
    segsNow = null;
    placedPrice = [new Map(), new Map()];
    seedTaken();
    let listed: Point[][] = [];
    for (const j of order) {
      const key = `${j.a}\u0000${j.b}`;
      // Which of the line's tries it takes; null: the usual one, found without listing the others.
      const pin = pinned.get(key) ?? (key === count ? 0 : null);
      // The same line where the same lines lie as in an earlier order or re-route: its tries from then.
      const mk = `${key}\u0001${order.length}\u0001${(asSet ? [...placedIds].sort() : placedIds).join('\u0002')}`;
      const known = everyTry.get(mk);
      if (pin === null) {
        let at = firstTry.get(mk) ?? (known && tryOf(known, 0));
        if (!at) {
          at = tryOf(tryLine(j, order.length, false), 0);
          firstTry.set(mk, at);
        }
        place(j, key, at, true);
        continue;
      }
      let tries = known;
      if (!tries) {
        tries = tryLine(j, order.length, true);
        everyTry.set(mk, tries);
      }
      if (key !== count) {
        place(j, key, tryOf(tries, pin), true);
        continue;
      }
      // The listed line: its tries as found here, and its route is one of them (the same points, as the stretches
      // pulled apart below move them).
      const own = [...tries.straights.map((s) => [{ ...s.p }, { ...s.q }]), ...tries.gaps.map((g) => g.pts.map((p) => ({ ...p })))];
      listed = own;
      const at = tryOf(tries, pin);
      if (at.kind === 'straight') place(j, key, { ...at, p: own[pin][0], q: own[pin][1] }, false);
      else if (at.kind === 'gap') place(j, key, { ...at, pts: [...own[pin]] }, false);
      else place(j, key, at, false);
    }
    // 3. Pull shared stretches apart: interior segments on the same midline that overlap get 18 px tracks.
    const segsAll: Array<{ L: RoutedPair; i: number; vert: boolean; c: number; lo: number; hi: number }> = [];
    for (const L of out.values()) {
      for (let i = 1; i < L.pts.length - 2; i++) {
        const p = L.pts[i];
        const q = L.pts[i + 1];
        const vert = Math.abs(p.x - q.x) < 0.01;
        segsAll.push({
          L,
          i,
          vert,
          c: vert ? p.x : p.y,
          lo: Math.min(vert ? p.y : p.x, vert ? q.y : q.x),
          hi: Math.max(vert ? p.y : p.x, vert ? q.y : q.x),
        });
      }
    }
    const groups: Array<{ vert: boolean; c: number; items: typeof segsAll }> = [];
    for (const s of segsAll) {
      const g = groups.find(
        (g) =>
          g.vert === s.vert && Math.abs(g.c - s.c) < 0.5 && g.items.some((t) => Math.min(t.hi, s.hi) - Math.max(t.lo, s.lo) > 1),
      );
      if (g) g.items.push(s);
      else groups.push({ vert: s.vert, c: s.c, items: [s] });
    }
    const near2 = all.map((r) => inflate(r, 2));
    for (const g of groups) {
      if (g.items.length < 2) continue;
      const k = g.items.length;
      g.items.forEach((s, n) => {
        const off = (n - (k - 1) / 2) * P.track;
        const saved = s.L.pts.map((p) => ({ ...p }));
        const p = s.L.pts[s.i];
        const q = s.L.pts[s.i + 1];
        if (s.vert) {
          p.x += off;
          q.x += off;
        } else {
          p.y += off;
          q.y += off;
        }
        const own = [rects.get(s.L.a), rects.get(s.L.b)];
        const bad = s.L.pts.some(
          (pt, i) =>
            i < s.L.pts.length - 1 &&
            near2.some((r, ri) => {
              const src = all[ri];
              if ((i === 0 && src === own[0]) || (i === s.L.pts.length - 2 && src === own[1])) return false;
              return segRect(pt, s.L.pts[i + 1], r);
            }),
        );
        if (bad) s.L.pts.splice(0, s.L.pts.length, ...saved);
      });
    }
    for (const L of out.values()) L.path = roundedPath(L.pts);
    const Ls = [...out.values()];
    let crossings = 0;
    let length = 0;
    let hug = 0;
    const hugs: string[] = [];
    for (const L of Ls) {
      const unrelated = others(rects.get(L.a)!, rects.get(L.b)!);
      let h = 0;
      for (const [p, q] of segsOf(L.pts)) {
        length += Math.hypot(q.x - p.x, q.y - p.y);
        h += hugLength(p, q, unrelated);
      }
      if (h > 0.5) hugs.push(`${L.a}\u2013${L.b}: ${Math.round(h)} px`);
      hug += h;
    }
    // near (D58): length where two lines run parallel closer than three tracks (54 px).
    let near = 0;
    for (let i = 0; i < Ls.length; i++) {
      for (let k = i + 1; k < Ls.length; k++) {
        for (const [p, q] of segsOf(Ls[i].pts)) {
          for (const [a, b] of segsOf(Ls[k].pts)) {
            if (crossesStrict(p, q, a, b)) crossings++;
            const v1 = Math.abs(p.x - q.x) < 0.01;
            const v2 = Math.abs(a.x - b.x) < 0.01;
            const h1 = Math.abs(p.y - q.y) < 0.01;
            const h2 = Math.abs(a.y - b.y) < 0.01;
            const d = v1 && v2 ? Math.abs(p.x - a.x) : h1 && h2 ? Math.abs(p.y - a.y) : Infinity;
            if (!(d > 0.5 && d < 3 * P.track)) continue;
            const ov = v1
              ? Math.min(Math.max(p.y, q.y), Math.max(a.y, b.y)) - Math.max(Math.min(p.y, q.y), Math.min(a.y, b.y))
              : Math.min(Math.max(p.x, q.x), Math.max(a.x, b.x)) - Math.max(Math.min(p.x, q.x), Math.min(a.x, b.x));
            if (ov > 1) near += ov;
          }
        }
      }
    }
    const shared = groups.filter((g) => g.items.length >= 2).map((g) => g.items.map((s) => `${s.L.a}\u2013${s.L.b}`).join(' / '));
    return { lines: out, failed, shared, crossings, length, hug, hugs, near, order, listed };
  };

  // D52: the routing order decides who gets a shared gutter. Try the default order; when it leaves a failure, a
  // shared stretch, a crossing, a run beside a card or a bundle, try every order (page maps only: at most 6 lines)
  // and keep the best: fewest failures, then shared stretches, then crossings x 700 + hug x 6 + near x 6 + length.
  // D83: an order given (a result's own) is kept, with the pinned lines by their tries.
  const keyOf = (j: Job) => `${j.a}\u0000${j.b}`;
  return ({ pins = new Map(), order: fixedOrder, vary } = {}) => {
    const first = fixedOrder?.flatMap((k) => jobs.filter((j) => keyOf(j) === k));
    let best = first ? attempt([...first, ...jobs.filter((j) => !first.includes(j))], pins, vary) : attempt(jobs);
    if (!first && (best.failed.length || best.shared.length || best.crossings || best.hug || best.near) && jobs.length <= 6) {
      const score = (x: typeof best) => [
        x.failed.length,
        x.shared.length,
        x.crossings * P.cross + x.hug * P.hugCost + x.near * P.nearCost + x.length,
      ];
      for (const order of permutations(jobs)) {
        const r = attempt(order);
        const [a, b] = [score(r), score(best)];
        const k = a.findIndex((v, i) => v !== b[i]);
        if (k >= 0 && a[k] < b[k]) best = r;
      }
    }
    if (!first && (pins.size || vary !== undefined)) best = attempt(best.order, pins, vary);
    return {
      lines: best.lines,
      failed: best.failed,
      shared: best.shared,
      hugs: best.hugs,
      crossings: best.crossings,
      near: Math.round(best.near),
      hug: best.hug,
      length: best.length,
      order: best.order.map(keyOf),
      tries: vary === undefined ? undefined : best.listed,
    };
  };
}

// --- count badges ----------------------------------------------------------------------

/** A count badge's height and its width for a number: 14 px digits in a pill at least 28 px wide (D43). */
export const BADGE_H = 20;
export function badgeWidth(count: number): number {
  return Math.max(28, 16 + 9 * String(count).length);
}

/**
 * The smallest count drawn in a badge as wide as this one's (the width counts the digits). The map sees a count only
 * through its badge's width, so counts with the same badgeCount route the same map: the page routes with this, and a
 * count that keeps its badge's width (12 to 13) routes nothing, while one that crosses a width (9 to 10) does.
 */
export function badgeCount(count: number): number {
  return 10 ** (String(count).length - 1);
}

/**
 * Spot order (D57, D58): 28 px from every other line and 40 px from cards the
 * line doesn't join; else 16 and 24; else 16 px from lines; else 8 px from
 * lines (a short gutter run another line must cross). Tier 5 = no allowed
 * spot (a check failure; the page doesn't draw it).
 */
export const BADGE_TIERS: ReadonlyArray<readonly [tier: 1 | 2 | 3 | 4, gap: number, cardGap: number]> = [
  [1, 28, 40],
  [2, 16, 24],
  [3, 16, 0],
  [4, 8, 0],
];

export interface BadgeSpot {
  key: string;
  at: Point;
  box: Rect;
  tier: 1 | 2 | 3 | 4 | 5;
  /**
   * No allowed spot (tier 5): the page leaves this count off the map (the
   * hour list below still has it), so it is no obstacle to anything else.
   */
  forced: boolean;
}

const overlap = (a: Rect, b: Rect, pad = 0) =>
  a.x < b.x + b.w + pad && b.x < a.x + a.w + pad && a.y < b.y + b.h + pad && b.y < a.y + a.h + pad;

const lengthOf = (pts: Point[]) => segsOf(pts).reduce((s, [p, q]) => s + Math.hypot(q.x - p.x, q.y - p.y), 0);

/**
 * Each line's count on its own straight run (page.mjs): short lines first
 * (they have the fewest spots); along each stretch, longest first, from its
 * middle outward every 6 px, never within 12 px of its ends; never on a card,
 * the hub or another badge (10 px), and as far from other lines and
 * unrelated cards as the spot order allows. Returned in the input's order.
 * A count with no allowed spot is marked forced and is never drawn, so it
 * keeps no other count away (page.mjs drew it mid-line and failed its check).
 * With `only`, just that line's count, with no other count in its way (D83).
 */
export function placeBadges(
  lines: Array<{ key: string; a: string; b: string; pts: Point[]; w: number; h: number }>,
  cards: Map<string, Rect>,
  hubs: Rect[] = [],
  only?: string,
): BadgeSpot[] {
  const all = [...cards.values()];
  const boxes = [...all, ...hubs];
  const placed = new Map<string, BadgeSpot>();
  for (const L of [...lines].sort((a, b) => lengthOf(a.pts) - lengthOf(b.pts))) {
    if (only !== undefined && L.key !== only) continue;
    const otherSegs = lines.filter((o) => o !== L).flatMap((o) => segsOf(o.pts));
    const tries = segsOf(L.pts)
      .map(([p, q]) => ({ p, q, l: Math.hypot(q.x - p.x, q.y - p.y) }))
      .sort((a, b) => b.l - a.l)
      .flatMap((s) => {
        const out: Point[] = [];
        const half = Math.max(0, s.l / 2 - 12);
        for (let d = 0; d <= half; d += 6) {
          for (const sgn of d ? [1, -1] : [1]) {
            const t = (s.l / 2 + sgn * d) / (s.l || 1);
            out.push({ x: s.p.x + (s.q.x - s.p.x) * t, y: s.p.y + (s.q.y - s.p.y) * t });
          }
        }
        return out;
      });
    const own = [cards.get(L.a), cards.get(L.b)];
    const unrelated = [...all.filter((r) => !own.includes(r)), ...hubs];
    let spot: BadgeSpot | null = null;
    for (const [tier, gap, cardGap] of BADGE_TIERS) {
      for (const p of tries) {
        const box = { x: p.x - L.w / 2, y: p.y - L.h / 2, w: L.w, h: L.h };
        const grown = { x: box.x - gap, y: box.y - gap, w: box.w + 2 * gap, h: box.h + 2 * gap };
        const hit =
          boxes.some((r) => overlap(box, r, 3)) ||
          [...placed.values()].some((b) => !b.forced && overlap(box, b.box, 10)) ||
          (cardGap > 0 && unrelated.some((r) => overlap(box, r, cardGap))) ||
          otherSegs.some(([a, b]) => segRect(a, b, grown));
        if (!hit) {
          spot = { key: L.key, at: p, box, tier, forced: false };
          break;
        }
      }
      if (spot) break;
    }
    if (!spot) {
      const p = pathPoint(L.pts, 0.5);
      spot = { key: L.key, at: p, box: { x: p.x - L.w / 2, y: p.y - L.h / 2, w: L.w, h: L.h }, tier: 5, forced: true };
    }
    placed.set(L.key, spot);
  }
  return lines.flatMap((l) => placed.get(l.key) ?? []);
}

// --- the whole map -------------------------------------------------------------------------

/** Shortest distance between segment p-q and rect r (0 when they touch). */
export function segRectDistance(p: Point, q: Point, r: Rect): number {
  if (segRect(p, q, r)) return 0;
  const toRect = (s: Point) => {
    const dx = Math.max(r.x - s.x, 0, s.x - (r.x + r.w));
    const dy = Math.max(r.y - s.y, 0, s.y - (r.y + r.h));
    return Math.hypot(dx, dy);
  };
  const toSeg = (s: Point) => {
    const dx = q.x - p.x;
    const dy = q.y - p.y;
    const l2 = dx * dx + dy * dy;
    const t = l2 ? Math.max(0, Math.min(1, ((s.x - p.x) * dx + (s.y - p.y) * dy) / l2)) : 0;
    return Math.hypot(p.x + t * dx - s.x, p.y + t * dy - s.y);
  };
  const corners = [
    { x: r.x, y: r.y },
    { x: r.x + r.w, y: r.y },
    { x: r.x, y: r.y + r.h },
    { x: r.x + r.w, y: r.y + r.h },
  ];
  return Math.min(toRect(p), toRect(q), ...corners.map(toSeg));
}

export interface MapLineIn {
  /** "a|b", the pair in name order. */
  key: string;
  a: string;
  b: string;
  count: number;
}

export interface PaintedLine extends MapLineIn {
  /** The route as the router left it (a's port to b's port). */
  route: Point[];
  /** The painted polyline, crossing hops included: the dot's path. */
  pts: Point[];
  /** SVG path data of pts, corners rounded at 8 px. */
  path: string;
  straight: boolean;
  /** Crossings drawn with a hop, and crossings that couldn't get one. */
  hops: number;
  unhopped: number;
  /** px within 28 px of a card (or the hub) the line doesn't join. */
  hug: number;
  /** Nearest distance to a card (or the hub) the line doesn't join. */
  clearance: number;
}

export interface MapGeometry {
  lines: PaintedLine[];
  /** One per painted line, same order. */
  badges: BadgeSpot[];
  failed: string[];
  shared: string[];
  crossings: number;
  unhopped: number;
  near: number;
  hug: number;
  /**
   * D83: a count had no allowed spot on its line's usual route, and another of
   * the router's tries for that line gave it one: these lines are that route.
   */
  rerouted: boolean;
}

/**
 * Route, place the counts, then paint: in the drawn order (newest first),
 * each later line hops the earlier ones it crosses, clear of cards, the hub
 * and the counts (page.mjs drawMap).
 *
 * D83: when a count has no allowed spot (tier 5), its line first tries the
 * router's other tries for it (its other straight heights, then its routes
 * through the gaps, cheapest first; the lines after it routed round it as
 * usual) and takes the first that gives the count a spot, takes no other
 * count's spot and is no worse on the map's bars (failures, shared
 * stretches, runs near cards, unhopped crossings). None: the line keeps its
 * route and its count is left off the map (the pair list keeps the number).
 * Each re-route costs as much as routing the map once, so a count gets at
 * most `reroutes` of them (D83_REROUTES), the first tries in the router's
 * order whose count has a spot among the lines before it.
 */
export function mapGeometry(
  lines: MapLineIn[],
  cards: Map<string, Rect>,
  hubs: Rect[],
  box: { w: number; h: number },
  { reroutes = D83_REROUTES }: { reroutes?: number } = {},
): MapGeometry {
  const pairs = lines.map((l) => ({ a: l.a, b: l.b }));
  // One router for the map: a re-route (D83) takes the lines it shares with an earlier routing from it.
  const route = lineRouter(pairs, cards, { width: box.w, height: box.h, obstacles: hubs });
  let routes = route();
  let map = paintMap(lines, routes, cards, hubs);
  const pins = new Map<string, number>();
  const dropped = (g: MapGeometry) => new Set(g.badges.filter((b) => b.forced).map((b) => b.key));
  for (const key of dropped(map)) {
    // An earlier line's new route may have given this count its spot.
    if (!dropped(map).has(key)) continue;
    const line = lines.find((l) => l.key === key)!;
    const id = `${line.a}\u0000${line.b}`;
    const before = dropped(map);
    const { order } = routes;
    // The lines routed before this one stay as they are whichever try it takes, and the later ones only take
    // spots away: a try with no spot even among the earlier ones alone is passed over without routing the rest.
    const earlier = order.slice(0, order.indexOf(id)).flatMap((k) => {
      const r = routes.lines.get(k);
      return r ? [{ key: k, a: r.a, b: r.b, pts: r.pts, w: 0, h: 0 }] : [];
    });
    const size = { w: badgeWidth(line.count), h: BADGE_H };
    let left = reroutes;
    for (const [k, pts] of (route({ pins, order, vary: id }).tries ?? []).entries()) {
      if (left <= 0) break;
      if (k === 0 || placeBadges([{ key, a: line.a, b: line.b, pts, ...size }, ...earlier], cards, hubs, key)[0].forced) continue;
      left -= 1;
      const other = route({ pins: new Map([...pins, [id, k]]), order });
      if (other.failed.length > routes.failed.length || other.shared.length > routes.shared.length) continue;
      if (other.hug > routes.hug + 0.5) continue;
      const geometry = paintMap(lines, other, cards, hubs);
      const after = dropped(geometry);
      if (geometry.lines.length < map.lines.length || geometry.unhopped > map.unhopped) continue;
      if (after.has(key) || [...after].some((x) => !before.has(x))) continue;
      pins.set(id, k);
      routes = other;
      map = { ...geometry, rerouted: true };
      break;
    }
  }
  return map;
}

/** D83: at most this many re-routes for a count with no spot (each costs one routing of the map). */
export const D83_REROUTES = 8;

/** Place the counts on routed lines and paint them (mapGeometry's second half). */
function paintMap(lines: MapLineIn[], routed: RouteResult, cards: Map<string, Rect>, hubs: Rect[]): MapGeometry {
  const kept = lines.flatMap((l) => {
    const r = routed.lines.get(`${l.a}\u0000${l.b}`);
    return r ? [{ ...l, route: r.pts, straight: r.straight }] : [];
  });
  const badges = placeBadges(
    kept.map((l) => ({ key: l.key, a: l.a, b: l.b, pts: l.route, w: badgeWidth(l.count), h: BADGE_H })),
    cards,
    hubs,
  );
  // A forced count is never drawn, so a hop need not keep clear of it.
  const hopBoxes = [...cards.values(), ...hubs, ...badges.filter((b) => !b.forced).map((b) => b.box)];
  const previous: Point[][] = [];
  let unhopped = 0;
  let crossings = 0;
  const painted = kept.map((l): PaintedLine => {
    const paint = bridgeLine(l.route, previous, hopBoxes);
    previous.push(l.route);
    crossings += paint.bridges.length + paint.skipped.length;
    unhopped += paint.skipped.length;
    const own = [cards.get(l.a), cards.get(l.b)];
    const unrelated = [...[...cards.values()].filter((r) => !own.includes(r)), ...hubs];
    let hug = 0;
    for (const [p, q] of segsOf(l.route)) hug += hugLength(p, q, unrelated);
    let clearance = Infinity;
    for (const [p, q] of segsOf(paint.pts)) for (const r of unrelated) clearance = Math.min(clearance, segRectDistance(p, q, r));
    return {
      ...l,
      pts: paint.pts,
      path: paint.path,
      hops: paint.bridges.length,
      unhopped: paint.skipped.length,
      hug,
      clearance,
    };
  });
  return {
    lines: painted,
    badges,
    failed: routed.failed,
    shared: routed.shared,
    crossings,
    unhopped,
    near: routed.near,
    hug: routed.hug,
    rerouted: false,
  };
}

// --- You/Temper hub lines (D81) ---------------------------------------------------------

/** A hub line keeps at least this far from every count badge (D81). */
export const HUB_BADGE_CLEAR = 16;
/** A hub line's prices to cross or run near a line: below a drawn line's 700/400, as it hops and lasts one cue (D81). */
export const HUB_COST = { cross: 350, near: 200 } as const;

export interface HubPath {
  /** The painted route, with a hop at each crossing: the dot follows it. */
  pts: Point[];
  path: string;
  /** The route before hops (what a later hub line is routed round). */
  base: Point[];
  /** Which try drew it: 1 = strict; 2-4 only when the stricter ones can't route it. */
  try: number;
  hops: number;
  unhopped: number;
}

export interface HubPathsInput {
  /** The member cards by name, map-relative. */
  rects: Map<string, Rect>;
  /** The You/Temper hub, or null when it isn't measured. */
  hub: Rect | null;
  /** The drawn lines' routes before hops. */
  lines?: Point[][];
  /** The count badges that are drawn. */
  badges?: Rect[];
  width: number;
  height: number;
}

/**
 * One step's hub lines (Design D81, glance.mjs hubPaths): a hub line is a
 * later line like any other. Each receiver in turn is routed after the drawn
 * lines and the step's earlier hub lines: it never takes their ports, never
 * runs within LINE.track beside them, pays HUB_COST to cross or run near one,
 * keeps HUB_BADGE_CLEAR from every count badge (badges are grown by the gap
 * left over the router's own pad, so a gutter midline exactly 16 px away
 * stays open), and hops where it crosses. A looser try only when the strict
 * one can't route it. When the gutters are taken, the grid goes round by the
 * map's edge. The hub's short ends keep one port in their middle (D5).
 */
export function hubPaths(receivers: Iterable<string>, input: HubPathsInput): Map<string, HubPath> {
  const { rects, hub, lines: drawn = [], badges = [], width, height } = input;
  const out = new Map<string, HubPath>();
  const tos = [...new Set(receivers)].filter((t) => rects.has(t));
  if (!tos.length || !hub) return out;
  const HUB = '\u0000hub';
  const all = new Map<string, Rect>([[HUB, hub], ...rects]);
  const clear = HUB_BADGE_CLEAR - LINE.pad;
  const boxes = [...rects.values(), hub, ...badges];
  const earlier: Point[][] = [];
  for (const b of tos) {
    const placed = [...drawn, ...earlier];
    const tries: Array<Pick<RouteOptions, 'placed' | 'avoid' | 'cost'>> = [
      { placed, avoid: badges.map((x) => inflate(x, clear)), cost: HUB_COST },
      { placed, avoid: badges, cost: HUB_COST },
      { placed, cost: HUB_COST },
      {},
    ];
    for (const [k, extra] of tries.entries()) {
      const { lines: got, failed } = routeLines([{ a: HUB, b }], all, { width, height, ...extra });
      const r = got.get(`${HUB}\u0000${b}`);
      if ((failed.length || !r) && k < tries.length - 1) continue;
      if (!r) break;
      const paint = bridgeLine(r.pts, placed, boxes);
      earlier.push(r.pts);
      out.set(b, {
        pts: paint.pts,
        path: paint.path,
        base: r.pts,
        try: k + 1,
        hops: paint.bridges.length,
        unhopped: paint.skipped.length,
      });
      break;
    }
  }
  return out;
}
