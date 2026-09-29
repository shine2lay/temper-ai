/**
 * Pictures of the live panel, taken from a made-up run.
 *
 * The page is the real build; only what feeds it is replaced — the REST
 * snapshot and the websocket both come from `liveReplay.ts`. That way the
 * panel can be photographed in states a real run reaches rarely or slowly
 * (many agents at once, a loop's second round, a failed step, a run read
 * back after it ended) without spending a cent or touching real data.
 *
 * Run it against any server that serves the dashboard:
 *
 *     TEMPER_E2E_BASE_URL=http://127.0.0.1:8420 npx playwright test e2e/liveview.spec.ts
 *
 * Each shot asserts the state it means to show before the shutter fires — a
 * picture of the wrong screen is worse than none.
 */
import { test, expect, type Page } from '@playwright/test';
import { replayRun, finishedRun, bigRun, LIVE_WORDS, LIVE_TOOLS } from './liveReplay';

const OUT = process.env.TEMPER_PROOF_DIR ?? 'e2e/proofs/live';

type Snapshot = ReturnType<typeof replayRun>;

declare global {
  interface Window {
    __replay?: { send: (msg: unknown) => void; open: boolean };
  }
}

/** Feed the page a made-up run instead of the server's. */
async function replay(page: Page, snapshot: Snapshot): Promise<void> {
  await page.route('**/api/workflows/**', async (route) => {
    const url = route.request().url();
    if (url.includes('/agents')) {
      const agents = snapshot.nodes.flatMap((n) =>
        n.agents.map((a) => ({
          id: a.id,
          agent_name: a.agent_name,
          round: a.round,
          status: a.status,
          node_id: n.id,
          node_name: n.name,
          start_time: a.start_time,
          end_time: a.end_time,
          duration_seconds: a.duration_seconds,
          prompt_tokens: a.prompt_tokens,
          completion_tokens: a.completion_tokens,
          total_tokens: a.total_tokens,
          estimated_cost_usd: a.estimated_cost_usd,
        })),
      );
      await route.fulfill({ json: { agents } });
      return;
    }
    await route.fulfill({ json: snapshot });
  });
  await page.route('**/api/runs/**', (route) => route.fulfill({ json: { gates: [], checkpoints: [] } }));

  // A websocket that says what we tell it to.
  await page.addInitScript((snap) => {
    class ReplaySocket {
      static OPEN = 1;
      readyState = 1;
      onopen: ((e: unknown) => void) | null = null;
      onmessage: ((e: { data: string }) => void) | null = null;
      onerror: ((e: unknown) => void) | null = null;
      onclose: ((e: unknown) => void) | null = null;
      constructor() {
        window.__replay = {
          open: true,
          send: (msg: unknown) => this.onmessage?.({ data: JSON.stringify(msg) }),
        };
        setTimeout(() => {
          this.onopen?.({});
          window.__replay?.send({ type: 'snapshot', workflow: snap });
        }, 0);
      }
      send() {}
      close() {
        this.readyState = 3;
        if (window.__replay) window.__replay.open = false;
      }
      addEventListener() {}
      removeEventListener() {}
    }
    (window as unknown as { WebSocket: unknown }).WebSocket = ReplaySocket;
  }, snapshot);

  await page.goto(`/app/workflow/${snapshot.id}`);
  await expect(page.getByTestId('live-panel')).toBeVisible();
}

/** Say a few words as one of the agents. */
async function say(page: Page, from: number, to: number): Promise<void> {
  const slice = LIVE_WORDS.slice(from, to);
  await page.evaluate((chunks) => {
    for (const c of chunks) {
      window.__replay?.send({
        type: 'event',
        event_type: 'llm_stream_batch',
        agent_id: c.agentId,
        timestamp: new Date().toISOString(),
        data: {
          chunks: [{ agent_id: c.agentId, content: c.content, chunk_type: c.kind, call_id: c.callId }],
        },
      });
    }
  }, slice);
}

/** Start a tool step, and optionally end it. */
async function runTool(page: Page, index: number, finish?: 'ok' | 'fail'): Promise<void> {
  const tool = LIVE_TOOLS[index];
  await page.evaluate(({ tool, finish }) => {
    const base = { agent_id: tool.agentId, tool_name: tool.name };
    window.__replay?.send({
      type: 'event',
      event_type: 'tool.call.started',
      agent_id: tool.agentId,
      timestamp: new Date().toISOString(),
      data: { ...base, event_id: tool.toolId, input_params: tool.args },
    });
    if (finish) {
      window.__replay?.send({
        type: 'event',
        event_type: finish === 'ok' ? 'tool.call.completed' : 'tool.call.failed',
        agent_id: tool.agentId,
        timestamp: new Date().toISOString(),
        data: {
          ...base,
          tool_execution_id: tool.toolId,
          status: finish === 'ok' ? 'success' : 'error',
          duration_seconds: tool.seconds,
          output_data: finish === 'ok' ? { passed: 412, failed: 0 } : undefined,
          error_message: finish === 'fail' ? 'exit code 1' : undefined,
        },
      });
    }
  }, { tool, finish });
}

test.describe('the live panel', () => {
  test('several agents at work, at the size it opens at', async ({ page }) => {
    await replay(page, replayRun());

    // Thinking as it arrives: the newest is open and unfolded.
    await say(page, 0, 14);
    await expect(page.getByTestId('agent-story')).toContainText('hard-codes');
    await page.screenshot({ path: `${OUT}/panel-thinking-live.png` });

    await say(page, 14, 40);
    await runTool(page, 0);

    await expect(page.getByTestId('live-now-line')).toContainText('coder');
    await expect(page.getByTestId('agent-story')).toContainText('cache key');
    await page.screenshot({ path: `${OUT}/panel-default.png` });

    // The story of a step, opened: what it was given and what came back.
    await runTool(page, 0, 'ok');
    await page.getByTestId('story-tool').last().getByRole('button').first().click();
    await expect(page.getByTestId('story-tool').last()).toContainText('passed');
    await page.screenshot({ path: `${OUT}/panel-step-open.png` });
  });

  test('dragged to full height, and folded to a bar', async ({ page }) => {
    await replay(page, replayRun());
    await say(page, 0, 60);

    const handle = page.getByTestId('live-panel-handle');
    const box = (await handle.boundingBox())!;
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2, 60, { steps: 12 });
    await page.mouse.up();
    await expect(page.getByTestId('agent-story')).toBeVisible();
    await page.screenshot({ path: `${OUT}/panel-tall.png` });

    await page.getByLabel('Fold the live panel').click();
    await expect(page.getByTestId('live-agent-roster')).toHaveCount(0);
    await expect(page.getByTestId('live-now-line')).toBeVisible();
    await page.screenshot({ path: `${OUT}/panel-folded.png` });
  });

  test('a crowded run: the list scrolls and finished stages fold', async ({ page }) => {
    await replay(page, bigRun());
    await expect(page.getByTestId('live-agent-row').first()).toBeVisible();
    const rows = await page.getByTestId('live-agent-row').count();
    expect(rows).toBeGreaterThan(20);
    await page.screenshot({ path: `${OUT}/panel-many-agents.png` });
  });

  test('a step that failed', async ({ page }) => {
    await replay(page, replayRun());
    await page.getByTestId('live-agent-row').filter({ hasText: 'packager' }).click();
    await expect(page.getByTestId('agent-story')).toContainText('could not run');
    await page.getByTestId('story-tool').first().getByRole('button').first().click();
    await expect(page.getByTestId('story-tool').first()).toContainText('missing script');
    await page.screenshot({ path: `${OUT}/panel-failed-step.png` });
  });

  test('a run that is over, read back', async ({ page }) => {
    await replay(page, finishedRun());
    await page.getByTestId('live-agent-row').filter({ hasText: 'architect' }).first().click();
    await expect(page.getByTestId('agent-story')).toContainText('failing job is the release build');
    await page.screenshot({ path: `${OUT}/panel-finished-run.png` });
  });
});
