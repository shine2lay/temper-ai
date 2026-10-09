/**
 * Where a team run stands, on every screen (owner's order bp-7ca34155, 2026-10-08):
 *   1. on a phone the sidebar starts as the icon rail and the guard banner is
 *      one sentence with "Show details";
 *   2. the round card shows the latest DECIDED review, and a newer review still
 *      going on a line of its own (it never takes the decided one's place);
 *   3. that review's summary and every member's verdict, as Temper has them.
 * Words are Design's (rm-91ea14d3): "verdicts", "Round N · <leader> decided",
 * "No decision yet", "<leader>'s summary".
 *
 * The runs are fixtures the routes really answered (journey-run-answered: round 1
 * decided keep going, round 2 just opened with one verdict in, as the live Project
 * read after its Continue on 2026-10-08).
 */
import type { ReactNode } from 'react';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AppSidebar } from '@/components/layout/AppSidebar';
import { TeamGuardBanner } from '@/components/team/TeamGuardBanner';
import { OutcomeCard } from '@/components/team/run/OutcomeCard';
import { RoundCard } from '@/components/team/run/RoundCard';
import { openReviewWords, roundReviews } from '@/lib/teamReview';
import type { TeamReview, TeamRun } from '@/types/team';

import runAnswered from '../../e2e/fixtures/team/journey-run-answered.json';
import runDone from '../../e2e/fixtures/team/run-done.json';
import runInterrupted from '../../e2e/fixtures/team/run-interrupted.json';
import runRefusedDone from '../../e2e/fixtures/team/run-refused-done.json';
import runRunning from '../../e2e/fixtures/team/run-running.json';

const realMatchMedia = window.matchMedia;

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.matchMedia = realMatchMedia;
  localStorage.clear();
  sessionStorage.clear();
});

/** A phone-width screen: only the app's narrow query matches. */
function onPhone() {
  window.matchMedia = ((query: string) => ({
    matches: query === '(max-width: 767px)',
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as typeof window.matchMedia;
}

function show(ui: ReactNode, at = '/team') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[at]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

const flat = (text: string | null | undefined) => (text ?? '').replace(/\s+/g, ' ').trim();
const ANSWERED = runAnswered.body as unknown as TeamRun;

describe('the round card: the latest decided review, and the next one on its own line', () => {
  it('shows round 1 decided with its verdicts and summary, and round 2 open with its one verdict', () => {
    const [round1, round2] = ANSWERED.reviews;
    // The fixture is the live case: round 2 opened the second round 1 was decided.
    expect([round1.state, round1.decision, round2.state, round2.decision]).toEqual(['decided', 'keep_going', 'open', null]);
    expect(round1.summary).toBeTruthy();

    show(<RoundCard run={ANSWERED} />);
    const card = screen.getByRole('region', { name: 'Round 2' });

    const decided = card.querySelector<HTMLElement>('[data-review="decided"]');
    const open = card.querySelector<HTMLElement>('[data-review="open"]');
    expect(decided).not.toBeNull();
    expect(open).not.toBeNull();
    // The decided review comes first; the open one never takes its place.
    expect(decided!.compareDocumentPosition(open!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    // Round 1: its commit and files, every member's verdict (both asked for changes), the decision, the summary.
    expect(flat(decided!.textContent)).toContain(
      `Latest decided review · commit ${round1.commit!.slice(0, 7)} · ${round1.files_count} files`,
    );
    for (const [member, view] of Object.entries(round1.views)) {
      expect(within(decided!).getByText(`${member}: ${view.verdict.replace(/_/g, ' ')}`)).toBeInTheDocument();
    }
    expect(flat(decided!.querySelector('[data-review-decision]')?.textContent)).toBe(
      `Round 1 · ${ANSWERED.trial.leader} decided: keep going`,
    );
    const summary = decided!.querySelector<HTMLElement>('[data-review-summary]');
    expect(flat(summary?.textContent)).toContain(`${ANSWERED.trial.leader}'s summary`);
    expect(flat(summary?.textContent)).toContain(flat(round1.summary));

    // Round 2: Temper's state in words, its own commit, and the one verdict in so far.
    expect(flat(open!.textContent)).toContain(
      `Round 2 review open · 1 verdict in · commit ${round2.commit!.slice(0, 7)} · ${round2.files_count} files`,
    );
    expect(within(open!).getByText('checker: satisfied')).toBeInTheDocument();
    expect(within(open!).queryByText(/decided/)).toBeNull();
    // No invented progress: no percentage, no time left, never "views".
    expect(card.textContent).not.toMatch(/%|\bleft\b|\bETA\b|\bviews?\b/);
    cleanup();

    // Before any decision: "No decision yet", never an empty box; round 1's review open.
    const running = runRunning.body as unknown as TeamRun;
    expect(running.reviews.map((r) => [r.round, r.state, r.decision])).toEqual([[1, 'open', null]]);
    show(<RoundCard run={running} />);
    expect(flat(document.querySelector('[data-review="none"]')?.textContent)).toBe('No decision yet');
    expect(document.querySelector('[data-review="decided"]')).toBeNull();
    expect(flat(document.querySelector('[data-review="open"]')?.textContent)).toContain(
      'Round 1 review open · no verdicts yet',
    );
    cleanup();

    // A refused done as the latest decided review: SPEC's words and Temper's refusal, quoted
    // (the typed rule: decision done_refused with reviews[].refusal; round 2 left out here).
    const refusedRun = runRefusedDone.body as unknown as TeamRun;
    const refused = refusedRun.reviews[0];
    expect([refused.decision, Boolean(refused.refusal)]).toEqual(['done_refused', true]);
    show(<RoundCard run={{ ...refusedRun, reviews: [refused] }} />);
    const refusedBox = document.querySelector<HTMLElement>('[data-review="decided"]')!;
    expect(flat(refusedBox.querySelector('[data-review-decision]')?.textContent)).toBe(
      `Round 1 · ${refusedRun.trial.leader} said done; refused`,
    );
    const quote = refusedBox.querySelector<HTMLElement>('[data-quote="engine"]');
    expect(flat(quote?.querySelector('figcaption')?.textContent)).toBe('Temper said:');
    expect(flat(quote?.querySelector('blockquote')?.textContent)).toBe(flat(refused.refusal));
    expect(flat(refusedBox.textContent)).not.toContain('decided:');
  });

  it("words a review without a decision by Temper's state, and an ended run's as never decided", () => {
    const review = (state: string, views: number): TeamReview => ({
      review_id: 'r2',
      round: 2,
      state,
      commit: null,
      files_count: null,
      views: Object.fromEntries(
        Array.from({ length: views }, (_, i) => [`m${i}`, { verdict: 'satisfied', note: null, review_id: 'r2', round: 2 }]),
      ) as TeamReview['views'],
      decision: null,
      refusal: null,
      summary: null,
    });
    expect(openReviewWords(review('open', 0), 'lead', true)).toEqual({ head: 'Round 2 review open', rest: 'no verdicts yet' });
    expect(openReviewWords(review('open', 1), 'lead', true)).toEqual({ head: 'Round 2 review open', rest: '1 verdict in' });
    expect(openReviewWords(review('open', 3), 'lead', true)).toEqual({ head: 'Round 2 review open', rest: '3 verdicts in' });
    expect(openReviewWords(review('collected', 3), 'lead', true)).toEqual({
      head: 'Round 2 review',
      rest: "all verdicts in, waiting for lead's decision",
    });
    expect(openReviewWords(review('open', 0), 'lead', false)).toEqual({ head: 'Round 2 review', rest: 'never decided, no verdicts' });
    expect(openReviewWords(review('open', 2), 'lead', false)).toEqual({
      head: 'Round 2 review',
      rest: 'never decided, 2 verdicts in',
    });
    // Only a newer review counts as the next one; nothing decided yet leaves it alone.
    expect(roundReviews([review('open', 0)])).toEqual({ decided: null, open: review('open', 0) });

    // An interrupted run's open review reads as never decided.
    const interrupted = runInterrupted.body as unknown as TeamRun;
    show(<RoundCard run={interrupted} />);
    expect(flat(document.querySelector('[data-review="open"]')?.textContent)).toContain('Round 1 review · never decided');
    cleanup();

    // A run that ended before the team wrote its outcome: Temper reads it by the run's own
    // status (done, stopped or failed) with outcome null. Its newer undecided review, open or
    // collected, is never decided: not "open", not "waiting for" (Architecture rm-b2adb3fd M1).
    const [round1, round2] = ANSWERED.reviews;
    for (const state of ['failed', 'stopped', 'done']) {
      for (const reviewState of ['open', 'collected']) {
        const ended: TeamRun = {
          ...ANSWERED,
          state,
          outcome: null,
          reviews: [round1, { ...round2, state: reviewState }],
        } as TeamRun;
        show(<RoundCard run={ended} />);
        const line = flat(document.querySelector('[data-review="open"]')?.textContent);
        expect(line, `${state} run, ${reviewState} review`).toContain('Round 2 review · never decided, 1 verdict in');
        expect(line).not.toMatch(/\bopen\b|waiting for/);
        // The decided review stays as it was.
        expect(flat(document.querySelector('[data-review-decision]')?.textContent)).toBe(
          `Round 1 · ${ANSWERED.trial.leader} decided: keep going`,
        );
        cleanup();
      }
    }
  });

  it("leaves a done run's summary to the outcome card, which shows it in full", () => {
    const done = runDone.body as unknown as TeamRun;
    const doneReview = done.reviews.find((r) => r.review_id === done.outcome?.done?.review_id);
    expect(doneReview?.summary).toBeTruthy();
    show(
      <>
        <OutcomeCard run={done} />
        <RoundCard run={done} />
      </>,
    );
    const card = screen.getByRole('region', { name: /^Round/ });
    expect(flat(card.querySelector('[data-review-decision]')?.textContent)).toBe(`Round 2 · ${done.trial.leader} decided: done`);
    expect(card.querySelector('[data-review-summary]')).toBeNull();
    expect(flat(document.body.textContent)).toContain(flat(doneReview!.summary).slice(0, 40));
  });
});

describe('on a phone', () => {
  it('the sidebar starts as the icon rail, opens on request, and keeps the wide-screen choice', () => {
    localStorage.setItem('temper-sidebar-collapsed', 'false');
    onPhone();
    // On Workflows, so its link below goes to the page already open.
    show(<AppSidebar />, '/');
    const toggle = screen.getByRole('button', { name: 'Expand sidebar' });
    // The rail: icons with names, no labels.
    expect(screen.getByRole('link', { name: 'Workflows' })).toHaveAttribute('title', 'Workflows');
    expect(screen.queryByText('Collapse')).toBeNull();
    // Expand: a drawer over the page, focus on its first link; the rail's room stays, under a scrim.
    fireEvent.click(toggle);
    const drawer = screen.getByRole('dialog', { name: 'Main menu' });
    expect(drawer).toHaveAttribute('aria-modal', 'true');
    expect(screen.getByText('Workflows')).toBeVisible();
    expect(screen.getByRole('link', { name: 'Workflows' })).toHaveFocus();
    expect(document.querySelector('[data-sidebar-placeholder]')).not.toBeNull();
    // Tab goes round inside it: Shift+Tab from the first link lands on the last control.
    fireEvent.keyDown(screen.getByRole('link', { name: 'Workflows' }), { key: 'Tab', shiftKey: true });
    expect(screen.getByRole('button', { name: 'Collapse sidebar' })).toHaveFocus();
    fireEvent.click(screen.getByRole('button', { name: 'Collapse sidebar' }));
    expect(screen.getByRole('button', { name: 'Expand sidebar' })).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).toBeNull();
    // Esc closes it, focus back on the toggle.
    fireEvent.click(screen.getByRole('button', { name: 'Expand sidebar' }));
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getByRole('button', { name: 'Expand sidebar' })).toHaveFocus();
    // A tap outside closes it.
    fireEvent.click(screen.getByRole('button', { name: 'Expand sidebar' }));
    fireEvent.click(document.querySelector('[data-sidebar-scrim]')!);
    expect(screen.queryByRole('dialog')).toBeNull();
    // Choosing a link closes it, even the page you are on (the owner's path: open the menu, tap Team).
    fireEvent.click(screen.getByRole('button', { name: 'Expand sidebar' }));
    fireEvent.click(screen.getByRole('link', { name: 'Workflows' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getByRole('button', { name: 'Expand sidebar' })).toHaveFocus();
    // The phone's open and close never change what a wide screen remembers.
    expect(localStorage.getItem('temper-sidebar-collapsed')).toBe('false');
    cleanup();

    // A wide screen still opens as it was left.
    window.matchMedia = realMatchMedia;
    show(<AppSidebar />);
    expect(screen.getByRole('button', { name: 'Collapse sidebar' })).toBeInTheDocument();
  });

  it('the guard banner is its first sentence, with the rest behind Show details', () => {
    onPhone();
    show(<TeamGuardBanner mode="record" />);
    const banner = document.querySelector<HTMLElement>('[data-guard-mode="record"]')!;
    expect(flat(banner.textContent)).toContain("Answers, messages and stops aren't limited to you yet.");
    const rest = screen.getByText(/Temper records who did each one/);
    expect(rest).not.toBeVisible();
    const more = screen.getByRole('button', { name: 'Show details' });
    expect(more).toHaveAttribute('aria-expanded', 'false');
    expect(more).toHaveAttribute('aria-controls', rest.id);
    fireEvent.click(more);
    expect(rest).toBeVisible();
    expect(screen.getByRole('button', { name: 'Hide details' })).toHaveAttribute('aria-expanded', 'true');
    // Closing it for the session is still there.
    expect(screen.getByRole('button', { name: 'Hide this notice for this session' })).toBeInTheDocument();
    cleanup();

    // A wide screen shows it whole, with no toggle.
    window.matchMedia = realMatchMedia;
    show(<TeamGuardBanner mode="record" />);
    expect(screen.getByText(/Temper records who did each one/)).toBeVisible();
    expect(screen.queryByRole('button', { name: 'Show details' })).toBeNull();
  });
});
