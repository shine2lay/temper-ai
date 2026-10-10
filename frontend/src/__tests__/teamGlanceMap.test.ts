/**
 * The glance map's line contract (Design home decision A, 2026-10-09; D42-D58):
 * which pairs get a line, the router (a port of Design's glance.mjs), the
 * count's spot, the hop, the hub's port, and the dots that may run.
 */
import { describe, expect, it } from 'vitest';
import {
  BADGE_H,
  BADGE_TIERS,
  LINE,
  badgeWidth,
  HUB_BADGE_CLEAR,
  bridgeLine,
  hubPaths,
  mapGeometry,
  placeBadges,
  routeLines,
  segRect,
  segRectDistance,
  type Point,
  type Rect,
} from '@/lib/teamGlanceRoute';
import {
  DOT_STAGGER_MS,
  MAX_LINES,
  RECENT_LINE_MS,
  dotPlan,
  drawnLines,
  extraWords,
  hourRows,
  lineGreen,
  mapSlots,
  pairKey,
  type GlanceMember,
  type GlanceMessageEvent,
  type MapLine,
} from '@/lib/teamGlance';

const AS_OF = Date.parse('2026-10-09T10:00:00.000Z');
const ago = (min: number, sec = 0) => new Date(AS_OF - min * 60_000 - sec * 1000).toISOString();
const L = (a: string, b: string, count: number, lastAt: string | null): MapLine => ({ a, b, count, lastAt });
const names = (lines: MapLine[]) => lines.map((l) => `${l.a}-${l.b}`);

/** Every set of `k` pairs, deterministic, then every `step`-th of them (glance.test.mjs's sampling). */
function pairSets(cards: string[], k = MAX_LINES): Array<Array<{ a: string; b: string }>> {
  const pairs: Array<{ a: string; b: string }> = [];
  for (let i = 0; i < cards.length; i++) for (let j = i + 1; j < cards.length; j++) pairs.push({ a: cards[i], b: cards[j] });
  const sets: Array<Array<{ a: string; b: string }>> = [];
  const pick = (from: number, acc: Array<{ a: string; b: string }>) => {
    if (acc.length === Math.min(k, pairs.length)) {
      sets.push(acc);
      return;
    }
    for (let i = from; i < pairs.length; i++) pick(i + 1, [...acc, pairs[i]]);
  };
  pick(0, []);
  const step = pairs.length <= 6 ? 1 : pairs.length <= 10 ? 7 : 21;
  return sets.filter((_, i) => i % step === 0);
}

const segsOf = (pts: Point[]) => pts.slice(1).map((q, i) => [pts[i], q] as const);
const grow = (r: Rect, d: number): Rect => ({ x: r.x - d, y: r.y - d, w: r.w + 2 * d, h: r.h + 2 * d });

/** Design's reference grid (glance.mjs layoutSlots), for the reference's own router test. */
function referenceSlots(n: number): Array<{ col: number; row: number }> {
  if (n === 1) return [{ col: 1, row: 0 }];
  if (n === 2) return [{ col: 0, row: 0 }, { col: 2, row: 0 }];
  const others = n - 1;
  const left = Math.ceil(others / 2);
  const right = others - left;
  const rows = Math.max(left, right);
  const slots = [{ col: 1, row: (rows - 1) / 2 }];
  for (let i = 0; i < others; i++) {
    const side = i % 2 === 0 ? 0 : 2;
    const count = side === 0 ? left : right;
    slots.push({ col: side, row: Math.floor(i / 2) + (rows - count) / 2 });
  }
  return slots;
}

/**
 * The app's map as the page lays it out (glance.css): three columns, 36 px
 * sides, 64 px gutters and top, 72 px between rows; cards at most 284 px
 * wide, centred in their column; the leader in the middle column, centred on
 * the rows (mapSlots).
 */
function appLayout(n: number, width: number, cardH = 150): { rects: Map<string, Rect>; box: { w: number; h: number } } {
  const member = (name: string, leader: boolean) => ({ name, leader }) as GlanceMember;
  const team = Array.from({ length: n }, (_, i) => member(i === 0 ? 'lead' : `m${i}`, i === 0));
  const { slots, rows } = mapSlots(team);
  const px = 36;
  const py = 64;
  const gx = 64;
  const gy = 72;
  const colW = (width - 2 * px - 2 * gx) / 3;
  const cardW = Math.min(colW, 284);
  const gridH = rows * cardH + (rows - 1) * gy;
  const rects = new Map<string, Rect>();
  for (const s of slots) {
    const x = px + (s.col - 1) * (colW + gx) + (colW - cardW) / 2;
    const y = s.col === 2 ? py + (gridH - cardH) / 2 : py + (s.row - 1) * (cardH + gy);
    rects.set(s.name, { x, y, w: cardW, h: cardH });
  }
  return { rects, box: { w: width, h: py * 2 + gridH } };
}

describe("the map's lines: which pairs (D42, D44)", () => {
  it('only pairs within 10 min of as_of, at most 4, newest first, ties by count then names', () => {
    expect(RECENT_LINE_MS).toBe(600_000);
    expect(MAX_LINES).toBe(4);
    const all = [
      L('A', 'B', 1, ago(1)),
      L('C', 'D', 9, ago(10)),
      L('E', 'F', 2, ago(10, 1)),
      L('A', 'C', 3, ago(2)),
      L('B', 'D', 5, ago(2)),
      L('B', 'C', 5, ago(2)),
      L('D', 'E', 7, ago(40)),
    ];
    // 10:00 old exactly is in, 10:01 is out. A-B is newest; then three in one second: B-C and B-D (5) before A-C (3).
    expect(names(drawnLines(all, AS_OF))).toEqual(['A-B', 'B-C', 'B-D', 'A-C']);
    expect(names(drawnLines(all.slice(1, 3), AS_OF))).toEqual(['C-D']);
    // No reply time: nothing is drawn, never by the device's clock.
    expect(drawnLines(all, null)).toEqual([]);
    // The same links read an hour later, by that reply's as_of: nothing is recent.
    expect(drawnLines(all, AS_OF + 3_600_000)).toEqual([]);
    // A pair with no time is never drawn.
    expect(drawnLines([L('A', 'B', 4, null)], AS_OF)).toEqual([]);
  });

  it('the hour list: every pair, newest first in the map order, with the count on its line and its age by as_of', () => {
    const lines = [L('A', 'B', 2, ago(30)), L('C', 'D', 1, ago(3)), L('B', 'C', 4, ago(3)), L('D', 'E', 1, null)];
    const rows = hourRows(lines, AS_OF);
    expect(rows.map((r) => r.key)).toEqual(['B|C', 'C|D', 'A|B', 'D|E']);
    expect(rows.map((r) => r.pair)).toEqual([
      'B and C: 4\u00a0messages',
      'C and D: 1\u00a0message',
      'A and B: 2\u00a0messages',
      'D and E: 1\u00a0message',
    ]);
    expect(rows.map((r) => r.time)).toEqual(['last 3 min ago', 'last 3 min ago', 'last 30 min ago', 'time not supplied']);
    // The list's top rows are the drawn lines, with the same counts.
    const drawn = drawnLines(lines, AS_OF);
    expect(rows.slice(0, drawn.length).map((r) => r.key)).toEqual(drawn.map((l) => pairKey(l.a, l.b)));
  });

  it('a drawn line is green for a minute after its last message, by as_of', () => {
    expect(lineGreen({ lastAt: ago(1) }, AS_OF)).toBe(true);
    expect(lineGreen({ lastAt: ago(1, 1) }, AS_OF)).toBe(false);
    expect(lineGreen({ lastAt: ago(0, 5) }, null)).toBe(false);
  });
});

describe('dots only on drawn lines (D43)', () => {
  const msg = (seq: number, from: string, to: string, at: string, fromKind: GlanceMessageEvent['fromKind'] = 'member'): GlanceMessageEvent => ({
    kind: 'message',
    seq,
    at,
    member: fromKind === 'member' ? from : null,
    from,
    fromKind,
    to,
    messageKind: 'work_request',
    text: `message ${seq}`,
    messageId: `m${seq}`,
  }) as GlanceMessageEvent;
  const team = new Set(['A', 'B', 'C', 'D']);

  it("a message on a pair that isn't drawn gets no dot and joins +N more sent; You and Temper are unaffected", () => {
    const at = ago(0, 1);
    const plan = dotPlan([msg(1, 'A', 'B', at), msg(2, 'C', 'D', at), msg(3, 'You', 'A', at, 'owner')], new Set(['A|B']), team);
    expect(plan.dots.map((d) => `${d.event.from}>${d.event.to}@${d.delay}`)).toEqual(['A>B@0', 'You>A@120']);
    expect(plan.extra).toBe(1);
  });

  it('a start fan-out to 5 members with 4 lines drawn: 4 dots 120 ms apart and "+1 more sent"', () => {
    const at = '2026-10-09T09:59:58.000Z';
    const to = ['B', 'C', 'D', 'E', 'F'];
    const fan = to.map((t, i) => msg(i + 1, 'A', t, at));
    const links = to.map((t) => L('A', t, 1, at));
    const drawn = drawnLines(links, AS_OF);
    expect(drawn).toHaveLength(4);
    const plan = dotPlan(fan, new Set(drawn.map((l) => pairKey(l.a, l.b))), new Set(['A', ...to]));
    expect(plan.dots.map((d) => d.delay)).toEqual([0, 1, 2, 3].map((i) => i * DOT_STAGGER_MS));
    expect(plan.dots.every((d) => drawn.some((l) => pairKey(l.a, l.b) === pairKey(d.event.from, d.event.to)))).toBe(true);
    expect(plan.extra).toBe(1);
    expect(extraWords(plan.extra)).toBe('+1 more sent');
  });
});

describe("the router (Design's glance.mjs, D52 and D58)", () => {
  it("keeps Design's constants and cost order", () => {
    expect(LINE).toEqual({
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
    });
    expect(BADGE_TIERS).toEqual([
      [1, 28, 40],
      [2, 16, 24],
      [3, 16, 0],
      [4, 8, 0],
    ]);
    expect([badgeWidth(4), badgeWidth(12), badgeWidth(123), BADGE_H]).toEqual([28, 34, 43, 20]);
  });

  it('a straight line keeps 28 px from a card it passes, when its facing sides allow it (D58)', () => {
    // The 4-member map at 1024: builder and checker side by side, the taller lead card in the middle
    // starting 88 px below them. The middle of their facing sides would pass lead 12 px off.
    const rects = new Map<string, Rect>([
      ['builder', { x: 40, y: 0, w: 178, h: 152 }],
      ['lead', { x: 282, y: 88, w: 178, h: 212 }],
      ['checker', { x: 524, y: 0, w: 178, h: 152 }],
    ]);
    const out = routeLines([{ a: 'builder', b: 'checker' }], rects, { width: 742, height: 360 });
    const pts = out.lines.get('builder\u0000checker')!.pts;
    expect(pts).toHaveLength(2);
    expect(pts[0].y).toBe(pts[1].y);
    expect(segRectDistance(pts[0], pts[1], rects.get('lead')!)).toBeGreaterThanOrEqual(LINE.hug);
    // Still a port: 28 px or more from the corners.
    expect(pts[0].y).toBeGreaterThanOrEqual(LINE.corner);
  });

  it('perpendicular crossings get a visible hop on the same painted dot path', () => {
    const source = [
      { x: 0, y: 50 },
      { x: 100, y: 50 },
    ];
    const paint = bridgeLine(source, [
      [
        { x: 50, y: 0 },
        { x: 50, y: 100 },
      ],
    ]);
    expect(paint.bridges).toHaveLength(1);
    expect(paint.skipped).toHaveLength(0);
    expect(paint.pts.some((p) => p.y !== 50)).toBe(true);
    expect(paint.path).toMatch(/Q/);
    expect(source).toEqual([
      { x: 0, y: 50 },
      { x: 100, y: 50 },
    ]);
  });

  it('a hop takes the side clear of a count, and is never forced through a card or a count', () => {
    const source = [
      { x: 0, y: 50 },
      { x: 100, y: 50 },
    ];
    const previous = [
      [
        { x: 50, y: 0 },
        { x: 50, y: 100 },
      ],
    ];
    const below = bridgeLine(source, previous, [{ x: 40, y: 25, w: 20, h: 20 }]);
    expect(below.bridges).toHaveLength(1);
    expect(below.pts.some((p) => p.y > 50)).toBe(true);
    const blocked = bridgeLine(source, previous, [{ x: 40, y: 25, w: 20, h: 50 }]);
    expect(blocked.bridges).toHaveLength(0);
    expect(blocked.skipped).toHaveLength(1);
    expect(blocked.pts).toEqual(source);
  });

  it(
    "Design's layouts: every 4-pair set (sampled for 5-6 members) routes, shares nothing and crosses no card, 3 and 2 columns",
    () => {
      for (const cols of [3, 2]) {
        for (let n = 1; n <= 6; n++) {
          // glance.test.mjs's synthetic grid: cards 270 x 150.
          const W = cols === 3 ? 1060 : 740;
          const cw = 270;
          const ch = 150;
          const gx = cols === 3 ? 64 : 96;
          const gy = 72;
          const px = 36;
          const py = 44;
          const colW = (W - 2 * px - (cols - 1) * gx) / cols;
          const rects = new Map<string, Rect>();
          const cards = Array.from({ length: n }, (_, i) => `M${i}`);
          if (cols === 3) {
            referenceSlots(n).forEach((s, i) =>
              rects.set(cards[i], { x: px + s.col * (colW + gx) + (colW - cw) / 2, y: py + s.row * (ch + gy), w: cw, h: ch }),
            );
          } else {
            rects.set(cards[0], { x: (W - cw) / 2, y: py, w: cw, h: ch });
            for (let i = 1; i < n; i++) {
              const r = Math.floor((i - 1) / 2);
              const c = (i - 1) % 2;
              const last = i === n - 1 && (n - 1) % 2 === 1;
              rects.set(cards[i], {
                x: last ? (W - cw) / 2 : px + c * (colW + gx) + (colW - cw) / 2,
                y: py + (r + 1) * (ch + gy),
                w: cw,
                h: ch,
              });
            }
          }
          const H = Math.max(...[...rects.values()].map((r) => r.y + r.h)) + py;
          for (const set of pairSets(cards)) {
            const label = `${cols} cols, ${n} members, ${set.map((p) => `${p.a}-${p.b}`).join(' ')}`;
            const out = routeLines(set, rects, { width: W, height: H });
            expect(out.failed, `${label}: every pair routed`).toEqual([]);
            expect(out.shared, `${label}: no shared stretch`).toEqual([]);
            for (const line of out.lines.values()) {
              for (const [name, r] of rects) {
                if (name === line.a || name === line.b) continue;
                for (const [p, q] of segsOf(line.pts)) expect(segRect(p, q, grow(r, 2)), `${label}: ${line.a}-${line.b} crosses ${name}`).toBe(false);
              }
            }
          }
        }
      }
    },
    600_000,
  );

  it(
    "the app's own layout at the 1024 and 1440 map widths: every bar on every 4-pair set (sampled for 5-6 members)",
    () => {
      // Sets where one count has no allowed spot. Design's glance.mjs routes these sets the same way (the
      // count's only straight run is crossed by another line), so the page leaves that count off the map;
      // the hour list below still has it. Pinned so a router change shows here.
      const noSpot: Record<number, Record<number, number>> = { 742: { 5: 9, 6: 6 }, 1110: { 5: 8, 6: 7 } };
      // The map box at 1024 x 768 and 1440 x 900 (measured in the browser: the page's column beside the sidebar).
      for (const width of [742, 1110]) {
        for (let n = 2; n <= 6; n++) {
          const { rects, box } = appLayout(n, width);
          let forcedSets = 0;
          for (const set of pairSets([...rects.keys()])) {
            const label = `${width} px, ${n} members, ${set.map((p) => `${p.a}-${p.b}`).join(' ')}`;
            const geometry = mapGeometry(
              set.map((p) => ({ key: pairKey(p.a, p.b), a: p.a, b: p.b, count: 12 })),
              rects,
              [],
              box,
            );
            expect(geometry.failed, `${label}: routed`).toEqual([]);
            expect(geometry.shared, `${label}: no shared stretch`).toEqual([]);
            expect(geometry.unhopped, `${label}: every crossing hopped`).toBe(0);
            for (const line of geometry.lines) {
              // Never across a card it doesn't join; ports 28 px from a corner.
              for (const [name, r] of rects) {
                if (name === line.a || name === line.b) continue;
                for (const [p, q] of segsOf(line.pts)) expect(segRectDistance(p, q, r), `${label}: ${line.key} at ${name}`).toBeGreaterThan(0);
              }
              for (const [end, name] of [
                [line.route[0], line.a],
                [line.route[line.route.length - 1], line.b],
              ] as const) {
                const r = rects.get(name)!;
                const along = end.y === r.y || end.y === r.y + r.h ? end.x - r.x : end.y - r.y;
                const side = end.y === r.y || end.y === r.y + r.h ? r.w : r.h;
                expect(Math.min(along, side - along), `${label}: ${line.key} port at ${name}`).toBeGreaterThanOrEqual(LINE.corner - 0.5);
              }
            }
            // Ports on one side keep 30 px apart.
            const ends = geometry.lines.flatMap((l) => [l.route[0], l.route[l.route.length - 1]]);
            for (let i = 0; i < ends.length; i++) {
              for (let j = i + 1; j < ends.length; j++) {
                const d = Math.hypot(ends[i].x - ends[j].x, ends[i].y - ends[j].y);
                expect(d, `${label}: ports ${d.toFixed(1)} px apart`).toBeGreaterThanOrEqual(LINE.port - 0.5);
              }
            }
            // A drawn count sits in an allowed spot (tiers 1-4) on its own line; one with no spot is not drawn.
            geometry.badges.forEach((badge, i) => {
              if (badge.forced) return;
              expect(badge.tier, `${label}: ${badge.key} spot`).toBeLessThanOrEqual(4);
              const own = segsOf(geometry.lines[i].route).some(([p, q]) => {
                const onX = Math.abs(p.x - q.x) < 0.5 && Math.abs(badge.at.x - p.x) < 0.5;
                const onY = Math.abs(p.y - q.y) < 0.5 && Math.abs(badge.at.y - p.y) < 0.5;
                const within = (v: number, a: number, b: number) => v >= Math.min(a, b) - 0.5 && v <= Math.max(a, b) + 0.5;
                return (onX && within(badge.at.y, p.y, q.y)) || (onY && within(badge.at.x, p.x, q.x));
              });
              expect(own, `${label}: ${badge.key} count on its own run`).toBe(true);
            });
            if (geometry.badges.some((b) => b.forced)) forcedSets += 1;
          }
          expect(forcedSets, `${width} px, ${n} members: sets with a count left off`).toBe(noSpot[width][n] ?? 0);
        }
      }
    },
    600_000,
  );
});

describe('counts on their own straight run (D43, D57, D58)', () => {
  const cards = new Map<string, Rect>([
    ['a', { x: 0, y: 100, w: 200, h: 150 }],
    ['b', { x: 600, y: 100, w: 200, h: 150 }],
  ]);
  const straight = { key: 'a|b', a: 'a', b: 'b', pts: [{ x: 200, y: 175 }, { x: 600, y: 175 }], w: 28, h: BADGE_H };

  it('a free line puts its count in the middle of its run, the first spot (28 px from lines, 40 from other cards)', () => {
    const [badge] = placeBadges([straight], cards);
    expect(badge).toMatchObject({ key: 'a|b', tier: 1, forced: false, at: { x: 400, y: 175 } });
  });

  it('a line or a card close by moves the count down the spot order; no spot at all is reported, never drawn on a line', () => {
    const line = (dy: number) => ({ key: 'c|d', a: 'c', b: 'd', pts: [{ x: 200, y: 175 + dy }, { x: 600, y: 175 + dy }], w: 28, h: BADGE_H });
    // The count's box is 20 px tall: a line 30 px below its middle is 20 px from it (the 16 px spot);
    // 20 px below, 10 px from it (the 8 px spot, a short gutter run).
    expect(placeBadges([straight, line(30)], cards)[0].tier).toBe(2);
    expect(placeBadges([straight, line(20)], cards)[0].tier).toBe(4);
    // A card the line doesn't join, 15 px under the whole run: the third spot (16 px from lines only).
    const beside = new Map([...cards, ['c', { x: 200, y: 200, w: 400, h: 50 }]]);
    expect(placeBadges([straight], beside)[0].tier).toBe(3);
    // 2 px from another line: no allowed spot. Reported, and the page doesn't draw it.
    expect(placeBadges([straight, line(12)], cards)[0]).toMatchObject({ tier: 5, forced: true });
  });
});

describe("the You and Temper hub's lines (D5, D81)", () => {
  // Design's measures (glance.test.mjs, D81): a segment's gap to a box; the distance between two parallel
  // segments that overlap by more than 10 px (else Infinity); a strict crossing, 1 px in from both ends.
  const gap = ([p, q]: readonly [Point, Point], b: Rect) =>
    Math.hypot(
      Math.max(b.x - Math.max(p.x, q.x), Math.min(p.x, q.x) - (b.x + b.w), 0),
      Math.max(b.y - Math.max(p.y, q.y), Math.min(p.y, q.y) - (b.y + b.h), 0),
    );
  const vert = ([p, q]: readonly [Point, Point]) => Math.abs(p.x - q.x) < 0.01;
  const span = ([p, q]: readonly [Point, Point], k: 'x' | 'y') => [Math.min(p[k], q[k]), Math.max(p[k], q[k])];
  const beside = (s: readonly [Point, Point], t: readonly [Point, Point]) => {
    if (vert(s) !== vert(t)) return Infinity;
    const [k, o] = vert(s) ? (['y', 'x'] as const) : (['x', 'y'] as const);
    const [a0, a1] = span(s, k);
    const [b0, b1] = span(t, k);
    return Math.min(a1, b1) - Math.max(a0, b0) > 10 ? Math.abs(s[0][o] - t[0][o]) : Infinity;
  };
  const crosses = (s: readonly [Point, Point], t: readonly [Point, Point]): boolean => {
    if (vert(s) === vert(t)) return false;
    if (!vert(s)) return crosses(t, s);
    return (
      Math.min(t[0].x, t[1].x) + 1 < s[0].x &&
      s[0].x < Math.max(t[0].x, t[1].x) - 1 &&
      Math.min(s[0].y, s[1].y) + 1 < t[0].y &&
      t[0].y < Math.max(s[0].y, s[1].y) - 1
    );
  };
  /** Every hub line of one step against the D81 bars, in order: what it fails, by receiver. */
  const hubFaults = (got: ReturnType<typeof hubPaths>, drawn: Point[][], badges: Rect[]) => {
    const earlier: Point[][] = [];
    const faults: string[] = [];
    for (const [to, r] of got) {
      const clear = Math.min(Infinity, ...segsOf(r.base).flatMap((s) => badges.map((b) => gap(s, b))));
      if (clear < HUB_BADGE_CLEAR - 1e-6) faults.push(`${to}: ${clear} px from a count`);
      const others = [...drawn, ...earlier].flatMap(segsOf);
      const near = Math.min(Infinity, ...segsOf(r.base).flatMap((s) => others.map((t) => beside(s, t))));
      if (near < LINE.track) faults.push(`${to}: ${near} px beside a line`);
      const n = segsOf(r.base).reduce((k, s) => k + others.filter((t) => crosses(s, t)).length, 0);
      if (r.unhopped > 0 || r.hops < n) faults.push(`${to}: ${n} crossings, ${r.hops} hops, ${r.unhopped} unhopped`);
      earlier.push(r.base);
    }
    return faults;
  };

  it('D81: hub lines keep 16 px clear of count badges, never run beside a line, and hop what they cross', () => {
    // checkin-asked at 1024 (Design's numbers): five cards, the Backend-QA line and its count badge. Before D81,
    // You -> Design was routed alone and ran down x=375 through the badge and across the line without a hop.
    const rects = new Map<string, Rect>([
      ['Product', { x: 215, y: 64, w: 284, h: 169 }],
      ['Frontend', { x: 60, y: 305, w: 249, h: 169 }],
      ['Backend', { x: 405, y: 305, w: 249, h: 169 }],
      ['QA', { x: 60, y: 546, w: 249, h: 169 }],
      ['Design', { x: 405, y: 546, w: 249, h: 169 }],
    ]);
    const hub: Rect = { x: 10, y: 8, w: 256, h: 24.3 };
    const drawn: Point[][] = [[{ x: 405, y: 446 }, { x: 357, y: 446 }, { x: 357, y: 574 }, { x: 309, y: 574 }]];
    const badges: Rect[] = [{ x: 367, y: 435, w: 28, h: 22 }];
    const size = { width: 714, height: 779 };
    const before = routeLines([{ a: '@hub', b: 'Design' }], new Map([['@hub', hub], ...rects]), size).lines.get('@hub\u0000Design')!.pts;
    expect(Math.min(...segsOf(before).map((s) => gap(s, badges[0]))), 'the old route runs through the badge (the test sees the fault)').toBe(0);

    const got = hubPaths(['Design', 'QA', 'Product'], { rects, hub, lines: drawn, badges, ...size });
    expect([...got.keys()]).toEqual(['Design', 'QA', 'Product']);
    for (const [to, r] of got) expect(r.try, `${to}: strict try`).toBe(1);
    expect(hubFaults(got, drawn, badges)).toEqual([]);
    // The same routes as Design's reference router (glance.mjs hubPaths, pinned 724a6254): Design's to the map's
    // right edge and down, as the gutters are taken; QA's down the left of the line; Product's short jog.
    const rounded = (pts: Point[]) => pts.map((p) => [Math.round(p.x * 1000) / 1000, Math.round(p.y * 1000) / 1000]);
    expect(rounded(got.get('Design')!.base)).toEqual([[266, 20.15], [684, 20.15], [684, 510], [433, 510], [433, 546]]);
    expect(rounded(got.get('QA')!.base)).toEqual([[184.5, 32.3], [184.5, 269], [339, 269], [339, 492], [281, 492], [281, 546]]);
    expect(rounded(got.get('Product')!.base)).toEqual([[238, 32.3], [238, 48.25], [243, 48.25], [243, 64]]);
    // The dot follows the painted route: no crossing here, so it is the route itself.
    for (const [to, r] of got) expect(r.pts, to).toEqual(r.base);

    // The map's own lines are routed exactly as before: D81's options are empty there.
    const map = routeLines([{ a: 'QA', b: 'Backend' }], rects, size);
    const same = routeLines([{ a: 'QA', b: 'Backend' }], rects, { ...size, placed: [], avoid: [], cost: {} });
    expect(same.lines.get('QA\u0000Backend')!.pts).toEqual(map.lines.get('QA\u0000Backend')!.pts);
  });

  // The page's You/Temper corner, as measured at 1024 and 1440.
  const pageHub: Rect = { x: 10, y: 8, w: 256, h: 24 };
  /** Every receiver alone, then every two at once in either order: the batches D81's bars must hold for on any map. */
  const alonesAndPairs = (names: string[]) => [
    ...names.map((a) => [a]),
    ...names.flatMap((a) => names.filter((b) => b !== a).map((b) => [a, b])),
  ];

  it("a hub line starts on the hub's edge: a short end's middle (D5) or a port 28 px from the corners, and never crosses a card", () => {
    const hub = pageHub;
    const { rects, box } = appLayout(5, 1110);
    for (const to of rects.keys()) {
      const r = hubPaths([to], { rects, hub, width: box.w, height: box.h }).get(to)!;
      expect(r.try, `${to}: strict try`).toBe(1);
      const start = r.base[0];
      const bottom = start.y === hub.y + hub.h && start.x >= hub.x + LINE.corner && start.x <= hub.x + hub.w - LINE.corner;
      const end = (start.x === hub.x || start.x === hub.x + hub.w) && start.y === hub.y + hub.h / 2;
      expect(bottom || end, `${to}: starts at ${start.x},${start.y}`).toBe(true);
      for (const [name, c] of rects) {
        if (name === to) continue;
        for (const [p, q] of segsOf(r.pts)) expect(segRect(p, q, c), `${to} crosses ${name}`).toBe(false);
      }
      const last = r.base[r.base.length - 1];
      const card = rects.get(to)!;
      expect(last.x >= card.x && last.x <= card.x + card.w && last.y >= card.y && last.y <= card.y + card.h, `${to} ends on its card`).toBe(true);
    }
    // An earlier hub line is a placed line too: two at once never share a port or run beside each other.
    for (const pair of alonesAndPairs([...rects.keys()]).filter((g) => g.length === 2)) {
      const got = hubPaths(pair, { rects, hub, width: box.w, height: box.h });
      expect([...got.keys()], `${pair}`).toEqual(pair);
      const [a, b] = [...got.values()].map((r) => r.base[0]);
      expect(a.x === b.x && a.y === b.y, `${pair}: one port each`).toBe(false);
      expect(hubFaults(got, [], []), `${pair}`).toEqual([]);
    }
  });

  // Three or more at once can miss the bars on a crowded map: a known D81 gap Design was asked about, pinned
  // with its numbers in the browser test (e2e/team-glance-hub-groups.ts).
  it('the app map with its drawn lines and counts: each member alone, and any two at once, keep the D81 bars', () => {
    const hub = pageHub;
    for (const width of [1024, 1440]) {
      const { rects, box } = appLayout(5, width);
      const pairs = [
        { a: 'lead', b: 'm1' },
        { a: 'lead', b: 'm2' },
        { a: 'm1', b: 'm3' },
        { a: 'm2', b: 'm4' },
      ];
      const g = mapGeometry(pairs.map((p) => ({ ...p, key: pairKey(p.a, p.b), count: 12 })), rects, [hub], box);
      const drawn = g.lines.map((l) => l.route);
      const badges = g.badges.filter((b) => !b.forced).map((b) => b.box);
      expect(drawn.length, `${width}: four drawn lines`).toBe(4);
      expect(badges.length, `${width}: counts drawn`).toBeGreaterThan(0);
      for (const group of alonesAndPairs([...rects.keys()])) {
        const got = hubPaths(group, { rects, hub, lines: drawn, badges, width: box.w, height: box.h });
        expect([...got.keys()], `${width} ${group}: every receiver routed, in order`).toEqual(group);
        expect(hubFaults(got, drawn, badges), `${width} ${group}`).toEqual([]);
      }
    }
  });
});
