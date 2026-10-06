/**
 * The Team page's part C in a real browser: the trials list, the roles, the
 * Run trial form, the message composer, the guard notice and the settings
 * wait (contract E24), plus a wait of a kind the page doesn't know.
 *
 * Every /api/team route is served from the fixtures the routes really
 * answered (e2e/fixtures/team, made by scripts/capture_team_fixtures.py) or
 * from a fixture changed for a stress case, so the tests run on a server
 * with the Team switch off, start no trial and call no model. Each state is
 * looked at in both themes at 1024 and 1440 px and must pass axe (WCAG 2.2
 * A/AA and best practice) with nothing found, with every target at least
 * 24 px; the behaviour (what is sent, request ids, polling, paging,
 * keyboard) is checked once, at 1440 px.
 *
 * Screenshots for reading against Design's boards go to TEAM_SHOTS when set.
 */
import { expect, test, type Page } from '@playwright/test';
import {
  answers,
  card,
  expectAxeClean,
  expectTargets,
  type Fixture,
  fixture,
  nothingSent,
  openRun,
  pick,
  refusalText,
  type Reply,
  RUN_ID,
  serveActions,
  serveTeam,
  shoot,
  withBody,
} from './team-helpers';

type Item = Record<string, unknown> & { trial_id: string; execution_id: string; workflow: string; started_at: string };

const TRIALS_POLL_MS = 5000;

/** `total` trials made from the captured ones, each with its own ids, newest first; served by limit and offset. */
function manyTrials(total = 57): (url: URL) => Fixture {
  const base = (fixture('trials-list').body as { trials: Item[] }).trials;
  const items: Item[] = Array.from({ length: total }, (_, i) => {
    const t = base[i % base.length];
    const id = (0xa00000000000 + i).toString(16);
    return {
      ...t,
      trial_id: id,
      execution_id: `${(0xb0000000 + i).toString(16)}-0000-4000-8000-${id}`,
      workflow: `team-trial-${id}`,
      started_at: new Date(Date.parse(t.started_at) - i * 3_600_000).toISOString(),
    };
  });
  // The 26th is a re-run of the 25th's trial: page 2 opens on it (A-8).
  items[25] = { ...items[25], trial_id: items[24].trial_id, workflow: items[24].workflow, goal_first_line: items[24].goal_first_line };
  return (url) => {
    const limit = Number(url.searchParams.get('limit') ?? 50);
    const offset = Number(url.searchParams.get('offset') ?? 0);
    return { route: 'GET /api/team/trials', status: 200, body: { total, trials: items.slice(offset, offset + limit) } };
  };
}

/** Board S5: fourteen roles from the box's list, one of which can't join. */
function manyRoles(): Fixture {
  const ids = ['analyst', 'architect', 'backend', 'builder', 'data', 'designer', 'docs', 'frontend', 'ops', 'planner', 'product', 'reviewer', 'scribe', 'security'];
  return withBody('roles-ok', (body) => ({
    ...body,
    roles: ids.map((id) => ({
      id,
      title: id[0].toUpperCase() + id.slice(1),
      about: `# ${id[0].toUpperCase() + id.slice(1)}\n\nWhat the ${id} role does on a team, in a few lines.`,
      has_home_chat: id !== 'docs',
      problems: id === 'scribe' ? ["role 'scribe': its about page (about.md) is missing or unreadable"] : [],
    })),
  }));
}

/** The captured role list plus a role whose id is a reserved name (board F2). */
function rolesWithTemper(): Fixture {
  return withBody('roles-ok', (body) => ({
    ...body,
    roles: [
      ...(body.roles as unknown[]),
      { id: 'temper', title: 'Temper', about: '# Temper\n\nKeeps the trial on track.', has_home_chat: false, problems: [] },
    ],
  }));
}

/** Board S1: a check that finds 26 problems, every place one can sit. */
const S1_PROBLEMS = [
  { field: 'goal', text: 'goal: the goal is empty' },
  { field: 'pause_after_rounds', text: 'pause_after_rounds: give how many rounds without done pause the team (1 or more)' },
  { field: 'communication', text: "communication: 'edges' comes later; use 'all'" },
  { field: 'project_path', text: 'project: the folder must be an absolute path' },
  { field: 'leader', text: "mode: leader 'nobody' is not a member (members: lead, maker, checker)" },
  { field: null, text: 'roles: role list not configured (set TEMPER_PI_BOX_CONFIG to the worker box config)' },
  ...Array.from({ length: 20 }, (_, i) => ({
    field: 'members',
    member: ['lead', 'maker', 'checker'][i % 3],
    text: `member '${['lead', 'maker', 'checker'][i % 3]}': problem ${i + 1} of the stress list, word for word`,
  })),
];

const s1Check = (): Fixture => ({ route: 'POST /api/team/check', status: 200, body: { ok: false, problems: S1_PROBLEMS, notes: [] } });

const checkWithNote = (): Fixture =>
  withBody('check-ok', (body) => ({ ...body, notes: [{ field: 'project_path', text: 'folder checks run when the Pi lane starts the team' }] }));

/** A reply held until the test lets it go, to see the page while it waits. */
function held(then: Fixture | 'no reply'): { reply: Reply; until: Promise<void>; release: () => void } {
  let release = () => {};
  const until = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { reply: { until, then }, until, release };
}

/** Hold every read of a Team list (`/api/team/trials` or `/api/team/roles`) until released. */
async function holdReads(page: Page, pathname: string, answer: Fixture) {
  const wait = held(answer);
  // Registered after serveTeam, so it answers these reads first.
  await page.route(
    (url) => url.pathname === pathname,
    async (route) => {
      if (route.request().method() !== 'GET') return route.fallback();
      await wait.until;
      await route.fulfill({ status: answer.status, contentType: 'application/json', body: JSON.stringify(answer.body) });
    },
  );
  return wait.release;
}

const trialsList = (page: Page) => page.getByRole('list', { name: 'Trials' });
const trialRows = (page: Page) => page.locator('[data-trial-row]');
const tabs = (page: Page) => page.getByRole('navigation', { name: 'Team' });
const banner = (page: Page) => page.locator('[data-guard-mode]');
const form = (page: Page) => page.getByTestId('team-form');
const formResult = (page: Page) => page.getByTestId('team-form-result');
const problemsBox = (page: Page) => page.getByTestId('team-form-problems');
const member = (page: Page, n: number) => form(page).getByRole('group', { name: `Member ${n}`, exact: true });
const composer = (page: Page) => page.locator('[data-card="composer"]');
const messageResult = (page: Page) => page.getByTestId('team-message-result');
const timeline = (page: Page) => page.getByRole('region', { name: 'Timeline' });

/** The timeline shows its newest entries first; open the rest. */
async function wholeTimeline(page: Page) {
  await timeline(page).getByRole('button', { name: 'Show all' }).click();
}
const trialsReads = (seen: string[]) => seen.filter((p) => p.startsWith('/api/team/trials')).length;

/** Open the trials list (or another Team page) with the API served from fixtures. */
async function openTeam(page: Page, url: string, serve: Parameters<typeof serveTeam>[1] = {}) {
  const seen = await serveTeam(page, serve);
  const sent = nothingSent();
  return { seen, sent, go: () => page.goto(url) };
}

/** Fill the form's members: [role, team name or '' to keep the default]. The first leads unless `leader` says. */
async function fillMembers(page: Page, members: [string, string][], leader = 1) {
  for (let i = 0; i < members.length; i++) {
    if (i > 0) await form(page).getByRole('button', { name: 'Add member' }).click();
    const row = member(page, i + 1);
    const [role, name] = members[i];
    if (role) await row.getByLabel('Role').selectOption(role);
    if (name) await row.getByLabel('Team name').fill(name);
  }
  await member(page, leader).getByRole('radio', { name: 'Leader' }).check();
}

/** A form the server would take: a goal, two members, a pause. */
async function fillForm(page: Page) {
  await page.locator('#team-goal').fill('Write a short welcome note for the notes app.');
  await fillMembers(page, [
    ['planner', 'lead'],
    ['builder', 'maker'],
  ]);
  await page.locator('#team-pause').fill('2');
}

async function openForm(page: Page, serve: Parameters<typeof serveTeam>[1] = {}, replies: { check?: Reply[]; trial?: Reply[] } = {}) {
  const seen = await serveTeam(page, serve);
  const sent = nothingSent();
  await serveActions(page, sent, replies);
  await page.goto('/app/team/new');
  await expect(page.getByRole('heading', { level: 1, name: 'New trial' })).toBeVisible();
  await expect(member(page, 1).getByLabel('Role')).toBeEnabled();
  return { seen, sent };
}

for (const theme of ['dark', 'light'] as const) {
  for (const width of [1024, 1440]) {
    test.describe(`Team page C, ${theme}, ${width} px`, () => {
      test.use({ viewport: { width, height: 900 } });
      const tag = `${theme}-${width}`;

      test.beforeEach(async ({ page }) => {
        await page.addInitScript((t) => localStorage.setItem('temper_theme', t), theme);
      });

      async function looks(page: Page, name: string) {
        await expectAxeClean(page);
        await expectTargets(page);
        await shoot(page, `${tag}-${name}`);
      }

      // ---- Trials (boards T1, T1-light, T2, T3, T3b) -------------------------------------------

      test('trials: rows, needs you, stopped and failed (T1)', async ({ page }) => {
        const { go } = await openTeam(page, '/app/team');
        await go();
        await expect(page.getByRole('heading', { level: 1, name: 'Team' })).toBeVisible();
        await expect(trialRows(page)).toHaveCount(4);
        await expect(tabs(page).getByRole('link', { name: 'Trials 4' })).toHaveAttribute('aria-current', 'page');
        await expect(tabs(page).getByRole('link', { name: 'Roles 4' })).toBeVisible();
        await expect(page.getByText(/^Updated \d/)).toBeVisible();
        // One row needs the owner: amber, with its chip.
        const needs = trialRows(page).and(page.locator('[data-needs-you]'));
        await expect(needs).toHaveCount(1);
        await expect(needs).toContainText('Name the three buttons on the share dialog.');
        await expect(needs.locator('[data-chip="needs-you"]')).toHaveText('needs you');
        await expect(needs).toContainText('by temper-ci');
        // The stopped row pairs with the run list's own status (E18).
        const stopped = trialRows(page).filter({ hasText: "Tidy the settings page's wording." });
        await expect(stopped).toContainText('Stopped');
        await expect(stopped).toContainText('run list: cancelled');
        await expect(stopped).toContainText('unknown caller');
        const failed = trialRows(page).filter({ hasText: 'Make the empty notes list say what to do first.' });
        await expect(failed).toContainText('Failed');
        await expect(failed.getByLabel('no round yet')).toHaveText('—');
        await expect(failed).not.toContainText('run list:');
        // The goal opens the Team run view; Run page opens the run page.
        const first = (fixture('trials-list').body as { trials: Item[] }).trials[0];
        await expect(needs.getByRole('link', { name: 'Name the three buttons on the share dialog.' })).toHaveAttribute(
          'href',
          `/app/team/runs/${first.execution_id}`,
        );
        await expect(needs.getByRole('link', { name: 'Run page' })).toHaveAttribute('href', `/app/workflow/${first.execution_id}`);
        await expect(needs).toContainText(`${first.workflow} · Leader lead (planner) · maker (builder), checker (reviewer)`);
        await expect(page.getByTestId('trials-showing')).toHaveText('Showing 1–4 of 4 · newest first');
        await expect(banner(page)).toBeVisible();
        // From 1280 px a row is one line under the column names (T1); at 1024 it stacks (T1 at 1024),
        // and the goal has the row's whole width.
        const columnNames = page.locator('[data-column-names]');
        if (width >= 1280) await expect(columnNames).toBeVisible();
        else await expect(columnNames).toBeHidden();
        const goalLink = needs.getByRole('link', { name: 'Name the three buttons on the share dialog.' });
        expect(await goalLink.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
        // The unknown-caller chip never breaks inside.
        const chip = stopped.locator('[data-who="unknown"]');
        expect(await chip.evaluate((el) => el.getClientRects().length === 1 && el.getBoundingClientRect().height < 30)).toBe(true);
        await looks(page, 'trials');
      });

      test('trials: a trial with a re-run and a fork, grouped (A-8)', async ({ page }) => {
        const { go } = await openTeam(page, '/app/team', { trials: fixture('trials-with-reruns') });
        await go();
        await expect(trialRows(page)).toHaveCount(4);
        const group = trialsList(page).getByRole('listitem').filter({ hasText: "Tidy the settings page's wording." }).first();
        const subs = group.getByRole('list', { name: 'Re-runs and forks' }).locator('[data-trial-subrow]');
        await expect(subs).toHaveCount(2);
        await expect(subs.nth(0)).toContainText('Re-run or fork from the run page');
        await expect(subs.nth(0)).toContainText('run 3eacb8a3');
        await expect(subs.nth(0)).toContainText('Running');
        await expect(subs.nth(0)).toContainText('$0.18');
        await expect(subs.nth(0)).toContainText('You');
        await expect(subs.nth(1)).toContainText('run 9b1e7c42');
        await expect(subs.nth(1)).toContainText('Done');
        await expect(subs.nth(1)).toContainText('round 2');
        await expect(page.getByTestId('trials-showing')).toHaveText('Showing 1–6 of 6 · newest first');
        if (width >= 1280) {
          // Every column after the trial lines up under its column name, in the re-run rows too (T1).
          const lefts = (el: Element) => Array.from(el.children).slice(1).map((c) => c.getBoundingClientRect().left);
          const head = await group.locator('[data-trial-row]').first().evaluate(lefts);
          expect(head).toHaveLength(5);
          for (const i of [0, 1]) {
            const sub = await subs.nth(i).evaluate(lefts);
            sub.forEach((x, k) => expect(Math.abs(x - head[k])).toBeLessThanOrEqual(1));
          }
        }
        await looks(page, 'trials-reruns');
      });

      test('trials: a trial waiting at a settings check', async ({ page }) => {
        const { go } = await openTeam(page, '/app/team', { trials: fixture('trials-settings') });
        await go();
        const row = trialRows(page).first();
        await expect(row).toHaveAttribute('data-needs-you', 'true');
        await expect(row).toContainText('Settings changed');
        await expect(row).toContainText('settings changed while it waited');
        await looks(page, 'trials-settings');
      });

      test('trials: 57 trials, page 1 and page 2 (T1 paging)', async ({ page }) => {
        const { go } = await openTeam(page, '/app/team', { trials: manyTrials() });
        await go();
        await expect(trialRows(page)).toHaveCount(25);
        await expect(page.getByTestId('trials-showing')).toHaveText('Showing 1–25 of 57 · newest first');
        await expect(page.getByRole('button', { name: 'Previous' })).toBeDisabled();
        await expect(tabs(page).getByRole('link', { name: 'Trials 57' })).toBeVisible();
        await looks(page, 'trials-page-1');
        await page.getByRole('button', { name: 'Next' }).click();
        await expect(page.getByTestId('trials-showing')).toHaveText('Showing 26–50 of 57 · newest first');
        // Page 2 opens on a re-run of a trial from page 1: it says which trial.
        const top = trialsList(page).locator('[data-trial-subrow]').first();
        await expect(top).toHaveAttribute('data-orphan', 'true');
        await expect(top).toContainText('of team-trial-a00000000018');
        await looks(page, 'trials-page-2');
      });

      test('trials: none yet (T2)', async ({ page }) => {
        const { go } = await openTeam(page, '/app/team', { trials: fixture('trials-empty') });
        await go();
        await expect(page.getByRole('heading', { name: 'No trials yet' })).toBeVisible();
        await expect(
          page.getByText(
            "A trial puts a few pi roles on one goal. They work in rounds, review each other's work and stop when the leader's version is approved. Start one with New trial at the top right.",
          ),
        ).toBeVisible();
        await expect(tabs(page).getByRole('link', { name: 'Trials 0' })).toBeVisible();
        await expect(page.getByTestId('trials-showing')).toHaveCount(0);
        await looks(page, 'trials-empty');
      });

      test('trials: loading', async ({ page }) => {
        await serveTeam(page);
        const release = await holdReads(page, '/api/team/trials', fixture('trials-list'));
        await page.goto('/app/team');
        await expect(page.getByRole('status').filter({ hasText: 'Loading the trials…' })).toBeVisible();
        await looks(page, 'trials-loading');
        release();
        await expect(trialRows(page)).toHaveCount(4);
      });

      test("trials: Temper couldn't be read (T3b)", async ({ page }) => {
        const { go } = await openTeam(page, '/app/team', { trials: fixture('trials-error') });
        await go();
        const note = page.locator('[data-note="bad"]').filter({ hasText: "Couldn't load the trials." });
        await expect(note).toBeVisible();
        await expect(note).toContainText('Temper said:');
        await expect(note).toContainText('Internal Server Error');
        await expect(note).toContainText('Nothing changed. The page tries again every 5 s while it is open.');
        await expect(note.getByRole('button', { name: 'Try again' })).toBeVisible();
        await looks(page, 'trials-error');
      });

      test('trials: a refresh that failed keeps the rows (T3)', async ({ page }) => {
        let reads = 0;
        const { go } = await openTeam(page, '/app/team', {
          trials: () => (reads++ === 0 ? fixture('trials-list') : fixture('trials-error')),
        });
        await go();
        await expect(trialRows(page)).toHaveCount(4);
        const note = page.locator('[data-note="warn"]').filter({ hasText: "Couldn't refresh at" });
        await expect(note).toBeVisible({ timeout: TRIALS_POLL_MS + 5000 });
        await expect(note).toContainText('Trying again every 5 s.');
        await expect(trialRows(page)).toHaveCount(4);
        await expect(page.getByText(/^Updated .* · not current$/)).toBeVisible();
        await looks(page, 'trials-refresh-failed');
      });

      // ---- Roles (boards L1, L1-light, L1b, L2, L3, L4, S5) -----------------------------------

      test('roles: the table and an about page (L1, L1b)', async ({ page }) => {
        const { go } = await openTeam(page, '/app/team/roles');
        await go();
        const table = page.getByRole('table', { name: 'Roles' });
        await expect(table.getByRole('row')).toHaveCount(5);
        await expect(page.getByTestId('roles-summary')).toHaveText(
          "4 roles from the box's role list · 1 can't join yet. Read only: roles are made and changed in pi, not here.",
        );
        const scribe = page.locator('[data-role-row="scribe"]');
        await expect(scribe).toHaveAttribute('data-cant-join', 'true');
        await expect(scribe).toContainText("Can't join");
        await expect(scribe).toContainText("role 'scribe': its about page (about.md) is missing or unreadable");
        await expect(page.locator('[data-role-row="planner"]')).toContainText('Can join');
        await expect(tabs(page).getByRole('link', { name: 'Roles 4' })).toHaveAttribute('aria-current', 'page');
        await looks(page, 'roles');
        await page.getByRole('button', { name: 'About page: reviewer' }).click();
        const sheet = page.getByTestId('role-about-sheet');
        await expect(sheet).toBeVisible();
        await expect(sheet.getByRole('heading', { name: 'Reviewer' }).first()).toBeVisible();
        await expect(sheet).toContainText('Shown as markdown, never as HTML. From the role\u2019s about.md.'.replace('\u2019', "'"));
        await looks(page, 'roles-about');
      });

      test("roles: the role list isn't set up (L2)", async ({ page }) => {
        const { go } = await openTeam(page, '/app/team/roles', { roles: fixture('roles-not-set-up') });
        await go();
        const note = page.locator('[data-note="warn"]').filter({ hasText: "The role list isn't set up" });
        await expect(note).toContainText('Temper said:');
        await expect(note).toContainText((fixture('roles-not-set-up').body as { problem: string }).problem);
        await expect(note).toContainText("No roles can join a team until it is. Trials can't start; the trials list still shows past trials.");
        await expect(tabs(page).getByRole('link', { name: 'Roles 0' })).toBeVisible();
        await looks(page, 'roles-not-set-up');
      });

      test('roles: loading (L3)', async ({ page }) => {
        await serveTeam(page);
        const release = await holdReads(page, '/api/team/roles', fixture('roles-ok'));
        await page.goto('/app/team/roles');
        await expect(page.getByRole('status').filter({ hasText: 'Loading the role list…' })).toBeVisible();
        await expect(page.getByRole('table', { name: 'Roles' })).toHaveAttribute('aria-busy', 'true');
        await looks(page, 'roles-loading');
        release();
        await expect(page.locator('[data-role-row]')).toHaveCount(4);
      });

      test("roles: Temper couldn't be read (L4)", async ({ page }) => {
        const { go } = await openTeam(page, '/app/team/roles', {
          roles: { route: '', status: 500, body: 'Internal Server Error' },
        });
        await go();
        const note = page.locator('[data-note="bad"]').filter({ hasText: "Couldn't load the role list." });
        await expect(note).toContainText('Temper said:');
        await expect(note).toContainText('Nothing changed. The page tries again every 5 s while it is open.');
        await expect(note.getByRole('button', { name: 'Try again' })).toBeVisible();
        await looks(page, 'roles-error');
      });

      test("roles: fourteen roles, one can't join (S5)", async ({ page }) => {
        const { go } = await openTeam(page, '/app/team/roles', { roles: manyRoles() });
        await go();
        await expect(page.locator('[data-role-row]')).toHaveCount(14);
        await expect(page.getByTestId('roles-summary')).toContainText("14 roles from the box's role list · 1 can't join yet.");
        await expect(page.locator('[data-role-row="docs"]')).toContainText('No');
        await looks(page, 'roles-stress');
      });

      // ---- The Run trial form (boards F1, F2, F2b, F3, F3-light, F4a, F4b, F5, S1, S2, S6) -----

      test('form: empty (F1)', async ({ page }) => {
        await openForm(page);
        await expect(page.getByRole('navigation', { name: 'Breadcrumb' })).toContainText('Team');
        await expect(page.locator('#team-members-count')).toHaveText('1 of up to 6');
        await expect(page.locator('#team-pause')).toHaveValue('');
        await expect(member(page, 1).getByRole('checkbox', { name: 'Bash' })).toBeDisabled();
        await expect(page.locator('#team-bash-why')).toContainText('Bash is off until owner-only writes are enforced (#45)');
        await expect(page.getByRole('radio', { name: /^edges/ })).toBeDisabled();
        await expect(page.getByText('comes later', { exact: true })).toBeVisible();
        const aside = page.getByRole('complementary', { name: 'About this trial' });
        await expect(aside).toContainText('claude-opus-5-5 · anthropic · thinking max');
        await expect(aside).toContainText('Every member uses these. Choosing per member comes later.');
        await expect(page.locator('#team-project-help')).toContainText('/srv/example/projects/notes-app');
        await expect(member(page, 1).getByLabel('Role').locator('option', { hasText: "scribe: Scribe (can't join)" })).toBeDisabled();
        await looks(page, 'form');
      });

      test('form: a reserved role leaves the team name to you (F2)', async ({ page }) => {
        await openForm(page, { roles: rolesWithTemper() });
        await member(page, 1).getByLabel('Role').selectOption('temper');
        await expect(member(page, 1).getByLabel('Team name')).toHaveValue('');
        await expect(member(page, 1)).toContainText("'temper' is a reserved name, so the team name is left for you to fill.");
        await member(page, 1).getByLabel('Role').selectOption('planner');
        await expect(member(page, 1).getByLabel('Team name')).toHaveValue('planner');
        await member(page, 1).getByLabel('Role').selectOption('temper');
        await looks(page, 'form-reserved');
      });

      test('form: the check passed, with a note (F2b)', async ({ page }) => {
        await openForm(page, {}, { check: [checkWithNote()] });
        await fillForm(page);
        await page.locator('#team-project').fill('/srv/example/projects/notes-app');
        await page.getByRole('button', { name: 'Check' }).click();
        const note = formResult(page).locator('[data-note="ok"]');
        await expect(note).toContainText('The check passed. Nothing was saved or started.');
        await expect(note).toContainText("Temper's note, so a passed check doesn't promise the start:");
        await expect(note.getByRole('link', { name: 'folder checks run when the Pi lane starts the team' })).toBeVisible();
        await expect(page.locator('#team-project-note-0')).toContainText("Temper's note: folder checks run when the Pi lane starts the team");
        await looks(page, 'form-check-passed');
      });

      test("form: Temper's problems, each at its place (F3)", async ({ page }) => {
        await openForm(page, {}, { check: [fixture('check-problems')] });
        await page.locator('#team-goal').fill('Write a short welcome note.');
        await fillMembers(page, [
          ['planner', 'Lead'],
          ['reviewer', 'checker'],
          ['builder', 'temper'],
          ['', ''],
        ]);
        await page.getByRole('button', { name: 'Check' }).click();
        await expect(problemsBox(page).getByRole('heading', { name: 'The check found 7 problems' })).toBeFocused();
        await looks(page, 'form-problems');
      });

      test('form: sending (F4a)', async ({ page }) => {
        const wait = held(fixture('trial-start-201'));
        await openForm(page, {}, { trial: [wait.reply] });
        await fillForm(page);
        await page.getByRole('button', { name: 'Run trial' }).click();
        await expect(page.getByRole('button', { name: 'Starting…' })).toBeDisabled();
        await expect(page.getByText('Sending to Temper…')).toBeVisible();
        await expect(page.locator('#team-goal')).toBeDisabled();
        await looks(page, 'form-sending');
        wait.release();
      });

      test("form: Temper didn't answer (F4b)", async ({ page }) => {
        await openForm(page, {}, { trial: ['no reply'] });
        await fillForm(page);
        await page.getByRole('button', { name: 'Run trial' }).click();
        const note = formResult(page).locator('[data-note="bad"]');
        await expect(note).toContainText("Temper didn't answer. Trying again is safe: the same request counts once.");
        await expect(note).toContainText(/Request [0-9a-f]{8} · your inputs are kept\./);
        await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible();
        await expect(page.locator('#team-goal')).toHaveValue('Write a short welcome note for the notes app.');
        await looks(page, 'form-no-answer');
      });

      test('form: the guard refused (F5)', async ({ page }) => {
        await openForm(page, {}, { trial: [fixture('trial-start-403')] });
        await fillForm(page);
        await page.getByRole('button', { name: 'Run trial' }).click();
        const note = formResult(page).locator('[data-note="bad"]');
        await expect(note).toContainText('Temper refused to start the trial.');
        await expect(note).toContainText(refusalText('trial-start-403'));
        await expect(note).toContainText('Nothing was saved or started.');
        await expect(page.locator('#team-pause')).toHaveValue('2');
        await looks(page, 'form-refused');
      });

      test("form: a 401 opens the dashboard's own key form, as answers do", async ({ page }) => {
        // The dashboard's TokenGate takes every 401 (part B's answers too); the form shows
        // only the refusals it is handed (F5, 403).
        await page.route('**/api/runtime-config', (route) =>
          route.fulfill({ json: { auth_required: false, writes_need_key: true } }),
        );
        await openForm(page, {}, { trial: [fixture('trial-start-401')] });
        await fillForm(page);
        await page.getByRole('button', { name: 'Run trial' }).click();
        await expect(page.getByRole('heading', { name: 'This action needs your key' })).toBeVisible();
      });

      test('form: 26 problems (S1)', async ({ page }) => {
        await openForm(page, {}, { check: [s1Check()] });
        await fillMembers(page, [
          ['planner', 'lead'],
          ['builder', 'maker'],
          ['reviewer', 'checker'],
        ]);
        await page.getByRole('button', { name: 'Check' }).click();
        await expect(problemsBox(page).getByRole('heading', { name: 'The check found 26 problems' })).toBeVisible();
        await expect(problemsBox(page).getByRole('listitem')).toHaveCount(26);
        await looks(page, 'form-26-problems');
      });

      test('form: six members (S6)', async ({ page }) => {
        await openForm(page, { roles: manyRoles() });
        await fillMembers(page, [
          ['analyst', ''],
          ['architect', ''],
          ['backend', ''],
          ['builder', ''],
          ['data', ''],
          ['designer', 'a-forty-character-team-name-for-the-row1'],
        ]);
        await expect(page.locator('#team-members-count')).toHaveText('6 of up to 6');
        await expect(form(page).getByRole('button', { name: 'Add member' })).toBeDisabled();
        await looks(page, 'form-six');
      });

      test('form: a goal over the limit (S2)', async ({ page }) => {
        await openForm(page);
        const goal = page.locator('#team-goal');
        await goal.fill('x'.repeat(20_000));
        await expect(page.locator('#team-goal-count')).toHaveText('20,000 / 20,000');
        await goal.press('End');
        await goal.press('y');
        await expect(page.locator('#team-goal-count')).toHaveText('20,001 / 20,000 · 1 over');
        await looks(page, 'form-goal-over');
      });

      test('form: the role list not set up, and a team settings problem (L2 in the form)', async ({ page }) => {
        await serveTeam(page, { roles: fixture('roles-not-set-up'), status: fixture('status-project-problems') });
        await page.goto('/app/team/new');
        await expect(page.getByText("The role list isn't set up")).toBeVisible();
        await expect(page.getByText("Temper's team settings have a problem:")).toBeVisible();
        await looks(page, 'form-roles-not-set-up');
      });

      test("form: the role list couldn't be read", async ({ page }) => {
        await serveTeam(page, { roles: { route: '', status: 500, body: { detail: 'database is locked' } } });
        await page.goto('/app/team/new');
        await expect(page.getByText("Couldn't load the role list.")).toBeVisible();
        await expect(page.locator('[data-quote="engine"] blockquote')).toHaveText('database is locked');
        await looks(page, 'form-roles-read-failed');
      });

      // ---- The message composer (boards O2, O6r) ---------------------------------------------

      test('composer: sent, it reaches the member at its next turn (O2)', async ({ page }) => {
        const { sent } = await openRun(page, 'run-running', { message: [fixture('message-201-pending')] });
        await expect(composer(page).getByLabel('To')).toHaveValue('lead');
        await expect(composer(page)).toContainText('Reaches the member at its next turn.');
        await composer(page).getByLabel('To').selectOption('maker');
        await composer(page).getByLabel('Message').fill('Keep the note under 60 words.');
        await composer(page).getByRole('button', { name: 'Send message' }).click();
        await expect(messageResult(page)).toContainText('Sent. maker gets it at its next turn.');
        await expect(composer(page).getByLabel('Message')).toHaveValue('');
        expect(sent.messages).toHaveLength(1);
        await looks(page, 'composer-sent');
      });

      test('composer: held while a question waits (O2)', async ({ page }) => {
        await openRun(page, 'run-paused', { message: [fixture('message-201-held')] });
        await expect(composer(page)).toContainText('Held until you answer the open question.');
        await composer(page).getByLabel('Message').fill('Keep the note under 60 words.');
        await composer(page).getByRole('button', { name: 'Send message' }).click();
        await expect(messageResult(page)).toContainText(
          'Sent: held until you answer the open question. The team is paused, so no member takes a turn until then.',
        );
        await looks(page, 'composer-held');
      });

      test('composer: Temper refused (O2)', async ({ page }) => {
        await openRun(page, 'run-running', { message: [fixture('message-409-member-ended')] });
        await composer(page).getByLabel('To').selectOption('checker');
        await composer(page).getByLabel('Message').fill('Please look at the heading again.');
        await composer(page).getByRole('button', { name: 'Send message' }).click();
        await expect(messageResult(page)).toContainText(`Temper refused: ${refusalText('message-409-member-ended')} Your text is kept.`);
        await expect(composer(page).getByLabel('Message')).toHaveValue('Please look at the heading again.');
        await looks(page, 'composer-refused');
      });

      test("composer: Temper didn't answer (O2)", async ({ page }) => {
        await openRun(page, 'run-running', { message: ['no reply'] });
        await composer(page).getByLabel('Message').fill('Keep the note under 60 words.');
        await composer(page).getByRole('button', { name: 'Send message' }).click();
        await expect(messageResult(page)).toContainText("Temper didn't answer. Trying again is safe: the same request counts once.");
        await expect(messageResult(page).getByRole('button', { name: 'Try again' })).toBeVisible();
        await looks(page, 'composer-no-answer');
      });

      // ---- The guard notice (boards O6, O6r) -------------------------------------------------

      for (const [mode, lead, rest] of [
        [
          'off',
          "Answers, messages and stops aren't limited to you.",
          '#45 is off: anyone who can reach Temper can answer, message or stop a trial.',
        ],
        [
          'record',
          "Answers, messages and stops aren't limited to you yet.",
          'Temper records who did each one (#45 is in record mode) but refuses no one. One sent without your credential shows as "unknown caller".',
        ],
      ] as const) {
        test(`guard notice: ${mode} (O6, O6r)`, async ({ page }) => {
          const status = mode === 'off' ? fixture('status-on') : fixture('status-record');
          const { go } = await openTeam(page, '/app/team', { status });
          await go();
          await expect(banner(page)).toHaveAttribute('data-guard-mode', mode);
          await expect(banner(page)).toContainText(lead);
          await expect(banner(page)).toContainText(rest);
          await looks(page, `guard-${mode}`);
          await openRun(page, 'run-paused', { status });
          await expect(banner(page)).toContainText(lead);
          await expect(banner(page)).toContainText(rest);
          await looks(page, `guard-${mode}-run`);
        });
      }

      // ---- The settings wait (SPEC 5.2a; boards R18, R18-light, R18s, O1e, O4, S8) -----------

      test('settings: the card (R18)', async ({ page }) => {
        await openRun(page, 'run-settings-changed');
        await expect(page.locator('header').first()).toContainText('Settings changed');
        await expect(card(page)).toHaveAttribute('data-wait-kind', 'settings');
        await expect(card(page).getByRole('heading', { name: "A deploy changed the team's settings while it waited" })).toBeVisible();
        await expect(card(page)).toContainText(
          'Nothing has run with the new settings yet. Your last answer is on hold: it is applied once after Go on, and dropped if you stop.',
        );
        const wait = (fixture('run-settings-changed').body as { open_waits: { question: string; answers: { means: string }[] }[] }).open_waits[0];
        await expect(card(page).locator('[data-quote="engine"]').first()).toHaveText(wait.question);
        const table = card(page).getByRole('table', { name: 'What changed' });
        await expect(table.locator('[data-setting="extensions.identity"]')).toHaveCount(3);
        await expect(table.locator('[data-settings-group="checker"]')).toContainText('Extension identity');
        await expect(table.locator('[data-settings-group="checker"]')).toContainText('607eb54de1ec');
        await expect(table.locator('[data-settings-group="checker"]')).toContainText('8f409eb72820');
        await expect(card(page).locator('[data-pin="lead"]')).toContainText('Settings fingerprint · lead');
        await expect(card(page).locator('[data-pin="lead"]')).toContainText('bc1292af03ba');
        await expect(answers(page).getByRole('radio', { name: /^Go on with the new settings/ })).toBeVisible();
        await expect(answers(page).getByRole('radio', { name: /^Stop the team/ })).toBeVisible();
        for (const a of wait.answers) await expect(answers(page)).toContainText(a.means);
        await looks(page, 'settings');
      });

      test('settings: stop, confirmed (O1e) and ended (R18s)', async ({ page }) => {
        await openRun(page, 'run-settings-changed', {
          answer: [fixture('answer-200-settings-stop')],
          after: 'run-settings-stopped',
        });
        await pick(page, 'Stop the team', "Not on these settings; I'll start a new trial.");
        await card(page).getByRole('button', { name: 'Stop the team…' }).click();
        const dialog = page.getByRole('alertdialog').or(page.getByRole('dialog'));
        await expect(dialog.getByRole('heading', { name: 'Stop the team at the settings check?' })).toBeVisible();
        await expect(dialog).toContainText(
          'The team ends here, before anything runs with the new settings. Your last answer is not applied, and nothing more is spent.',
        );
        await expect(dialog).toContainText('The run list will show this run as cancelled, like Stop run.');
        await looks(page, 'settings-stop-confirm');
        await dialog.getByRole('button', { name: 'Stop the team' }).click();
        const outcome = (fixture('run-settings-stopped').body as { outcome: { reason: string } }).outcome;
        // Temper's reason shows on the outcome card and on the timeline's stopped row.
        await expect(page.locator('[data-card="outcome"]').getByText(outcome.reason)).toBeVisible();
        await looks(page, 'settings-stopped');
        await wholeTimeline(page);
        await expect(timeline(page).getByText('answered stop (settings check)')).toBeVisible();
        await expect(page.getByRole('region', { name: 'Who did what' }).getByText('stop at the settings check')).toBeVisible();
      });

      test('settings: go on, and the held answer after it (O4)', async ({ page }) => {
        await openRun(page, 'run-settings-go-on');
        await expect(page.getByRole('heading', { name: "Done: the leader's version was approved" })).toBeVisible();
        await looks(page, 'settings-go-on');
        await wholeTimeline(page);
        // Go on twice: the first wasn't applied (the settings changed again), the second was.
        const goOn = timeline(page).locator('li', { hasText: 'answered go on (settings check)' });
        await expect(goOn).toHaveCount(2);
        await expect(goOn.locator('[data-chip="not-applied"]')).toHaveCount(1);
        await expect(timeline(page).getByText('Temper asked you: settings changed while the team waited').first()).toBeVisible();
        await expect(page.getByRole('region', { name: 'Who did what' }).getByText('go on at the settings check')).toHaveCount(2);
      });

      test('settings: asked again', async ({ page }) => {
        await openRun(page, 'run-settings-asked-again');
        await expect(card(page)).toContainText('Asked again (1 time)');
        await looks(page, 'settings-asked-again');
      });

      test('settings: changed again before go on (not applied)', async ({ page }) => {
        await openRun(page, 'run-settings-changed-again');
        await expect(page.locator('[data-chip="not-applied"]')).toHaveText('not applied');
        await expect(card(page)).toHaveAttribute('data-wait-kind', 'settings');
        await looks(page, 'settings-changed-again');
      });

      test('settings: thirty changes and a long member name (S8)', async ({ page }) => {
        await openRun(page, 'run-settings-stress');
        const table = card(page).getByRole('table', { name: 'What changed' });
        await expect(table.locator('[data-setting]')).toHaveCount(8);
        await expect(card(page)).toContainText('22 more changes · Show all');
        await expect(table.locator('tbody').first()).toHaveAttribute('data-settings-group', 'Whole team');
        await looks(page, 'settings-stress');
        await card(page).getByRole('button', { name: 'Show all' }).click();
        await expect(table.locator('[data-setting]')).toHaveCount(30);
        await expect(card(page).getByRole('button', { name: 'Show fewer' })).toHaveAttribute('aria-expanded', 'true');
        await looks(page, 'settings-stress-all');
      });

      // ---- Other waits and reviews ------------------------------------------------------------

      test("a wait of a kind the page doesn't know", async ({ page }) => {
        await openRun(page, 'run-unknown-wait');
        const wait = (fixture('run-unknown-wait').body as {
          open_waits: { question: string; answers: { answer: string; means: string }[] }[];
        }).open_waits[0];
        await expect(card(page).getByRole('heading', { name: 'Temper is waiting for you' })).toBeVisible();
        await expect(card(page).locator('[data-quote="engine"]').first()).toHaveText(wait.question);
        for (const a of wait.answers) {
          await expect(answers(page).getByRole('radio', { name: new RegExp(`^${a.answer}\\b`) })).toBeVisible();
          await expect(answers(page)).toContainText(a.means);
        }
        await looks(page, 'unknown-wait');
      });

      test('a done Temper refused (E14)', async ({ page }) => {
        await openRun(page, 'run-refused-done');
        await wholeTimeline(page);
        const refused = timeline(page).locator('li', { hasText: 'said done; refused' });
        await expect(refused).toHaveCount(1);
        await expect(refused).toContainText('your copy has 1 change(s) since the reviewed version');
        await looks(page, 'refused-done');
      });

      test('a long question waiting behind the asked one (R16)', async ({ page }) => {
        await openRun(page, 'run-paused-long-next');
        const next = card(page).getByRole('button', { name: 'Show all' });
        await expect(next).toHaveAttribute('aria-expanded', 'false');
        await looks(page, 'long-next');
        await next.click();
        await expect(card(page).getByRole('button', { name: 'Show less' })).toHaveAttribute('aria-expanded', 'true');
      });
    });
  }
}

// ---- Behaviour: what the page sends, request ids, polling, paging, keyboard (1440 px, dark) ----

test.describe('Team page C: behaviour', () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test('the trials list reads every 5 s while it is open, and not on Roles', async ({ page }) => {
    const { seen, go } = await openTeam(page, '/app/team');
    await go();
    await expect(trialRows(page)).toHaveCount(4);
    await expect.poll(() => trialsReads(seen), { timeout: TRIALS_POLL_MS * 2 + 2000 }).toBeGreaterThanOrEqual(3);
    expect(seen.find((p) => p.startsWith('/api/team/trials'))).toBe('/api/team/trials?limit=25&offset=0');
    await tabs(page).getByRole('link', { name: /^Roles/ }).click();
    await expect(page.locator('[data-role-row]')).toHaveCount(4);
    const before = trialsReads(seen);
    await page.waitForTimeout(TRIALS_POLL_MS + 1500);
    expect(trialsReads(seen)).toBe(before);
  });

  test('paging: Next, Previous and the page in the address', async ({ page }) => {
    const { seen, go } = await openTeam(page, '/app/team', { trials: manyTrials() });
    await go();
    await page.getByRole('button', { name: 'Next' }).click();
    await expect(page).toHaveURL(/\/app\/team\?page=2$/);
    expect(seen).toContain('/api/team/trials?limit=26&offset=24');
    await page.getByRole('button', { name: 'Next' }).click();
    await expect(page.getByTestId('trials-showing')).toHaveText('Showing 51–57 of 57 · newest first');
    await expect(page.getByRole('button', { name: 'Next' })).toBeDisabled();
    await page.getByRole('button', { name: 'Previous' }).click();
    await expect(page.getByTestId('trials-showing')).toHaveText('Showing 26–50 of 57 · newest first');
    // A page past the end goes to the last one.
    await page.goto('/app/team?page=9');
    await expect(page.getByTestId('trials-showing')).toHaveText('Showing 51–57 of 57 · newest first');
  });

  test('a failed refresh: Try now reads again at once', async ({ page }) => {
    let reads = 0;
    const { go } = await openTeam(page, '/app/team', {
      trials: () => (reads++ === 1 ? fixture('trials-error') : fixture('trials-list')),
    });
    await go();
    const note = page.locator('[data-note="warn"]').filter({ hasText: "Couldn't refresh at" });
    await expect(note).toBeVisible({ timeout: TRIALS_POLL_MS + 5000 });
    await note.getByRole('button', { name: 'Try now' }).click();
    await expect(note).toHaveCount(0);
    await expect(trialRows(page)).toHaveCount(4);
  });

  test('roles: the about page by keyboard, and back', async ({ page }) => {
    const { go } = await openTeam(page, '/app/team/roles');
    await go();
    const open = page.getByRole('button', { name: 'About page: planner' });
    await open.focus();
    await page.keyboard.press('Enter');
    const sheet = page.getByTestId('role-about-sheet');
    await expect(sheet).toBeVisible();
    await expect(sheet.getByRole('heading', { name: 'Planner', level: 1 })).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(sheet).toHaveCount(0);
    await expect(open).toBeFocused();
    // No about page: it says so.
    await page.getByRole('button', { name: 'About page: scribe' }).click();
    await expect(sheet).toContainText('This role has no about page.');
    await sheet.getByRole('button', { name: 'Close' }).click();
    await expect(page.getByRole('button', { name: 'About page: scribe' })).toBeFocused();
  });

  test('roles: a read that failed tries again, and Try again reads at once', async ({ page }) => {
    let reads = 0;
    const { go } = await openTeam(page, '/app/team/roles', {
      roles: () => (reads++ === 0 ? { route: '', status: 500, body: 'Internal Server Error' } : fixture('roles-ok')),
    });
    await go();
    await page.getByRole('button', { name: 'Try again' }).click();
    await expect(page.locator('[data-role-row]')).toHaveCount(4);
  });

  test('form: Run trial sends the form and opens the run', async ({ page }) => {
    const { sent } = await openForm(page, {}, { trial: [fixture('trial-start-201')] });
    await fillForm(page);
    await member(page, 2).getByRole('checkbox', { name: 'Edit' }).uncheck();
    await page.getByRole('button', { name: 'Run trial' }).click();
    const started = fixture('trial-start-201').body as { execution_id: string };
    await expect(page).toHaveURL(new RegExp(`/app/team/runs/${started.execution_id}$`));
    expect(sent.trials).toHaveLength(1);
    const body = sent.trials[0];
    expect(typeof body.request_id).toBe('string');
    expect(body).toEqual({
      request_id: body.request_id,
      goal: 'Write a short welcome note for the notes app.',
      members: [
        { role: 'planner', name: 'lead', tools: ['Read', 'Grep', 'Glob', 'Edit', 'Write'] },
        { role: 'builder', name: 'maker', tools: ['Read', 'Grep', 'Glob', 'Write'] },
      ],
      leader: 'lead',
      pause_after_rounds: 2,
      communication: 'all',
      project_path: null,
    });
  });

  test("form: after no answer, Try again sends the same request id; a changed form a new one", async ({ page }) => {
    const { sent } = await openForm(page, {}, { trial: ['no reply', 'no reply', fixture('trial-start-201-repeated')] });
    await fillForm(page);
    await page.getByRole('button', { name: 'Run trial' }).click();
    await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible();
    await page.getByRole('button', { name: 'Try again' }).click();
    await expect(formResult(page).locator('[data-note="bad"]')).toBeVisible();
    expect(sent.trials).toHaveLength(2);
    expect(sent.trials[1].request_id).toBe(sent.trials[0].request_id);
    await page.locator('#team-pause').fill('3');
    await expect(page.getByRole('button', { name: 'Run trial' })).toBeVisible();
    await page.getByRole('button', { name: 'Run trial' }).click();
    await expect(page).toHaveURL(/\/app\/team\/runs\//);
    expect(sent.trials).toHaveLength(3);
    expect(sent.trials[2].request_id).not.toBe(sent.trials[0].request_id);
  });

  test("form: problems sit by field and member, and each link goes to its place (F3)", async ({ page }) => {
    const { sent } = await openForm(page, {}, { check: [fixture('check-problems')] });
    await page.locator('#team-goal').fill('Write a short welcome note.');
    await fillMembers(page, [
      ['planner', 'Lead'],
      ['reviewer', 'checker'],
      ['builder', 'temper'],
      ['', ''],
    ]);
    await page.locator('#team-project').fill('/srv/example/elsewhere/notes-app');
    await page.getByRole('button', { name: 'Check' }).click();
    expect(sent.checks).toHaveLength(1);
    expect(sent.checks[0].request_id).toBeUndefined();
    const problems = (fixture('check-problems').body as { problems: { field: string | null; member?: string; text: string }[] }).problems;
    // The top list: every problem, word for word, in Temper's order.
    await expect(problemsBox(page).getByRole('listitem')).toHaveText(problems.map((p) => p.text));
    await expect(problemsBox(page)).toContainText('Nothing was saved. Your inputs are kept below.');
    // Each under its own place.
    await expect(page.locator('#team-goal-problem-0')).toContainText(problems[1].text);
    await expect(page.locator('#team-goal')).toHaveAttribute('aria-invalid', 'true');
    await expect(page.locator('#team-project-problem-0')).toContainText(problems[6].text);
    const membersList = page.locator('#team-members-problems');
    await expect(membersList).toContainText(problems[0].text);
    await expect(membersList).toContainText(problems[2].text);
    await expect(member(page, 1)).toHaveAttribute('data-bad', 'true');
    await expect(member(page, 1)).toContainText(problems[3].text);
    await expect(member(page, 2)).toContainText(problems[4].text);
    await expect(member(page, 3)).toContainText(problems[5].text);
    await expect(member(page, 4)).not.toHaveAttribute('data-bad', 'true');
    // A link moves the focus to its place.
    await problemsBox(page).getByRole('link', { name: problems[1].text }).click();
    await expect(page.locator('#team-goal')).toBeFocused();
    await problemsBox(page).getByRole('link', { name: problems[4].text }).click();
    await expect(member(page, 2)).toBeFocused();
    await problemsBox(page).getByRole('link', { name: problems[0].text }).press('Enter');
    await expect(page.locator('#team-members-problems')).toBeFocused();
  });

  test('form: a problem with no field sits in the top list only, with no link (A-5)', async ({ page }) => {
    await openForm(page, {}, { trial: [fixture('trial-start-400-run-refused')] });
    await fillForm(page);
    await page.getByRole('button', { name: 'Run trial' }).click();
    await expect(problemsBox(page).getByRole('heading', { name: "Temper didn't start the trial: 1 problem" })).toBeFocused();
    await expect(problemsBox(page).getByRole('listitem')).toHaveText(['the run start said no']);
    await expect(problemsBox(page).getByRole('link')).toHaveCount(0);
  });

  test('form: the 400 of a start, placed (leader)', async ({ page }) => {
    await openForm(page, {}, { trial: [fixture('trial-start-400-problems')] });
    await fillForm(page);
    await page.getByRole('button', { name: 'Run trial' }).click();
    const text = (fixture('trial-start-400-problems').body as { problems: { text: string }[] }).problems[0].text;
    await expect(problemsBox(page).getByRole('heading', { name: "Temper didn't start the trial: 1 problem" })).toBeVisible();
    await expect(page.locator('#team-members-problems')).toContainText(text);
  });

  // A 401 goes to the dashboard's own key form (TokenGate), not to the page: tested on its own.
  for (const name of ['trial-start-403', 'trial-start-409-request-id-reused', 'trial-start-400-no-request-id']) {
    test(`form: refusal word for word (${name})`, async ({ page }) => {
      await openForm(page, {}, { trial: [fixture(name)] });
      await fillForm(page);
      await page.getByRole('button', { name: 'Run trial' }).click();
      const note = formResult(page).locator('[data-note="bad"]');
      await expect(note).toContainText('Temper refused to start the trial.');
      await expect(note.locator('[data-engine-words]')).toHaveText(refusalText(name));
      await expect(page.locator('#team-goal')).toHaveValue('Write a short welcome note for the notes app.');
    });
  }

  test('form: Check after no answer says so, and checks again', async ({ page }) => {
    const { sent } = await openForm(page, {}, { check: ['no reply', fixture('check-ok')] });
    await fillForm(page);
    await page.getByRole('button', { name: 'Check' }).click();
    await expect(formResult(page)).toContainText("Temper didn't answer the check.");
    await expect(formResult(page)).toContainText('Nothing was saved or started. Checking again is safe.');
    await page.getByRole('button', { name: 'Check' }).click();
    await expect(formResult(page)).toContainText('The check passed. Nothing was saved or started.');
    expect(sent.checks).toHaveLength(2);
  });

  test('form: the role list not set up, and a team settings problem', async ({ page }) => {
    await serveTeam(page, { roles: fixture('roles-not-set-up'), status: fixture('status-project-problems') });
    await page.goto('/app/team/new');
    await expect(page.getByRole('heading', { level: 1, name: 'New trial' })).toBeVisible();
    await expect(page.getByText("The role list isn't set up")).toBeVisible();
    await expect(page.getByText("Temper's team settings have a problem:")).toBeVisible();
    const problem = (fixture('status-project-problems').body as { project_problems: string[] }).project_problems[0];
    await expect(page.getByText(problem)).toBeVisible();
  });

  test('form: Add member stops at six; Remove member takes a row out', async ({ page }) => {
    await openForm(page, { roles: manyRoles() });
    for (let i = 0; i < 5; i++) await form(page).getByRole('button', { name: 'Add member' }).click();
    await expect(form(page).getByRole('button', { name: 'Add member' })).toBeDisabled();
    await member(page, 3).getByRole('button', { name: 'Remove member 3' }).click();
    await expect(page.locator('#team-members-count')).toHaveText('5 of up to 6');
    await expect(form(page).getByRole('button', { name: 'Add member' })).toBeEnabled();
  });

  test('composer: what it sends, and the same request id after no answer', async ({ page }) => {
    const { sent } = await openRun(page, 'run-running', { message: ['no reply', fixture('message-201-pending')] });
    await composer(page).getByLabel('To').selectOption('maker');
    await composer(page).getByLabel('Message').fill('Keep the note under 60 words.');
    await composer(page).getByRole('button', { name: 'Send message' }).click();
    await expect(messageResult(page).getByRole('button', { name: 'Try again' })).toBeVisible();
    await messageResult(page).getByRole('button', { name: 'Try again' }).click();
    await expect(messageResult(page)).toContainText('Sent. maker gets it at its next turn.');
    expect(sent.messages).toHaveLength(2);
    expect(sent.messages[0]).toEqual({ request_id: sent.messages[0].request_id, to: 'maker', body: 'Keep the note under 60 words.' });
    expect(typeof sent.messages[0].request_id).toBe('string');
    expect(sent.messages[1].request_id).toBe(sent.messages[0].request_id);
  });

  for (const name of [
    'message-409-team-ended',
    'message-409-team-not-started',
    'message-409-member-ended',
    'message-409-request-id-reused',
    'message-400-empty',
    'message-400-not-a-member',
    'message-400-too-long',
    'message-403',
  ]) {
    test(`composer: refusal word for word (${name})`, async ({ page }) => {
      await openRun(page, 'run-running', { message: [fixture(name)] });
      await composer(page).getByLabel('Message').fill('Please look at the heading again.');
      await composer(page).getByRole('button', { name: 'Send message' }).click();
      await expect(messageResult(page).locator('[data-engine-words]')).toHaveText(refusalText(name));
      await expect(messageResult(page)).toContainText('Your text is kept.');
      await expect(composer(page).getByLabel('Message')).toHaveValue('Please look at the heading again.');
    });
  }

  test("composer: a 401 opens the dashboard's own key form, and the text is kept", async ({ page }) => {
    await page.route('**/api/runtime-config', (route) =>
      route.fulfill({ json: { auth_required: false, writes_need_key: true } }),
    );
    await openRun(page, 'run-running', { message: [fixture('message-401')] });
    await composer(page).getByLabel('Message').fill('Please look at the heading again.');
    await composer(page).getByRole('button', { name: 'Send message' }).click();
    await expect(page.getByRole('heading', { name: 'This action needs your key' })).toBeVisible();
  });

  test('composer: none on an ended run', async ({ page }) => {
    await openRun(page, 'run-done');
    await expect(composer(page)).toHaveCount(0);
  });

  test('guard notice: hidden for the session, back for another mode, never in enforce', async ({ page }) => {
    const { go } = await openTeam(page, '/app/team');
    await go();
    await page.getByRole('button', { name: 'Hide this notice for this session' }).click();
    await expect(banner(page)).toHaveCount(0);
    await page.reload();
    await expect(trialRows(page)).toHaveCount(4);
    await expect(banner(page)).toHaveCount(0);
    await page.unrouteAll({ behavior: 'ignoreErrors' });
    await serveTeam(page, { status: fixture('status-record') });
    await page.reload();
    await expect(banner(page)).toHaveAttribute('data-guard-mode', 'record');
    await page.unrouteAll({ behavior: 'ignoreErrors' });
    await serveTeam(page, { status: fixture('status-enforce') });
    await page.reload();
    await expect(trialRows(page)).toHaveCount(4);
    await expect(banner(page)).toHaveCount(0);
  });

  test('settings: go on sends go on with no words', async ({ page }) => {
    const { sent } = await openRun(page, 'run-settings-changed', {
      answer: [fixture('answer-200-settings-go-on')],
      after: 'run-settings-go-on',
    });
    await pick(page, 'Go on with the new settings');
    await card(page).getByRole('button', { name: 'Send answer' }).click();
    await expect(card(page)).toHaveCount(0);
    await wholeTimeline(page);
    await expect(timeline(page).locator('li', { hasText: 'answered go on (settings check)' }).first()).toBeVisible();
    expect(sent.answers).toHaveLength(1);
    expect(sent.answers[0].answer).toBe('go on');
    // No words: part B sends an empty text for an answer that takes none.
    expect(sent.answers[0].text ?? '').toBe('');
  });

  test('settings: stop sends stop with the words', async ({ page }) => {
    const { sent } = await openRun(page, 'run-settings-changed', {
      answer: [fixture('answer-200-settings-stop')],
      after: 'run-settings-stopped',
    });
    await pick(page, 'Stop the team', 'Not now.');
    await card(page).getByRole('button', { name: 'Stop the team…' }).click();
    await page.getByRole('alertdialog').or(page.getByRole('dialog')).getByRole('button', { name: 'Keep the team' }).click();
    expect(sent.answers).toHaveLength(0);
    await card(page).getByRole('button', { name: 'Stop the team…' }).click();
    await page.getByRole('alertdialog').or(page.getByRole('dialog')).getByRole('button', { name: 'Stop the team' }).click();
    await expect(page.getByText('answered stop (settings check)')).toBeVisible();
    expect(sent.answers).toHaveLength(1);
    expect(sent.answers[0].answer).toBe('stop');
    expect(sent.answers[0].text).toBe('Not now.');
  });

  test('a message to a run is never sent while its first read is going', async ({ page }) => {
    // The composer shows only once the run is read: nothing to send to before.
    await serveTeam(page, { run: [fixture('run-running')] });
    await page.goto(`/app/team/runs/${RUN_ID}`);
    await expect(composer(page)).toBeVisible();
  });
});
