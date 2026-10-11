/**
 * The free-flowing Team page at a glance (Design's GLANCE.md), on Temper's
 * own serializer replies (e2e/fixtures/team/flow/real, FLOW #80) and the
 * states derived from them (flow/derived, scripts/make_flow_fixtures.mjs).
 * Every /api/team answer comes from them, so no Temper is needed and nothing
 * is written.
 *
 * One journey, as the owner's test rule asks (bp-be8d76b9): a Project from
 * its start (only the leader has the goal) through the leader's work
 * requests, the first shared version, the $100 check-in, a Guide answer,
 * then closing and done. At each step it checks the words on screen, axe,
 * 24 px targets, no sideways scroll and the count badges' drawn clearance,
 * in both themes at 390x844, 1024x768 and 1440x900, and at 320 px (reflow).
 * On the wide map it also holds the two flying dots under their counts and
 * checks, in pixels, that each count paints over its dot (Design D32).
 * Edge tests only for contract points: a burst past six dots on Temper's
 * clock (counts over dots, +N over both), reduced motion, dots stopping when
 * switched off or stale (no replay), usage limits that ask only when Temper
 * does, a check-in that asks only once Temper opens its wait, no release yet
 * and a receiver not on this team (D33), long and future times (D22, D28),
 * history read quietly in pages, and an old round run keeping its page.
 *
 * Temper's nine replies are nine separate runs. Start to resumed is one
 * story under one id (each step's feed carries on where the last one ended);
 * closing and done are opened fresh at their own ids, because their feeds
 * restart the story. The page's Date is pinned to each step's as_of.
 */
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { expect, test, type Locator, type Page } from '@playwright/test';
import {
  expectAxeClean,
  expectTargets,
  glanceFontsSettled,
  nothingSent,
  RUN_ID,
  runReads,
  serveActions,
  serveTeam,
  withBody,
  type Fixture,
} from './team-helpers';
import { expectDroppedCountsListed } from './team-glance-map-measure';

type Raw = Record<string, unknown>;
type Step =
  | 'start'
  | 'working'
  | 'share'
  | 'check_in'
  | 'resumed'
  | 'closing'
  | 'done'
  | 'burst'
  | 'starting'
  | 'check_in_running'
  | 'limit'
  | 'limit_asked'
  | 'limit_spent'
  | 'limit_unavailable';

const FLOW_DIR = path.join(process.cwd(), 'e2e/fixtures/team/flow');

/** A flow reply as Temper sent it (real) or as derived from one (derived). */
function flowRaw(name: Step, feed = false): Raw {
  for (const dir of ['real', 'derived']) {
    const file = path.join(FLOW_DIR, dir, `${name}${feed ? '-events' : ''}.json`);
    if (existsSync(file)) return JSON.parse(readFileSync(file, 'utf8')) as Raw;
  }
  throw new Error(`no flow fixture ${name}`);
}

const asOf = (step: Step) => flowRaw(step).as_of as string;
const ownId = (step: Step) => flowRaw(step).execution_id as string;
/** The journey's one run: the start's own id. */
const FLOW_ID = ownId('start');
const CHECK_IN = (flowRaw('check_in').open_waits as Array<{ wait_id: string }>)[0].wait_id;
const GOAL = (flowRaw('start').trial as { goal: string }).goal;
const GUIDE = 'Keep the README under 40 lines and add a Usage section.';

/** Temper's reply to the check-in's Guide (the shape the answer route really sends). */
const GUIDED = withBody('answer-200-guide', (b) => ({
  ...b,
  wait_id: CHECK_IN,
  answer: 'guide',
  text: GUIDE,
  at: asOf('resumed'),
}));

/** A contract test's change to one step's run and feed (fresh copies on each read). */
type Tweak = (step: Step, run: Raw, feed: { events: Raw[]; as_of: string }) => void;

/**
 * Temper for one page: the run reads as the current step under the id the
 * page opened; once the page has answered the check-in, the check-in reads as
 * resumed. The event feed answers what is past `after`, up to the run's own
 * events_cursor, at most `cap` events a page (Temper caps at the asked limit).
 */
async function serveFlow(
  page: Page,
  start: Step,
  {
    cap = Infinity,
    answer = [GUIDED],
    tweak,
    bodies,
  }: { cap?: number; answer?: Fixture[]; tweak?: Tweak; bodies?: Record<string, string> } = {},
) {
  // `down`: Temper doesn't answer run reads (the page goes stale).
  const state = { step: start, id: start === 'closing' || start === 'done' ? ownId(start) : FLOW_ID, down: false };
  const sent = nothingSent();
  const stepNow = (): Step => (state.step === 'check_in' && sent.answers.length > 0 ? 'resumed' : state.step);
  const data = (step: Step) => {
    const run = flowRaw(step);
    const feed = flowRaw(step, true) as { events: Raw[]; as_of: string };
    tweak?.(step, run, feed);
    return { run, feed };
  };
  const runNow = (): Fixture =>
    state.down
      ? { route: '', status: 503, body: { detail: 'Temper is not answering' } }
      : { route: '', status: 200, body: { ...data(stepNow()).run, execution_id: state.id } };
  const seen = await serveTeam(page, { run: runNow });
  await serveActions(page, sent, { answer });
  // `bodies`: a message's whole body by id, as Temper's message read sends it; any other id as serveTeam answers.
  if (bodies) {
    await page.route(/\/api\/team\/runs\/[^/]+\/messages\/[^/]+$/, async (route) => {
      const id = new URL(route.request().url()).pathname.split('/').pop() ?? '';
      if (!(id in bodies)) return route.fallback();
      const read = withBody('message-read', (b) => ({ ...b, message_id: id, body: bodies[id] }));
      await route.fulfill({ status: read.status, contentType: 'application/json', body: JSON.stringify(read.body) });
    });
  }
  const reads: number[] = [];
  // Set up after serveTeam, so it answers the feed first.
  await page.route(/\/api\/team\/runs\/[^/]+\/events(\?|$)/, async (route) => {
    const url = new URL(route.request().url());
    const after = Number(url.searchParams.get('after') ?? '0');
    const limit = Number(url.searchParams.get('limit') ?? '200');
    reads.push(after);
    const { run, feed } = data(stepNow());
    const upTo = run.events_cursor as number;
    const past = feed.events.filter((e) => (e.seq as number) > after && (e.seq as number) <= upTo);
    const shown = past.slice(0, Math.min(limit, cap));
    const more = past.length > shown.length;
    // Temper's cursor is the newest row it read, its hidden bookkeeping included
    // (flow_view.events_view): once nothing more waits, the run's own events_cursor.
    const cursor = more ? (shown[shown.length - 1].seq as number) : Math.max(after, upTo);
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ events: shown, cursor, more, as_of: feed.as_of }),
    });
  });
  return { state, sent, reads, seen };
}

async function open(
  page: Page,
  start: Step,
  options?: { cap?: number; clock?: string; answer?: Fixture[]; tweak?: Tweak; bodies?: Record<string, string> },
) {
  await page.clock.setFixedTime(new Date(options?.clock ?? asOf(start)));
  const served = await serveFlow(page, start, options);
  await page.goto(`/app/team/runs/${served.state.id}`);
  await expect(page.getByTestId('glance-page')).toBeVisible();
  // The whole history is read, and the map measured with the page's own fonts, before anything is asserted.
  await expect(page.getByTestId('glance-just-sent')).not.toContainText('Reading the team');
  await glanceFontsSettled(page);
  return served;
}

/** Move the journey on: the page's clock first, then what Temper says; the page's own poll reads it. */
async function goTo(page: Page, state: { step: Step }, step: Step) {
  await page.clock.setFixedTime(new Date(asOf(step)));
  state.step = step;
}

/** Open another of Temper's runs at its own id, as the owner would from the Projects list. */
async function openFresh(page: Page, state: { step: Step; id: string }, step: 'closing' | 'done') {
  await page.clock.setFixedTime(new Date(asOf(step)));
  state.step = step;
  state.id = ownId(step);
  await page.goto(`/app/team/runs/${state.id}`);
  await expect(page.getByTestId('glance-page')).toHaveAttribute('data-phase', step);
  await expect(page.getByTestId('glance-just-sent')).not.toContainText('Reading the team');
  await glanceFontsSettled(page);
}

const phase = (page: Page) => page.getByTestId('glance-page');
const nowWord = (page: Page) => page.getByTestId('glance-now-word');
const nowSentence = (page: Page) => page.getByTestId('glance-now-sentence');
const youTitle = (page: Page) => page.getByTestId('glance-you-title');
const justSent = (page: Page) => page.getByTestId('glance-just-sent');
const teamCount = (page: Page) => page.getByTestId('glance-team-count');
const spend = (page: Page) => page.getByTestId('glance-spend');
const latestFirst = (page: Page) => page.getByTestId('glance-latest').locator('li').first();
const dotsLaunched = (page: Page) => page.getByTestId('glance-map').getAttribute('data-dots-launched');

/** A CSS colour (a token, `var(--x)`) as the page computes it, to compare with what an element shows. */
const cssColor = (page: Page, value: string) =>
  page.evaluate((v) => {
    const el = document.createElement('span');
    el.style.color = v;
    document.body.appendChild(el);
    const c = getComputedStyle(el).color;
    el.remove();
    return c;
  }, value);

/** What an element's text looks like: its size and colour, and its own fill. */
const looks = (locator: Locator) =>
  locator.evaluate((el) => {
    const s = getComputedStyle(el);
    return { size: s.fontSize, color: s.color, fill: s.backgroundColor };
  });

/**
 * Lets a test hold the flying dots and the +N cue still, so one frame can be
 * looked at (D32). Off until a test sets window.__holdDots; then each new dot
 * or cue animation starts paused, as the page made it.
 */
async function installDotHold(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as { __holdDots?: boolean; __held?: Animation[] };
    const animate = Element.prototype.animate;
    Element.prototype.animate = function (this: Element, ...args: Parameters<Element['animate']>) {
      const anim = animate.apply(this, args);
      if (w.__holdDots && (this.classList.contains('glance-dot') || this.classList.contains('glance-extra'))) {
        anim.pause();
        (w.__held ??= []).push(anim);
      }
      return anim;
    };
  });
}

const holdDots = (page: Page) => page.evaluate(() => Object.assign(window, { __holdDots: true, __held: [] }));

/** Lets the held dots and cue fly on (and finish), and stops holding new ones. */
const releaseDots = (page: Page) =>
  page.evaluate(() => {
    const w = window as unknown as { __holdDots?: boolean; __held?: Animation[] };
    w.__holdDots = false;
    for (const anim of w.__held ?? []) anim.play();
    w.__held = [];
  });

/** Pixels that differ by more than 40 in some channel between two same-sized PNG screenshots, decoded in the page. */
async function pixelsApart(page: Page, a: Buffer, b: Buffer) {
  return page.evaluate(
    async ([one, two]) => {
      const read = async (b64: string) => {
        const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
        const bitmap = await createImageBitmap(new Blob([bytes], { type: 'image/png' }));
        const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
        const ctx = canvas.getContext('2d')!;
        ctx.drawImage(bitmap, 0, 0);
        return ctx.getImageData(0, 0, bitmap.width, bitmap.height).data;
      };
      const [x, y] = await Promise.all([read(one), read(two)]);
      let apart = 0;
      for (let i = 0; i < x.length; i += 4) {
        const d = Math.max(Math.abs(x[i] - y[i]), Math.abs(x[i + 1] - y[i + 1]), Math.abs(x[i + 2] - y[i + 2]));
        if (d > 40) apart += 1;
      }
      return { apart, pixels: x.length / 4 };
    },
    [a.toString('base64'), b.toString('base64')] as const,
  );
}

/**
 * D32 in pixels, on held dots: each held dot is moved to where it passes
 * closest to a count badge, then back to its start. Inside the badge, the
 * picture with the dot there and without it must match (the opaque count
 * paints over it), while with the counts hidden the dot must show there
 * (so the check is not empty). Returns the badges looked at, for the record.
 * The dots are held at full opacity: a count can sit near a line's end (D57),
 * where a flying dot is still fading in, and a full dot is the harder case.
 */
async function expectCountsOverDots(page: Page) {
  const solid = await page.addStyleTag({ content: '.glance-dot { opacity: 1 !important; }' });
  const plan = await page.evaluate(() => {
    const held = (window as unknown as { __held?: Animation[] }).__held ?? [];
    // Each count is a pill (D58): r is half its height.
    const badges = Array.from(document.querySelectorAll<SVGGElement>('g.glance-count')).map((g) => {
      const r = g.querySelector('rect')!.getBoundingClientRect();
      return { key: g.dataset.count ?? '', x: r.x + r.width / 2, y: r.y + r.height / 2, r: Math.min(r.width, r.height) / 2 };
    });
    const dots = held.filter((a) => (a.effect as KeyframeEffect | null)?.target?.classList.contains('glance-dot'));
    const at = dots.map((anim) => {
      const el = (anim.effect as KeyframeEffect).target as HTMLElement;
      const end = Number((anim.effect as KeyframeEffect).getComputedTiming().endTime);
      let best = { t: 0, key: '', d: Infinity };
      for (let t = 0; t <= end; t += 1) {
        anim.currentTime = t;
        const r = el.getBoundingClientRect();
        for (const b of badges) {
          const d = Math.hypot(r.x + r.width / 2 - b.x, r.y + r.height / 2 - b.y);
          if (d < best.d) best = { t, key: b.key, d };
        }
      }
      anim.currentTime = 0;
      return best;
    });
    return { badges, at };
  });
  expect(plan.at.length, 'held dots').toBeGreaterThan(0);
  const seek = (where: 'at' | 'away') =>
    page.evaluate(
      ([to, times]) => {
        const held = (window as unknown as { __held?: Animation[] }).__held ?? [];
        const dots = held.filter((a) => (a.effect as KeyframeEffect | null)?.target?.classList.contains('glance-dot'));
        dots.forEach((anim, i) => (anim.currentTime = to === 'at' ? times[i] : 0));
      },
      [where, plan.at.map((a) => a.t)] as const,
    );
  const seen: Array<{ key: string; passes: number; under: number; through: number; digits: number; pixels: number }> = [];
  for (const badge of plan.badges) {
    const passing = plan.at.filter((a) => a.key === badge.key && a.d <= badge.r / 2);
    if (passing.length === 0) continue;
    const side = Math.max(8, Math.floor(badge.r * 1.2));
    // The map can run past a 768 px screen: bring this count into view, then read where it is now.
    const centre = await page.evaluate((key) => {
      const rect = document.querySelector(`g.glance-count[data-count="${CSS.escape(key)}"] rect`)!;
      rect.scrollIntoView({ block: 'center', inline: 'center' });
      const r = rect.getBoundingClientRect();
      return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
    }, badge.key);
    const clip = { x: centre.x - side / 2, y: centre.y - side / 2, width: side, height: side };
    await seek('at');
    const over = await page.screenshot({ clip });
    const digits = await page.evaluate(
      async ([b64, key]) => {
        const text = document.querySelector(`g.glance-count[data-count="${CSS.escape(key)}"] text`)!;
        const [r, g, b] = getComputedStyle(text).fill.match(/\d+/g)!.map(Number);
        const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
        const bitmap = await createImageBitmap(new Blob([bytes], { type: 'image/png' }));
        const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
        const ctx = canvas.getContext('2d')!;
        ctx.drawImage(bitmap, 0, 0);
        const px = ctx.getImageData(0, 0, bitmap.width, bitmap.height).data;
        let n = 0;
        for (let i = 0; i < px.length; i += 4) if (Math.hypot(px[i] - r, px[i + 1] - g, px[i + 2] - b) < 60) n += 1;
        return n;
      },
      [over.toString('base64'), badge.key] as const,
    );
    await seek('away');
    const clear = await page.screenshot({ clip });
    const hide = await page.addStyleTag({ content: '.glance-counts { visibility: hidden !important; }' });
    await seek('at');
    const bare = await page.screenshot({ clip });
    await seek('away');
    const empty = await page.screenshot({ clip });
    await hide.evaluate((el) => el.remove());
    const under = await pixelsApart(page, over, clear);
    const through = await pixelsApart(page, bare, empty);
    seen.push({ key: badge.key, passes: passing.length, under: under.apart, through: through.apart, digits, pixels: under.pixels });
    // The count hides the dot passing under it, and its digits are there to read.
    expect(under.apart, `dot shows through the ${badge.key} count`).toBeLessThanOrEqual(Math.ceil(under.pixels * 0.03));
    expect(digits, `digits of the ${badge.key} count`).toBeGreaterThanOrEqual(4);
    // Not empty: without the counts the same dot is plainly there.
    expect(through.apart, `dot at the ${badge.key} count`).toBeGreaterThanOrEqual(Math.ceil(through.pixels * 0.25));
  }
  await solid.evaluate((el) => el.remove());
  expect(seen.length, 'counts with a dot passing under them').toBeGreaterThan(0);
  test.info().annotations.push({ type: 'counts-over-dots', description: JSON.stringify(seen) });
  return seen;
}

/** D32: the held +N cue, while shown, is the top thing where it stands; layers stack dots < counts < cue. */
async function expectExtraOnTop(page: Page) {
  const top = await page.evaluate(() => {
    const held = (window as unknown as { __held?: Animation[] }).__held ?? [];
    const cue = held.find((a) => (a.effect as KeyframeEffect | null)?.target?.classList.contains('glance-extra'));
    if (!cue) return null;
    const timing = (cue.effect as KeyframeEffect).getComputedTiming();
    cue.currentTime = Number(timing.delay ?? 0) + 0.2 * Number(timing.duration);
    const el = (cue.effect as KeyframeEffect).target as HTMLElement;
    const style = document.createElement('style');
    style.textContent = '.glance-dots, .glance-dot, .glance-counts, .glance-counts *, .glance-extras, .glance-extra { pointer-events: auto !important; }';
    document.head.appendChild(style);
    const r = el.getBoundingClientRect();
    const first = document.elementsFromPoint(r.x + r.width / 2, r.y + r.height / 2)[0];
    style.remove();
    const z = (sel: string) => Number(getComputedStyle(document.querySelector(sel)!).zIndex);
    return {
      text: el.textContent,
      opacity: getComputedStyle(el).opacity,
      onTop: first === el,
      layers: [z('.glance-dots'), z('.glance-counts'), z('.glance-extras')],
    };
  });
  expect(top, 'held +N cue').not.toBeNull();
  expect(top!.onTop, `+N cue on top: ${JSON.stringify(top)}`).toBe(true);
  expect(top!.opacity).toBe('1');
  const [dots, counts, extras] = top!.layers;
  expect(dots).toBeLessThan(counts);
  expect(counts).toBeLessThan(extras);
  return top;
}

/** The members as the page shows them at this width: map cards or list rows. */
const members = (page: Page, wide: boolean) => page.getByTestId(wide ? 'glance-map' : 'glance-list');

/** Nothing scrolls sideways: not the window, not the page column. */
async function expectNoSideways(page: Page) {
  const wide = await page.evaluate(() => {
    const out: string[] = [];
    const boxes = [document.scrollingElement, ...Array.from(document.querySelectorAll('main, [data-testid="glance-page"]'))];
    for (const el of boxes) {
      if (el && el.scrollWidth > el.clientWidth + 1) out.push(`${el.tagName.toLowerCase()} ${el.scrollWidth} > ${el.clientWidth}`);
    }
    return out;
  });
  expect(wide, 'sideways scroll').toEqual([]);
}

/**
 * The count pills as drawn (D57, D58): at least 10 px from each other and
 * 8 px (the closest spot D57 allows) from every other line, crossing hops
 * included, sampled every 0.5 px along the drawn path. Returns the closest
 * gaps for the record.
 */
async function expectBadgeClearance(page: Page) {
  const map = page.getByTestId('glance-map');
  if (!(await map.isVisible())) return null;
  const gaps = await map.evaluate((box) => {
    type B = { key: string; x: number; y: number; w: number; h: number };
    const badges: B[] = Array.from(box.querySelectorAll<SVGGElement>('g.glance-count')).map((g) => {
      const r = g.querySelector('rect') as SVGRectElement;
      const [x, y, w, h] = [r.x, r.y, r.width, r.height].map((v) => v.baseVal.value);
      return { key: g.dataset.count ?? '', x, y, w, h };
    });
    const lines = Array.from(box.querySelectorAll<SVGPathElement>('path[data-line]'));
    // SVG units -> rendered CSS pixels (the map scales with its column).
    const scale = box.querySelector('path[data-line]')?.closest('svg')?.getScreenCTM()?.a ?? 1;
    const apart = (dx: number, dy: number) => Math.hypot(Math.max(dx, 0), Math.max(dy, 0));
    let badge = Infinity;
    let line = Infinity;
    badges.forEach((a, i) => {
      for (const b of badges.slice(i + 1)) {
        badge = Math.min(badge, apart(Math.max(b.x - (a.x + a.w), a.x - (b.x + b.w)), Math.max(b.y - (a.y + a.h), a.y - (b.y + b.h))));
      }
      for (const path of lines) {
        if (path.dataset.line === a.key) continue;
        const length = path.getTotalLength();
        for (let s = 0; s <= length; s += 0.5) {
          const p = path.getPointAtLength(s);
          line = Math.min(line, apart(Math.max(a.x - p.x, p.x - (a.x + a.w)), Math.max(a.y - p.y, p.y - (a.y + a.h))));
        }
      }
    });
    return { badges: badges.length, lines: lines.length, scale, badge: badge * scale, line: line * scale };
  });
  if (gaps.badges > 1) expect(gaps.badge, 'badge to badge').toBeGreaterThanOrEqual(10);
  if (gaps.badges > 0 && gaps.lines > 1) expect(gaps.line, 'badge to another line').toBeGreaterThanOrEqual(7.5);
  test.info().annotations.push({ type: 'badge-clearance', description: JSON.stringify(gaps) });
  return gaps;
}

async function expectSound(page: Page) {
  await expectAxeClean(page);
  await expectTargets(page);
  await expectNoSideways(page);
  // Every count on a clear spot, or left off the map and kept in the list (D83), and no two lines running closer
  // than 18 px (Design D23).
  await expectDroppedCountsListed(page);
  await expect(page.getByTestId('glance-map')).toHaveAttribute('data-lines-alongside', '0');
  await expectBadgeClearance(page);
  // D28: time words stay in their 64 px slot and can wrap rather than clip.
  const times = await page.getByTestId('glance-latest-time').evaluateAll((spans) => spans.map((span) => ({
    wrap: getComputedStyle(span).whiteSpace,
    overflow: span.scrollWidth > span.clientWidth + 1,
  })));
  for (const time of times) expect(time).toEqual({ wrap: 'normal', overflow: false });
}

/** Words the free-flowing page never says: it has no rounds, no %, no ETA, no work left. */
const ROUND_WORDS = /\bround\b|\brounds\b|\breview\b|verdict|pauses after|\d\s?%|\bETA\b|work left/i;

/** A phone, a small laptop and a desktop, then 320 px: WCAG's reflow width. */
const SIZES = [
  { width: 390, height: 844 },
  { width: 1024, height: 768 },
  { width: 1440, height: 900 },
  { width: 320, height: 568 },
] as const;

for (const theme of ['dark', 'light'] as const) {
  for (const { width, height } of SIZES) {
    test(`glance journey: start to done on Temper's replies, ${theme}, ${width}x${height}`, async ({ page }) => {
      test.setTimeout(150_000);
      const wide = width >= 768;
      await page.setViewportSize({ width, height });
      await page.addInitScript((t) => localStorage.setItem('temper_theme', t), theme);
      await installDotHold(page);

      // Start: only the leader has the goal; the others wait for its first message.
      const { state, sent } = await open(page, 'start');
      await expect(phase(page)).toHaveAttribute('data-phase', 'working');
      await expect(page.getByTestId('glance-title')).toHaveText(GOAL);
      await expect(nowWord(page)).toHaveText('Working');
      await expect(nowSentence(page)).toHaveText('The leader is working; 2 members wait for its first message. Last activity 0 s ago.');
      await expect(teamCount(page)).toHaveText('1 working · 2 waiting for the leader');
      await expect(members(page, wide).getByTestId('glance-chip').filter({ hasText: 'Waiting for the leader' })).toHaveCount(2);
      await expect(youTitle(page)).toHaveText('Nothing needs you');
      await expect(spend(page)).toContainText('$0.00');
      await expect(spend(page)).toContainText('At $100 the team pauses and asks you.');
      await expect(justSent(page)).toContainText('Temper → lead');
      // Nothing shared yet: the words say how versions will read (D34).
      await expect(page.getByTestId('glance-work-empty')).toHaveText(
        'No shared version yet. When a member shares its work it shows here as v1, v2 and so on.',
      );
      await expect(page.getByTestId('glance-version')).toHaveText('No shared version yet.');
      // The guard notice is calm (D96): the panel's fill, a line-colour border, 15 px text in the secondary colour.
      const text2 = await cssColor(page, 'var(--temper-text-2)');
      const guard = page.locator('[data-guard-look="calm"]');
      await expect(guard).toBeVisible();
      expect(await looks(guard)).toMatchObject({ size: '15px', color: text2 });
      expect((await looks(page.locator('[data-note="neutral"]').filter({ has: guard }))).fill).toBe(
        await cssColor(page, 'var(--temper-panel)'),
      );
      if (wide) {
        await expect(page.getByTestId('glance-lines').locator('path[data-line]')).toHaveCount(0);
        // History never moves: the page loaded with the goal already sent.
        expect(await dotsLaunched(page)).toBe('0');
      } else {
        await expect(page.getByTestId('glance-map')).toBeHidden();
      }
      await expectSound(page);

      // The leader sends work to both members; all three work. On the map the two
      // dots are held mid-flight under their counts: the counts stay on top (D32).
      if (wide) await holdDots(page);
      await goTo(page, state, 'working');
      await expect(teamCount(page)).toHaveText('3 working', { timeout: 12_000 });
      await expect(nowSentence(page)).toHaveText('3 of 3 members working. Last activity 0 s ago.');
      // f928ed03's goal from Temper is a start row, not an owner message; the two leader requests are the burst (D74).
      await expect(justSent(page)).toContainText(
        'Just sent · 2 messages in the same second, last: lead → checker: “Build the checker part and share it.”',
      );
      await expect(page.getByTestId('glance-sent-dot')).toHaveAttribute('data-tone', 'accent');
      await expect(members(page, wide).getByTestId('glance-chip').filter({ hasText: /^Working/ })).toHaveCount(3);
      await expect(members(page, wide).getByTestId('glance-tools').first()).toHaveText('Edit ×4 · Bash ×2');
      if (wide) {
        await expect(page.getByTestId('glance-lines').locator('path[data-line]')).toHaveCount(2);
        // Two fresh work requests, two dots.
        await expect.poll(() => dotsLaunched(page)).toBe('2');
        await expectCountsOverDots(page);
        await releaseDots(page);
      } else {
        await expect(page.getByTestId('glance-list').getByTestId('glance-chip').first()).toHaveText(/^Working/);
        // D30: the narrow list keeps the supplied pair counts, not just the cards.
        const pairs = page.getByTestId('glance-pair-counts');
        await expect(pairs.getByRole('heading', { name: 'Messages in the last hour' })).toBeVisible();
        await expect(pairs).toContainText('builder and lead: 1 message');
        await expect(pairs).toContainText('checker and lead: 1 message');
        await expect(page.getByTestId('glance-phone-note')).toHaveText(
          'The switch controls busy rings here; message dots appear on the wider map.',
        );
        await expect(page.getByTestId('glance-motion-note')).toHaveCount(0);
      }
      await expectSound(page);

      // The builder shares the first version; everyone is idle.
      await goTo(page, state, 'share');
      await expect(latestFirst(page)).toContainText('builder shared v1', { timeout: 12_000 });
      await expect(page.getByTestId('glance-latest-version')).toContainText('Shared by builder');
      // Now says which version is the latest, from whom, and its note, on two 16 px lines (D97); a phone starts the
      // second with the time (D111). Shared work's number is 28 px (D93).
      const version = page.getByTestId('glance-version');
      await expect(version.getByTestId('glance-version-line1')).toContainText(/Latest version v1 from\sbuilder/);
      // At 320 the note is cut to its room, inside its quotes; the whole note is the line's title.
      await expect(version.getByTestId('glance-version-line2')).toHaveText(
        wide
          ? '\u201cBuilder\'s part is shared\u201d'
          : width >= 390
            ? /^\d+\s(s|min)\sago\s*\u201cBuilder's part is shared\u201d$/
            : /^\d+\s(s|min)\sago\s*\u201cBuilder.*\u2026\u201d$/,
      );
      await expect(version.getByTestId('glance-version-line2')).toHaveAttribute('title', "Builder's part is shared");
      for (const line of ['glance-version-line1', 'glance-version-line2']) expect((await looks(version.getByTestId(line))).size).toBe('16px');
      expect((await looks(page.getByTestId('glance-version-number'))).size).toBe('28px');
      await expect(teamCount(page)).toHaveText('3 idle');
      await expect(members(page, wide)).toContainText('Idle: “lead: waiting for the next part”');
      // Animate messages is there at every width while the run is live, and works from the keyboard
      // without losing focus (D24, D60).
      const animate = page.getByRole('switch', { name: 'Animate messages' });
      await expect(animate).toBeVisible();
      await expect(animate).toHaveAttribute('aria-checked', 'true');
      await animate.focus();
      await page.keyboard.press('Shift+Tab');
      await page.keyboard.press('Tab');
      await expect(animate).toBeFocused();
      await expectFocusRing(animate);
      await page.keyboard.press('Space');
      await expect(animate).toHaveAttribute('aria-checked', 'false');
      await expect(animate).toBeFocused();
      await page.keyboard.press('Enter');
      await expect(animate).toHaveAttribute('aria-checked', 'true');
      await expect(animate).toBeFocused();
      await expectFocusRing(animate);

      // The $100 check-in: no new work starts until you answer.
      await goTo(page, state, 'check_in');
      await expect(youTitle(page)).toHaveText('Needs you: carry on?', { timeout: 12_000 });
      await expect(phase(page)).toHaveAttribute('data-phase', 'check_in');
      // SPEC: "Check-in at $X" uses spend.cost_usd.
      await expect(nowWord(page)).toHaveText('Check-in at $105.00');
      // D112: no one works while it asks.
      await expect(nowSentence(page)).toHaveText('No one is working until you answer.');
      await expect(spend(page)).toContainText('$105.00');
      await expect(spend(page)).toContainText('If you continue, the next check-in is at $205.');
      // D98: the next check-in line, 16 px in the secondary colour. D99: You's title 20 px, 17 under 768.
      expect(await looks(page.getByTestId('glance-spend-line'))).toMatchObject({ size: '16px', color: await cssColor(page, 'var(--temper-text-2)') });
      expect((await looks(youTitle(page))).size).toBe(wide ? '20px' : '17px');
      await expect(latestFirst(page)).toContainText('Spend reached $100.00: check-in. No new work starts.');
      const answers = page.getByTestId('glance-answers').getByRole('button');
      // D91, D92: 44 px buttons; the stop reads "Stop project" with the header's square icon.
      await expect(answers).toHaveText(['Continue', 'Guide…', 'Stop project']);
      for (const b of await answers.all()) expect((await b.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44);
      await expect(answers.last().locator('svg')).toHaveCount(1);
      await expectSound(page);

      // Guide: the owner's words go once through the answer path; the leader works on them.
      await page.clock.setFixedTime(new Date(asOf('resumed')));
      await answers.getByText('Guide…', { exact: true }).click();
      await page.getByRole('textbox', { name: 'Words for lead' }).fill(GUIDE);
      await expectFocusRing(page.getByRole('textbox', { name: 'Words for lead' }));
      await expectSound(page);
      await page.getByRole('button', { name: 'Send guide' }).click();
      await expect(youTitle(page)).toHaveText('Nothing needs you', { timeout: 12_000 });
      expect(sent.answers).toHaveLength(1);
      expect(sent.answers[0]).toMatchObject({ answer: 'guide', text: GUIDE });
      await expect(phase(page)).toHaveAttribute('data-phase', 'working');
      await expect(spend(page)).toContainText('At $205 the team pauses and asks you.');
      await expect(teamCount(page)).toHaveText('1 working · 2 idle');
      await expect(justSent(page)).toContainText(`You → lead: “${GUIDE}”`, { timeout: 12_000 });
      await expect(latestFirst(page)).toContainText('You answered Temper: guide');
      // The owner's first message flies from the You hub (D5).
      if (wide) await expect.poll(() => dotsLaunched(page)).toBe('3');
      await expectSound(page);

      // Closing (another of Temper's runs): the leader said done.
      await openFresh(page, state, 'closing');
      await expect(nowWord(page)).toHaveText('Finishing up');
      await expect(nowSentence(page)).toHaveText('The leader said done.');
      await expect(page.getByTestId('glance-summary')).toContainText('Every part is shared');
      await expect(latestFirst(page)).toContainText('lead said done');
      // events_total is the count, though the cursor is at 19 (D14).
      await expect(page.getByRole('link', { name: 'All activity (18 entries)' })).toBeVisible();
      if (wide) expect(await dotsLaunched(page)).toBe('0');
      await expectSound(page);

      // Done: the last version; nothing runs any more.
      await openFresh(page, state, 'done');
      await expect(nowWord(page)).toHaveText('Done');
      await expect(teamCount(page)).toHaveText('3 members \u00b7 all ended');
      await expect(latestFirst(page)).toContainText('Done: v1 is the result');
      // D67: no next check-in, said once.
      await expect(spend(page)).toContainText('Spent in all. 0 check-ins, none to come · 1 shared version.');
      const doneVersion = (flowRaw('done').work as { latest: { commit_short: string } }).latest.commit_short;
      // No Timeline card on a free-flowing page (home's decision 3): the version's commit is in Shared work, and
      // All activity's done row has SPEC 9's words.
      await expect(page.locator('section[aria-labelledby="glance-work-title"]')).toContainText(`commit ${doneVersion.slice(0, 7)}`);
      await expect(page.locator('#glance-activity')).toContainText('Done: v1 is the result');
      await expect(page.getByRole('button', { name: 'Stop project' })).toHaveCount(0);
      await expect(page.locator('main')).not.toContainText(ROUND_WORDS);
      // An ended run's time is the one Temper froze at its end, never the clock (G5).
      await expect(page.locator('main')).toContainText(/\bran \d/);
      await expect(page.locator('main')).not.toContainText(/\brunning \d/);
      // An ended run's newest message is history (D22).
      await expect(justSent(page)).toContainText('Last message');
      await expect(page.getByTestId('glance-sent-dot')).toHaveAttribute('data-tone', 'neutral');
      // Nothing moves after the end: an ended run has no Animate switch and no note about it (D47, D60).
      await expect(page.getByRole('switch', { name: 'Animate messages' })).toHaveCount(0);
      await expect(page.getByTestId('glance-motion-note')).toHaveCount(0);
      await expectSound(page);
    });
  }
}

/** A focused control shows a ring of at least 2 px (WCAG 2.4.7 / 2.4.11). */
async function expectFocusRing(control: ReturnType<Page['getByRole']>) {
  await expect(control).toBeFocused();
  const ring = await control.evaluate((el) => {
    const s = getComputedStyle(el);
    return { outline: s.outlineStyle, width: parseFloat(s.outlineWidth), shadow: s.boxShadow };
  });
  const outlined = ring.outline !== 'none' && ring.width >= 2;
  expect(outlined || ring.shadow !== 'none', `focus ring ${JSON.stringify(ring)}`).toBe(true);
}

/** Temper's restart reply for the limit wait (the answer route's shape, as the Guide reply). */
const LIMIT_WAIT = (flowRaw('limit_asked').open_waits as Array<{ wait_id: string; words: string }>)[0];
const RESTARTED = withBody('answer-200-guide', (b) => ({
  ...b,
  wait_id: LIMIT_WAIT.wait_id,
  answer: 'restart',
  text: null,
  at: asOf('limit_asked'),
}));

/** The page's Now words for a held limit: Temper's words, the pending check, then the missing reset. */
const heldWords = (step: Step) => {
  const phase = flowRaw(step).phase as { words: string; resets_known: boolean };
  const words = phase.words.replace(/[.\s]+$/, '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const missing = phase.resets_known ? '' : ' No usable reset time\\.';
  return new RegExp(`^${words}\\. Next allowance check at [^.]+\\.${missing}( \\d+ turns? finishing\\.)?$`);
};

for (const step of ['limit', 'limit_spent', 'limit_unavailable'] as const) {
  test(`contract: a held usage limit asks nothing and offers no restart (${step}, D31)`, async ({ page }) => {
    test.setTimeout(90_000);
    await page.setViewportSize({ width: 1440, height: 900 });
    // The device's clock is years past every reset and check: only Temper's words and waits count.
    await open(page, step, { clock: '2031-01-01T00:00:00Z' });
    await expect(phase(page)).toHaveAttribute('data-phase', 'limit');
    await expect(nowWord(page)).toHaveText('Usage limit');
    await expect(nowSentence(page)).toHaveText(heldWords(step));
    await expect(youTitle(page)).toHaveText('Nothing needs you');
    await expect(page.getByTestId('glance-answers')).toHaveCount(0);
    await expect(page.getByRole('button', { name: /restart/i })).toHaveCount(0);
    await expect(page.locator('main')).not.toContainText(/available again|restart or stop/i);
    // "Stop works throughout" a limit (api-fields section 3): it stays in the header.
    await expect(page.getByRole('button', { name: 'Stop project' })).toHaveCount(1);
    const resetsKnown = (flowRaw(step).phase as { resets_known: boolean }).resets_known;
    await expect(latestFirst(page)).toContainText('Usage limit: next allowance check at ');
    if (resetsKnown) await expect(latestFirst(page)).not.toContainText('no usable reset time');
    else await expect(latestFirst(page)).toContainText('; no usable reset time');
    expect(await dotsLaunched(page)).toBe('0');
    await expectSound(page);
    await page.setViewportSize({ width: 320, height: 568 });
    await expect(nowSentence(page)).toHaveText(heldWords(step));
    await expectSound(page);
  });
}

test('contract: a verified weekly limit asks restart or stop, and Restart sends only that word (D31)', async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  const { sent } = await open(page, 'limit_asked', { answer: [RESTARTED] });
  // D89: its own word; D112: no one works while it asks; D94: Temper's words, not quoted.
  await expect(nowWord(page)).toHaveText('Usage limit: waiting for you');
  await expect(nowSentence(page)).toHaveText('No one is working until you answer.');
  await expect(youTitle(page)).toHaveText(`Needs you: ${LIMIT_WAIT.words}`);
  const answers = page.getByTestId('glance-answers').getByRole('button');
  await expect(answers).toHaveText(['Restart', 'Stop project']);
  await expectSound(page);
  await page.setViewportSize({ width: 320, height: 568 });
  await expectSound(page);
  await answers.getByText('Restart', { exact: true }).click();
  await expect.poll(() => sent.answers.length).toBe(1);
  expect(sent.answers[0]).toMatchObject({ answer: 'restart' });
  expect(sent.answers[0].text ?? '').toBe('');
  expect(sent.cancels).toHaveLength(0);
});

test('contract: dots stop when switched off or stale, and nothing replays', async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  // Chromium plays every animation 50 times slower, so a 400 ms dot is still flying when checked.
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Animation.enable');
  await cdp.send('Animation.setPlaybackRate', { playbackRate: 0.02 });
  const { state } = await open(page, 'start');
  const map = page.getByTestId('glance-map');
  const dots = page.locator('.glance-dot');
  const animate = page.getByRole('switch', { name: 'Animate messages' });

  // Off: the two dots in flight stop at once; on again, they don't fly again.
  await goTo(page, state, 'working');
  await expect(dots).toHaveCount(2, { timeout: 12_000 });
  await animate.click();
  await expect(animate).toHaveAttribute('aria-checked', 'false');
  await expect(map).toHaveAttribute('data-motion', 'off');
  await expect(dots).toHaveCount(0);
  await animate.click();
  await expect(map).toHaveAttribute('data-motion', 'on');
  await page.waitForTimeout(1_000);
  await expect(dots).toHaveCount(0);
  expect(await dotsLaunched(page)).toBe('2');

  // Stale: a burst is flying when Temper stops answering; it stops, the switch keeps your choice.
  state.step = 'burst';
  await expect(dots).toHaveCount(6, { timeout: 12_000 });
  state.down = true;
  // D64's stale note.
  await expect(page.getByText(/^Temper hasn.t answered for /).first()).toBeVisible({ timeout: 12_000 });
  await expect(map).toHaveAttribute('data-motion', 'off');
  await expect(dots).toHaveCount(0);
  await expect(page.locator('.glance-extra')).toHaveCount(0);
  await expect(animate).toHaveAttribute('aria-checked', 'true');
  await expect(page.getByTestId('glance-motion-note')).toHaveText('Paused until Temper answers; this switch saves your preference.');
  const moving = await map.evaluate((box) => box.getAnimations({ subtree: true }).filter((a) => a.playState === 'running').length);
  expect(moving, 'animations running in the map').toBe(0);

  // Temper answers again: motion is back for new messages only; nothing let go replays.
  state.down = false;
  await page.getByRole('button', { name: 'Try again' }).click();
  await expect(map).toHaveAttribute('data-motion', 'on', { timeout: 12_000 });
  await page.waitForTimeout(1_000);
  await expect(dots).toHaveCount(0);
  expect(await dotsLaunched(page)).toBe('8');
  await expectSound(page);
});

test('contract: on a phone gone stale, the list keeps the last pair counts and the note keeps your choice (D30)', async ({ page }) => {
  test.setTimeout(60_000);
  // Opened at phone width, as a phone would (the app's sidebar starts collapsed there).
  await page.setViewportSize({ width: 390, height: 844 });
  const { state } = await open(page, 'working');
  const pairs = page.getByTestId('glance-pair-counts');
  state.step = 'burst';
  await expect(pairs).toContainText('builder and lead: 5 messages', { timeout: 12_000 });
  state.down = true;
  await expect(page.getByText(/^Temper hasn.t answered for /).first()).toBeVisible({ timeout: 12_000 });
  // SPEC: on a phone the pause note comes on top of the switch note.
  await expect(page.getByTestId('glance-motion-note')).toHaveText('Paused until Temper answers; this switch saves your preference.');
  await expect(page.getByTestId('glance-phone-note')).toBeVisible();
  await expect(page.getByRole('switch', { name: 'Animate messages' })).toHaveAttribute('aria-checked', 'true');
  await expect(pairs).toContainText('builder and lead: 5 messages');
  await expect(pairs).toContainText('checker and lead: 4 messages');
  await expectSound(page);
});

test("contract: a burst past six dots counts the rest, on Temper's clock", async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await installDotHold(page);
  // The device clock is years off: every age still counts to Temper's as_of (D4, D14).
  const { state } = await open(page, 'working', { clock: '2031-01-01T00:00:00Z' });
  await expect(nowSentence(page)).toHaveText('3 of 3 members working. Last activity 0 s ago.');
  expect(await dotsLaunched(page)).toBe('0');
  await holdDots(page);
  state.step = 'burst';
  // Seven messages in one second: six dots, then "+1 more sent" (D10).
  await expect.poll(() => dotsLaunched(page), { timeout: 12_000 }).toBe('6');
  await expect(page.getByTestId('glance-map')).toHaveAttribute('data-dots-extra', '1');
  // Held mid-burst: each count reads over the dots under it, and +1 is over both (D32).
  await expect(page.locator('.glance-dot')).toHaveCount(6);
  await expectCountsOverDots(page);
  expect(await expectExtraOnTop(page)).toMatchObject({ text: '+1 more sent' });
  await releaseDots(page);
  await expect(page.locator('.glance-dot')).toHaveCount(0, { timeout: 5_000 });
  await expect(page.locator('.glance-extra')).toHaveCount(0, { timeout: 5_000 });
  await expect(justSent(page)).toContainText("lead → builder: “Use the project's name as the title.”");
  await expect(nowSentence(page)).toHaveText('2 of 3 members working. Last activity 5 s ago.');
  await expect(members(page, true).getByTestId('glance-chip').filter({ hasText: 'Working · 40 s' })).toHaveCount(2);
  await expectSound(page);
});

test('contract: before any message the sent mark is neutral, and a receiver not on this team is named, never drawn (D33)', async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  const OUTSIDE = 'Write the release note for this README.';
  const tweak: Tweak = (step, run, feed) => {
    // Starting, with the goal not yet released to the leader: no message at all.
    if (step === 'starting') feed.events = feed.events.filter((e) => e.kind !== 'message');
    if (step !== 'working') return;
    // The leader then also writes to a name with no card on this run.
    const lead = feed.events.find((e) => e.kind === 'message' && e.from === 'lead')!;
    feed.events.push({ ...lead, seq: 11, to: 'Marketing', text: OUTSIDE, message_id: 'outside-1' });
    run.events_cursor = 11;
    run.events_total = 11;
  };
  const { state } = await open(page, 'starting', { tweak });
  await expect(justSent(page)).toContainText('No messages between members yet.');
  const mark = page.getByTestId('glance-sent-dot');
  await expect(mark).toHaveAttribute('data-tone', 'none');
  const paint = await mark.evaluate((el) => {
    const s = getComputedStyle(el);
    return { fill: s.backgroundColor, ring: s.borderTopStyle, width: s.borderTopWidth };
  });
  expect(paint).toEqual({ fill: 'rgba(0, 0, 0, 0)', ring: 'solid', width: '1px' });
  await expectSound(page);

  // Two dots for the two members; the outside name gets words, not a card, line or dot.
  await goTo(page, state, 'working');
  await expect(justSent(page)).toContainText(`lead \u2192 Marketing (not on this team): \u201c${OUTSIDE}\u201d`, { timeout: 12_000 });
  await expect(teamCount(page)).toHaveText('3 working');
  await expect.poll(() => dotsLaunched(page)).toBe('2');
  await expect(page.getByTestId('glance-lines').locator('path[data-line]')).toHaveCount(2);
  await expect(page.getByTestId('glance-map').getByText('Marketing')).toHaveCount(0);
  await page.waitForTimeout(1_000);
  await expect(page.locator('.glance-dot')).toHaveCount(0);
  expect(await dotsLaunched(page)).toBe('2');
  await expectSound(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(justSent(page)).toContainText('lead \u2192 Marketing (not on this team)');
  await expect(page.getByTestId('glance-list').getByText('Marketing')).toHaveCount(0);
  await expect(page.getByTestId('glance-pair-counts')).not.toContainText('Marketing');
  await expectSound(page);
});

test('contract: a check-in while turns finish asks nothing until Temper opens its wait (D27)', async ({ page }) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  const { sent } = await open(page, 'check_in_running');
  await expect(nowWord(page)).toHaveText(/^Check-in at \$/);
  await expect(nowSentence(page)).toHaveText('No new work starts. 1 member is finishing its turn.');
  await expect(youTitle(page)).toHaveText('Nothing needs you yet');
  await expect(page.getByTestId('glance-you')).toContainText("You'll be asked to carry on once these turns finish.");
  await expect(page.getByTestId('glance-answers')).toHaveCount(0);
  await expect(page.getByRole('button', { name: /^(Continue|Guide\u2026|Stop)$/ })).toHaveCount(0);
  await expectSound(page);
  await page.setViewportSize({ width: 320, height: 568 });
  await expect(youTitle(page)).toHaveText('Nothing needs you yet');
  await expectSound(page);
  expect(sent.answers).toHaveLength(0);
});

test('contract: long ages and a time past Temper\'s clock stay in their slot; the future one shows its clock time (D22, D28)', async ({ page }) => {
  test.setTimeout(60_000);
  const later = (iso: string, ms: number) => new Date(Date.parse(iso) + ms).toISOString();
  // Temper's clock is 23 h 59 min past the history; the newest message is 10 min past Temper's clock.
  const LATER = (23 * 60 + 59) * 60_000 + 30_000;
  const tweak: Tweak = (_step, run, feed) => {
    run.as_of = later(run.as_of as string, LATER);
    feed.as_of = later(feed.as_of, LATER);
    const messages = feed.events.filter((e) => e.kind === 'message');
    messages[messages.length - 1].at = later(run.as_of as string, 10 * 60_000);
  };
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, 'working', { tweak });
  const times = page.getByTestId('glance-latest-time');
  // D59: Latest ages say "ago".
  await expect(times.filter({ hasText: /^23\sh\s59\smin\sago$/ }).first()).toBeVisible();
  await expect(times.filter({ hasText: /^\d{1,2}:\d{2}\s[AP]M$/ })).toHaveCount(1);
  await expect(page.locator('main')).not.toContainText(/\b0 s ago\b|-\d+ s\b/);
  await expect(justSent(page)).toContainText(/recorded at \d{1,2}:\d{2}\s[AP]M/);
  await expect(justSent(page)).not.toContainText(' ago');
  await expectSound(page);
  await page.setViewportSize({ width: 320, height: 568 });
  await expect(times.filter({ hasText: /^\d{1,2}:\d{2}\s[AP]M$/ })).toHaveCount(1);
  await expectSound(page);
});

test('glance with reduced motion: no dot moves, the words still update', async ({ page }) => {
  test.setTimeout(90_000);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.setViewportSize({ width: 1440, height: 900 });
  const { state } = await open(page, 'start');
  // SPEC 5: the switch is off and disabled, with the reason next to it, and still takes focus.
  const motion = page.getByRole('switch', { name: 'Animate messages' });
  await expect(motion).toHaveAttribute('aria-checked', 'false');
  await expect(motion).toHaveAttribute('aria-disabled', 'true');
  await expect(motion).toHaveAccessibleDescription('Off: your device asks for less motion');
  // It still takes focus, and Space changes nothing while the device asks for less motion.
  await motion.focus();
  await expect(motion).toBeFocused();
  await page.keyboard.press('Space');
  await expect(motion).toHaveAttribute('aria-checked', 'false');
  await goTo(page, state, 'working');
  await expect(justSent(page)).toContainText('lead → checker', { timeout: 12_000 });
  await expect(page.getByTestId('glance-lines').locator('path[data-line]')).toHaveCount(2);
  expect(await dotsLaunched(page)).toBe('0');
  await expect(page.locator('.glance-dot')).toHaveCount(0);
  await expectSound(page);

  // Once the device allows motion again, the switch is on, and it is remembered for the session.
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  const toggle = page.getByRole('switch', { name: 'Animate messages' });
  await expect(toggle).not.toHaveAttribute('aria-disabled', 'true');
  await expect(toggle).toHaveAttribute('aria-checked', 'true');
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-checked', 'false');
  await page.reload();
  await expect(page.getByRole('switch', { name: 'Animate messages' })).toHaveAttribute('aria-checked', 'false');
});

test('contract: a cut activity row opens whole in place with Show all, by keyboard, and stays open as new events arrive (D85)', async ({
  page,
}) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 1024, height: 768 });
  // lead's request to builder says more than its first line: Temper's message read holds the whole body.
  const asked = (flowRaw('working', true).events as Raw[]).find((e) => e.kind === 'message' && e.to === 'builder')!;
  const tail = 'Share it once the Install and Usage sections both run as written.';
  const body = `${asked.text as string}\n\nStart from the template in docs/README-template.md.\n${tail}`;
  // Temper's next event, once `later.on`: one new message, read by the page's own poll.
  const later = { on: false };
  const next = { ...(flowRaw('burst', true).events as Raw[]).find((e) => e.seq === 12)!, seq: 11, at: asOf('working') };
  await open(page, 'working', {
    bodies: { [asked.message_id as string]: body },
    tweak: (_step, run, feed) => {
      if (!later.on) return;
      feed.events.push(next);
      run.events_cursor = 11;
      run.events_total = 11;
    },
  });
  const region = page.getByRole('region', { name: 'All activity' });
  const heading = region.getByRole('heading', { name: 'All activity' });
  // Only the cut row offers it: every other row is whole, or its body says no more.
  const showAll = region.getByRole('button', { name: 'Show all' });
  await expect(showAll).toHaveCount(1);
  // An inner locator is matched inside each row, so it starts from the page, not from the region.
  const key = await region.locator('li', { has: page.getByRole('button', { name: 'Show all' }) }).getAttribute('data-row');
  const row = region.locator(`li[data-row="${key}"]`);
  await expect(row).toContainText(`\u201c${asked.text as string}\u201d`);
  await expect(row).not.toContainText(tail);
  await expect(showAll).toHaveAttribute('aria-expanded', 'false');
  const text = row.locator(`#${await showAll.getAttribute('aria-controls')}`);
  await expect(text).toHaveCount(1);
  const target = (await showAll.boundingBox())!;
  expect(Math.min(target.width, target.height), 'Show all target').toBeGreaterThanOrEqual(24);

  // The keyboard reaches it in order from the heading, with the focus ring; Enter opens it in place: the row's
  // top and everything above stay put, and focus stays on the button, now Show less.
  await heading.click();
  for (let i = 0; i < 20 && !(await showAll.evaluate((el) => el === document.activeElement)); i += 1) await page.keyboard.press('Tab');
  await expectFocusRing(showAll);
  await row.evaluate((el) => el.scrollIntoView({ block: 'center' }));
  const y = async () => [(await row.boundingBox())!.y, (await heading.boundingBox())!.y];
  const [rowTop, headTop] = await y();
  await page.keyboard.press('Enter');
  const showLess = region.getByRole('button', { name: 'Show less' });
  await expect(showLess).toHaveAttribute('aria-expanded', 'true');
  await expect(showLess).toBeFocused();
  await expect(text).toContainText('Start from the template in docs/README-template.md.');
  await expect(text).toContainText(tail);
  const [rowOpen, headOpen] = await y();
  expect(rowOpen, 'the row top stays put').toBeCloseTo(rowTop, 0);
  expect(headOpen, 'what is above stays put').toBeCloseTo(headTop, 0);
  await expectAxeClean(page);
  await expectTargets(page);

  // A new event arrives on the page's poll: the open row stays open, whole.
  later.on = true;
  await expect(region.locator('li').first()).toContainText(next.text as string, { timeout: 15_000 });
  await expect(showLess).toHaveAttribute('aria-expanded', 'true');
  await expect(text).toContainText(tail);

  // Space closes it: the first line again, the row's top where it was.
  const [rowBefore] = await y();
  await showLess.focus();
  await page.keyboard.press('Space');
  await expect(showAll).toHaveAttribute('aria-expanded', 'false');
  await expect(showAll).toBeFocused();
  await expect(row).not.toContainText(tail);
  expect((await y())[0], 'the row top stays put on Show less').toBeCloseTo(rowBefore, 0);
});

test('contract: history is read quietly in pages, and an ended run is read once', async ({ page }) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  // Temper answers five events a page: the page follows `more` and the cursor.
  const { reads, seen } = await open(page, 'done', { cap: 5 });
  await expect(latestFirst(page)).toContainText('Done: v1 is the result');
  await expect(justSent(page)).toContainText('lead → checker');
  expect(reads.slice(0, 4)).toEqual([0, 5, 10, 15]);
  expect(await dotsLaunched(page)).toBe('0');
  // Done is final: no more run reads after the page's 5 s poll would have come.
  const before = runReads(seen);
  await page.waitForTimeout(6_000);
  expect(runReads(seen)).toBe(before);
  await page.reload();
  await expect(latestFirst(page)).toContainText('Done: v1 is the result');
  expect(await dotsLaunched(page)).toBe('0');
});

test('contract: an old round run keeps its round page', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await serveTeam(page);
  await page.goto(`/app/team/runs/${RUN_ID}`);
  await expect(page.getByText('Who did what').first()).toBeVisible();
  await expect(page.getByText(/Pauses after/).first()).toBeVisible();
  await expect(page.getByTestId('glance-page')).toHaveCount(0);
});
