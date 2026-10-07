/**
 * Three more checks of the Team page's part C, each one test over all its
 * cases, the usual case first:
 * - a done Temper refused (contract E14) reads as Temper's refusal in the
 *   timeline and on the round card, and nothing else reads as one;
 * - a next question cut short (board R16) opens and closes in place and
 *   sends nothing (the keyboard and touch paths are in the e2e test);
 * - the settings check's table names each setting as Temper's question does
 *   (SPEC 5.2a), and fails if temper_ai/pi_agent/settings_wait.py renames one.
 * The runs are the fixtures the routes really answered, changed only where a
 * case says so; nothing here starts a server.
 */
import type { ReactNode } from 'react';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { NeedsYouCard } from '@/components/team/run/NeedsYouCard';
import { RoundCard } from '@/components/team/run/RoundCard';
import { SettingsChanges } from '@/components/team/run/SettingsChanges';
import { Timeline } from '@/components/team/run/Timeline';
import { settingLabel } from '@/lib/teamText';
import type { TeamDecisionEntry, TeamReview, TeamRun } from '@/types/team';

import runDone from '../../e2e/fixtures/team/run-done.json';
import runPausedLongNext from '../../e2e/fixtures/team/run-paused-long-next.json';
import runRefusedDone from '../../e2e/fixtures/team/run-refused-done.json';
import runSettingsStress from '../../e2e/fixtures/team/run-settings-stress.json';
import runStopped from '../../e2e/fixtures/team/run-stopped.json';
import SETTINGS_WAIT from '../../../temper_ai/pi_agent/settings_wait.py?raw';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function show(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

function must<T>(value: T | null | undefined, what: string): T {
  if (value == null) throw new Error(`the fixture has no ${what}`);
  return value;
}

const flat = (text: string | null | undefined) => (text ?? '').replace(/\s+/g, ' ').trim();

// ---- A done Temper refused (contract E14) ------------------------------------------------------

const REFUSED_RUN = runRefusedDone.body as unknown as TeamRun;
const DECISIONS = REFUSED_RUN.timeline.entries.filter((e) => e.entry === 'decision') as TeamDecisionEntry[];
const REFUSED_REVIEW = must(
  REFUSED_RUN.reviews.find((r) => r.decision === 'done_refused'),
  'refused review',
);
const KEPT_REVIEW = must(
  REFUSED_RUN.reviews.find((r) => r.decision === 'keep_going'),
  'keep-going review',
);
const REFUSED_ENTRY = must(
  DECISIONS.find((e) => e.data.review_id === REFUSED_REVIEW.review_id),
  'decision entry for the refused review',
);
const KEPT_ENTRY = must(
  DECISIONS.find((e) => e.data.review_id === KEPT_REVIEW.review_id),
  'decision entry for the keep-going review',
);
const REFUSAL = must(REFUSED_REVIEW.refusal, 'refusal on the refused review');
const LEADER = REFUSED_RUN.trial.leader;

/** The run with one decision entry and these reviews. */
function runWith(entry: TeamDecisionEntry, reviews: TeamReview[]): TeamRun {
  return {
    ...REFUSED_RUN,
    round: { ...REFUSED_RUN.round, current: 1 },
    timeline: { ...REFUSED_RUN.timeline, entries: [entry], not_shown: 0 },
    reviews,
  };
}

function entryWith(entry: TeamDecisionEntry, change: Record<string, unknown>, data: Record<string, unknown> = {}) {
  return { ...entry, ...change, data: { ...entry.data, ...data } } as unknown as TeamDecisionEntry;
}

const SAYS_REFUSED = 'The checker refused the heading, so we keep going.';
const NOT_ON_THE_ENTRY = 'words on the entry itself, which Temper never sends';
const REFUSED_DATA_WITHOUT_ID = Object.fromEntries(
  Object.entries(REFUSED_ENTRY.data).filter(([key]) => key !== 'review_id'),
);

const E14_CASES: { name: string; run: TeamRun; refused: boolean; roundCardToo: boolean }[] = [
  {
    name: 'a refused done, with no refusal on the entry',
    run: runWith(REFUSED_ENTRY, [REFUSED_REVIEW]),
    refused: true,
    roundCardToo: true,
  },
  {
    name: 'a refused done whose entry has no event_type',
    run: runWith(entryWith(REFUSED_ENTRY, { event_type: undefined }), [REFUSED_REVIEW]),
    refused: true,
    roundCardToo: true,
  },
  {
    name: 'an ordinary keep going whose summary says refused',
    run: runWith(entryWith(KEPT_ENTRY, {}, { summary: SAYS_REFUSED }), [{ ...KEPT_REVIEW, summary: SAYS_REFUSED }]),
    refused: false,
    roundCardToo: true,
  },
  {
    name: "an ordinary keep going with event_type 'decision: done_refused'",
    run: runWith(entryWith(KEPT_ENTRY, { event_type: 'decision: done_refused' }), [KEPT_REVIEW]),
    refused: false,
    roundCardToo: true,
  },
  {
    name: "a refusal on the entry whose review isn't refused",
    run: runWith(entryWith(KEPT_ENTRY, {}, { refusal: NOT_ON_THE_ENTRY }), [KEPT_REVIEW]),
    refused: false,
    roundCardToo: true,
  },
  {
    name: "a review that keeps going but carries a refusal",
    run: runWith(REFUSED_ENTRY, [{ ...REFUSED_REVIEW, decision: 'keep_going' }]),
    refused: false,
    roundCardToo: true,
  },
  {
    name: 'a done_refused review with an empty refusal',
    run: runWith(REFUSED_ENTRY, [{ ...REFUSED_REVIEW, refusal: '' }]),
    refused: false,
    roundCardToo: true,
  },
  {
    name: 'a done_refused review with no refusal',
    run: runWith(REFUSED_ENTRY, [{ ...REFUSED_REVIEW, refusal: null }]),
    refused: false,
    roundCardToo: true,
  },
  {
    name: "the entry's own review kept going while another review is refused",
    run: runWith(KEPT_ENTRY, [REFUSED_REVIEW, KEPT_REVIEW]),
    refused: false,
    roundCardToo: false,
  },
  {
    name: "the entry's review isn't in the run's reviews",
    run: runWith(REFUSED_ENTRY, [KEPT_REVIEW]),
    refused: false,
    roundCardToo: false,
  },
  {
    name: 'the entry names no review',
    run: runWith({ ...REFUSED_ENTRY, data: REFUSED_DATA_WITHOUT_ID } as TeamDecisionEntry, [REFUSED_REVIEW]),
    refused: false,
    roundCardToo: false,
  },
];

function timelineRows(): HTMLElement[] {
  const timeline = screen.getByRole('region', { name: /Timeline/ });
  const all = within(timeline).queryByRole('button', { name: 'Show all' });
  if (all) fireEvent.click(all);
  return within(timeline).getAllByRole('listitem');
}

describe('a done Temper refused (contract E14)', () => {
  it('reads as Temper refusal, word for word, in the timeline and on the round card, and nothing else does', () => {
    expect(REFUSED_ENTRY.decision).toBe('keep_going');
    expect('refusal' in REFUSED_ENTRY.data).toBe(false);

    for (const c of E14_CASES) {
      show(
        <>
          <Timeline run={c.run} />
          <RoundCard run={c.run} />
        </>,
      );
      const [row] = timelineRows();
      const roundCard = screen.getByRole('region', { name: /^Round/ });
      if (c.refused) {
        expect(flat(row.textContent), c.name).toContain(`${LEADER} said done; refused`);
        expect(flat(row.textContent), c.name).toContain(flat(REFUSAL));
        expect(flat(row.textContent), c.name).not.toContain('decided:');
      } else {
        expect(flat(row.textContent), c.name).toContain(`${LEADER} decided: keep going`);
        expect(flat(row.textContent), c.name).not.toContain('said done; refused');
        expect(flat(row.textContent), c.name).not.toContain(NOT_ON_THE_ENTRY);
      }
      // The round card reads the same review by the same rule, so the two never disagree.
      if (c.roundCardToo) {
        expect(flat(roundCard.textContent), `${c.name}: the round card`).toContain(
          c.refused ? `${LEADER} said done; refused` : `${LEADER} decided: keep going`,
        );
      }
      cleanup();
    }

    // The done and stopped lines are as before.
    show(<Timeline run={runDone.body as unknown as TeamRun} />);
    const done = timelineRows().map((li) => flat(li.textContent));
    expect(done.some((text) => text.includes('lead decided: done'))).toBe(true);
    expect(done.some((text) => text.includes('said done; refused'))).toBe(false);
    cleanup();
    show(<Timeline run={runStopped.body as unknown as TeamRun} />);
    const stopped = timelineRows().map((li) => flat(li.textContent));
    expect(stopped.some((text) => text.includes('stopped the team'))).toBe(true);
    expect(stopped.some((text) => text.includes('said done; refused'))).toBe(false);
  });
});

// ---- The next question, cut short (board R16) ----------------------------------------------------

describe('a question that comes next (board R16)', () => {
  it('shows its whole text on Show all, folds it again on Show less, and sends nothing', () => {
    const run = runPausedLongNext.body as unknown as TeamRun;
    const [wait, ...next] = run.open_waits;
    const question = must(next[0]?.question, 'next question');
    // jsdom lays nothing out: the next question's box says its text is taller than the two lines it shows.
    Object.defineProperty(HTMLElement.prototype, 'scrollHeight', {
      configurable: true,
      get(this: HTMLElement) {
        return this.hasAttribute('data-next-question') ? 96 : 0;
      },
    });
    const fetchCalls = vi.spyOn(globalThis, 'fetch');
    const send = vi.fn();
    try {
      show(
        <NeedsYouCard run={run} wait={wait} next={next} limits={null} sender={{ sending: false, result: null, send }} result={null} />,
      );
      const open = screen.getByRole('button', { name: 'Show all' });
      expect(open).toHaveAttribute('aria-expanded', 'false');
      const text = must(document.getElementById(must(open.getAttribute('aria-controls'), 'aria-controls')), 'question box');
      // Screen readers have the whole question while it is folded too.
      expect(flat(text.textContent)).toBe(flat(question));

      fireEvent.click(open);
      const close = screen.getByRole('button', { name: 'Show less' });
      expect(close).toHaveAttribute('aria-expanded', 'true');
      expect(close).toHaveAttribute('aria-controls', text.id);
      expect(flat(text.textContent)).toBe(flat(question));
      fireEvent.click(close);
      expect(screen.getByRole('button', { name: 'Show all' })).toHaveAttribute('aria-expanded', 'false');

      // It is never answerable: the answers are the asked question's, and nothing was sent.
      const answers = screen.getAllByRole('radio').map((r) => r.getAttribute('value'));
      expect(answers).toEqual(wait.answers.map((a) => a.answer));
      expect(send).not.toHaveBeenCalled();
      expect(fetchCalls).not.toHaveBeenCalled();
    } finally {
      delete (HTMLElement.prototype as { scrollHeight?: number }).scrollHeight;
    }
  });
});

// ---- The settings' plain names (SPEC 5.2a) ----------------------------------------------------

const SPEC_NAMES: Record<string, string> = {
  team: 'Team settings',
  agent_config_sha256: 'Agent config',
  image: 'Box image',
  pi_version: 'Pi version',
  provider: 'Provider',
  model: 'Model',
  thinking: 'Thinking',
  tools: 'Tools',
  route_host: 'Worker route',
  workflow: 'Workflow',
  cwd: 'Working folder',
  'extensions.probe': 'Extension probe',
  'add_ons.pi-tldr': 'Add-on pi-tldr',
};

describe("the settings check's names (SPEC 5.2a)", () => {
  it("names every setting as Temper's question does, in the table too, and fails when Temper renames one", () => {
    for (const [key, name] of Object.entries(SPEC_NAMES)) expect(settingLabel(key), key).toBe(name);
    // No plain name: the table shows Temper's own key.
    for (const key of ['extensions', 'add_ons', 'extensions.', 'budget_usd', 'toString', 'constructor']) {
      expect(settingLabel(key), key).toBeNull();
    }

    // The drift guard: every name in settings_wait.py's LABELS, first letter capitalized, and its two patterns.
    const labels = must(/^LABELS = \{([^}]*)\}/m.exec(SETTINGS_WAIT)?.[1], 'LABELS in settings_wait.py');
    const pairs = [...labels.matchAll(/"([^"]+)":\s*"([^"]+)"/g)].map(([, key, name]) => [key, name] as const);
    expect(pairs.map(([key]) => key).sort()).toEqual(
      Object.keys(SPEC_NAMES)
        .filter((key) => !key.includes('.'))
        .sort(),
    );
    for (const [key, name] of pairs) expect(settingLabel(key), key).toBe(name.charAt(0).toUpperCase() + name.slice(1));
    expect(SETTINGS_WAIT).toContain('head, _, name = key.partition(".")');
    expect(SETTINGS_WAIT).toContain('return f"extension {name}"');
    expect(SETTINGS_WAIT).toContain('return f"add-on {name}"');

    // The table (board S8): Setting, Was, Now; the whole team first, then each member; all 30 by name.
    const wait = (runSettingsStress.body as unknown as TeamRun).open_waits[0];
    const changes = must(wait.settings_changes, 'settings changes');
    show(<SettingsChanges changes={changes} pins={wait.pins ?? []} />);
    const table = screen.getByRole('table', { name: 'What changed' });
    const [head, ...groups] = within(table).getAllByRole('rowgroup');
    expect(within(head).getAllByRole('columnheader').map((th) => flat(th.textContent))).toEqual(['Setting', 'Was', 'Now']);
    expect(groups[0]).toHaveAttribute('data-settings-group', 'Whole team');
    fireEvent.click(screen.getByRole('button', { name: 'Show all' }));
    const rows = table.querySelectorAll('tr[data-setting]');
    expect(rows).toHaveLength(changes.length);
    const members = within(table)
      .getAllByRole('rowgroup')
      .slice(1)
      .map((group) => group.getAttribute('data-settings-group'));
    expect(members[0]).toBe('Whole team');
    expect(members.slice(1)).toEqual([...new Set(changes.filter((c) => c.scope === 'member').map((c) => c.member))]);
    for (const row of Array.from(rows)) {
      const key = must(row.getAttribute('data-setting'), 'data-setting');
      const name = must(settingLabel(key), `a plain name for ${key}`);
      expect(flat(within(row as HTMLElement).getByRole('rowheader').textContent), key).toBe(name);
    }
  });
});
