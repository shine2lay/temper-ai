/**
 * The Team page journey in the gate: e2e/team-journey.ts with every
 * /api/team answer taken from one trial the real routes answered
 * (fixtures/team/journey-*.json, scripts/capture_team_fixtures.py --only
 * journey) and the page clock pinned. The same journey runs live by hand
 * (e2e-live/team-journey.live.spec.ts), where it starts a real project, so a
 * page change that would break it fails here first.
 *
 * The run's answers follow the journey: the first read after the start is
 * running, later reads running with more entries, the needs-you step paused,
 * then what the page has sent (answered, messaged), and the outcome step
 * done. The observer's reads never move it on.
 *
 * No journey here may write to a real Temper: every page's first route stops
 * any write the mocks don't answer. One test needs a real server (Team off) and
 * is tagged @needs-server, so the server-free run leaves it out; it stops after
 * the Team step.
 */
import { expect, test, type Page } from '@playwright/test';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { privateFolder } from './privateFolder';
import { JOURNEY_STEPS, journeyGoal, journeyMessage, teamJourney, type JourneyStep } from './team-journey';
import { fixture, nothingSent, serveActions, serveTeam, SHOTS, type Fixture } from './team-helpers';

/** The tag the fixtures were captured with (capture_team_fixtures.py, JOURNEY_TAG). */
const TAG = 'journey-2026-01-01T09:00:00.000Z';
/** A made-up key: the journey must send it as the dashboard does and never put it in the report. */
const KEY = 'journey-made-up-key-0000';
/** Five minutes after the captured trial's last event. */
const NOW = new Date('2026-10-07T02:22:46Z');
const STARTED = fixture('journey-trial-start-201').body as { execution_id: string };

interface Write {
  who: string;
  path: string;
  auth: string | undefined;
}

/**
 * Set up first on a page, so it has the last word: a read the mocks leave goes
 * on to this server; a write they leave is stopped in the browser and noted.
 */
async function stopWrites(page: Page, stopped: string[]) {
  await page.route('**/*', (route) => {
    const r = route.request();
    if (r.method() === 'GET' || r.method() === 'HEAD') return route.fallback();
    stopped.push(`${r.method()} ${new URL(r.url()).pathname}`);
    return route.abort('blockedbyclient');
  });
}

/** The journey's Temper: the run's answer moves on with the journey and with what the owner's page sent. */
function journeyServer() {
  const sent = nothingSent();
  const writes: Write[] = [];
  const stopped: string[] = [];
  let step: JourneyStep = 'team';
  let ownerReads = 0;
  const now = (): Fixture => {
    if (step === 'outcome') return fixture('journey-run-done');
    if (sent.messages.length) return fixture('journey-run-messaged');
    if (sent.answers.length) return fixture('journey-run-answered');
    if (step === 'needs-you') return fixture('journey-run-paused');
    return fixture(ownerReads <= 1 ? 'journey-run-running' : 'journey-run-running-more');
  };
  const prepare = async (page: Page, who: 'owner' | 'observer') => {
    await stopWrites(page, stopped);
    await page.clock.setFixedTime(NOW);
    page.on('request', (r) => {
      const url = new URL(r.url());
      if (r.method() !== 'GET' && url.pathname.startsWith('/api/')) {
        writes.push({ who, path: url.pathname, auth: r.headers()['authorization'] });
      }
    });
    await serveTeam(page, {
      run:
        who === 'owner'
          ? () => {
              ownerReads += 1;
              return now();
            }
          : now,
      trials: () => fixture(sent.trials.length ? 'journey-trials' : 'trials-empty'),
    });
    if (who === 'owner') {
      await serveActions(page, sent, {
        trial: [fixture('journey-trial-start-201')],
        answer: [fixture('journey-answer-200')],
        message: [fixture('journey-message-201')],
      });
    }
  };
  return { sent, writes, stopped, prepare, onStep: (s: JourneyStep) => (step = s) };
}

test.describe('Team page journey', () => {
  test('start a project, watch it, answer, message, read the outcome and the projects, in both themes', async ({
    browser,
    baseURL,
  }, testInfo) => {
    test.setTimeout(180_000);
    const server = journeyServer();
    const reportPath = testInfo.outputPath('report.json');
    const report = await teamJourney(browser, {
      mode: 'mocked',
      baseURL: baseURL ?? '',
      tag: TAG,
      timeoutMs: 30_000,
      shotsDir: SHOTS ? path.join(SHOTS, 'journey') : undefined,
      reportPath,
      ownerKey: KEY,
      form: { roles: ['planner', 'builder', 'reviewer'] },
      prepare: server.prepare,
      onStep: server.onStep,
    });

    // Every step and every look passed, each look in both themes.
    expect(report.result).toBe('passed');
    expect(report.steps.map((s) => s.step)).toEqual([...JOURNEY_STEPS]);
    expect(report.steps.every((s) => s.passed && s.checks.length > 0)).toBe(true);
    const looks = report.steps.flatMap((s) => s.looks);
    expect(looks.map((l) => `${l.name} ${l.theme}`)).toEqual(
      ['team', 'form', 'run', 'needs-you', 'needs-you-answered', 'message', 'outcome', 'trials'].flatMap((n) => [
        `${n} light`,
        `${n} dark`,
      ]),
    );
    for (const look of looks) {
      expect(look.passed, `${look.name} ${look.theme}`).toBe(true);
      expect(look.axe).toEqual({ critical: 0, serious: 0, moderate: 0, minor: 0 });
      expect(look.small_targets).toEqual([]);
    }
    expect(report).toMatchObject({
      guard_mode: 'off',
      execution_id: STARTED.execution_id,
      answer: 'continue',
      answered_by: 'you',
      outcome: 'done',
      form: { roles: ['planner', 'builder', 'reviewer'], pause: '1', who_can_message: 'all', project: 'empty' },
    });

    // What the page sent: one trial, one answer, one message, each as the owner would send them.
    const { sent, writes } = server;
    expect(sent.trials).toHaveLength(1);
    expect(sent.trials[0]).toMatchObject({
      goal: journeyGoal(TAG),
      members: [{ role: 'planner' }, { role: 'builder' }, { role: 'reviewer' }],
      leader: 'planner',
      pause_after_rounds: 1,
      communication: 'all',
      project_path: null,
    });
    expect(sent.answers).toEqual([expect.objectContaining({ answer: 'continue' })]);
    expect(sent.messages).toEqual([expect.objectContaining({ to: 'lead', body: journeyMessage(TAG) })]);
    expect(sent.cancels).toEqual([]);
    expect(sent.checks).toEqual([]);

    // Only the owner's page wrote, three times, each with the key as the dashboard sends it.
    expect(writes.map((w) => `${w.who} ${w.path.replace(/[0-9a-f-]{32,36}/g, '<id>')}`)).toEqual([
      'owner /api/team/trials',
      'owner /api/team/runs/<id>/waits/<id>/answer',
      'owner /api/team/runs/<id>/messages',
    ]);
    expect(writes.every((w) => w.auth === `Bearer ${KEY}`)).toBe(true);
    // Nothing got past the mocks to this server.
    expect(server.stopped).toEqual([]);

    // The key is nowhere in the report.
    expect(readFileSync(reportPath, 'utf8')).not.toContain(KEY);
  });

  test('stops where asked: after Team with Team on, before the form, and after the form, filled in and not sent', async ({
    browser,
    baseURL,
  }) => {
    // Team on (status 200), stopped after the Team step: the form step never begins, so Run project is never clicked.
    const atTeam = journeyServer();
    const begun: JourneyStep[] = [];
    const first = await teamJourney(browser, {
      mode: 'mocked',
      baseURL: baseURL ?? '',
      tag: TAG,
      timeoutMs: 30_000,
      stopAfter: 'team',
      prepare: atTeam.prepare,
      onStep: (s) => {
        begun.push(s);
        atTeam.onStep(s);
      },
    });
    expect(first.result).toBe('stopped');
    expect(first.guard_mode).toBe('off');
    expect(begun).toEqual(['team']);
    expect(first.steps.map((s) => `${s.step} ${s.passed}`)).toEqual(['team true']);
    expect(first.form).toBeNull();
    expect([...atTeam.writes, ...atTeam.stopped]).toEqual([]);

    const server = journeyServer();
    const report = await teamJourney(browser, {
      mode: 'mocked',
      baseURL: baseURL ?? '',
      tag: TAG,
      timeoutMs: 30_000,
      stopAfter: 'form',
      prepare: server.prepare,
      onStep: server.onStep,
    });
    expect(report.result).toBe('stopped');
    expect(report.steps.map((s) => `${s.step} ${s.passed}`)).toEqual(['team true', 'form true']);
    // Unset, the form's own first choices: one member with the first role offered (roles-ok lists builder first).
    expect(report.form).toMatchObject({ roles: ['builder'], pause: '1', who_can_message: 'all' });
    expect([...server.writes, ...server.stopped]).toEqual([]);
  });

  test('Team off, mocked: stops at the first step with the switched-off message and writes nothing', async ({
    browser,
    baseURL,
  }) => {
    // Mocked: every /api/team answer is the 404 a Team-off Temper gives.
    const mocked = { stopped: [] as string[], begun: [] as JourneyStep[] };
    await expect(
      teamJourney(browser, {
        mode: 'mocked',
        baseURL: baseURL ?? '',
        tag: TAG,
        timeoutMs: 30_000,
        stopAfter: 'team',
        prepare: async (page) => {
          await stopWrites(page, mocked.stopped);
          await page.route('**/api/team/**', (route) =>
            route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'Not Found' }) }),
          );
        },
        onStep: (s) => {
          mocked.begun.push(s);
        },
      }),
    ).rejects.toThrow('Team is switched off on this server');
    expect(mocked).toEqual({ stopped: [], begun: ['team'] });
  });

  test('Team off, on this server: stops at the first step and writes nothing', { tag: '@needs-server' }, async ({ browser, baseURL }) => {
    // A real server with Team off, read only: stopped after the Team step, and every
    // write stopped in the browser, so whatever it answers, nothing is sent to it.
    const here = { stopped: [] as string[], begun: [] as JourneyStep[] };
    await expect(
      teamJourney(browser, {
        mode: 'live',
        baseURL: baseURL ?? '',
        tag: TAG,
        timeoutMs: 30_000,
        stopAfter: 'team',
        prepare: (page) => stopWrites(page, here.stopped),
        onStep: (s) => {
          here.begun.push(s);
        },
      }),
    ).rejects.toThrow('Team is switched off on this server');
    expect(here).toEqual({ stopped: [], begun: ['team'] });

    // The tripwire itself, on a page set up as the journeys' are: a read goes on to this server, a write is stopped in the browser.
    const probe: string[] = [];
    const context = await browser.newContext({ baseURL });
    try {
      const page = await context.newPage();
      await stopWrites(page, probe);
      await page.goto('/api/health');
      const tried = await page.evaluate(async () => ({
        read: await fetch('/api/health').then(
          (r) => r.status,
          () => 0,
        ),
        write: await fetch('/api/team/trials', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: '{}',
        }).then(
          (r) => `sent, answered ${r.status}`,
          () => 'stopped',
        ),
      }));
      expect(tried).toEqual({ read: 200, write: 'stopped' });
      expect(probe).toEqual(['POST /api/team/trials']);
    } finally {
      await context.close();
    }
  });

  test('the live entry keeps its shots out of every checkout: plain paths, links into one, folders still to be made', () => {
    const tmp = realpathSync(mkdtempSync(path.join(os.tmpdir(), 'team-journey-folder-')));
    try {
      const repo = path.join(tmp, 'repo');
      mkdirSync(path.join(repo, '.git'), { recursive: true });
      mkdirSync(path.join(repo, 'frontend'));
      const worktree = path.join(tmp, 'worktree');
      mkdirSync(worktree);
      writeFileSync(path.join(worktree, '.git'), 'gitdir: /elsewhere\n');
      const outside = path.join(tmp, 'outside');
      mkdirSync(outside);
      symlinkSync(path.join(repo, 'frontend'), path.join(outside, 'into-repo'));
      symlinkSync(path.join(repo, 'frontend', 'gone'), path.join(outside, 'nowhere'));
      symlinkSync(outside, path.join(tmp, 'to-outside'));

      const refused = (dir: string | undefined, why: string) => expect(() => privateFolder(dir), String(dir)).toThrow(why);
      // Plain paths in a checkout, there or still to be made; a worktree's .git file counts too.
      refused(path.join(repo, 'frontend'), `inside the git checkout ${repo}:`);
      refused(path.join(repo, 'frontend', 'shots', 'new'), `inside the git checkout ${repo}:`);
      refused(path.join(worktree, 'shots'), `inside the git checkout ${worktree}:`);
      // A link from outside into a checkout, with and without folders still to be made under it.
      refused(path.join(outside, 'into-repo'), `inside the git checkout ${repo} (`);
      refused(path.join(outside, 'into-repo', 'shots', 'new'), `really is ${path.join(repo, 'frontend', 'shots', 'new')})`);
      // A link to nothing, a way up, a relative path, nothing at all.
      refused(path.join(outside, 'nowhere', 'shots'), 'leads nowhere real');
      refused(`${outside}/into-repo/../shots`, "must not go up with '..'");
      refused('shots/journey', 'absolute folder outside every git checkout');
      refused('', 'absolute folder outside every git checkout');
      refused(undefined, 'absolute folder outside every git checkout');
      // Asking made nothing.
      expect(existsSync(path.join(repo, 'frontend', 'shots'))).toBe(false);

      // Outside every checkout it is allowed, as the real folder, there or still to be made.
      expect(privateFolder(path.join(outside, 'shots', 'new'))).toBe(path.join(outside, 'shots', 'new'));
      expect(privateFolder(path.join(tmp, 'to-outside', 'shots'))).toBe(path.join(outside, 'shots'));
      expect(privateFolder(`${outside}/`)).toBe(outside);
    } finally {
      rmSync(tmp, { recursive: true, force: true });
    }
  });
});
