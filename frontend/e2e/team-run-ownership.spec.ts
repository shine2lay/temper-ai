/** H-OWN-1: production app, cached client-side route changes, delayed real API helpers. */
import { expect, test, type Page } from '@playwright/test';
import { A, B, CLOCK, accepted, event, flow, page as eventPage, type Raw } from '../src/__tests__/teamOwnershipFixtures';
import { expectAxeClean, expectTargets, fixture, glanceFontsSettled } from './team-helpers';

function gate() {
  let release!: () => void;
  const promise = new Promise<void>((done) => { release = done; });
  return { promise, release };
}
interface Capture { path: string; body?: Raw }
type OwnerReceipt = { node: Element; updates: string[]; observer: MutationObserver };
async function fixtures(page: Page) {
  const eventsA = gate();
  const messageA = gate();
  const messageB = gate();
  const requests: Capture[] = [];
  const list = fixture('trials-list').body as { trials: Raw[] };
  const trials = { total: 2, trials: [A, B].map((id) => ({
    ...list.trials[0], trial_id: `trial-${id}`, execution_id: id,
    goal_first_line: `Project ${id}`, state: 'running', run_status: 'running',
  })) };
  await page.route('**/api/team/**', async (route) => {
    const url = new URL(route.request().url());
    const req: Capture = { path: url.pathname + url.search };
    if (route.request().method() === 'POST') req.body = route.request().postDataJSON() as Raw;
    requests.push(req);
    let body: unknown;
    let status = 200;
    const id = url.pathname.split('/')[4];
    if (url.pathname === '/api/team/status') body = fixture('status-on').body;
    else if (url.pathname === '/api/team/roles') body = fixture('roles-ok').body;
    else if (url.pathname === '/api/team/trials') body = trials;
    else if (url.pathname.endsWith('/events')) {
      if (id === A) await eventsA.promise;
      const after = Number(url.searchParams.get('after'));
      body = id === A
        ? eventPage([event(A, 1, 'Late A foreign history')], 900, false, '2026-10-11T18:38:00Z')
        : eventPage(after < 2 ? [event(B, 1, 'Only B history'), event(B, 2, 'Only B second event')] : [], Math.max(2, after));
    } else if (url.pathname.endsWith('/messages') && req.body) {
      await (id === A ? messageA : messageB).promise;
      body = accepted(req.body.to as string); status = 201;
    } else if (url.pathname.includes('/messages/')) body = { body: id === A ? 'Late A foreign history' : 'Only B history' };
    else if (/^\/api\/team\/runs\/[^/]+$/.test(url.pathname)) body = flow(id, 'working', id === A ? 900 : 2);
    else return route.fallback(); // the static server fails closed with 503
    await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
  });
  return { eventsA, messageA, messageB, requests };
}
const composer = (page: Page) => page.getByRole('region', { name: 'Message a member' });
const activity = (page: Page) => page.getByRole('region', { name: 'All activity' });
async function visitFromList(page: Page, id: string) {
  await page.getByRole('link', { name: `Project ${id}`, exact: true }).click();
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(`Project ${id}`);
}
async function directClientRoute(page: Page, id: string) {
  // BrowserRouter consumes native history/popstate too (Back/Forward). Do NOT visit
  // /team between these runs: that would unmount even the faulty original owner.
  await page.evaluate((executionId) => {
    const state = { ...window.history.state, idx: (window.history.state?.idx ?? 0) + 1 };
    window.history.pushState(state, '', `/app/team/runs/${executionId}`);
    window.dispatchEvent(new PopStateEvent('popstate', { state }));
  }, id);
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(`Project ${id}`);
}

for (const theme of ['dark', 'light'] as const) for (const width of [320, 390, 1440]) {
  test(`cached Project owner journey, ${theme}, ${width}`, async ({ page }, testInfo) => {
    test.setTimeout(120_000);
    await page.setViewportSize({ width, height: width < 768 ? 844 : 900 });
    await page.addInitScript((t) => localStorage.setItem('temper_theme', t), theme);
    await page.clock.setFixedTime(new Date(CLOCK));
    const rig = await fixtures(page);
    await page.goto('/app/team'); // the ONLY document navigation in this journey
    await page.evaluate(() => Object.defineProperty(document, 'ownershipToken', { value: 'one-mounted-document' }));
    try {
      await test.step('happy path seeds cached B and measures its unchanged page', async () => {
        await visitFromList(page, B);
        await expect(activity(page)).toContainText('Only B history');
        await glanceFontsSettled(page);
        await expectAxeClean(page);
        await expectTargets(page);
        await expect(page.getByTestId('glance-map')).toHaveAttribute('data-dots-launched', '0');
        expect(await page.getByTestId('glance-page').evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
        const buttons = await page.getByTestId('glance-page').locator('button').evaluateAll((els) => els
          .filter((el) => el.getClientRects().length && !el.hasAttribute('data-testid'))
          .filter((el) => /^(Message a member|Stop project|Send message)$/.test(el.textContent?.trim() ?? ''))
          .map((el) => ({ text: el.textContent?.trim(), height: el.getBoundingClientRect().height })));
        expect(buttons.length).toBeGreaterThanOrEqual(3);
        expect(buttons.filter((b) => b.height < 44)).toEqual([]);
      });
      await directClientRoute(page, A);
      await expect.poll(() => rig.requests.filter((r) => r.path.startsWith(`/api/team/runs/${A}/events?`)).length).toBe(1);
      await composer(page).getByRole('textbox', { name: 'Message', exact: true }).fill('Identical words');
      await composer(page).getByRole('button', { name: 'Send message', exact: true }).click();
      await expect(composer(page).getByRole('button', { name: 'Sending…' })).toBeDisabled();
      await page.goBack(); // B→A→Back to cached B: same matching route element throughout
      await expect(page.getByRole('heading', { level: 1 })).toHaveText(`Project ${B}`);
      await expect(activity(page)).toContainText('Only B history');
      await expect(activity(page)).not.toContainText('Late A foreign history');
      await expect(composer(page).getByRole('button', { name: 'Send message', exact: true })).toBeEnabled();
      await expect(composer(page).getByRole('textbox', { name: 'Message', exact: true })).toHaveValue('');
      const box = composer(page).getByRole('textbox', { name: 'Message', exact: true });
      await box.fill('Identical words');
      await composer(page).getByRole('button', { name: 'Send message', exact: true }).click();
      await box.focus();
      const facts = await page.getByTestId('glance-facts').textContent();
      const receipt = page.getByTestId('team-message-result');
      await receipt.evaluate((node) => {
        // Combined A+B: watch B's own region before A's late result can arrive.
        const updates: string[] = [];
        const observer = new MutationObserver(() => updates.push(node.textContent ?? ''));
        observer.observe(node, { subtree: true, childList: true, characterData: true });
        (window as unknown as { __ownerReceipt: OwnerReceipt }).__ownerReceipt = { node, updates, observer };
      });
      rig.eventsA.release(); rig.messageA.release();
      await expect.poll(() => rig.requests.filter((r) => r.path === `/api/team/runs/${A}`).length).toBeGreaterThanOrEqual(2);
      await expect(box).toHaveValue('Identical words');
      await expect(box).toBeFocused();
      await expect(page.getByTestId('team-message-result')).toBeEmpty();
      await expect(composer(page).getByRole('button', { name: 'Sending…' })).toBeDisabled();
      await expect(activity(page)).not.toContainText('Late A foreign history');
      await expect(page.getByTestId('glance-facts')).toHaveText(facts!);
      expect(rig.requests.filter((r) => r.path.startsWith(`/api/team/runs/${B}/events?`))
        .every((r) => !r.path.includes('after=900'))).toBe(true);
      rig.messageB.release();
      await expect(box).toHaveValue('');
      const acceptedB = 'Temper accepted your message for lead.';
      await expect(receipt).toHaveText(acceptedB);
      await expect(box).toBeFocused();
      expect(await page.evaluate(() => {
        const p = (window as unknown as { __ownerReceipt: OwnerReceipt }).__ownerReceipt;
        p.observer.disconnect();
        return { same: p.node.isConnected && p.node === document.querySelector('[data-testid="team-message-result"]'),
          updates: p.updates, polite: p.node.getAttribute('aria-live'), atomic: p.node.getAttribute('aria-atomic'),
          nested: p.node.querySelectorAll('[aria-live], [role="status"], [role="alert"]').length };
      })).toEqual({ same: true, updates: [acceptedB], polite: 'polite', atomic: 'true', nested: 0 });
      const posts = rig.requests.filter((r) => r.body);
      expect(posts.map((r) => r.path)).toEqual([`/api/team/runs/${A}/messages`, `/api/team/runs/${B}/messages`]);
      expect(posts.map((r) => ({ to: r.body!.to, body: r.body!.body }))).toEqual([
        { to: 'lead', body: 'Identical words' }, { to: 'lead', body: 'Identical words' },
      ]);
      expect(posts[0].body!.request_id).not.toBe(posts[1].body!.request_id);
      expect(await page.evaluate(() => (document as unknown as { ownershipToken: string }).ownershipToken)).toBe('one-mounted-document');
      await glanceFontsSettled(page);
      await expectAxeClean(page); await expectTargets(page);
      expect(await page.getByTestId('glance-page').evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
      // The static service itself, with no intercept, rejects all API/ws paths.
      expect((await page.request.get('/api/ownership-no-live')).status()).toBe(503);
      expect((await page.request.get('/ws/ownership-no-live')).status()).toBe(503);
      await page.screenshot({ path: testInfo.outputPath(`owner-${theme}-${width}.png`), fullPage: true });
    } finally {
      rig.eventsA.release(); rig.messageA.release(); rig.messageB.release();
      await testInfo.attach('fictional-request-captures', { body: JSON.stringify(rig.requests, null, 2), contentType: 'application/json' });
    }
  });
}
