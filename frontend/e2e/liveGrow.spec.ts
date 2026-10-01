/**
 * Watch a real run that keeps adding nodes, in a real browser, without ever
 * reloading the page.
 *
 * `ci_dispatch_rounds` is a zero-cost script workflow that dispatches three
 * children and the next round's dispatcher, three rounds deep: nodes appear
 * every few seconds for a minute or so, which is exactly the situation where
 * the run page used to throw and go blank. Script agents only, so the
 * throwaway stack the machine check runs has no model keys to need.
 *
 * The test fails on the first page error, and reports where it happened: the
 * build carries source maps, so the stack is in our own file and function
 * names rather than the minified ones.
 */
import { test, expect, type Page } from '@playwright/test';

/** Everything the browser complained about while the page was open. */
function watchForTrouble(page: Page): string[] {
  const trouble: string[] = [];
  page.on('pageerror', (err) => {
    trouble.push(`pageerror: ${err.message}\n${err.stack ?? ''}`);
  });
  page.on('console', (msg) => {
    if (msg.type() !== 'error') return;
    const text = msg.text();
    // React logs a second copy of every crash it catches; keep it, it carries
    // the component stack the pageerror does not have.
    trouble.push(`console: ${text}`);
  });
  return trouble;
}

// Three rounds of three children, three seconds each: the run itself takes
// around a minute, and the point is to watch the whole of it.
test.setTimeout(300_000);

test('a run that keeps growing never breaks the page', async ({ page, request }) => {
  const started = await request.post('/api/runs', {
    data: {
      workflow: 'ci_dispatch_rounds',
      inputs: { items: ['alpha', 'bravo', 'charlie'] },
    },
  });
  expect(started.ok(), `could not start the run: ${await started.text()}`).toBe(true);
  const { execution_id: id } = await started.json();

  const trouble = watchForTrouble(page);
  await page.goto(`/app/workflow/${id}`);
  await expect(page.locator('.react-flow')).toBeVisible();

  // Watch it grow. The run takes ~2 min; check often, never reload.
  let seen = 0;
  for (let i = 0; i < 60; i++) {
    const nodes = await page.locator('.react-flow__node').count();
    seen = Math.max(seen, nodes);
    expect(trouble, 'the page broke while the run was growing').toEqual([]);
    const body = await (await request.get(`/api/workflows/${id}`)).json();
    if (['completed', 'failed', 'cancelled'].includes(body.status)) break;
    await page.waitForTimeout(2000);
  }

  // It really did grow while we watched: one node at the start, many at the end.
  expect(seen).toBeGreaterThan(5);
  expect(trouble).toEqual([]);
  await expect(page.locator('.react-flow')).toBeVisible();
});
