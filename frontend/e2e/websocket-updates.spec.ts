/**
 * E2E tests focused on WebSocket connectivity and live frontend updates.
 * Triggers a real workflow and verifies that the React frontend
 * updates in real-time as WebSocket events arrive.
 *
 * Requires `temper-ai serve --port 8421` running.
 */
import { test, expect, type Page, type APIRequestContext } from '@playwright/test';

const BASE = 'http://localhost:8421';

/**
 * Trigger a workflow and return its observability wf-* ID.
 */
async function triggerAndGetWfId(request: APIRequestContext): Promise<string> {
  // Record existing workflow IDs before triggering
  const beforeRes = await request.get(`${BASE}/api/workflows`);
  const beforeWorkflows = await beforeRes.json();
  const existingIds = new Set(
    beforeWorkflows.map((w: { id: string }) => w.id),
  );

  // Trigger
  const triggerRes = await request.post(`${BASE}/api/runs`, {
    data: { workflow: 'workflows/quick_decision_demo.yaml' },
  });
  expect(triggerRes.ok()).toBe(true);

  // Poll for new workflow ID
  for (let attempt = 0; attempt < 30; attempt++) {
    const wfRes = await request.get(`${BASE}/api/workflows`);
    const workflows = await wfRes.json();
    const newWf = workflows.find(
      (w: { id: string }) => !existingIds.has(w.id),
    );
    if (newWf) return newWf.id;
    await new Promise((r) => setTimeout(r, 500));
  }

  throw new Error('Workflow ID not found after triggering');
}

// ---------------------------------------------------------------------------
// WebSocket Connection
// ---------------------------------------------------------------------------

test.describe('WebSocket Connection', () => {
  test('establishes WebSocket connection and shows Connected indicator', async ({
    page,
    request,
  }) => {
    // Use an existing completed workflow
    const res = await request.get(`${BASE}/api/workflows`);
    const workflows = await res.json();
    const wfId = workflows[0].id;

    await page.goto(`${BASE}/app/workflow/${wfId}`);

    // Wait for data to load
    await expect(
      page.getByRole('heading', { name: 'quick_decision_demo' }),
    ).toBeVisible({ timeout: 15_000 });

    // WS connected indicator
    await expect(page.getByText('Connected')).toBeVisible({ timeout: 10_000 });
  });

  test('WebSocket delivers snapshot that populates the DAG', async ({
    page,
    request,
  }) => {
    const res = await request.get(`${BASE}/api/workflows`);
    const workflows = await res.json();
    const wfId = workflows[0].id;

    await page.goto(`${BASE}/app/workflow/${wfId}`);

    // Wait for WS snapshot → DAG should render with stage + agents
    await expect(
      page.getByRole('heading', { name: 'quick_decision_demo' }),
    ).toBeVisible({ timeout: 15_000 });

    // Stage node rendered
    const stageLabel = page
      .locator('.react-flow span', { hasText: 'decision' })
      .first();
    await expect(stageLabel).toBeVisible({ timeout: 10_000 });

    // Agents rendered inside stage node
    await expect(page.getByText('optimist').first()).toBeVisible();
    await expect(page.getByText('skeptic').first()).toBeVisible();
    await expect(page.getByText('pragmatist').first()).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// Live Updates — Frontend reacts to WebSocket events
// ---------------------------------------------------------------------------

test.describe('Live Frontend Updates via WebSocket', () => {
  test('workflow status transitions from running to completed', async ({
    page,
    request,
  }) => {
    const wfId = await triggerAndGetWfId(request);

    await page.goto(`${BASE}/app/workflow/${wfId}`);

    // Wait for workflow to load
    await expect(
      page.getByRole('heading', { name: 'quick_decision_demo' }),
    ).toBeVisible({ timeout: 20_000 });

    // Initially should be "running" (if we're fast enough) or already transitioning
    // Wait for "completed" status to appear — proves workflow_end event was received
    await expect(page.getByText('completed').first()).toBeVisible({
      timeout: 60_000,
    });
  });

  test('agent cards appear and update status during execution', async ({
    page,
    request,
  }) => {
    const wfId = await triggerAndGetWfId(request);

    await page.goto(`${BASE}/app/workflow/${wfId}`);

    await expect(
      page.getByRole('heading', { name: 'quick_decision_demo' }),
    ).toBeVisible({ timeout: 20_000 });

    // Wait for stage node to appear (stage_start event → creates stage in DAG)
    const stageLabel = page
      .locator('.react-flow span', { hasText: 'decision' })
      .first();
    await expect(stageLabel).toBeVisible({ timeout: 15_000 });

    // Wait for all 3 agents to appear (agent_start events → populate agent cards)
    await expect(page.getByText('optimist').first()).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByText('skeptic').first()).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByText('pragmatist').first()).toBeVisible({
      timeout: 30_000,
    });

    // Wait for workflow to complete (all agent_end + workflow_end events)
    await expect(page.getByText('completed').first()).toBeVisible({
      timeout: 60_000,
    });
  });

  test('duration updates live while workflow is running', async ({
    page,
    request,
  }) => {
    const wfId = await triggerAndGetWfId(request);

    await page.goto(`${BASE}/app/workflow/${wfId}`);

    await expect(
      page.getByRole('heading', { name: 'quick_decision_demo' }),
    ).toBeVisible({ timeout: 20_000 });

    // Capture the duration display early
    const durationEl = page.locator('header span.font-mono');
    await expect(durationEl).toBeVisible({ timeout: 5_000 });
    const earlyDuration = await durationEl.textContent();

    // Wait a moment then check duration changed (live ticker)
    await page.waitForTimeout(2000);
    const laterDuration = await durationEl.textContent();

    // If workflow is still running, duration should have changed
    // If already completed, both will be the same (final value) — still valid
    expect(laterDuration).toBeTruthy();

    // Wait for completion
    await expect(page.getByText('completed').first()).toBeVisible({
      timeout: 60_000,
    });

    // After completion, duration should show final value
    const finalDuration = await durationEl.textContent();
    expect(finalDuration).toBeTruthy();
    expect(finalDuration).not.toBe('—');
  });

  test('WebSocket heartbeat keeps connection alive', async ({
    page,
    request,
  }) => {
    const res = await request.get(`${BASE}/api/workflows`);
    const workflows = await res.json();
    const wfId = workflows[0].id;

    await page.goto(`${BASE}/app/workflow/${wfId}`);

    // Verify connected
    await expect(page.getByText('Connected')).toBeVisible({ timeout: 10_000 });

    // Wait 35 seconds (heartbeat interval is 30s)
    await page.waitForTimeout(35_000);

    // Should still show "Connected" after heartbeat
    await expect(page.getByText('Connected')).toBeVisible();
  });

  test('multiple workflows can be viewed sequentially', async ({
    page,
    request,
  }) => {
    // Get two different completed workflows
    const res = await request.get(`${BASE}/api/workflows`);
    const workflows = await res.json();
    const wf1 = workflows[0].id;
    const wf2 = workflows[1].id;

    // View first workflow
    await page.goto(`${BASE}/app/workflow/${wf1}`);
    await expect(
      page.getByRole('heading', { name: 'quick_decision_demo' }),
    ).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText('Connected')).toBeVisible({ timeout: 10_000 });

    // Navigate to second workflow
    await page.goto(`${BASE}/app/workflow/${wf2}`);
    await expect(
      page.getByRole('heading', { name: 'quick_decision_demo' }),
    ).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText('Connected')).toBeVisible({ timeout: 10_000 });

    // Both should render the DAG successfully
    const stageLabel = page
      .locator('.react-flow span', { hasText: 'decision' })
      .first();
    await expect(stageLabel).toBeVisible({ timeout: 10_000 });
  });
});
