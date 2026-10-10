/**
 * The map routes again only when what it draws can change: a count reaches the
 * router only as its badge's width (badgeWidth), so a count that keeps its
 * badge's width (12 to 13, 3 to 4) routes nothing and only the number in its
 * badge changes, while a count that crosses a width (9 to 10) routes again.
 * Routing a members-6 map took 0.5-3 s on the main thread, and the counts
 * change on every read of a live run.
 *
 * Where the browser has workers, the map is routed in one: the page posts each
 * ask, draws only the latest one's answer, keeps the lines it drew while it
 * waits, and routes in the page only if the worker fails. jsdom has no
 * workers: the tests that don't stub one route in render, as before.
 */
import { act, cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { TeamMap } from '@/components/team/glance/TeamMap';
import type { GlanceFeed } from '@/hooks/useTeamGlanceEvents';
import { msOf, pairKey, type GlanceRun } from '@/lib/teamGlance';
import { toGlanceRun } from '@/lib/teamGlanceAdapter';
import { badgeCount, badgeWidth, mapGeometry } from '@/lib/teamGlanceRoute';
import { answerAsk, type GeometryAnswer, type GeometryAsk } from '@/lib/teamGlanceRoute.worker';

import working from '../../e2e/fixtures/team/flow/real/working.json';

vi.mock('@/lib/teamGlanceRoute', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/teamGlanceRoute')>();
  return { ...actual, mapGeometry: vi.fn(actual.mapGeometry) };
});

const routed = vi.mocked(mapGeometry);

/** Temper's real working reply: lead, builder and checker, both lines drawn (sent at as_of). */
const BASE = toGlanceRun(working);
const AT = BASE.links[0].lastAt;

function run(builder: number, checker: number): GlanceRun {
  return {
    ...BASE,
    links: [
      { from: 'lead', to: 'builder', count: builder, lastAt: AT },
      { from: 'lead', to: 'checker', count: checker, lastAt: AT },
    ],
  };
}

const FEED: GlanceFeed = { events: [], fresh: [], freshKey: 0, ready: true, failed: false, asOf: BASE.asOf };

function ui(r: GlanceRun) {
  return (
    <TeamMap run={r} feed={FEED} now={msOf(r.asOf)} animate={false} onAnimateChange={() => undefined} reducedMotion />
  );
}

/** The number drawn in a pair's badge. */
function badgeNumber(a: string, b: string): string | null {
  const g = screen.getByTestId('glance-counts').querySelector(`[data-count="${CSS.escape(pairKey(a, b))}"]`);
  return g?.textContent ?? null;
}

// jsdom lays nothing out: the map box and every card get a fixed box, so the map is measured and routed.
beforeEach(() => {
  const boxes = new Map<Element, DOMRect>();
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    if (this.dataset.testid === 'glance-map') return new DOMRect(0, 0, 1024, 560);
    let r = boxes.get(this);
    if (!r) {
      const i = boxes.size;
      r = new DOMRect(24 + (i % 3) * 340, 40 + Math.floor(i / 3) * 280, 240, 120);
      boxes.set(this, r);
    }
    return r;
  });
  routed.mockClear();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

/** A worker as the page sees one: it keeps what was posted (as cloned) and answers when the test says. */
class FakeWorker {
  static made: FakeWorker[] = [];
  url: string;
  options: unknown;
  posted: GeometryAsk[] = [];
  answered = 0;
  terminated = false;
  onmessage: ((e: MessageEvent<GeometryAnswer>) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  onmessageerror: ((e: Event) => void) | null = null;

  constructor(url: URL | string, options?: unknown) {
    this.url = String(url);
    this.options = options;
    FakeWorker.made.push(this);
  }

  postMessage(ask: GeometryAsk) {
    this.posted.push(structuredClone(ask));
  }

  terminate() {
    this.terminated = true;
  }

  /** Route ask number `seq` as the worker does, and answer it. */
  answer(seq: number) {
    const ask = this.posted.find((a) => a.seq === seq);
    if (!ask) throw new Error(`no ask ${seq}`);
    const data = structuredClone(answerAsk(ask));
    this.answered += 1;
    act(() => this.onmessage?.({ data } as MessageEvent<GeometryAnswer>));
  }

  fail() {
    act(() => this.onerror?.(new Event('error')));
  }
}

describe('the map routes only when a badge changes width', () => {
  it('gives each width one count, so counts route alike exactly when their badges are as wide', () => {
    const counts = [...Array.from({ length: 12001 }, (_, i) => i), 99999, 100000, 123456, 999999, 1000000];
    for (const n of counts) expect(badgeWidth(badgeCount(n))).toBe(badgeWidth(n));
    for (const [m, n] of [
      [1, 9],
      [12, 13],
      [10, 99],
      [100, 999],
    ])
      expect(badgeCount(m)).toBe(badgeCount(n));
    for (const [m, n] of [
      [9, 10],
      [99, 100],
      [999, 1000],
    ]) {
      expect(badgeCount(m)).not.toBe(badgeCount(n));
      expect(badgeWidth(m)).not.toBe(badgeWidth(n));
    }
  });

  it('routes nothing when the counts change but keep their widths, and draws the new numbers', () => {
    const view = render(ui(run(12, 3)));
    const map = screen.getByTestId('glance-map');
    expect(map.dataset.linesDrawn).toBe('2');
    expect(badgeNumber('lead', 'builder')).toBe('12');
    expect(badgeNumber('lead', 'checker')).toBe('3');
    const calls = routed.mock.calls.length;
    expect(calls).toBeGreaterThan(0);
    const paths = within(map).getAllByTestId('glance-lines')[0].innerHTML;

    // The next read: both counts went up, each badge as wide as before.
    view.rerender(ui(run(13, 4)));
    expect(routed.mock.calls.length).toBe(calls);
    expect(badgeNumber('lead', 'builder')).toBe('13');
    expect(badgeNumber('lead', 'checker')).toBe('4');
    expect(within(map).getAllByTestId('glance-lines')[0].innerHTML).toBe(paths);
    // Routed with each width's count; the numbers drawn are the pairs' own.
    expect(routed.mock.calls[calls - 1][0].map((l) => l.count)).toEqual([10, 1]);
  });

  it('routes in a worker: draws the latest answer, keeps its lines while routing again and never routes in the page', () => {
    FakeWorker.made = [];
    vi.stubGlobal('Worker', FakeWorker);
    const view = render(ui(run(12, 9)));
    const map = screen.getByTestId('glance-map');
    const lines = () => within(map).getAllByTestId('glance-lines')[0].innerHTML;

    // Measured and asked; nothing is drawn until the answer.
    expect(FakeWorker.made).toHaveLength(1);
    const worker = FakeWorker.made[0];
    // Vite's worker transform may add its own query (?worker_file&type=module).
    expect(worker.url).toMatch(/teamGlanceRoute\.worker\.ts(\?|$)/);
    expect(worker.options).toEqual({ type: 'module' });
    expect(worker.posted.map((a) => a.seq)).toEqual([1]);
    expect(worker.posted[0].lines.map((l) => l.count)).toEqual([10, 1]);
    expect(worker.posted[0].cards).toBeInstanceOf(Map);
    expect(map.dataset.geometry).toBe('pending');
    expect(map.dataset.linesDrawn).toBe('0');

    worker.answer(1);
    expect(map.dataset.geometry).toBe('ready');
    expect(map.dataset.linesDrawn).toBe('2');
    expect(badgeNumber('lead', 'builder')).toBe('12');
    expect(badgeNumber('lead', 'checker')).toBe('9');
    const first = lines();

    // A count that keeps its badge's width asks nothing.
    view.rerender(ui(run(13, 9)));
    expect(worker.posted).toHaveLength(1);
    expect(map.dataset.geometry).toBe('ready');
    expect(badgeNumber('lead', 'builder')).toBe('13');
    expect(lines()).toBe(first);

    // 9 to 10 asks again; until the answer the lines stay, each with its pair's real number.
    view.rerender(ui(run(13, 10)));
    expect(worker.posted.map((a) => a.seq)).toEqual([1, 2]);
    expect(worker.posted[1].lines.map((l) => l.count)).toEqual([10, 10]);
    expect(map.dataset.geometry).toBe('pending');
    expect(map.dataset.linesDrawn).toBe('2');
    expect(lines()).toBe(first);
    expect(badgeNumber('lead', 'checker')).toBe('10');

    // 99 to 100 before that answer: the late answer to ask 2 is dropped, ask 3's is drawn.
    view.rerender(ui(run(13, 100)));
    expect(worker.posted.map((a) => a.seq)).toEqual([1, 2, 3]);
    worker.answer(2);
    expect(map.dataset.geometry).toBe('pending');
    expect(lines()).toBe(first);
    worker.answer(3);
    expect(map.dataset.geometry).toBe('ready');
    expect(map.dataset.linesDrawn).toBe('2');
    expect(badgeNumber('lead', 'checker')).toBe('100');

    // No line in the window: nothing drawn, and nothing kept to show while the next ask is routed.
    view.rerender(ui(run(0, 0)));
    expect(map.dataset.geometry).toBe('ready');
    expect(map.dataset.linesDrawn).toBe('0');
    view.rerender(ui(run(13, 9)));
    expect(worker.posted.map((a) => a.seq)).toEqual([1, 2, 3, 4]);
    expect(map.dataset.geometry).toBe('pending');
    expect(map.dataset.linesDrawn).toBe('0');
    worker.answer(4);
    expect(map.dataset.linesDrawn).toBe('2');
    expect(lines()).toBe(first);

    // Every routing was the worker's; leaving the page ends it.
    expect(routed.mock.calls.length).toBe(worker.answered);
    view.unmount();
    expect(worker.terminated).toBe(true);
  });

  it('routes in the page when the worker fails', () => {
    FakeWorker.made = [];
    vi.stubGlobal('Worker', FakeWorker);
    const view = render(ui(run(12, 9)));
    const map = screen.getByTestId('glance-map');
    const worker = FakeWorker.made[0];
    expect(map.dataset.geometry).toBe('pending');
    expect(routed.mock.calls.length).toBe(0);

    worker.fail();
    expect(worker.terminated).toBe(true);
    expect(map.dataset.geometry).toBe('ready');
    expect(map.dataset.linesDrawn).toBe('2');
    expect(routed.mock.calls.length).toBe(1);
    view.rerender(ui(run(13, 9)));
    expect(routed.mock.calls.length).toBe(1);
    expect(badgeNumber('lead', 'builder')).toBe('13');
    expect(FakeWorker.made).toHaveLength(1);
  });

  it('routes again when a count crosses a badge width (9 to 10)', () => {
    const view = render(ui(run(12, 9)));
    const calls = routed.mock.calls.length;
    expect(badgeNumber('lead', 'checker')).toBe('9');

    view.rerender(ui(run(12, 10)));
    expect(routed.mock.calls.length).toBe(calls + 1);
    const lines = routed.mock.calls[calls][0];
    expect(lines.find((l) => l.key === pairKey('checker', 'lead'))?.count).toBe(10);
    expect(badgeNumber('lead', 'checker')).toBe('10');
  });
});
