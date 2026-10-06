/**
 * The Team page in a real browser: the shared parts, the run view (reading,
 * answering Temper, Stop run, ended runs) and the run page's way in.
 *
 * Most tests serve the /api/team routes from the fixtures the routes really
 * answered (e2e/fixtures/team, made by scripts/capture_team_fixtures.py), so
 * they run on a server with the Team switch off, as CI's is, and start no
 * team trial and call no model. Each runs in both themes at 1024 and 1440 px
 * wide and must pass axe (WCAG 2.2 A/AA and best practice) with nothing
 * found. The last group runs with no mocks at all and checks that with the
 * switch off nothing of the Team shows.
 *
 * Screenshots for reading against Design's boards go to TEAM_SHOTS when set.
 */
import { expect, test } from '@playwright/test';
import { startSmokeRun } from './helpers';
import {
  answers,
  asRun,
  card,
  expectAxeClean,
  expectTargets,
  fixture,
  openRun,
  pick,
  refusalText,
  result,
  RUN_ID,
  runReads,
  serveTeam,
  shoot,
} from './team-helpers';

/** The run view states that need no answer from the owner, and what each must show. */
const RUN_STATES: { fixture: string; shows: RegExp | string }[] = [
  { fixture: 'run-starting', shows: 'Starting: no member turn has begun yet' },
  { fixture: 'run-running', shows: 'Who did what' },
  { fixture: 'run-interrupted', shows: 'Interrupted: resume it from the run page' },
];

/**
 * Each kind of question Temper asks the owner: the card's title, the
 * answers in Temper's order, and a line only that kind shows.
 */
const WAITS: { fixture: string; title: string; answers: string[]; shows: RegExp | string }[] = [
  { fixture: 'run-paused', title: 'Paused after round 1', answers: ['continue', 'guide', 'stop'], shows: 'Waiting since' },
  {
    fixture: 'run-quiet',
    title: 'Quiet: the team has nothing left to do',
    answers: ['nudge', 'stop'],
    shows: /Not the run list.s .quiet. mark/,
  },
  {
    fixture: 'run-member-waiting',
    title: "lead's turn 1 was cut off",
    answers: ['accept', 'retry', 'stop'],
    shows: /Why:\s*Pi stopped before it settled/,
  },
  {
    fixture: 'run-member-waiting-usage-limit',
    title: "lead's turn 1 was cut off by a usage limit",
    answers: ['accept', 'retry', 'stop'],
    shows: /Why:\s*usage limit: /,
  },
  { fixture: 'run-member-waiting-failed', title: "lead's turn 1 failed", answers: ['retry', 'stop'], shows: /^lead's turn 1 failed: / },
  {
    fixture: 'run-member-waiting-asked-again',
    title: "lead's turn 1 was cut off",
    answers: ['accept', 'retry', 'stop'],
    shows: 'Asked again (1 time)',
  },
  { fixture: 'run-member-waiting-question', title: 'maker asks you', answers: ['reply'], shows: 'Waiting since' },
  {
    fixture: 'run-paused-two-waits',
    title: 'Paused after round 1',
    answers: ['continue', 'guide', 'stop'],
    shows: 'Temper asks one question at a time. This one comes next, after you answer:',
  },
  { fixture: 'run-paused-held-message', title: 'Paused after round 1', answers: ['continue', 'guide', 'stop'], shows: 'Waiting since' },
];

/** Each ended run, the outcome card's title, and the lines it must show. */
const ENDED: { fixture: string; title: string; shows: (RegExp | string)[] }[] = [
  {
    fixture: 'run-done',
    title: "Done: the leader's version was approved",
    shows: ["lead's summary", 'No objections', /team\/\w+ in notes-app, at the approved commit/, 'Files in the approved version (2)'],
  },
  { fixture: 'run-done-objections', title: "Done: the leader's version was approved", shows: ['Objections', /round \d+:/] },
  { fixture: 'run-done-after-guide', title: "Done: the leader's version was approved", shows: ["lead's summary"] },
  {
    fixture: 'run-done-branch-not-made',
    title: "Done: the leader's version was approved",
    shows: ["branch not made: exists · the approved commit stays fetchable from Temper's kept copy."],
  },
  {
    fixture: 'run-done-no-project',
    title: "Done: the leader's version was approved",
    shows: ['No branch: this trial started from an empty project. Getting its files out comes later.'],
  },
  {
    fixture: 'run-stopped',
    title: 'Stopped',
    shows: [
      'stopped at the pause after round 1',
      /Stopped by\s*You\s*from the dashboard/,
      'We have what we need for now.',
    ],
  },
  {
    fixture: 'run-stopped-quiet',
    title: 'Stopped',
    shows: ['stopped when the team had nothing left to do'],
  },
  {
    fixture: 'run-stopped-recovery',
    title: 'Stopped',
    shows: [
      'lead turn 1 did not finish and the team was stopped',
      "Why the run list says failed: Temper records a team stopped at a member's failed or unfinished turn as failed. Here the stop was a choice, not a crash: who stopped it and why are on the left.",
    ],
  },
  {
    fixture: 'run-cancelled',
    title: 'Stopped',
    shows: [
      'the run was cancelled',
      /Stopped by\s*You\s*from the dashboard/,
      "Enough for today; I'll pick this up tomorrow.",
    ],
  },
  { fixture: 'run-cancelled-by-ci', title: 'Stopped', shows: [/Stopped by\s*temper-ci\s*through the API/] },
  { fixture: 'run-cancelled-by-unknown', title: 'Stopped', shows: [/Stopped by\s*an unknown caller\s*from an unknown place/] },
  { fixture: 'run-stopped-from-chat', title: 'Stopped', shows: [/Stopped by\s*You\s*from a chat/] },
  { fixture: 'run-stopped-by-ci', title: 'Stopped', shows: [/Stopped by\s*temper-ci\s*through the API/, "temper-ci's words"] },
  {
    fixture: 'run-failed',
    title: 'Failed',
    shows: [/^lead \(planner\) turn 1 failed: /, 'Resume it from the run page to retry or stop the turn.'],
  },
  { fixture: 'run-failed-cant-go-on', title: 'Failed', shows: [/^the team can't go on: /, /Bash is off until owner-only writes/] },
  { fixture: 'run-failed-copies', title: 'Failed', shows: [/^the team's project copies could not be made: git clone exited 128/] },
  { fixture: 'run-failed-cant-open', title: 'Failed', shows: ["the team can't open: another attempt holds the team"] },
  { fixture: 'run-failed-recorder', title: 'Failed', shows: ["the team needs the run's event recorder and the worker box config"] },
  { fixture: 'run-didnt-start', title: "Didn't start", shows: [/^the team can't start: /, 'Nothing was spent.'] },
];

/**
 * The ways a team was stopped at a question (R12v), and how the timeline's
 * "stopped the team" row and the outcome card both name who did it.
 */
const STOPS: { fixture: string; who: string; kind: string; from: string }[] = [
  { fixture: 'run-stopped', who: 'You', kind: 'owner', from: 'from the dashboard' },
  { fixture: 'run-stopped-by-ci', who: 'temper-ci', kind: 'named', from: 'through the API' },
  { fixture: 'run-stopped-by-unknown', who: 'unknown caller', kind: 'unknown', from: 'from an unknown place' },
  { fixture: 'run-stopped-from-chat', who: 'You', kind: 'owner', from: 'from a chat' },
];

/** Each refusal of an answer, the run read after it, and what the page shows. */
const REFUSALS: { fixture: string; after: string; kind: string; shows: RegExp | string }[] = [
  {
    fixture: 'answer-409-already-answered',
    after: 'run-running',
    kind: 'answered',
    shows: /Already answered by\s*You\s*from the dashboard\s*at \d{1,2}:\d{2}/,
  },
  {
    fixture: 'answer-409-asked-again-old',
    after: 'run-running',
    kind: 'answered',
    shows: /Already answered by\s*an unknown caller\s*through the API\s*at \d{1,2}:\d{2}/,
  },
  { fixture: 'answer-409-replaced', after: 'run-member-waiting', kind: 'replaced', shows: 'This question was replaced by a newer one.' },
  { fixture: 'answer-409-already-rejected', after: 'run-cancelled', kind: 'ended', shows: 'The team has ended.' },
  { fixture: 'answer-404-after-stop', after: 'run-cancelled', kind: 'not_open', shows: 'That question is no longer open.' },
  ...[
    'answer-409-not-asked-yet',
    'answer-409-request-id-reused',
    'answer-400-not-an-answer',
    'answer-400-takes-no-words',
    'answer-400-guide-needs-words',
    'answer-400-reply-needs-words',
    'answer-400-guidance-too-long',
    'answer-400-nudge-too-long',
    'answer-400-reply-too-long',
    'answer-400-stop-reason-too-long',
    'answer-403',
  ].map((name) => ({ fixture: name, after: 'run-paused', kind: 'refused', shows: refusalText(name) })),
];

for (const theme of ['dark', 'light'] as const) {
  for (const width of [1024, 1440]) {
    test.describe(`Team page, ${theme}, ${width} px`, () => {
      test.use({ viewport: { width, height: 900 } });
      const tag = `${theme}-${width}`;

      test.beforeEach(async ({ page }) => {
        await page.addInitScript((t) => localStorage.setItem('temper_theme', t), theme);
      });

      for (const { fixture: name, shows } of RUN_STATES) {
        test(`run view: ${name.replace(/^run-/, '')}`, async ({ page }) => {
          await serveTeam(page, { run: [fixture(name)] });
          await page.goto(`/app/team/runs/${RUN_ID}`);
          await expect(page.getByText(shows).first()).toBeVisible();
          await expect(page.getByRole('heading', { level: 1 })).not.toHaveText('Team run');
          await expect(card(page)).toHaveCount(0);
          await expect(page.locator('[data-card="outcome"]')).toHaveCount(0);
          await expectAxeClean(page);
          await expectTargets(page);
          await shoot(page, `${tag}-${name}`);
        });
      }

      for (const { fixture: name, title, answers: offered, shows } of WAITS) {
        test(`needs you: ${name.replace(/^run-/, '')}`, async ({ page }) => {
          const { sent } = await openRun(page, name);
          await expect(card(page).getByRole('heading', { level: 2, name: title })).toBeVisible();
          await expect(card(page).getByText(shows).first()).toBeVisible();
          // The header row starts with the "Needs you" chip, then the kind's title (spec 5.2).
          await expect(card(page).locator('div:has(> h2)').getByText('Needs you')).toBeVisible();
          // Temper's answers, in its order, with nothing picked when the card opens.
          const radios = answers(page).getByRole('radio');
          await expect(radios).toHaveCount(offered.length);
          for (const [i, answer] of offered.entries()) {
            await expect(radios.nth(i)).toHaveAccessibleName(new RegExp(`^${answer}\\b`));
            await expect(radios.nth(i)).not.toBeChecked();
          }
          // Only the question Temper asks now can be answered.
          await expect(page.getByRole('group', { name: 'Your answer' })).toHaveCount(1);
          await expect(card(page).getByRole('button', { name: 'Send answer' })).toBeEnabled();
          await expect(page.getByText('Answering on the Team page is still being built.')).toHaveCount(0);
          // The round moves into the card while Temper waits.
          await expect(page.locator('[data-round-card="card"]')).toHaveCount(0);
          await expectAxeClean(page);
          await expectTargets(page);
          await shoot(page, `${tag}-${name}`);
          expect(sent.answers).toEqual([]);
        });
      }

      for (const { fixture: name, title, shows } of ENDED) {
        test(`ended: ${name.replace(/^run-/, '')}`, async ({ page }) => {
          await openRun(page, name);
          const outcome = page.locator('[data-card="outcome"]');
          await expect(outcome.getByRole('heading', { level: 2, name: title })).toBeVisible();
          for (const line of shows) await expect(outcome.getByText(line).first()).toBeVisible();
          await expect(outcome.getByText(/^Ended /)).toBeVisible();
          // Only a stop at a failed or unfinished turn explains the run list's word (E18).
          if (!shows.some((line) => typeof line === 'string' && line.startsWith('Why the run list says'))) {
            await expect(outcome.getByText(/Why the run list says/)).toHaveCount(0);
          }
          await expect(outcome.getByRole('link', { name: 'Open the run page' })).toBeVisible();
          // The place kept for M5, and nothing to answer or stop.
          await expect(page.getByText('M5, designed later')).toBeVisible();
          await expect(card(page)).toHaveCount(0);
          await expect(page.getByRole('button', { name: 'Stop run' })).toHaveCount(0);
          await expectAxeClean(page);
          await expectTargets(page);
          await shoot(page, `${tag}-${name}`);
        });
      }

      for (const { fixture: name, who, kind, from } of STOPS) {
        test(`ended: the stopped row and the outcome card name the same stop (${name.replace(/^run-/, '')})`, async ({ page }) => {
          await openRun(page, name);
          const stoppedBy = page.locator('[data-card="outcome"] [data-stopped-by]');
          const rows = page.getByRole('region', { name: /Timeline/ }).getByRole('listitem');
          const row = rows.filter({ hasText: 'stopped the team' });
          await expect(row).toHaveCount(1);
          // Who and from where: the stopping action's, on both; "You" only when the owner stopped it.
          await expect(row).toContainText(`${who} ${from} stopped the team`);
          await expect(stoppedBy).toContainText(from);
          await expect(row.locator('[data-who]')).toHaveAttribute('data-who', kind);
          await expect(stoppedBy.locator('[data-who]')).toHaveAttribute('data-who', kind);
          await expect(row.getByText('You', { exact: true })).toHaveCount(who === 'You' ? 1 : 0);
          await expect(stoppedBy.getByText('You', { exact: true })).toHaveCount(who === 'You' ? 1 : 0);
          // When: the same time on both, and every entry has one.
          const cardTime = stoppedBy.locator('time');
          await expect(row.locator('time')).toHaveAttribute('datetime', (await cardTime.getAttribute('datetime'))!);
          await expect(row.locator('time')).toHaveText((await cardTime.textContent())!);
          expect(await rows.locator('time').count()).toBe(await rows.count());
          await expectAxeClean(page);
          await shoot(page, `${tag}-stopped-row-${name.replace(/^run-/, '')}`);
        });
      }

      test('run view: a long goal wraps to two lines at most, and the goal card keeps all of it', async ({ page }) => {
        const running = fixture('run-running');
        const body = running.body as { trial: { goal: string } };
        // The heading is the goal's first line: make that line long.
        const [first, ...rest] = body.trial.goal.split('\n');
        const heading = `${first} ${'Keep it friendly and plain, and say where the new note button is for someone who opens the app for the first time. '.repeat(5).trim()}`;
        const goal = [heading, ...rest].join('\n');
        await serveTeam(page, { run: [{ ...running, body: { ...body, trial: { ...body.trial, goal } } }] });
        await page.goto(`/app/team/runs/${RUN_ID}`);
        const h1 = page.getByRole('heading', { level: 1 });
        await expect(h1).toHaveText(heading);
        await expect(h1).toHaveAttribute('title', goal);
        const box = await h1.evaluate((el) => {
          const style = getComputedStyle(el);
          return {
            clamp: style.webkitLineClamp,
            line: parseFloat(style.lineHeight),
            height: el.getBoundingClientRect().height,
            clipped: el.scrollHeight > el.clientHeight,
          };
        });
        // Two whole lines, the rest held back with an ellipsis: wrapped, never cut to one line.
        expect(box.clamp).toBe('2');
        expect(box.height).toBeGreaterThan(box.line * 1.5);
        expect(box.height).toBeLessThanOrEqual(box.line * 2 + 1);
        expect(box.clipped).toBe(true);
        await shoot(page, `${tag}-long-goal`);
        // The whole goal stays on the page: the goal card shows all of it on request.
        const goalCard = page.getByRole('region', { name: 'Goal' });
        await goalCard.getByRole('button', { name: 'Show all' }).click();
        await expect(goalCard.getByRole('button', { name: 'Show less' })).toHaveAttribute('aria-expanded', 'true');
        for (const part of goal.split('\n').map((line) => line.trim()).filter(Boolean)) {
          await expect(goalCard).toContainText(part);
        }
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
        expect(overflow).toBeLessThanOrEqual(0);
        await expectAxeClean(page);
        await expectTargets(page);
      });

      test('needs you: Send with nothing picked says so, and sends nothing', async ({ page }) => {
        const { sent } = await openRun(page, 'run-paused');
        await card(page).getByRole('button', { name: 'Send answer' }).click();
        await expect(card(page).getByText('Pick an answer first.')).toBeVisible();
        await expect(answers(page).getByRole('radio').first()).toBeFocused();
        await expect(answers(page)).toHaveAccessibleDescription('Pick an answer first.');
        await expectAxeClean(page);
        await shoot(page, `${tag}-answer-pick-first`);
        expect(sent.answers).toEqual([]);
      });

      test('needs you: words an answer needs are asked for first', async ({ page }) => {
        const { sent } = await openRun(page, 'run-paused');
        await pick(page, 'guide');
        await expect(card(page).getByRole('textbox', { name: 'Words for lead' })).toBeVisible();
        await expect(card(page).getByText('required', { exact: true })).toBeVisible();
        await card(page).getByRole('button', { name: 'Send answer' }).click();
        await expect(card(page).getByText('Write the words for lead first.')).toBeVisible();
        await expect(card(page).getByRole('textbox', { name: 'Words for lead' })).toBeFocused();
        await expectAxeClean(page);
        await shoot(page, `${tag}-answer-words-first`);
        expect(sent.answers).toEqual([]);
      });

      test("needs you: a member's question needs a reply first", async ({ page }) => {
        const { sent } = await openRun(page, 'run-member-waiting-question');
        await pick(page, 'reply');
        await card(page).getByRole('button', { name: 'Send answer' }).click();
        await expect(card(page).getByText('Write your reply to maker first.')).toBeVisible();
        await expect(card(page).getByRole('textbox', { name: 'Your reply to maker' })).toBeFocused();
        expect(sent.answers).toEqual([]);
      });

      test('needs you: the answers are a radio group, in the page order of section 6', async ({ page }) => {
        await openRun(page, 'run-paused');
        await page.getByRole('button', { name: 'Stop run' }).focus();
        // The guard notice (part C, guard_mode off here) comes first in the content column.
        await page.keyboard.press('Tab');
        await expect(page.getByRole('button', { name: 'Hide this notice for this session' })).toBeFocused();
        await page.keyboard.press('Tab');
        const radios = answers(page).getByRole('radio');
        await expect(radios.nth(0)).toBeFocused();
        await page.keyboard.press('ArrowDown');
        await expect(radios.nth(1)).toBeFocused();
        await expect(radios.nth(1)).toBeChecked();
        await page.keyboard.press('Tab');
        await expect(card(page).getByRole('textbox', { name: 'Words for lead' })).toBeFocused();
        await page.keyboard.press('Tab');
        await expect(card(page).getByRole('button', { name: 'Send answer' })).toBeFocused();
        await page.keyboard.press('Shift+Tab');
        await page.keyboard.press('Shift+Tab');
        await expect(radios.nth(1)).toBeFocused();
        await page.keyboard.press('ArrowDown');
        await expect(radios.nth(2)).toBeChecked();
        await expect(card(page).getByRole('textbox', { name: 'Your words with the stop' })).toBeVisible();
        await expect(card(page).getByRole('button', { name: 'Stop the team\u2026' })).toBeVisible();
        await page.keyboard.press('ArrowUp');
        await page.keyboard.press('ArrowUp');
        await expect(radios.nth(0)).toBeChecked();
        // continue takes no words: no box.
        await expect(card(page).getByRole('textbox')).toHaveCount(0);
      });

      test('needs you: guide is sent with its words, once, and the run is read again', async ({ page }) => {
        const { sent, seen } = await openRun(page, 'run-paused', {
          after: 'run-running',
          answer: [fixture('answer-200-guide')],
        });
        await pick(page, 'guide', 'Keep the heading to one line.');
        await expect(card(page).getByText('29 / 20,000')).toBeVisible();
        const reads = runReads(seen);
        await card(page).getByRole('button', { name: 'Send answer' }).click();
        await expect(result(page)).toContainText('Answer sent: guide.');
        await expect(result(page)).toBeFocused();
        await expect.poll(() => runReads(seen)).toBeGreaterThan(reads);
        await expect(card(page)).toHaveCount(0);
        expect(sent.answers).toHaveLength(1);
        expect(sent.answers[0]).toMatchObject({ answer: 'guide', text: 'Keep the heading to one line.' });
        expect(String(sent.answers[0].request_id)).toMatch(/\S{8,}/);
        await expectAxeClean(page);
        await expectTargets(page);
        await shoot(page, `${tag}-answer-sent`);
      });

      test('needs you: no reply from Temper, then Send again with the same request id', async ({ page }) => {
        const { sent } = await openRun(page, 'run-paused', {
          after: 'run-paused',
          answer: ['no reply', fixture('answer-200-guide')],
        });
        await pick(page, 'guide', 'Keep the heading to one line.');
        await card(page).getByRole('button', { name: 'Send answer' }).click();
        await expect(result(page)).toContainText("Temper didn't answer.");
        await expect(result(page)).toContainText('Trying again is safe: the same request counts once.');
        const first = String(sent.answers[0].request_id);
        await expect(result(page)).toContainText(`Request ${first.slice(0, 8)} \u00b7 your inputs are kept.`);
        await expect(card(page).getByRole('textbox', { name: 'Words for lead' })).toHaveValue('Keep the heading to one line.');
        await expectAxeClean(page);
        await shoot(page, `${tag}-answer-no-reply`);
        await card(page).getByRole('button', { name: 'Send answer' }).click();
        await expect(result(page)).toContainText('Answer sent: guide.');
        expect(sent.answers.map((a) => a.request_id)).toEqual([first, first]);
      });

      test('needs you: the answer was kept but the run needs Resume', async ({ page }) => {
        await openRun(page, 'run-paused', { after: 'run-interrupted', answer: [fixture('answer-200-needs-resume')] });
        await pick(page, 'guide', 'Keep the heading to one line.');
        await card(page).getByRole('button', { name: 'Send answer' }).click();
        await expect(result(page)).toContainText('Answer kept: guide.');
        await expect(result(page)).toContainText(
          'Approved and kept. The run is not running, so it needs Resume; when it comes back it goes on with this answer without asking again.',
        );
        await expect(result(page).getByRole('link', { name: 'Open the run page' })).toBeVisible();
        await expectAxeClean(page);
        await expectTargets(page);
        await shoot(page, `${tag}-answer-needs-resume`);
      });

      test('needs you: a send Temper already had counts once', async ({ page }) => {
        await openRun(page, 'run-paused', { after: 'run-running', answer: [fixture('answer-200-repeated')] });
        await pick(page, 'guide', 'Keep the heading to one line.');
        await card(page).getByRole('button', { name: 'Send answer' }).click();
        await expect(result(page)).toContainText('Temper already had it from your last try; it counted once.');
      });

      for (const { fixture: name, after, kind, shows } of REFUSALS) {
        test(`needs you: refused, ${name.replace(/^answer-/, '')}`, async ({ page }) => {
          // "Already answered ... at <time>" gives the time of day only for an answer made today, and the
          // date on any later day. The page's clock is set to 5 minutes after the fixture's answer, so the
          // test reads the same on any day and in any time zone (it failed in CI from 00:00 UTC on 7 Oct).
          const answeredAt = (fixture(name).body as { answered_at?: string | null }).answered_at;
          if (answeredAt) await page.clock.setFixedTime(new Date(Date.parse(answeredAt) + 5 * 60_000));
          const { seen } = await openRun(page, 'run-paused', { after, answer: [fixture(name)] });
          await pick(page, 'continue');
          const reads = runReads(seen);
          await card(page).getByRole('button', { name: 'Send answer' }).click();
          await expect(page.locator(`[data-answer-result="${kind}"]`)).toBeVisible();
          await expect(result(page)).toContainText(shows);
          // Every reply is followed by a read of the run: after a 409 it shows who answered.
          await expect.poll(() => runReads(seen)).toBeGreaterThan(reads);
          if (after !== 'run-paused') await expect(card(page)).toHaveCount(after === 'run-member-waiting' ? 1 : 0);
          await expectAxeClean(page);
          await expectTargets(page);
          await shoot(page, `${tag}-${name}`);
        });
      }

      test("needs you: a 401 opens the dashboard's own key form", async ({ page }) => {
        // With the guard on, reading is open and answering needs the owner's key.
        await page.route('**/api/runtime-config', (route) =>
          route.fulfill({ json: { auth_required: false, writes_need_key: true } }),
        );
        const { sent } = await openRun(page, 'run-paused', { answer: [fixture('answer-401')] });
        await pick(page, 'continue');
        await card(page).getByRole('button', { name: 'Send answer' }).click();
        await expect(page.getByRole('heading', { name: 'This action needs your key' })).toBeVisible();
        await expect(
          page.getByText(
            'Reading is open; starting, answering and stopping runs needs your key. Paste the contents of your key file. It stays in this browser. Then do the action again.',
          ),
        ).toBeVisible();
        expect(sent.answers).toHaveLength(1);
        await shoot(page, `${tag}-answer-401`);
      });

      test('needs you: words at the limit are sent, one over is caught first (S2)', async ({ page }) => {
        const { sent } = await openRun(page, 'run-paused', { answer: [fixture('answer-200-guide')] });
        await pick(page, 'guide', 'x'.repeat(20_001));
        await expect(card(page).getByText('20,001 / 20,000 \u00b7 1 over')).toBeVisible();
        await card(page).getByRole('button', { name: 'Send answer' }).click();
        await expect(card(page).getByText('Shorten your words first: they are 1 character over the limit of 20,000.')).toBeVisible();
        await expect(card(page).getByRole('textbox', { name: 'Words for lead' })).toBeFocused();
        await expectAxeClean(page);
        await shoot(page, `${tag}-answer-over-limit`);
        expect(sent.answers).toEqual([]);
        await card(page).getByRole('textbox', { name: 'Words for lead' }).fill('x'.repeat(20_000));
        await card(page).getByRole('button', { name: 'Send answer' }).click();
        await expect(result(page)).toContainText('Answer sent: guide.');
        expect(sent.answers).toHaveLength(1);
      });

      test('needs you: a nudge has its own limit (S2)', async ({ page }) => {
        const { sent } = await openRun(page, 'run-quiet');
        await pick(page, 'nudge', 'n'.repeat(4_001));
        await card(page).getByRole('button', { name: 'Send answer' }).click();
        await expect(card(page).getByText('Shorten your words first: they are 1 character over the limit of 4,000.')).toBeVisible();
        expect(sent.answers).toEqual([]);
      });

      test("needs you: HTML in a member's question stays text (S7)", async ({ page }) => {
        await openRun(page, 'run-member-waiting-question-script');
        await expect(card(page).getByText(/<script>alert\('boards'\)<\/script> <b>bold\?<\/b>/)).toBeVisible();
        expect(await page.locator('main script, main img[src="x"], main b:text-is("bold?")').count()).toBe(0);
        await expectAxeClean(page);
        await shoot(page, `${tag}-answer-script`);
      });

      test('stop at a question: the confirm, Keep the team, then Stop the team', async ({ page }) => {
        const { sent } = await openRun(page, 'run-paused', { after: 'run-stopped', answer: [fixture('answer-200-stop')] });
        await pick(page, 'stop', 'We have what we need for now.');
        // Design's words for a stop picked in the card (O1c).
        await expect(card(page).getByText("Shown quoted with the outcome, labelled as yours, beside Temper's reason.")).toBeVisible();
        await expect(card(page).getByText('You confirm in the next step.')).toBeVisible();
        await shoot(page, `${tag}-stop-picked`);
        const stopTeam = card(page).getByRole('button', { name: 'Stop the team\u2026' });
        await stopTeam.click();
        const dialog = page.getByRole('alertdialog', { name: 'Stop the team at this question?' });
        await expect(dialog).toBeVisible();
        await expect(dialog.getByText('The team ends here and nothing more is spent.')).toBeVisible();
        await expect(
          dialog.getByText(
            "The run list will show this run as cancelled, like Stop run. This page shows Stopped, with Temper's reason and your words.",
          ),
        ).toBeVisible();
        await expect(dialog.getByText('We have what we need for now.')).toBeVisible();
        await expect(dialog.getByText("You can't undo this.")).toBeVisible();
        await expectAxeClean(page);
        await shoot(page, `${tag}-stop-answer-confirm`);
        await dialog.getByRole('button', { name: 'Keep the team' }).click();
        await expect(dialog).toHaveCount(0);
        await expect(stopTeam).toBeFocused();
        expect(sent.answers).toEqual([]);
        await stopTeam.click();
        await page.getByRole('alertdialog').getByRole('button', { name: 'Stop the team', exact: true }).click();
        await expect(page.locator('[data-card="outcome"]').getByRole('heading', { name: 'Stopped' })).toBeVisible();
        expect(sent.answers).toHaveLength(1);
        expect(sent.answers[0]).toMatchObject({ answer: 'stop', text: 'We have what we need for now.' });
      });

      test('stop at a failed turn: the confirm says the run list will show failed', async ({ page }) => {
        await openRun(page, 'run-member-waiting-failed');
        await pick(page, 'stop');
        await card(page).getByRole('button', { name: 'Stop the team\u2026' }).click();
        const dialog = page.getByRole('alertdialog', { name: 'Stop the team at this question?' });
        await expect(dialog.getByText('The team ends here and nothing more is spent.')).toBeVisible();
        await expect(
          dialog.getByText(
            "The run list will show this run as failed: Temper records a stop at a member's failed or unfinished turn as failed. This page shows Stopped, with Temper's reason and your words.",
          ),
        ).toBeVisible();
        await expect(dialog.getByText(/as cancelled/)).toHaveCount(0);
        await page.keyboard.press('Escape');
        await expect(dialog).toHaveCount(0);
      });

      test('Stop run: the confirm, Keep running, then Stop run with a reason', async ({ page }) => {
        const { sent, seen } = await openRun(page, 'run-paused', { after: 'run-cancelled', cancel: [fixture('cancel-200')] });
        const stopRun = page.getByRole('button', { name: 'Stop run' });
        await stopRun.click();
        const dialog = page.getByRole('alertdialog', { name: /^Stop run: team-trial-/ });
        await expect(dialog).toBeVisible();
        const reason = dialog.getByRole('textbox', { name: 'Your reason' });
        await expect(reason).toBeFocused();
        await expect(dialog.getByText('0 / 2,000')).toBeVisible();
        await reason.fill('Enough for today.');
        await expect(dialog.getByText('17 / 2,000')).toBeVisible();
        await expectAxeClean(page);
        await shoot(page, `${tag}-stop-run-confirm`);
        await dialog.getByRole('button', { name: 'Keep running' }).click();
        await expect(dialog).toHaveCount(0);
        await expect(stopRun).toBeFocused();
        expect(sent.cancels).toEqual([]);
        await stopRun.click();
        await expect(reason).toHaveValue('');
        await reason.fill('Enough for today.');
        const reads = runReads(seen);
        await dialog.getByRole('button', { name: 'Stop run' }).click();
        await expect(dialog).toHaveCount(0);
        expect(sent.cancels).toEqual([{ reason: 'Enough for today.' }]);
        await expect.poll(() => runReads(seen)).toBeGreaterThan(reads);
        await expect(page.locator('[data-card="outcome"]').getByText('the run was cancelled')).toBeVisible();
        // Stop run is gone with the run: the focus goes to the outcome, not the page's body.
        await expect(page.locator('#team-outcome-title')).toBeFocused();
      });

      test('Stop run: a reason over the limit is caught first, and nothing is sent', async ({ page }) => {
        const { sent } = await openRun(page, 'run-paused');
        await page.getByRole('button', { name: 'Stop run' }).click();
        const dialog = page.getByRole('alertdialog');
        await dialog.getByRole('textbox', { name: 'Your reason' }).fill('r'.repeat(2_001));
        await expect(dialog.getByText('2,001 / 2,000 \u00b7 1 over')).toBeVisible();
        await dialog.getByRole('button', { name: 'Stop run' }).click();
        await expect(dialog.getByText('Shorten your reason first: it is 1 character over the limit of 2,000.')).toBeVisible();
        await expect(dialog.getByRole('textbox', { name: 'Your reason' })).toBeFocused();
        await expectAxeClean(page);
        await shoot(page, `${tag}-stop-run-too-long`);
        expect(sent.cancels).toEqual([]);
      });

      for (const [name, words] of [
        ['cancel-404', "Execution 'not-a-run' not found"],
        ['cancel-400-too-long', 'the reason is too long (2001 characters; at most 2000)'],
      ] as const) {
        test(`Stop run: refused, ${name}`, async ({ page }) => {
          // A server with a higher limit than this page knows lets the long reason through to Temper.
          const status = fixture('status-on');
          const body = status.body as { limits: Record<string, number> };
          const { sent } = await openRun(page, 'run-paused', {
            cancel: [fixture(name)],
            status: { ...status, body: { ...body, limits: { ...body.limits, stop_reason_max_chars: 5_000 } } },
          });
          await page.getByRole('button', { name: 'Stop run' }).click();
          const dialog = page.getByRole('alertdialog');
          await dialog.getByRole('textbox', { name: 'Your reason' }).fill('r'.repeat(2_001));
          await dialog.getByRole('button', { name: 'Stop run' }).click();
          await expect(dialog.getByText(`Temper refused: ${words} Nothing was stopped.`)).toBeVisible();
          await expect(dialog.getByRole('button', { name: 'Keep running' })).toBeVisible();
          expect(sent.cancels).toHaveLength(1);
          await expectAxeClean(page);
          await shoot(page, `${tag}-stop-run-${name}`);
        });
      }

      test('Stop run: the run had already ended (G13)', async ({ page }) => {
        const { seen } = await openRun(page, 'run-paused', { after: 'run-done', cancel: [fixture('cancel-ended')] });
        await page.getByRole('button', { name: 'Stop run' }).click();
        const dialog = page.getByRole('alertdialog');
        await dialog.getByRole('textbox', { name: 'Your reason' }).fill('Enough for today.');
        const reads = runReads(seen);
        await dialog.getByRole('button', { name: 'Stop run' }).click();
        const notice = dialog.getByRole('status');
        await expect(notice).toContainText('Nothing was stopped. The run had already ended (');
        await expect(notice).toContainText("completed) before your stop reached Temper. Your reason wasn't recorded.");
        await expect(dialog.getByRole('button', { name: 'Close', exact: true }).last()).toBeFocused();
        await expect(dialog.getByRole('button', { name: 'Keep running' })).toHaveCount(0);
        await expect(dialog.getByRole('button', { name: 'Stop run' })).toHaveCount(0);
        await expect.poll(() => runReads(seen)).toBeGreaterThan(reads);
        await expectAxeClean(page);
        await shoot(page, `${tag}-stop-run-g13`);
        await dialog.getByRole('button', { name: 'Close', exact: true }).last().click();
        await expect(dialog).toHaveCount(0);
        await expect(page.locator('[data-card="outcome"]')).toBeVisible();
        await expect(page.locator('#team-outcome-title')).toBeFocused();
      });

      test('ended: a 4,000-character summary and 500 files (S4)', async ({ page }) => {
        await openRun(page, 'run-done-big');
        const outcome = page.locator('[data-card="outcome"]');
        const files = outcome.getByRole('region', { name: 'Files in the approved version (500)' });
        await expect(files.getByRole('listitem')).toHaveCount(20);
        await expect(outcome.getByRole('button', { name: 'Show all', exact: true })).toBeVisible();
        expect(await outcome.locator('b:text-is("not bold")').count()).toBe(0);
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
        expect(overflow).toBeLessThanOrEqual(0);
        await expectAxeClean(page);
        await expectTargets(page);
        await shoot(page, `${tag}-ended-big`);
        await files.getByRole('button', { name: 'Show all 500 files' }).click();
        await expect(files.getByRole('listitem')).toHaveCount(500);
        await outcome.getByRole('button', { name: 'Show all', exact: true }).click();
        await expect(outcome.getByText('Still open')).toBeVisible();
      });

      test("ended: HTML in the owner's words stays text (S7)", async ({ page }) => {
        await openRun(page, 'run-stopped-script');
        const outcome = page.locator('[data-card="outcome"]');
        await expect(outcome.getByText(/Stop\. <script>alert\('boards'\)<\/script> <b>bold\?<\/b>/)).toBeVisible();
        expect(await page.locator('main script, main img[src="x"], main b:text-is("bold?")').count()).toBe(0);
        await expectAxeClean(page);
        await shoot(page, `${tag}-ended-script`);
      });

      test('run view: at its limits (six members, a 40-character name, 400 entries, a goal that looks like HTML)', async ({ page }) => {
        await serveTeam(page, { run: [fixture('run-stress')] });
        await page.goto(`/app/team/runs/${RUN_ID}`);
        const members = page.getByRole('region', { name: /Members/ });
        await expect(members.getByRole('listitem')).toHaveCount(6);
        await expect(members.getByTitle('a-very-long-team-name-for-the-stress-40c')).toBeVisible();
        await expect(members.getByText(/turn 5: the worker box closed the session/)).toBeVisible();
        await expect(members.getByText('used claude-sonnet-5 \u00b7 high')).toBeVisible();
        await expect(page.getByText('392 more in this list')).toBeVisible();
        await expect(page.getByText(/1,234 earlier entries not shown/)).toBeVisible();
        // The goal's HTML-looking text is shown as text, never run or drawn.
        await expect(page.getByText(/<script>alert\("boards"\)<\/script> <b>not bold<\/b>/).first()).toBeVisible();
        expect(await page.locator('main script, main img[src="x"], main b:text-is("not bold")').count()).toBe(0);
        // Nothing wider than the window.
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
        expect(overflow).toBeLessThanOrEqual(0);
        await expectAxeClean(page);
        await expectTargets(page);
        await shoot(page, `${tag}-run-stress`);
        const timeline = page.getByRole('region', { name: /Timeline/ });
        await timeline.getByRole('button', { name: /^Show all/ }).click();
        await expect(timeline.getByRole('listitem')).toHaveCount(400);
      });

      test('run view: one message opened, the one its row stands for', async ({ page }) => {
        const read = fixture('message-read').body as { message_id: string; body: string };
        const done = fixture('run-done');
        const seen = await serveTeam(page, { run: [done] });
        await page.goto(`/app/team/runs/${RUN_ID}`);
        // maker's view to lead in round 1, the message Temper's captured read answered: an older entry.
        const timeline = page.getByRole('region', { name: /Timeline/ });
        await timeline.getByRole('button', { name: 'Show all' }).click();
        const row = timeline
          .getByRole('listitem')
          .filter({ hasText: /maker\s*to\s*lead/ })
          .filter({ hasText: read.body.slice(0, 40) });
        await row.getByRole('button', { name: /^Open/ }).click();
        await expect(row.getByText(/The heading wraps to three lines on a phone/)).toBeVisible();
        await expect(row.getByRole('button', { name: /^Close/ })).toHaveAttribute('aria-expanded', 'true');
        const runId = (done.body as { execution_id: string }).execution_id;
        expect(seen).toContain(`/api/team/runs/${runId}/messages/${read.message_id}`);
        await expectAxeClean(page);
        await expectTargets(page);
        await shoot(page, `${tag}-message-open`);
      });

      test("run view: a refresh that failed keeps the run and says so", async ({ page }) => {
        await serveTeam(page, { run: [fixture('run-running'), { route: '', status: 500, body: 'Internal Server Error' }] });
        await page.goto(`/app/team/runs/${RUN_ID}`);
        await expect(page.getByText('Who did what')).toBeVisible();
        await expect(page.getByText(/Couldn't refresh at/)).toBeVisible({ timeout: 15_000 });
        await expect(page.getByText(/not current/)).toBeVisible();
        await expect(page.getByText('Who did what')).toBeVisible();
        await expectAxeClean(page);
        await expectTargets(page);
        await shoot(page, `${tag}-refresh-failed`);
      });

      test("run view: a run that isn't a team trial", async ({ page }) => {
        await serveTeam(page, { run: [fixture('run-404')] });
        await page.goto(`/app/team/runs/${RUN_ID}`);
        await expect(page.getByText("This run isn't a team trial")).toBeVisible();
        await expect(page.getByText('not a team trial, or no such run')).toBeVisible();
        // Information, not a failure; the heading is for screen readers only (Design's R0).
        await expect(page.locator('[data-note="info"]')).toContainText("This run isn't a team trial");
        await expect(page.locator('[data-note="bad"]')).toHaveCount(0);
        await expect(page.getByRole('heading', { level: 1, name: 'Team run' })).toHaveClass(/sr-only/);
        await expect(page.getByRole('link', { name: 'Open the run page' })).toBeVisible();
        await expectAxeClean(page);
        await shoot(page, `${tag}-not-team`);
      });

      // The trials list, the roles, the form, the composer, the guard notice
      // and the settings wait: team-c.spec.ts.

      test('Team page: Page not found when the switch is off', async ({ page }) => {
        await serveTeam(page, { status: fixture('status-off') });
        await page.goto('/app/team');
        await expect(page.getByRole('heading', { name: 'Page not found' })).toBeVisible();
        await expect(page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name: 'Team' })).toHaveCount(0);
      });
    });
  }
}

test.describe("the run page's Team run view link", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test('goes to the run view and back for a team trial', async ({ page, request }) => {
    const id = await startSmokeRun(request);
    await serveTeam(page, { run: [asRun('run-done', id)] });
    await page.goto(`/app/workflow/${id}`);
    const link = page.getByRole('link', { name: 'Team run view' });
    await expect(link).toBeVisible();
    await expectAxeClean(page);
    await shoot(page, 'link-run-page');
    await link.click();
    await expect(page).toHaveURL(new RegExp(`/app/team/runs/${id}$`));
    await expect(page.getByText('Who did what')).toBeVisible();
    await page.getByRole('link', { name: 'Run page', exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/app/workflow/${id}$`));
  });

  test("isn't there for a run that isn't a team trial", async ({ page, request }) => {
    const id = await startSmokeRun(request);
    const seen = await serveTeam(page, { run: [fixture('run-404')] });
    await page.goto(`/app/workflow/${id}`);
    await expect(page.getByRole('link', { name: 'Edit in Studio' })).toBeVisible();
    await expect.poll(() => seen.filter((p) => p.startsWith('/api/team/runs/')).length).toBe(1);
    await expect(page.getByRole('link', { name: 'Team run view' })).toHaveCount(0);
  });
});

/**
 * No mocks: the server's own answers. With the switch off (CI, and every
 * server unless its owner turns the Team on) nothing of the Team shows and
 * the run page asks nothing about team runs.
 */
test.describe('with the Team switch off', () => {
  test.beforeEach(async ({ request }) => {
    const status = await request.get('/api/team/status');
    test.skip(status.status() !== 404, 'this server has the Team switch on');
  });

  test('the sidebar has no Team item and /app/team is Page not found', async ({ page }) => {
    await page.goto('/app/');
    const nav = page.getByRole('navigation', { name: 'Main navigation' });
    await expect(nav.getByRole('link', { name: 'Workflows' })).toBeVisible();
    await expect(nav.getByRole('link', { name: 'Team' })).toHaveCount(0);
    for (const url of ['/app/team', '/app/team/roles', '/app/team/new', '/app/team/runs/anything']) {
      await page.goto(url);
      await expect(page.getByRole('heading', { name: 'Page not found' })).toBeVisible();
    }
  });

  test('the run page has no Team run view button and asks nothing about team runs', async ({ page, request }) => {
    const id = await startSmokeRun(request);
    const asked: string[] = [];
    page.on('request', (r) => {
      const { pathname } = new URL(r.url());
      if (pathname.startsWith('/api/team/')) asked.push(pathname);
    });
    await page.goto(`/app/workflow/${id}`);
    await expect(page.getByRole('link', { name: 'Edit in Studio' })).toBeVisible();
    await page.waitForTimeout(1500);
    await expect(page.getByRole('link', { name: 'Team run view' })).toHaveCount(0);
    // The one switch read per page load is all; never a team run.
    expect(asked.filter((p) => p !== '/api/team/status')).toEqual([]);
  });
});
