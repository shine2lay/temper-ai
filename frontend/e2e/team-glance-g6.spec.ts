/**
 * The free-flowing Team page on Temper's real G6 runs: twelve runs its real
 * engine made without a model (e2e/fixtures/team/flow/real-g6, byte for byte
 * as FLOW/G6-INPUTS.sha256 lists them; teamGlanceG6.test.ts checks the
 * hashes). Every /api/team answer comes from them, so no Temper is needed and
 * nothing is written: the owner's answers are kept, not sent.
 *
 * One journey per run, as the owner's test rule asks (bp-be8d76b9): Now, You,
 * Spend, the cards, Latest and All activity say what the binding rows say
 * (Frontend's g6/G6-TRUTH.md: SPEC, DELTA, home's decisions, TEMPER-D86), and
 * no answer word Temper records shows raw. Each journey also checks axe,
 * 24 px targets, no text under 14 px, no sideways scroll and the band on the
 * first screen (D84), in both themes at 390x844, 1024x768 and 1440x900. The
 * three runs that ask the owner something new (a member's question, a
 * verified weekly limit, a settings question asked again) are answered, and
 * each answer goes to that run's open wait.
 *
 * Shots for review with G6_SHOTS=<folder>: <run>-<theme>-<width>.png (the
 * whole page), -first.png (the first screen) and -answer.png (the You cell
 * as the owner answers).
 */
import { mkdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { expect, test, type Locator, type Page } from '@playwright/test';
import {
  expectAxeClean,
  expectTargets,
  glanceFontsSettled,
  nothingSent,
  serveActions,
  serveTeam,
  shoot,
  withBody,
  type Fixture,
} from './team-helpers';

type Raw = Record<string, unknown>;
type Feed = { events: Raw[]; as_of: string };

const DIR = path.join(process.cwd(), 'e2e/fixtures/team/flow/real-g6');
const SHOTS = process.env.G6_SHOTS;
/** The owner's time zone: the page tells clock times in the viewer's own zone (SPEC's Now table). */
const ZONE = 'America/Los_Angeles';
test.use({ timezoneId: ZONE });

const RUNS = [
  'member_question',
  'retry',
  'interrupted',
  'interrupted_no_end',
  'limit_waiting',
  'limit_unavailable',
  'limit_ready',
  'limit_ended',
  'restart_deferred',
  'conflict',
  'settings_late',
  'invalid',
] as const;
type Run = (typeof RUNS)[number];

/** A G6 reply as Temper sent it, as a fresh copy. */
function g6(name: Run, feed = false): Raw {
  return JSON.parse(readFileSync(path.join(DIR, `${name}${feed ? '-events' : ''}.json`), 'utf8')) as Raw;
}

/** "3:00 PM" in the viewer's zone, as the page says a clock time. */
const clock = (iso: string) =>
  new Date(iso).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true, timeZone: ZONE });
const phaseOf = (name: Run) => g6(name).phase as Raw;
const nextCheck = (name: Run) => clock(phaseOf(name).resumes_at as string);
const firstWait = (name: Run) => (g6(name).open_waits as Raw[])[0];
const youWords = (name: Run) => (g6(name).you as { first: { words: string } }).first.words;
/** What the run has spent, as the page says money: "$65.00". */
const spent = (name: Run) => `$${(g6(name).spend as { cost_usd: number }).cost_usd.toFixed(2)}`;
/** The words of the newest question the feed shows Temper opening (shorter than the open wait's question). */
const lastAsk = (name: Run) =>
  ((g6(name, true) as unknown as Feed).events.filter((e) => e.kind === 'wait_opened').at(-1) as { words: string }).words;

/** D86's fixed marks (g6/TEMPER-D86.md, "Words (Design)"). */
const NOT_APPLIED_INVALID = 'Not applied: the answer didn\u2019t match any of the choices. Temper asked again.';
const NOT_APPLIED_RESTART = 'Not applied: Temper couldn\u2019t confirm the usage limit has reset.';

/** What one run must show: the binding rows of g6/G6-TRUTH.md. */
interface Truth {
  phase: string;
  /** Now: the word and the sentence. */
  now: [string, string];
  /** The Team now count line (SPEC 5, D18). */
  team: string;
  /** You: the title, and the line under it when there is one. */
  you: string;
  youLine?: string;
  /** Spend: words the cell holds. */
  spend: string[];
  /** Cards by member: the chip, the On line, and other words the card holds. */
  cards: Record<string, { chip: string | RegExp; on?: string; has?: string }>;
  /** Latest: the newest row, and rows it holds. */
  latestFirst: string;
  latest?: string[];
  /** All activity: rows it holds. */
  activity: string[];
  /** The answers Temper offers in the You cell. */
  answers?: string[];
  /** Words this run never shows. */
  never?: RegExp;
}

const LIMIT_NEVER = /reset at|carries on at/i;
const STOP_LINE = 'Stop stays at the top if you want to end it.';
// D90: sentence case, "new project".
const ENDED_LINE = 'Read what it made below, or start a new project.';

const TRUTH: Record<Run, Truth> = {
  member_question: {
    phase: 'working',
    now: ['Working', '0 of 3 members working. Last activity 0 s ago.'],
    team: '1 ready \u00b7 1 idle \u00b7 1 needs you',
    you: 'Needs you: \u201cMay I rename the docs folder to guide? Three links in the README would change with it\u2026\u201d',
    spend: [spent('member_question'), 'At $100 the team pauses and asks you.'],
    cards: {
      builder: { chip: 'Needs you', on: youWords('member_question') },
      // D95: the waiting messages move from the chip to the On line.
      checker: { chip: 'Ready \u00b7 waiting for a free turn', on: '1 message' },
      lead: { chip: /^Idle \u00b7 / },
    },
    latestFirst: 'You answered: a reply',
    latest: ['checker asked you: \u201cShould the checks also cover the example scripts?\u201d'],
    activity: [
      // D108: your words to checker right after your answer to its own question answer it.
      'You answered checker: \u201cyes\u201d',
      'You answered: a reply',
      'checker asked you: \u201cShould the checks also cover the example scripts?\u201d',
    ],
  },
  retry: {
    phase: 'working',
    now: ['Working', '1 of 3 members working. Last activity 0 s ago.'],
    team: '1 working \u00b7 2 idle',
    you: 'Nothing needs you',
    spend: [spent('retry')],
    cards: {
      builder: { chip: 'Working on a retry \u00b7 0 s' },
      lead: { chip: /^Idle \u00b7 /, on: 'Ended its turn without a note' },
      checker: { chip: /^Idle \u00b7 / },
    },
    latestFirst: 'lead sent work to 2 members',
    activity: [
      'builder started turn 2 (Temper\u2019s retry of turn 1)',
      'builder ended turn 1: failed',
      'checker\u2019s turn 1 ended at its tool-call limit.',
      'lead went idle without a note',
      'lead ended turn 1: completed (no tool call)',
    ],
  },
  interrupted: {
    phase: 'interrupted',
    now: ['Interrupted', 'The run ended without the team ending.'],
    team: '3 members \u00b7 all ended',
    you: 'Nothing needs you',
    youLine: ENDED_LINE,
    spend: ['$105.00', 'Spent in all. 0 check-ins, none to come \u00b7 1 shared version.'],
    // D105: an ended run's cards read "Ended"; Temper's reason ends All activity.
    cards: { lead: { chip: 'Ended' }, builder: { chip: 'Ended' }, checker: { chip: 'Ended' } },
    latestFirst: 'builder shared v1',
    activity: ['Interrupted: the run ended (interrupted) without the team ending', 'builder shared v1'],
  },
  interrupted_no_end: {
    phase: 'interrupted',
    // D105: Temper recorded no end, so Now gives the newest time it did record.
    now: ['Interrupted', 'Last activity 8:40 PM. Temper didn\u2019t record when it ended.'],
    team: '3 members \u00b7 all ended',
    you: 'Nothing needs you',
    youLine: ENDED_LINE,
    spend: ['$105.00', 'Spent in all. 0 check-ins, none to come \u00b7 1 shared version.'],
    cards: { lead: { chip: 'Ended' }, builder: { chip: 'Ended' }, checker: { chip: 'Ended' } },
    latestFirst: 'builder shared v1',
    activity: ['Interrupted: the run ended (interrupted) without the team ending', 'builder shared v1'],
  },
  limit_waiting: {
    phase: 'limit',
    now: [
      'Usage limit',
      `The account hit its usage limit; it carries on only after fresh usage shows room. Next allowance check at ${nextCheck('limit_waiting')}.`,
    ],
    team: '1 paused \u00b7 2 idle',
    you: 'Nothing needs you',
    youLine: STOP_LINE,
    spend: [spent('limit_waiting')],
    cards: { builder: { chip: 'Paused: usage limit' }, lead: { chip: /^Idle/ }, checker: { chip: /^Idle/ } },
    latestFirst: `Usage limit: next allowance check at ${nextCheck('limit_waiting')}`,
    activity: [`Usage limit: next allowance check at ${nextCheck('limit_waiting')}`],
    never: LIMIT_NEVER,
  },
  limit_unavailable: {
    phase: 'limit',
    now: [
      'Usage limit',
      `Usage cannot be checked; the team keeps waiting. Next allowance check at ${nextCheck('limit_unavailable')}. No usable reset time.`,
    ],
    team: '1 paused \u00b7 2 idle',
    you: 'Nothing needs you',
    youLine: STOP_LINE,
    spend: [spent('limit_unavailable')],
    cards: { builder: { chip: 'Paused: usage limit' } },
    latestFirst: `Usage limit: next allowance check at ${nextCheck('limit_unavailable')}; no usable reset time`,
    activity: [`Usage limit: next allowance check at ${nextCheck('limit_unavailable')}; no usable reset time`],
    never: LIMIT_NEVER,
  },
  limit_ready: {
    phase: 'limit',
    // D89: the asked limit has its own word; D112: no one works while it asks.
    now: ['Usage limit: waiting for you', 'No one is working until you answer.'],
    team: '1 paused \u00b7 2 idle',
    // D94: Temper's own words, not quoted.
    you: `Needs you: ${youWords('limit_ready')}`,
    spend: [spent('limit_ready')],
    cards: { builder: { chip: 'Paused: usage limit' } },
    latestFirst: 'Usage limit',
    activity: ['Usage limit'],
    answers: ['Restart', 'Stop project'],
    // A verified limit names no pending check anywhere (D31).
    never: /allowance check at|reset at|carries on at/i,
  },
  limit_ended: {
    phase: 'working',
    now: ['Working', '0 of 3 members working. Last activity 0 s ago.'],
    team: '1 ready \u00b7 2 idle',
    you: 'Nothing needs you',
    spend: [spent('limit_ended')],
    cards: { builder: { chip: 'Ready \u00b7 waiting for a free turn', on: '1 message' } },
    latestFirst: 'The usage limit is over. The team carried on at 8:40 PM.',
    latest: ['Usage limit'],
    activity: ['The usage limit is over. The team carried on at 8:40 PM.', 'Usage limit'],
    never: LIMIT_NEVER,
  },
  restart_deferred: {
    phase: 'limit',
    now: [
      'Usage limit',
      // D104: Temper's next check is 3 days on (Fri Oct 9 to Mon Oct 12 in Los Angeles), so it gets its day.
      `The account hit its weekly limit; the team waits, then asks you before restarting. Next allowance check Mon at ${nextCheck('restart_deferred')}.`,
    ],
    team: '1 paused \u00b7 2 idle',
    you: 'Nothing needs you',
    youLine: STOP_LINE,
    spend: [spent('restart_deferred')],
    cards: { builder: { chip: 'Paused: usage limit' } },
    latestFirst: `Usage limit: next allowance check Mon at ${nextCheck('restart_deferred')}`,
    latest: [`You answered: restart. ${NOT_APPLIED_RESTART}`],
    activity: [`You answered: restart. ${NOT_APPLIED_RESTART}`],
    never: LIMIT_NEVER,
  },
  conflict: {
    phase: 'working',
    now: ['Working', '0 of 3 members working. Last activity 0 s ago.'],
    team: '1 ready \u00b7 2 idle',
    you: 'Nothing needs you',
    spend: [spent('conflict')],
    cards: { checker: { chip: 'Ready \u00b7 waiting for a free turn', on: '1 message', has: '1 file in conflict' } },
    latestFirst: 'checker has 1 file in conflict after a sync',
    activity: [
      // D107: Temper's why is only the verb.
      'checker\u2019s version wasn\u2019t shared. Temper gave no reason.',
      'Temper told checker: \u201cNot shared: these files still hold git\'s conflict markers: part.md. Remove the markers and share again.\u201d',
      'checker has 1 file in conflict after a sync',
    ],
  },
  settings_late: {
    phase: 'settings',
    now: ['Settings changed', 'No one is working until you answer.'],
    team: '3 idle',
    you: 'Needs you: go on or stop?',
    spend: [spent('settings_late')],
    cards: { lead: { chip: /^Idle/ } },
    // The feed's own words for the question Temper asked again; the You cell shows the open wait's whole question.
    latestFirst: `Temper asked you: \u201c${lastAsk('settings_late')}\u201d`,
    latest: ['You answered: go on'],
    activity: [`Temper asked you: \u201c${lastAsk('settings_late')}\u201d`, 'You answered: go on'],
    answers: ['Go on', 'Stop project'],
    // D86: without `applied` the go on is an ordinary one.
    never: /Not applied/,
  },
  invalid: {
    phase: 'check_in',
    now: ['Check-in at $105.00', 'No one is working until you answer.'],
    team: '3 idle',
    you: 'Needs you: carry on?',
    spend: [spent('invalid'), 'If you continue, the next check-in is at $205.'],
    cards: { lead: { chip: /^Idle/ } },
    latestFirst: `You answered. ${NOT_APPLIED_INVALID}`,
    activity: [`You answered. ${NOT_APPLIED_INVALID}`],
    answers: ['Continue', 'Guide\u2026', 'Stop project'],
  },
};

/**
 * Temper for one page, at one run: the run reads as Temper sent it; the feed
 * answers what is past `after`, up to the run's own events_cursor. The
 * answers are kept with the wait each went to, and answered with `answer`.
 */
async function open(page: Page, name: Run, answer: Fixture[] = []) {
  const run = g6(name);
  await page.clock.setFixedTime(new Date(run.as_of as string));
  const sent = nothingSent();
  await serveTeam(page, { run: () => ({ route: '', status: 200, body: g6(name) }) });
  await serveActions(page, sent, { answer });
  // The wait each answer went to, kept before serveActions answers it.
  const answered: string[] = [];
  await page.route('**/api/team/runs/*/waits/*/answer', async (route) => {
    answered.push(new URL(route.request().url()).pathname);
    await route.fallback();
  });
  // Set up after serveTeam, so it answers the feed first.
  await page.route(/\/api\/team\/runs\/[^/]+\/events(\?|$)/, async (route) => {
    const url = new URL(route.request().url());
    const after = Number(url.searchParams.get('after') ?? '0');
    const limit = Number(url.searchParams.get('limit') ?? '200');
    const upTo = g6(name).events_cursor as number;
    const feed = g6(name, true) as unknown as Feed;
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
  await page.goto(`/app/team/runs/${run.execution_id as string}`);
  await expect(page.getByTestId('glance-page')).toBeVisible();
  await expect(page.getByTestId('glance-just-sent')).not.toContainText('Reading the team');
  await glanceFontsSettled(page);
  return { sent, answered, id: run.execution_id as string };
}

/** Temper's 200 for an answer to `wait`, in the answer route's own shape. */
function approved(name: Run, answer: string, text: string | null): Fixture {
  const wait = firstWait(name);
  return withBody(answer === 'go on' ? 'answer-200-settings-go-on' : 'answer-200-guide', (b) => ({
    ...b,
    wait_id: wait.wait_id,
    answer,
    text,
    at: g6(name).as_of,
  }));
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

/** D84: the status band ends on the first screen (844 px on a 390x844 phone, 768 at 1024x768). */
const BAND_MAX: Record<number, number> = { 390: 844, 1024: 768 };

async function expectSound(page: Page, width: number) {
  await expectAxeClean(page);
  await expectTargets(page);
  await expectNoSmallText(page);
  await expectNoSideways(page);
  const max = BAND_MAX[width];
  if (max) {
    const end = await page.getByTestId('glance-band').evaluate((band) => band.getBoundingClientRect().bottom);
    expect(end, 'the band ends on the first screen (D84)').toBeLessThanOrEqual(max);
  }
}

/** Every answer word Temper records, as the page must never show it. */
const RAW_ANSWER = /\b(given|invalid|restart_deferred)\b/;

const SIZES = [
  { width: 390, height: 844 },
  { width: 1024, height: 768 },
  { width: 1440, height: 900 },
] as const;

async function shots(page: Page, name: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await shoot(page, name, SHOTS);
  await page.screenshot({ path: path.join(SHOTS, `${name}-first.png`) });
}

async function shotOf(you: Locator, name: string) {
  if (SHOTS) await you.screenshot({ path: path.join(SHOTS, `${name}-answer.png`) });
}

for (const name of RUNS) {
  for (const theme of ['dark', 'light'] as const) {
    for (const { width, height } of SIZES) {
      test(`G6 ${name}: Temper's real run reads as the binding rows say, ${theme}, ${width}x${height}`, async ({ page }) => {
        test.setTimeout(90_000);
        const wide = width >= 768;
        const truth = TRUTH[name];
        const raw = g6(name);
        const ended = truth.phase === 'interrupted';
        await page.setViewportSize({ width, height });
        await page.addInitScript((t) => localStorage.setItem('temper_theme', t), theme);
        const answer =
          name === 'member_question'
            ? [approved(name, 'reply', 'Yes, rename it and change the three links with it.')]
            : name === 'limit_ready'
              ? [approved(name, 'restart', null)]
              : name === 'settings_late'
                ? [approved(name, 'go on', null)]
                : [];
        const { sent, answered, id } = await open(page, name, answer);
        const main = page.locator('main');

        // Now, You, Spend.
        await expect(page.getByTestId('glance-page')).toHaveAttribute('data-phase', truth.phase);
        await expect.soft(page.getByTestId('glance-now-word')).toHaveText(truth.now[0]);
        await expect.soft(page.getByTestId('glance-now-sentence')).toHaveText(truth.now[1]);
        await expect.soft(page.getByTestId('glance-team-count')).toHaveText(truth.team);
        const you = page.getByTestId('glance-you');
        await expect.soft(page.getByTestId('glance-you-title')).toHaveText(truth.you);
        if (truth.youLine) await expect.soft(you).toContainText(truth.youLine);
        for (const words of truth.spend) await expect.soft(page.getByTestId('glance-spend')).toContainText(words);

        // The cards, on the map or in the phone's list.
        const members = page.getByTestId(wide ? 'glance-map' : 'glance-list');
        for (const [member, card] of Object.entries(truth.cards)) {
          const box = members.locator(`[data-member="${member}"]`);
          await expect.soft(box.getByTestId('glance-chip'), `${member}: chip`).toHaveText(card.chip);
          if (card.on) await expect.soft(box.getByTestId('glance-on'), `${member}: on`).toContainText(card.on);
          if (card.has) await expect.soft(box, member).toContainText(card.has);
        }

        // Latest, its link with events_total (D14), and All activity.
        const latest = page.getByTestId('glance-latest');
        await expect.soft(latest.locator('li').first()).toContainText(truth.latestFirst);
        for (const row of truth.latest ?? []) await expect.soft(latest).toContainText(row);
        await expect
          .soft(page.getByRole('link', { name: `All activity (${raw.events_total as number} entries)` }))
          .toBeVisible();
        const activity = page.getByRole('region', { name: 'All activity' });
        for (const row of truth.activity) await expect.soft(activity).toContainText(row);

        // No answer word Temper records shows raw; nothing this run must not say.
        await expect.soft(main).not.toContainText(RAW_ANSWER);
        if (truth.never) await expect.soft(main).not.toContainText(truth.never);

        // Stop and Animate only while the team is live (D24, D47); an ended run's time is frozen at its end (G5).
        // D92: You's stop reads "Stop project" too, so count the header's.
        await expect.soft(main.locator('header').getByRole('button', { name: 'Stop project' })).toHaveCount(ended ? 0 : 1);
        await expect.soft(page.getByRole('switch', { name: 'Animate messages' })).toHaveCount(ended ? 0 : 1);
        const facts = page.getByTestId('glance-facts');
        if (name === 'interrupted') await expect.soft(facts).toContainText('ran 45 s');
        if (name === 'interrupted_no_end') {
          // Temper has no end time: no length at all, never "0 s" and never a running clock.
          await expect.soft(facts).not.toContainText(/\bran\b|\brunning\b|\b0 s\b/);
        }

        // Temper's own waits are answered in the You cell; a member's question opens the answer view (D79).
        const answers = page.getByTestId('glance-answers').getByRole('button');
        if (truth.answers) await expect.soft(answers).toHaveText(truth.answers);
        else if (name !== 'member_question') await expect.soft(page.getByTestId('glance-answers')).toHaveCount(0);
        if (name === 'settings_late' || name === 'limit_ready') {
          // Temper's question, under the title when the title doesn't say it.
          await expect.soft(you).toContainText(firstWait(name).question as string);
        }
        if (name === 'member_question') {
          await expect.soft(page.getByTestId('glance-from-row')).toContainText('From builder');
          // D79: Temper's note under the question in the wide band; the phone leaves it to the answer view.
          if (wide) await expect.soft(page.getByTestId('glance-you-note')).toHaveText(firstWait(name).note as string);
          else await expect.soft(page.getByTestId('glance-you-note')).toBeHidden();
        }
        await expectSound(page, width);
        await shots(page, `${name}-${theme}-${width}`);

        if (name === 'member_question') {
          const wait = firstWait(name);
          await page.getByTestId('glance-from-row').getByRole('button', { name: 'Answer' }).click();
          const view = page.getByTestId('glance-answer-view');
          // Titled with Temper's header, the whole question, then the note right above the box (D62, D79).
          await expect(view.getByTestId('glance-answer-header')).toHaveText('builder asks');
          await expect(view.getByTestId('glance-question')).toHaveText(wait.question as string);
          await expect(view.getByTestId('glance-question-note')).toHaveText(wait.note as string);
          const box = view.getByRole('textbox');
          await expect(box).toBeFocused();
          const [question, note, field] = await Promise.all(
            [view.getByTestId('glance-question'), view.getByTestId('glance-question-note'), box].map(async (l) => {
              const b = await l.boundingBox();
              if (!b) throw new Error('not drawn');
              return b;
            }),
          );
          expect(note.y, 'the note under the question').toBeGreaterThanOrEqual(question.y + question.height - 1);
          expect(field.y, 'the box under the note').toBeGreaterThanOrEqual(note.y + note.height - 1);
          await expect(page.getByText(wait.note as string, { exact: true })).toHaveCount(1);
          await expectSound(page, 0);
          await shotOf(you, `${name}-${theme}-${width}`);
          await box.fill('Yes, rename it and change the three links with it.');
          await view.getByRole('button', { name: 'Send reply' }).click();
          await expect.poll(() => sent.answers.length).toBe(1);
          // The page sends `reply`, as offered; Temper records it as `given` (api-fields:260).
          expect(sent.answers[0]).toMatchObject({ answer: 'reply', text: 'Yes, rename it and change the three links with it.' });
          expect(answered).toEqual([`/api/team/runs/${id}/waits/${wait.wait_id as string}/answer`]);
        }
        if (name === 'limit_ready' || name === 'settings_late') {
          const wait = firstWait(name);
          await shotOf(you, `${name}-${theme}-${width}`);
          await answers.getByText(name === 'limit_ready' ? 'Restart' : 'Go on', { exact: true }).click();
          await expect.poll(() => sent.answers.length).toBe(1);
          expect(sent.answers[0]).toMatchObject({ answer: name === 'limit_ready' ? 'restart' : 'go on' });
          expect(sent.answers[0].text ?? '').toBe('');
          expect(answered).toEqual([`/api/team/runs/${id}/waits/${wait.wait_id as string}/answer`]);
          expect(sent.cancels).toHaveLength(0);
        }
        if (name === 'invalid') await shotOf(you, `${name}-${theme}-${width}`);
      });
    }
  }
}
