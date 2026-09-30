/**
 * Clicking a node of a real run has to open its details — every node, not
 * only the ones at the top level.
 *
 * What broke: the store filled its stage map from the drawn graph, which
 * keeps a node's children inside it, so a stage sitting inside another stage
 * was never a key of that map and its panel read "Stage not found". On a real
 * `epd_propose` run that was all six `pitch_*` stages; on a `github_work` run
 * it was the `environment` stage inside `build`. Unit tests cover the lookup;
 * only a click on the real page proves the graph, the store and the panel
 * agree about a node's id.
 *
 * So this clicks every node the graph draws and reads the panel that opens.
 * It runs against a real server with the built dashboard:
 *
 *   npm run build && TEMPER_E2E_BASE_URL=http://localhost:8420 \
 *     npx playwright test e2e/nestedStages.spec.ts
 *
 * The data is its own: the zero-cost `ci_nested` workflow (script agents, no
 * API key, no spend) has the same shape — a stage inside a stage.
 */
import { expect, test } from '@playwright/test';

import { startNestedRun } from './helpers';

/** Open a finished run's page and wait for its graph to be drawn. */
async function openRun(page: import('@playwright/test').Page, id: string) {
  await page.goto(`/app/workflow/${id}`);
  await expect(page.locator('.react-flow__node').first()).toBeVisible();
  // Nodes arrive in one layout pass; give the last of them a moment to land.
  await expect
    .poll(async () => page.locator('.react-flow__node').count(), { timeout: 15_000 })
    .toBeGreaterThan(4);
}

test.describe('a stage inside a stage', () => {
  test('every node of the graph opens a details panel', async ({ page, request }) => {
    const id = await startNestedRun(request);
    await openRun(page, id);

    const nodes = page.locator('.react-flow__node');
    const ids = await nodes.evaluateAll((els) =>
      els.map((el) => el.getAttribute('data-id')).filter((v): v is string => !!v),
    );
    // begin, outer, inner, deep_one, deep_two, after_inner, finish.
    expect(ids.length).toBeGreaterThanOrEqual(7);

    const notFound: string[] = [];
    for (const nodeId of ids) {
      await page.keyboard.press('Escape');
      const node = page.locator(`.react-flow__node[data-id="${nodeId}"]`);
      // Click the node's own corner: a group node's middle belongs to a child.
      await node.click({ position: { x: 12, y: 12 }, force: true });

      const panel = page.getByRole('dialog');
      await expect(panel).toBeVisible();
      const text = (await panel.textContent()) ?? '';
      if (/not found/i.test(text)) notFound.push(`${nodeId}: ${text.slice(0, 80)}`);
    }

    expect(notFound, 'nodes whose panel said "not found"').toEqual([]);
  });

  test('the inner stage shows its own details', async ({ page, request }) => {
    const id = await startNestedRun(request);
    await openRun(page, id);

    // `inner` sits inside `outer`; the graph draws it as a group of its own.
    await page.locator('.react-flow__node', { hasText: 'inner' }).last().click({
      position: { x: 12, y: 12 },
      force: true,
    });

    const panel = page.getByRole('dialog');
    await expect(panel).toBeVisible();
    await expect(panel).not.toContainText(/not found/i);
    await expect(panel.getByRole('heading', { name: 'inner' })).toBeVisible();
    // Its agents, and a duration that actually came from the node.
    await expect(panel).toContainText('deep_one');
    await expect(panel).toContainText(/\d+\.\d+s/);
  });

  test('an agent inside the inner stage links back to a stage that opens', async ({
    page,
    request,
  }) => {
    const id = await startNestedRun(request);
    await openRun(page, id);

    await page.locator('.react-flow__node', { hasText: 'deep_two' }).last().click({ force: true });
    const panel = page.getByRole('dialog');
    await expect(panel).toBeVisible();

    await panel.getByRole('button', { name: /Back to Stage/i }).click();

    await expect(panel).toBeVisible();
    await expect(panel).not.toContainText(/not found/i);
    await expect(panel).toContainText('Stage Details');
  });

  test('the header counts stay top-level', async ({ page, request }) => {
    const id = await startNestedRun(request);
    await openRun(page, id);

    // begin, outer, finish — the stage inside `outer` and its agents are not
    // stages of the run, and adding them to the map would have inflated this.
    await expect(page.getByText('Stages').locator('..')).toContainText('3/3');
  });
});
