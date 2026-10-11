/** Final fields: one G7 journey and one scoped destructive-action journey per theme/width.
 * Paired serializer replies only; no Temper, model, server or project is started. */
import { mkdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { expect, test, type Page, type Locator } from '@playwright/test';
import { expectAxeClean, expectTargets, fixture, glanceFontsSettled, nothingSent, serveActions, serveTeam } from './team-helpers';

type Raw = Record<string, unknown>;
const FLOW = path.join(process.cwd(), 'e2e/fixtures/team/flow');
const sample = (name: string, feed = false): Raw => JSON.parse(readFileSync(path.join(FLOW, `${name}${feed ? '-events' : ''}.json`), 'utf8')) as Raw;
const G7 = ['starting', 'check_in_not_asked', 'draining', 'stopped', 'stopped_check_in', 'failed', 'didnt_start'] as const;
const SHOTS = process.env.FIELDS_SHOTS;
test.use({ timezoneId: 'America/Los_Angeles' });

async function sound(page: Page) {
  await expectAxeClean(page);
  await expectTargets(page);
  expect(await page.locator('main').evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
}
async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
}
async function actions44(dialog: Locator) {
  for (const action of await dialog.getByRole('button').all()) {
    const r = await action.boundingBox();
    expect(r, await action.textContent()).not.toBeNull();
    expect(r!.height).toBeGreaterThanOrEqual(44);
    expect(r!.width).toBeGreaterThanOrEqual(44);
  }
  expect(await dialog.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
}

for (const theme of ['dark', 'light']) for (const [width, height] of [[1440, 900], [1024, 768], [390, 844], [320, 844]]) {
  test(`G7 journey: exact paired truth, D121 terminal counter-cases, ${theme}, ${width}`, async ({ page }) => {
    test.setTimeout(240_000);
    await page.setViewportSize({ width, height });
    await page.addInitScript((t) => localStorage.setItem('temper_theme', t), theme);
    await page.clock.install();
    const state = { name: 'real-g7/starting' };
    const sent = nothingSent();
    const seen = await serveTeam(page, { run: () => ({ route: '', status: 200, body: sample(state.name) }) });
    await serveActions(page, sent, {});
    let feeds = 0;
    await page.route(/\/api\/team\/runs\/[^/]+\/events(\?|$)/, async (route) => {
      feeds++;
      const feed = sample(state.name, true);
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(feed) });
    });
    for (const name of G7) await test.step(name, async () => {
      state.name = `real-g7/${name}`;
      const run = sample(state.name);
      await page.clock.setFixedTime(new Date(run.as_of as string));
      await page.goto(`/app/team/runs/${run.execution_id as string}`);
      await expect(page.getByTestId('glance-page')).toHaveAttribute('data-phase', (run.phase as Raw).name as string);
      await expect(page.getByTestId('glance-just-sent')).not.toContainText('Reading the team');
      await glanceFontsSettled(page);
      const members = page.getByTestId(width >= 768 ? 'glance-map' : 'glance-list').locator('[data-member]');
      const terminal = ['stopped', 'stopped_check_in', 'failed', 'didnt_start'].includes(name);
      if (terminal) {
        for (const chip of await members.getByTestId('glance-chip').all()) await expect(chip).toHaveText('Ended');
        for (const on of await members.getByTestId('glance-on').all()) await expect(on).toHaveText(/^Last:/);
        await expect(page.getByRole('button', { name: 'Stop project', exact: true })).toHaveCount(0);
        await expect(page.getByRole('switch', { name: 'Animate messages' })).toHaveCount(0);
        await expect(page.locator('.glance-busy, .glance-dot, .glance-extra')).toHaveCount(0);
        await expect(page.getByTestId('glance-answers')).toHaveCount(0);
      }
      if (name === 'starting') {
        expect((run.members as Raw[]).every((m) => m.turns === 0)).toBe(true);
        await expect(page.getByTestId('glance-now-word')).toHaveText('Starting');
        await expect(page.getByRole('button', { name: 'Stop project', exact: true })).toHaveCount(1);
      } else if (name === 'check_in_not_asked') {
        await expect(page.getByTestId('glance-now-word')).toContainText('finishing turns');
        await expect(page.getByTestId('glance-you')).toContainText('Nothing needs you yet');
        await expect(page.getByTestId('glance-answers')).toHaveCount(0);
        expect((run.phase as Raw).running).toBe(1);
      } else if (name === 'draining') {
        await expect(page.getByTestId('glance-now-word')).toHaveText('Temper is restarting');
        await expect(page.getByTestId('glance-now-sentence')).toHaveText('The team carries on after it.');
        await expect(members.getByTestId('glance-chip').filter({ hasText: /Finishing its turn/ })).toHaveCount(2);
      } else if (name === 'stopped') {
        await expect(page.getByTestId('glance-now-word')).toHaveText('Stopped');
        await expect(page.getByTestId('glance-now-sentence')).toHaveText('The run was cancelled');
      } else if (name === 'failed') {
        await expect(page.getByTestId('glance-now-word')).toHaveText('Failed');
        await expect(page.getByTestId('glance-now-sentence')).toHaveText('Account anthropic-4 refused the call (not allowed for this organization); the team was stopped');
        expect((run.members as Raw[]).some((m) => (m.turns as number) > 0)).toBe(true);
        for (const card of await members.all()) await expect(card).not.toContainText('No work started.');
      } else if (name === 'didnt_start') {
        await expect(page.getByTestId('glance-now-word')).toHaveText('Failed to start');
        await expect(page.getByTestId('glance-now-sentence')).toHaveText((run.phase as Raw).reason as string);
        await expect(page.getByTestId('glance-now-reason')).toHaveCount(0);
        await expect(page.getByTestId('glance-you')).toContainText('Nothing needs you');
        await expect(page.getByTestId('glance-you')).toContainText('You can start a new project.');
        await expect(page.getByRole('link', { name: 'New project', exact: true })).toHaveAttribute('href', /\/team\/new$/);
        await expect(page.getByRole('main')).toContainText('Start requested by you');
        await expect(page.getByRole('main')).not.toContainText(/\bran \d|\brunning \d|didnt_start|Read what it made|finishing its turn|of \d members working/);
        for (const on of await members.getByTestId('glance-on').all()) await expect(on).toHaveText('Last: No work started.');
        await expect(page.getByTestId('glance-spend')).toContainText(`$${((run.spend as Raw).cost_usd as number).toFixed(2)}`);
        await expect(page.getByTestId('glance-work-empty')).toHaveText('No shared version.');
        await expect(page.getByTestId('glance-version')).toHaveText('No shared version.');
        expect(sample(state.name, true).events).toEqual([]);
        await expect(page.getByRole('region', { name: 'Latest' }).getByRole('listitem')).toHaveCount(0);
        await expect(page.getByRole('region', { name: 'All activity' }).getByRole('listitem')).toHaveCount(0);
        await expect(page.getByRole('region', { name: 'All activity' })).toContainText('0 entries, newest first');
        await expect(page.getByRole('region', { name: 'All activity' })).toContainText('Nothing yet.');
        await expect(page.getByRole('region', { name: 'Latest' })).toContainText('Nothing big has happened yet.');
        await expect(page.getByRole('link', { name: 'All activity (0 entries)' })).toHaveCount(0);
        await expect(page.getByTestId('glance-working')).toHaveCount(0);
        await expect(page.locator('#glance-message')).toHaveCount(0);
        const before = await page.getByRole('main').innerText();
        const reads = seen.filter((p) => /^\/api\/team\/runs\/[^/?]+$/.test(p)).length;
        const feedReads = feeds;
        await page.clock.fastForward(120_000);
        expect(seen.filter((p) => /^\/api\/team\/runs\/[^/?]+$/.test(p)).length, 'terminal run polling').toBe(reads);
        expect(feeds, 'terminal feed polling').toBe(feedReads);
        expect(await page.getByRole('main').innerText(), 'no ticking work/age').toBe(before);
      }
      await sound(page);
      await shot(page, `g7-${name}-${theme}-${width}`);
    });
    // The older failed MEMBER remains a live recovery state, not the G7 failed TEAM.
    state.name = 'real/failed';
    await page.goto(`/app/team/runs/${sample(state.name).execution_id as string}`);
    await expect(page.getByTestId('glance-page')).toHaveAttribute('data-phase', 'waiting_for_owner');
    await page.getByTestId('glance-you').getByRole('button', { name: 'Answer', exact: true }).click();
    await expect(page.getByTestId('glance-answers')).toBeVisible();
    expect(sent).toEqual(nothingSent());
  });

  test(`H17 ordinary multiline Now reasons, unchanged activity and token classification, ${theme}, ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await page.addInitScript((t) => localStorage.setItem('temper_theme', t), theme);
    const sent = nothingSent();
    const state = { run: sample('real-g7/stopped'), feed: sample('real-g7/stopped', true) };
    await serveTeam(page, { run: () => ({ route: '', status: 200, body: state.run }) });
    await serveActions(page, sent, {});
    await page.route(/\/api\/team\/runs\/[^/]+\/events(\?|$)/, (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(state.feed) }));
    for (const [phase, supplied] of [
      ['stopped', 'the owner cancelled it.\nThe CSV is kept.\n'],
      ['failed', 'account refused the call.\nThe recorded work is kept.\n'],
      ['failed', 'account_refused\nThe genuine supplied explanation.\n'],
    ]) {
      state.run = sample(`real-g7/${phase}`);
      state.feed = sample(`real-g7/${phase}`, true);
      (state.run.phase as Raw).reason = supplied;
      const ending = (state.feed.events as Raw[]).find((e) => e.kind === 'ended');
      expect(ending).toBeTruthy();
      ending!.reason = supplied;
      await page.goto(`/app/team/runs/${state.run.execution_id as string}`);
      await expect(page.getByTestId('glance-page')).toHaveAttribute('data-phase', phase);
      await glanceFontsSettled(page);
      // textContent, not whitespace-normalised toHaveText: the final newline is part of the contract.
      const wanted = supplied.replace(/^./u, (first) => first.toUpperCase());
      expect(await page.getByTestId('glance-now-sentence').textContent()).toBe(wanted);
      const activity = page.getByRole('region', { name: 'All activity' });
      // Activity classifies its first line, unchanged: the token-only first line is suppressed there.
      const row = activity.locator(`[data-row="a${ending!.seq as number}"]`);
      if (supplied.startsWith('account_refused')) await expect(row).not.toContainText('account_refused');
      else await expect(row).toContainText(supplied.split('\n')[0]);
      await expect(row).not.toContainText(supplied.split('\n')[1]);
      const showAll = row.getByRole('button', { name: 'Show all' });
      await showAll.click();
      await expect(row).toContainText(supplied.split('\n')[1]);
      await expect(page.getByRole('button', { name: 'Stop project', exact: true })).toHaveCount(0);
      await expect(page.getByRole('switch', { name: 'Animate messages' })).toHaveCount(0);
      await sound(page);
      await shot(page, `h17-${phase}${supplied.startsWith('account_refused') ? '-token-text' : ''}-${theme}-${width}`);
    }
    expect(sent).toEqual(nothingSent());
  });

  test(`D123 scoped stop confirmations: cancel, pending, refusal, both routes and settings, ${theme}, ${width}`, async ({ page }) => {
    test.setTimeout(180_000);
    await page.setViewportSize({ width, height });
    await page.addInitScript((t) => localStorage.setItem('temper_theme', t), theme);
    const state = { name: 'real/check_in' };
    const sent = nothingSent();
    await serveTeam(page, { run: () => ({ route: '', status: 200, body: sample(state.name) }) });
    await page.route(/\/api\/team\/runs\/[^/]+\/events(\?|$)/, (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(sample(state.name, true)) }));
    let release!: () => void;
    const held = new Promise<void>((resolve) => { release = resolve; });
    await serveActions(page, sent, {
      cancel: [
        { until: held, then: { ...fixture('cancel-200'), body: { execution_id: 'fixture-flow', status: 'completed' } } },
        { route: '', status: 403, body: { detail: 'Stopping is refused in this fixture.' } },
        fixture('cancel-200'),
      ],
      answer: [{ route: '', status: 409, body: { detail: { reason: 'already_answered', message: 'Already answered by someone else.' } } }],
    });
    const go = async (name: string) => {
      state.name = name;
      await page.goto(`/app/team/runs/${sample(name).execution_id as string}`);
      await expect(page.getByTestId('glance-page')).toBeVisible();
      await glanceFontsSettled(page);
    };
    await go('real/check_in');
    const headerStop = page.getByRole('button', { name: 'Stop project', exact: true }).first();
    await headerStop.click();
    let dialog = page.getByRole('alertdialog', { name: 'Stop this project?' });
    await expect(dialog).toContainText('Ends this project and cancels its run.');
    await expect(dialog).toContainText('Workflow');
    await expect(dialog).toContainText(sample(state.name).workflow as string);
    await expect(dialog).toContainText("You can't undo this.");
    await expect(dialog.getByRole('button', { name: 'Stop project', exact: true })).not.toBeFocused();
    await actions44(dialog);
    await sound(page);
    await shot(page, `stop-header-${theme}-${width}`);
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    await expect(headerStop).toBeFocused();
    expect(sent.cancels).toEqual([]);
    await headerStop.click();
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
    expect(sent.cancels).toEqual([]);
    await headerStop.click();
    await dialog.getByRole('button', { name: 'Stop project', exact: true }).click();
    await expect(dialog.getByRole('button', { name: 'Stopping…' })).toBeDisabled();
    await expect(dialog.getByRole('button', { name: 'Cancel', exact: true })).toBeDisabled();
    expect(sent.cancels).toHaveLength(1);
    release();
    // Both the X and the post-response footer are named Close; only the footer has text.
    const responseClose = dialog.getByRole('button', { name: 'Close', exact: true }).filter({ hasText: /^Close$/ });
    await expect(responseClose).toBeVisible();
    await expect(responseClose).toBeFocused();
    await actions44(dialog);
    await responseClose.click();
    await expect(headerStop).toBeFocused();
    await headerStop.click();
    await dialog.getByRole('button', { name: 'Stop project', exact: true }).click();
    await expect(dialog).toContainText('Stopping is refused in this fixture.');
    await expect(dialog.getByRole('button', { name: 'Stop project', exact: true })).toBeEnabled();
    await actions44(dialog);
    await shot(page, `stop-refused-${theme}-${width}`);
    state.name = 'derived/stopped';
    await dialog.getByRole('button', { name: 'Stop project', exact: true }).click();
    await expect(dialog).toHaveCount(0);
    await expect(page.getByTestId('glance-page')).toHaveAttribute('data-phase', 'stopped');
    expect(sent.cancels).toHaveLength(3);

    for (const name of ['real/check_in', 'derived/settings', 'real/failed']) {
      await go(name);
      // A member question uses the existing answer view, unlike Temper's inline check-in/settings actions.
      if (name === 'real/failed') await page.getByTestId('glance-you').getByRole('button', { name: 'Answer', exact: true }).click();
      const stop = page.getByTestId('glance-answers').getByRole('button', { name: 'Stop project', exact: true });
      await stop.click();
      const settings = name.endsWith('settings');
      dialog = page.getByRole('alertdialog', { name: settings ? 'Stop this project at the settings check?' : 'Stop this project at this question?' });
      await expect(dialog).toContainText('Your answer: stop');
      await expect(dialog).toContainText(settings ? 'The project ends here, before anything runs with the new settings. Your last answer is not applied, and nothing more is spent.' : 'The project ends here and nothing more is spent.');
      await expect(dialog).toContainText(name === 'real/failed' ? 'will show this run as failed' : 'will show this run as cancelled, like Stop project');
      await expect(dialog.getByRole('button', { name: 'Stop project', exact: true })).not.toBeFocused();
      await actions44(dialog);
      await sound(page);
      await shot(page, `${settings ? 'stop-settings' : name === 'real/failed' ? 'stop-recovery' : 'stop-question'}-${theme}-${width}`);
      const count = sent.answers.length;
      await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
      await expect(stop).toBeFocused();
      expect(sent.answers).toHaveLength(count);
      if (!settings && name !== 'real/failed') {
        await stop.click();
        await dialog.getByRole('button', { name: 'Stop project', exact: true }).click();
        await expect(page.getByRole('main')).toContainText(/already answered/i);
        expect(sent.answers).toHaveLength(count + 1);
        expect(sent.answers.at(-1)?.answer).toBe('stop');
      }
    }
  });
}

test('S2: a literal 60-character no-space file name reflows at 390 and 320', async ({ page }) => {
  const file = 'x'.repeat(57) + '.md';
  const sent = nothingSent();
  await serveTeam(page, { run: () => ({ route: '', status: 200, body: sample('real-g6/conflict') }) });
  await serveActions(page, sent, {});
  const feed = sample('real-g6/conflict', true);
  const row = (feed.events as Raw[]).find((e) => e.seq === 24)!;
  Object.assign(row, { reason: `Fix ${file}.`, paths: [file] });
  await page.route(/\/api\/team\/runs\/[^/]+\/events(\?|$)/, (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(feed) }));
  for (const theme of ['dark', 'light']) for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await page.addInitScript((t) => localStorage.setItem('temper_theme', t), theme);
    await page.goto(`/app/team/runs/${sample('real-g6/conflict').execution_id as string}`);
    const region = page.getByRole('region', { name: 'All activity' });
    await expect(region.locator('code').filter({ hasText: file })).toHaveText(file);
    await expect(region.locator('code').filter({ hasText: file })).toHaveCSS('overflow-wrap', 'anywhere');
    expect(await region.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
    await sound(page);
  }
});
