/**
 * Design's real-run words (D104-D110, Oct 10) on Temper's own runs, as one
 * journey a user takes through them: a usage limit that resets in 3 days, runs
 * that ended in every way (interrupted with and without an end time, done,
 * stopped, failed), a turn ended at its cap, a share Temper refused, an answer
 * to a member's question, a check-in answered with Guide, a usage limit that
 * is over and Temper's own settings question. Then the New project form, whose
 * text a phone must read without zooming (Design's note on its phone text).
 *
 * Every /api/team answer comes from Temper's samples (e2e/fixtures/team/flow:
 * real-g6, real, derived), so no Temper is needed and nothing is written. At
 * each stop: the words a user reads, found by region and text, axe clean and
 * every target 24 px or more; in both themes at 390x844, 1024x768 and 1440x900.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { expect, test, type Locator, type Page } from '@playwright/test';
import { expectAxeClean, expectTargets, glanceFontsSettled, nothingSent, serveActions, serveTeam } from './team-helpers';

type Raw = Record<string, unknown>;
type Feed = { events: Raw[]; as_of: string };

const FLOW = path.join(process.cwd(), 'e2e/fixtures/team/flow');
/** The owner's time zone: the page tells times in the viewer's own zone, and D104's days by its calendar. */
test.use({ timezoneId: 'America/Los_Angeles' });

/** A sample as Temper sent it ('real-g6/retry'), as a fresh copy; its feed with `feed`. */
function sample(name: string, feed = false): Raw {
  return JSON.parse(readFileSync(path.join(FLOW, `${name}${feed ? '-events' : ''}.json`), 'utf8')) as Raw;
}

/** Temper, answering from the sample the journey is at: the run, and its feed up to the run's events_cursor. */
async function serveSamples(page: Page) {
  const at = { name: '' };
  const sent = nothingSent();
  await serveTeam(page, { run: () => ({ route: '', status: 200, body: sample(at.name) }) });
  await serveActions(page, sent, {});
  // Set up after serveTeam, so it answers the feed first.
  await page.route(/\/api\/team\/runs\/[^/]+\/events(\?|$)/, async (route) => {
    const url = new URL(route.request().url());
    const after = Number(url.searchParams.get('after') ?? '0');
    const limit = Number(url.searchParams.get('limit') ?? '200');
    const upTo = sample(at.name).events_cursor as number;
    const feed = sample(at.name, true) as unknown as Feed;
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
  return { at, sent };
}

/** Open the page of one sample's run, at Temper's clock, once its whole history is read. */
async function visit(page: Page, at: { name: string }, name: string) {
  at.name = name;
  const run = sample(name);
  await page.clock.setFixedTime(new Date(run.as_of as string));
  await page.goto(`/app/team/runs/${run.execution_id as string}`);
  await expect(page.getByTestId('glance-page')).toHaveAttribute('data-phase', (run.phase as Raw).name as string);
  await expect(page.getByTestId('glance-just-sent')).not.toContainText('Reading the team');
  await glanceFontsSettled(page);
}

const status = (page: Page) => page.getByRole('region', { name: 'Status' });
const latest = (page: Page) => page.getByRole('region', { name: 'Latest' });
const activity = (page: Page) => page.getByRole('region', { name: 'All activity' });

/** All activity's rows, newest first, with older ones shown: each row's words without its time. */
async function activityRows(page: Page): Promise<string[]> {
  const older = activity(page).getByRole('button', { name: /^Show older/ });
  if (await older.isVisible()) await older.click();
  return activity(page)
    .getByRole('listitem')
    .evaluateAll((rows) => rows.map((r) => (r.querySelector('[id$="-text"]')?.textContent ?? '').trim()));
}

/** Every member card of `name`'s run says "Ended", with no live duration; never "Idle \u00b7 0 s" (D105). */
async function expectCardsEnded(page: Page, wide: boolean, name: string) {
  const cards = page.getByTestId(wide ? 'glance-map' : 'glance-list').locator('[data-member]');
  await expect(cards).toHaveCount((sample(name).members as Raw[]).length);
  for (const chip of await cards.getByTestId('glance-chip').all()) await expect.soft(chip).toHaveText('Ended');
  await expect.soft(cards.filter({ hasText: /Idle \u00b7|Working \u00b7/ })).toHaveCount(0);
}

/** What every stop must hold: axe finds nothing, every target is 24 px or more, nobody is "The team" asking. */
async function expectSound(page: Page) {
  await expectAxeClean(page);
  await expectTargets(page);
  await expect.soft(page.getByRole('main')).not.toContainText('The team asked you');
}

/** Text under `px` in `scope`, as the reader sees it (hidden text, icons and the sidebar left out). */
async function textUnder(scope: Locator, px: number): Promise<string[]> {
  return scope.evaluate((root, floor) => {
    const out: string[] = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const el = n.parentElement;
      if (!n.textContent?.trim() || !el || el.closest('.sr-only, svg') || !el.getClientRects().length) continue;
      const s = getComputedStyle(el);
      if (s.visibility === 'hidden' || parseFloat(s.fontSize) >= floor) continue;
      out.push(`${s.fontSize} "${n.textContent.trim().slice(0, 40)}"`);
    }
    return out;
  }, px);
}

/** Fields that take typed text, with their font size. */
async function fieldSizes(scope: Locator): Promise<string[]> {
  return scope.evaluate((root) =>
    Array.from(
      root.querySelectorAll<HTMLElement>('input:not([type="checkbox"]):not([type="radio"]):not([type="hidden"]), textarea, select'),
    )
      .filter((el) => el.getClientRects().length > 0)
      .map((el) => `${getComputedStyle(el).fontSize} ${el.id || el.getAttribute('name') || el.tagName.toLowerCase()}`),
  );
}

const SIZES = [
  { width: 390, height: 844 },
  { width: 1024, height: 768 },
  { width: 1440, height: 900 },
] as const;

for (const theme of ['dark', 'light'] as const) {
  for (const { width, height } of SIZES) {
    test(`A user reads Temper's real runs in Design's words (D104-D110), then the New project form, ${theme}, ${width}x${height}`, async ({
      page,
    }) => {
      test.setTimeout(240_000);
      const wide = width >= 768;
      await page.setViewportSize({ width, height });
      await page.addInitScript((t) => localStorage.setItem('temper_theme', t), theme);
      const { at, sent } = await serveSamples(page);
      const go = async (name: string) => {
        await visit(page, at, name);
        await expectSound(page);
      };

      await test.step('D104: a check 3 days away gets its day', async () => {
        // Temper's clock: Fri Oct 9, 8:59 PM; its next allowance check: Mon Oct 12, 8:59 PM.
        await go('real-g6/restart_deferred');
        await expect.soft(status(page).getByTestId('glance-now-sentence')).toContainText('Next allowance check Mon at 8:59 PM.');
        await expect.soft(latest(page).getByRole('listitem').first()).toContainText('Usage limit: next allowance check Mon at 8:59 PM');
        await expect.soft(activity(page)).toContainText('Usage limit: next allowance check Mon at 8:59 PM');
        await expect.soft(page.locator('#glance-message')).toContainText('No new turn starts before Mon at 8:59 PM.');
      });

      await test.step('D105: an interrupted run reads as ended, with Temper\u2019s reason', async () => {
        await go('real-g6/interrupted');
        await expect.soft(status(page).getByTestId('glance-now-word')).toHaveText('Interrupted');
        await expect.soft(status(page).getByTestId('glance-now-sentence')).toHaveText('The run ended without the team ending.');
        await expect
          .soft(status(page).getByTestId('glance-now-reason'))
          .toHaveText('the run ended (interrupted) without the team ending');
        await expectCardsEnded(page, wide, 'real-g6/interrupted');
        // Temper gave no time for its reason: the last row of the run, with no time.
        const first = activity(page).getByRole('listitem').first();
        await expect.soft(first).toHaveText('Interrupted: the run ended (interrupted) without the team ending');
        await expect.soft(first.locator('time')).toHaveCount(0);
      });

      await test.step('D105: Temper recorded no end, so Now gives the newest time it did record', async () => {
        await go('real-g6/interrupted_no_end');
        await expect.soft(status(page).getByTestId('glance-now-word')).toHaveText('Interrupted');
        await expect
          .soft(status(page).getByTestId('glance-now-sentence'))
          .toHaveText('Last activity 8:40 PM. Temper didn\u2019t record when it ended.');
        await expectCardsEnded(page, wide, 'real-g6/interrupted_no_end');
      });

      await test.step('D105: done, stopped and failed runs\u2019 cards say "Ended" too', async () => {
        for (const name of ['real/done', 'derived/stopped', 'derived/run_failed']) {
          await go(name);
          await expectCardsEnded(page, wide, name);
          const reason = (sample(name).phase as Raw).reason as string | undefined;
          if (reason) {
            // Their reason shows as before: Now's sentence, and Temper's own row once in All activity; no second row.
            await expect.soft(status(page).getByTestId('glance-now-sentence'), name).toContainText(reason);
            expect.soft((await activityRows(page)).filter((r) => r.includes(reason)), name).toHaveLength(1);
          }
        }
        await expect.soft(status(page).getByTestId('glance-now-word')).toHaveText('Failed');
      });

      await test.step('D106: a turn ended at its tool-call limit', async () => {
        await go('real-g6/retry');
        expect.soft(await activityRows(page)).toContain('checker\u2019s turn 1 ended at its tool-call limit.');
      });

      await test.step('D107: a share Temper refused without a reason', async () => {
        await go('real-g6/conflict');
        expect.soft(await activityRows(page)).toContain('checker\u2019s version wasn\u2019t shared. Temper gave no reason.');
        await expect.soft(page.getByRole('main')).not.toContainText(/refused: refused/i);
      });

      await test.step('D108, D110: a member asks, you answer; Latest and All activity say it alike', async () => {
        await go('real-g6/member_question');
        const asked = 'checker asked you: \u201cShould the checks also cover the example scripts?\u201d';
        await expect.soft(latest(page)).toContainText(asked);
        const rows = await activityRows(page);
        expect.soft(rows).toContain(asked);
        expect.soft(rows).toContain('You answered checker: \u201cyes\u201d');
      });

      await test.step('D108, D110: Temper\u2019s check-in answered with Guide, then the guide\u2019s words', async () => {
        await go('derived/resumed');
        await expect.soft(latest(page)).toContainText('You answered: guide');
        const rows = await activityRows(page);
        const guided = rows.indexOf('You messaged lead: \u201cKeep the README under 40 lines and add a Usage section.\u201d');
        expect.soft(guided, 'the guide\u2019s words').toBeGreaterThanOrEqual(0);
        expect.soft(rows[guided + 1], 'right under them, the answer to the check-in').toBe('You answered: guide');
        expect.soft(rows).toContainEqual(expect.stringMatching(/^Temper asked you: \u201cThe team has spent \$105\.00/));
      });

      await test.step('D109: the usage limit is over, and when the team carried on', async () => {
        await go('real-g6/limit_ended');
        const over = 'The usage limit is over. The team carried on at 8:40 PM.';
        await expect.soft(latest(page).getByRole('listitem').first()).toContainText(over);
        expect.soft(await activityRows(page)).toContain(over);
      });

      await test.step('D110: Temper\u2019s own question names Temper', async () => {
        await go('real-g6/settings_late');
        const asks = (sample('real-g6/settings_late', true) as unknown as Feed).events.filter((e) => e.kind === 'wait_opened');
        expect.soft(await activityRows(page)).toContain(`Temper asked you: \u201c${asks[asks.length - 1].words as string}\u201d`);
      });

      await test.step('The New project form: phone text 14 px, typed text 16 px; 768 px and up as before', async () => {
        await page.goto('/app/team/new');
        await expect(page.getByRole('heading', { level: 1, name: 'New project' })).toBeVisible();
        const form = page.getByTestId('team-form');
        await expect(form.getByRole('group', { name: 'Member 1', exact: true }).getByLabel('Role')).toBeEnabled();
        await expectAxeClean(page);
        await expectTargets(page);
        const main = page.getByRole('main');
        if (!wide) {
          expect.soft(await textUnder(main, 14), 'text under 14 px on a phone').toEqual([]);
          expect.soft((await fieldSizes(main)).filter((f) => !f.startsWith('16px ')), 'fields under 16 px on a phone').toEqual([]);
        } else {
          // Nothing changes at 768 px and up: the help stays 12 px, the fields 14 px.
          await expect.soft(page.locator('#team-goal-help')).toHaveCSS('font-size', '12px');
          await expect.soft(form.getByRole('textbox', { name: /^Goal/ })).toHaveCSS('font-size', '14px');
        }
      });

      // The journey only read: nothing was answered, sent or started.
      expect(sent).toEqual(nothingSent());
    });
  }
}
