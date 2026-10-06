/**
 * The Team page in a real browser: the shared parts, the read-only run view
 * and the run page's way in.
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
import { expect, test, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { startSmokeRun } from './helpers';

interface Fixture {
  route: string;
  status: number;
  body: unknown;
}

function fixture(name: string): Fixture {
  const file = path.join(process.cwd(), 'e2e/fixtures/team', `${name}.json`);
  return JSON.parse(readFileSync(file, 'utf8')) as Fixture;
}

const RUN_ID = (fixture('run-running').body as { execution_id: string }).execution_id;
const SHOTS = process.env.TEAM_SHOTS;
const AXE_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'];

/** A fixture's body with the run's id swapped for another (a real run on this server). */
function asRun(name: string, executionId: string): Fixture {
  const f = fixture(name);
  return { ...f, body: { ...(f.body as object), execution_id: executionId } };
}

/**
 * Serve /api/team/* from fixtures. `run` is a list: each read of the run
 * takes the next answer and the last one repeats.
 */
async function serveTeam(
  page: Page,
  { status = fixture('status-on'), run = [fixture('run-running')], message = fixture('message-read') }: {
    status?: Fixture;
    run?: Fixture[];
    message?: Fixture;
  } = {},
): Promise<string[]> {
  const seen: string[] = [];
  let reads = 0;
  await page.route('**/api/team/**', async (route) => {
    const { pathname } = new URL(route.request().url());
    seen.push(pathname);
    let answer: Fixture;
    if (pathname === '/api/team/status') answer = status;
    else if (/^\/api\/team\/runs\/[^/]+\/messages\/[^/]+$/.test(pathname)) answer = message;
    else if (/^\/api\/team\/runs\/[^/]+$/.test(pathname)) answer = run[Math.min(reads++, run.length - 1)];
    else answer = { route: '', status: 404, body: { detail: 'Not Found' } };
    await route.fulfill({ status: answer.status, contentType: 'application/json', body: JSON.stringify(answer.body) });
  });
  return seen;
}

/** axe on the whole page: nothing found. */
async function expectAxeClean(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze();
  const found = results.violations.map((v) => `${v.id} (${v.impact}): ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`);
  expect(found, 'axe found problems').toEqual([]);
}

/** Every button and link on the Team page is at least 24 x 24 px (WCAG 2.5.8). */
async function expectTargets(page: Page) {
  const small = await page.locator('main').evaluate((main) => {
    const out: string[] = [];
    for (const el of main.querySelectorAll<HTMLElement>('a[href], button, [role="button"], summary')) {
      const box = el.getBoundingClientRect();
      if (box.width === 0 && box.height === 0) continue;
      if (box.width < 24 || box.height < 24) {
        out.push(`${el.tagName.toLowerCase()} "${(el.textContent ?? '').trim().slice(0, 40)}" ${box.width.toFixed(0)}x${box.height.toFixed(0)}`);
      }
    }
    return out;
  });
  expect(small, 'targets under 24 px').toEqual([]);
}

async function shoot(page: Page, name: string) {
  if (SHOTS) await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: true });
}

/** The run view states this part of the page covers, and what each must show. */
const RUN_STATES: { fixture: string; shows: RegExp | string }[] = [
  { fixture: 'run-starting', shows: 'Starting: no member turn has begun yet' },
  { fixture: 'run-running', shows: 'Who did what' },
  { fixture: 'run-interrupted', shows: 'Interrupted: resume it from the run page' },
  { fixture: 'run-paused', shows: 'Paused after round 1' },
  { fixture: 'run-quiet', shows: 'Quiet: the team has nothing left to do' },
  { fixture: 'run-member-waiting', shows: /didn't finish/ },
  { fixture: 'run-member-waiting-question', shows: 'maker asks you' },
  { fixture: 'run-done', shows: /^Ended/ },
  { fixture: 'run-stopped', shows: 'Your words' },
  { fixture: 'run-failed', shows: /^Ended/ },
  { fixture: 'run-didnt-start', shows: /^Ended/ },
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
          await expectAxeClean(page);
          await expectTargets(page);
          await shoot(page, `${tag}-${name}`);
        });
      }

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

      test('run view: one message opened', async ({ page }) => {
        await serveTeam(page);
        await page.goto(`/app/team/runs/${RUN_ID}`);
        await page.getByRole('button', { name: /^Open/ }).first().click();
        await expect(page.getByText(/The heading wraps to three lines on a phone/)).toBeVisible();
        await expect(page.getByRole('button', { name: /^Close/ }).first()).toHaveAttribute('aria-expanded', 'true');
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
        await expectAxeClean(page);
        await shoot(page, `${tag}-not-team`);
      });

      for (const [where, url, notice] of [
        ['trials', '/app/team', 'The trials list is still being built.'],
        ['roles', '/app/team/roles', 'The roles list is still being built.'],
        ['new trial', '/app/team/new', 'Starting a trial from here is still being built.'],
      ] as const) {
        test(`Team page: ${where}`, async ({ page }) => {
          await serveTeam(page);
          await page.goto(url);
          await expect(page.getByRole('heading', { level: 1, name: 'Team' })).toBeVisible();
          await expect(page.getByText(notice)).toBeVisible();
          const nav = page.getByRole('navigation', { name: 'Main navigation' });
          await expect(nav.getByRole('link', { name: 'Team' })).toBeVisible();
          await expectAxeClean(page);
          await expectTargets(page);
          await shoot(page, `${tag}-page-${where.replace(' ', '-')}`);
        });
      }

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
