/**
 * The Team page's shared parts and read-only run view, on the fixtures the
 * routes really answered (frontend/e2e/fixtures/team, made by
 * scripts/capture_team_fixtures.py). Nothing here starts a server.
 */
import type { ReactNode } from 'react';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AppSidebar } from '@/components/layout/AppSidebar';
import { TeamCharCount } from '@/components/team/TeamCharCount';
import { TeamGate } from '@/components/team/TeamGate';
import { EngineQuote, OwnerWords } from '@/components/team/TeamQuote';
import { TeamRunViewLink } from '@/components/team/TeamRunViewLink';
import { TeamStateBadge } from '@/components/team/TeamStateBadge';
import { TeamWho } from '@/components/team/TeamWho';
import { TEAM_RUN_POLL_MS } from '@/hooks/useTeamRun';
import { teamStopper } from '@/lib/teamOutcome';
import { entryTime, waitEntryTitle } from '@/lib/teamTimeline';
import {
  TEAM_STATES,
  charCount,
  countChars,
  ownerActionWhat,
  teamRunEnded,
  teamSource,
  teamWho,
  waitTitle,
} from '@/lib/teamText';
import TeamPage from '@/pages/team/TeamPage';
import TeamRunView from '@/pages/team/TeamRunView';
import type { TeamEntry, TeamOwnerAction, TeamOwnerWaitEntry, TeamRun } from '@/types/team';

import messageRead from '../../e2e/fixtures/team/message-read.json';
import run404 from '../../e2e/fixtures/team/run-404.json';
import runDone from '../../e2e/fixtures/team/run-done.json';
import runInterrupted from '../../e2e/fixtures/team/run-interrupted.json';
import runPaused from '../../e2e/fixtures/team/run-paused.json';
import runQuestion from '../../e2e/fixtures/team/run-member-waiting-question.json';
import runRunning from '../../e2e/fixtures/team/run-running.json';
import runStarting from '../../e2e/fixtures/team/run-starting.json';
import runStopped from '../../e2e/fixtures/team/run-stopped.json';
import runStoppedByCi from '../../e2e/fixtures/team/run-stopped-by-ci.json';
import runStoppedByUnknown from '../../e2e/fixtures/team/run-stopped-by-unknown.json';
import runStoppedFromChat from '../../e2e/fixtures/team/run-stopped-from-chat.json';
import rolesOk from '../../e2e/fixtures/team/roles-ok.json';
import runStress from '../../e2e/fixtures/team/run-stress.json';
import statusOff from '../../e2e/fixtures/team/status-off.json';
import statusOn from '../../e2e/fixtures/team/status-on.json';
import trialsList from '../../e2e/fixtures/team/trials-list.json';

interface Answer {
  status: number;
  body: unknown;
}

const RUNNING = runRunning.body as unknown as TeamRun;
const ID = RUNNING.execution_id;

/**
 * Serve the Team routes from fixtures. `run` may be a list: each read of the
 * run takes the next answer and the last one repeats.
 */
function serve({
  status = statusOn,
  run = [runRunning],
  message = messageRead,
  trials = trialsList,
  roles = rolesOk,
}: {
  status?: Answer;
  run?: Answer[];
  message?: Answer;
  trials?: Answer;
  roles?: Answer;
} = {}) {
  let reads = 0;
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = new URL(String(input), 'http://temper.test').pathname;
    let answer: Answer;
    if (path === '/api/team/status') answer = status;
    else if (path === '/api/team/trials') answer = trials;
    else if (path === '/api/team/roles') answer = roles;
    else if (/^\/api\/team\/runs\/[^/]+\/messages\/[^/]+$/.test(path)) answer = message;
    else if (/^\/api\/team\/runs\/[^/]+$/.test(path)) answer = run[Math.min(reads++, run.length - 1)];
    else answer = { status: 500, body: { detail: `not served by this test: ${path}` } };
    return new Response(JSON.stringify(answer.body), {
      status: answer.status,
      headers: { 'content-type': 'application/json' },
    });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function calls(fetchMock: ReturnType<typeof serve>, pattern: RegExp): number {
  return fetchMock.mock.calls.filter(([input]) => pattern.test(new URL(String(input), 'http://temper.test').pathname))
    .length;
}

function show(ui: ReactNode, path = '/') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

/** Wait until the run itself is on screen (not the "Reading the team run" frame). */
function runShown() {
  return screen.findByRole('region', { name: /Members/ });
}

function showRun(path = `/team/runs/${ID}`) {
  return show(
    <Routes>
      <Route path="/team/runs/:executionId" element={<TeamRunView />} />
    </Routes>,
    path,
  );
}

beforeEach(() => {
  vi.unstubAllGlobals();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

// --- shared parts ---------------------------------------------------------------

describe('state badge', () => {
  it('shows every one of the eleven states as an icon and a word', () => {
    const words = ['Starting', 'Running', 'Paused', 'Quiet', 'Member waiting', 'Settings changed', 'Interrupted', 'Done', 'Stopped', 'Failed', "Didn't start"];
    expect(TEAM_STATES).toHaveLength(11);
    TEAM_STATES.forEach((state, i) => {
      const { container, unmount } = render(<TeamStateBadge state={state} />);
      const badge = container.querySelector('[data-component="team-state-badge"]');
      expect(badge).toHaveTextContent(words[i]);
      expect(badge?.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
      unmount();
    });
  });

  it("shows a state it doesn't know by its own name", () => {
    const { container } = render(<TeamStateBadge state="thinking_hard" />);
    expect(container).toHaveTextContent('thinking hard');
  });
});

describe('who', () => {
  it('tells you, a named caller and an unknown caller apart', () => {
    expect(teamWho('owner')).toEqual({ kind: 'owner', label: 'You' });
    expect(teamWho('temper-ci')).toEqual({ kind: 'named', label: 'temper-ci' });
    expect(teamWho('unknown caller').kind).toBe('unknown');
    // Nobody named is never you.
    expect(teamWho(null).kind).toBe('unknown');
    expect(teamWho('').kind).toBe('unknown');
  });

  it('makes an unknown caller stand out, with the sentence it was given', () => {
    const { container } = render(<TeamWho by="unknown caller" unknownLabel="Started by an unknown caller" />);
    const who = container.querySelector('[data-who="unknown"]');
    expect(who).toHaveTextContent('Started by an unknown caller');
    expect(who).toHaveClass('font-bold');
  });

  it('writes the owner as You and a named caller by its name', () => {
    render(
      <>
        <TeamWho by="owner" />
        <TeamWho by="temper-ci" />
      </>,
    );
    expect(screen.getByText('You')).toBeInTheDocument();
    expect(screen.getByText('temper-ci')).toBeInTheDocument();
  });
});

describe('quotes', () => {
  it("keeps Temper's words and a person's words under their own labels", () => {
    render(
      <>
        <EngineQuote label="Temper's reason">stopped at the pause after round 1</EngineQuote>
        <OwnerWords by="owner" words="We have what we need for now." />
        <OwnerWords by="temper-ci" words="Nightly stop." />
        <OwnerWords by={null} words="Who wrote this?" />
      </>,
    );
    expect(screen.getByText("Temper's reason")).toBeInTheDocument();
    expect(screen.getByText('Your words')).toBeInTheDocument();
    expect(screen.getByText("temper-ci's words")).toBeInTheDocument();
    expect(screen.getByText('Words from an unknown caller')).toBeInTheDocument();
  });

  it('shows untrusted words as text, never as HTML', () => {
    const { container } = render(<OwnerWords by="owner" words={'<img src="x" onerror="alert(1)"> plain'} />);
    expect(container.querySelector('img')).toBeNull();
  });
});

describe('character count', () => {
  it('counts characters the way the server does: an emoji is one', () => {
    expect(countChars('a😀b')).toBe(3);
    expect(countChars('')).toBe(0);
  });

  it('says how far over the limit a text is', () => {
    expect(charCount('abcd', 4).label).toBe('4 / 4');
    expect(charCount('abcdef', 4)).toEqual({ used: 6, over: 2, label: '6 / 4 · 2 over' });
    expect(charCount('x'.repeat(4321), 4000).label).toBe('4,321 / 4,000 · 321 over');
  });

  it('shows the count', () => {
    render(<TeamCharCount text="abcdef" limit={4} />);
    expect(screen.getByText(/6 \/ 4/)).toBeInTheDocument();
    expect(screen.getByText(/2 over/)).toBeInTheDocument();
  });
});

describe('words', () => {
  it('says where an action came from; both dashboard pages read as the dashboard', () => {
    expect(teamSource('team_page').table).toBe('Dashboard');
    expect(teamSource('run_page').table).toBe('Dashboard');
    expect(teamSource('chat').table).toBe('Chat');
    expect(teamSource('api').table).toBe('API');
    expect(teamSource(null).table).toBe('Unknown');
  });

  it('says what each owner action did', () => {
    const action = (kind: string, detail: Record<string, string> = {}): TeamOwnerAction =>
      ({ at: null, kind, by: 'owner', source: 'team_page', request_id: 'r', detail }) as unknown as TeamOwnerAction;
    expect(ownerActionWhat(action('start'))).toBe('started the trial');
    expect(ownerActionWhat(action('message', { to: 'maker' }))).toBe('message to maker');
    expect(ownerActionWhat(action('stop'))).toBe('stopped the run');
    expect(ownerActionWhat(action('answer', { answer: 'continue', wait_kind: 'stalled' }))).toBe(
      'continue when the team went quiet',
    );
    // Without the wait in the timeline, Design's words for the kind (SPEC 5.7).
    expect(ownerActionWhat(action('answer', { answer: 'retry', wait_kind: 'recovery' }))).toBe("retry at a member's turn");
    expect(ownerActionWhat(action('answer', { answer: 'reply', wait_kind: 'question' }))).toBe(
      "reply to a member's question",
    );
  });

  it('titles each kind of wait', () => {
    expect(waitTitle({ kind: 'pause', round: 3, member: null, turn_no: null })).toBe('Paused after round 3');
    expect(waitTitle({ kind: 'question', round: null, member: 'maker', turn_no: null })).toBe('maker asks you');
    // A closed wait carries no why: the title says only what is true of both endings.
    expect(waitTitle({ kind: 'recovery', round: null, member: 'qa', turn_no: 2 })).toBe("qa's turn 2 didn't finish");
    expect(waitTitle({ kind: 'recovery', round: null, member: 'qa', turn_no: 2, why: 'Pi stopped before it settled' })).toBe(
      "qa's turn 2 was cut off",
    );
    expect(waitTitle({ kind: 'recovery', round: null, member: 'qa', turn_no: 2, why: 'failed' })).toBe(
      "qa's turn 2 failed",
    );
    expect(
      waitTitle({ kind: 'recovery', round: null, member: 'qa', turn_no: 2, why: 'usage limit: 429 rate_limit_error' }),
    ).toBe("qa's turn 2 was cut off by a usage limit");
  });

  it('counts a run as ended only once its outcome is written and the run is over', () => {
    expect(teamRunEnded(runDone.body as unknown as TeamRun)).toBe(true);
    expect(teamRunEnded(runStopped.body as unknown as TeamRun)).toBe(true);
    expect(teamRunEnded(RUNNING)).toBe(false);
    expect(teamRunEnded(runPaused.body as unknown as TeamRun)).toBe(false);
  });
});

// --- the switch ---------------------------------------------------------------------

describe('the Team switch', () => {
  it('shows Page not found with the switch off', async () => {
    serve({ status: statusOff });
    show(
      <TeamGate>
        <p>team page</p>
      </TeamGate>,
    );
    expect(await screen.findByText('Page not found')).toBeInTheDocument();
    expect(screen.queryByText('team page')).toBeNull();
  });

  it('shows the page with the switch on', async () => {
    serve();
    show(
      <TeamGate>
        <p>team page</p>
      </TeamGate>,
    );
    expect(await screen.findByText('team page')).toBeInTheDocument();
  });

  it('keeps the Team item out of the sidebar with the switch off', async () => {
    const fetchMock = serve({ status: statusOff });
    show(<AppSidebar />);
    await act(async () => {});
    await vi.waitFor(() => expect(calls(fetchMock, /^\/api\/team\/status$/)).toBe(1));
    expect(screen.getByRole('link', { name: /Workflows/ })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /^Team$/ })).toBeNull();
  });

  it('puts Team after Workflows with the switch on', async () => {
    serve();
    show(<AppSidebar />);
    const team = await screen.findByRole('link', { name: /^Team$/ });
    expect(team).toHaveAttribute('href', '/team');
    const links = screen.getAllByRole('link').map((l) => l.textContent?.trim());
    expect(links.indexOf('Team')).toBe(links.indexOf('Workflows') + 1);
  });
});

describe('Team page header', () => {
  it('has the title, New trial and the two tabs, with the open one marked and counted', async () => {
    serve();
    show(<TeamPage tab="roles" />);
    expect(screen.getByRole('heading', { level: 1, name: 'Team' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'New trial' })).toHaveAttribute('href', '/team/new');
    const tabs = within(screen.getByRole('navigation', { name: 'Team' }));
    expect(await tabs.findByRole('link', { name: 'Roles 4' })).toHaveAttribute('aria-current', 'page');
    expect(await tabs.findByRole('link', { name: 'Trials 4' })).not.toHaveAttribute('aria-current');
    // Part A's "still being built" notices are gone.
    expect(screen.queryByText(/still being built/)).toBeNull();
  });
});

// --- the run view -----------------------------------------------------------------------

describe('run view', () => {
  it('shows a running trial: state, members, round and who did what', async () => {
    serve();
    showRun();
    await runShown();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      "Write a short welcome note for the notes app's first screen.",
    );
    expect(document.querySelector('[data-component="team-state-badge"]')).toHaveTextContent('Running');

    const members = within(screen.getByRole('region', { name: /Members/ }));
    for (const name of ['lead', 'maker', 'checker']) expect(members.getByText(name)).toBeInTheDocument();
    expect(members.getByText('leader')).toBeInTheDocument();
    expect(members.getByText('Working')).toBeInTheDocument();

    const round = within(screen.getByRole('region', { name: /Round 1/ }));
    expect(round.getByRole('img', { name: '0 of 3 rounds without done' })).toBeInTheDocument();

    const actions = within(screen.getByRole('region', { name: 'Who did what' }));
    expect(actions.getByText('started the trial')).toBeInTheDocument();
    expect(actions.getByText('Dashboard')).toBeInTheDocument();
    // The captured start came with no name on it: it must not pass as yours.
    expect(actions.getByText('Started by an unknown caller')).toBeInTheDocument();
    expect(actions.queryByText('You')).toBeNull();
  });

  it('shows a trial that is starting', async () => {
    serve({ run: [runStarting] });
    showRun();
    expect(await screen.findByText('Starting: no member turn has begun yet')).toBeInTheDocument();
    expect(document.querySelector('[data-component="team-state-badge"]')).toHaveTextContent('Starting');
  });

  it('sends an interrupted trial to the run page to resume', async () => {
    serve({ run: [runInterrupted] });
    showRun();
    expect(await screen.findByText('Interrupted: resume it from the run page')).toBeInTheDocument();
    const links = screen.getAllByRole('link', { name: /run page/i }).map((l) => l.getAttribute('href'));
    expect(links).toContain(`/workflow/${ID}`);
  });

  it("shows a member's question word for word, with the answer it takes", async () => {
    serve({ run: [runQuestion] });
    showRun();
    const heading = await screen.findByRole('heading', { name: /^maker asks you/ });
    const card = within(heading.closest('section')!);
    expect(card.getByText('Should the note mention the keyboard shortcut for a new note?')).toBeInTheDocument();
    expect(card.getByRole('radio', { name: 'reply · needs words' })).not.toBeChecked();
    expect(card.getByRole('button', { name: 'Send answer' })).toBeEnabled();
  });

  it("shows how a trial ended, with Temper's reason and the owner's words apart", async () => {
    serve({ run: [runStopped] });
    showRun();
    const ended = await screen.findByRole('region', { name: 'Stopped' });
    expect(within(ended).getByText("Temper's reason")).toBeInTheDocument();
    expect(within(ended).getByText('stopped at the pause after round 1')).toBeInTheDocument();
    expect(within(ended).getByText('Your words')).toBeInTheDocument();
    expect(within(ended).getByText('We have what we need for now.')).toBeInTheDocument();
  });

  it("shows each member's role, a failed turn's reason and the model its turns really used", async () => {
    serve({ run: [runStress] });
    showRun();
    const members = await runShown();
    const rows = within(members).getAllByRole('listitem');
    expect(rows).toHaveLength(6);
    const long = rows[1];
    expect(within(long).getByTitle('a-very-long-team-name-for-the-stress-40c')).toBeInTheDocument();
    expect(within(long).getByText('backend')).toBeInTheDocument();
    expect(within(long).getByText('Working')).toBeInTheDocument();
    expect(within(rows[0]).queryByText('frontend', { selector: 'span' })).toBeNull();
    expect(within(rows[2]).getByText('Waiting on you')).toBeInTheDocument();
    expect(within(rows[3]).getByText('Failed')).toBeInTheDocument();
    expect(
      within(rows[3]).getByText('turn 5: the worker box closed the session: exit code 137 (out of memory)'),
    ).toBeInTheDocument();
    expect(within(rows[4]).getByText('used claude-sonnet-5 \u00b7 high')).toBeInTheDocument();
    expect(within(rows[0]).queryByText(/^used /)).toBeNull();
    expect(within(rows[5]).getByText('Ended')).toBeInTheDocument();
  });

  it("says when a run isn't a team trial, in Temper's words, as information and not a failure", async () => {
    serve({ run: [run404] });
    showRun();
    const title = await screen.findByText("This run isn't a team trial");
    expect(screen.getByText('not a team trial, or no such run')).toBeInTheDocument();
    expect(title.closest('[data-note]')).toHaveAttribute('data-note', 'info');
    // The heading stays for screen readers only; the note says it all (Design's R0).
    expect(screen.getByRole('heading', { level: 1, name: 'Team run' })).toHaveClass('sr-only');
    expect(screen.getByRole('link', { name: 'Open the run page' })).toHaveAttribute('href', `/workflow/${ID}`);
  });

  it('opens one message and shows its body as text, never as HTML', async () => {
    serve({
      message: {
        status: 200,
        body: { ...messageRead.body, body: '<img src="x" onerror="alert(1)"> The heading **wraps** on a phone.' },
      },
    });
    const { container } = showRun();
    const open = await screen.findAllByRole('button', { name: /^Open/ });
    fireEvent.click(open[0]);
    expect(await screen.findByText('wraps')).toBeInTheDocument();
    expect(container.querySelector('img')).toBeNull();
  });
});

// --- the timeline ------------------------------------------------------------------------

const STOPPED = runStopped.body as unknown as TeamRun;

/** The ways a team was stopped at a question, and how the page names who did it and from where. */
const STOPS: { name: string; run: TeamRun; who: string; from: string }[] = [
  { name: 'from the dashboard', run: STOPPED, who: 'You', from: 'from the dashboard' },
  { name: 'by the CI key', run: runStoppedByCi.body as unknown as TeamRun, who: 'temper-ci', from: 'through the API' },
  {
    name: 'by an unknown caller',
    run: runStoppedByUnknown.body as unknown as TeamRun,
    who: 'unknown caller',
    from: 'from an unknown place',
  },
  { name: 'from a chat', run: runStoppedFromChat.body as unknown as TeamRun, who: 'You', from: 'from a chat' },
];

function timelineRows(): HTMLElement[] {
  return within(screen.getByRole('region', { name: /Timeline/ })).getAllByRole('listitem');
}

function entryOf(run: TeamRun, kind: string): TeamEntry {
  const entry = run.timeline.entries.find((e) => e.entry === kind);
  if (!entry) throw new Error(`no ${kind} entry in this fixture`);
  return entry as TeamEntry;
}

describe('timeline', () => {
  it('names a wait by the title its card uses, never its id or header', async () => {
    const paused = runPaused.body as unknown as TeamRun;
    const open = paused.open_waits[0];
    const openEntry = entryOf(paused, 'owner_wait') as TeamOwnerWaitEntry;
    expect(openEntry.data.wait_id).toBe(open.wait_id);
    expect(waitEntryTitle(openEntry, paused)).toBe(waitTitle(open));
    // A closed wait: from its own kind and round, as the card titled it.
    const closed = entryOf(STOPPED, 'owner_wait') as TeamOwnerWaitEntry;
    expect(waitEntryTitle(closed, STOPPED)).toBe('Paused after round 1');
    // A closed recovery wait has no why left: only what is true of a failed and a cut-off turn.
    const recovery = {
      ...closed,
      wait_kind: 'recovery',
      data: { ...closed.data, round: null, member: 'lead', turn_no: 1 },
    } as unknown as TeamOwnerWaitEntry;
    expect(waitEntryTitle(recovery, STOPPED)).toBe("lead's turn 1 didn't finish");

    serve({ run: [runPaused] });
    showRun();
    await runShown();
    const timeline = within(screen.getByRole('region', { name: /Timeline/ }));
    expect(timeline.getByText(waitTitle(open))).toBeInTheDocument();
    expect(timeline.queryByText(new RegExp(open.wait_id))).toBeNull();
    expect(timeline.queryByText(/pause-after-round-1/)).toBeNull();
  });

  it.each(STOPS)('says who stopped the team $name, from where and when, as the outcome card does', async ({ run, who, from }) => {
    const stopper = teamStopper(run);
    expect(stopper.action?.kind).toBe('answer');
    serve({ run: [{ status: 200, body: run }] });
    showRun();
    const outcome = await screen.findByRole('region', { name: 'Stopped' });
    const stoppedBy = outcome.querySelector<HTMLElement>('[data-stopped-by]')!;
    const row = timelineRows().find((li) => li.textContent?.includes('stopped the team'))!;
    expect(row).toHaveTextContent(`${who} ${from} stopped the team`);
    expect(stoppedBy).toHaveTextContent(from);
    // The same caller, drawn the same way; "You" only when the owner stopped it.
    const kind = (el: HTMLElement) => el.querySelector('[data-who]')?.getAttribute('data-who');
    expect(kind(row)).toBe(kind(stoppedBy));
    expect(within(row).queryByText('You') !== null).toBe(stopper.by === 'owner');
    expect(within(stoppedBy).queryByText('You') !== null).toBe(stopper.by === 'owner');
    // The same time: the stopping action's, never Temper's timeless entry.
    const rowTime = row.querySelector('time')!;
    const cardTime = stoppedBy.querySelector('time')!;
    expect(rowTime.getAttribute('datetime')).toBe(cardTime.getAttribute('datetime'));
    expect(rowTime).toHaveTextContent(cardTime.textContent!);
    expect(new Date(rowTime.getAttribute('datetime')!).getTime()).toBe(new Date(stopper.action!.at!).getTime());
  });

  it('gives every entry a time, the stopping one too', async () => {
    serve({ run: [runStopped] });
    showRun();
    await screen.findByRole('region', { name: 'Stopped' });
    const rows = timelineRows();
    expect(rows.length).toBeGreaterThan(1);
    for (const row of rows) expect(row.querySelector('time')).not.toBeNull();
  });

  it("takes an entry's time from the owner action that records it when Temper sent none, and makes none up", () => {
    const answer = entryOf(STOPPED, 'owner_answer');
    const action = STOPPED.owner_actions.find((a) => a.kind === 'answer')!;
    expect(entryTime({ ...answer, timestamp: null } as TeamEntry, STOPPED)).toBe(action.at);
    const stopped = STOPPED.timeline.entries.find((e) => e.entry === 'decision' && 'decision' in e && e.decision === 'stopped')!;
    expect(stopped.timestamp ?? null).toBeNull();
    expect(entryTime(stopped, STOPPED)).toBe(action.at);
    const turn = entryOf(STOPPED, 'member_turn');
    expect(entryTime({ ...turn, timestamp: null } as TeamEntry, STOPPED)).toBeNull();
  });

  it("falls back to the outcome's own caller and time when no owner action stopped the team", () => {
    const cancelled = { ...STOPPED, outcome: { ...STOPPED.outcome!, decision: 'cancelled' } } as TeamRun;
    expect(teamStopper(cancelled).action).toBeNull();
    expect(teamStopper(cancelled).by).toBe(STOPPED.outcome!.by);
    expect(teamStopper(cancelled).at).toBe(STOPPED.outcome!.at);
    expect(teamStopper(STOPPED).source).toBe('team_page');
  });
});

describe('run view polling', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  it('reads a live run again every 5 s', async () => {
    const fetchMock = serve();
    showRun();
    await runShown();
    expect(calls(fetchMock, /^\/api\/team\/runs\/[^/]+$/)).toBe(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(TEAM_RUN_POLL_MS + 50);
    });
    expect(calls(fetchMock, /^\/api\/team\/runs\/[^/]+$/)).toBe(2);
  });

  it('stops reading once the run has ended', async () => {
    const fetchMock = serve({ run: [runDone] });
    showRun();
    await runShown();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(TEAM_RUN_POLL_MS * 3);
    });
    expect(calls(fetchMock, /^\/api\/team\/runs\/[^/]+$/)).toBe(1);
  });

  it('keeps what it had when a refresh fails, and says it is not current', async () => {
    serve({ run: [runRunning, { status: 500, body: { detail: 'Internal Server Error' } }] });
    showRun();
    await runShown();
    expect(screen.queryByText(/not current/)).toBeNull();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(TEAM_RUN_POLL_MS + 50);
    });
    expect(await screen.findByText(/Couldn't refresh at/)).toBeInTheDocument();
    expect(screen.getByText(/not current/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try now' })).toBeInTheDocument();
    // The run is still on screen.
    expect(screen.getByRole('region', { name: /Members/ })).toBeInTheDocument();
  });
});

// --- the run page's link ----------------------------------------------------------------

describe("the run page's Team run view link", () => {
  it('shows for a team trial with the switch on', async () => {
    serve();
    show(<TeamRunViewLink executionId={ID} />);
    expect(await screen.findByRole('link', { name: 'Team run view' })).toHaveAttribute('href', `/team/runs/${ID}`);
  });

  it("doesn't show for a run that isn't a team trial", async () => {
    const fetchMock = serve({ run: [run404] });
    show(<TeamRunViewLink executionId={ID} />);
    await act(async () => {
      await vi.waitFor(() => expect(calls(fetchMock, /^\/api\/team\/runs\//)).toBe(1));
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    expect(screen.queryByRole('link', { name: 'Team run view' })).toBeNull();
  });

  it('asks nothing about the run with the switch off', async () => {
    const fetchMock = serve({ status: statusOff });
    show(<TeamRunViewLink executionId={ID} />);
    await vi.waitFor(() => expect(calls(fetchMock, /^\/api\/team\/status$/)).toBe(1));
    await act(async () => {});
    expect(calls(fetchMock, /^\/api\/team\/runs\//)).toBe(0);
    expect(screen.queryByRole('link', { name: 'Team run view' })).toBeNull();
  });
});
