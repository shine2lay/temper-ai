/**
 * Script agents' logs in a browser: what a script prints shows while it runs, comes back after a
 * reload, and stays after the script failed, timed out or was cancelled.
 *
 * The runs are the zero-cost `ci_script_log` and `ci_script_log_timeout` workflows: script agents
 * printing made-up lines on a timer (configs/agents/ci_log_talker.yaml, ci_log_stuck.yaml), so no
 * model, no key and no network. Timing and completeness are asserted against the API (the saved
 * log, the agent's status); screenshots are only evidence, written to TEMPER_PROOF_DIR when set.
 */
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { isTeamSwitchOffConsole, waitForFinish } from './helpers';

const OUT = process.env.TEMPER_PROOF_DIR;

function watchForTrouble(page: Page): string[] {
  const trouble: string[] = [];
  page.on('pageerror', (err) => {
    trouble.push(`pageerror: ${err.message}\n${err.stack ?? ''}`);
  });
  page.on('console', (msg) => {
    if (msg.type() === 'error' && !isTeamSwitchOffConsole(msg)) trouble.push(`console: ${msg.text()}`);
  });
  return trouble;
}

async function shoot(page: Page, name: string) {
  if (OUT) await page.screenshot({ path: `${OUT}/${name}.png` });
}

async function startRun(request: APIRequestContext, workflow: string, inputs: Record<string, string> = {}) {
  const res = await request.post('/api/runs', { data: { workflow, inputs } });
  expect(res.ok(), `could not start ${workflow}: ${res.status()} ${await res.text()}`).toBeTruthy();
  return (await res.json()).execution_id as string;
}

interface Agent {
  id: string;
  status: string;
  output?: unknown;
  output_data?: unknown;
  log?: { saved_bytes?: number; truncated?: boolean; complete?: boolean; limit?: number } | null;
}

async function agentOf(request: APIRequestContext, runId: string, node: string): Promise<Agent | null> {
  const res = await request.get(`/api/workflows/${runId}`);
  if (!res.ok()) return null;
  const body = await res.json();
  for (const n of body.nodes ?? []) {
    if (n.name === node && n.agent?.id) return n.agent as Agent;
  }
  return null;
}

/** Wait until the node's agent has started, and return it. */
async function waitForAgent(request: APIRequestContext, runId: string, node: string): Promise<Agent> {
  for (let i = 0; i < 60; i++) {
    const agent = await agentOf(request, runId, node);
    if (agent) return agent;
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`${node} never started in run ${runId}`);
}

interface Entry {
  stream: string;
  text: string;
  kind?: string;
}

/** The whole saved log of one attempt, read page by page from the start. */
async function savedLog(request: APIRequestContext, runId: string, attemptId: string) {
  const entries: Entry[] = [];
  let after = 0;
  let rows = 0;
  for (;;) {
    const res = await request.get(`/api/runs/${runId}/agents/${attemptId}/log?after_seq=${after}&max_bytes=4194304`);
    expect(res.ok()).toBeTruthy();
    const page = await res.json();
    for (const row of page.rows) {
      expect(row.seq, 'saved rows have no gaps').toBe(after + 1);
      after = row.seq;
      rows += 1;
      entries.push(...row.entries);
    }
    if (!page.has_more_after || page.rows.length === 0) break;
  }
  const text = (stream?: string) =>
    entries.filter((e) => e.stream !== 'temper' && (!stream || e.stream === stream)).map((e) => e.text).join('');
  return { entries, rows, text };
}

/** Open the run page and pick an agent in the live panel. */
async function openAgent(page: Page, runId: string, attemptId: string) {
  await page.goto(`/app/workflow/${runId}`);
  await expect(page.locator('.react-flow')).toBeVisible();
  const row = page.locator(`[data-testid="live-agent-row"][data-agent-id="${attemptId}"]`);
  await expect(row).toBeVisible();
  await row.click();
  const log = page.locator(`[data-testid="script-log"][data-attempt="${attemptId}"]`);
  await expect(log).toBeVisible();
  return log;
}

test.describe('script agent logs', () => {
  test.setTimeout(180_000);

  test('output shows while the script runs, and comes back whole after a reload', async ({ page, request }) => {
    const runId = await startRun(request, 'ci_script_log', { ticks: '12', delay: '0.7' });
    const trouble = watchForTrouble(page);
    const a = await waitForAgent(request, runId, 'talk_a');
    const b = await waitForAgent(request, runId, 'talk_b');
    expect(a.id).not.toBe(b.id);

    const log = await openAgent(page, runId, a.id);
    const lines = log.getByTestId('script-log-lines');

    // Before the script ends: a line from early on, with its time, and stderr marked as such.
    await expect(lines).toContainText('a: tick 2/12', { timeout: 15_000 });
    expect((await agentOf(request, runId, 'talk_a'))?.status, 'seen while it was still running').toBe('running');
    await expect(log).toHaveAttribute('data-status', 'live');
    await expect(log.getByTestId('script-log-status')).toHaveText(/Live/);
    const err = log.locator('[data-testid="script-log-line"][data-stream="stderr"]').first();
    await expect(err).toContainText('a: warning at tick 2');
    await expect(err).toContainText(/\d\d:\d\d:\d\d\.\d{3}/);
    await expect(err).toContainText('err');
    await expect(log.getByTestId('script-log-limit')).toContainText('limit 10 MB');
    // Its own log only: talker b runs at the same time under the same agent name.
    await expect(lines).not.toContainText('b: tick');
    await shoot(page, 'script-log-live');

    // Reload half way through: what was saved comes back, and new output keeps coming.
    await page.reload();
    const again = await openAgent(page, runId, a.id);
    const linesAgain = again.getByTestId('script-log-lines');
    await expect(linesAgain).toContainText('a: tick 1/12');
    expect((await agentOf(request, runId, 'talk_a'))?.status, 'reloaded while it was still running').toBe('running');
    await expect(linesAgain).toContainText('a: tick 12/12', { timeout: 30_000 });
    await expect(again).toHaveAttribute('data-status', 'completed', { timeout: 30_000 });
    await expect(again.getByTestId('script-log-note').last()).toContainText('finished: exit code 0');
    await shoot(page, 'script-log-after-reload');

    // Every saved line exactly once on the page: nothing missed, nothing doubled.
    const saved = await savedLog(request, runId, a.id);
    const shown = (await linesAgain.locator('[data-testid="script-log-line"]').allInnerTexts()).join('\n');
    for (let i = 1; i <= 12; i++) {
      const line = `a: tick ${i}/12`;
      expect(saved.text('stdout')).toContain(line);
      expect(shown.split(line).length - 1, `"${line}" shown once`).toBe(1);
    }
    expect(shown.split('a: warning at tick').length - 1).toBe(6);
    // The partial line, written in two pieces, is one line on the page.
    expect(shown).toContain('a: one line, printed in two pieces... and finished');

    // The hand-off is unchanged: the next step got talker a's JSON, and none of the log.
    await waitForFinish(request, runId);
    const use = await agentOf(request, runId, 'use');
    expect(JSON.stringify(use?.output ?? use?.output_data)).toContain('\\"saw\\": \\"a\\"');
    const done = await agentOf(request, runId, 'talk_a');
    expect(JSON.stringify(done?.output ?? '')).not.toContain('finished: exit code');
    expect(done?.log?.complete).toBe(true);

    // The full-screen view of the agent shows the same saved log.
    await page.getByTestId('live-details-button').click();
    const big = page.getByTestId('big-view').getByTestId('bv-script-log');
    await expect(big).toContainText('a: tick 12/12');
    await expect(big.getByTestId('script-log')).toHaveAttribute('data-status', 'completed');
    await shoot(page, 'script-log-full-screen');

    expect(trouble, 'no errors on the page').toEqual([]);
  });

  test('a failed, a timed-out and a cancelled script keep what they printed', async ({ page, request }) => {
    const trouble = watchForTrouble(page);

    // Failed: exit code 3, after printing.
    const failed = await startRun(request, 'ci_script_log', { ticks: '2', delay: '0.3', fail: '3' });
    await waitForFinish(request, failed);
    const fa = await waitForAgent(request, failed, 'talk_a');
    let log = await openAgent(page, failed, fa.id);
    await expect(log).toHaveAttribute('data-status', 'failed');
    await expect(log.getByTestId('script-log-status')).toContainText('exit code 3');
    await expect(log.locator('[data-testid="script-log-line"][data-stream="stderr"]').last())
      .toContainText('a: giving up with exit code 3');
    await expect(log.getByTestId('script-log-lines')).toContainText('a: tick 2/2');
    await shoot(page, 'script-log-failed');

    // Timed out: printed for five seconds, then stopped.
    const timedOut = await startRun(request, 'ci_script_log_timeout');
    await waitForFinish(request, timedOut);
    const st = await waitForAgent(request, timedOut, 'stuck');
    log = await openAgent(page, timedOut, st.id);
    await expect(log).toHaveAttribute('data-status', 'timed_out');
    await expect(log.getByTestId('script-log-lines')).toContainText('stuck: still going, line 3');
    await expect(log.getByTestId('script-log-note').last()).toContainText('timed out after 5s');
    const stuckSaved = await savedLog(request, timedOut, st.id);
    expect(stuckSaved.entries.at(-1)?.kind).toBe('end');
    await shoot(page, 'script-log-timed-out');

    // Cancelled while printing.
    const cancelled = await startRun(request, 'ci_script_log', { ticks: '40', delay: '0.5' });
    const ca = await waitForAgent(request, cancelled, 'talk_a');
    for (let i = 0; i < 40; i++) {
      if ((await savedLog(request, cancelled, ca.id)).text().includes('a: tick 3/40')) break;
      await new Promise((r) => setTimeout(r, 500));
    }
    expect((await request.post(`/api/runs/${cancelled}/cancel`, { data: {} })).ok()).toBeTruthy();
    await waitForFinish(request, cancelled);
    log = await openAgent(page, cancelled, ca.id);
    await expect(log).toHaveAttribute('data-status', 'cancelled', { timeout: 15_000 });
    await expect(log.getByTestId('script-log-lines')).toContainText('a: tick 3/40');
    await expect(log.getByTestId('script-log-note').last()).toContainText('cancelled');
    await shoot(page, 'script-log-cancelled');

    expect(trouble, 'no errors on the page').toEqual([]);
  });

  test('a flood of output: the limit shows, older output pages in, the page keeps up', async ({ page, request }) => {
    const runId = await startRun(request, 'ci_script_log', { ticks: '1', delay: '0.2', flood_mb: '12' });
    const trouble = watchForTrouble(page);
    const b = await waitForAgent(request, runId, 'talk_b');
    const log = await openAgent(page, runId, b.id);

    await expect(log).toHaveAttribute('data-status', 'completed', { timeout: 60_000 });
    await expect(log.getByTestId('script-log-truncated')).toContainText('Limit reached');
    await expect(log.getByTestId('script-log-limit')).toContainText('10 MB saved');
    await expect(log.getByTestId('script-log-note').last()).toContainText('not saved');
    const agent = await agentOf(request, runId, 'talk_b');
    expect(agent?.log?.saved_bytes).toBe(10_000_000);
    expect(agent?.log?.truncated).toBe(true);

    // Only a window of the log is on the page, and older output can still be read.
    const drawn = await log.locator('[data-testid="script-log-line"]').count();
    expect(drawn).toBeLessThanOrEqual(1500);
    const lines = log.getByTestId('script-log-lines');
    await lines.evaluate((el) => { el.scrollTop = 0; });
    const older = log.getByTestId('script-log-older').or(log.getByTestId('script-log-earlier'));
    await expect(older).toBeVisible();
    await older.click();
    await expect(log.locator('[data-testid="script-log-line"]').first()).toBeVisible();

    // Still responsive: the panel answers a click at once.
    const t0 = Date.now();
    await page.getByLabel('Fold the live panel').click();
    await expect(page.getByTestId('live-agent-roster')).toHaveCount(0);
    expect(Date.now() - t0).toBeLessThan(3_000);
    await page.getByLabel('Open the live panel', { exact: true }).click();
    await expect(log).toBeVisible();
    await shoot(page, 'script-log-flood');

    expect(trouble, 'no errors on the page').toEqual([]);
  });
});
