/**
 * The free-flowing Team page's words and states outside the map (Design's
 * rows D8, D9 and D35-D77), on Temper's final serializer replies (flow/real)
 * and the states derived from them (flow/derived). Every /api/team answer
 * comes from them, so no Temper is needed and nothing is written.
 *
 * Happy path first, as the owner's test rule asks (bp-be8d76b9): a working
 * team read at a glance in both themes at 390x844, 1024x768 and 1440x900,
 * then 320 px (reflow). Now names who works on what, You and Spend say what
 * they mean, the cards put role and leader under the name, Latest says "...
 * ago" and All activity tells the time to the second; with axe, 24 px
 * targets, 14 px header buttons, no text under 14 px and no sideways
 * scroll; on a phone the band ends on the first screen.
 * Then contract points only: a member's own long question (named, cut in
 * the band, whole with Temper's note in the answer view), the phone band in
 * every state Temper can be in, a usage check that can't be read, ended
 * runs, and a page whose Temper stops answering.
 */
import { existsSync, readdirSync, readFileSync } from 'node:fs';
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

/** Every state there is a reply for, real and derived. */
const STATES = ['real', 'derived']
  .flatMap((dir) => readdirSync(path.join(FLOW_DIR, dir)))
  .filter((f) => f.endsWith('.json') && !f.endsWith('-events.json'))
  .map((f) => f.slice(0, -'.json'.length))
  .sort();

const ENDED = new Set(['done', 'stopped', 'failed', 'interrupted']);
const phaseOf = (name: string) => (flowRaw(name).phase as { name: string }).name;

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

const nowWord = (page: Page) => page.getByTestId('glance-now-word');
const nowSentence = (page: Page) => page.getByTestId('glance-now-sentence');
const youTitle = (page: Page) => page.getByTestId('glance-you-title');
const activity = (page: Page) => page.getByRole('region', { name: 'All activity' });
const stopButton = (page: Page) => page.getByRole('button', { name: 'Stop project' });

/**
 * D84: states whose band still ends past 844 px at the 320 reflow (264 px of page beside the rail), with text at
 * SPEC's sizes, the reference's phone spacing (D9) and Now's rows capped: recorded for Design with where the band
 * ends (px). Each may not grow. The check-in and limit states grew by one line with SPEC's own words: Now's
 * "Check-in at $X" from spend.cost_usd (l.129-130, l.141) and the limit's You line "Stop stays at the top if you want
 * to end it." (l.148); recorded for Design again with the new ends.
 */
const D84_OVER_AT_320: Record<string, number> = {
  burst: 853.1,
  check_in: 985.6,
  check_in_running: 906.6,
  draining: 850.6,
  failed: 914.6,
  limit: 944.6,
  limit_asked: 972.6,
  limit_spent: 878.6,
  limit_start_check: 854.6,
  limit_unavailable: 854.6,
  map_fanout: 875.1,
  member_question: 1015.1,
  settings: 945.6,
  stalled: 916.6,
  waiting: 970.6,
};

/** Where the status band ends, in CSS px from the top of the window (D9: at most 844 on a 390x844 phone). */
const bandEnd = (page: Page) =>
  page.getByTestId('glance-band').evaluate((band) => Math.round(band.getBoundingClientRect().bottom * 10) / 10);

async function boxOf(locator: Locator) {
  const box = await locator.boundingBox();
  if (!box) throw new Error('not drawn');
  return box;
}

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

/** No visible text on the page is under 14 px (SPEC: "Nothing is smaller than 14"); the sidebar is not the page's. */
async function expectNoSmallText(page: Page) {
  const small = await page.getByRole('main').evaluate((main) => {
    const out: string[] = [];
    const walker = document.createTreeWalker(main, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const el = n.parentElement;
      if (!n.textContent?.trim() || !el || el.closest('.sr-only, svg') || !el.getClientRects().length) continue;
      const s = getComputedStyle(el);
      if (s.visibility === 'hidden' || parseFloat(s.fontSize) >= 14) continue;
      out.push(`${s.fontSize} "${n.textContent.trim().slice(0, 40)}"`);
    }
    return out;
  });
  expect(small, 'text under 14 px').toEqual([]);
}

const SIZES = [
  { width: 390, height: 844 },
  { width: 1024, height: 768 },
  { width: 1440, height: 900 },
] as const;

for (const theme of ['dark', 'light'] as const) {
  for (const { width, height } of SIZES) {
    test(`words journey: a working team at a glance, ${theme}, ${width}x${height}`, async ({ page }) => {
      test.setTimeout(90_000);
      const phone = width < 768;
      await page.setViewportSize({ width, height });
      await page.addInitScript((t) => localStorage.setItem('temper_theme', t), theme);
      await open(page, 'working');

      // Header: both breadcrumbs are whole targets (D35); the buttons are 14 px (D8/D9),
      // and a phone leaves out "3 members", since Now counts them on the same screen (D74).
      const crumbs = page.getByRole('navigation', { name: 'Breadcrumb' }).getByRole('link');
      await expect(crumbs).toHaveText(['Team', 'Projects']);
      for (const crumb of await crumbs.all()) {
        const box = await boxOf(crumb);
        expect(Math.min(box.width, box.height), 'breadcrumb target').toBeGreaterThanOrEqual(24);
      }
      for (const name of ['Message a member', 'Stop project']) {
        await expect(page.getByRole('button', { name })).toHaveCSS('font-size', '14px');
      }
      const facts = page.getByTestId('glance-facts');
      if (phone) await expect(facts).not.toContainText('3 members', { useInnerText: true });
      else await expect(facts).toContainText('3 members', { useInnerText: true });

      // Now: Temper's count first, then who works on what, one line each (D8); a phone lists two and counts the
      // rest, 768 px and wider list three (D84).
      await expect(nowWord(page)).toHaveText('Working');
      await expect(nowSentence(page)).toHaveText(/^3 of 3 members working\. Last activity \d+\u00a0s\u00a0ago\.$/);
      const working = page.getByTestId('glance-working');
      await expect(working).toHaveAttribute('aria-label', 'Working now');
      await expect(working.getByTestId('glance-working-row').locator('b')).toHaveText(phone ? ['lead', 'builder'] : ['lead', 'builder', 'checker']);
      await expect(working.getByTestId('glance-working-on')).toHaveText([
        '\u201cBuild the builder part and share it.\u201d',
        ...(phone ? [] : ['\u201cBuild the checker part and share it.\u201d']),
      ]);
      const rest = working.getByText('and 1 more working', { exact: true });
      if (phone) await expect(rest).toBeVisible();
      else await expect(rest).toHaveCount(0);

      // You and Spend: nothing needs you; the general hint stays off a phone (D9).
      await expect(youTitle(page)).toHaveText('Nothing needs you');
      const hint = page.getByTestId('glance-you').getByText('Questions and check-ins show up here.');
      if (phone) await expect(hint).toBeHidden();
      else await expect(hint).toBeVisible();
      const spend = page.getByTestId('glance-spend');
      await expect(spend).toContainText('$0.00');
      await expect(spend).toContainText('of $100');
      await expect(spend).toContainText('At $100 the team pauses and asks you.');

      // On a phone the whole band, Spend's line included, ends on the first screen (D9).
      if (phone) expect(await bandEnd(page), 'band end').toBeLessThanOrEqual(844);

      // Cards: role and leader on their own line under the name, no middot (D51).
      const cards = page.locator('[data-member]:visible');
      await expect(cards).toHaveCount(3);
      for (const card of await cards.all()) {
        const name = card.locator('h3 > span').first();
        const role = card.getByTestId('glance-role');
        await expect(role).not.toContainText('\u00b7');
        expect((await boxOf(role)).y, 'role under the name').toBeGreaterThanOrEqual((await boxOf(name)).y + (await boxOf(name)).height - 1);
      }
      await expect(page.locator('[data-member="lead"]:visible').getByTestId('glance-role')).toContainText('leader');

      // Latest: ages say "ago" in a 76 px column, 68 on a phone (D59).
      const ages = page.getByTestId('glance-latest-time');
      expect(await ages.count()).toBeGreaterThan(0);
      for (const age of await ages.all()) {
        await expect(age).toHaveText(/^\d.*\sago$/);
        expect((await boxOf(age)).width).toBeCloseTo(phone ? 68 : 76, 0);
      }

      // All activity: clock times to the second (D46).
      const times = await activity(page).locator('time').allTextContents();
      expect(times.length).toBeGreaterThan(0);
      for (const time of times) expect(time).toMatch(/^\d{2}:\d{2}:\d{2}$/);

      // The message box says when the chosen member gets it (D56).
      const composer = page.locator('#glance-message');
      await composer.getByLabel('To').selectOption('builder');
      await expect(composer.getByText('is working: it gets your message during this turn.')).toBeVisible();
      await expect(composer.locator('b', { hasText: 'builder' })).toBeVisible();

      await page.getByRole('main').evaluate((main) => main.scrollTo(0, 0));
      await expectAxeClean(page);
      await expectTargets(page);
      await expectNoSideways(page);
      await expectNoSmallText(page);
      if (phone) {
        await page.setViewportSize({ width: 320, height: 568 });
        await expect(working.getByTestId('glance-working-row')).toHaveCount(2);
        await expect(rest).toBeVisible();
        // D84: the band ends on a 844 px screen at the 320 reflow too.
        await page.getByRole('main').evaluate((main) => main.scrollTo(0, 0));
        expect(await bandEnd(page), 'band end at 320').toBeLessThanOrEqual(844);
        await expectTargets(page);
        await expectNoSideways(page);
        await expectNoSmallText(page);
      } else if (width === 1024) {
        // D84: at 1024x768 the band ends on the first screen.
        expect(await bandEnd(page), 'band end at 1024x768').toBeLessThanOrEqual(768);
      }
    });
  }
}

test("contract: a member's own long question names it, fits the phone band, and opens whole with Temper's note (D62, S1)", async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 390, height: 844 });
  const wait = (flowRaw('member_question').open_waits as Raw[])[0];
  const question = wait.question as string;
  expect(question.length).toBeGreaterThan(900);
  await open(page, 'member_question');

  // The band: the first line cut after a whole word at 90 (D62), from the member, never "owner".
  const title = /^Needs you: \u201c(.+)\u2026\u201d$/.exec(((await youTitle(page).textContent()) ?? '').trim());
  const shown = title?.[1] ?? '';
  expect(shown.length + 1, 'cut at 90').toBeLessThanOrEqual(90);
  expect(shown.length, 'cut late enough').toBeGreaterThan(54);
  expect(question.startsWith(shown), 'the question\'s own first words').toBe(true);
  expect(question.charAt(shown.length), 'after a whole word').toMatch(/[^\p{L}\p{N}]/u);
  const you = page.getByTestId('glance-you');
  await expect(you).not.toContainText(/\bowner\b/i);
  const from = page.getByTestId('glance-from-row');
  const asker = from.getByText('From builder', { exact: true });
  const answer = from.getByRole('button', { name: 'Answer' });
  // "From builder" shares its row with a 24 px Answer (D9).
  const a = await boxOf(answer);
  const f = await boxOf(asker);
  expect(Math.min(a.width, a.height), 'Answer target').toBeGreaterThanOrEqual(24);
  expect(Math.abs(a.y + a.height / 2 - (f.y + f.height / 2)), 'same row').toBeLessThan(a.height / 2);
  // The phone's compact band leaves Temper's note to the answer view (D9, D79), so it still ends on the first screen.
  await expect(page.getByTestId('glance-you-note')).toBeHidden();
  await expect(page.getByTestId('glance-question-note')).toHaveCount(0);
  expect(await bandEnd(page), 'band end').toBeLessThanOrEqual(844);
  // The others keep working while builder waits; its card and the activity rows keep 160 (D62).
  await expect(page.getByTestId('glance-working-row').locator('b')).toHaveText(['lead', 'checker']);
  expect((wait.words as string).length).toBeLessThanOrEqual(160);
  await expect(page.locator('[data-member="builder"]:visible').getByTestId('glance-on')).toHaveText(wait.words as string);
  await expect(activity(page)).toContainText('builder asked you:');

  // The answer view (D79): titled with Temper's header as sent ("builder asks"), the whole question,
  // then Temper's fixed note exactly as sent, right above the box.
  await answer.click();
  const view = page.getByTestId('glance-answer-view');
  await expect(view.getByTestId('glance-answer-header')).toHaveText(wait.header as string);
  await expect(view).toHaveAccessibleName(wait.header as string);
  await expect(view.getByTestId('glance-question')).toHaveText(question);
  expect((await boxOf(view.getByTestId('glance-answer-header'))).y, 'header first').toBeLessThan(
    (await boxOf(view.getByTestId('glance-question'))).y,
  );
  const note = view.getByTestId('glance-question-note');
  await expect(note).toHaveText(wait.note as string);
  const box = view.getByRole('textbox');
  await expect(box).toBeVisible();
  const noteId = await note.getAttribute('id');
  expect(noteId).toBeTruthy();
  expect((await box.getAttribute('aria-describedby'))?.split(' ')).toContain(noteId);
  expect((await boxOf(note)).y + (await boxOf(note)).height, 'note above the box').toBeLessThanOrEqual((await boxOf(box)).y);
  await expect(you).not.toContainText(/\bowner\b/i);
  await expectAxeClean(page);
  await expectTargets(page);
  await expectNoSideways(page);

  // While the question is open the message box says builder reads it after the answer (D56).
  const composer = page.locator('#glance-message');
  await composer.getByLabel('To').selectOption('builder');
  await expect(composer.getByText("is waiting for an answer: it gets your message once that's answered.")).toBeVisible();

  // At 320 px the whole question and the note still wrap inside the page (D50).
  await page.setViewportSize({ width: 320, height: 568 });
  await expectNoSideways(page);
  await expectTargets(page);
});

test('contract: in every state Temper can be in, the band ends on the first screen (390x844, 320 and 1024x768, D84), no text is under 14 px, and Stop is offered only while the team is live', async ({
  context,
}) => {
  test.setTimeout(240_000);
  const ends: Record<string, number> = {};
  for (const name of STATES) {
    const page = await context.newPage();
    await page.setViewportSize({ width: 390, height: 844 });
    await open(page, name);
    ends[name] = await bandEnd(page);
    expect(ends[name], `${name}: band end`).toBeLessThanOrEqual(844);
    // Stop by liveness, never from owner_actions (that is history).
    await expect(stopButton(page), `${name}: Stop`).toHaveCount(ENDED.has(phaseOf(name)) ? 0 : 1);
    // A phone band leaves Temper's note to the answer view (D9, D79).
    await expect(page.getByTestId('glance-question-note'), `${name}: no answer view`).toHaveCount(0);
    await expect(page.getByTestId('glance-you-note'), `${name}: no note in the phone band`).toBeHidden();
    await expectNoSmallText(page);
    // Reflow: nothing sideways at 320 px in any state; where the band ends is checked for all states below (D84).
    await page.setViewportSize({ width: 320, height: 568 });
    await expectNoSideways(page);
    ends[`${name} at 320`] = await bandEnd(page);
    // D84: at 1024x768 the band ends on the first screen; no text under 14 px, phone or wide.
    await page.setViewportSize({ width: 1024, height: 768 });
    ends[`${name} at 1024`] = await bandEnd(page);
    expect(ends[`${name} at 1024`], `${name}: band end at 1024x768`).toBeLessThanOrEqual(768);
    await expectNoSmallText(page);
    await page.close();
  }
  test.info().annotations.push({ type: 'band-ends', description: JSON.stringify(ends) });
  // D84: at the 320 reflow the band ends by 844 px too, except the states recorded for Design, which may not grow.
  const over = STATES.flatMap((name) => {
    const end = ends[`${name} at 320`];
    const recorded = D84_OVER_AT_320[name];
    return end <= 844 || (recorded !== undefined && end <= recorded + 2) ? [] : [`${name}: ${end}`];
  });
  expect(over, 'band ends past 844 px at 320 (D84)').toEqual([]);
});

test("contract: on a wide screen Temper's note sits under a member's own question, said once, and never under Temper's own waits (D79)", async ({
  context,
}) => {
  test.setTimeout(120_000);
  const page = await context.newPage();
  await page.setViewportSize({ width: 1024, height: 768 });
  const wait = (flowRaw('member_question').open_waits as Raw[])[0];
  await open(page, 'member_question');
  const note = page.getByTestId('glance-you-note');
  await expect(note).toHaveText(wait.note as string);
  // 14 px muted text, right under the question.
  expect(await note.evaluate((el) => getComputedStyle(el).fontSize)).toBe('14px');
  const title = await boxOf(youTitle(page));
  expect((await boxOf(note)).y, 'under the question').toBeGreaterThanOrEqual(title.y + title.height - 1);
  await expectAxeClean(page);
  // With the answer view open the note is said once, right above the box.
  await page.getByTestId('glance-from-row').getByRole('button', { name: 'Answer' }).click();
  await expect(note).toHaveCount(0);
  await expect(page.getByTestId('glance-answer-view').getByTestId('glance-question-note')).toHaveText(wait.note as string);
  await expect(page.getByText(wait.note as string, { exact: true })).toHaveCount(1);
  await page.close();
  // Temper's own waits carry no note, and none is made up.
  for (const name of ['failed', 'check_in', 'limit_asked', 'settings', 'stalled']) {
    expect((flowRaw(name).open_waits as Raw[]).every((w) => w.note === null), `${name}: note null`).toBe(true);
    const other = await context.newPage();
    await other.setViewportSize({ width: 1024, height: 768 });
    await open(other, name);
    await expect(youTitle(other)).toContainText('Needs you');
    await expect(other.getByTestId('glance-you-note'), `${name}: no note`).toHaveCount(0);
    await other.close();
  }
});

/** The band's cells: where each starts and how wide it is, and its top. */
function bandCells(page: Page, testId: string) {
  return page
    .getByTestId(testId)
    .locator('.glance-band-grid > *')
    .evaluateAll((els) =>
      els.map((el) => {
        const r = el.getBoundingClientRect();
        return { x: Math.round(r.left), width: Math.round(r.width), top: Math.round(r.top) };
      }),
    );
}

test("contract: before Temper's first reply the band keeps its loaded shape; a failed first read says so (SPEC 10, D7, D53, D70)", async ({
  page,
}) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 1024, height: 768 });
  const name = 'working';
  const run = flowRaw(name);
  await page.clock.setFixedTime(new Date(run.as_of as string));
  await serveState(page, name);
  // The first read waits until the loading view has been looked at.
  let release = () => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(/\/api\/team\/runs\/[^/?]+(\?|$)/, async (route) => {
    await held;
    await route.fallback();
  });
  await page.goto(`/app/team/runs/${run.execution_id as string}`);
  await expect(page.getByTestId('glance-loading')).toBeVisible();
  // One page heading, for screen readers only; nothing about the kind of run yet (D7, D53).
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Team run');
  await expect(page.getByRole('heading', { level: 1 })).toHaveClass(/sr-only/);
  await expect(page.getByRole('navigation', { name: 'Breadcrumb' }).getByRole('link')).toHaveText(['Team', 'Projects']);
  const skeleton = page.getByTestId('glance-band-loading');
  await expect(skeleton).toHaveAttribute('aria-busy', 'true');
  await expect(skeleton.getByRole('heading', { level: 3 })).toHaveText(['Now', 'You', 'Spend']);
  await expect(page.getByRole('status').filter({ hasText: 'Loading the project from Temper\u2026' })).toBeVisible();
  await expectAxeClean(page);
  const loadingCells = await bandCells(page, 'glance-band-loading');
  release();
  await expect(page.getByTestId('glance-page')).toBeVisible();
  const loadedCells = await bandCells(page, 'glance-band');
  // D70: at 1024 Now runs across the top with You and Spend side by side under it, loading and loaded alike.
  expect(loadingCells.map(({ x, width }) => ({ x, width }))).toEqual(loadedCells.map(({ x, width }) => ({ x, width })));
  for (const cells of [loadingCells, loadedCells]) {
    expect(cells[1].top).toBeGreaterThan(cells[0].top);
    expect(cells[2].top).toBe(cells[1].top);
    expect(cells[0].width).toBeGreaterThan(cells[1].width + cells[2].width - 2);
  }

  // The first read fails: the page says so, changes nothing, and offers Try again and the way back.
  await page.unrouteAll({ behavior: 'ignoreErrors' });
  const failed = await serveState(page, name);
  failed.state.down = true;
  await page.goto(`/app/team/runs/${run.execution_id as string}`);
  await expect(page.getByTestId('glance-read-failed')).toBeVisible();
  await expect(page.getByRole('heading', { level: 1 })).toHaveText("This project couldn't be read");
  const alert = page.getByRole('alert');
  await expect(alert).toContainText("Temper didn't answer");
  await expect(alert).toContainText(
    'The page asked Temper for this project and got no answer. Nothing was changed. It may be restarting.',
  );
  await expect(alert.getByRole('link', { name: 'Back to Projects' })).toHaveAttribute('href', /\/team$/);
  await expectAxeClean(page);
  await expectTargets(page);
  failed.state.down = false;
  await alert.getByRole('button', { name: 'Try again' }).click();
  await expect(page.getByTestId('glance-page')).toBeVisible();
});

test("contract: paths and quoted words break inside the page at 320 px, never sideways (D50)", async ({ page }) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 320, height: 568 });
  const longPath = 'frontend/src/components/team/glance/averyveryverylongfoldernamewithnobreaks/StatusBandWordsAndStates.tsx';
  await open(page, 'working', {
    run: (run) => {
      for (const m of run.members as Raw[]) if (m.on) (m.on as Raw).text = `Fix ${longPath} and share it.`;
    },
    // All activity reads the events feed, the page's one history (home decision 3).
    feed: (feed) => {
      for (const e of feed.events) if (e.kind === 'message' && e.message_kind === 'work_request') e.text = `Fix ${longPath} and share it.`;
    },
  });
  await expect(page.locator('[data-member="builder"]:visible').getByTestId('glance-on')).toContainText(longPath);
  await expect(activity(page)).toContainText(longPath);
  await expectNoSideways(page);
  await expectTargets(page);
});

test("contract: a usage check that can't be read names the next check, promises no resume, and asks nothing (D65)", async ({ page }) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, 'limit_start_check');
  await expect(nowWord(page)).toHaveText('Usage limit');
  await expect(nowSentence(page)).toHaveText(
    /^Usage cannot be checked; the team keeps waiting\. Next allowance check at [^.]+\. No usable reset time\.$/,
  );
  await expect(page.getByTestId('glance-band')).not.toContainText(/resume|carries on|starts again/i);
  await expect(youTitle(page)).toHaveText('Nothing needs you');
  await expect(page.getByRole('button', { name: /restart/i })).toHaveCount(0);
  // Latest's limit row names the check while the team is in its limit.
  await expect(page.getByTestId('glance-latest')).toContainText(/Usage limit: next allowance check at [^;]+; no usable reset time/);
  await expect(stopButton(page)).toHaveCount(1);
  await expectAxeClean(page);
});

test('contract: an ended run says how it ended once, spends "in all", and offers no Stop and no dead link (D41, D54, D67)', async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  const ended = STATES.filter((name) => ENDED.has(phaseOf(name)));
  expect(ended.length).toBeGreaterThanOrEqual(4);
  for (const name of ended) {
    await page.unrouteAll({ behavior: 'ignoreErrors' });
    await open(page, name);
    await expect(page.getByTestId('glance-spend'), name).toContainText(/Spent in all\. \d+ check-ins?, none to come/);
    await expect(stopButton(page), name).toHaveCount(0);
    await expect(page.locator('#glance-message'), name).toHaveCount(0);
    // D54: no version view is reachable from this page, so no "See the changes"; never "#".
    await expect(page.getByRole('link', { name: /see the changes/i }), name).toHaveCount(0);
    await expect(page.locator('main a[href="#"]'), name).toHaveCount(0);
    // D41: the label, then the reason, never the label twice.
    const rows = [
      ...(await page.getByTestId('glance-latest').locator('li').allInnerTexts()),
      ...(await activity(page).locator('li').allInnerTexts()),
    ];
    for (const row of rows) expect(row, name).not.toMatch(/(Stopped|Failed|Cancelled|Ended: done): (stopped|failed|cancelled|ended)\b/i);
  }
  await expectAxeClean(page);
});

test('contract: when Temper stops answering, Now says "Last seen" and You says when something last needed you (D48, D64)', async ({ page }) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 390, height: 844 });
  const { state } = await open(page, 'working');
  state.down = true;
  await expect(page.getByText(/^Temper hasn.t answered for /).first()).toBeVisible({ timeout: 15_000 });
  await expect(nowWord(page)).toHaveText('Last seen: Working');
  await expect(nowSentence(page)).toHaveText('3 of 3 members working.');
  const working = page.getByTestId('glance-working');
  await expect(working).toHaveAttribute('aria-label', 'Working when last seen');
  // D84: with the stale note on a phone, Now lists one member and counts the rest.
  await expect(working.getByTestId('glance-working-row').locator('b')).toHaveText(['lead']);
  await expect(working.getByText('and 2 more working', { exact: true })).toBeVisible();
  expect(await bandEnd(page), 'band end').toBeLessThanOrEqual(844);
  await expect(youTitle(page)).toHaveText(/^Nothing needed you .+ ago$/);
  await expect(page.getByTestId('glance-you')).toContainText('Questions show up once Temper answers.');
  await expectAxeClean(page);
  await expectTargets(page);
  await expectNoSideways(page);
});
