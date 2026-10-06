/**
 * Shared helpers for the Team page's e2e specs (team.spec.ts: the run view;
 * team-c.spec.ts: the trials, roles, form, composer, guard and settings).
 *
 * The /api/team routes are served from the fixtures the routes really
 * answered (e2e/fixtures/team, made by scripts/capture_team_fixtures.py), so
 * the specs run on a server with the Team switch off, as CI's is, and start
 * no team trial and call no model.
 */
import { expect, type Page, type Route } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { readFileSync } from 'node:fs';
import path from 'node:path';

export interface Fixture {
  route: string;
  status: number;
  body: unknown;
}

export function fixture(name: string): Fixture {
  const file = path.join(process.cwd(), 'e2e/fixtures/team', `${name}.json`);
  return JSON.parse(readFileSync(file, 'utf8')) as Fixture;
}

/** A fixture with its body changed (the stress cases the harness can't reach). */
export function withBody(name: string, change: (body: Record<string, unknown>) => unknown): Fixture {
  const f = fixture(name);
  return { ...f, body: change(structuredClone(f.body) as Record<string, unknown>) };
}

export const RUN_ID = (fixture('run-running').body as { execution_id: string }).execution_id;
export const SHOTS = process.env.TEAM_SHOTS;
export const AXE_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'];

/** A fixture's body with the run's id swapped for another (a real run on this server). */
export function asRun(name: string, executionId: string): Fixture {
  const f = fixture(name);
  return { ...f, body: { ...(f.body as object), execution_id: executionId } };
}

export const RUN_READ = /^\/api\/team\/runs\/[^/]+$/;

/**
 * The message reads Temper really answered, by message id. A message
 * nobody captured gets Temper's own 404, never another message's body.
 */
const MESSAGES = new Map(
  ['message-read', 'message-read-owner'].map((name) => [(fixture(name).body as { message_id: string }).message_id, name]),
);

function messageRead(pathname: string): Fixture {
  return fixture(MESSAGES.get(pathname.split('/').pop() ?? '') ?? 'message-read-404');
}

/** A read's answer: a fixture, or one made from the request's URL (paging, filters). */
export type Read = Fixture | ((url: URL) => Fixture);

const answerOf = (read: Read, url: URL): Fixture => (typeof read === 'function' ? read(url) : read);

/**
 * Serve the GETs under /api/team/* from fixtures. `run` is a list: each
 * read of the run takes the next answer and the last one repeats. It can
 * also be a function, read at each request (to answer by what the page has
 * sent). A message is answered by its id, unless `message` is given. The
 * trials list and the role list answer `trials-list` and `roles-ok` unless
 * given. Every path asked is kept in the list returned.
 */
export async function serveTeam(
  page: Page,
  {
    status = fixture('status-on'),
    run = [fixture('run-running')],
    message,
    trials = fixture('trials-list'),
    roles = fixture('roles-ok'),
  }: {
    status?: Fixture;
    run?: Fixture[] | (() => Fixture);
    message?: Fixture;
    trials?: Read;
    roles?: Read;
  } = {},
): Promise<string[]> {
  const seen: string[] = [];
  let reads = 0;
  await page.route('**/api/team/**', async (route) => {
    const url = new URL(route.request().url());
    const { pathname } = url;
    seen.push(pathname + url.search);
    let answer: Fixture;
    if (pathname === '/api/team/status') answer = status;
    else if (pathname === '/api/team/trials') answer = answerOf(trials, url);
    else if (pathname === '/api/team/roles') answer = answerOf(roles, url);
    else if (/^\/api\/team\/runs\/[^/]+\/messages\/[^/]+$/.test(pathname)) answer = message ?? messageRead(pathname);
    else if (RUN_READ.test(pathname)) answer = typeof run === 'function' ? run() : run[Math.min(reads++, run.length - 1)];
    else answer = { route: '', status: 404, body: { detail: 'Not Found' } };
    await route.fulfill({ status: answer.status, contentType: 'application/json', body: JSON.stringify(answer.body) });
  });
  return seen;
}

/**
 * A reply to a POST: a fixture, no reply at all (the connection fails), or
 * a reply held until `until` settles (to see the page while it sends).
 */
export type Reply = Fixture | 'no reply' | { until: Promise<unknown>; then: Fixture | 'no reply' };

export interface Sent {
  answers: Record<string, unknown>[];
  cancels: Record<string, unknown>[];
  checks: Record<string, unknown>[];
  trials: Record<string, unknown>[];
  messages: Record<string, unknown>[];
}

export const nothingSent = (): Sent => ({ answers: [], cancels: [], checks: [], trials: [], messages: [] });

/**
 * Serve the POSTs the Team page makes: team_answer, the run page's cancel,
 * team_check, team_trial_start and team_message. Each takes the next reply
 * (the last repeats); the bodies the page sent are kept in `sent`.
 */
export async function serveActions(
  page: Page,
  sent: Sent,
  {
    answer = [],
    cancel = [],
    check = [],
    trial = [],
    message = [],
  }: { answer?: Reply[]; cancel?: Reply[]; check?: Reply[]; trial?: Reply[]; message?: Reply[] },
) {
  const reply = async (route: Route, replies: Reply[], n: number) => {
    let r = replies[Math.min(n - 1, replies.length - 1)];
    if (r && typeof r === 'object' && 'until' in r) {
      await r.until;
      r = r.then;
    }
    if (!r || r === 'no reply') return route.abort('failed');
    await route.fulfill({ status: r.status, contentType: 'application/json', body: JSON.stringify(r.body) });
  };
  const post = (list: Record<string, unknown>[], replies: Reply[]) => async (route: Route) => {
    if (route.request().method() !== 'POST') return route.fallback();
    list.push(route.request().postDataJSON() as Record<string, unknown>);
    await reply(route, replies, list.length);
  };
  await page.route('**/api/team/runs/*/waits/*/answer', post(sent.answers, answer));
  await page.route('**/api/runs/*/cancel', post(sent.cancels, cancel));
  await page.route('**/api/team/check', post(sent.checks, check));
  await page.route('**/api/team/trials', post(sent.trials, trial));
  await page.route('**/api/team/runs/*/messages', post(sent.messages, message));
}

/** The run view of `before`, which reads as `after` once the page has sent an answer or a stop. */
export async function openRun(
  page: Page,
  before: string,
  {
    after = before,
    answer = [],
    cancel = [],
    message = [],
    status,
  }: { after?: string; answer?: Reply[]; cancel?: Reply[]; message?: Reply[]; status?: Fixture } = {},
): Promise<{ sent: Sent; seen: string[] }> {
  const sent = nothingSent();
  const seen = await serveTeam(page, {
    status,
    run: () => fixture(sent.answers.length + sent.cancels.length > 0 ? after : before),
  });
  await serveActions(page, sent, { answer, cancel, message });
  await page.goto(`/app/team/runs/${RUN_ID}`);
  await expect(page.getByRole('heading', { level: 1 })).not.toHaveText('Team run');
  return { sent, seen };
}

/** Temper's words in a refusal body, as the page must show them. */
export function refusalText(name: string): string {
  const body = fixture(name).body as { problem?: string; message?: string; detail?: string };
  return body.problem ?? body.message ?? body.detail ?? '';
}

export const card = (page: Page) => page.locator('[data-card="needs-you"]');
export const answers = (page: Page) => card(page).getByRole('group', { name: 'Your answer' });
export const result = (page: Page) => page.locator('#team-answer-result');

/** Pick an answer in the needs-you card and, when given, write its words. */
export async function pick(page: Page, answer: string, words?: string) {
  await answers(page).getByRole('radio', { name: new RegExp(`^${answer}\\b`) }).check();
  if (words !== undefined) await card(page).getByRole('textbox').fill(words);
}

export const runReads = (seen: string[]) => seen.filter((p) => RUN_READ.test(p)).length;

/** axe on the whole page: nothing found. */
export async function expectAxeClean(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze();
  const found = results.violations.map((v) => `${v.id} (${v.impact}): ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`);
  expect(found, 'axe found problems').toEqual([]);
}

/** Every button and link on the Team page is at least 24 x 24 px (WCAG 2.5.8). */
export async function expectTargets(page: Page) {
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

export async function shoot(page: Page, name: string) {
  if (!SHOTS) return;
  // The dashboard scrolls inside its main column, so a full-page shot stops at the window's
  // height. Grow the window to the tallest scrolled content for the shot, then put it back.
  const size = page.viewportSize();
  const tall = await page.evaluate(() => {
    let bottom = document.documentElement.scrollHeight;
    for (const el of Array.from(document.querySelectorAll<HTMLElement>('*'))) {
      const style = getComputedStyle(el);
      if (!/(auto|scroll)/.test(style.overflowY) || el.scrollHeight <= el.clientHeight) continue;
      bottom = Math.max(bottom, el.getBoundingClientRect().top + el.scrollHeight);
    }
    return Math.ceil(bottom);
  });
  if (size && tall > size.height) await page.setViewportSize({ width: size.width, height: tall });
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: true });
  if (size && tall > size.height) await page.setViewportSize(size);
}
