import { test, expect, type APIRequestContext, type Page } from '@playwright/test';
import { waitForFinish } from './helpers';
import { replayInto, replayRun, RUN_ID } from './liveReplay';

/**
 * Each approval answers the wait it was meant for, and a loop that runs out of
 * rounds fails, on the zero-cost `ci_gate_rounds` workflow: `review` waits for
 * an approval every round and always asks for another, so its second round is
 * its last and the run fails with "ran out of rounds: 2 of 2".
 *
 * Pass or fail comes from the API's answers and the stored run; the
 * screenshots (kept when TEMPER_PROOF_DIR is set) are for people.
 *
 * The same file is the live check after a deploy:
 *   TEMPER_E2E_BASE_URL=http://127.0.0.1:8420 TEMPER_PROOF_DIR=... npx playwright test gateRounds
 */
const OUT = process.env.TEMPER_PROOF_DIR ?? 'test-results/gate-rounds';

interface Gate {
  event_id: string;
  node_name: string;
  path?: string;
  round?: number;
}

async function gates(request: APIRequestContext, id: string): Promise<Gate[]> {
  const res = await request.get(`/api/runs/${id}/gates`);
  return res.ok() ? ((await res.json()).gates ?? []) : [];
}

/** Wait until the run waits at `review` in round `round`, and return that wait. */
async function waitingRound(request: APIRequestContext, id: string, round: number): Promise<Gate> {
  for (let i = 0; i < 60; i++) {
    const open = (await gates(request, id)).filter((g) => g.node_name === 'review');
    const mine = open.find((g) => (g.round ?? 1) === round);
    if (mine) return mine;
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`run ${id} never waited at review round ${round}: ${JSON.stringify(await gates(request, id))}`);
}

async function start(request: APIRequestContext, inputs: Record<string, string> = {}): Promise<string> {
  const res = await request.post('/api/runs', { data: { workflow: 'ci_gate_rounds', inputs } });
  expect(res.ok(), await res.text()).toBeTruthy();
  return (await res.json()).execution_id as string;
}

function approve(request: APIRequestContext, id: string, body: Record<string, unknown>) {
  return request.post(`/api/runs/${id}/approve/review`, { data: body });
}

function reviewNode(run: Record<string, unknown>) {
  const nodes = (run.nodes ?? []) as { name: string; status: string; error_message?: string | null }[];
  return nodes.find((n) => n.name === 'review');
}

async function shot(page: Page, name: string): Promise<void> {
  await page.screenshot({ path: `${OUT}/${name}.png` });
}

test.describe('approvals answer their own round', () => {
  test.describe.configure({ timeout: 120_000 });

  test('stale, simultaneous and repeated approvals; then the loop runs out and stays red', async ({
    page,
    request,
  }) => {
    const id = await start(request);
    const round1 = await waitingRound(request, id, 1);

    // The same click arriving twice decides once.
    const first = await approve(request, id, { event_id: round1.event_id, request_id: `e2e-${id}-1` });
    expect(first.status()).toBe(200);
    const again = await approve(request, id, { event_id: round1.event_id, request_id: `e2e-${id}-1` });
    expect(again.status()).toBe(200);
    expect((await again.json()).repeated).toBe(true);

    const round2 = await waitingRound(request, id, 2);
    expect(round2.event_id).not.toBe(round1.event_id);

    // A stale tab still showing round 1: refused, round 2 untouched.
    const stale = await approve(request, id, { event_id: round1.event_id, request_id: `e2e-${id}-stale` });
    expect(stale.status()).toBe(409);
    expect((await stale.json()).detail.reason).toBe('already_answered');
    expect((await gates(request, id)).map((g) => g.event_id)).toContain(round2.event_id);

    // Two approvals of round 2 at the same moment: one wins, the other is told who did.
    await page.goto(`/app/workflow/${id}`);
    await expect(page.getByRole('dialog')).toBeVisible();
    await shot(page, '1-round-2-waiting');
    const [a, b] = await Promise.all([
      approve(request, id, { event_id: round2.event_id, request_id: `e2e-${id}-a`, by: 'tab A' }),
      approve(request, id, { event_id: round2.event_id, request_id: `e2e-${id}-b`, by: 'tab B' }),
    ]);
    expect([a.status(), b.status()].sort()).toEqual([200, 409]);
    const loser = (a.status() === 409 ? await a.json() : await b.json()).detail;
    expect(loser.reason).toBe('already_answered');
    expect(['tab A', 'tab B']).toContain(loser.answered_by);
    expect(loser.message).toContain('Already answered by');

    // Round 2 still asked for another round: none left, so the step and the run fail.
    const over = await waitForFinish(request, id);
    expect(over.status).toBe('failed');
    expect(reviewNode(over)?.status).toBe('failed');
    expect(reviewNode(over)?.error_message).toContain('ran out of rounds: 2 of 2');

    await page.reload();
    const card = page.locator('[data-testid="agent-card"][data-name="review"]');
    await expect(card).toHaveAttribute('data-status', 'failed');
    await expect(card).toContainText('ran out of rounds: 2 of 2');
    await shot(page, '2-ran-out-red');

    // Resume runs review again with its count kept: it asks once more and fails the same way.
    const resumed = await request.post(`/api/runs/${id}/resume`, { data: { workflow: 'ci_gate_rounds' } });
    expect(resumed.ok(), await resumed.text()).toBeTruthy();
    const round3 = await waitingRound(request, id, 3);
    expect((await approve(request, id, { event_id: round3.event_id, request_id: `e2e-${id}-3` })).status()).toBe(200);
    const after = await waitForFinish(request, id);
    expect(after.status).toBe('failed');
    expect(reviewNode(after)?.error_message).toContain('ran out of rounds');
    const ship = ((after.nodes ?? []) as { name: string; status: string }[]).find((n) => n.name === 'ship');
    expect(ship?.status).not.toBe('completed');
  });

  test('a stale tab approving says plainly that it was already answered', async ({ page, request }) => {
    const id = await start(request);
    const round1 = await waitingRound(request, id, 1);

    // This tab saw round 1 and then stopped hearing about the run.
    let frozen: string | null = null;
    await page.route(`**/api/runs/${id}/gates`, async (route) => {
      if (frozen) {
        await route.fulfill({ status: 200, contentType: 'application/json', body: frozen });
        return;
      }
      const res = await route.fetch();
      frozen = await res.text();
      await route.fulfill({ response: res, body: frozen });
    });
    await page.goto(`/app/workflow/${id}`);
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();

    // Someone else approves round 1 (another tab, Slack, ...), and round 2 starts waiting.
    expect((await approve(request, id, { event_id: round1.event_id, by: 'someone else' })).status()).toBe(200);
    await waitingRound(request, id, 2);

    await dialog.getByRole('button', { name: /Approve & continue/ }).click();
    await expect(page.getByText(/Already answered by someone else/)).toBeVisible();
    await shot(page, '3-stale-tab-refused');

    // Round 2 is still waiting: the stale click did not answer it.
    expect((await gates(request, id)).some((g) => (g.round ?? 1) === 2)).toBe(true);
    await request.post(`/api/runs/${id}/cancel`);
  });

  test('one approval and the loop is happy: it ships', async ({ request }) => {
    const id = await start(request, { verdict: 'done' });
    const round1 = await waitingRound(request, id, 1);
    // By step name alone, as EPD's approve_pr.py and the CI smoke do: one waits, so it is that one.
    expect((await request.post(`/api/runs/${id}/approve/review`)).status()).toBe(200);
    const done = await waitForFinish(request, id);
    expect(done.status).toBe('completed');
    expect(round1.event_id).toBeTruthy();
  });
});

test.describe('the run page, west of UTC', () => {
  test.use({ timezoneId: 'America/Los_Angeles' });

  /** Stored times come back without a zone (they are UTC), as the server sends them. */
  function storedWithoutZone(run: ReturnType<typeof replayRun>) {
    return JSON.parse(JSON.stringify(run).replace(/(\d{2}:\d{2}:\d{2}\.\d{3})Z"/g, '$1"'));
  }

  test('keeps stored items before live ones, and a failed tool shows its error live', async ({ page }) => {
    await replayInto(page, storedWithoutZone(replayRun()));
    await page.getByTestId('live-agent-row').filter({ hasText: 'coder' }).click();
    const story = page.getByTestId('agent-story');
    await expect(story.getByTestId('story-tool')).toHaveCount(2);

    // A tool heard live now, which then fails, as tool events say it: `error`, `duration_ms`.
    await page.evaluate((run) => {
      const base = { agent_id: 'ag-build-1', tool_name: 'Bash', tool_execution_id: 'live-bash-1' };
      const now = new Date().toISOString();
      window.__replay?.send({
        type: 'event', event_type: 'tool.call.started', agent_id: 'ag-build-1', timestamp: now,
        execution_id: run, data: { ...base, event_id: 'live-bash-1', input_params: { command: 'make release' } },
      });
      window.__replay?.send({
        type: 'event', event_type: 'tool.call.failed', agent_id: 'ag-build-1', timestamp: now,
        execution_id: run,
        data: { ...base, status: 'failed', error: 'exit status 2: no rule to make target', duration_ms: 1500 },
      });
    }, RUN_ID);

    const steps = story.getByTestId('story-tool');
    await expect(steps).toHaveCount(3);
    // What happened before the page opened comes first, not seven hours late.
    await expect(steps.nth(0)).toContainText('release.sh');
    await expect(steps.nth(2)).toContainText('make release');
    await expect(steps.nth(2)).toContainText('1.5s');
    await steps.nth(2).getByRole('button').first().click();
    await expect(steps.nth(2)).toContainText('no rule to make target');
    await shot(page, '4-failed-tool-live-west-of-utc');
  });
});
