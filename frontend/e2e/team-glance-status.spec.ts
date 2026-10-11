/**
 * Design's D88-D99, D111-D113 and D116 on the free-flowing Team page (its
 * sixteenth receipt): the status box leads and the guard notice is calm.
 * Contract points only; the glance journey (team-glance.spec.ts) walks the
 * happy path with these words, sizes and colours in both themes. Every
 * /api/team answer comes from Temper's flow replies (flow/real, flow/derived),
 * some with a shared version added, so no Temper is needed and nothing is
 * written.
 *
 * - D88, D89: a paused member is yellow only while you are asked, grey
 *   otherwise; the asked usage limit has its own yellow Now word.
 * - D91, D92: every button in the band is 44 px, one solid button per view
 *   (its main action), and every stop reads "Stop project" with its icon.
 * - D94: quotes only around a person's words; Temper's own questions end
 *   with "?".
 * - D97, D111: the share note cut to one line inside its quotes, whole in the
 *   line's title and in All activity; a phone starts line 2 with the time.
 * - D111-D113: a phone lists one busy row, none under the stale note, and
 *   "and N more working" only under a row.
 * - D112: "No one is working until you answer." only when no one works.
 * - D116: at 1024x768 the version sits beside the state word only, so no busy
 *   row is cut.
 * - Design's phone table (HANDOFF-D88-D99): with a shared version the band
 *   still ends on a 390x844 first screen, in both themes.
 */
import { existsSync, mkdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { expect, test, type Locator, type Page } from '@playwright/test';
import { expectAxeClean, expectTargets, glanceFontsSettled, nothingSent, serveActions, serveTeam, type Fixture } from './team-helpers';

type Raw = Record<string, unknown>;
type Feed = { events: Raw[]; as_of: string };

const FLOW_DIR = path.join(process.cwd(), 'e2e/fixtures/team/flow');

/** A flow reply as Temper sent it (real) or as derived from one (derived), as a fresh copy. */
function flowRaw(name: string, feed = false): Raw {
  for (const dir of ['real', 'derived']) {
    const file = path.join(FLOW_DIR, dir, `${name}${feed ? '-events' : ''}.json`);
    if (existsSync(file)) return JSON.parse(readFileSync(file, 'utf8')) as Raw;
  }
  throw new Error(`no flow fixture ${name}`);
}

/** A contract test's change to the run or its feed (applied to fresh copies at each read). */
interface Change {
  run?: (run: Raw) => void;
  feed?: (feed: Feed) => void;
}

/**
 * Temper for one page, at one state: the run reads as that state (or, once
 * `down`, Temper doesn't answer); the feed answers what is past `after`, up
 * to the run's own events_cursor. Answers and messages are kept, not sent.
 */
async function serveState(page: Page, name: string, change: Change = {}) {
  const state = { down: false };
  const sent = nothingSent();
  const run = (): Fixture => {
    if (state.down) return { route: '', status: 503, body: { detail: 'Temper is not answering' } };
    const body = flowRaw(name);
    change.run?.(body);
    return { route: '', status: 200, body };
  };
  await serveTeam(page, { run });
  await serveActions(page, sent, {});
  // Set up after serveTeam, so it answers the feed first.
  await page.route(/\/api\/team\/runs\/[^/]+\/events(\?|$)/, async (route) => {
    const url = new URL(route.request().url());
    const after = Number(url.searchParams.get('after') ?? '0');
    const limit = Number(url.searchParams.get('limit') ?? '200');
    const upTo = flowRaw(name).events_cursor as number;
    const feed = flowRaw(name, true) as unknown as Feed;
    change.feed?.(feed);
    const past = feed.events.filter((e) => (e.seq as number) > after && (e.seq as number) <= upTo);
    const shown = past.slice(0, limit);
    const more = past.length > shown.length;
    const cursor = more ? (shown[shown.length - 1].seq as number) : Math.max(after, upTo);
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ events: shown, cursor, more, as_of: feed.as_of }),
    });
  });
  return { state, sent };
}

/** Open one state at its own id, the page's clock pinned to Temper's as_of, its history read. */
async function open(page: Page, name: string, change?: Change) {
  const run = flowRaw(name);
  await page.clock.setFixedTime(new Date(run.as_of as string));
  const served = await serveState(page, name, change);
  await page.goto(`/app/team/runs/${run.execution_id as string}`);
  await expect(page.getByTestId('glance-page')).toBeVisible();
  await expect(page.getByTestId('glance-just-sent')).not.toContainText('Reading the team');
  await glanceFontsSettled(page);
  return served;
}

/** A note long enough to be cut on one line at every width (Design's own words for a share). */
const LONG_NOTE =
  'Export button and CSV writer: the button sits in the toolbar, the writer quotes every field, and the tests cover both.';

/**
 * Temper's work.latest as it reads once a member has shared: v1 from builder
 * (flow/real/share), shared 4 minutes before the run's as_of, with `note`.
 */
function withVersion(note: string | null = LONG_NOTE, ago = 4 * 60_000): (run: Raw) => void {
  return (run) => {
    const work = flowRaw('share').work as Raw;
    const at = new Date(Date.parse(run.as_of as string) - ago).toISOString();
    for (const share of [work.latest, ...(work.shares as Raw[])] as Raw[]) {
      share.note = note;
      share.at = at;
    }
    run.work = work;
  };
}

/** Each member's work in the words #70 measured cut at 1024 before D116 ("Wire the Export button to t\u2026"). */
function longerWork(run: Raw) {
  for (const m of run.members as Raw[]) {
    const on = m.on as Raw | null;
    if (on && typeof on.text === 'string') on.text = 'Wire the Export button to the CSV writer';
  }
}

const nowWord = (page: Page) => page.getByTestId('glance-now-word');
const nowSentence = (page: Page) => page.getByTestId('glance-now-sentence');
const youTitle = (page: Page) => page.getByTestId('glance-you-title');
const activity = (page: Page) => page.getByRole('region', { name: 'All activity' });

/** Where the status band ends, in CSS px from the top of the window. */
const bandEnd = (page: Page) =>
  page.getByTestId('glance-band').evaluate((band) => Math.round(band.getBoundingClientRect().bottom * 10) / 10);

async function boxOf(locator: Locator) {
  const box = await locator.boundingBox();
  if (!box) throw new Error('not drawn');
  return box;
}

/** A CSS colour (a token, `var(--x)`) as the page computes it, to compare with what an element shows. */
function cssColor(page: Page, value: string): Promise<string> {
  return page.evaluate((v) => {
    const el = document.createElement('span');
    el.style.color = v;
    document.body.appendChild(el);
    const c = getComputedStyle(el).color;
    el.remove();
    return c;
  }, value);
}

const colorOf = (locator: Locator) => locator.evaluate((el) => getComputedStyle(el).color);
const fillOf = (locator: Locator) => locator.evaluate((el) => getComputedStyle(el).backgroundColor);

test('contract: a paused member is yellow only while you are asked, grey otherwise; the asked usage limit has its own yellow word (D88, D89)', async ({
  context,
}) => {
  test.setTimeout(120_000);
  for (const theme of ['dark', 'light'] as const) {
    const page = await context.newPage();
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.addInitScript((t) => localStorage.setItem('temper_theme', t), theme);
    const checker = () => page.getByTestId('glance-map').locator('[data-member="checker"]');

    // The limit, not asked: Temper waits on fresh usage, not on you. Grey, dashed (D88); Now's word grey.
    await open(page, 'limit');
    // The theme's tokens, read once the page has them.
    const yellow = await cssColor(page, 'var(--badge-waiting-text)');
    const grey = await cssColor(page, 'var(--temper-text-muted)');
    expect(yellow, 'yellow and grey differ').not.toBe(grey);
    await expect(checker().getByTestId('glance-chip')).toHaveText('Paused: usage limit');
    await expect(checker().locator('.glance-ring')).toHaveAttribute('data-ring', 'dashed-grey');
    expect(await colorOf(checker().getByTestId('glance-chip')), `${theme}: limit chip`).toBe(grey);
    await expect(nowWord(page)).toHaveText('Usage limit');
    expect(await colorOf(page.locator('.glance-now-word')), `${theme}: limit word`).toBe(grey);

    // The same limit once fresh usage is verified and you are asked: yellow, dashed (D88), and Now's own
    // word "Usage limit: waiting for you" in yellow with the yellow edge (D89).
    await page.unrouteAll({ behavior: 'ignoreErrors' });
    await open(page, 'limit_asked');
    await expect(checker().getByTestId('glance-chip')).toHaveText('Paused: usage limit');
    await expect(checker().locator('.glance-ring')).toHaveAttribute('data-ring', 'dashed-yellow');
    expect(await colorOf(checker().getByTestId('glance-chip')), `${theme}: asked chip`).toBe(yellow);
    await expect(nowWord(page)).toHaveText('Usage limit: waiting for you');
    expect(await colorOf(page.locator('.glance-now-word')), `${theme}: asked word`).toBe(yellow);
    await expect(page.getByTestId('glance-now')).toHaveAttribute('data-tone', 'yellow');
    await expectAxeClean(page);
    await page.close();
  }
});

test('contract: every button in the band is 44 px, one is solid (the main action), and every stop reads "Stop project" with its icon (D90, D91, D92)', async ({
  context,
}) => {
  test.setTimeout(150_000);
  for (const width of [390, 1440]) {
    const page = await context.newPage();
    await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });

    // The check-in asks: Continue is the one solid button; Guide… and Stop project are outlined.
    await open(page, 'check_in');
    const accent = await cssColor(page, 'var(--temper-accent)');
    const answers = page.getByTestId('glance-answers').getByRole('button');
    await expect(answers).toHaveText(['Continue', 'Guide\u2026', 'Stop project']);
    const solid: string[] = [];
    for (const button of await page.getByTestId('glance-band').getByRole('button').all()) {
      const name = ((await button.textContent()) ?? '').trim();
      expect((await boxOf(button)).height, `${width}: ${name} is 44 px`).toBeGreaterThanOrEqual(44);
      if ((await fillOf(button)) === accent) solid.push(name);
    }
    expect(solid, `${width}: one solid button`).toEqual(['Continue']);
    // The header's stop and You's stop: the same words and the same square icon (D92).
    for (const stop of await page.getByRole('button', { name: 'Stop project' }).all()) {
      await expect(stop.locator('svg')).toHaveCount(1);
      expect((await boxOf(stop)).height, `${width}: Stop project`).toBeGreaterThanOrEqual(44);
    }
    await expect(page.getByRole('button', { name: 'Stop project' })).toHaveCount(2);
    await expect(page.getByRole('button', { name: /^stop$/i })).toHaveCount(0);

    // An ended run: "New project" is its one main action, a 44 px solid button; the run page stays a link (D90, D91).
    await page.unrouteAll({ behavior: 'ignoreErrors' });
    await open(page, 'stopped');
    await expect(page.getByTestId('glance-you')).toContainText('Read what it made below, or start a new project.');
    const next = page.getByTestId('glance-new-project');
    await expect(next).toHaveAccessibleName('New project');
    await expect(next).toHaveAttribute('href', /\/team\/new$/);
    expect((await boxOf(next)).height, `${width}: New project`).toBeGreaterThanOrEqual(44);
    expect(await fillOf(next), `${width}: New project is solid`).toBe(accent);
    await expect(page.getByRole('link', { name: 'Open the run page' })).toBeVisible();
    await expectAxeClean(page);
    await expectTargets(page);
    await page.close();
  }
});

test('contract: only a person\u2019s words are quoted in You, and Temper\u2019s own questions end with "?" (D94)', async ({ context }) => {
  test.setTimeout(150_000);
  const titles: Record<string, string | RegExp> = {
    // A member's own question: its words, quoted, cut after a whole word (D62).
    member_question: /^Needs you: \u201c.+\u2026\u201d$/,
    // A held turn: Temper's own words, never quoted.
    failed: `Needs you: ${(flowRaw('failed').you as { first: { words: string } }).first.words}`,
    // Temper's own questions.
    check_in: 'Needs you: carry on?',
    stalled: 'Needs you: nudge the team or stop?',
    settings: 'Needs you: go on or stop?',
    // The asked usage limit: Temper's words as sent, not quoted (D31).
    limit_asked: `Needs you: ${(flowRaw('limit_asked').you as { first: { words: string } }).first.words}`,
  };
  for (const [name, title] of Object.entries(titles)) {
    const page = await context.newPage();
    await page.setViewportSize({ width: 1440, height: 900 });
    await open(page, name);
    await expect(youTitle(page), name).toHaveText(title);
    if (name !== 'member_question') await expect(youTitle(page), `${name}: not quoted`).not.toContainText(/[\u201c\u201d"]/);
    // Every stop the page offers reads "Stop project" (D92).
    for (const stop of await page.getByTestId('glance-answers').getByRole('button', { name: /stop/i }).all()) {
      await expect(stop, name).toHaveText('Stop project');
    }
    await page.close();
  }
});

for (const { width, height } of [
  { width: 1440, height: 900 },
  { width: 390, height: 844 },
] as const) {
  test(`contract: Now's version lines say who shared what and when; a long note is cut inside its quotes, whole in its title and in All activity (D97, D111), ${width}x${height}`, async ({
    page,
  }) => {
    test.setTimeout(90_000);
    const phone = width < 768;
    await page.setViewportSize({ width, height });
    await open(page, 'share', {
      run: withVersion(LONG_NOTE),
      feed: (feed) => {
        for (const e of feed.events) if (e.kind === 'share') e.note = LONG_NOTE;
      },
    });
    const version = page.getByTestId('glance-version');
    const line1 = version.getByTestId('glance-version-line1');
    const line2 = version.getByTestId('glance-version-line2');
    // Line 1: "Latest version v1 from builder · 4 min ago"; under 768 px the time leads line 2 instead (D111).
    // (Each fact starts with its hidden "·" separator; Playwright reads a no-break space as a space.)
    if (phone) {
      await expect(line1).toHaveText(/^\u00b7?\s*Latest version v1 from\sbuilder$/);
      await expect(line2).toHaveText(/^4\smin\sago\s*\u201cExport.*\u2026\u201d$/);
    } else {
      await expect(line1).toHaveText(/^\u00b7?\s*Latest version v1 from\sbuilder\s*\u00b7\s*4\smin\sago$/);
      await expect(line2).toHaveText(/^\u201cExport.*\u2026\u201d$/);
    }
    // What shows is the note's own start, cut to the room left (D97).
    const shown = /\u201c(.*)\u2026\u201d/.exec((await line2.getByTestId('glance-version-note').textContent()) ?? '')?.[1] ?? '';
    expect(shown.length, 'some of the note shows').toBeGreaterThan(5);
    expect(LONG_NOTE.startsWith(shown), `"${shown}" starts the note`).toBe(true);
    // One line each, 16 px; the note cut to the room left, its closing quote kept, the whole note in the title.
    for (const line of [line1, line2]) {
      expect(await line.evaluate((el) => getComputedStyle(el).fontSize)).toBe('16px');
      const { height: h } = await boxOf(line);
      expect(h, 'one line').toBeLessThan(16 * 1.35 * 1.5);
    }
    await expect(line2).toHaveAttribute('title', LONG_NOTE);
    const note = line2.getByTestId('glance-version-note');
    expect(await note.evaluate((el) => el.scrollWidth <= el.clientWidth + 1), 'the cut fits: no CSS ellipsis needed').toBe(true);
    await expect(activity(page)).toContainText(`builder shared v1: \u201c${LONG_NOTE}\u201d`);
    await expectAxeClean(page);

    // With no note, line 2 counts the files Temper says changed.
    await page.unrouteAll({ behavior: 'ignoreErrors' });
    await open(page, 'share', { run: withVersion(null) });
    await expect(page.getByTestId('glance-version-files')).toHaveText('1 file changed');
    await expect(page.getByTestId('glance-version-line2')).not.toHaveAttribute('title', /./);
  });
}

test('contract: a phone lists one busy row and counts the rest; under the stale note it lists none and no "and N more" (D111, D113)', async ({
  page,
}) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 390, height: 844 });
  const { state } = await open(page, 'working', { run: withVersion() });
  const working = page.getByTestId('glance-working');
  await expect(working.getByTestId('glance-working-row')).toHaveCount(1);
  await expect(working.getByText('and 2 more working', { exact: true })).toBeVisible();
  expect(await bandEnd(page), 'band end').toBeLessThanOrEqual(844);

  // Temper stops answering: the stale note takes the row's room; the count line keeps the number.
  state.down = true;
  await expect(page.getByText(/^Temper hasn.t answered for /).first()).toBeVisible({ timeout: 15_000 });
  await expect(nowSentence(page)).toHaveText('3 of 3 members working.');
  await expect(page.getByTestId('glance-working')).toHaveCount(0);
  await expect(page.getByText(/^and \d+ more working$/)).toHaveCount(0);
  // The stale note's Try again: a 44 px outlined button (D91).
  const retry = page.getByRole('button', { name: 'Try again' });
  expect((await boxOf(retry)).height).toBeGreaterThanOrEqual(44);
  expect(await fillOf(retry)).not.toBe(await cssColor(page, 'var(--temper-accent)'));
  expect(await bandEnd(page), 'band end, stale').toBeLessThanOrEqual(844);
  await expectAxeClean(page);
});

/** Item 14: emoji, a skin-tone ZWJ sequence, a family ZWJ sequence and combining accents early in a long note. */
const UNICODE_NOTE =
  'CSV [grin] cafe\u0301 [coder] and [family] export: the writer quotes every field, the button sits in the toolbar, and the tests cover both.'
    .replace('[grin]', '\u{1F600}')
    .replace('[coder]', '\u{1F469}\u{1F3FD}\u200D\u{1F4BB}')
    .replace('[family]', '\u{1F468}\u200D\u{1F469}\u200D\u{1F467}');
const graphemeEnds = (s: string) => {
  const ends = new Set<number>([0]);
  for (const g of new Intl.Segmenter('en', { granularity: 'grapheme' }).segment(s)) ends.add(g.index + g.segment.length);
  return ends;
};
const LONE_SURROGATE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/;

for (const theme of ['dark', 'light'] as const) {
  test(`contract: a long Unicode note is cut only between whole characters, refits on resize, whole in its title and All activity (item 14), ${theme}`, async ({
    page,
  }) => {
    test.setTimeout(120_000);
    await page.addInitScript((t) => localStorage.setItem('temper_theme', t), theme);
    await page.setViewportSize({ width: 320, height: 844 });
    await open(page, 'share', {
      run: withVersion(UNICODE_NOTE),
      feed: (feed) => {
        for (const e of feed.events) if (e.kind === 'share') e.note = UNICODE_NOTE;
      },
    });
    const line2 = page.getByTestId('glance-version-line2');
    const note = line2.getByTestId('glance-version-note');
    const ends = graphemeEnds(UNICODE_NOTE);
    const lengths: number[] = [];
    for (const width of [320, 390, 1024, 390]) {
      await page.setViewportSize({ width, height: width < 768 ? 844 : 768 });
      await glanceFontsSettled(page);
      // D111's responsive shape must be in place before measuring the room left.
      if (width < 768) await expect(line2).toContainText(/4.min.ago/);
      else await expect(line2).not.toContainText(/4.min.ago/);
      // The sidebar really animates between its 56px phone rail and 200px wide panel.
      // Measure only its finished room, not a native maximum that changes afterward.
      const sidebar = page.getByRole('complementary').filter({ has: page.getByRole('navigation', { name: 'Main navigation' }) });
      await expect(sidebar).toHaveCSS('width', width < 768 ? '56px' : '200px');
      // Map readiness is not the note's ResizeObserver completion signal on a phone.
      // Independently measure whole grapheme prefixes in the same native font, then
      // await the EXACT longest fitting result (no sleeps, looser cut or overflow bar).
      const fitted = await line2.evaluate(async (v2, whole) => {
        await document.fonts.ready;
        const t = v2.querySelector<HTMLElement>('[data-testid="glance-version-note"]')!;
        const room = v2.getBoundingClientRect().width - [...v2.children]
          .filter((c) => c !== t).reduce((w, c) => w + c.getBoundingClientRect().width, 0);
        const css = getComputedStyle(t);
        const probe = document.createElement('span');
        Object.assign(probe.style, { position: 'fixed', left: '-10000px', top: '0', whiteSpace: 'nowrap' });
        for (const key of ['fontFamily', 'fontSize', 'fontWeight', 'fontStyle', 'fontStretch', 'fontKerning',
          'fontVariant', 'fontFeatureSettings', 'fontVariationSettings', 'letterSpacing', 'wordSpacing', 'textTransform'] as const) {
          probe.style[key] = css[key];
        }
        document.body.append(probe);
        let expected = '\u201c\u2026\u201d';
        try {
          const limits = [0, ...[...new Intl.Segmenter('en', { granularity: 'grapheme' }).segment(whole)]
            .map((g) => g.index + g.segment.length)];
          for (const end of limits) {
            const candidate = end === whole.length ? `\u201c${whole}\u201d` : `\u201c${whole.slice(0, end).trimEnd()}\u2026\u201d`;
            probe.textContent = candidate;
            if (probe.getBoundingClientRect().width <= room + 0.01) expected = candidate;
          }
          return { expected, room, font: css.font, children: [...v2.children].map((c) => ({
            text: c.textContent, width: c.getBoundingClientRect().width,
          })) };
        } finally { probe.remove(); }
      }, UNICODE_NOTE);
      await test.info().attach(`unicode-fit-${width}-${lengths.length}`, {
        body: Buffer.from(JSON.stringify(fitted, null, 2)), contentType: 'application/json',
      });
      await expect(note, `native maximum fit at ${width}`).toHaveText(fitted.expected);
      await expect(note).toHaveText(/^\u201c.+\u2026\u201d$/);
      const shown = /^\u201c(.*)\u2026\u201d$/.exec((await note.textContent()) ?? '')?.[1] ?? '';
      expect(UNICODE_NOTE.startsWith(shown), `"${shown}" starts the note at ${width}`).toBe(true);
      expect(ends.has(shown.length), `"${shown}" ends on a whole character at ${width}`).toBe(true);
      expect(LONE_SURROGATE.test(shown), `no half character at ${width}`).toBe(false);
      expect(await note.evaluate((el) => el.scrollWidth <= el.clientWidth + 1), `the cut fits at ${width}`).toBe(true);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `no sideways scroll at ${width}`).toBe(true);
      await expect(line2).toHaveAttribute('title', UNICODE_NOTE);
      lengths.push(shown.length);
    }
    expect(lengths[2], 'wider window shows more of the note').toBeGreaterThan(lengths[1]);
    expect(lengths[3], 'back to the phone, the same cut').toBe(lengths[1]);
    await expect(activity(page)).toContainText(`builder shared v1: \u201c${UNICODE_NOTE}\u201d`);
    await expectAxeClean(page);
  });

  test(`contract: the stale note is red with a warning sign; words, frozen page, retry and fit unchanged (D122), ${theme}`, async ({ page }) => {
    test.setTimeout(120_000);
    await page.addInitScript((t) => localStorage.setItem('temper_theme', t), theme);
    await page.setViewportSize({ width: 1440, height: 900 });
    const { state, sent } = await open(page, 'working', { run: withVersion() });
    const asked = await page.getByTestId('glance-answers').count();
    state.down = true;
    const stale = page.locator('[data-note]').filter({ hasText: /^Temper hasn.t answered for / });
    await expect(stale).toBeVisible({ timeout: 15_000 });
    await expect(stale).toHaveAttribute('data-note', 'bad');
    expect(await fillOf(stale), 'red tint').toBe(await cssColor(page, 'var(--badge-failed-bg)'));
    expect(await fillOf(stale), 'not the answer-request yellow').not.toBe(await cssColor(page, 'var(--badge-waiting-bg)'));
    const sign = stale.locator('svg').first();
    expect(await colorOf(sign), 'red warning sign').toBe(await cssColor(page, 'var(--badge-failed-text)'));
    await expect(stale).toContainText('This is what it said last; nothing below moves until it answers again.');
    await expect(nowWord(page)).toHaveText(/^Last seen: /);
    await expect(page.getByTestId('glance-answers')).toHaveCount(asked);
    const retry = stale.getByRole('button', { name: 'Try again' });
    for (const [width, height] of [[1440, 900], [390, 844], [320, 844]] as const) {
      await page.setViewportSize({ width, height });
      const box = await boxOf(retry);
      expect(box.height, `Try again 44 px at ${width}`).toBeGreaterThanOrEqual(44);
      expect(await fillOf(retry), 'outline, not solid').not.toBe(await cssColor(page, 'var(--temper-accent)'));
      expect(await stale.evaluate((el) => el.scrollWidth <= el.clientWidth + 1), `note fits at ${width}`).toBe(true);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `no sideways scroll at ${width}`).toBe(true);
      await expectTargets(page);
      await expectAxeClean(page);
      if (process.env.FIELDS_SHOTS) mkdirSync(process.env.FIELDS_SHOTS, { recursive: true });
      if (process.env.FIELDS_SHOTS) await page.screenshot({ path: path.join(process.env.FIELDS_SHOTS, `d122-stale-${theme}-${width}.png`) });
    }
    state.down = false;
    await retry.click();
    await expect(stale).toHaveCount(0, { timeout: 15_000 });
    await expect(nowWord(page)).not.toHaveText(/^Last seen: /);
    expect(sent).toEqual(nothingSent());
  });
}

test('contract: "No one is working until you answer." only while you are asked and no one works (D95, D112)', async ({ context }) => {
  test.setTimeout(150_000);
  const NO_ONE = 'No one is working until you answer.';
  const cases: [string, string | RegExp, string | RegExp][] = [
    ['waiting', 'Waiting for you', NO_ONE],
    ['check_in', /^Check-in at \$[\d.]+$/, NO_ONE],
    ['stalled', 'Everyone is idle', NO_ONE],
    ['settings', 'Settings changed', NO_ONE],
    ['limit_asked', 'Usage limit: waiting for you', NO_ONE],
    // Asked while members work: the count stays (SPEC: never a claim that no one works).
    ['member_question', 'Working', /^\d+ of \d+ members working\./],
    // The check-in before it asks: turns still finishing, in the word too (D95); someone still works.
    ['check_in_running', /^Check-in at \$[\d.]+: finishing turns$/, /^(?!No one is working)/],
  ];
  for (const [name, word, sentence] of cases) {
    const page = await context.newPage();
    await page.setViewportSize({ width: 1440, height: 900 });
    await open(page, name);
    await expect(nowWord(page), name).toHaveText(word);
    await expect(nowSentence(page), name).toHaveText(sentence);
    await page.close();
  }
});

test('contract: at 1024x768 the version sits beside the state word only, and no busy row is cut (D116)', async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 1024, height: 768 });
  await open(page, 'working', {
    run: (run) => {
      withVersion()(run);
      longerWork(run);
    },
  });
  const now = page.getByTestId('glance-now');
  const word = page.locator('.glance-now-word');
  const version = page.getByTestId('glance-version');
  const [n, w, v, s] = await Promise.all([now, word, version, nowSentence(page)].map(boxOf));
  // The version beside the word, on its row; the sentence under both, across Now.
  expect(v.x, 'version right of the word').toBeGreaterThanOrEqual(w.x + w.width - 1);
  expect(Math.abs(v.y - w.y), 'version on the word\u2019s row').toBeLessThan(12);
  expect(s.y, 'sentence under the word').toBeGreaterThanOrEqual(w.y + w.height - 1);
  expect(s.width, 'sentence across Now').toBeGreaterThan(n.width * 0.75);
  // Every busy row shows its whole work: nothing cut to a few letters.
  await expect(page.getByTestId('glance-working-row')).toHaveCount(3);
  const rows = page.getByTestId('glance-working-on');
  expect(await rows.count(), 'rows with work words').toBeGreaterThan(0);
  const cut = await rows.evaluateAll((els) => els.filter((el) => el.scrollWidth > el.clientWidth + 1).map((el) => el.textContent));
  expect(cut, 'cut busy rows').toEqual([]);
  expect(await bandEnd(page), 'band end').toBeLessThanOrEqual(768);
  await expectAxeClean(page);
});

/**
 * Design's phone table (HANDOFF-D88-D99, 390x844): each situation with a
 * shared version and a long note, in both themes; the band ends on the
 * first screen. Ours: the stale page, a member's long question, six
 * members, a held turn, the asked check-in, two members asking, the asked
 * usage limit.
 */
const PHONE_TABLE = ['member_question', 'map_members_6', 'failed', 'check_in', 'waiting', 'limit_asked'] as const;

test('contract: with a shared version the band still ends on a 390x844 first screen in Design\u2019s phone situations, both themes (D97, D111)', async ({
  context,
}) => {
  test.setTimeout(300_000);
  const ends: Record<string, number> = {};
  for (const theme of ['dark', 'light'] as const) {
    for (const name of PHONE_TABLE) {
      const page = await context.newPage();
      await page.setViewportSize({ width: 390, height: 844 });
      await page.addInitScript((t) => localStorage.setItem('temper_theme', t), theme);
      await open(page, name, { run: withVersion() });
      await expect(page.getByTestId('glance-version-line2'), name).toBeVisible();
      ends[`${name} ${theme}`] = await bandEnd(page);
      await page.close();
    }
    const page = await context.newPage();
    await page.setViewportSize({ width: 390, height: 844 });
    await page.addInitScript((t) => localStorage.setItem('temper_theme', t), theme);
    const { state } = await open(page, 'working', { run: withVersion() });
    state.down = true;
    await expect(page.getByText(/^Temper hasn.t answered for /).first()).toBeVisible({ timeout: 15_000 });
    ends[`stale ${theme}`] = await bandEnd(page);
    await page.close();
  }
  test.info().annotations.push({ type: 'band-ends', description: JSON.stringify(ends) });
  const over = Object.entries(ends).flatMap(([k, end]) => (end <= 844 ? [] : [`${k}: ${end}`]));
  expect(over, 'band ends past 844 px').toEqual([]);
});
