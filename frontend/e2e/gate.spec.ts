import { test, expect } from '@playwright/test';
import { startGatedRun, waitForFinish, waitingGates } from './helpers';

/**
 * A human gate in a real browser: the run parks, the modal opens by itself
 * with the questions the previous node asked, and the answers come out the
 * other side inside the next agent's prompt.
 *
 * The unit tests cover the component against fixtures; these cover the part
 * fixtures cannot — that a parked run actually opens a modal, and that what
 * is clicked here reaches the node that runs next.
 */
test.describe('human gate', () => {
  test('asks the questions, then hands the answers to the gated node', async ({ page, request }) => {
    const id = await startGatedRun(request);
    await page.goto(`/app/workflow/${id}`);

    // Nobody clicked anything: a parked run says so on its own.
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText('decide');

    // The plan is shown as prose. The JSON it was parsed out of is in the
    // page but folded away, so the questions are not on screen twice.
    const upstream = dialog.locator('section').first();
    await expect(upstream).toContainText('Two ways to store gate answers');
    await expect(upstream.getByText(/"questions":/)).toBeHidden();
    await expect(dialog.getByText('Full output')).toBeVisible();

    // Each question is a labelled control, options or not.
    for (const q of [
      'Where should a gate answer live?',
      'Which runs should carry answers?',
      'Anything I should not touch while doing this?',
    ]) {
      await expect(dialog.getByLabel(q, { exact: true })).toBeVisible();
    }

    // Approving is held until the questions with options are answered.
    const approve = dialog.getByRole('button', { name: /Approve & continue/ });
    await expect(approve).toBeDisabled();

    // A preview belongs to its option and appears only once chosen.
    const storage = dialog
      .locator('section')
      .filter({ has: page.getByRole('button', { name: /Its own table/ }) });
    await expect(storage.getByText(/CREATE TABLE gate_responses/)).toHaveCount(0);
    await dialog.getByRole('button', { name: /Its own table/ }).click();
    await expect(storage.getByText(/CREATE TABLE gate_responses/)).toBeVisible();

    // One answer replaces another; a multi-select keeps both.
    await dialog.getByRole('button', { name: /On the waiting event/ }).click();
    await expect(dialog.getByRole('button', { name: /On the waiting event/ })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    await expect(dialog.getByRole('button', { name: /Its own table/ })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
    await dialog.getByRole('button', { name: /^In-process/ }).click();
    await dialog.getByRole('button', { name: /^Worker/ }).click();
    for (const label of [/^In-process/, /^Worker/]) {
      await expect(dialog.getByRole('button', { name: label })).toHaveAttribute(
        'aria-pressed',
        'true',
      );
    }

    await dialog
      .getByLabel('Anything I should not touch while doing this?', { exact: true })
      .fill('do not touch the worker poll interval');
    await dialog.getByLabel(/Anything else/).fill('ship it');

    await expect(approve).toBeEnabled();
    await approve.click();
    await expect(dialog).toBeHidden();

    // The answers are in the gated node's prompt, in the order asked, with
    // the multi-select joined and the free text last.
    const body = await waitForFinish(request, id);
    expect(body.status).toBe('completed');
    const nodes = body.nodes as { name: string; status: string; agent?: { output?: string } }[];
    const decide = nodes.find((n) => n.name === 'decide');
    expect(decide?.status).toBe('completed');
    expect(decide?.agent?.output).toContain('A: On the waiting event');
    expect(decide?.agent?.output).toContain('A: In-process, Worker');
    expect(decide?.agent?.output).toContain('do not touch the worker poll interval');
    expect(decide?.agent?.output).toContain('ship it');

    // `gate` belongs to the gated node alone.
    const build = nodes.find((n) => n.name === 'build');
    expect(build?.status).toBe('completed');
    expect(build?.agent?.output).toContain('not gated');
  });

  test('"Later" leaves the run waiting', async ({ page, request }) => {
    const id = await startGatedRun(request);
    await page.goto(`/app/workflow/${id}`);

    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    // Exact: an option's description says "Queryable later" too.
    await dialog.getByRole('button', { name: 'Later', exact: true }).click();
    await expect(dialog).toBeHidden();

    // Dismissing is not answering: the run is still parked, and the gated
    // node's card can open the modal again.
    expect(await waitingGates(request, id)).toHaveLength(1);

    // The gated node is a placeholder in the DAG — it has not run — so that
    // placeholder is what has to bring the question back.
    await page.getByRole('button', { name: /decide/ }).first().click();
    await expect(page.getByRole('dialog')).toBeVisible();
  });
});
