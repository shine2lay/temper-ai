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

  test("a row's Studio link is at least 24 px square", async ({ page, request }) => {
    // WCAG 2.2 2.5.8. The link sits inside the row, which is a target too, so
    // only its own size counts. It was 19 px tall.
    await startSmokeRun(request);
    await page.goto('/app/');

    const studio = page.locator('a[href$="/studio/smoke_test"]').first();
    await expect(studio).toBeVisible();
    const box = await studio.boundingBox();
    expect(box!.height).toBeGreaterThanOrEqual(24);
    expect(box!.width).toBeGreaterThanOrEqual(24);
  });

  test("a row's compare checkbox is a 24 px target that never opens the run", async ({
    page,
    request,
  }) => {
    // WCAG 2.2 2.5.8. It was 16 px, inside the row. The box you see is still
    // 16 px; the checkbox you use is the 24 px one around it.
    await startSmokeRun(request);
    await page.goto('/app/');

    const box = page.getByRole('checkbox', { name: 'Select smoke_test for comparison' }).first();
    await expect(box).toBeVisible();
    const b = (await box.boundingBox())!;
    expect(b.height).toBeGreaterThanOrEqual(24);
    expect(b.width).toBeGreaterThanOrEqual(24);

    // A click near its corner, outside the 16 px box, ticks it and stays here.
    const before = await box.isChecked();
    await page.mouse.click(b.x + 2, b.y + 2);
    await expect(box).toBeChecked({ checked: !before });
    await expect(page).not.toHaveURL(/\/workflow\//);
  });

  test("keys on a row's checkbox and Studio link reach them, not the row", async ({
    page,
    request,
  }) => {
    // WCAG 2.2 2.1.1. The row opens its run on Enter or Space, and it used to
    // catch those keys from its controls too.
    await startSmokeRun(request);
    await page.goto('/app/');

    const box = page.getByRole('checkbox', { name: 'Select smoke_test for comparison' }).first();
    await expect(box).toBeVisible();
    const before = await box.isChecked();
    await box.focus();
    await page.keyboard.press('Space');
    await expect(box).toBeChecked({ checked: !before });
    await expect(page).not.toHaveURL(/\/workflow\//);

    await page.locator('a[href$="/studio/smoke_test"]').first().focus();
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(/\/studio\/smoke_test/);
  });

  test("a running row's Cancel is a 24 px target that never opens the run", async ({
    page,
    request,
  }) => {
    // WCAG 2.2 2.5.8. It was 21 px tall, inside the row. `ci_slow` sleeps, so
    // the run is still going while the list is open; the click cancels it.
    const res = await request.post('/api/runs', {
      data: { workflow: 'ci_slow', inputs: { seconds: '40' } },
    });
    expect(res.ok(), 'could not start ci_slow').toBe(true);
    const { execution_id: id } = await res.json();
    try {
      await page.goto('/app/');
      // This run's own row (it shows the id's first 8 characters): another
      // spec may have a ci_slow run going at the same time.
      const row = page.locator('[role="link"]', { hasText: id.replace('wf-', '').slice(0, 8) });
      const cancel = row.getByRole('button', { name: 'Cancel workflow ci_slow' });
      await expect(cancel).toBeVisible({ timeout: 20_000 });
      const b = (await cancel.boundingBox())!;
      expect(b.height).toBeGreaterThanOrEqual(24);
      expect(b.width).toBeGreaterThanOrEqual(24);

      // A click on its top edge, above the button you see, cancels and stays here.
      await page.mouse.click(b.x + b.width / 2, b.y + 1);
      await expect
        .poll(async () => (await (await request.get(`/api/workflows/${id}`)).json()).status, {
          timeout: 20_000,
        })
        .toBe('cancelled');
      await expect(page).not.toHaveURL(/\/workflow\//);
    } finally {
      await request.post(`/api/runs/${id}/cancel`, { data: {} }).catch(() => undefined);
    }
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

  test("the find bar's status choices are 24 px targets", async ({ page, request }) => {
    // WCAG 2.2 2.5.8: "All" was 23 by 18 px and touched "Running".
    const id = await startSmokeRun(request);
    await page.goto(`/app/workflow/${id}`);
    await expect(page.getByTestId('run-find-bar')).toBeVisible({ timeout: 20_000 });

    for (const key of ['all', 'running', 'failed', 'waiting']) {
      const b = (await page.getByTestId(`run-find-status-${key}`).boundingBox())!;
      expect(b.height, key).toBeGreaterThanOrEqual(24);
      expect(b.width, key).toBeGreaterThanOrEqual(24);
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

    // By the row's own name, not its rendered text: a row whose values
    // disagree also shows a "differs" marker, and whether two smoke runs
    // take the same tenth of a second is a coin toss. Asserting the exact
    // text made this test fail at random for weeks.
    await expect(page.locator('th[data-row="Duration"]')).toBeVisible();
    // Node rows are the union across both runs.
    await expect(page.locator('th[data-row="first"]')).toBeVisible();
    await expect(page.locator('th[data-row="second"]')).toBeVisible();
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
