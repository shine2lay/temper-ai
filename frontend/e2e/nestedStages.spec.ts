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
import type { APIRequestContext, Page } from '@playwright/test';

import { startNestedRun } from './helpers';

type Node = { id: string; name: string; child_nodes?: Node[] };

/**
 * The run's nodes by name, nested ones included.
 *
 * Picking a node by its text picks the group it sits in just as easily, so
 * the clicks below go by id, the same id the graph puts in `data-id`.
 */
async function nodeIds(
  request: APIRequestContext,
  runId: string,
): Promise<Record<string, string>> {
  const res = await request.get(`/api/workflows/${runId}`);
  expect(res.ok(), `run ${runId} could not be read`).toBe(true);
  const byName: Record<string, string> = {};
  const walk = (nodes: Node[] | undefined) => {
    for (const n of nodes ?? []) {
      byName[n.name] = n.id;
      walk(n.child_nodes);
    }
  };
  walk((await res.json()).nodes);
  return byName;
}

/** Click a node the way a person does: on its own corner, not on a child. */
async function clickNode(page: Page, id: string) {
  await page.keyboard.press('Escape');
  await page
    .locator(`.react-flow__node[data-id="${id}"]`)
    .click({ position: { x: 12, y: 12 }, force: true });
}

/** Open a finished run's page and wait for its graph to be drawn. */
async function openRun(page: Page, id: string) {
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
      await clickNode(page, nodeId);

      const panel = page.getByRole('dialog');
      await expect(panel).toBeVisible();
      const text = (await panel.textContent()) ?? '';
      if (/not found/i.test(text)) notFound.push(`${nodeId}: ${text.slice(0, 80)}`);
    }

    expect(notFound, 'nodes whose panel said "not found"').toEqual([]);
  });

  test('the inner stage shows its own details', async ({ page, request }) => {
    const id = await startNestedRun(request);
    const ids = await nodeIds(request, id);
    await openRun(page, id);

    // `inner` sits inside `outer`; the graph draws it as a group of its own.
    await clickNode(page, ids.inner);

    const panel = page.getByRole('dialog');
    await expect(panel).toBeVisible();
    await expect(panel).not.toContainText(/not found/i);
    await expect(panel).toContainText('Stage Details');
    await expect(panel).toContainText('inner');
    // Filled in from the node itself: its status, its timing, its agents.
    await expect(panel).toContainText('completed');
    await expect(panel).toContainText(/Duration\s*\d/);
    await expect(panel).toContainText('ci_step');
  });

  test('an agent inside the inner stage links back to a stage that opens', async ({
    page,
    request,
  }) => {
    const id = await startNestedRun(request);
    const ids = await nodeIds(request, id);
    await openRun(page, id);

    await clickNode(page, ids.deep_two);
    const panel = page.getByRole('dialog');
    await expect(panel).toBeVisible();
    await expect(panel).toContainText('Agent Details');

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
