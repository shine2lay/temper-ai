/**
 * The Team page's happy path as one journey with many checks (the owner's
 * direction of 2026-10-06: happy paths first, many things in one test): open
 * Team, fill the Run trial form and start the trial, watch the run view,
 * answer the needs-you card, send a message, then read the outcome card and
 * the trials list.
 *
 * Two entries run it:
 * - e2e/team-journey.spec.ts, in the gate: every /api/team answer comes from
 *   the journey-*.json fixtures (one trial the real routes answered,
 *   scripts/capture_team_fixtures.py --only journey) and the page clock is
 *   pinned.
 * - e2e-live/team-journey.live.spec.ts, by hand, against a Temper with Team
 *   on, such as temper's practice-run rig (README.md, "Team journey (live)").
 *
 * The journey installs no route and makes no API call of its own. The
 * owner's context clicks only New trial (the Run trial control), Add member
 * (when the form is given more than one role), Run trial, one answer and
 * Send answer, and Send message; never Stop, Cancel or a setting. Each step
 * is then looked at in both themes at the same URL: light in the owner's
 * context, dark in an observer context that only opens pages. A look runs
 * expectAxeClean and expectTargets (team-helpers.ts, the gate's own bars)
 * and takes a full-page shot when there is a folder for it. The report says,
 * per step and theme, what was checked and what was found.
 *
 * Nothing here knows the members' words: the goal and the message start
 * with a tag (journey-<time>) and are found again by it.
 */
import { expect, type Browser, type BrowserContext, type Page } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { answers, card, expectAxeClean, expectTargets, result, shoot } from './team-helpers';

export const JOURNEY_STEPS = ['team', 'form', 'run', 'needs-you', 'message', 'outcome'] as const;
export type JourneyStep = (typeof JOURNEY_STEPS)[number];
export type Theme = 'light' | 'dark';

/** The Run trial form's choices, named after its labels. Unset: the form's own first choice. */
export interface JourneyForm {
  /** Role, one per member in order (the first leads). Default: one member, the first role offered. */
  roles?: string[];
  /** Pause after this many rounds without done. Default 1: the team asks after its first round. */
  pause?: string;
  /** Who can message whom: the visible label of the way to pick. Default: the one the form picked. */
  whoCanMessage?: string;
  /** Project. Default: empty (Temper's own default). */
  project?: string;
}

export interface JourneyOptions {
  mode: 'live' | 'mocked';
  baseURL: string;
  /** Typed first into the goal and the message, and found again by it. */
  tag: string;
  /** How long to wait for what only the team can change (a new entry, the pause, the end). */
  timeoutMs: number;
  /** Folder for the screenshots; none are taken without one. */
  shotsDir?: string;
  /** Where the report (JSON) goes; none is written without one. */
  reportPath?: string;
  /** The needs-you answer to pick, by the start of its visible label. Default: the first offered. */
  answer?: string;
  form?: JourneyForm;
  /** Stop, passed, after this step. 'form' stops with the form filled in and not sent. */
  stopAfter?: JourneyStep;
  /** The owner's key, kept in the browser the way the dashboard keeps it; never logged or reported. */
  ownerKey?: string;
  /** Mocked mode: set up each page (routes, clock) before it opens anything. */
  prepare?: (page: Page, who: 'owner' | 'observer') => Promise<void>;
  /** Mocked mode: told as each step begins. */
  onStep?: (step: JourneyStep) => void;
}

type Impact = 'critical' | 'serious' | 'moderate' | 'minor';

export interface JourneyLook {
  name: string;
  theme: Theme;
  url: string;
  checks: string[];
  axe: Record<Impact, number>;
  axe_found: string[];
  small_targets: string[];
  screenshot: string | null;
  passed: boolean;
  error?: string;
}

export interface JourneyStepReport {
  step: JourneyStep;
  checks: string[];
  looks: JourneyLook[];
  passed: boolean;
  error?: string;
}

export interface JourneyReport {
  journey: 'team-page';
  mode: 'live' | 'mocked';
  base_url: string;
  tag: string;
  owner_key: 'given' | 'not given';
  stop_after: JourneyStep | null;
  started_at: string;
  ended_at: string | null;
  guard_mode: string | null;
  form: { roles: string[]; pause: string; who_can_message: string; project: 'given' | 'empty' } | null;
  execution_id: string | null;
  answer: string | null;
  answered_by: 'you' | 'unknown caller' | null;
  outcome: string | null;
  steps: JourneyStepReport[];
  result: 'running' | 'passed' | 'failed' | 'stopped';
  failed_step: JourneyStep | null;
  error: string | null;
}

const GOAL_WORDS = 'A practice run of the Team page journey.';
const MESSAGE_WORDS = 'A message from the Team page journey.';
const ANSWER_WORDS = 'Words from the Team page journey.';
const RUN_PATH = /\/team\/runs\/([^/]+)$/;
const ENDED = /^(done|stopped|failed|didnt_start)$/;
const DARK = /(^|\s)dark(\s|$)/;

/** The goal and the message the journey types (the gated twin's fixtures were captured with these). */
export const journeyGoal = (tag: string) => `${tag}\n\n${GOAL_WORDS}`;
export const journeyMessage = (tag: string) => `${tag} ${MESSAGE_WORDS}`;

const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const startsWith = (label: string) => new RegExp(`^\\s*${esc(label.trim())}`, 'i');
const ANSI = new RegExp(String.fromCharCode(27) + '\\[[0-9;]*m', 'g');

/** An error's words for the report: no colour codes, never the key. */
function clean(e: unknown, key: string | undefined): string {
  let words = (e instanceof Error ? e.message : String(e)).replace(ANSI, '');
  if (key) words = words.split(key).join('[the key]');
  return words.length > 4000 ? `${words.slice(0, 4000)}…` : words;
}

const member = (page: Page, n: number) => page.getByTestId('team-form').getByRole('group', { name: `Member ${n}` });
const runBadge = (page: Page) => page.locator('header [data-component="team-state-badge"]').first();
const trialRow = (page: Page, tag: string) => page.locator('[data-trial-row]').filter({ hasText: tag });

/** The timeline's count: the entries in view plus the earlier ones it says it left out. */
async function timelineTotal(page: Page): Promise<number> {
  const text = await page
    .getByRole('region', { name: 'Timeline' })
    .innerText({ timeout: 5_000 })
    .catch(() => '');
  const count = (re: RegExp) => Number((re.exec(text)?.[1] ?? '0').replace(/\D/g, '') || 0);
  return count(/([\d,.\s]+?) entr(?:y|ies), newest first/) + count(/([\d,.\s]+?) earlier entr(?:y|ies) not shown/);
}

/** The roles the form's first member row offers (loaded from Temper). */
async function rolesOffered(page: Page): Promise<string[]> {
  const select = member(page, 1).getByLabel('Role');
  const enabled = () =>
    select
      .locator('option:not([disabled])')
      .evaluateAll((options) => options.map((o) => (o as HTMLOptionElement).value).filter((v) => v !== ''));
  await expect.poll(async () => (await enabled()).length, { message: 'the form offers no role' }).toBeGreaterThan(0);
  return enabled();
}

/** Put the key in as setApiKey (src/lib/authFetch.ts) does. Runs in the page; takes nothing from here but the key. */
function putKey(token: string) {
  localStorage.setItem('temper_api_token', token);
  document.cookie = `temper_token=${encodeURIComponent(token)}; path=/; SameSite=Strict`;
}

class Journey {
  private current!: JourneyStepReport;
  private executionId = '';
  private readonly opts: JourneyOptions;
  private readonly report: JourneyReport;
  private readonly owner: Page;
  private readonly observer: Page;
  private readonly save: () => void;

  constructor(opts: JourneyOptions, report: JourneyReport, owner: Page, observer: Page, save: () => void) {
    this.opts = opts;
    this.report = report;
    this.owner = owner;
    this.observer = observer;
    this.save = save;
  }

  private clean(e: unknown): string {
    return clean(e, this.opts.ownerKey);
  }

  async step(step: JourneyStep) {
    this.current = { step, checks: [], looks: [], passed: false };
    this.report.steps.push(this.current);
    this.opts.onStep?.(step);
    try {
      if (step === 'team') await this.team();
      else if (step === 'form') await this.form();
      else if (step === 'run') await this.run();
      else if (step === 'needs-you') await this.needsYou();
      else if (step === 'message') await this.message();
      else await this.outcome();
      this.current.passed = true;
    } catch (e) {
      this.current.error = this.clean(e);
      this.report.failed_step = step;
      throw e;
    } finally {
      this.save();
    }
  }

  /** One check: its name goes in the report when it passes, and leads the error when it fails. */
  private async check(name: string, body: () => Promise<unknown>) {
    try {
      await body();
    } catch (e) {
      if (e instanceof Error) e.message = `[${this.current.step}] ${name}\n${e.message}`;
      throw e;
    }
    this.current.checks.push(name);
  }

  /** The step's view in both themes: the owner's page as it is, then the observer at the same URL. */
  private async look(name: string, ready: (page: Page) => Promise<unknown>) {
    const at = new URL(this.owner.url());
    await this.lookAt(name, 'light', this.owner, ready);
    await this.observer.goto(at.pathname + at.search);
    await this.lookAt(name, 'dark', this.observer, ready);
  }

  private async lookAt(name: string, theme: Theme, page: Page, ready: (page: Page) => Promise<unknown>) {
    const look: JourneyLook = {
      name,
      theme,
      url: new URL(page.url()).pathname,
      checks: [],
      axe: { critical: 0, serious: 0, moderate: 0, minor: 0 },
      axe_found: [],
      small_targets: [],
      screenshot: null,
      passed: false,
    };
    this.current.looks.push(look);
    try {
      await ready(page);
      look.checks.push('view ready');
      if (theme === 'dark') await expect(page.locator('html')).toHaveClass(DARK);
      else await expect(page.locator('html')).not.toHaveClass(DARK);
      look.checks.push(`${theme} theme`);
      await expectAxeClean(page, (violations, found) => {
        for (const v of violations) look.axe[(v.impact ?? 'minor') as Impact] += 1;
        look.axe_found = found;
      });
      look.checks.push('axe: nothing found');
      await expectTargets(page, (small) => {
        look.small_targets = small;
      });
      look.checks.push('every button and link at least 24 x 24 px');
      look.passed = true;
    } catch (e) {
      look.error = this.clean(e);
      if (e instanceof Error) e.message = `[${this.current.step}] look ${name} (${theme})\n${e.message}`;
      throw e;
    } finally {
      if (this.opts.shotsDir) {
        const file = `${String(this.report.steps.length).padStart(2, '0')}-${name}-${theme}`;
        try {
          await shoot(page, file, this.opts.shotsDir);
          look.screenshot = `${file}.png`;
        } catch {
          // No shot: the look's own result says why.
        }
      }
    }
  }

  // 1. Open Team: the heading, the guard notice as Temper's status says, the Run trial control, no error.
  private async team() {
    const { owner } = this;
    const status = owner.waitForResponse((r) => new URL(r.url()).pathname === '/api/team/status', { timeout: 30_000 });
    await owner.goto('/app/team');
    const res = await status.catch(() => null);
    if (!res) throw new Error(`The page asked Temper for no /api/team/status within 30 s: is ${this.opts.baseURL} a Temper dashboard?`);
    if (res.status() === 404) throw new Error('Team is switched off on this server (GET /api/team/status answered 404).');
    if (res.status() === 401) throw new Error('Temper asked for a key (GET /api/team/status answered 401): give the owner key file.');
    if (!res.ok()) throw new Error(`GET /api/team/status answered ${res.status()}.`);
    const guard = ((await res.json()) as { guard_mode?: string }).guard_mode ?? 'off';
    this.report.guard_mode = guard;

    await this.check('the Team heading', () => expect(owner.getByRole('heading', { level: 1, name: 'Team' })).toBeVisible());
    await this.check(`the guard notice as guard mode ${guard} wants it`, () =>
      guard === 'enforce'
        ? expect(owner.locator('[data-guard-mode]')).toHaveCount(0)
        : expect(owner.locator(`[data-guard-mode="${guard}"]`)).toBeVisible(),
    );
    const newTrial = owner.getByRole('link', { name: 'New trial' });
    await this.check('the Run trial control (New trial) is there and goes to the form', async () => {
      await expect(newTrial).toBeVisible();
      await expect(newTrial).toHaveAttribute('href', /\/team\/new$/);
      await expect(newTrial).not.toHaveAttribute('aria-disabled', 'true');
    });
    await this.check('no error alert', () => expect(owner.getByRole('alert')).toHaveCount(0));
    await this.look('team', async (page) => {
      await expect(page.getByRole('heading', { level: 1, name: 'Team' })).toBeVisible();
      await expect(
        page.getByRole('list', { name: 'Trials' }).or(page.locator('section[aria-labelledby="trials-empty"]')).first(),
      ).toBeVisible();
    });
  }

  // 2. The Run trial form: labelled fields, filled with the tag and the choices; not sent here.
  private async form() {
    const { owner, opts } = this;
    const form = owner.getByTestId('team-form');
    await owner.getByRole('link', { name: 'New trial' }).click();
    await this.check('New trial opens the form', async () => {
      await expect(owner).toHaveURL(/\/team\/new$/);
      await expect(owner.getByRole('heading', { level: 1, name: 'New trial' })).toBeVisible();
      await expect(form).toBeVisible();
    });
    const goal = form.getByLabel('Goal', { exact: true });
    const pause = form.getByLabel('Pause after this many rounds without done');
    const ways = form.getByRole('group', { name: 'Who can message whom' });
    await this.check('the required fields have labels: Goal, Role, Team name, Leader, Pause, Who can message whom', async () => {
      await expect(goal).toBeEditable();
      await expect(member(owner, 1).getByLabel('Role')).toBeEnabled();
      await expect(member(owner, 1).getByLabel('Team name')).toBeEditable();
      await expect(member(owner, 1).getByRole('radio', { name: 'Leader' })).toBeChecked();
      await expect(pause).toBeEditable();
      await expect(ways.getByRole('radio').first()).toBeVisible();
    });

    const roles = opts.form?.roles?.length ? opts.form.roles : (await rolesOffered(owner)).slice(0, 1);
    for (let i = 0; i < roles.length; i++) {
      if (i > 0) await form.getByRole('button', { name: 'Add member' }).click();
      await member(owner, i + 1).getByLabel('Role').selectOption(roles[i]);
    }
    await goal.fill(journeyGoal(opts.tag));
    const pauseAfter = opts.form?.pause ?? '1';
    await pause.fill(pauseAfter);
    if (opts.form?.whoCanMessage) await ways.getByRole('radio', { name: startsWith(opts.form.whoCanMessage) }).check();
    if (opts.form?.project) await form.getByLabel('Project', { exact: true }).fill(opts.form.project);
    const way = ways.getByRole('radio', { checked: true });
    await this.check('the form holds the tagged goal, the roles, the pause and one way to message', async () => {
      await expect(goal).toHaveValue(journeyGoal(opts.tag));
      for (let i = 0; i < roles.length; i++) await expect(member(owner, i + 1).getByLabel('Role')).toHaveValue(roles[i]);
      await expect(pause).toHaveValue(pauseAfter);
      await expect(way).toHaveCount(1);
    });
    this.report.form = {
      roles,
      pause: pauseAfter,
      who_can_message: (await way.getAttribute('value')) ?? '',
      project: opts.form?.project ? 'given' : 'empty',
    };
    await this.look('form', async (page) => {
      await expect(page.getByRole('heading', { level: 1, name: 'New trial' })).toBeVisible();
      await rolesOffered(page);
    });
  }

  // 3. Run trial: the run opens, running, with members, and a new timeline entry comes in without a reload.
  private async run() {
    const { owner, opts } = this;
    await owner.getByTestId('team-form').getByRole('button', { name: 'Run trial' }).click();
    const note = owner.getByTestId('team-form-result');
    const opened = () => RUN_PATH.test(new URL(owner.url()).pathname);
    await this.check('Temper starts the trial and its run opens', async () => {
      await expect
        .poll(async () => opened() || ((await note.innerText().catch(() => '')).trim() !== ''), {
          timeout: opts.timeoutMs,
          message: 'the run never opened',
        })
        .toBe(true);
      if (!opened()) throw new Error(`Temper did not start the trial: ${(await note.innerText()).trim()}`);
    });
    this.executionId = decodeURIComponent(RUN_PATH.exec(new URL(owner.url()).pathname)?.[1] ?? '');
    this.report.execution_id = this.executionId;
    await owner.evaluate(() => {
      (window as unknown as { teamJourney?: string }).teamJourney = 'not reloaded';
    });

    await this.check('the header says running', () =>
      expect(
        runBadge(owner),
        'the run must be running when the page reads it: the team has to keep working for at least 10 s before it pauses (the page reads every 5 s)',
      ).toHaveAttribute('data-state', 'running', { timeout: 30_000 }),
    );
    await this.check('at least one member', async () => {
      const members = owner.getByRole('region', { name: /^Members \(\d+\)$/ });
      await expect(members).toBeVisible();
      expect(await members.getByRole('listitem').count()).toBeGreaterThan(0);
    });
    const before = await timelineTotal(owner);
    await this.check('a new timeline entry comes in without a reload', async () => {
      await expect
        .poll(() => timelineTotal(owner), { timeout: opts.timeoutMs, message: `no entry came in after the first ${before}` })
        .toBeGreaterThan(before);
      expect(await owner.evaluate(() => (window as unknown as { teamJourney?: string }).teamJourney)).toBe('not reloaded');
    });
    await this.look('run', async (page) => {
      await expect(runBadge(page)).toBeVisible();
      await expect(page.getByRole('region', { name: /^Members \(\d+\)$/ })).toBeVisible();
      await expect(page.getByRole('region', { name: 'Timeline' })).toBeVisible();
    });
  }

  // 4. The needs-you card: pick the answer, send it; the result region and the timeline say it was yours.
  private async needsYou() {
    const { owner, opts } = this;
    await this.check('the needs-you card comes up', () => expect(card(owner)).toBeVisible({ timeout: opts.timeoutMs }));
    await this.check('it asks with a title and offers answers', async () => {
      await expect(card(owner).getByRole('heading').first()).toBeVisible();
      await expect(answers(owner).getByRole('radio').first()).toBeVisible();
    });
    await this.look('needs-you', (page) => expect(card(page)).toBeVisible({ timeout: 30_000 }));

    const radio = opts.answer
      ? answers(owner).getByRole('radio', { name: startsWith(opts.answer) })
      : answers(owner).getByRole('radio').first();
    await this.check(`the answer to pick is offered (${opts.answer ?? 'the first'})`, () => expect(radio).toHaveCount(1));
    const answer = (await radio.getAttribute('value')) ?? '';
    if (answer === 'stop') throw new Error('The journey never stops the team: pick another answer.');
    this.report.answer = answer;
    await radio.check();
    const words = card(owner).locator('textarea');
    if ((await words.count()) > 0 && (await card(owner).getByText('required', { exact: true }).count()) > 0) {
      await words.fill(`${opts.tag} ${ANSWER_WORDS}`);
    }
    await card(owner).getByRole('button', { name: 'Send answer' }).click();
    await this.check(`the result region confirms: Answer sent: ${answer}.`, async () => {
      await expect(result(owner)).toHaveAttribute('data-answer-result', 'sent', { timeout: 30_000 });
      await expect(result(owner)).toContainText(`Answer sent: ${answer}.`);
    });
    const who = opts.ownerKey ? 'owner' : 'unknown';
    this.report.answered_by = opts.ownerKey ? 'you' : 'unknown caller';
    const row = owner.locator('li[data-entry="owner_answer"]').first();
    await this.check(
      `the timeline shows it answered by ${opts.ownerKey ? 'you' : 'an unknown caller (no key given)'}, with the time`,
      async () => {
        await expect(row).toBeVisible({ timeout: opts.timeoutMs });
        await expect(row).toContainText(answer);
        await expect(row.locator('time[datetime]').first()).toBeVisible();
        await expect(row.locator(`[data-who="${who}"]`).first()).toBeVisible();
        if (opts.ownerKey) await expect(row).toContainText('You');
      },
    );
    await this.look('needs-you-answered', (page) =>
      expect(page.locator('li[data-entry="owner_answer"]').first()).toBeVisible({ timeout: 30_000 }),
    );
  }

  // 5. A message: Temper takes it, the box clears, and it shows in the timeline with the tag.
  private async message() {
    const { owner, opts } = this;
    const composer = owner.locator('[data-card="composer"]');
    await this.check('the message box is open', () => expect(composer).toBeVisible({ timeout: 30_000 }));
    const box = composer.getByLabel('Message', { exact: true });
    await box.fill(journeyMessage(opts.tag));
    await composer.getByRole('button', { name: 'Send message' }).click();
    const note = owner.getByTestId('team-message-result');
    await this.check('Temper takes it (Sent), no refusal', async () => {
      await expect(note).toContainText('Sent', { timeout: 30_000 });
      await expect(note).not.toContainText('Temper refused');
    });
    await this.check('the box clears', () => expect(box).toHaveValue(''));
    const tagged = (page: Page) => page.locator('li[data-entry="message"]').filter({ hasText: opts.tag }).first();
    await this.check('the message shows in the timeline with the tag', () =>
      expect(tagged(owner)).toBeVisible({ timeout: opts.timeoutMs }),
    );
    await this.look('message', (page) => expect(tagged(page)).toBeVisible({ timeout: 30_000 }));
  }

  // 6. The end: the outcome card, the same state in the trials list, and its link back to the run.
  private async outcome() {
    const { owner, opts } = this;
    const outcomeCard = (page: Page) => page.locator('[data-card="outcome"]');
    await this.check('the run ends: the outcome card shows an end state', async () => {
      await expect(outcomeCard(owner)).toBeVisible({ timeout: opts.timeoutMs });
      await expect(outcomeCard(owner)).toHaveAttribute('data-outcome', ENDED);
    });
    const state = (await outcomeCard(owner).getAttribute('data-outcome')) ?? '';
    this.report.outcome = state;
    await this.check(`the outcome card and the header both say ${state}`, async () => {
      await expect(outcomeCard(owner).locator('[data-component="team-state-badge"]').first()).toHaveAttribute('data-state', state);
      await expect(outcomeCard(owner).getByRole('heading', { level: 2 }).first()).toBeVisible();
      await expect(runBadge(owner)).toHaveAttribute('data-state', state);
    });
    await this.look('outcome', (page) => expect(outcomeCard(page)).toBeVisible({ timeout: 30_000 }));

    await owner.goto('/app/team');
    const row = trialRow(owner, opts.tag);
    const link = row.locator(`a[href$="/team/runs/${encodeURIComponent(this.executionId)}"]`).first();
    await this.check('the trials list shows the tagged trial', () => expect(row).toHaveCount(1, { timeout: 30_000 }));
    await this.check(`there it is ${state} too`, () =>
      expect(row.locator('[data-component="team-state-badge"]').first()).toHaveAttribute('data-state', state, {
        timeout: 30_000,
      }),
    );
    await this.check('its link goes to the same run', () => expect(link).toBeVisible());
    await this.look('trials', (page) => expect(trialRow(page, opts.tag)).toHaveCount(1, { timeout: 30_000 }));

    const href = (await link.getAttribute('href')) ?? '';
    await owner.goto(href);
    await this.check(`the link opens the same run, ended ${state}`, async () => {
      expect(decodeURIComponent(RUN_PATH.exec(new URL(owner.url()).pathname)?.[1] ?? '')).toBe(this.executionId);
      await expect(outcomeCard(owner)).toHaveAttribute('data-outcome', state, { timeout: 30_000 });
      await expect(owner.getByRole('heading', { level: 1 })).toContainText(opts.tag);
    });
  }
}

async function openPage(
  browser: Browser,
  opts: JourneyOptions,
  theme: Theme,
  who: 'owner' | 'observer',
  contexts: BrowserContext[],
): Promise<Page> {
  const context = await browser.newContext({
    baseURL: opts.baseURL,
    viewport: { width: 1440, height: 900 },
    serviceWorkers: 'block',
  });
  contexts.push(context);
  await context.addInitScript((t) => localStorage.setItem('temper_theme', t), theme);
  // The observer gets the key too where Temper asks one for reads; it only opens pages, so it changes nothing.
  if (opts.ownerKey) await context.addInitScript(putKey, opts.ownerKey);
  const page = await context.newPage();
  await opts.prepare?.(page, who);
  return page;
}

/**
 * Walk the journey, step by step, up to `stopAfter` or the end. The report is
 * written after every step and once more at the end; a failure is rethrown
 * after it is in the report.
 */
export async function teamJourney(browser: Browser, opts: JourneyOptions): Promise<JourneyReport> {
  const report: JourneyReport = {
    journey: 'team-page',
    mode: opts.mode,
    base_url: opts.baseURL,
    tag: opts.tag,
    owner_key: opts.ownerKey ? 'given' : 'not given',
    stop_after: opts.stopAfter ?? null,
    started_at: new Date().toISOString(),
    ended_at: null,
    guard_mode: null,
    form: null,
    execution_id: null,
    answer: null,
    answered_by: null,
    outcome: null,
    steps: [],
    result: 'running',
    failed_step: null,
    error: null,
  };
  const save = () => {
    if (!opts.reportPath) return;
    mkdirSync(path.dirname(opts.reportPath), { recursive: true });
    writeFileSync(opts.reportPath, `${JSON.stringify(report, null, 2)}\n`);
  };
  if (opts.shotsDir) mkdirSync(opts.shotsDir, { recursive: true });
  const contexts: BrowserContext[] = [];
  try {
    const owner = await openPage(browser, opts, 'light', 'owner', contexts);
    const observer = await openPage(browser, opts, 'dark', 'observer', contexts);
    const journey = new Journey(opts, report, owner, observer, save);
    for (const step of JOURNEY_STEPS) {
      await journey.step(step);
      if (opts.stopAfter === step) {
        report.result = 'stopped';
        break;
      }
    }
    if (report.result === 'running') report.result = 'passed';
  } catch (e) {
    report.result = 'failed';
    report.error = clean(e, opts.ownerKey);
    if (opts.ownerKey && String(e).includes(opts.ownerKey)) throw new Error(report.error);
    throw e;
  } finally {
    report.ended_at = new Date().toISOString();
    save();
    for (const context of contexts) await context.close().catch(() => undefined);
  }
  return report;
}
