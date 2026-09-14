/**
 * End-to-end checks against a real server and the built dashboard.
 *
 * These deliberately cover the things that broke silently and were only
 * caught by looking: a run list that becomes unreadable on a narrow window,
 * a bad link that hangs on a skeleton forever, navigation that throws away
 * unsaved edits, buttons whose accessible name does not match their label.
 * Unit tests cannot see any of that.
 *
 * Every spec creates its own data through the API (the zero-cost
 * `smoke_test` workflow), so there is nothing to seed and nothing to spend.
 */
import { expect, test } from '@playwright/test';

import { startSmokeRun } from './helpers';

test.describe('Workflow list', () => {
  test('lists runs, and the counter reflects the server total', async ({ page, request }) => {
    await startSmokeRun(request);
    await page.goto('/app/');

    await expect(page.getByRole('heading', { name: 'Workflows' })).toBeVisible();
    await expect(page.getByText('smoke_test').first()).toBeVisible();

    // "N of TOTAL" — the total comes from the API, not from the loaded page.
    const counter = page.getByText(/\d+ of \d+/).first();
    await expect(counter).toBeVisible();
    const [loaded, total] = (await counter.innerText()).match(/(\d+) of (\d+)/)!.slice(1).map(Number);
    expect(total).toBeGreaterThanOrEqual(loaded);
  });

  test('status tabs filter on the server', async ({ page, request }) => {
    await startSmokeRun(request);
    await page.goto('/app/');
    await page.getByRole('button', { name: 'completed', exact: true }).click();

    await expect(page.getByText(/\d+ of \d+ completed runs/)).toBeVisible();
    // Every visible badge belongs to a completed run.
    const badges = page.locator('[href*="/app/workflow/"] >> text=/^(failed|cancelled)$/');
    await expect(badges).toHaveCount(0);
  });

  test('the workflow name survives a narrow window', async ({ page, request }) => {
    // The columns were fixed-width and unshrinkable, so below ~1100px the
    // name — the only thing identifying a row — was squeezed to zero.
    await startSmokeRun(request);
    await page.setViewportSize({ width: 820, height: 900 });
    await page.goto('/app/');

    const name = page.getByText('smoke_test').first();
    await expect(name).toBeVisible();
    const box = await name.boundingBox();
    expect(box!.width).toBeGreaterThan(40);
  });

  test('buttons can be reached by their visible label', async ({ page }) => {
    // aria-label used to replace the visible text, which breaks voice control.
    await page.goto('/app/');
    await expect(page.getByRole('button', { name: /New Run/ })).toBeVisible();
  });

  test('keyboard focus is visible', async ({ page }) => {
    await page.goto('/app/');
    await page.keyboard.press('Tab');
    const outline = await page.evaluate(() => {
      const s = getComputedStyle(document.activeElement!);
      return `${s.outlineStyle} ${s.outlineWidth}`;
    });
    expect(outline).not.toMatch(/none|0px/);
  });
});

test.describe('Execution view', () => {
  test('shows the run, its nodes and each tab', async ({ page, request }) => {
    const id = await startSmokeRun(request, { message: 'from e2e' });
    await page.goto(`/app/workflow/${id}`);

    await expect(page.getByRole('heading', { name: 'smoke_test' })).toBeVisible();
    await expect(page.getByText('completed').first()).toBeVisible();

    // Both nodes are drawn, titled by their workflow node names.
    await expect(page.locator('.react-flow__node').first()).toBeVisible();
    await expect(page.getByText('first', { exact: true }).first()).toBeVisible();
    await expect(page.getByText('second', { exact: true }).first()).toBeVisible();

    for (const tab of ['Timeline', 'Event Log', 'Checkpoints', 'DAG']) {
      await page.getByText(tab, { exact: false }).first().click();
      await expect(page.getByText(tab, { exact: false }).first()).toBeVisible();
    }
  });

  test('the page title names the run', async ({ page, request }) => {
    const id = await startSmokeRun(request);
    await page.goto(`/app/workflow/${id}`);
    await expect(page).toHaveTitle(/smoke_test/);
  });

  test('a run that does not exist reports it instead of loading forever', async ({ page }) => {
    await page.goto('/app/workflow/definitely-not-a-run');

    await expect(page.getByText('Run not found')).toBeVisible();
    await expect(page.getByRole('link', { name: /Back to workflows/ })).toBeVisible();
  });
});

test.describe('Compare', () => {
  test('compares two runs side by side', async ({ page, request }) => {
    const [a, b] = [await startSmokeRun(request, { message: 'a' }), await startSmokeRun(request, { message: 'b' })];
    await page.goto(`/app/compare?ids=${a},${b}`);

    await expect(page.getByRole('heading', { name: /Comparing 2 runs/ })).toBeVisible();
    await expect(page.getByRole('cell', { name: 'Duration', exact: true })).toBeVisible();
    // Node rows are the union across both runs.
    await expect(page.getByRole('cell', { name: 'first', exact: true })).toBeVisible();
    await expect(page.getByRole('cell', { name: 'second', exact: true })).toBeVisible();
  });

  test('asks for two runs when given fewer', async ({ page }) => {
    await page.goto('/app/compare?ids=');
    await expect(page.getByText(/Pick at least two runs/)).toBeVisible();
  });
});

test.describe('Library', () => {
  test('warns before discarding unsaved edits', async ({ page }) => {
    await page.goto('/app/library/agent/smoke_echo');

    const field = page.locator('textarea').first();
    await expect(field).toBeVisible();
    await field.fill('edited by the end-to-end test');

    let asked = '';
    page.on('dialog', (d) => {
      asked = d.message();
      void d.dismiss();
    });
    await page.getByRole('link', { name: 'Workflows' }).first().click();
    await page.waitForTimeout(1000);

    expect(asked).toMatch(/unsaved changes/i);
    await expect(page).toHaveURL(/\/library\/agent\//);
  });
});

test('no page makes a failing request', async ({ page, request }) => {
  const id = await startSmokeRun(request);
  const failures: string[] = [];
  page.on('response', (r) => {
    if (r.status() >= 400) failures.push(`${r.status()} ${r.url()}`);
  });

  for (const path of ['/app/', `/app/workflow/${id}`, '/app/library', '/app/docs', '/app/settings', '/app/studio']) {
    await page.goto(path);
    await page.waitForTimeout(1200);
  }

  expect(failures).toEqual([]);
});
