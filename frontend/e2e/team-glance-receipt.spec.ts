/**
 * F-MF3: a real built page/sender, fictional serializer-shaped replies, and
 * the static-only registry. No live sends, models, proxy or Temper server.
 * One happy-path journey bundles copy, seq mutations, focus, fit and axe;
 * contract negatives keep held/legacy/refusal/no-answer words distinct.
 * Mutation/ARIA evidence does not claim observed screen-reader speech.
 */
import { mkdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { expect, test, type Locator, type Page } from '@playwright/test';
import { expectAxeClean, expectTargets, fixture, glanceFontsSettled, nothingSent, serveActions, serveTeam, type Fixture, type Reply } from './team-helpers';
import type receiptsShape from './fixtures/team/message-receipts-fictional.json';

const receipts = JSON.parse(readFileSync(path.join(process.cwd(), 'e2e/fixtures/team/message-receipts-fictional.json'), 'utf8')) as typeof receiptsShape;
type Raw = Record<string, unknown>;
const ID = 'fictional-receipt-run';
const AT = '2026-10-12T18:00:00+00:00';
const ACCEPTED = 'Temper accepted your message for maker.';
const HELD = 'Sent: held until you answer the open question.';
const PAUSED = `${HELD} The team is paused, so no member takes a turn until then.`;
const LEGACY = 'Sent. maker gets it at its next turn.';
const LONG = `<img src=x onerror="alert(1)"> & ${'very-long-recipient-'.repeat(12)}`;
const SHOTS = process.env.TEAM_RECEIPT_SHOTS;

/** Preserve captured serializer fields, replacing trial/output/user data with fixed fiction. */
function fictionalRun(flow: boolean, ready = false, paused = false): Fixture {
  const raw: Raw = flow
    ? JSON.parse(readFileSync(path.join(process.cwd(), 'e2e/fixtures/team/flow/real/working.json'), 'utf8')) as Raw
    : structuredClone(fixture('run-running').body) as Raw;
  const trial = raw.trial as Raw;
  const member = (raw.members as Raw[]).find((m) => m.name === (flow ? 'lead' : 'maker'))!;
  const members = [{ ...member, name: 'maker', role: 'builder', leader: true, state: ready ? 'ready' : 'working',
    activity: ready ? 'idle' : 'working', model: 'fictional-model', thinking: 'high', effective: null,
    since: AT, last_turn: null, turn_no: 1, on: null, idle_note: null, idle_reason: null,
    tools_now: [], ready_messages: ready ? 1 : 0, last_sent: null, last_share: null, conflicts: [], wait_id: null, last_activity_at: AT }];
  return { route: '', status: 200, body: { ...raw,
    execution_id: ID, kind: flow ? 'flow' : 'rounds', trial_id: 'fictional-receipt', workflow: 'fictional-receipt',
    run_status: 'running', state: paused ? 'paused' : 'running', cost_usd: 0,
    account: null, trial: { ...trial, goal: 'Fictional receipt test.', leader: 'maker', members: [{ name: 'maker', role: 'builder', leader: true, tools: [] }],
      project: null, started_at: AT, started_by: 'fictional owner', request_id: 'fictional-start' },
    members, open_waits: [], timeline: { entries: [], not_shown: 0 }, owner_actions: [], outcome: null,
    round: { current: 1, keep_goings: 0, pause_after_rounds: 3 }, reviews: [],
    phase: { name: 'working', words: 'Fictional work.', since: AT, running: ready ? 0 : 1, asked: false, reason: null },
    as_of: AT, started_at: AT, elapsed_s: 0, last_activity_at: AT,
    spend: { cost_usd: 0, pause_every_usd: 100, last_check_in_usd: 0, next_check_in_usd: 100, since_check_in_usd: 0, check_ins: 0 },
    you: { count: 0, first: null }, counts: { members: 1, working: ready ? 0 : 1, ready: ready ? 1 : 0, idle: 0, held: 0, failed: 0, ended: 0 },
    links: [], work: { latest: null, shares: [], shares_total: 0, summary: null }, events_cursor: 0, events_total: 0,
  } };
}

function latch() {
  let release!: () => void;
  const until = new Promise<void>((resolve) => { release = resolve; });
  return { until, release };
}

async function open(page: Page, flow: boolean, replies: Reply[]) {
  const state = { ready: false, paused: false };
  const sent = nothingSent();
  await serveTeam(page, { run: () => fictionalRun(flow, state.ready, state.paused) });
  await serveActions(page, sent, { message: replies });
  await page.route(/\/api\/team\/runs\/[^/]+\/events(\?|$)/, (route) => route.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ events: [], cursor: 0, more: false, as_of: AT }) }));
  const writes: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('/api/') && request.method() !== 'GET') writes.push(new URL(request.url()).pathname);
  });
  await page.clock.setFixedTime(new Date(AT));
  await page.goto(`/app/team/runs/${ID}`);
  if (flow) {
    await expect(page.getByTestId('glance-page')).toBeVisible();
    await expect(page.getByTestId('glance-just-sent')).not.toContainText('Reading the team');
    await glanceFontsSettled(page);
  }
  const composer = page.getByRole('region', { name: 'Message a member' });
  await expect(composer).toBeVisible();
  return { state, sent, writes, composer };
}

type Probe = { node: Element; updates: string[]; observer: MutationObserver };
type ProbeWindow = Window & { __receiptProbe?: Probe };
const result = (page: Page) => page.getByTestId('team-message-result');

async function watch(page: Page) {
  await result(page).evaluate((node) => {
    const w = window as ProbeWindow;
    const updates: string[] = [];
    const observer = new MutationObserver(() => updates.push(node.textContent ?? ''));
    observer.observe(node, { subtree: true, childList: true, characterData: true });
    w.__receiptProbe = { node, updates, observer };
  });
}

async function probe(page: Page) {
  return page.evaluate(() => {
    const p = (window as ProbeWindow).__receiptProbe!;
    return { same: p.node.isConnected && p.node === document.querySelector('[data-testid="team-message-result"]'),
      updates: p.updates, atomic: p.node.getAttribute('aria-atomic'), polite: p.node.getAttribute('aria-live'),
      nested: p.node.querySelectorAll('[aria-live], [role="status"], [role="alert"]').length };
  });
}

/** Measure every non-whitespace character's drawn range, not a clipped DOM textContent alone. */
async function measureReceipt(receipt: Locator, to: string) {
  return receipt.evaluate((root, recipient) => {
    const bounds = root.getBoundingClientRect();
    const rows = new Set<number>();
    const recipientRows = new Set<number>();
    const clipped: string[] = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const text = node.textContent ?? '';
      const start = text.indexOf(recipient);
      for (let i = 0; i < text.length; i++) {
        if (!text[i].trim()) continue;
        const range = document.createRange();
        range.setStart(node, i); range.setEnd(node, i + 1);
        for (const box of range.getClientRects()) {
          rows.add(Math.round(box.top));
          if (start >= 0 && i >= start && i < start + recipient.length) recipientRows.add(Math.round(box.top));
          if (box.left < bounds.left - 1 || box.right > bounds.right + 1 || box.top < bounds.top - 1 || box.bottom > bounds.bottom + 1) clipped.push(text[i]);
        }
      }
    }
    const badStyles = Array.from(root.querySelectorAll<HTMLElement>('*')).filter((el) => {
      const s = getComputedStyle(el);
      const clamped = ['line-clamp', '-webkit-line-clamp'].some((name) => {
        const value = s.getPropertyValue(name);
        return value !== '' && value !== 'none';
      });
      return s.textOverflow === 'ellipsis' || s.whiteSpace === 'nowrap' || clamped;
    }).map((el) => el.tagName);
    const overflow: string[] = [];
    for (let el: Element | null = root; el; el = el.parentElement) {
      if (el.scrollWidth > el.clientWidth + 1) overflow.push(`${el.tagName}:${el.scrollWidth}/${el.clientWidth}`);
    }
    return { rows: rows.size, recipientRows: recipientRows.size, clipped, badStyles, overflow,
      pageOverflow: document.documentElement.scrollWidth > innerWidth + 1, width: bounds.width };
  }, to);
}

async function fit(receipt: Locator, to: string) {
  const measured = await measureReceipt(receipt, to);
  expect(measured.clipped, 'each visible character fits the receipt bounds').toEqual([]);
  expect(measured.badStyles, 'no ellipsis/nowrap/line clamp').toEqual([]);
  expect(measured.overflow, 'receipt and ancestors do not scroll horizontally').toEqual([]);
  expect(measured.pageOverflow).toBe(false);
  expect(measured.rows).toBeGreaterThan(1);
  if (to === LONG) expect(measured.recipientRows, 'the full long recipient wraps too').toBeGreaterThan(1);
  return measured;
}

async function picture(composer: Locator, name: string) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await composer.screenshot({ path: path.join(SHOTS, `${name}.png`) });
}

/** Top and bottom edges in CSS px; attached-only, so a clipped or empty region still measures. */
const edges = (el: Locator) => el.evaluate((node) => {
  const b = node.getBoundingClientRect();
  return { top: b.top, bottom: b.bottom, height: b.height };
});

/** The receipt's drawn lines, top to bottom, and the word count of the last one. */
async function receiptLines(receipt: Locator) {
  return receipt.locator('[data-note]').evaluate((note) => {
    const rows = new Map<number, string>();
    const walker = document.createTreeWalker(note, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const text = node.textContent ?? '';
      for (let i = 0; i < text.length; i++) {
        const range = document.createRange();
        range.setStart(node, i); range.setEnd(node, i + 1);
        const box = Array.from(range.getClientRects()).find((r) => r.width > 0);
        if (box) rows.set(Math.round(box.top), (rows.get(Math.round(box.top)) ?? '') + text[i]);
      }
    }
    const lines = [...rows.entries()].sort((a, b) => a[0] - b[0]).map(([, t]) => t.trim());
    return { lines, lastWords: (lines.at(-1) ?? '').split(/\s+/).filter(Boolean).length };
  });
}

for (const theme of ['dark', 'light'] as const) {
  test(`isolated receipt fit checker: clean / ellipsis / nowrap / restored, ${theme}, 320`, async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 844 });
    await page.addInitScript((t) => localStorage.setItem('temper_theme', t), theme);
    const { composer } = await open(page, true, [receipts.pending]);
    await composer.getByRole('textbox', { name: 'Message' }).fill('Fictional measurement message.');
    await composer.getByRole('button', { name: 'Send message' }).click();
    await expect(result(page)).toHaveText(ACCEPTED);
    await fit(result(page), 'maker');
    const text = result(page).locator('[data-note] > div');
    await text.evaluate((el) => { (el as HTMLElement).style.textOverflow = 'ellipsis'; });
    expect((await measureReceipt(result(page), 'maker')).badStyles).toContain('DIV');
    await text.evaluate((el) => { (el as HTMLElement).style.removeProperty('text-overflow'); (el as HTMLElement).style.whiteSpace = 'nowrap'; });
    const bad = await measureReceipt(result(page), 'maker');
    expect(bad.badStyles).toContain('DIV');
    expect(bad.clipped.length).toBeGreaterThan(0);
    await text.evaluate((el) => { (el as HTMLElement).style.removeProperty('white-space'); });
    await fit(result(page), 'maker');
  });

  test(`isolated ready receipt stage on visible phone list, ${theme}, 320`, async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 844 });
    await page.addInitScript((t) => localStorage.setItem('temper_theme', t), theme);
    const { state, composer } = await open(page, true, [receipts.pending]);
    await watch(page);
    state.ready = true;
    await composer.getByRole('textbox', { name: 'Message' }).fill('Fictional ready message.');
    await composer.getByRole('button', { name: 'Send message' }).click();
    await expect(result(page)).toHaveText(ACCEPTED);
    const chip = page.getByTestId('glance-list').getByTestId('glance-chip');
    await expect(chip).toBeVisible();
    await expect(chip).toContainText('Ready');
    expect((await probe(page)).same).toBe(true);
    expect((await probe(page)).updates).toEqual([ACCEPTED]);
  });

  for (const width of [390, 320]) {
    test(`FLOW acceptance and announcement journey, ${theme}, ${width}`, async ({ page }) => {
      test.setTimeout(120_000);
      await page.setViewportSize({ width, height: 844 });
      await page.addInitScript((t) => localStorage.setItem('temper_theme', t), theme);
      const first = latch();
      const second = latch();
      const last = latch();
      const { state, sent, writes, composer } = await open(page, true, [
        { until: first.until, then: receipts.pending }, { until: second.until, then: receipts.repeated },
        receipts.held, receipts.held, receipts.refused, 'no reply', receipts.repeated,
        { until: last.until, then: { ...receipts.pending, body: { ...receipts.pending.body, to: LONG } } },
      ]);
      const receipt = result(page);
      const box = composer.getByRole('textbox', { name: 'Message' });
      const send = composer.getByRole('button', { name: 'Send message' });
      await expect(receipt).toHaveAttribute('aria-live', 'polite');
      await expect(receipt).toHaveAttribute('aria-atomic', 'true');
      expect(await receipt.evaluate((node) => getComputedStyle(node).display)).not.toBe('none');
      await watch(page);

      await test.step('working success: whole sentence, persistent region and focus; one update', async () => {
        await box.fill('Fictional first message.'); await send.click();
        await expect.poll(() => sent.messages.length).toBe(1);
        await box.focus(); first.release();
        await expect(receipt).toHaveText(ACCEPTED); await expect(box).toBeFocused();
        expect(await probe(page)).toEqual({ same: true, updates: [ACCEPTED], atomic: 'true', polite: 'polite', nested: 0 });
        await fit(receipt, 'maker');
        await expectAxeClean(page); await expectTargets(page);
        await picture(composer, `${theme}-${width}-accepted`);
      });

      await test.step('ready, repeated identical success: same node, one new update, unchanged rerenders silent', async () => {
        state.ready = true;
        await box.fill('Fictional second message.'); await send.click();
        await expect.poll(() => sent.messages.length).toBe(2);
        await box.focus(); second.release();
        await expect(receipt).toHaveText(ACCEPTED); await expect(box).toHaveValue('');
        await expect(page.getByTestId('glance-list').getByTestId('glance-chip')).toContainText('Ready');
        await expect(box).toBeFocused();
        expect((await probe(page)).updates).toEqual([ACCEPTED, ACCEPTED]);
        expect((await probe(page)).same).toBe(true);
        await box.fill('A new draft, same result seq.');
        await composer.getByLabel('To', { exact: true }).selectOption('maker');
        expect((await probe(page)).updates).toEqual([ACCEPTED, ACCEPTED]);
      });

      await test.step('held non-paused and paused: existing sentences, never acceptance', async () => {
        await send.click(); await expect(receipt).toHaveText(HELD);
        state.paused = true;
        await box.fill('Fictional held message.'); await send.click(); await expect(receipt).toHaveText(PAUSED);
        await expect(receipt).not.toContainText('Temper accepted');
      });

      await test.step('refusal and no answer: text retained, retry is the same request counted once', async () => {
        state.paused = false;
        await box.fill('Fictional refused message.'); await send.click();
        await expect(receipt).toHaveText('Temper refused: Fictional member has ended. Your text is kept.');
        await expect(box).toHaveValue('Fictional refused message.');
        await send.click(); await expect(receipt).toContainText("Temper didn't answer. Trying again is safe: the same request counts once.");
        await expect(receipt).not.toContainText('Temper accepted'); await expect(box).toHaveValue('Fictional refused message.');
        await composer.getByRole('button', { name: 'Try again' }).click();
        await expect(receipt).toHaveText(ACCEPTED); await expect(box).toHaveValue('');
        expect(sent.messages[6]).toEqual(sent.messages[5]);
        expect(sent.messages[5].request_id).not.toBe(sent.messages[4].request_id);
      });

      await test.step('long/metacharacter recipient is literal, fully wrapped, not markup; same region and focus', async () => {
        const before = (await probe(page)).updates.length;
        await box.fill('Fictional long-recipient message.'); await send.click();
        await expect.poll(() => sent.messages.length).toBe(8);
        await box.focus(); last.release();
        const whole = `Temper accepted your message for ${LONG}.`;
        await expect(receipt).toHaveText(whole); await expect(box).toBeFocused();
        await expect(receipt.locator('img, [onerror]')).toHaveCount(0);
        expect((await probe(page)).same).toBe(true);
        expect((await probe(page)).updates.slice(before)).toEqual([whole]);
        const measured = await fit(receipt, LONG);
        await expectAxeClean(page); await expectTargets(page);
        await picture(composer, `${theme}-${width}-long-recipient`);
        await test.info().attach('receipt-measurements', { body: Buffer.from(JSON.stringify({ theme, width, probe: await probe(page), measured, requests: sent.messages }, null, 2)), contentType: 'application/json' });
      });
      expect(sent.messages).toHaveLength(8);
      expect(writes).toEqual(Array(8).fill(`/api/team/runs/${ID}/messages`));
      expect(sent.answers.concat(sent.cancels, sent.checks, sent.trials)).toEqual([]);
      expect(sent.messages.every((m) => Object.keys(m).sort().join(',') === 'body,request_id,to' && m.to === 'maker')).toBe(true);
      // Node API requests are not page.route intercepted: these reach only the static 503 server.
      expect((await page.request.get('/api/team/status')).status()).toBe(503);
      expect((await page.request.get('/ws/fictional-proof')).status()).toBe(503);
    });
  }

  test(`legacy receipt counters remain unchanged, ${theme}, 320`, async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 844 });
    await page.addInitScript((t) => localStorage.setItem('temper_theme', t), theme);
    const { state, composer, sent } = await open(page, false, [receipts.pending, receipts.repeated, receipts.held, receipts.held, receipts.refused, 'no reply', receipts.repeated]);
    const receipt = result(page);
    const box = composer.getByRole('textbox', { name: 'Message' });
    const send = composer.getByRole('button', { name: 'Send message' });
    expect(await receipt.getAttribute('aria-atomic')).toBeNull();
    for (const expected of [LEGACY, LEGACY, HELD]) {
      await box.fill('Fictional legacy message.'); await send.click(); await expect(receipt).toHaveText(expected);
      await expect(box).toHaveValue('');
    }
    state.paused = true;
    await box.fill('Fictional legacy held message.'); await send.click(); await expect(receipt).toHaveText(PAUSED);
    await box.fill('Fictional legacy refused message.'); await send.click();
    await expect(receipt).toHaveText('Temper refused: Fictional member has ended. Your text is kept.');
    await send.click(); await expect(receipt).toContainText("Temper didn't answer.");
    await expect(receipt).not.toContainText('Temper accepted');
    await composer.getByRole('button', { name: 'Try again' }).click(); await expect(receipt).toHaveText(LEGACY);
    expect(sent.messages[6]).toEqual(sent.messages[5]);
    await expectAxeClean(page); await expectTargets(page);
  });

  // Design S1/C1 on 8856ba92: before any result the glance region stays a polite atomic live
  // region but takes no room, so the box -> footer gap is the section's one 12 px gap-3 (24 px
  // when the empty region was a flex item). The receipt keeps 12 px either side of it, and at
  // 390 its last line is not a lone word.
  for (const width of [320, 390, 1440]) {
    test(`no-result composer gap, persistent region and receipt lines, ${theme}, ${width}`, async ({ page }) => {
      await page.setViewportSize({ width, height: width === 1440 ? 900 : 844 });
      await page.addInitScript((t) => localStorage.setItem('temper_theme', t), theme);
      const answer = latch();
      const { sent, composer } = await open(page, true, [{ until: answer.until, then: receipts.pending }]);
      const receipt = result(page);
      const box = composer.getByRole('textbox', { name: 'Message' });
      const send = composer.getByRole('button', { name: 'Send message' });
      const footer = send.locator('..');

      const live = await receipt.evaluate((node) => {
        const s = getComputedStyle(node);
        return { polite: node.getAttribute('aria-live'), atomic: node.getAttribute('aria-atomic'), ariaHidden: node.getAttribute('aria-hidden'),
          display: s.display, visibility: s.visibility, inert: node.closest('[inert]') !== null, text: node.textContent };
      });
      const { display, ...exposed } = live;
      expect(display, 'region never display:none').not.toBe('none');
      expect(exposed, 'region present before any result: polite, atomic, exposed, empty').toEqual({ polite: 'polite', atomic: 'true',
        ariaHidden: null, visibility: 'visible', inert: false, text: '' });
      const empty = { box: await edges(box), region: await edges(receipt), footer: await edges(footer) };
      const gap = Math.round((empty.footer.top - empty.box.bottom) * 100) / 100;
      expect.soft(gap, 'no-result box -> footer gap (px)').toBeCloseTo(12, 1);
      await expectAxeClean(page);
      await picture(composer, `${theme}-${width}-no-result`);

      await watch(page);
      await box.fill('Fictional gap message.'); await send.click();
      await expect.poll(() => sent.messages.length).toBe(1);
      await box.focus(); answer.release();
      await expect(receipt).toHaveText(ACCEPTED); await expect(box).toBeFocused();
      expect(await probe(page), 'same region node, one whole-sentence update').toEqual({ same: true, updates: [ACCEPTED], atomic: 'true', polite: 'polite', nested: 0 });
      const shown = { box: await edges(box), region: await edges(receipt), footer: await edges(footer) };
      expect(shown.region.top - shown.box.bottom, 'box -> receipt gap (px)').toBeCloseTo(12, 1);
      expect(shown.footer.top - shown.region.bottom, 'receipt -> footer gap (px)').toBeCloseTo(12, 1);
      const lines = await receiptLines(receipt);
      if (width === 390) expect.soft(lines.lastWords, `last receipt line at 390: ${JSON.stringify(lines.lines)}`).toBeGreaterThanOrEqual(2);
      if (width < 1440) await fit(receipt, 'maker');
      await picture(composer, `${theme}-${width}-receipt`);
      await test.info().attach('composer-gap-measurements', { body: Buffer.from(JSON.stringify({ theme, width, live, empty, gap, shown, lines }, null, 2)), contentType: 'application/json' });
    });
  }
}
