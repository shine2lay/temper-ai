/**
 * Temper #115 on the free-flowing Team page, in the browser: Temper refusing to
 * run git over a member's folder, on Temper's real serializer output
 * (e2e/fixtures/team/flow/real-git, made by scripts/capture_team_fixtures.py
 * --only git). Every /api/team answer comes from those files, so no Temper is
 * needed and nothing is sent.
 *
 * One happy-path journey per run (owner's test rule bp-be8d76b9): the resting
 * member's card and the feed rows read as Temper's words with Temper as the
 * actor, never quoted as the member's own note and never a bare engine word;
 * axe finds nothing and every target is at least 24 px, in both themes, on a
 * phone and a desktop. The word-level contract is
 * src/__tests__/teamGlanceGitRefused.test.ts.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { expect, test, type Page } from '@playwright/test';
import { expectAxeClean, expectTargets, glanceFontsSettled, nothingSent, serveActions, serveTeam, shoot } from './team-helpers';

type Raw = Record<string, unknown>;
type Feed = { events: Raw[]; as_of: string };

const DIR = path.join(process.cwd(), 'e2e/fixtures/team/flow/real-git');
/** Shots for review with GIT_SHOTS=<folder>: <run>-<theme>-<width>.png. */
const SHOTS = process.env.GIT_SHOTS;
test.use({ timezoneId: 'America/Los_Angeles' });

type Run = 'git_rest' | 'git_writer';
function real(name: Run, feed = false): Raw {
  return JSON.parse(readFileSync(path.join(DIR, `${name}${feed ? '-events' : ''}.json`), 'utf8')) as Raw;
}
/** Temper's reason on the run's one sync_refused event. */
const syncReason = (name: Run) => ((real(name, true) as unknown as Feed).events.find((e) => e.kind === 'sync_refused') as { reason: string }).reason;

async function open(page: Page, name: Run) {
  const run = real(name);
  await page.clock.setFixedTime(new Date(run.as_of as string));
  const sent = nothingSent();
  await serveTeam(page, { run: () => ({ route: '', status: 200, body: real(name) }) });
  await serveActions(page, sent, {});
  // Set up after serveTeam, so it answers the feed first.
  await page.route(/\/api\/team\/runs\/[^/]+\/events(\?|$)/, async (route) => {
    const url = new URL(route.request().url());
    const after = Number(url.searchParams.get('after') ?? '0');
    const feed = real(name, true) as unknown as Feed;
    const events = feed.events.filter((e) => (e.seq as number) > after && (e.seq as number) <= (run.events_cursor as number));
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ events, cursor: Math.max(after, run.events_cursor as number), more: false, as_of: feed.as_of }),
    });
  });
  await page.goto(`/app/team/runs/${run.execution_id as string}`);
  await expect(page.getByTestId('glance-page')).toBeVisible();
  await expect(page.getByTestId('glance-just-sent')).not.toContainText('Reading the team');
  await glanceFontsSettled(page);
  return sent;
}

const REST = 'Temper couldn\u2019t share its work twice in a row (its folder holds a .git of its own)';

for (const theme of ['light', 'dark'] as const) {
  for (const { width, height } of [
    { width: 390, height: 844 },
    { width: 1440, height: 900 },
  ]) {
    test(`git refusals read as Temper's, ${theme}, ${width}x${height}`, async ({ page }) => {
      test.setTimeout(90_000);
      await page.setViewportSize({ width, height });
      await page.addInitScript((t) => localStorage.setItem('temper_theme', t), theme);

      // git_rest: Temper rested the builder after refusing git over its folder in two turns in a row.
      const sent = await open(page, 'git_rest');
      const builder = page.getByTestId(width >= 768 ? 'glance-map' : 'glance-list').locator('[data-member="builder"]');
      await expect(builder.getByTestId('glance-chip')).toHaveText(/^Resting/);
      await expect(builder.getByTestId('glance-on')).toHaveText(`${REST}. A message wakes it.`);
      await expect(page.getByTestId('glance-team-count')).toHaveText('1 working \u00b7 1 resting');
      const activity = page.getByRole('region', { name: 'All activity' });
      await expect(activity).toContainText(`builder is resting: ${REST}.`);
      await expect(activity).toContainText(
        `builder didn\u2019t get the team\u2019s latest shared work before this turn; the turn went ahead, and Temper told it why. Temper\u2019s reason: \u201c${syncReason('git_rest')}\u201d`,
      );
      const main = page.locator('main');
      // Temper's note is never the member's quoted words (only Temper's own message to the leader says it), and no
      // engine word shows bare.
      await expect(builder).not.toContainText('Temper refused to run git');
      await expect(main).not.toContainText(/went idle: \u201cTemper refused/);
      await expect(main).not.toContainText(/\bsync_refused\b|\bgit_refused\b/);
      await expectAxeClean(page);
      await expectTargets(page);
      if (SHOTS) await shoot(page, `git_rest-${theme}-${width}`, SHOTS);

      // git_writer: the sync was refused while Temper couldn't rule out a writer; that turn didn't start.
      await page.unrouteAll({ behavior: 'ignoreErrors' });
      const sentWriter = await open(page, 'git_writer');
      await expect(page.getByRole('region', { name: 'All activity' })).toContainText(
        `builder didn\u2019t get the team\u2019s latest shared work, so this turn didn\u2019t start. Temper\u2019s reason: \u201c${syncReason('git_writer')}\u201d`,
      );
      await expect(page.locator('main')).not.toContainText(/\bsync_refused\b/);
      await expectAxeClean(page);
      await expectTargets(page);
      if (SHOTS) await shoot(page, `git_writer-${theme}-${width}`, SHOTS);

      for (const s of [sent, sentWriter]) expect(s).toEqual(nothingSent());
    });
  }
}
