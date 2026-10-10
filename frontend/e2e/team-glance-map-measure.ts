/**
 * The glance map as the browser drew it, measured in rendered pixels, for
 * Design's map-line bars (D52, D57, D58): for each drawn line, its hops, its
 * sockets, how close it comes to a card or the You/Temper corner it doesn't
 * join, whether it runs along another line, and where its count sits.
 * team-glance-map.spec.ts holds the map to the bars with it.
 */
import { expect, type Page } from '@playwright/test';

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
