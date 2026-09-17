/**
 * Capture the UI states that serve as visual evidence.
 *
 * Screenshots go stale the moment a UI fix ships. During the audit this cost
 * real time four separate times: a proof showed a bug that had already been
 * fixed, and disproving it took longer than the original fix. Bulk
 * re-captures do not settle it either — one proof went stale twice in a day.
 *
 * So capture is a test. Run it after a UI change and the evidence moves with
 * the code:
 *
 *     TEMPER_E2E_BASE_URL=http://127.0.0.1:8420 npx playwright test e2e/proofs.spec.ts
 *
 * These assert only that the state was reached before the shutter — a
 * screenshot of the wrong screen is worse than none. Behaviour is covered by
 * dashboard.spec.ts.
 */
import { test, expect } from '@playwright/test';
import { startSmokeRun } from './helpers';

const OUT = process.env.TEMPER_PROOF_DIR ?? 'e2e/proofs';

test.describe('proofs', () => {
  test('list, library and studio', async ({ page }) => {
    await page.goto('/app');
    await expect(page.getByRole('heading', { name: 'Workflows' })).toBeVisible();
    await page.screenshot({ path: `${OUT}/list.png`, fullPage: false });

    await page.goto('/app/library');
    await expect(page.getByText('My Library')).toBeVisible();
    await page.screenshot({ path: `${OUT}/library.png` });

    await page.goto('/app/studio');
    await page.waitForLoadState('networkidle');
    await page.screenshot({ path: `${OUT}/studio.png` });
  });

  test('a run, each of its tabs, and an agent panel', async ({ page }) => {
    // Capture a run this suite created, so the proof shows a known shape
    // rather than whatever happened to be at the top of the list.
    const id = await startSmokeRun(page.request);

    await page.goto(`/app/workflow/${id}`);
    await expect(page.locator('.react-flow__node').first()).toBeVisible();
    await page.screenshot({ path: `${OUT}/run-dag.png` });

    for (const tab of ['Timeline', 'Event Log', 'LLM Calls', 'Checkpoints']) {
      await page.getByRole('tab', { name: tab }).click();
      // The panel must actually be the one named before the shutter fires.
      await expect(page.getByRole('tab', { name: tab })).toHaveAttribute('data-state', 'active');
      await page.screenshot({ path: `${OUT}/run-tab-${tab.replace(/\s+/g, '_')}.png` });
    }

    await page.getByRole('tab', { name: 'DAG' }).click();
    await page.locator('.react-flow__node').first().click({ position: { x: 40, y: 12 } });
    await page.screenshot({ path: `${OUT}/run-panel.png` });
  });

  test('states that are easy to get wrong', async ({ page }) => {
    await page.goto('/app/workflow/does-not-exist');
    await expect(page.getByText('Run not found')).toBeVisible();
    await page.screenshot({ path: `${OUT}/run-not-found.png` });

    await page.goto('/app?status=failed');
    await expect(page).toHaveURL(/status=failed/);
    await page.screenshot({ path: `${OUT}/list-filtered.png` });

    // Narrow: where Save/Run and New Run were once clipped out of reach.
    await page.setViewportSize({ width: 640, height: 900 });
    await page.goto('/app');
    // Two proxies failed here before this line was right. toBeVisible() is
    // true for an element pushed off the right edge, and bare
    // toBeInViewport() passes on *any* intersection — it accepted a button
    // spanning 636-703px in a 640px viewport because 4px poked in. The bug
    // is a control placed out of reach, so require the whole of it.
    await expect(page.getByRole('button', { name: /New Run/ })).toBeInViewport({ ratio: 1 });
    await page.screenshot({ path: `${OUT}/list-640.png` });

    await page.goto('/app/studio');
    await page.waitForLoadState('networkidle');
    for (const name of ['Save', 'Run']) {
      await expect(page.getByRole('button', { name, exact: true })).toBeInViewport({ ratio: 1 });
    }
    await page.screenshot({ path: `${OUT}/studio-640.png` });
  });
});
