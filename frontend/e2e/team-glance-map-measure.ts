/**
 * The glance map as the browser drew it, measured in rendered pixels, for
 * Design's map-line bars (D52, D57, D58): for each drawn line, its hops, its
 * sockets, how close it comes to a card or the You/Temper corner it doesn't
 * join, whether it runs along another line, and where its count sits.
 * team-glance-map.spec.ts holds the map to the bars with it.
 */
import { expect, type Page } from '@playwright/test';
import { hubPaths } from '../src/lib/teamGlanceRoute';

export interface BadgeMeasure {
  /** The spot used, 1 (best) to 4 (a short run between cards), as the page marks it. */
  tier: number;
  text: string;
  /** The count's centre lies on its own line. */
  onLine: boolean;
  /** Closest other line, unrelated card or You/Temper corner, other count (px; null when none). */
  lineGap: number | null;
  cardGap: number | null;
  badgeGap: number | null;
}

export interface LineMeasure {
  pair: string;
  green: boolean;
  hops: number;
  sockets: number;
  /** A socket sits on each end of the line. */
  socketsAtEnds: boolean;
  /** Closest the line comes to a card or the You/Temper corner it doesn't join (px). */
  cardClear: number | null;
  /** Points of the line inside a card or the corner (its own cards included, 2 px in from their edge). */
  across: number;
  /** Stretches over 12 px where the line runs within 3 px of another line. */
  shared: number;
  badge: BadgeMeasure | null;
}

export interface MapMeasure {
  lines: LineMeasure[];
  /**
   * D80: the largest gap (px) between a box the lines were routed round (the page's data-card-boxes)
   * and the same card or corner as painted now; null when the page reports no boxes.
   */
  boxDrift: number | null;
  /** The boxes the router used, by card name (and "hub"), map-relative, as reported. */
  routedBoxes: Record<string, { x: number; y: number; w: number; h: number }>;
  /** The router's own report on the map element (data-*). */
  report: Record<string, string>;
}

/** Measure the drawn map (wide layouts only: the map is hidden under 768 px). */
export function measureMap(page: Page): Promise<MapMeasure> {
  return page.getByTestId('glance-map').evaluate((box) => {
    type P = { x: number; y: number };
    type R = { x: number; y: number; w: number; h: number };
    const rectOf = (el: Element): R => {
      const r = el.getBoundingClientRect();
      return { x: r.x, y: r.y, w: r.width, h: r.height };
    };
    const toRect = (p: P, r: R) =>
      Math.hypot(Math.max(r.x - p.x, 0, p.x - (r.x + r.w)), Math.max(r.y - p.y, 0, p.y - (r.y + r.h)));
    const rectGap = (a: R, b: R) =>
      Math.hypot(Math.max(b.x - (a.x + a.w), 0, a.x - (b.x + b.w)), Math.max(b.y - (a.y + a.h), 0, a.y - (b.y + b.h)));
    const inside = (p: P, r: R, inset: number) =>
      p.x > r.x + inset && p.x < r.x + r.w - inset && p.y > r.y + inset && p.y < r.y + r.h - inset;
    const screen = (el: SVGGraphicsElement, x: number, y: number): P => {
      const m = el.getScreenCTM()!;
      return { x: m.a * x + m.c * y + m.e, y: m.b * x + m.d * y + m.f };
    };
    const round = (n: number) => Math.round(n * 10) / 10;
    const min = (values: number[]) => (values.length ? round(Math.min(...values)) : null);

    const cards = new Map<string, R>();
    box.querySelectorAll<HTMLElement>('.glance-map-grid [data-member]').forEach((el) => cards.set(el.dataset.member!, rectOf(el)));
    // The You/Temper corner: one box, the router's obstacle (D76).
    const corner = Array.from(box.querySelectorAll('.glance-hub')).map(rectOf);
    const groups = Array.from(box.querySelectorAll<SVGGElement>('svg.glance-lines g[data-pair]'));
    const drawn = groups.map((g) => {
      const path = g.querySelector<SVGPathElement>('path[data-line]')!;
      const total = path.getTotalLength();
      const pts: P[] = [];
      for (let s = 0; s < total; s += 1) {
        const q = path.getPointAtLength(s);
        pts.push(screen(path, q.x, q.y));
      }
      const end = path.getPointAtLength(total);
      pts.push(screen(path, end.x, end.y));
      return { g, path, pair: g.dataset.pair!, pts };
    });
    const badges = new Map<string, { el: SVGGElement; box: R }>();
    box.querySelectorAll<SVGGElement>('svg.glance-counts g.glance-count').forEach((el) => {
      badges.set(el.dataset.count!, { el, box: rectOf(el.querySelector('rect')!) });
    });

    const lines = drawn.map((line) => {
      const ends = line.pair.split('|');
      const own = ends.map((name) => cards.get(name)).filter((r): r is R => !!r);
      const unrelated = [...[...cards].filter(([name]) => !ends.includes(name)).map(([, r]) => r), ...corner];
      const others = drawn.filter((o) => o !== line);
      // Points within 3 px of another line, in runs along this one (1 px apart).
      let shared = 0;
      let run = 0;
      for (const p of line.pts) {
        const near = others.some((o) => o.pts.some((q) => Math.hypot(p.x - q.x, p.y - q.y) < 3));
        run = near ? run + 1 : 0;
        if (run === 13) shared += 1;
      }
      const sockets = Array.from(line.g.querySelectorAll<SVGCircleElement>('circle.glance-socket')).map((c) =>
        screen(c, c.cx.baseVal.value, c.cy.baseVal.value),
      );
      const first = line.pts[0];
      const last = line.pts[line.pts.length - 1];
      const at = (p: P) => sockets.some((s) => Math.hypot(s.x - p.x, s.y - p.y) < 1);
      const badge = badges.get(line.pair);
      let badgeMeasure = null;
      if (badge) {
        const c = { x: badge.box.x + badge.box.w / 2, y: badge.box.y + badge.box.h / 2 };
        badgeMeasure = {
          tier: Number(badge.el.dataset.tier),
          text: badge.el.textContent ?? '',
          onLine: line.pts.some((p) => Math.hypot(p.x - c.x, p.y - c.y) < 1.5),
          lineGap: min(others.flatMap((o) => o.pts.map((p) => toRect(p, badge.box)))),
          cardGap: min(unrelated.map((r) => rectGap(badge.box, r))),
          badgeGap: min([...badges].filter(([key]) => key !== line.pair).map(([, b]) => rectGap(badge.box, b.box))),
        };
      }
      return {
        pair: line.pair,
        green: line.g.dataset.green === 'true',
        hops: Number(line.path.dataset.hops ?? 0),
        sockets: sockets.length,
        socketsAtEnds: at(first) && at(last),
        cardClear: min(line.pts.flatMap((p) => unrelated.map((r) => toRect(p, r)))),
        across: line.pts.filter((p) => unrelated.some((r) => inside(p, r, 1)) || own.some((r) => inside(p, r, 2))).length,
        shared,
        badge: badgeMeasure,
      };
    });
    const report: Record<string, string> = {};
    for (const name of ['linesDrawn', 'routeFailed', 'linesAlongside', 'crossingHops', 'unhopped', 'badgesForced', 'badgeTiers']) {
      report[name] = (box as HTMLElement).dataset[name] ?? '';
    }
    // D80: the router's boxes against the painted ones, both relative to the map box.
    const routedBoxes = JSON.parse((box as HTMLElement).dataset.cardBoxes || '{}') as Record<string, R>;
    const at = box.getBoundingClientRect();
    const painted = (key: string): R | null => {
      const el = key === 'hub' ? box.querySelector('.glance-hub') : box.querySelector(`.glance-map-grid [data-member="${CSS.escape(key)}"]`);
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { x: r.left - at.left, y: r.top - at.top, w: r.width, h: r.height };
    };
    const drifts = Object.entries(routedBoxes).map(([key, r]) => {
      const p = painted(key);
      return p ? Math.max(Math.abs(p.x - r.x), Math.abs(p.y - r.y), Math.abs(p.w - r.w), Math.abs(p.h - r.h)) : Infinity;
    });
    const boxDrift = drifts.length ? round(Math.max(...drifts)) : null;
    return { lines, report, boxDrift, routedBoxes };
  });
}

/** Each spot's distances from other lines and from unrelated cards (Design D57: 28/40, 16/24, 16/0, 8/0). */
export const SPOTS: Record<number, { line: number; card: number }> = {
  1: { line: 28, card: 40 },
  2: { line: 16, card: 24 },
  3: { line: 16, card: 0 },
  4: { line: 8, card: 0 },
};

/**
 * Design's bars on the drawn map: no route fails, nothing across a card or
 * the corner, no shared stretch, 28 px from cards a line doesn't join, a
 * socket on both ends of every line, every
 * crossing hopped, and each count on its own line in an allowed spot, 10 px
 * from the next count. Returns the measure for the record.
 */
export async function expectMapBars(page: Page): Promise<MapMeasure> {
  const measure = await measureMap(page);
  const { report } = measure;
  expect(report.routeFailed, 'routes that failed').toBe('0');
  expect(report.linesAlongside, 'shared stretches the router found').toBe('0');
  expect(report.unhopped, 'crossings without a hop').toBe('0');
  expect(report.badgesForced, 'counts with no allowed spot').toBe('0');
  expect(Number(report.linesDrawn)).toBe(measure.lines.length);
  for (const line of measure.lines) {
    const name = `line ${line.pair}`;
    expect(line.across, `${name}: points across a card`).toBe(0);
    expect(line.shared, `${name}: stretches along another line`).toBe(0);
    // D58: a line keeps 28 px from a card it doesn't join (these maps' lines all can).
    if (line.cardClear !== null) expect(line.cardClear, `${name}: clearance from a card it doesn't join`).toBeGreaterThanOrEqual(27.5);
    expect(line.sockets, `${name}: sockets`).toBe(2);
    expect(line.socketsAtEnds, `${name}: a socket on both ends`).toBe(true);
    expect(line.badge, `${name}: count`).not.toBeNull();
    const badge = line.badge!;
    const spot = SPOTS[badge.tier];
    expect(spot, `${name}: count spot ${badge.tier}`).toBeDefined();
    expect(badge.onLine, `${name}: count on its own line`).toBe(true);
    if (badge.lineGap !== null) expect(badge.lineGap, `${name}: count to another line`).toBeGreaterThanOrEqual(spot.line - 0.5);
    if (badge.cardGap !== null) expect(badge.cardGap, `${name}: count to an unrelated card`).toBeGreaterThanOrEqual(spot.card - 0.5);
    if (badge.badgeGap !== null) expect(badge.badgeGap, `${name}: count to count`).toBeGreaterThanOrEqual(9.5);
  }
  return measure;
}

// --- You/Temper hub lines (D81) -----------------------------------------------------------

type HubPoint = { x: number; y: number };
type HubBox = { x: number; y: number; w: number; h: number };

/** The map's last You/Temper batch (data-hub-routes): what it was routed round, map-relative, and its routes. */
export interface HubReport {
  rects: Record<string, HubBox>;
  hub: HubBox | null;
  /** The drawn lines before hops. */
  lines: HubPoint[][];
  /** The drawn counts. */
  badges: HubBox[];
  width: number;
  height: number;
  /** In routing order: `base` before hops, `pts` as painted (the dot's path); `try` 1 is the strict one. */
  routes: Array<{ to: string; try: number; hops: number; unhopped: number; base: HubPoint[]; pts: HubPoint[] }>;
}

/** The map's last hub batch, or null before one has flown. */
export async function readHubRoutes(page: Page): Promise<HubReport | null> {
  const raw = await page.getByTestId('glance-map').getAttribute('data-hub-routes');
  return raw ? (JSON.parse(raw) as HubReport) : null;
}

/** D81's bars, as Design's motion.py hub_geometry checks them (16 px and 18 px, less float noise). */
export const HUB_BARS = { badgeClear: 15.99, beside: 17.99 } as const;

// Design's measures (motion.py hub_geometry, glance.test.mjs D81) on straight segments.
type Seg = readonly [HubPoint, HubPoint];
const segs = (pts: HubPoint[]): Seg[] => pts.slice(1).map((q, i) => [pts[i], q] as const);
/** A segment's gap to a box (0 when it touches or enters it). */
const gapTo = ([p, q]: Seg, b: HubBox) =>
  Math.hypot(
    Math.max(b.x - Math.max(p.x, q.x), Math.min(p.x, q.x) - (b.x + b.w), 0),
    Math.max(b.y - Math.max(p.y, q.y), Math.min(p.y, q.y) - (b.y + b.h), 0),
  );
const vert = ([p, q]: Seg) => Math.abs(p.x - q.x) < 0.01;
const span = ([p, q]: Seg, k: 'x' | 'y') => [Math.min(p[k], q[k]), Math.max(p[k], q[k])];
/** Two parallel segments that overlap by more than 10 px: how far apart, and how long they run together. */
const sideBySide = (s: Seg, t: Seg): { gap: number; run: number } | null => {
  if (vert(s) !== vert(t)) return null;
  const [k, o] = vert(s) ? (['y', 'x'] as const) : (['x', 'y'] as const);
  const [a0, a1] = span(s, k);
  const [b0, b1] = span(t, k);
  const run = Math.min(a1, b1) - Math.max(a0, b0);
  return run > 10 ? { gap: Math.abs(s[0][o] - t[0][o]), run } : null;
};
/** A strict crossing, 1 px in from both ends of both segments. */
const crosses = (s: Seg, t: Seg): boolean => {
  if (vert(s) === vert(t)) return false;
  if (!vert(s)) return crosses(t, s);
  return (
    Math.min(t[0].x, t[1].x) + 1 < s[0].x &&
    s[0].x < Math.max(t[0].x, t[1].x) - 1 &&
    Math.min(s[0].y, s[1].y) + 1 < t[0].y &&
    t[0].y < Math.max(s[0].y, s[1].y) - 1
  );
};

/**
 * One way a hub line misses D81's bars, with its numbers (px, to 0.1): too
 * close to a count; a run beside a drawn line ("builder|lead") or the batch's
 * earlier hub line ("hub>checker"), how far apart and how long; crossings
 * left without a hop.
 */
export type HubGap =
  | { to: string; kind: 'count'; clear: number }
  | { to: string; kind: 'beside'; line: string; gap: number; run: number }
  | { to: string; kind: 'unhopped'; crossings: number; hops: number; unhopped: number };

const tenth = (v: number) => Math.round(v * 10) / 10;

/** A drawn line's name, by the cards its two ends sit on ("builder|lead"). */
function drawnName(pts: HubPoint[], rects: Record<string, HubBox>): string {
  const on = (p: HubPoint) =>
    Object.entries(rects).find(([, r]) => p.x >= r.x - 0.6 && p.x <= r.x + r.w + 0.6 && p.y >= r.y - 0.6 && p.y <= r.y + r.h + 0.6)?.[0] ?? '?';
  return [on(pts[0]), on(pts[pts.length - 1])].sort().join('|');
}

/**
 * Every way a batch's hub lines miss D81's bars, in routing order, each
 * against the drawn lines and the batch's earlier hub lines (Design's
 * motion.py hub_geometry, glance.test.mjs D81): none is the bar.
 */
export function hubGaps(report: HubReport): HubGap[] {
  const placed = report.lines.map((pts) => ({ name: drawnName(pts, report.rects), pts }));
  const out: HubGap[] = [];
  for (const r of report.routes) {
    const own = segs(r.base);
    const clear = Math.min(Infinity, ...own.flatMap((s) => report.badges.map((b) => gapTo(s, b))));
    if (clear < HUB_BARS.badgeClear) out.push({ to: r.to, kind: 'count', clear: tenth(clear) });
    for (const other of placed) {
      for (const s of own) {
        for (const t of segs(other.pts)) {
          const side = sideBySide(s, t);
          if (side && side.gap < HUB_BARS.beside) out.push({ to: r.to, kind: 'beside', line: other.name, gap: tenth(side.gap), run: tenth(side.run) });
        }
      }
    }
    const crossings = own.reduce((n, s) => n + placed.flatMap((o) => segs(o.pts)).filter((t) => crosses(s, t)).length, 0);
    if (r.unhopped > 0 || r.hops < crossings) out.push({ to: r.to, kind: 'unhopped', crossings, hops: r.hops, unhopped: r.unhopped });
    placed.push({ name: `hub>${r.to}`, pts: r.base });
  }
  return out;
}

export const describeGap = (g: HubGap): string =>
  g.kind === 'count'
    ? `${g.to}: ${g.clear} px from a count`
    : g.kind === 'beside'
      ? `${g.to}: runs ${g.run} px beside ${g.line}, ${g.gap} px apart`
      : `${g.to}: ${g.crossings} crossings, ${g.hops} hops, ${g.unhopped} unhopped`;

/**
 * The same router as the page (hubPaths), run here on the page's own measured
 * input (what a flown batch reported): the hub lines `to` would get, in that
 * order. The D81 test checks it draws the flown batch exactly as the page did.
 */
export function routeHubGroup(input: Omit<HubReport, 'routes'>, to: string[]): HubReport {
  const { rects, hub, lines, badges, width, height } = input;
  const got = hubPaths(to, { rects: new Map(Object.entries(rects)), hub, lines, badges, width, height });
  return {
    rects,
    hub,
    lines,
    badges,
    width,
    height,
    routes: [...got].map(([name, r]) => ({ to: name, try: r.try, hops: r.hops, unhopped: r.unhopped, base: r.base, pts: r.pts })),
  };
}
