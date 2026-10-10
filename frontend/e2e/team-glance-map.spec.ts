/**
 * The glance map's lines (Design D42-D60 and its map-line decision of
 * 2026-10-09), on map stories derived from Temper's working reply
 * (e2e/fixtures/team/flow/derived/map_*, scripts/make_flow_fixtures.mjs).
 * Every /api/team answer comes from them, so no Temper is needed and nothing
 * is written.
 *
 * The map draws the pairs who messaged each other in the 10 minutes before
 * Temper's reply, at most 4, newest first; each line carries the hour's count
 * on its own straight run and a socket at both ends, never shares a stretch
 * with another line or crosses a card; a dot flies only on a drawn line, the
 * rest join "+N more sent"; and every pair of the hour is listed under the
 * map at every width. The cards are measured with the page's own fonts
 * (D80), and a line from You or Temper is routed after the drawn ones, clear
 * of their counts, hopped where it crosses (D81); when they message three or
 * more members in one second, no line is drawn: the sender's tag and the
 * receiving rings light up and one cue names the batch (D82).
 *
 * One journey first, as the owner's test rule asks (bp-be8d76b9): a team of
 * six read 50 minutes in (five recent pairs, four lines, one green), then the
 * leader's same-second burst over five pairs, in both themes at 390x844,
 * 1024x768 and 1440x900. It checks the lines, counts, list, legend, dots and
 * the switch by keyboard, with axe and 24 px targets at each step. Then
 * contract points only: every team size from 2 to 6, the font landing late,
 * the corner messaging members (every group of one or two keeps the bars,
 * team-glance-hub-groups.ts; three or more light up, also with motion off),
 * the leader's work to five members, no recent pair, and an ended run.
 */
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { expect, test, type Page } from '@playwright/test';
import { expectAxeClean, expectTargets, glanceFontsSettled, serveTeam, type Fixture } from './team-helpers';
import { droppedCounts, expectMapBars, measureMap, readHubRoutes, routeHubGroup } from './team-glance-map-measure';
import { checkHubGroups, type HubInput } from './team-glance-hub-groups';

type Raw = Record<string, unknown>;
type MapStep =
  | 'map_members_2'
  | 'map_members_3'
  | 'map_members_4'
  | 'map_members_5'
  | 'map_members_6'
  | 'map_burst'
  | 'map_fanout_before'
  | 'map_fanout'
  | 'map_quiet'
  | 'map_ended'
  | 'check_in';

const FLOW = path.join(process.cwd(), 'e2e/fixtures/team/flow');
/** A step's run, or its event feed: the map stories are derived, the check-in is Temper's own reply. */
const read = (step: MapStep, feed = false) => {
  const name = `${step}${feed ? '-events' : ''}.json`;
  const file = ['derived', 'real'].map((dir) => path.join(FLOW, dir, name)).find((f) => existsSync(f));
  if (!file) throw new Error(`no flow fixture ${name}`);
  return JSON.parse(readFileSync(file, 'utf8')) as Raw;
};
const asOf = (step: MapStep) => read(step).as_of as string;

/**
 * Temper for one page: the run reads as the current step; the event feed
 * answers what is past `after`, up to the run's own events_cursor (each
 * step's feed carries on where the one before ended).
 */
async function serveMap(page: Page, start: MapStep, links: Raw[] | null = null) {
  // `down`: Temper stops answering, the run read and the feed alike.
  // `extra`: messages released after the step's own (hubBatch), past its cursor.
  // `links`: the run's pair counts in place of the step's own (D83's maps).
  const state = { step: start, down: false, extra: [] as Raw[] };
  const id = read(start).execution_id as string;
  const cursorOf = () => (read(state.step).events_cursor as number) + state.extra.length;
  const run = (): Fixture =>
    state.down
      ? { route: '', status: 503, body: { detail: 'Temper is not answering' } }
      : { route: '', status: 200, body: { ...read(state.step), ...(links ? { links } : {}), execution_id: id, events_cursor: cursorOf() } };
  await serveTeam(page, { run });
  await page.route(/\/api\/team\/runs\/[^/]+\/events(\?|$)/, async (route) => {
    if (state.down) {
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Temper is not answering' }) });
      return;
    }
    const url = new URL(route.request().url());
    const after = Number(url.searchParams.get('after') ?? '0');
    const limit = Number(url.searchParams.get('limit') ?? '200');
    const upTo = cursorOf();
    const feed = read(state.step, true) as { events: Raw[]; as_of: string };
    const past = [...feed.events, ...state.extra].filter((e) => (e.seq as number) > after && (e.seq as number) <= upTo);
    const shown = past.slice(0, limit);
    const more = past.length > shown.length;
    const cursor = more ? (shown[shown.length - 1].seq as number) : Math.max(after, upTo);
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ events: shown, cursor, more, as_of: feed.as_of }),
    });
  });
  return { state, id };
}

/**
 * Open a map story at its first step, with the page's clock on Temper's. Ready once the history is read
 * and the map measured with the page's own fonts (D80); `fonts: false` for a test that holds them back.
 */
async function open(page: Page, start: MapStep, { fonts = true, links = null }: { fonts?: boolean; links?: Raw[] | null } = {}) {
  await page.clock.setFixedTime(new Date(asOf(start)));
  const served = await serveMap(page, start, links);
  await page.goto(`/app/team/runs/${served.id}`);
  await expect(page.getByTestId('glance-page')).toBeVisible();
  await expect(page.getByTestId('glance-just-sent')).not.toContainText('Reading the team');
  if (fonts) await glanceFontsSettled(page);
  return served.state;
}

/**
 * You and Temper message each of `to` at once (D81), `second` seconds before Temper's clock, so the page's next
 * poll reads them as one fresh batch, after any batch before it: one dot each from the corner, in this order,
 * for one or two members; three or more light up instead (D82). `from`: one sender for the whole batch;
 * otherwise You and Temper take turns.
 */
function hubBatch(
  state: { step: MapStep; extra: Raw[] },
  to: string[],
  { from, second = 1 }: { from?: 'owner' | 'temper'; second?: number } = {},
) {
  const cursor = (read(state.step).events_cursor as number) + state.extra.length;
  const at = new Date(Date.parse(asOf(state.step)) - second * 1000).toISOString();
  state.extra = [
    ...state.extra,
    ...to.map((name, i) => {
      const by = from ?? (i % 2 === 0 ? 'owner' : 'temper');
      return {
        seq: cursor + i + 1,
        at,
        kind: 'message',
        member: by,
        from: by,
        from_kind: by,
        to: name,
        message_kind: by === 'owner' ? 'guide' : 'info',
        text: `A word for ${name}.`,
        message_id: `hub-${cursor + i + 1}`,
        mid_turn: false,
      };
    }),
  ];
}

type Glow = { ring?: string; tag?: string; cue?: string; delay: number };

/** Logs each ring highlight, corner tag glow and cue the page starts, with its delay (D82), on every page load. */
async function installGlowLog(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as { __glows?: Glow[]; __glowLog?: boolean };
    if (w.__glowLog) return;
    w.__glowLog = true;
    const play = Element.prototype.animate;
    Element.prototype.animate = function (this: Element, ...args: Parameters<Element['animate']>) {
      const el = this as HTMLElement;
      const timing = args[1];
      const delay = typeof timing === 'object' && timing !== null ? Number(timing.delay ?? 0) : 0;
      const log = (w.__glows ??= []);
      if (el.dataset?.pulse !== undefined) log.push({ ring: el.dataset.pulse, delay });
      else if (el.dataset?.hubTag !== undefined) log.push({ tag: el.dataset.hubTag, delay });
      else if (el.classList?.contains('glance-extra')) log.push({ cue: el.textContent ?? '', delay });
      return play.apply(this, args);
    };
  });
}

/** What lit up since the last call. */
const takeGlows = (page: Page) =>
  page.evaluate(() => {
    const w = window as unknown as { __glows?: Glow[] };
    const out = w.__glows ?? [];
    w.__glows = [];
    return out;
  });

/** The drawn lines as painted: pair and path, in the map's order. */
const linePaths = (page: Page) =>
  page
    .getByTestId('glance-lines')
    .locator('path.glance-line')
    .evaluateAll((ps) => ps.map((p) => [(p as SVGPathElement).dataset.line, p.getAttribute('d')]));

/** Move the story on: the page's clock first, then what Temper says; the page's own poll reads it. */
async function goTo(page: Page, state: { step: MapStep }, step: MapStep) {
  await page.clock.setFixedTime(new Date(asOf(step)));
  state.step = step;
}

const map = (page: Page) => page.getByTestId('glance-map');
const legend = (page: Page) => page.getByTestId('glance-legend');
const hourList = (page: Page) => page.getByTestId('glance-pair-counts');
const animate = (page: Page) => page.getByRole('switch', { name: 'Animate messages' });

/** The drawn lines' pairs, in the map's order. */
const drawnPairs = (page: Page) =>
  page.getByTestId('glance-lines').locator('g[data-pair]').evaluateAll((gs) => gs.map((g) => (g as SVGGElement).dataset.pair));

/** Each drawn line's count, by pair. */
const counts = (page: Page) =>
  page
    .getByTestId('glance-counts')
    .locator('g.glance-count')
    .evaluateAll((gs) => Object.fromEntries(gs.map((g) => [(g as SVGGElement).dataset.count, g.textContent])));

/** The hour list as shown: pair key, whether it is drawn, its words and its time. */
const rows = (page: Page) =>
  hourList(page)
    .locator('li[data-pair]')
    .evaluateAll((lis) =>
      lis.map((li) => [
        (li as HTMLElement).dataset.pair,
        (li as HTMLElement).dataset.drawn,
        li.querySelector('.glance-hour-pair')!.textContent!.replace(/\u00a0/g, ' '),
        li.querySelector('.glance-hour-time')!.textContent,
      ]),
    );

const LEGEND =
  'Lines join members who messaged each other in the last 10 minutes (up to 4, newest first); the number is how many messages in the last hour. Every pair is listed below.';
const GREEN = 'A line turns green for a minute after a message is sent; it doesn\u2019t mean a turn is running.';
const DOTS =
  'A moving dot means a message was released, never that it was read or answered. Messages from you and Temper start at the corner.';

/** Lets a test hold the flying dots and the +N cue still: each new one starts paused once window.__holdDots is set. */
async function installDotHold(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as { __holdDots?: boolean; __held?: Animation[] };
    const play = Element.prototype.animate;
    Element.prototype.animate = function (this: Element, ...args: Parameters<Element['animate']>) {
      const anim = play.apply(this, args);
      if (w.__holdDots && (this.classList.contains('glance-dot') || this.classList.contains('glance-extra'))) {
        anim.pause();
        (w.__held ??= []).push(anim);
      }
      return anim;
    };
  });
}
const holdDots = (page: Page) => page.evaluate(() => Object.assign(window, { __holdDots: true, __held: [] }));
const releaseDots = (page: Page) =>
  page.evaluate(() => {
    const w = window as unknown as { __holdDots?: boolean; __held?: Animation[] };
    w.__holdDots = false;
    for (const anim of w.__held ?? []) anim.play();
    w.__held = [];
  });

/** A focused control shows a ring of at least 2 px (WCAG 2.4.7 / 2.4.11). */
async function expectFocusRing(control: ReturnType<Page['getByRole']>) {
  await expect(control).toBeFocused();
  const ring = await control.evaluate((el) => {
    const s = getComputedStyle(el);
    return { outline: s.outlineStyle, width: parseFloat(s.outlineWidth), shadow: s.boxShadow };
  });
  expect(ring.outline !== 'none' && ring.width >= 2 ? true : ring.shadow !== 'none', `focus ring ${JSON.stringify(ring)}`).toBe(true);
}

async function expectSound(page: Page) {
  await expectAxeClean(page);
  await expectTargets(page);
}

const SIZES = [
  { width: 390, height: 844 },
  { width: 1024, height: 768 },
  { width: 1440, height: 900 },
] as const;

for (const theme of ['dark', 'light'] as const) {
  for (const { width, height } of SIZES) {
    test(`glance map journey: a team of six, then a burst, ${theme}, ${width}x${height}`, async ({ page }) => {
      test.setTimeout(120_000);
      const wide = width >= 768;
      await page.setViewportSize({ width, height });
      await page.addInitScript((t) => localStorage.setItem('temper_theme', t), theme);
      await installDotHold(page);

      // Fifty minutes in: five pairs messaged in the last 10 minutes; the map draws the newest four.
      // (Each story message is 1 ms past its round second, so 40 s reads "39 s" and 2 min "1 min".)
      const state = await open(page, 'map_members_6');
      // On a phone nothing is drawn: the list is the whole story.
      const on = wide ? 'true' : 'false';
      const hour = [
        ['builder|lead', on, 'builder and lead: 2 messages', 'last 39 s ago'],
        ['checker|designer', on, 'checker and designer: 1 message', 'last 1 min ago'],
        ['lead|writer', on, 'lead and writer: 2 messages', 'last 3 min ago'],
        ['designer|tester', on, 'designer and tester: 1 message', 'last 5 min ago'],
        ['checker|lead', 'false', 'checker and lead: 2 messages', 'last 7 min ago'],
        ['designer|lead', 'false', 'designer and lead: 1 message', 'last 48 min ago'],
        ['lead|tester', 'false', 'lead and tester: 1 message', 'last 48 min ago'],
      ];
      // The list is there at every width, newest first, the drawn lines on top (D44).
      await expect(hourList(page).getByRole('heading', { name: 'Messages in the last hour' })).toBeVisible();
      expect(await rows(page)).toEqual(hour);
      if (wide) {
        expect(await drawnPairs(page)).toEqual(['builder|lead', 'checker|designer', 'lead|writer', 'designer|tester']);
        // Each count is the pair's row in the list (D43).
        expect(await counts(page)).toEqual({ 'builder|lead': '2', 'checker|designer': '1', 'lead|writer': '2', 'designer|tester': '1' });
        // The newest line is green for a minute, sockets too (D58); the legend says so.
        await expect(page.locator('g[data-pair][data-green="true"]')).toHaveCount(1);
        await expect(page.locator('g[data-pair="builder|lead"] circle.glance-socket.is-green')).toHaveCount(2);
        await expect(legend(page)).toHaveText(`${LEGEND} ${GREEN} ${DOTS}`);
        await expect(page.getByTestId('glance-map-quiet')).toHaveCount(0);
        await expectMapBars(page);
      } else {
        await expect(map(page)).toBeHidden();
        await expect(legend(page)).toBeHidden();
      }
      // A live run has the switch, and it works from the keyboard without losing focus (D47, D60).
      await expect(animate(page)).toBeVisible();
      await expect(animate(page)).toHaveAttribute('aria-checked', 'true');
      await animate(page).focus();
      await page.keyboard.press('Space');
      await expect(animate(page)).toHaveAttribute('aria-checked', 'false');
      await page.keyboard.press('Enter');
      await expect(animate(page)).toHaveAttribute('aria-checked', 'true');
      await expectFocusRing(animate(page));
      await expectSound(page);

      // The leader's turn releases eight messages in one second over five pairs.
      if (wide) await holdDots(page);
      await goTo(page, state, 'map_burst');
      await expect(hourList(page).locator('li[data-pair]').first()).toContainText('builder and lead: 4 messages', { timeout: 12_000 });
      expect(await rows(page)).toEqual([
        ['builder|lead', on, 'builder and lead: 4 messages', 'last 4 s ago'],
        ['checker|lead', on, 'checker and lead: 4 messages', 'last 4 s ago'],
        ['designer|lead', on, 'designer and lead: 3 messages', 'last 4 s ago'],
        ['lead|writer', on, 'lead and writer: 3 messages', 'last 4 s ago'],
        ['lead|tester', 'false', 'lead and tester: 2 messages', 'last 4 s ago'],
        ['checker|designer', 'false', 'checker and designer: 1 message', 'last 2 min ago'],
        ['designer|tester', 'false', 'designer and tester: 1 message', 'last 6 min ago'],
      ]);
      if (wide) {
        // A same-second tie goes to the higher count, then names A-Z: tester's pair is not drawn (D42).
        expect(await drawnPairs(page)).toEqual(['builder|lead', 'checker|lead', 'designer|lead', 'lead|writer']);
        expect(await counts(page)).toEqual({ 'builder|lead': '4', 'checker|lead': '4', 'designer|lead': '3', 'lead|writer': '3' });
        // Seven messages on drawn lines: the first six in release order fly; the seventh (designer's second)
        // and tester's one are "+2 more sent" (D10, D43).
        await expect.poll(() => map(page).getAttribute('data-dots-launched')).toBe('6');
        await expect(map(page)).toHaveAttribute('data-dots-extra', '2');
        const flying = await page.locator('.glance-dot').evaluateAll((dots) => dots.map((d) => (d as HTMLElement).dataset.to));
        expect(flying.sort()).toEqual(['builder', 'builder', 'checker', 'checker', 'designer', 'writer']);
        // One cue, at the map's top right, never on a line.
        const cue = page.locator('.glance-extra');
        await expect(cue).toHaveText('+2 more sent');
        const [cueBox, mapBox] = [await cue.boundingBox(), await map(page).boundingBox()];
        expect(mapBox!.x + mapBox!.width - (cueBox!.x + cueBox!.width)).toBeLessThanOrEqual(16);
        expect(cueBox!.y - mapBox!.y).toBeLessThanOrEqual(16);
        await expect(legend(page)).toHaveText(`${LEGEND} ${GREEN} ${DOTS}`);
        await expectMapBars(page);
        await releaseDots(page);
        await expect(page.locator('.glance-dot')).toHaveCount(0, { timeout: 5_000 });
      }
      await expectSound(page);
    });
  }
}

/** Each team's drawn lines at 50 minutes in (MAP_ACTS in make_flow_fixtures.mjs), newest first. */
const DRAWN: Record<number, string[]> = {
  2: ['builder|lead'],
  3: ['checker|lead', 'builder|lead', 'builder|checker'],
  4: ['builder|lead', 'designer|lead', 'checker|designer', 'builder|checker'],
  5: ['builder|lead', 'designer|tester', 'checker|lead', 'builder|checker'],
  6: ['builder|lead', 'checker|designer', 'lead|writer', 'designer|tester'],
};

test('contract: every team from 2 to 6 members keeps the bars at 1024 and 1440 (D42, D52, D57, D58)', async ({ page }) => {
  test.setTimeout(120_000);
  for (const width of [1024, 1440]) {
    for (const size of [2, 3, 4, 5, 6] as const) {
      await page.unrouteAll();
      await page.setViewportSize({ width, height: width === 1024 ? 768 : 900 });
      await open(page, `map_members_${size}`);
      expect(await drawnPairs(page), `${size} members at ${width}`).toEqual(DRAWN[size]);
      // The drawn pairs top the list; a fifth recent pair is listed, never drawn.
      const listed = await rows(page);
      expect(listed.filter((r) => r[1] === 'true').map((r) => r[0])).toEqual(DRAWN[size]);
      expect(listed.slice(0, DRAWN[size].length).map((r) => r[0])).toEqual(DRAWN[size]);
      const shown = await counts(page);
      for (const [pair, , words] of listed.filter((r) => r[1] === 'true')) {
        expect(words, `${pair}: the count on its line`).toContain(`: ${shown[pair!]} message`);
      }
      await expectMapBars(page);
    }
  }
});

/**
 * D83: four pairs of the six-member team, each with 12 messages in the same second (so drawn A-Z), whose usual
 * routes leave designer and lead's count no allowed spot on this map. In `rescued`, another route of a line gives
 * it one; in `dropped`, none does. Every line of each set keeps 28 px from the cards it doesn't join (D58), as the
 * map bars check. Found on the measured map with type/d83_e2e_cases.mts (private).
 */
const D83_SETS: Record<number, { rescued: string[]; dropped: string[] }> = {
  1024: {
    rescued: ['builder|checker', 'builder|lead', 'checker|writer', 'designer|lead'],
    dropped: ['builder|lead', 'builder|tester', 'designer|lead', 'lead|writer'],
  },
  1440: {
    rescued: ['builder|checker', 'builder|lead', 'builder|tester', 'designer|lead'],
    dropped: ['builder|lead', 'builder|tester', 'designer|lead', 'lead|writer'],
  },
};

test("contract: a count with no spot takes another route of its line, or stays off the map and keeps its number in the list (D83), at 1024 and 1440", async ({
  page,
}) => {
  test.setTimeout(120_000);
  // Two minutes before Temper's clock: drawn (D42), not green.
  const lastAt = new Date(Date.parse(asOf('map_members_6')) - 120_000).toISOString();
  const links = (pairs: string[]) =>
    pairs.map((p) => {
      const [a, b] = p.split('|');
      return { from: b, to: a, count: 12, last_at: lastAt };
    });
  for (const width of [1024, 1440]) {
    for (const [kind, pairs] of Object.entries(D83_SETS[width])) {
      const label = `${kind} at ${width}`;
      await page.unrouteAll();
      await page.setViewportSize({ width, height: width === 1024 ? 768 : 900 });
      await open(page, 'map_members_6', { links: links(pairs) });
      expect(await drawnPairs(page), `${label}: the four lines`).toEqual(pairs);
      const m = map(page);
      const listed = await rows(page);
      expect(listed.map((r) => r[0]), `${label}: every pair listed`).toEqual(pairs);
      for (const [pair, drawn, words] of listed) {
        expect(drawn, `${label}: ${pair} drawn`).toBe('true');
        expect(words, `${label}: ${pair} in the list`).toMatch(/: 12\smessages$/);
      }
      if (kind === 'rescued') {
        await expect(m, `${label}: another route placed the count`).toHaveAttribute('data-badges-rerouted', 'true');
        await expect(m).toHaveAttribute('data-badges-forced', '0');
        expect(Object.keys(await counts(page)).sort(), `${label}: every count on the map`).toEqual([...pairs].sort());
        expect(Object.values(await counts(page)), `${label}: each shows 12`).toEqual(['12', '12', '12', '12']);
      } else {
        expect(await droppedCounts(page), `${label}: designer and lead's count is left off the map`).toEqual([
          { pair: 'designer|lead', count: 12 },
        ]);
        expect(Object.keys(await counts(page)).sort(), `${label}: the other counts are drawn`).toEqual(
          pairs.filter((p) => p !== 'designer|lead').sort(),
        );
      }
      // The bars, with a dropped count found in the list with the same number and not drawn.
      await expectMapBars(page);
    }
  }
});

test('contract: once the page font lands, the lines are routed round the cards as painted, at 1024 and 1440 (D80)', async ({ page }) => {
  test.setTimeout(60_000);
  // Hold the page's own font back: the first layout uses a fallback font, and boxes change size when it lands.
  let landFont = () => {};
  const held = new Promise<void>((resolve) => (landFont = resolve));
  await page.route(/sourcesanspro-[^/]*\.ttf(\?|$)/, async (route) => {
    await held;
    await route.continue();
  });
  await page.setViewportSize({ width: 1024, height: 768 });
  await open(page, 'map_members_6', { fonts: false });
  await expect(page.getByTestId('glance-lines').locator('g[data-pair]')).toHaveCount(4);
  const font = () => page.evaluate(() => document.fonts.check('16px "Source Sans Pro"'));
  expect(await font(), 'the page font is still held back').toBe(false);
  // Not ready while the page's faces are out: the checks' ready point waits for them.
  await expect(map(page)).toHaveAttribute('data-fonts', 'waiting');
  const before = (await measureMap(page)).routedBoxes;

  landFont();
  // Ready once both faces loaded and the cards were measured again: the router's boxes are the painted ones
  // at that point, with no wait after it, and the font did change some of them.
  await expect(map(page)).toHaveAttribute('data-fonts', 'loaded');
  expect(await font(), 'the page font has landed').toBe(true);
  expect((await measureMap(page)).boxDrift, 'boxes measured with the page font').toBeLessThanOrEqual(0.5);
  const after = (await measureMap(page)).routedBoxes;
  const changed = Object.keys(after).filter((key) => {
    const [a, b] = [before[key], after[key]];
    return !a || Math.max(Math.abs(a.x - b.x), Math.abs(a.y - b.y), Math.abs(a.w - b.w), Math.abs(a.h - b.h)) > 0.5;
  });
  expect(changed.length, 'boxes the font changed').toBeGreaterThan(0);
  await expectMapBars(page);

  // A new width: measured again, still the painted boxes.
  await page.setViewportSize({ width: 1440, height: 900 });
  await expect.poll(async () => (await measureMap(page)).boxDrift, { timeout: 5_000 }).toBeLessThanOrEqual(0.5);
  await expectMapBars(page);
  await expectSound(page);
});

/**
 * The stories You and Temper message members on: every team size, the check-in's team of three, and the
 * six-member stories (quiet, before and after the leader's burst, the burst itself).
 */
const HUB_STORIES: MapStep[] = [
  'map_members_2',
  'map_members_3',
  'check_in',
  'map_members_4',
  'map_members_5',
  'map_members_6',
  'map_quiet',
  'map_fanout_before',
  'map_burst',
  'map_fanout',
];

for (const step of HUB_STORIES) {
  test(`contract: You and Temper on ${step}: one or two members get later lines, 16 px from every count, never beside a line, every crossing hopped (D81); three or more light up with no line (D82); at 1024 and 1440 in both themes`, async ({
    page,
  }) => {
    test.setTimeout(180_000);
    const members = (read(step).members as Array<{ name: string }>).map((m) => m.name);
    // The map as each width and theme measured it: the groups are routed once per distinct map.
    const measured = new Map<string, { width: number; input: HubInput; seen: string[] }>();
    await installGlowLog(page);
    for (const width of [1024, 1440]) {
      for (const theme of ['dark', 'light'] as const) {
        const label = `${step} at ${width}, ${theme}`;
        await page.unrouteAll();
        await page.addInitScript((t) => localStorage.setItem('temper_theme', t), theme);
        await page.setViewportSize({ width, height: width === 1024 ? 768 : 900 });
        const state = await open(page, step);
        const drawn = await linePaths(page);
        // Two members get a message from the corner at once (You, then Temper), each line routed after the
        // drawn ones and the batch's earlier one.
        const two = members.slice(0, 2);
        hubBatch(state, two);
        await expect(map(page), `${label}: the batch flew`).toHaveAttribute('data-dots-launched', String(two.length), {
          timeout: 15_000,
        });
        const hub = await readHubRoutes(page);
        expect(hub, `${label}: the hub routes are reported`).not.toBeNull();
        expect(hub!.routes.map((r) => r.to), `${label}: one line per receiver, in order`).toEqual(two);
        for (const r of hub!.routes) {
          const [first, last] = [r.pts[0], r.pts[r.pts.length - 1]];
          const onEdge = (p: { x: number; y: number }, b: { x: number; y: number; w: number; h: number }) =>
            p.x >= b.x - 0.5 && p.x <= b.x + b.w + 0.5 && p.y >= b.y - 0.5 && p.y <= b.y + b.h + 0.5;
          expect(onEdge(first, hub!.hub!), `${label}: ${r.to}'s line leaves the corner`).toBe(true);
          expect(onEdge(last, hub!.rects[r.to]), `${label}: ${r.to}'s line reaches its card`).toBe(true);
        }
        // The drawn lines are routed round as before: the batch changes none of them.
        expect(hub!.lines.length, `${label}: routed round the drawn lines`).toBe(drawn.length);
        expect(await linePaths(page), `${label}: drawn lines unchanged`).toEqual(drawn);
        await expectMapBars(page);
        // The page routed with hubPaths on what it measured: the same router in Node draws the same lines, so
        // every other group can be routed here on the page's own map.
        const { routes, ...input } = hub!;
        expect(routeHubGroup(input, two).routes, `${label}: the page's routes are hubPaths' on its map`).toEqual(routes);
        const key = JSON.stringify(input);
        const known = measured.get(key);
        if (known) known.seen.push(theme);
        else measured.set(key, { width, input, seen: [theme] });

        // D82: three members or more in one second, each size up to the whole team, one sender each, You and
        // Temper in turn, each batch in its own second, all read in one poll. No line and no dot: at the
        // batch's turn the sender's tag glows, each receiving ring gets its highlight, and one cue names it.
        await expect.poll(async () => (await page.evaluate(() => (window as unknown as { __glows?: Glow[] }).__glows ?? [])).filter((g) => g.ring).length, {
          message: `${label}: the two dots landed`,
        }).toBe(two.length);
        await takeGlows(page);
        const sizes = members.map((_, i) => i + 1).filter((n) => n >= 3);
        if (sizes.length === 0) continue;
        const sender = (n: number) => (n % 2 === 0 ? 'owner' : 'temper');
        const who = (n: number) => (n % 2 === 0 ? 'You' : 'Temper');
        // A different set each time: the batch of n starts at member n - 3, round the team.
        const batchTo = (n: number) => members.map((_, i) => members[(n - 3 + i) % members.length]).slice(0, n);
        sizes.forEach((n, i) => hubBatch(state, batchTo(n), { from: sender(n), second: 2 + i }));
        await expect(map(page), `${label}: every batch lit up`).toHaveAttribute('data-hub-lit', String(sizes.length), { timeout: 15_000 });
        expect(await map(page).getAttribute('data-dots-launched'), `${label}: no dot for a lit batch`).toBe(String(two.length));
        expect(await map(page).getAttribute('data-hub-routes'), `${label}: no hub line for a lit batch`).toBeNull();
        await expect(page.locator('.glance-dot'), `${label}: nothing flies`).toHaveCount(0);
        const glows = await takeGlows(page);
        sizes.forEach((n, i) => {
          // Each batch has its turn, a dot's time (400 ms) after the one before.
          const at = glows.filter((g) => g.delay === i * 400);
          expect(at.filter((g) => g.ring).map((g) => g.ring).sort(), `${label}, ${n}: one highlight per receiver`).toEqual([...batchTo(n)].sort());
          expect(at.filter((g) => g.tag).map((g) => g.tag), `${label}, ${n}: the sender's tag glows`).toEqual([sender(n)]);
        });
        // One cue at a time at the top right, 1.6 s each, in order.
        expect(glows.filter((g) => g.cue !== undefined), `${label}: the cues`).toEqual(
          sizes.map((n, i) => ({ cue: `${who(n)} \u2192 ${n} members`, delay: Math.max(i * 400, i * 1600) })),
        );
        expect(glows.filter((g) => g.ring).length, `${label}: no other highlight`).toBe(sizes.reduce((sum, n) => sum + n, 0));
        expect(glows.filter((g) => g.tag).length, `${label}: no other tag glow`).toBe(sizes.length);
        // The words: Just sent names the newest batch; Latest has one row per batch, newest first.
        const last = sizes[sizes.length - 1];
        await expect(page.getByTestId('glance-sent-words')).toHaveText(
          `Just sent \u00b7 ${who(last)} \u2192 ${last} members: \u201cA word for ${batchTo(last)[last - 1]}.\u201d`,
        );
        const latest = page.getByTestId('glance-latest').locator('li');
        for (const [i, n] of [...sizes].reverse().entries()) {
          await expect(latest.nth(i), `${label}: Latest row ${i + 1}`).toContainText(`${who(n)} sent a message to ${n} members`);
        }
        // The drawn lines are as they were.
        expect(await linePaths(page), `${label}: drawn lines unchanged`).toEqual(drawn);
        await expectMapBars(page);
      }
    }
    // Each member alone and any two at once, in either order: D81's bars, with no known gap left (D82).
    for (const { width, input, seen } of measured.values()) {
      const { results, problems } = checkHubGroups(step, width, input, members);
      expect(results.length, `${step} at ${width}: groups routed`).toBeGreaterThan(0);
      expect(problems, `${step} at ${width}, ${seen.join(' and ')}: D81 bars`).toEqual([]);
    }
  });
}

test('contract: with motion reduced, or Animate off, three members messaged at once light nothing up, and the words still change (D82)', async ({
  page,
}) => {
  test.setTimeout(90_000);
  await installGlowLog(page);
  const team = ['lead', 'builder', 'checker'];
  for (const how of ['reduced', 'off'] as const) {
    await page.unrouteAll();
    await page.setViewportSize(how === 'reduced' ? { width: 1440, height: 900 } : { width: 1024, height: 768 });
    await page.emulateMedia({ reducedMotion: how === 'reduced' ? 'reduce' : 'no-preference' });
    const state = await open(page, 'map_members_6');
    if (how === 'off') {
      await animate(page).click();
      await expect(animate(page)).toHaveAttribute('aria-checked', 'false');
    } else {
      await expect(animate(page)).toHaveAttribute('aria-checked', 'false');
    }
    await takeGlows(page);
    hubBatch(state, team, { from: 'temper' });
    await expect(page.getByTestId('glance-sent-words')).toHaveText('Just sent \u00b7 Temper \u2192 3 members: \u201cA word for checker.\u201d', {
      timeout: 15_000,
    });
    await expect(page.getByTestId('glance-latest').locator('li').first()).toContainText('Temper sent a message to 3 members');
    expect(await takeGlows(page), `${how}: no glow, highlight or cue`).toEqual([]);
    expect(await map(page).getAttribute('data-hub-lit'), `${how}: nothing lit`).toBeNull();
    await expect(page.locator('.glance-extra')).toHaveCount(0);
    await expect(page.locator('.glance-dot')).toHaveCount(0);
  }
});

test('contract: the corner says who is outside the team, row-mates share a height, and the hour list keeps its time column (D69, D71, D74, D76, D78)', async ({
  page,
}) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, 'map_members_6');
  await expect(page.getByTestId('glance-lines').locator('g[data-pair]')).toHaveCount(4);

  // D76: a 14 px muted caption, then plain You and Temper tags like the leader tag; hidden from screen readers.
  const hub = page.getByTestId('glance-hub');
  await expect(hub).toHaveAttribute('aria-hidden', 'true');
  await expect(hub.locator('.glance-hub-cap')).toHaveText('From outside the team:');
  await expect(hub.locator('.glance-hub-tag')).toHaveText(['You', 'Temper']);
  const tags = await hub.locator('.glance-hub-tag').evaluateAll((els) =>
    els.map((el) => {
      const s = getComputedStyle(el);
      return [s.fontSize, s.fontWeight, s.borderTopWidth, s.borderTopStyle, s.borderTopLeftRadius, s.outlineStyle].join(' ');
    }),
  );
  expect(tags).toEqual(['14px 600 1px solid 6px none', '14px 600 1px solid 6px none']);
  expect(await hub.locator('.glance-hub-cap').evaluate((el) => getComputedStyle(el).fontSize)).toBe('14px');

  // D78: cards sharing a grid row take the tallest one's height; the staggered leader keeps its own.
  for (const width of [1440, 1024]) {
    await page.setViewportSize({ width, height: width === 1440 ? 900 : 768 });
    await page.evaluate(() => document.fonts.ready.then(() => undefined));
    const slots = await map(page)
      .locator('li[data-slot]')
      .evaluateAll((lis) =>
        lis.map((li) => {
          const card = li.firstElementChild as HTMLElement;
          return {
            slot: (li as HTMLElement).dataset.slot!,
            top: Math.round(li.getBoundingClientRect().top),
            li: li.getBoundingClientRect().height,
            card: card.getBoundingClientRect().height,
            align: getComputedStyle(li).alignSelf,
          };
        }),
      );
    const byRow = new Map<string, typeof slots>();
    for (const s of slots) {
      const [col, row] = s.slot.split(':');
      if (col === '2') {
        // The leader spans every row: its own height, centred.
        expect(s.align, `${width}: the leader is centred`).toBe('center');
        expect(Math.abs(s.li - s.card), `${width}: the leader keeps its own height`).toBeLessThanOrEqual(0.5);
        continue;
      }
      expect(Math.abs(s.card - s.li), `${width}: the card ${s.slot} fills its cell`).toBeLessThanOrEqual(0.5);
      byRow.set(row, [...(byRow.get(row) ?? []), s]);
    }
    const shared = [...byRow.values()].filter((mates) => mates.length > 1);
    expect(shared.length, `${width}: rows with two cards`).toBeGreaterThan(0);
    for (const mates of shared) {
      const tallest = Math.max(...mates.map((m) => m.card));
      for (const m of mates) {
        expect(m.align, `${width}: ${m.slot} stretches`).toBe('stretch');
        expect(Math.abs(m.card - tallest), `${width}: ${m.slot} takes its row's height`).toBeLessThanOrEqual(0.5);
      }
    }
  }

  // D69, D71, D74(4): "N messages" never splits; the time keeps its right-hand column; under 360 px it goes under the pair.
  const hour = async () =>
    hourList(page)
      .locator('li[data-pair]')
      .evaluateAll((lis) =>
        lis.map((li) => {
          const box = li.getBoundingClientRect();
          const pair = li.querySelector('.glance-hour-pair')!;
          const time = li.querySelector('.glance-hour-time')!.getBoundingClientRect();
          const pairRects = [...pair.getClientRects()];
          return {
            words: pair.textContent!,
            li: { left: box.left, right: box.right },
            pairTop: pairRects[0].top,
            pairBottom: pairRects[pairRects.length - 1].bottom,
            pairRight: Math.max(...pairRects.map((r) => r.right)),
            time: { left: time.left, right: time.right, top: time.top },
          };
        }),
      );
  for (const width of [1024, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 768 });
    const rowsNow = await hour();
    expect(rowsNow.length).toBeGreaterThan(0);
    for (const r of rowsNow) {
      expect(r.words, `${width}: "N messages" stays together`).toMatch(/\d+\u00a0messages?$/);
      expect(Math.abs(r.time.right - r.li.right), `${width}: the time ends at the row's right edge`).toBeLessThanOrEqual(1);
      expect(r.time.left, `${width}: the time has its own column`).toBeGreaterThanOrEqual(r.pairRight);
      expect(r.time.top, `${width}: the time sits on the pair's first line`).toBeLessThan(r.pairBottom);
    }
  }
  await page.setViewportSize({ width: 320, height: 568 });
  for (const r of await hour()) {
    expect(r.time.top, '320: the time goes under the pair').toBeGreaterThanOrEqual(r.pairBottom - 1);
    expect(Math.abs(r.time.left - r.li.left), '320: the time starts at the left').toBeLessThanOrEqual(1);
  }
  await expectSound(page);
});

test("contract: the leader's work to five members flies as four dots and +1 more sent (D43)", async ({ page }) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await installDotHold(page);
  const state = await open(page, 'map_fanout_before');
  await expect(page.getByTestId('glance-lines').locator('g[data-pair]')).toHaveCount(0);
  await holdDots(page);
  await goTo(page, state, 'map_fanout');
  await expect.poll(() => map(page).getAttribute('data-dots-launched'), { timeout: 12_000 }).toBe('4');
  await expect(map(page)).toHaveAttribute('data-dots-extra', '1');
  await expect(page.locator('.glance-extra')).toHaveText('+1 more sent');
  // Five pairs in one second, one message each: names A-Z draw four; writer's message is the +1.
  expect(await drawnPairs(page)).toEqual(['builder|lead', 'checker|lead', 'designer|lead', 'lead|tester']);
  const flying = await page.locator('.glance-dot').evaluateAll((dots) => dots.map((d) => (d as HTMLElement).dataset.to));
  expect(flying.sort()).toEqual(['builder', 'checker', 'designer', 'tester']);
  await expect(hourList(page).locator('li[data-pair="lead|writer"]')).toHaveAttribute('data-drawn', 'false');
  // Latest still tells all of it.
  await expect(page.getByTestId('glance-latest').locator('li').first()).toContainText('lead sent work to 5 members');
  await expectMapBars(page);
  await releaseDots(page);
  await expectSound(page);
});

test('contract: with no pair in the last 10 minutes there are no lines, one quiet line, and the list keeps the hour (D45)', async ({ page }) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, 'map_quiet');
  await expect(page.getByTestId('glance-lines').locator('g[data-pair]')).toHaveCount(0);
  await expect(page.getByTestId('glance-map-quiet')).toHaveText('No messages between members in the last 10 minutes');
  await expect(legend(page)).toHaveCount(0);
  const listed = await rows(page);
  expect(listed).toHaveLength(7);
  expect(listed.every((r) => r[1] === 'false')).toBe(true);
  expect(listed[0]).toEqual(['builder|lead', 'false', 'builder and lead: 1 message', 'last 11 min ago']);
  await expectSound(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(hourList(page).locator('li[data-pair]')).toHaveCount(7);
  await expect(hourList(page)).toBeVisible();
  await expectSound(page);
});

test("contract: when Temper stops answering, the map keeps its last lines, nothing is green and its words end at Temper's last answer (D64, D75)", async ({
  page,
}) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  const ticker = page.getByTestId('glance-just-sent');
  const hourTitle = page.locator('#glance-hour-title');
  const greenParts = page.getByTestId('glance-lines').locator('g[data-green="true"], .is-green');
  const goesStale = async (state: { down: boolean }, step: MapStep) => {
    state.down = true;
    // The poll that fails runs 2 min after the last good read.
    await page.clock.setFixedTime(new Date(Date.parse(asOf(step)) + 120_000));
    await expect(page.getByText(/^Temper hasn.t answered for /).first()).toBeVisible({ timeout: 15_000 });
  };

  // A burst a second before Temper's last answer: green lines and "Just sent" while it answers.
  const state = await open(page, 'map_burst');
  const before = { pairs: await drawnPairs(page), counts: await counts(page), rows: await rows(page) };
  expect(before.pairs.length).toBeGreaterThan(0);
  expect(await greenParts.count()).toBeGreaterThan(0);
  await expect(ticker).toContainText('Just sent');
  await expect(legend(page)).toContainText(LEGEND);
  await expect(legend(page)).toContainText(GREEN);
  await expect(hourTitle).toHaveText('Messages in the last hour');

  await goesStale(state, 'map_burst');
  // The lines and their counts as last read; nothing green: no line, socket or just-sent cue.
  expect(await drawnPairs(page)).toEqual(before.pairs);
  expect(await counts(page)).toEqual(before.counts);
  await expect(greenParts).toHaveCount(0);
  await expect(ticker).not.toContainText('Just sent');
  await expect(ticker).toContainText('Last message');
  // The words name Temper's clock (SPEC [D75]), with no green sentence.
  await expect(legend(page)).toHaveText(
    /^Lines join members who messaged each other in the 10 minutes before Temper\u2019s last answer, 2[\s\u00a0]min ago \(up to 4, newest first\); the number is how many messages in the hour before it\. Every pair is listed below\./,
  );
  await expect(legend(page)).not.toContainText(GREEN);
  await expect(hourTitle).toHaveText('Messages in the hour before Temper\u2019s last answer');
  await expect(hourList(page).getByRole('list')).toHaveAccessibleName('Messages in the hour before Temper\u2019s last answer');
  // The same pairs, words and order; every "ago" counts on to the present (D64).
  const after = await rows(page);
  expect(after.map((r) => r.slice(0, 3))).toEqual(before.rows.map((r) => r.slice(0, 3)));
  expect(after[0][3]).not.toBe(before.rows[0][3]);
  for (const r of after) expect(r[3]).toMatch(/ ago$/);
  await expectMapBars(page);
  await expectSound(page);

  // No pair in the window: the quiet line ends at Temper's last answer too.
  await page.unrouteAll({ behavior: 'ignoreErrors' });
  const quiet = await open(page, 'map_quiet');
  await expect(page.getByTestId('glance-map-quiet')).toHaveText('No messages between members in the last 10 minutes');
  await goesStale(quiet, 'map_quiet');
  await expect(page.getByTestId('glance-map-quiet')).toHaveText(
    'No messages between members in the 10 minutes before Temper\u2019s last answer',
  );
  await expect(hourTitle).toHaveText('Messages in the hour before Temper\u2019s last answer');
  await expect(greenParts).toHaveCount(0);
  await expectSound(page);
});

test('contract: an ended run has no Animate switch at any width, and its lines keep its own time (D42, D47, D60)', async ({ page }) => {
  test.setTimeout(60_000);
  // The device's clock is a day later: lines and ages still count to Temper's as_of.
  await page.clock.setFixedTime(new Date(Date.parse(asOf('map_ended')) + 86_400_000));
  for (const { width, height } of SIZES) {
    await page.setViewportSize({ width, height });
    await serveMap(page, 'map_ended');
    await page.goto(`/app/team/runs/${read('map_ended').execution_id as string}`);
    await expect(page.getByTestId('glance-page')).toHaveAttribute('data-phase', 'done');
    await expect(animate(page)).toHaveCount(0);
    await expect(page.getByTestId('glance-motion-note')).toHaveCount(0);
    const on = width >= 768 ? 'true' : 'false';
    expect((await rows(page))[0]).toEqual(['builder|lead', on, 'builder and lead: 2 messages', 'last 1 min ago']);
    if (width >= 768) {
      expect(await drawnPairs(page)).toEqual(DRAWN[6]);
      // A minute past its last message, no line is green any more.
      await expect(page.locator('g[data-pair][data-green="true"]')).toHaveCount(0);
      await expect(legend(page)).toHaveText(`${LEGEND} ${DOTS}`);
      await expectMapBars(page);
    }
    await expectSound(page);
    await page.unrouteAll();
  }
});
