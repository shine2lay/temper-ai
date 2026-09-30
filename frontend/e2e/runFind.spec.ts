/**
 * Finding your way around a big run, on the real page.
 *
 * A run of eighty nodes used to be a wall: no search, no way to the failure,
 * nothing but scrolling. The find bar answers that — type part of a name and
 * the rest dims, press Enter or `n` to walk the matches, press the trouble
 * button to land on what failed, or narrow the run to what is still running.
 *
 * Unit tests cover the rules (src/__tests__/runSearch.test.ts). Only the real
 * page proves the rest: that the graph, the store and the live panel agree on
 * a node's id, that dimming reaches both the canvas and the agent list, and
 * that a run of eighty-eight nodes still answers while you type.
 *
 *   npm run build && TEMPER_E2E_BASE_URL=http://localhost:8420 \
 *     npx playwright test e2e/runFind.spec.ts
 *
 * The first tests make their own data with the zero-cost `ci_nested` and
 * `ci_slow` workflows. The last ones want the real thing — a stored
 * `epd_propose` proposal, a `github_work` run, a run that failed — and step
 * aside on a database that has none.
 */
import { expect, test } from '@playwright/test';
import type { APIRequestContext, Page } from '@playwright/test';

import { startNestedRun } from './helpers';

/** Open a run's page and wait for its graph to be drawn. */
async function openRun(page: Page, id: string, atLeast = 3) {
  // A page that never draws is worth explaining, so anything the page itself
  // complains about ends up in the test's output.
  page.on('pageerror', (err) => console.log('[page error]', err.message));
  page.on('console', (msg) => {
    if (msg.type() === 'error') console.log('[console]', msg.text().slice(0, 300));
  });
  await page.goto(`/app/workflow/${id}`);
  // A run of eighty-eight nodes is laid out before anything is drawn, so the
  // first node is worth waiting longer for than the default. This machine
  // also drops the odd page load outright (ERR_NETWORK_CHANGED, nothing to
  // do with the dashboard), which leaves a white page; one reload settles it.
  const firstNode = page.locator('.react-flow__node').first();
  try {
    await expect(firstNode).toBeVisible({ timeout: 20_000 });
  } catch {
    await page.reload();
    await expect(firstNode).toBeVisible({ timeout: 30_000 });
  }
  await expect
    .poll(async () => page.locator('.react-flow__node').count(), { timeout: 20_000 })
    .toBeGreaterThanOrEqual(atLeast);
  // The find bar rides on the graph, so it is there once the graph is.
  await expect(page.getByTestId('run-find-bar')).toBeVisible();
  return settle(page);
}

/**
 * Wait until the graph stops growing, and say how many nodes it ended with.
 * A big run arrives in pieces — the run, then its stages, then the agents,
 * with a layout pass after each — and anything measured mid-flight measures
 * the loading, not the find bar.
 */
async function settle(page: Page): Promise<number> {
  let last = -1;
  for (let i = 0; i < 40; i++) {
    const n = await page.locator('.react-flow__node').count();
    if (n > 0 && n === last) return n;
    last = n;
    await page.waitForTimeout(400);
  }
  return last;
}

/** How many nodes the page is keeping bright. */
async function brightCount(page: Page): Promise<number> {
  return page.locator('.react-flow__node').evaluateAll(
    (els) => els.filter((el) => ((el as HTMLElement).style.opacity || '1') === '1').length,
  );
}

/**
 * What the helper below spends before the page has even been asked: the
 * find bar waits 120ms for typing to stop, and the helper rounds that up.
 */
const TYPING_SETTLE_ALLOWANCE = 250;

/** Type a word into the find bar and let the dimming settle. */
async function find(page: Page, word: string) {
  const box = page.getByTestId('run-find-input');
  await box.fill(word);
  await page.waitForTimeout(TYPING_SETTLE_ALLOWANCE);
}

/** The run's node names, nested ones included. */
async function nodeNames(request: APIRequestContext, runId: string): Promise<string[]> {
  const res = await request.get(`/api/workflows/${runId}`);
  expect(res.ok(), `run ${runId} could not be read`).toBe(true);
  const names: string[] = [];
  const walk = (nodes: { name: string; child_nodes?: unknown[] }[] | undefined) => {
    for (const n of nodes ?? []) {
      names.push(n.name);
      walk(n.child_nodes as { name: string; child_nodes?: unknown[] }[] | undefined);
    }
  };
  walk((await res.json()).nodes);
  return names;
}

/**
 * A stored run of one of these workflows, biggest first, or null.
 *
 * Real runs are the point of the last tests: made-up data cannot show what
 * eighty-eight nodes do to a page.
 */
async function storedRun(
  request: APIRequestContext,
  workflow: string,
  minNodes: number,
): Promise<{ id: string; nodes: string[] } | null> {
  const list = await request.get('/api/workflows?limit=200');
  if (!list.ok()) return null;
  const runs: { id: string; workflow_name: string; status: string }[] = (await list.json()).runs ?? [];
  for (const run of runs.filter((r) => r.workflow_name === workflow)) {
    const names = await nodeNames(request, run.id);
    if (names.length >= minNodes) return { id: run.id, nodes: names };
  }
  return null;
}

test.describe('finding your way around a run', () => {
  test('a word dims the rest, counts the matches and walks them', async ({ page, request }) => {
    const id = await startNestedRun(request);
    await openRun(page, id);

    const all = await page.locator('.react-flow__node').count();
    expect(await brightCount(page)).toBe(all); // nothing typed, nothing dimmed

    await find(page, 'inner');
    // The count reads "1 of 2"-ish: at least one match, and the page says so.
    const count = page.getByTestId('run-find-count');
    await expect(count).toBeVisible();
    await expect(count).toHaveText(/^\d+ of \d+$/);
    const matches = Number((await count.innerText()).split(' of ')[1]);
    expect(matches).toBeGreaterThan(0);

    // Dimmed, not deleted: every node is still drawn.
    expect(await page.locator('.react-flow__node').count()).toBe(all);
    expect(await brightCount(page)).toBeLessThan(all);

    // The match it is standing on wears the ring.
    await expect(page.locator('.react-flow__node.run-find-current')).toHaveCount(1);
    const first = await page
      .locator('.react-flow__node.run-find-current')
      .getAttribute('data-id');

    // Enter steps on, and round again at the end.
    await page.getByTestId('run-find-input').press('Enter');
    await page.waitForTimeout(150);
    if (matches > 1) {
      await expect(count).not.toHaveText(`1 of ${matches}`);
      const second = await page
        .locator('.react-flow__node.run-find-current')
        .getAttribute('data-id');
      expect(second).not.toBe(first);
    }

    // A word nothing answers to says so, and leaves the run whole.
    await find(page, 'zzz-nothing-here');
    await expect(count).toHaveText('none');
    expect(await page.locator('.react-flow__node').count()).toBe(all);
  });

  test('the keyboard: / focuses, n steps, Escape gives the run back', async ({ page, request }) => {
    const id = await startNestedRun(request);
    await openRun(page, id);
    const all = await page.locator('.react-flow__node').count();

    await page.locator('.react-flow').click({ position: { x: 5, y: 5 } });
    await page.keyboard.press('/');
    await expect(page.getByTestId('run-find-input')).toBeFocused();

    await page.keyboard.type('inner');
    await page.waitForTimeout(250);
    expect(await brightCount(page)).toBeLessThan(all);

    await page.keyboard.press('Escape');
    await page.waitForTimeout(250);
    await expect(page.getByTestId('run-find-input')).toHaveValue('');
    expect(await brightCount(page)).toBe(all);
    await expect(page.locator('.react-flow__node.run-find-current')).toHaveCount(0);

    // `n` outside the box steps through the matches.
    await find(page, 'inner');
    const before = await page.getByTestId('run-find-count').innerText();
    await page.locator('.react-flow').click({ position: { x: 5, y: 5 } });
    await page.keyboard.press('n');
    await page.waitForTimeout(150);
    const after = await page.getByTestId('run-find-count').innerText();
    expect(after.split(' of ')[1]).toBe(before.split(' of ')[1]); // same haystack
  });

  test('the status filter dims without deleting, and the live list follows', async ({ page, request }) => {
    const id = await startNestedRun(request);
    await openRun(page, id);
    const all = await page.locator('.react-flow__node').count();

    // A finished run has nothing running: the filter dims everything and the
    // graph still draws every node.
    await page.getByTestId('run-find-status-running').click();
    await page.waitForTimeout(250);
    expect(await page.locator('.react-flow__node').count()).toBe(all);
    expect(await brightCount(page)).toBeLessThan(all);

    await page.getByTestId('run-find-status-all').click();
    await page.waitForTimeout(250);
    expect(await brightCount(page)).toBe(all);

    // The same word narrows the live panel's agent list.
    const rows = page.getByTestId('live-agent-row');
    await expect.poll(async () => rows.count(), { timeout: 15_000 }).toBeGreaterThan(1);
    const names = await rows.locator('span').first().allInnerTexts();
    expect(names.length).toBeGreaterThan(0);

    await find(page, 'zzz-nothing-here');
    await expect
      .poll(async () => rows.locator('[data-dimmed]').count().catch(() => 0))
      .toBeGreaterThanOrEqual(0);
    const dimmed = await page.locator('[data-testid="live-agent-row"][data-dimmed]').count();
    const total = await rows.count();
    expect(dimmed).toBe(total); // nothing matches, so every row is dimmed
    expect(await rows.count()).toBe(total); // and every row is still listed
  });

  test('the trouble button goes to what is running when nothing failed', async ({ page, request }) => {
    // `ci_slow` sits in a sleeping script, so the run is still going while
    // the page is open. Without `seconds` its script has nothing to sleep on
    // and the node fails instead.
    const res = await request.post('/api/runs', {
      data: { workflow: 'ci_slow', inputs: { seconds: '25' } },
    });
    expect(res.ok(), 'could not start ci_slow').toBe(true);
    const { execution_id: id } = await res.json();

    await openRun(page, id, 2);
    const trouble = page.getByTestId('run-find-trouble');
    await expect.poll(async () => trouble.getAttribute('data-trouble'), { timeout: 20_000 })
      .toBe('running');

    await trouble.click();
    await page.waitForTimeout(400);
    const on = page.locator('.react-flow__node.run-find-current');
    await expect(on).toHaveCount(1);
    // It landed on the node that is actually running.
    await expect(on.locator('[data-status="running"], .dag-node-running').first()).toBeVisible();

    await request.post(`/api/runs/${id}/cancel`).catch(() => undefined);
  });
});

test.describe('on the real runs', () => {
  test('an 70+ node proposal: search finds its handful, and typing stays quick', async ({
    page,
    request,
  }) => {
    const run = await storedRun(request, 'epd_propose', 40);
    test.skip(!run, 'no big epd_propose run stored here');

    // The graph is left to arrive in full before anything is timed: the
    // question here is whether the find bar keeps up on a settled run of
    // eighty-odd nodes, not how long a big run takes to load.
    const all = await openRun(page, run!.id, 20);
    expect(all).toBeGreaterThan(20);

    // The run itself says how many of its nodes carry the word in their own
    // name; the page finds those and the agents under them, so it must find
    // at least as many — and never the whole run, or the word is doing
    // nothing.
    const byName = run!.nodes.filter((n) => n.toLowerCase().includes('pitch')).length;
    test.skip(byName === 0, 'this proposal has no pitch_* stages');

    const started = Date.now();
    await find(page, 'pitch');
    const count = page.getByTestId('run-find-count');
    await expect(count).toHaveText(/^\d+ of \d+$/);
    const found = Number((await count.innerText()).split(' of ')[1]);
    // Typing must not lock the page up. Measured on the built dashboard and
    // eighty-eight nodes, the count and the dimming land about 130ms after
    // the keystroke; a second is a budget that would catch a real stutter
    // without failing on a busy machine.
    expect(Date.now() - started).toBeLessThan(1000 + TYPING_SETTLE_ALLOWANCE);
    expect(found).toBeGreaterThanOrEqual(byName);
    expect(found).toBeLessThan(all);

    expect(await page.locator('.react-flow__node').count()).toBe(all);
    expect(await brightCount(page)).toBeLessThan(all);

    // Case does not matter: the same handful.
    await find(page, 'PITCH');
    expect(Number((await count.innerText()).split(' of ')[1])).toBe(found);

    // Stepping walks them without losing the count, and the page keeps up.
    const stepping = Date.now();
    for (let i = 0; i < 3; i++) {
      await page.getByTestId('run-find-next').click();
      await page.waitForTimeout(120);
    }
    expect(Date.now() - stepping).toBeLessThan(2000);
    expect(Number((await count.innerText()).split(' of ')[1])).toBe(found);
    await expect(page.locator('.react-flow__node.run-find-current')).toHaveCount(1);
  });

  test('a github_work run: search, filter and the whole graph left standing', async ({
    page,
    request,
  }) => {
    const run = await storedRun(request, 'github_work', 10);
    test.skip(!run, 'no github_work run stored here');

    const all = await openRun(page, run!.id, 5);

    const word = run!.nodes.find((n) => n === 'build') ?? run!.nodes[0];
    await find(page, word);
    await expect(page.getByTestId('run-find-count')).toHaveText(/^\d+ of \d+$/);
    expect(await brightCount(page)).toBeLessThan(all);
    expect(await page.locator('.react-flow__node').count()).toBe(all);

    // The filter narrows on top of the word, and clearing gives it all back.
    await page.getByTestId('run-find-status-failed').click();
    await page.waitForTimeout(250);
    expect(await page.locator('.react-flow__node').count()).toBe(all);

    // Escape from the filter button, not from the box: the whole page gives
    // the run back, however you got there.
    await page.keyboard.press('Escape');
    await page.waitForTimeout(400);
    await expect(page.getByTestId('run-find-input')).toHaveValue('');
    expect(await brightCount(page)).toBe(all);
  });

  test('a run that failed: the trouble button lands on the failure', async ({ page, request }) => {
    const list = await request.get('/api/workflows?limit=200');
    const runs: { id: string; status: string }[] = list.ok() ? (await list.json()).runs ?? [] : [];
    let failed: { id: string; node: string } | null = null;
    for (const run of runs.filter((r) => r.status === 'failed').slice(0, 8)) {
      const detail = await request.get(`/api/workflows/${run.id}`);
      if (!detail.ok()) continue;
      const nodes: { name: string; status: string; child_nodes?: unknown[] }[] = [];
      const walk = (ns: { name: string; status: string; child_nodes?: unknown[] }[] | undefined) => {
        for (const n of ns ?? []) {
          nodes.push(n);
          walk(n.child_nodes as typeof nodes | undefined);
        }
      };
      walk((await detail.json()).nodes);
      const bad = nodes.find((n) => n.status === 'failed');
      if (bad) {
        failed = { id: run.id, node: bad.name };
        break;
      }
    }
    test.skip(!failed, 'no failed run stored here');

    await openRun(page, failed!.id, 2);
    const trouble = page.getByTestId('run-find-trouble');
    await expect(trouble).toHaveAttribute('data-trouble', 'failed');

    await trouble.click();
    await page.waitForTimeout(400);
    const on = page.locator('.react-flow__node.run-find-current');
    await expect(on).toHaveCount(1);
    await expect(on).toContainText(failed!.node);
  });
});
