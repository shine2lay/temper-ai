/**
 * Starting a free-flowing Project, in a real browser, on either engine: one
 * happy-path journey per theme and size (owner bp-be8d76b9: many checks in
 * one test). The words are Design's settled ones (SPEC section 14 b, D55).
 *
 * The page follows the server, so either can land first. The new engine
 * (free-flowing teams, FLOW api-fields sections 1-2) says its check-in
 * default in GET /api/team/status: the New project form then asks Check in
 * every (whole dollars, "$" inside the field) and Max members at once, and
 * never sends pause_after_rounds, which it refuses ("start a new Project").
 * Today's server says none: the form is exactly today's. A Project paused at
 * a check-in keeps today's "Paused" badge with no amount (the list item has
 * none). An old review-round run (kind "rounds") is read-only on the new
 * engine: its run page offers no re-run, fork or resume, and the Team page
 * says it can't be resumed; a run whose reply has no kind keeps them. The
 * guard's off notice says how an unnamed sender shows (Design rm-c58cb171).
 *
 * Every /api call is answered here from the captured fixtures (changed where
 * the new engine differs), so the spec needs no Temper (server-free.txt).
 * Each Team page passes axe with nothing found and has every target at least
 * 24 px. Screenshots go to FORM_SHOTS when set.
 */
import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page, type Route } from '@playwright/test';
import {
  AXE_TAGS,
  expectAxeClean,
  expectTargets,
  type Fixture,
  fixture,
  nothingSent,
  serveActions,
  serveTeam,
  shoot,
  withBody,
} from './team-helpers';
import { runSnapshot } from './safeRenderingScenes';

const SHOTS = process.env.FORM_SHOTS;

/** Each width's height: a phone, a small laptop, a desktop. */
const SIZES = [
  [390, 844],
  [1024, 768],
  [1440, 900],
] as const;

/** Today's server: the captured status, with no check-in default. Its guard is off. */
const TODAY_STATUS = fixture('status-on');
const TOOLS = (TODAY_STATUS.body as { tools: { default: string[] } }).tools.default;

/** The new engine: the same status with its defaults and limits (FLOW api-fields section 2). */
const FLOW_STATUS = withBody('status-on', (body) => ({
  ...body,
  defaults: { ...(body.defaults as object), pause_every_usd: 100, max_parallel: null },
  limits: { ...(body.limits as object), pause_every_usd: { min: 1, max: 10000 } },
}));

const GUARD_LEAD = "Answers, messages and stops aren't limited to you.";
const GUARD_REST =
  '#45 is off: anyone who can reach Temper can answer, message or stop a project. One sent without your credential shows as "unknown caller".';

/** Today's request, key by key, in today's order; the new engine's. */
const TODAY_KEYS = ['goal', 'members', 'leader', 'pause_after_rounds', 'communication', 'project_path'];
const FLOW_KEYS = ['goal', 'members', 'leader', 'pause_every_usd', 'max_parallel', 'communication', 'project_path'];

const EVERY_PROBLEM = 'pause_every_usd: must be a number of US dollars from 1 to 10000';
const AT_ONCE_PROBLEM = "max_parallel: is 3, more than the team's 2 member(s)";

/** The new engine's check of a form with 0 dollars and 3 members at once for a team of 2. */
const CHECK_FLOW_PROBLEMS: Fixture = {
  route: 'POST /api/team/check',
  status: 200,
  body: {
    ok: false,
    problems: [
      { field: 'pause_every_usd', text: EVERY_PROBLEM },
      { field: 'max_parallel', text: AT_ONCE_PROBLEM },
    ],
    notes: [],
  },
};

const FLOW_GOAL = 'Draft the welcome screen for the notes app.';
const INTERRUPTED_GOAL = 'Sort the notes list by last change.';

/** What the filled form sends the new engine, whole: Check in every $50, 2 members at once. */
const FLOW_BODY = {
  goal: FLOW_GOAL,
  members: [
    { role: 'planner', name: 'lead', tools: TOOLS },
    { role: 'builder', name: 'maker', tools: TOOLS },
  ],
  leader: 'lead',
  pause_every_usd: 50,
  max_parallel: 2,
  communication: 'all',
  project_path: null,
};

/** The empty Projects list's line on each engine (Design's SPEC 14 b 6 for the new one). */
const FLOW_EMPTY =
  'Start one: the leader gets your goal and messages the others their work, and Temper checks in with you as spend grows.';
const TODAY_EMPTY =
  "A project puts a few pi roles on one goal. They work in rounds, review each other's work and stop when the leader's version is approved. Start one with New project at the top right.";

/** Design's SPEC 14 b 7: an old round run on the new engine can't be resumed. */
const ROUND_CANT_RESUME = "This round run can't be resumed here. Start a new project to carry on.";

/** The runs this journey opens: an old round team's, failed and interrupted, and one whose reply has no kind. */
const ROUNDS_RUN = 'form-flow-rounds-0001';
const NO_KIND_RUN = 'form-flow-nokind-0001';
const INTERRUPTED_RUN = 'form-flow-interrupted-0001';

/**
 * The Projects list on the new engine: a free-flowing Project paused at a
 * check-in on top (no round anywhere in its item), an old round team's run
 * that a restart interrupted, then today's four, which the new engine marks
 * as round teams.
 */
const FLOW_TRIALS = withBody('trials-list', (body) => {
  const trials = body.trials as Array<Record<string, unknown>>;
  const first = { ...trials[0] };
  delete first.round;
  const flow = {
    ...first,
    trial_id: 'f10f10f10f10',
    execution_id: 'f10f10f1-0000-4000-8000-f10f10f10f10',
    workflow: 'team-trial-f10f10f10f10',
    goal_first_line: FLOW_GOAL,
    kind: 'flow',
    state: 'paused',
    run_status: 'waiting',
    cost_usd: 100.42,
    started_at: '2026-10-09T09:30:00+00:00',
    started_by: 'owner',
  };
  const interrupted = {
    ...trials[1],
    trial_id: '1a7e1a7e1a7e',
    execution_id: INTERRUPTED_RUN,
    workflow: 'team-trial-1a7e1a7e1a7e',
    goal_first_line: INTERRUPTED_GOAL,
    kind: 'rounds',
    state: 'interrupted',
    run_status: 'interrupted',
    decision: null,
    started_at: '2026-10-09T08:00:00+00:00',
    ended_at: null,
  };
  const today = trials.map((t) => ({ ...t, kind: 'rounds' }));
  return { ...body, total: today.length + 2, trials: [flow, interrupted, ...today] };
});

/** The run page's own reads for two runs: failed, with one saved checkpoint (so Re-run, Resume and fork show). */
async function serveRunPage(page: Page) {
  await page.route('**/api/**', async (route) => {
    const { pathname } = new URL(route.request().url());
    const id = [ROUNDS_RUN, NO_KIND_RUN].find((run) => pathname.includes(run));
    let body: unknown = { detail: 'Not Found' };
    let status = 200;
    if (id && pathname === `/api/workflows/${id}`) body = { ...runSnapshot([{ name: 'writer' }], 'failed'), id };
    else if (id && pathname === `/api/workflows/${id}/agents`) body = { agents: [] };
    else if (id && pathname === `/api/runs/${id}/checkpoints`)
      body = {
        execution_id: id,
        checkpoints: [
          {
            id: `${id}-cp-1`,
            sequence: 1,
            event_type: 'stage_completed',
            node_name: 'study',
            agent_name: null,
            status: 'completed',
            cost_usd: 0,
            total_tokens: 0,
            duration_seconds: 60,
            error: null,
            metadata: {},
            timestamp: '2026-10-07T10:01:00+00:00',
          },
        ],
        total: 1,
      };
    else if (id && pathname.startsWith(`/api/runs/${id}/`)) body = { gates: [] };
    else if (pathname === '/api/workflows') body = { runs: [], total: 0 };
    else status = 404;
    await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
  });
}

/** Temper's team reply for a run, with its kind; none is today's server. */
const teamRun = (name: string, id: string, kind?: string) =>
  withBody(name, (body) => ({ ...body, execution_id: id, ...(kind ? { kind } : {}) }));

const TEAM_RUNS: Record<string, Fixture> = {
  [ROUNDS_RUN]: teamRun('run-failed', ROUNDS_RUN, 'rounds'),
  [NO_KIND_RUN]: teamRun('run-failed', NO_KIND_RUN),
  [INTERRUPTED_RUN]: teamRun('run-interrupted', INTERRUPTED_RUN, 'rounds'),
};

async function serveTeamRuns(page: Page) {
  // Registered after serveTeam, so it answers these runs' reads first.
  await page.route('**/api/team/runs/*', async (route) => {
    const id = new URL(route.request().url()).pathname.split('/').pop() ?? '';
    const answer = TEAM_RUNS[id];
    if (route.request().method() !== 'GET' || !answer) return route.fallback();
    await route.fulfill({ status: answer.status, contentType: 'application/json', body: JSON.stringify(answer.body) });
  });
}

/**
 * axe on the Workflows run page: nothing serious or critical. Not the Team
 * pages' nothing-at-all: the run page has a moderate finding of its own
 * (heading-order, the Checkpoints panel's h3), which this change leaves be.
 */
async function expectAxeNoSerious(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze();
  const found = results.violations
    .filter((v) => v.impact === 'serious' || v.impact === 'critical')
    .map((v) => `${v.id} (${v.impact}): ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`);
  expect(found, 'axe found serious or critical problems').toEqual([]);
}

/**
 * Design's SPEC 14 b 8: each problem in the summary keeps its bullet on its
 * first line, wrapped or not. A zero-width probe put at the start of the
 * item sits on the item's first line, where the bullet sits; the bottom of
 * its text must meet the bottom of the problem's first line. Says how many
 * problems wrap.
 */
async function bulletsOnFirstLine(page: Page): Promise<number> {
  const items = await page
    .getByTestId('team-form-problems')
    .locator('li')
    .evaluateAll((lis) =>
      lis.map((li) => {
        const text = li.querySelector('[data-engine-words]')?.firstChild;
        if (!text) return { gap: Infinity, lines: 0 };
        const probe = document.createTextNode('\u200b');
        li.insertBefore(probe, li.firstChild);
        const range = document.createRange();
        range.selectNodeContents(probe);
        const bullet = range.getBoundingClientRect().bottom;
        probe.remove();
        range.selectNodeContents(text);
        const lines = range.getClientRects();
        return { gap: Math.abs(bullet - lines[0].bottom), lines: lines.length };
      }),
    );
  expect(items.length).toBeGreaterThan(0);
  for (const item of items) expect(item.gap, 'a bullet off its first line').toBeLessThanOrEqual(2);
  return items.filter((item) => item.lines > 1).length;
}

const form = (page: Page) => page.getByTestId('team-form');
const member = (page: Page, n: number) => form(page).getByRole('group', { name: `Member ${n}`, exact: true });
const banner = (page: Page) => page.locator('[data-guard-mode]');
const every = (page: Page) => page.getByLabel('Check in every, in dollars', { exact: true });
/** Its label holds its "(optional)" tag. */
const atOnce = (page: Page) => page.getByLabel('Max members at once (optional)', { exact: true });
const atOnceHelp = (page: Page) => page.locator('#team-max-parallel-help');
const rerun = (page: Page) => page.getByRole('button', { name: /^Re-run — start this workflow again/ });
const row = (page: Page, goal: string) => page.locator('[data-trial-row]', { hasText: goal });

/** A goal and two members: lead (planner) leads, maker (builder). */
async function fillTeam(page: Page) {
  await page.locator('#team-goal').fill(FLOW_GOAL);
  await member(page, 1).getByLabel('Role').selectOption('planner');
  await member(page, 1).getByLabel('Team name').fill('lead');
  await form(page).getByRole('button', { name: 'Add member' }).click();
  await member(page, 2).getByLabel('Role').selectOption('builder');
  await member(page, 2).getByLabel('Team name').fill('maker');
  await member(page, 1).getByRole('radio', { name: 'Leader' }).check();
}

/**
 * Each member row's Role and Team name: below 768 px each takes the row's full width, Team name under Role, so
 * neither is cut; from 768 px side by side. The order, and so the keyboard path, stays Role, Team name, Leader,
 * remove (home's note 2 on #17).
 */
async function expectMemberFields(page: Page, narrow: boolean) {
  const rows = await page.locator('[data-member-row]').evaluateAll((els) =>
    els.map((el) => {
      const box = (sel: string) => el.querySelector(sel)!.getBoundingClientRect();
      const grid = el.querySelector('[data-member-field="role"]')!.parentElement!.getBoundingClientRect();
      const order = [...el.querySelectorAll('select, input[type="text"], input[type="radio"], button')].map((c) =>
        c.tagName === 'INPUT' ? (c as HTMLInputElement).type : c.tagName.toLowerCase(),
      );
      return { grid: { left: grid.left, width: grid.width }, role: box('select'), name: box('input[type="text"]'), order };
    }),
  );
  expect(rows.length).toBeGreaterThan(0);
  for (const r of rows) {
    expect(r.order.slice(0, 4)).toEqual(['select', 'text', 'radio', 'button']);
    if (narrow) {
      expect(Math.abs(r.role.width - r.grid.width), 'Role takes the full width').toBeLessThanOrEqual(1);
      expect(Math.abs(r.name.width - r.grid.width), 'Team name takes the full width').toBeLessThanOrEqual(1);
      expect(r.name.top, 'Team name sits under Role').toBeGreaterThanOrEqual(r.role.bottom);
    } else {
      expect(Math.abs(r.name.top - r.role.top), 'side by side').toBeLessThanOrEqual(1);
      expect(r.name.left).toBeGreaterThan(r.role.right);
    }
  }
}

async function formOpen(page: Page) {
  await expect(page.getByRole('heading', { level: 1, name: 'New project' })).toBeVisible();
  await expect(member(page, 1).getByLabel('Role')).toBeEnabled();
}

async function openForm(page: Page) {
  await page.goto('/app/team/new');
  await formOpen(page);
}

for (const theme of ['dark', 'light'] as const) {
  for (const [width, height] of SIZES) {
    test.describe(`Starting a free-flowing Project, ${theme}, ${width}x${height}`, () => {
      test.use({ viewport: { width, height } });
      const tag = `${theme}-${width}`;
      const narrow = width < 768;

      test.beforeEach(async ({ page }) => {
        await page.addInitScript((t) => localStorage.setItem('temper_theme', t), theme);
      });

      /** A Team page: axe finds nothing, every target is at least 24 px; then its shot. */
      async function looks(page: Page, name: string) {
        await expectAxeClean(page);
        await expectTargets(page);
        await shoot(page, `${tag}-${name}`, SHOTS);
      }

      test('the list, a round run, the new form, and the form and list on today’s server', async ({ page }) => {
        test.setTimeout(180_000);
        await serveRunPage(page);
        let projects: Fixture = FLOW_TRIALS;
        await serveTeam(page, { status: FLOW_STATUS, trials: () => projects, run: [fixture('run-running')] });
        await serveTeamRuns(page);
        const sent = nothingSent();
        await serveActions(page, sent, {
          check: [fixture('check-ok'), CHECK_FLOW_PROBLEMS, fixture('check-ok')],
          trial: [fixture('trial-start-201')],
        });

        // ---- The Projects list on the new engine ---------------------------------------------
        await page.goto('/app/team');
        await expect(page.getByRole('list', { name: 'Projects' })).toBeVisible();
        // Paused at a check-in: today's badge and needs you; no amount (G7) and nothing about rounds.
        const flowRow = row(page, FLOW_GOAL);
        await expect(flowRow).toBeVisible();
        await expect(flowRow).toHaveAttribute('data-needs-you', 'true');
        await expect(flowRow).toContainText('Paused');
        await expect(flowRow).toContainText('needs you');
        await expect(flowRow).not.toContainText(/round|check-in/i);
        await expect(flowRow.getByLabel('no round yet')).toHaveCount(0);
        // An old round team's run a restart interrupted: the new engine can't resume it.
        const halted = row(page, INTERRUPTED_GOAL);
        await expect(halted).toContainText('Interrupted');
        await expect(halted).toContainText("interrupted; this Temper can't resume a round run");
        await expect(halted).not.toContainText('resume it from the run page');
        // Today's projects, now marked as round teams, keep their round words.
        await expect(row(page, 'Name the three buttons on the share dialog.')).toContainText('round 1');
        if (width >= 1280) await expect(page.locator('[data-column-names]')).toContainText('Round');

        // ---- The guard's off notice, with Design's new sentence ------------------------------
        await expect(banner(page)).toHaveAttribute('data-guard-mode', 'off');
        await expect(banner(page)).toContainText(GUARD_LEAD);
        const rest = page.getByText(GUARD_REST, { exact: true });
        if (narrow) {
          // A phone shows the first sentence only, the rest behind Show details.
          await expect(rest).toBeHidden();
          await page.getByRole('button', { name: 'Show details' }).click();
          await expect(rest).toBeVisible();
          await page.getByRole('button', { name: 'Hide details' }).click();
          await expect(rest).toBeHidden();
        } else {
          await expect(rest).toBeVisible();
          await expect(page.getByRole('button', { name: 'Show details' })).toHaveCount(0);
        }
        await looks(page, 'projects-list');

        // ---- The interrupted round run says so and offers a new project -----------------------
        await halted.getByRole('link', { name: INTERRUPTED_GOAL }).click();
        await expect(page).toHaveURL(new RegExp(`/app/team/runs/${INTERRUPTED_RUN}$`));
        const stuck = page.locator('[data-card="interrupted"]');
        await expect(stuck.getByRole('heading', { level: 2 })).toHaveText(
          "Interrupted: this round run can't be resumed here. Start a new project to carry on.",
        );
        await expect(stuck.getByRole('link', { name: 'Open the run page' })).toHaveCount(0);
        await expect(page.getByText('Resume is on the run page')).toHaveCount(0);
        await looks(page, 'run-interrupted-rounds');
        await stuck.getByRole('link', { name: 'New project' }).click();
        await expect(page).toHaveURL(/\/app\/team\/new$/);
        await formOpen(page);

        // ---- The New project form on the new engine ------------------------------------------
        // Check in every: required like the Goal, whole dollars above 0, "$" inside the field as decoration.
        await expect(every(page)).toHaveValue('100');
        await expect(form(page).locator('label[for="team-pause-every"]')).toHaveText('Check in every');
        await expect(page.locator('#team-pause-every')).toHaveAccessibleName('Check in every, in dollars');
        await expect(form(page).locator('label[for="team-pause-every"] + span')).toHaveText('required');
        await expect(form(page).locator('label[for="team-goal"] + span')).toHaveText('required');
        await expect(every(page)).toHaveAttribute('min', '1');
        await expect(every(page)).toHaveAttribute('step', '1');
        await expect(every(page)).toHaveAttribute('inputmode', 'numeric');
        const dollar = form(page).locator('[data-prefix]');
        await expect(dollar).toHaveText('$');
        await expect(dollar).toHaveAttribute('aria-hidden', 'true');
        const field = (await every(page).boundingBox())!;
        const sign = (await dollar.boundingBox())!;
        // Inside the field, left of where the amount starts (28 px in).
        expect(sign.x).toBeGreaterThan(field.x);
        expect(sign.x + sign.width).toBeLessThanOrEqual(field.x + 28);
        expect(sign.y).toBeGreaterThanOrEqual(field.y);
        expect(sign.y + sign.height).toBeLessThanOrEqual(field.y + field.height);
        await expect(page.locator('#team-pause-every-help')).toHaveText(
          'When spend grows by this much, the team pauses and asks you to continue, guide or stop.',
        );
        // Max members at once: empty is every member; its range follows the members chosen (one so far).
        await expect(atOnce(page)).toHaveValue('');
        await expect(atOnceHelp(page)).toHaveText(
          'How many members may work at the same moment: 1 to 1. Leave it empty for all of them.',
        );
        await expect(page.locator('#team-pause')).toHaveCount(0);
        await expect(page.getByText('Pause after this many rounds without done')).toHaveCount(0);
        // The aside, as proposed (Design's SPEC 14 b 4).
        const about = page.getByRole('complementary', { name: 'About this project' });
        await expect(about).toContainText(
          'The leader gets the goal first and messages the others their work; then they work side by side.',
        );
        await expect(about).toContainText(
          'Temper checks in with you each time spend grows by your check-in amount, and asks you when a member needs you.',
        );
        await expect(about).not.toContainText('Members take turns, ask each other for review and send work back.');
        await expect(banner(page)).toContainText(GUARD_LEAD);
        await looks(page, 'form-flow-empty');

        // Check with Temper's defaults untouched: the $100 shown, and every member at once.
        await fillTeam(page);
        await expectMemberFields(page, narrow);
        await expect(atOnceHelp(page)).toHaveText(
          'How many members may work at the same moment: 1 to 2. Leave it empty for all of them.',
        );
        await form(page).getByRole('button', { name: 'Check' }).click();
        await expect(page.getByTestId('team-form-result')).toBeVisible();

        // Temper's problems sit under their own fields; each keeps its bullet on its first line.
        await every(page).fill('0');
        await atOnce(page).fill('3');
        await form(page).getByRole('button', { name: 'Check' }).click();
        await expect(page.locator('#team-pause-every-problem-0')).toContainText(EVERY_PROBLEM);
        await expect(page.locator('#team-max-parallel-problem-0')).toContainText(AT_ONCE_PROBLEM);
        await expect(every(page)).toHaveAttribute('aria-invalid', 'true');
        await expect(atOnce(page)).toHaveAttribute('aria-invalid', 'true');
        await expect(every(page)).toHaveAttribute('aria-describedby', /team-pause-every-problem-0/);
        await expect(page.getByTestId('team-form-problems')).toContainText('2 problems');
        const wrapped = await bulletsOnFirstLine(page);
        if (narrow) expect(wrapped, 'a problem wraps on a phone').toBeGreaterThan(0);
        await looks(page, 'form-flow-problems');

        // Fixed: the check passes and the Project starts.
        await every(page).fill('50');
        await atOnce(page).fill('2');
        await form(page).getByRole('button', { name: 'Check' }).click();
        await expect(page.locator('#team-pause-every-problem-0')).toHaveCount(0);
        await expect(every(page)).not.toHaveAttribute('aria-invalid', 'true');
        await form(page).getByRole('button', { name: 'Run project' }).click();
        await expect(page).toHaveURL(/\/app\/team\/runs\/f5facbc6-c8c5-4ade-bc58-8920b3355243$/);

        // What the page sent, whole: the check-in and members at once, never pause_after_rounds.
        expect(sent.checks).toHaveLength(3);
        for (const body of sent.checks) expect(Object.keys(body)).toEqual(FLOW_KEYS);
        expect(sent.checks[0]).toEqual({ ...FLOW_BODY, pause_every_usd: 100, max_parallel: null });
        expect(sent.checks[1]).toEqual({ ...FLOW_BODY, pause_every_usd: 0, max_parallel: 3 });
        expect(sent.checks[2]).toEqual(FLOW_BODY);
        expect(sent.trials).toHaveLength(1);
        expect(Object.keys(sent.trials[0]).sort()).toEqual([...FLOW_KEYS, 'request_id'].sort());
        expect(sent.trials[0]).toEqual({ ...FLOW_BODY, request_id: expect.any(String) });
        for (const body of [...sent.checks, ...sent.trials]) expect(body).not.toHaveProperty('pause_after_rounds');

        // ---- An old round team's failed run: no resume, on the Team page or the run page ------
        await page.goto(`/app/team/runs/${ROUNDS_RUN}`);
        await expect(page.getByText(ROUND_CANT_RESUME, { exact: true })).toBeVisible();
        await expect(page.getByText('Resume it from the run page to retry or stop the turn.')).toHaveCount(0);
        await looks(page, 'run-failed-rounds');
        // A run whose reply has no kind keeps today's words.
        await page.goto(`/app/team/runs/${NO_KIND_RUN}`);
        await expect(page.getByText('Resume it from the run page to retry or stop the turn.', { exact: true })).toBeVisible();
        await expect(page.getByText(ROUND_CANT_RESUME)).toHaveCount(0);

        await page.goto(`/app/workflow/${ROUNDS_RUN}`);
        // The Team run view link shows once Temper's team reply is in.
        await expect(page.getByRole('link', { name: 'Team run view' })).toBeVisible();
        await expect(rerun(page)).toHaveCount(0);
        await page.getByRole('tab', { name: 'Checkpoints' }).click();
        await page.getByText('study', { exact: true }).click();
        await expect(page.getByRole('button', { name: 'View on DAG' })).toBeVisible();
        await expect(page.getByRole('button', { name: 'Re-run from here' })).toHaveCount(0);
        await expect(page.getByRole('button', { name: 'Resume…' })).toHaveCount(0);
        await expect(page.getByText('Use "Resume from Last Checkpoint"')).toHaveCount(0);
        await expectAxeNoSerious(page);
        await shoot(page, `${tag}-run-page-rounds`, SHOTS);

        // A run whose reply has no kind keeps all three, as today.
        await page.goto(`/app/workflow/${NO_KIND_RUN}`);
        await expect(page.getByRole('link', { name: 'Team run view' })).toBeVisible();
        await expect(rerun(page)).toBeVisible();
        await page.getByRole('tab', { name: 'Checkpoints' }).click();
        await expect(page.getByRole('button', { name: 'Resume…' })).toBeVisible();
        await page.getByText('study', { exact: true }).click();
        await expect(page.getByRole('button', { name: 'Re-run from here' })).toBeVisible();
        await shoot(page, `${tag}-run-page-no-kind`, SHOTS);

        // ---- No projects yet, on the new engine ----------------------------------------------
        // No sentence until the status read answers, so today's words never flash first (home's note 1 on #17).
        projects = fixture('trials-empty');
        let releaseStatus = () => {};
        const statusHeld = new Promise<void>((resolve) => {
          releaseStatus = resolve;
        });
        const holdStatus = async (route: Route) => {
          await statusHeld;
          await route.fulfill({
            status: FLOW_STATUS.status,
            contentType: 'application/json',
            body: JSON.stringify(FLOW_STATUS.body),
          });
        };
        await page.route('**/api/team/status', holdStatus);
        await page.goto('/app/team');
        // The Team gate shows nothing until the status read answers, so neither engine's words can show yet.
        await expect(page.getByRole('link', { name: 'Workflows' })).toBeVisible();
        const empty = page.locator('section[aria-labelledby="trials-empty"]');
        await expect(empty).toHaveCount(0);
        await expect(page.getByText(TODAY_EMPTY)).toHaveCount(0);
        await expect(page.getByText(FLOW_EMPTY)).toHaveCount(0);
        releaseStatus();
        await expect(empty.getByRole('heading', { level: 2, name: 'No projects yet' })).toBeVisible();
        await expect(page.getByText(FLOW_EMPTY, { exact: true })).toBeVisible();
        await page.unroute('**/api/team/status', holdStatus);
        await expect(page.getByText(TODAY_EMPTY)).toHaveCount(0);
        await looks(page, 'projects-empty');

        // ---- Today's server: the form and the empty list are exactly today's ------------------
        // Registered last, so it answers the status read first.
        await page.route('**/api/team/status', (route) =>
          route.fulfill({ status: TODAY_STATUS.status, contentType: 'application/json', body: JSON.stringify(TODAY_STATUS.body) }),
        );
        await openForm(page);
        await expect(page.getByLabel('Pause after this many rounds without done')).toHaveValue('');
        await expect(page.locator('#team-pause-help')).toContainText('No default.');
        await expect(every(page)).toHaveCount(0);
        await expect(atOnce(page)).toHaveCount(0);
        await expect(form(page).locator('[data-prefix]')).toHaveCount(0);
        await expect(page.getByText('Members take turns, ask each other for review and send work back.')).toBeVisible();
        await fillTeam(page);
        await page.locator('#team-pause').fill('2');
        await form(page).getByRole('button', { name: 'Check' }).click();
        await expect(page.getByTestId('team-form-result')).toBeVisible();
        expect(sent.checks).toHaveLength(4);
        expect(Object.keys(sent.checks[3])).toEqual(TODAY_KEYS);
        expect(sent.checks[3]).toEqual({
          goal: FLOW_GOAL,
          members: FLOW_BODY.members,
          leader: 'lead',
          pause_after_rounds: 2,
          communication: 'all',
          project_path: null,
        });
        await looks(page, 'form-today');

        await page.goto('/app/team');
        await expect(page.getByRole('heading', { level: 2, name: 'No projects yet' })).toBeVisible();
        await expect(page.getByText(TODAY_EMPTY, { exact: true })).toBeVisible();
        await expect(page.getByText(FLOW_EMPTY)).toHaveCount(0);
        await looks(page, 'projects-empty-today');
      });
    });
  }
}
