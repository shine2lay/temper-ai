/**
 * Where a team run stands, at every width (owner's order bp-7ca34155, 2026-10-08),
 * in Design's words and to Design's bars (rm-91ea14d3). Mock-only: every
 * /api/team read is a fixture the routes really answered, so this runs with no
 * Temper behind it (AGENTS.md rule 15).
 *
 * The main journey is journey-run-answered, the live Project's shape after its
 * Continue: round 1 decided keep going, round 2 just opened with one verdict in,
 * Temper's guard in record mode. Then one test per other state Design checks:
 * needs-you, ended, no decision yet, a refused done, a long summary. Every one
 * checks the order (needs-you or outcome, the round box, then the history),
 * the words, and the bars: axe clean, targets 24 px or more, text 12 px or
 * more, chip borders 3:1, a visible focus, nothing clipped and nothing that
 * scrolls sideways. With TEAM_SHOTS set, each state is shot in full and, on a
 * phone, as its first screen.
 */
import { expect, test, type Locator, type Page } from '@playwright/test';
import { card as needsYouCard, expectAxeClean, expectTargets, fixture, RUN_ID, serveTeam, SHOTS, shoot } from './team-helpers';

type Fixture = ReturnType<typeof fixture>;
type Body = {
  trial: { leader: string };
  reviews: Array<{ round: number; summary: string | null; refusal: string | null; views: Record<string, { verdict: string }> }>;
};

const body = (f: Fixture) => f.body as Body;
const withBody = (f: Fixture, change: (b: Body) => Body = (b) => b): Fixture => ({
  ...f,
  body: { ...change(structuredClone(body(f))), execution_id: RUN_ID },
});

const ANSWERED = fixture('journey-run-answered');
const LEADER = body(ANSWERED).trial.leader;
const ROUND1 = body(ANSWERED).reviews[0];

/**
 * The refused done as the latest decided review: run-refused-done cut at the moment
 * just after the refusal, so the page shows one consistent moment. The review is the
 * real serializer's, untouched; the history stops after Temper's refusal notices,
 * before round 2's review opens (its review, verdicts and pause are left out with
 * it), and the run is still going, with 1 round without done.
 */
const REFUSED = withBody(fixture('run-refused-done'), (b) => {
  const refusedAt = b.timeline.entries.findIndex((e) => e.event_type === 'decision: done_refused');
  const round2At = b.timeline.entries.findIndex((e) => e.event_type === 'review round 2');
  if (refusedAt < 0 || round2At < refusedAt) throw new Error('run-refused-done: refusal, then round 2, expected');
  return {
    ...b,
    run_status: 'running',
    state: 'running',
    open_waits: [],
    round: { ...b.round, current: 1, keep_goings: 1 },
    reviews: [b.reviews[0]],
    timeline: { ...b.timeline, entries: b.timeline.entries.slice(0, round2At) },
  };
});
const REFUSAL = body(REFUSED).reviews[0].refusal!;

/** A long summary: round 1's own words, then more of them, so it runs past 3 lines. */
const LONG_TAIL =
  'Last paragraph: the reviewers still disagree on the heading, so the next round keeps both versions side by side.';
const LONG = withBody(ANSWERED, (b) => {
  const [r1, ...rest] = b.reviews;
  const more = [
    'What changed: the form keeps its fields when a check fails, and the error names the field.',
    'What the reviewers asked: maker wants shorter labels; checker wants the empty state to say what to do next.',
    LONG_TAIL,
  ];
  return { ...b, reviews: [{ ...r1, summary: [r1.summary, ...more].join('\n\n') }, ...rest] };
});

const WIDTHS = [390, 1024, 1440] as const;
const PHONE = 390;

/** Opens the run view on `run`; returns every request it sent other than a read. */
async function openRun(page: Page, run: Fixture): Promise<string[]> {
  const writes: string[] = [];
  page.on('request', (request) => {
    if (request.method() !== 'GET' && new URL(request.url()).pathname.startsWith('/api/')) {
      writes.push(`${request.method()} ${request.url()}`);
    }
  });
  await serveTeam(page, { status: fixture('status-record'), run: [run] });
  await page.goto(`/app/team/runs/${RUN_ID}`);
  await expect(page.getByRole('heading', { level: 1 })).not.toHaveText('Team run');
  return writes;
}

const roundCard = (page: Page) => page.locator('[data-round-card="card"]');
const timeline = (page: Page) => page.getByRole('region', { name: /Timeline/ });

/** `upper` ends before `lower` starts, on the page. */
async function expectAbove(upper: Locator, lower: Locator, what: string) {
  const [a, b] = [await upper.boundingBox(), await lower.boundingBox()];
  expect(a && b && a.y + a.height <= b.y + 1, what).toBe(true);
}

/** Design's bars (rm-91ea14d3) on what this change draws, plus axe and targets on the whole page. */
async function expectBars(page: Page) {
  await expectAxeClean(page);
  await expectTargets(page);
  const report = await page.evaluate(() => {
    const ctx = document.createElement('canvas').getContext('2d', { willReadFrequently: true })!;
    const rgba = (color: string): number[] => {
      ctx.clearRect(0, 0, 1, 1);
      ctx.fillStyle = '#000';
      ctx.fillStyle = color;
      ctx.fillRect(0, 0, 1, 1);
      const d = ctx.getImageData(0, 0, 1, 1).data;
      return [d[0], d[1], d[2], d[3] / 255];
    };
    const over = (top: number[], base: number[]) => base.map((v, i) => (i < 3 ? top[i] * top[3] + v * (1 - top[3]) : 1));
    const bgOf = (el: Element | null): number[] => {
      const layers: number[][] = [];
      for (let e = el; e; e = e.parentElement) {
        const c = rgba(getComputedStyle(e).backgroundColor);
        if (c[3] > 0) layers.push(c);
        if (c[3] >= 1) break;
      }
      return layers.reverse().reduce((base, layer) => over(layer, base), [255, 255, 255, 1]);
    };
    const lum = (c: number[]) => {
      const f = (v: number) => ((v /= 255) <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
      return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
    };
    const ratio = (a: number[], b: number[]) => {
      const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
      return (hi + 0.05) / (lo + 0.05);
    };
    const shown = (el: Element) => (el as HTMLElement).getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden';
    const label = (el: Element) => `${el.tagName.toLowerCase()} "${(el.textContent ?? '').trim().replace(/\s+/g, ' ').slice(0, 40)}"`;

    const out = { small: [] as string[], borders: [] as string[], clipped: [] as string[], rail: [] as string[], sideways: [] as string[] };
    // The round box, the guard banner (its words and its toggle) and the sidebar.
    const scopes = [
      ...Array.from(document.querySelectorAll('[data-round-card], aside')),
      ...Array.from(document.querySelectorAll('[data-guard-mode]')).map((p) => p.parentElement ?? p),
    ];
    for (const scope of scopes) {
      for (const el of [scope, ...Array.from(scope.querySelectorAll('*'))]) {
        if (!shown(el) || el.closest('svg')) continue;
        const text = Array.from(el.childNodes).some((n) => n.nodeType === Node.TEXT_NODE && n.textContent!.trim() !== '');
        const size = parseFloat(getComputedStyle(el).fontSize);
        if (text && size < 12) out.small.push(`${label(el)} ${size}px`);
      }
    }
    for (const card of Array.from(document.querySelectorAll('[data-round-card]'))) {
      const box = card.getBoundingClientRect();
      if (card.scrollWidth > card.clientWidth + 1) out.clipped.push(`round box scrolls ${card.scrollWidth}>${card.clientWidth}`);
      for (const el of Array.from(card.querySelectorAll('*'))) {
        if (!shown(el)) continue;
        const r = el.getBoundingClientRect();
        if (r.right > box.right + 1 || r.left < box.left - 1) out.clipped.push(`${label(el)} outside the round box`);
      }
      // Chips: the reviewer's name and verdict, bordered; the border against what is around it.
      for (const chip of Array.from(card.querySelectorAll('span.whitespace-nowrap'))) {
        const style = getComputedStyle(chip);
        if (style.borderTopStyle === 'none' || parseFloat(style.borderTopWidth) === 0) continue;
        // What is around the chip: past a backing of the chip's own size.
        let outside = chip.parentElement;
        while (outside?.hasAttribute('data-chip-backing')) outside = outside.parentElement;
        const around = bgOf(outside);
        const border = over(rgba(style.borderTopColor), around);
        const r = ratio(border, around);
        if (r < 3) out.borders.push(`${label(chip)} border ${r.toFixed(2)}:1`);
      }
    }
    for (const el of Array.from(document.querySelectorAll('aside a[href], aside button'))) {
      const r = el.getBoundingClientRect();
      if (r.width < 24 || r.height < 24) out.rail.push(`${label(el)} ${r.width.toFixed(0)}x${r.height.toFixed(0)}`);
    }
    const main = document.querySelector('main');
    if (document.documentElement.scrollWidth > window.innerWidth) out.sideways.push(`page ${document.documentElement.scrollWidth}>${window.innerWidth}`);
    if (main && main.scrollWidth > main.clientWidth + 1) out.sideways.push(`main ${main.scrollWidth}>${main.clientWidth}`);
    return out;
  });
  expect(report.small, 'text under 12 px').toEqual([]);
  expect(report.borders, 'chip borders under 3:1').toEqual([]);
  expect(report.clipped, 'clipped in the round box').toEqual([]);
  expect(report.rail, 'sidebar targets under 24 px').toEqual([]);
  expect(report.sideways, 'sideways scroll').toEqual([]);
}

/** Reached by the keyboard, the control shows the app's 2 px focus outline. */
async function expectFocusRing(page: Page, control: Locator, what: string) {
  await control.focus();
  await page.keyboard.press('Shift+Tab');
  await page.keyboard.press('Tab');
  await expect(control).toBeFocused();
  const ring = await control.evaluate((el) => {
    const style = getComputedStyle(el);
    return el.matches(':focus-visible') && style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) >= 2;
  });
  expect(ring, `${what}: visible focus`).toBe(true);
  await control.blur();
}

/** The full page, and on a phone the first screen too. */
async function shots(page: Page, name: string, width: number, firstScreen = width === PHONE) {
  await shoot(page, name);
  if (SHOTS && firstScreen) await page.screenshot({ path: `${SHOTS}/${name}-first-screen.png` });
}

for (const theme of ['light', 'dark'] as const) {
  for (const width of WIDTHS) {
    test.describe(`Team run status, ${theme}, ${width} px`, () => {
      test.use({ viewport: { width, height: width === PHONE ? 844 : width === 1024 ? 768 : 900 } });
      const tag = `${theme}-${width}`;
      const firstScreen = width === PHONE ? 844 : width === 1024 ? 768 : 900;

      test.beforeEach(async ({ page }) => {
        await page.addInitScript((t) => {
          localStorage.setItem('temper_theme', t);
          // A wide screen's saved choice: open. A phone starts as the rail anyway.
          localStorage.setItem('temper-sidebar-collapsed', 'false');
        }, theme);
      });

      test('running: the round box above the history, the decided review, then the open one', async ({ page }) => {
        const writes = await openRun(page, withBody(ANSWERED));

        // One round box, in the main column, above the history; on a phone, on the first screen.
        await expect(roundCard(page)).toHaveCount(1);
        const box = roundCard(page);
        await expect(box.getByRole('heading', { name: 'Round 2' })).toBeVisible();
        await expectAbove(box, timeline(page), 'round box above the history');
        expect((await box.boundingBox())!.y).toBeLessThan(firstScreen);

        // The decided review: the round named, the decision, every reviewer's verdict in words, the summary.
        const decided = box.locator('[data-review="decided"]');
        await expect(decided).toContainText('Latest decided review');
        await expect(decided.locator('[data-review-decision]')).toHaveText(`Round 1 · ${LEADER} decided: keep going`);
        for (const [member, view] of Object.entries(ROUND1.views)) {
          await expect(decided.getByText(`${member}: ${view.verdict.replace(/_/g, ' ')}`)).toBeVisible();
        }
        await expect(decided.locator('[data-review-summary]')).toContainText(`${LEADER}'s summary`);
        await expect(decided.locator('[data-review-summary]')).toContainText(ROUND1.summary!.slice(0, 40));

        // The open review on its own line, below; it says nothing it doesn't know.
        const open = box.locator('[data-review="open"]');
        await expect(open).toContainText('Round 2 review open · 1 verdict in');
        await expect(open.getByText('checker: satisfied')).toBeVisible();
        await expect(box).not.toContainText('%');
        await expect(box).not.toContainText(/\bviews?\b/);

        // The sidebar: the rail on a phone (named icons with tooltips), the wide-screen choice elsewhere.
        const sidebar = page.locator('aside');
        if (width === PHONE) {
          expect((await sidebar.boundingBox())!.width).toBeLessThanOrEqual(56);
          for (const name of ['Workflows', 'Team']) {
            await expect(sidebar.getByRole('link', { name })).toHaveAttribute('title', name);
          }
        } else {
          expect((await sidebar.boundingBox())!.width).toBe(200);
        }

        // The guard banner: whole on wide screens; on a phone its first sentence, then Show details.
        const banner = page.locator('[data-guard-mode="record"]');
        await expect(banner.locator('b').first()).toHaveText("Answers, messages and stops aren't limited to you yet.");
        const rest = banner.getByText(/Temper records who did each one/);
        await expect(page.getByRole('button', { name: 'Hide this notice for this session' })).toBeVisible();
        if (width === PHONE) {
          await expect(rest).toBeHidden();
          const more = page.getByRole('button', { name: 'Show details' });
          await expect(more).toHaveAttribute('aria-expanded', 'false');
          await expectFocusRing(page, more, 'Show details');
          await expectBars(page);
          await shots(page, `status-${tag}-running`, width);

          await more.click();
          await expect(rest).toBeVisible();
          await expect(page.getByRole('button', { name: 'Hide details' })).toHaveAttribute('aria-expanded', 'true');
          await expectBars(page);
          await shots(page, `status-${tag}-guard-details`, width);
          await page.getByRole('button', { name: 'Hide details' }).click();
          await expect(rest).toBeHidden();

          // The sidebar opened on a phone: a drawer over the page, which stays where it was
          // (Design rm-a79c1512, fix B).
          const main = page.locator('main');
          const before = await main.boundingBox();
          const expand = page.getByRole('button', { name: 'Expand sidebar' });
          await expectFocusRing(page, expand, 'Expand sidebar');
          await expand.click();
          // The sidebar slides open: wait for it to finish.
          await expect.poll(async () => (await sidebar.boundingBox())!.width).toBe(200);
          const drawer = page.getByRole('dialog', { name: 'Main menu' });
          await expect(drawer.getByRole('link', { name: 'Workflows' })).toContainText('Workflows');
          await expect(drawer.getByRole('link', { name: 'Workflows' })).toBeFocused();
          expect(await main.boundingBox(), 'the page is not squeezed by the drawer').toEqual(before);
          await expectBars(page);
          await shots(page, `status-${tag}-sidebar-open`, width);
          // Esc closes it, focus back on the toggle.
          await page.keyboard.press('Escape');
          await expect(drawer).toHaveCount(0);
          await expect(expand).toBeFocused();
          await expect.poll(async () => (await sidebar.boundingBox())!.width).toBeLessThanOrEqual(56);
          // The owner's path: open the menu, tap Team; the Team page opens, the menu closed.
          await expand.click();
          await drawer.getByRole('link', { name: 'Team' }).click();
          await expect(page).toHaveURL(/\/team$/);
          await expect(drawer).toHaveCount(0);
          await expect.poll(async () => (await sidebar.boundingBox())!.width).toBeLessThanOrEqual(56);
          expect(await main.boundingBox(), 'the Team page at its full width').toEqual(before);
          await page.waitForLoadState('networkidle');
          await shots(page, `status-${tag}-menu-link-closed`, width);
        } else {
          await expect(rest).toBeVisible();
          await expect(page.getByRole('button', { name: 'Show details' })).toHaveCount(0);
          await expectBars(page);
          await shots(page, `status-${tag}-running`, width);
        }
        // Read-only: the page only read Temper.
        expect(writes).toEqual([]);
      });

      test('needs you: the round sits inside the needs-you card', async ({ page }) => {
        const run = withBody(fixture('journey-run-paused'));
        const writes = await openRun(page, run);
        await expect(roundCard(page)).toHaveCount(0);
        const inWait = needsYouCard(page).locator('[data-round-card="in-wait"]');
        await expect(inWait).toHaveCount(1);
        await expect(inWait.locator('[data-review-decision]')).toHaveText(`Round 1 · ${body(run).trial.leader} decided: keep going`);
        await expectAbove(needsYouCard(page), timeline(page), 'needs-you card above the history');
        // The owner answers on that decision, so it comes before the choices (Design rm-a79c1512, fix A).
        const answers = needsYouCard(page).getByRole('group', { name: 'Your answer' });
        if (width < 1280) {
          // One column: the question, then the round and its decision, then the answers.
          await expectAbove(needsYouCard(page).getByRole('heading', { level: 2 }).first(), inWait, 'question above the round');
          await expectAbove(inWait, answers, 'round and decision above the answers');
        } else {
          // Two columns: the round under the question on the left, the answers on the right.
          const [round, choices] = [await inWait.boundingBox(), await answers.boundingBox()];
          expect(round!.x + round!.width <= choices!.x, 'round on the left, answers on the right').toBe(true);
        }
        // In the page's order too: a screen reader and the keyboard meet the decision before the answers.
        const roundFirst = await needsYouCard(page).evaluate((card) => {
          const round = card.querySelector('[data-round-card="in-wait"]');
          const legend = Array.from(card.querySelectorAll('legend')).find((l) => /your answer/i.test(l.textContent ?? ''));
          return !!round && !!legend && Boolean(round.compareDocumentPosition(legend) & Node.DOCUMENT_POSITION_FOLLOWING);
        });
        expect(roundFirst, 'round before the answers in the page order').toBe(true);
        await expectBars(page);
        await shots(page, `status-${tag}-needs-you`, width, width !== 1440);
        expect(writes).toEqual([]);
      });

      test('ended: the outcome, then the round box, then the history', async ({ page }) => {
        const run = withBody(fixture('run-done'));
        const writes = await openRun(page, run);
        const box = roundCard(page);
        await expect(box).toHaveCount(1);
        await expectAbove(page.locator('[data-outcome]'), box, 'outcome above the round box');
        await expectAbove(box, timeline(page), 'round box above the history');
        await expect(box.locator('[data-review-decision]')).toHaveText(`Round 2 · ${body(run).trial.leader} decided: done`);
        // The outcome card shows that review's summary in full; the round box doesn't repeat it.
        await expect(box.locator('[data-review-summary]')).toHaveCount(0);
        await expectBars(page);
        await shots(page, `status-${tag}-ended`, width);
        expect(writes).toEqual([]);
      });

      test('no decision yet: said so, never an empty box', async ({ page }) => {
        const writes = await openRun(page, withBody(fixture('run-running')));
        const box = roundCard(page);
        await expect(box.locator('[data-review="none"]')).toHaveText('No decision yet');
        await expect(box.locator('[data-review="decided"]')).toHaveCount(0);
        await expect(box.locator('[data-review="open"]')).toContainText('Round 1 review open · no verdicts yet');
        await expectAbove(box, timeline(page), 'round box above the history');
        await expectBars(page);
        await shots(page, `status-${tag}-no-decision`, width);
        expect(writes).toEqual([]);
      });

      test("a refused done: the leader said done, Temper's refusal quoted", async ({ page }) => {
        const writes = await openRun(page, REFUSED);
        const decided = page.locator('[data-round-card] [data-review="decided"]');
        await expect(decided.locator('[data-review-decision]')).toHaveText(`Round 1 · ${body(REFUSED).trial.leader} said done; refused`);
        await expect(decided.locator('[data-quote="engine"] figcaption')).toHaveText('Temper said:');
        await expect(decided.locator('[data-quote="engine"] blockquote')).toHaveText(REFUSAL);
        await expect(decided).not.toContainText('decided:');
        await expectBars(page);
        await shots(page, `status-${tag}-refused-done`, width);
        expect(writes).toEqual([]);
      });

      test('a long summary: 3 lines, then Show all and Show less', async ({ page }) => {
        const writes = await openRun(page, LONG);
        const summary = roundCard(page).locator('[data-review-summary]');
        await expect(summary).toContainText(`${LEADER}'s summary`);
        const all = summary.getByRole('button', { name: 'Show all' });
        await expect(all).toHaveAttribute('aria-expanded', 'false');
        // Cut after 3 lines: the last paragraph starts below the end of the shown text.
        const cut = await summary.evaluate((el, tail) => {
          const clamp = el.querySelector('.line-clamp-3');
          const last = Array.from(el.querySelectorAll('p')).find((p) => p.textContent?.includes(tail));
          return !!clamp && !!last && last.getBoundingClientRect().top >= clamp.getBoundingClientRect().bottom - 1;
        }, LONG_TAIL);
        expect(cut, 'summary cut after 3 lines').toBe(true);
        await expectFocusRing(page, all, 'Show all');
        await expectBars(page);
        await shots(page, `status-${tag}-summary-short`, width);

        await all.click();
        const less = summary.getByRole('button', { name: 'Show less' });
        await expect(less).toHaveAttribute('aria-expanded', 'true');
        await expect(summary.getByText(LONG_TAIL)).toBeVisible();
        await expectBars(page);
        await shots(page, `status-${tag}-summary-all`, width);
        expect(writes).toEqual([]);
      });
    });
  }
}
