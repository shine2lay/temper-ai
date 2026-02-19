/**
 * E2E tests for the Temper AI React frontend.
 * Requires `temper-ai serve --port 8421` running with at least one completed workflow.
 * Runs against the real built React app served by FastAPI.
 */
import { test, expect } from '@playwright/test';

const BASE = 'http://localhost:8421';

// ---------------------------------------------------------------------------
// 1. Workflow List Page
// ---------------------------------------------------------------------------

test.describe('Workflow List Page', () => {
  test('loads and displays workflow list from /api/workflows', async ({ page }) => {
    await page.goto(`${BASE}/app/`);

    // Should show the header
    await expect(page.getByText('Temper AI Workflows')).toBeVisible();

    // Wait for the workflow list to load (API call)
    const firstWorkflow = page.locator('a[href*="/workflow/"]').first();
    await expect(firstWorkflow).toBeVisible({ timeout: 10_000 });

    // Should show workflow names and status badges
    await expect(page.getByText('quick_decision_demo').first()).toBeVisible();
    await expect(page.getByText('completed').first()).toBeVisible();
  });

  test('workflow list items are clickable links to execution view', async ({ page }) => {
    await page.goto(`${BASE}/app/`);

    const firstLink = page.locator('a[href*="/workflow/"]').first();
    await expect(firstLink).toBeVisible({ timeout: 10_000 });

    // Get the href to verify navigation
    const href = await firstLink.getAttribute('href');
    expect(href).toMatch(/\/workflow\/wf-/);
  });
});

// ---------------------------------------------------------------------------
// 2. Execution View — Completed Workflow (via REST)
// ---------------------------------------------------------------------------

test.describe('Execution View — Completed Workflow', () => {
  let workflowId: string;

  test.beforeAll(async ({ request }) => {
    // Find a completed workflow via the API
    const res = await request.get(`${BASE}/api/workflows`);
    const workflows = await res.json();
    const completed = workflows.find(
      (w: { status: string }) => w.status === 'completed',
    );
    expect(completed).toBeDefined();
    workflowId = completed.id;
  });

  test('loads workflow header with name, status, and duration', async ({ page }) => {
    await page.goto(`${BASE}/app/workflow/${workflowId}`);

    // Wait for the workflow name to appear (loaded via REST or WS snapshot)
    await expect(page.getByText('quick_decision_demo')).toBeVisible({
      timeout: 15_000,
    });

    // Status badge should show "completed"
    await expect(page.getByText('completed').first()).toBeVisible();

    // Duration should be displayed (format: Xs or Xm Xs)
    await expect(page.locator('header span.font-mono')).toBeVisible();
  });

  test('renders DAG with stage node containing agent cards', async ({ page }) => {
    await page.goto(`${BASE}/app/workflow/${workflowId}`);

    // Wait for workflow data to load
    await expect(page.getByText('quick_decision_demo')).toBeVisible({
      timeout: 15_000,
    });

    // Stage name should appear in the DAG (use locator that excludes the header h1)
    const stageLabel = page.locator('.react-flow span', { hasText: 'decision' }).first();
    await expect(stageLabel).toBeVisible({ timeout: 10_000 });

    // Agent names should appear inside the stage node
    await expect(page.getByText('optimist').first()).toBeVisible();
    await expect(page.getByText('skeptic').first()).toBeVisible();
    await expect(page.getByText('pragmatist').first()).toBeVisible();
  });

  test('shows WebSocket connection indicator', async ({ page }) => {
    await page.goto(`${BASE}/app/workflow/${workflowId}`);

    await expect(page.getByText('quick_decision_demo')).toBeVisible({
      timeout: 15_000,
    });

    // WS indicator should show Connected (WS sends snapshot on connect)
    await expect(page.getByText('Connected')).toBeVisible({ timeout: 10_000 });
  });

  test('can switch to Event Log tab', async ({ page }) => {
    await page.goto(`${BASE}/app/workflow/${workflowId}`);

    await expect(page.getByText('quick_decision_demo')).toBeVisible({
      timeout: 15_000,
    });

    // Click the Event Log tab
    const eventLogTab = page.getByRole('tab', { name: /event log/i });
    if (await eventLogTab.isVisible()) {
      await eventLogTab.click();
    }
  });
});

// ---------------------------------------------------------------------------
// 3. Navigation — List → Execution View → Detail Panel
// ---------------------------------------------------------------------------

test.describe('Navigation Flow', () => {
  test('navigate from list to execution view by clicking workflow', async ({
    page,
  }) => {
    await page.goto(`${BASE}/app/`);

    // Wait for list to load
    const firstLink = page.locator('a[href*="/workflow/"]').first();
    await expect(firstLink).toBeVisible({ timeout: 10_000 });

    // Click the first workflow
    await firstLink.click();

    // Should navigate to execution view — wait for header (use heading role to avoid list items)
    await expect(
      page.getByRole('heading', { name: 'quick_decision_demo' }),
    ).toBeVisible({ timeout: 15_000 });

    // URL should contain /workflow/wf-
    expect(page.url()).toContain('/workflow/wf-');

    // DAG should render with stage node (use React Flow area to avoid header match)
    const stageLabel = page.locator('.react-flow span', { hasText: 'decision' }).first();
    await expect(stageLabel).toBeVisible({ timeout: 10_000 });
  });
});

// ---------------------------------------------------------------------------
// 4. Live Workflow — Trigger and watch via WebSocket
// ---------------------------------------------------------------------------

test.describe('Live Workflow via WebSocket', () => {
  test('trigger workflow and observe live updates', async ({ page, request }) => {
    // Record existing workflow IDs before triggering
    const beforeRes = await request.get(`${BASE}/api/workflows`);
    const beforeWorkflows = await beforeRes.json();
    const existingIds = new Set(
      beforeWorkflows.map((w: { id: string }) => w.id),
    );

    // Trigger a new workflow via the API
    const triggerRes = await request.post(`${BASE}/api/runs`, {
      data: { workflow: 'workflows/quick_decision_demo.yaml' },
    });
    expect(triggerRes.ok()).toBe(true);
    const runData = await triggerRes.json();
    expect(runData.execution_id).toBeTruthy();

    // Poll for the new workflow ID (one that wasn't in existingIds)
    let wfId: string | null = null;
    for (let attempt = 0; attempt < 30; attempt++) {
      const wfRes = await request.get(`${BASE}/api/workflows`);
      const workflows = await wfRes.json();
      const newWf = workflows.find(
        (w: { id: string }) => !existingIds.has(w.id),
      );
      if (newWf) {
        wfId = newWf.id;
        break;
      }
      await new Promise((r) => setTimeout(r, 500));
    }

    expect(wfId).toBeTruthy();

    // Navigate to the execution view
    await page.goto(`${BASE}/app/workflow/${wfId}`);

    // Wait for the workflow name to appear (via REST or WS snapshot)
    await expect(
      page.getByRole('heading', { name: 'quick_decision_demo' }),
    ).toBeVisible({ timeout: 20_000 });

    // Should show the stage "decision" in the DAG
    const stageLabel = page.locator('.react-flow span', { hasText: 'decision' }).first();
    await expect(stageLabel).toBeVisible({ timeout: 10_000 });

    // Wait for the workflow to complete (status badge should eventually show "completed")
    await expect(page.getByText('completed').first()).toBeVisible({
      timeout: 60_000,
    });

    // After completion, agents should all be visible
    await expect(page.getByText('optimist').first()).toBeVisible();
    await expect(page.getByText('skeptic').first()).toBeVisible();
    await expect(page.getByText('pragmatist').first()).toBeVisible();

    // WebSocket connection should be active
    await expect(page.getByText('Connected')).toBeVisible();
  });
});
