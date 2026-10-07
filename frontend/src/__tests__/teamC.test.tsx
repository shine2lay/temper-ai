/**
 * The Team page's part C: the Run trial form's checks, where Temper's
 * problems and notes go (by their field and member, never by their text),
 * the request ids that make a retry count once, the trials list's rows and
 * paging, messages, and the settings wait's table. The bodies are the
 * fixtures the routes really answered (frontend/e2e/fixtures/team); nothing
 * here starts a server.
 */
import type { ReactNode } from 'react';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes, useParams } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { TeamApiError } from '@/lib/teamApi';
import {
  FIELD_ANCHORS,
  checkAnswered,
  checkFailed,
  emptyForm,
  memberAnchor,
  newMember,
  pickRole,
  placeAnchor,
  placeFinding,
  placeFindings,
  problemCount,
  reservedHint,
  reservedWords,
  sentRows,
  startFailed,
  teamNameOf,
  trialInput,
  trialRequestId,
  type TrialForm,
} from '@/lib/teamForm';
import { canMessage, messageFailed, messageRequestId, messageSent } from '@/lib/teamMessage';
import { CHANGES_SHOWN, fingerprint, firstChanges, settingValue, settingsGroups } from '@/lib/teamSettings';
import {
  lastTrialsPage,
  personWords,
  showingWords,
  trialGroups,
  trialNeedsYou,
  trialPeople,
  trialPhrase,
  trialRows,
  trialsRead,
} from '@/lib/teamTrials';
import TeamNewTrial from '@/pages/team/TeamNewTrial';
import type { TeamFinding, TeamMessageSent, TeamRun, TeamSettingsChange, TeamStatus, TeamTrialItem } from '@/types/team';

import checkProblems from '../../e2e/fixtures/team/check-problems.json';
import message201Held from '../../e2e/fixtures/team/message-201-held.json';
import message201Pending from '../../e2e/fixtures/team/message-201-pending.json';
import message409MemberEnded from '../../e2e/fixtures/team/message-409-member-ended.json';
import rolesOk from '../../e2e/fixtures/team/roles-ok.json';
import runSettingsStress from '../../e2e/fixtures/team/run-settings-stress.json';
import statusOn from '../../e2e/fixtures/team/status-on.json';
import trialStart201 from '../../e2e/fixtures/team/trial-start-201.json';
import trialStart400NoRequestId from '../../e2e/fixtures/team/trial-start-400-no-request-id.json';
import trialStart400Problems from '../../e2e/fixtures/team/trial-start-400-problems.json';
import trialStart401 from '../../e2e/fixtures/team/trial-start-401.json';
import trialStart409Reused from '../../e2e/fixtures/team/trial-start-409-request-id-reused.json';
import trialsList from '../../e2e/fixtures/team/trials-list.json';
import trialsWithReruns from '../../e2e/fixtures/team/trials-with-reruns.json';

const STATUS = statusOn.body as unknown as TeamStatus;
const RESERVED = ['temper'];
const PROBLEMS = checkProblems.body.problems as TeamFinding[];

/** A refusal as postTeam* throws it: the body's detail when it has one, else the body. */
function refusal(f: { status: number; body: unknown }): TeamApiError {
  const body = f.body as { detail?: unknown };
  return new TeamApiError(f.status, body && typeof body === 'object' && 'detail' in body ? body.detail : body);
}

/** The form F3 was captured with: Lead, checker, temper and a row with no role. */
function f3Form(): TrialForm {
  const rows = ['Lead', 'checker', 'temper', ''].map((name, i) => ({
    ...newMember(STATUS, `r${i + 1}`),
    role: ['planner', 'reviewer', 'builder', ''][i],
    name,
    named: name !== '',
  }));
  return { goal: 'x'.repeat(20_001), members: rows, leader: 'r1', pause: '', communication: 'all', project: '' };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

// --- the Run trial form ----------------------------------------------------------------------

describe('the Run trial form', () => {
  it('starts with one member, who leads; no pause; all can message all', () => {
    const form = emptyForm(STATUS);
    expect(form.members).toHaveLength(1);
    expect(form.leader).toBe(form.members[0].key);
    expect(form.pause).toBe('');
    expect(form.communication).toBe('all');
    expect(form.members[0].tools).toEqual(STATUS.tools.default);
    expect(form.members[0].tools).not.toContain('Bash');
  });

  it("names a row after its role until the owner types a name; a reserved role's name is left empty (F2)", () => {
    const row = newMember(STATUS);
    expect(pickRole(row, 'planner', RESERVED).name).toBe('planner');
    const temper = pickRole(row, 'temper', RESERVED);
    expect(temper.name).toBe('');
    expect(reservedHint(temper, RESERVED)).toBe(true);
    expect(reservedWords('temper')).toBe("'temper' is a reserved name, so the team name is left for you to fill.");
    const named = { ...row, name: 'lead', named: true };
    expect(pickRole(named, 'builder', RESERVED).name).toBe('lead');
    expect(reservedHint({ ...temper, name: 'keeper', named: true }, RESERVED)).toBe(false);
  });

  it('sends names as typed, an empty pause as null, no folder as null, and the leader by team name', () => {
    const form = f3Form();
    form.members[3] = { ...form.members[3], role: 'scribe' };
    const input = trialInput({ ...form, leader: 'r4', pause: '', project: '' });
    expect(input.members.map((m) => m.name)).toEqual(['Lead', 'checker', 'temper', undefined]);
    expect(input.leader).toBe('scribe');
    expect(input.pause_after_rounds).toBeNull();
    expect(input.project_path).toBeNull();
    expect(trialInput({ ...form, pause: '2', project: '/srv/example/projects/notes-app' })).toMatchObject({
      pause_after_rounds: 2,
      project_path: '/srv/example/projects/notes-app',
      communication: 'all',
    });
    expect(teamNameOf({ role: 'builder', name: '  ' })).toBe('builder');
  });

  it("places each problem by its field and member, in Temper's order (F3, contract E20)", () => {
    const form = f3Form();
    const placed = placeFindings(PROBLEMS, sentRows(form));
    expect(placed.all.map((p) => p.finding.text)).toEqual(PROBLEMS.map((p) => p.text));
    expect(placed.fields.goal.map((p) => p.text)).toEqual([PROBLEMS[1].text]);
    expect(placed.fields.project_path.map((p) => p.text)).toEqual([PROBLEMS[6].text]);
    // The leader's problem and a members problem with no member: the Members section's own list.
    expect(placed.fields.members.map((p) => p.text)).toEqual([PROBLEMS[0].text, PROBLEMS[2].text]);
    expect(placed.rows.r1.map((p) => p.text)).toEqual([PROBLEMS[3].text]);
    expect(placed.rows.r2.map((p) => p.text)).toEqual([PROBLEMS[4].text]);
    expect(placed.rows.r3.map((p) => p.text)).toEqual([PROBLEMS[5].text]);
    expect(placed.rows.r4).toBeUndefined();
  });

  it("never reads a problem's text to place it", () => {
    const rows = sentRows(f3Form());
    // The text names member 'Lead', but the problem has no member: it stays in the Members list.
    expect(placeFinding({ field: 'members', member: undefined }, rows)).toEqual({ kind: 'field', field: 'members' });
    // A member no row has (renamed since the check): the Members list too.
    expect(placeFinding({ field: 'members', member: 'gone' }, rows)).toEqual({ kind: 'field', field: 'members' });
    // No field (roles, safety) or one the page doesn't know: the top list only.
    expect(placeFinding({ field: null }, rows)).toEqual({ kind: 'top' });
    expect(placeFinding({ field: 'budget' as TeamFinding['field'] }, rows)).toEqual({ kind: 'top' });
    expect(placeFinding({ field: 'communication' }, rows)).toEqual({ kind: 'field', field: 'communication' });
  });

  it('links every place but the top list', () => {
    expect(placeAnchor({ kind: 'top' })).toBeNull();
    expect(placeAnchor({ kind: 'row', key: 'r2' })).toBe(memberAnchor('r2'));
    expect(placeAnchor({ kind: 'field', field: 'goal' })).toBe('team-goal');
    expect(FIELD_ANCHORS.members).toBe('team-members-problems');
  });

  it('reuses the request id only for the same form after no answer', () => {
    let n = 0;
    const make = () => `rid-${++n}`;
    const input = trialInput(f3Form());
    const first = trialRequestId(null, input, make);
    expect(first).toBe('rid-1');
    expect(trialRequestId({ requestId: first, input }, trialInput(f3Form()), make)).toBe('rid-1');
    expect(trialRequestId({ requestId: first, input }, { ...input, pause_after_rounds: 3 }, make)).toBe('rid-2');
  });

  it("reads a start that failed: problems to place, other refusals word for word, no answer with its request id", () => {
    expect(startFailed(refusal(trialStart400Problems), 'rid-1')).toEqual({
      kind: 'problems',
      problems: trialStart400Problems.body.problems,
      notes: [],
    });
    for (const f of [trialStart401, trialStart409Reused, trialStart400NoRequestId]) {
      const body = f.body as { detail?: string; message?: string; problem?: string };
      expect(startFailed(refusal(f), 'rid-1')).toEqual({
        kind: 'refused',
        words: body.detail ?? body.message ?? body.problem,
        status: f.status,
      });
    }
    expect(startFailed(new TypeError('Failed to fetch'), 'rid-7')).toEqual({ kind: 'no_answer', requestId: 'rid-7' });
  });

  it('reads a check: passed with its notes, problems, a refusal, no answer', () => {
    const note = { field: 'project_path', text: 'folder checks run when the Pi lane starts the team' } as TeamFinding;
    expect(checkAnswered({ ok: true, problems: [], notes: [note] })).toEqual({ kind: 'passed', notes: [note] });
    expect(checkAnswered(checkProblems.body as never)).toMatchObject({ kind: 'problems', problems: PROBLEMS });
    expect(checkFailed(refusal(trialStart401))).toMatchObject({ kind: 'refused', status: 401 });
    expect(checkFailed(new TypeError('Failed to fetch'))).toEqual({ kind: 'no_answer' });
  });

  it('counts problems', () => {
    expect(problemCount(1)).toBe('1 problem');
    expect(problemCount(26)).toBe('26 problems');
    expect(problemCount(1200)).toBe('1,200 problems');
  });
});

// --- messages --------------------------------------------------------------------------------

describe('messages to a member', () => {
  const run = (state: string, outcome: unknown = null) => ({ state, outcome }) as unknown as TeamRun;

  it('can be sent while the team is live, never after it ended', () => {
    for (const state of ['running', 'paused', 'quiet', 'member_waiting', 'settings_changed']) {
      expect(canMessage(run(state))).toBe(true);
    }
    for (const state of ['starting', 'interrupted', 'done', 'stopped', 'failed', 'didnt_start']) {
      expect(canMessage(run(state))).toBe(false);
    }
    expect(canMessage(run('running', { kind: 'stopped' }))).toBe(false);
  });

  it('reuse the request id only for the same member and words after no answer', () => {
    let n = 0;
    const make = () => `m-${++n}`;
    const last = { requestId: messageRequestId(null, 'maker', 'Keep it short.', make), to: 'maker', body: 'Keep it short.' };
    expect(last.requestId).toBe('m-1');
    expect(messageRequestId(last, 'maker', 'Keep it short.', make)).toBe('m-1');
    expect(messageRequestId(last, 'checker', 'Keep it short.', make)).toBe('m-2');
    expect(messageRequestId(last, 'maker', 'Keep it shorter.', make)).toBe('m-3');
  });

  it('say when Temper holds one until the open question is answered', () => {
    expect(messageSent(message201Pending.body as TeamMessageSent)).toEqual({ kind: 'sent', to: 'maker', held: false, repeated: false });
    expect(messageSent(message201Held.body as TeamMessageSent)).toMatchObject({ held: true });
  });

  it("keep Temper's refusal word for word, and the request id when no answer came", () => {
    expect(messageFailed(refusal(message409MemberEnded), 'm-1')).toEqual({
      kind: 'refused',
      words: message409MemberEnded.body.message,
      status: 409,
    });
    expect(messageFailed(new TypeError('Failed to fetch'), 'm-1')).toEqual({ kind: 'no_answer', requestId: 'm-1' });
  });
});

// --- the trials list -------------------------------------------------------------------------

describe('the trials list', () => {
  const items = (f: { body: unknown }) => (f.body as { trials: TeamTrialItem[] }).trials;

  it('reads one item more before a later page, to know whether its first row continues a trial', () => {
    expect(trialsRead(0)).toEqual({ limit: 25, offset: 0, lead: 0 });
    expect(trialsRead(1)).toEqual({ limit: 26, offset: 24, lead: 1 });
    expect(trialsRead(2)).toEqual({ limit: 26, offset: 49, lead: 1 });
  });

  it('puts a re-run or fork under its trial, one row per run, newest first (A-8)', () => {
    const rows = trialRows(items(trialsWithReruns), 0);
    expect(rows).toHaveLength(6);
    const groups = trialGroups(rows);
    expect(groups).toHaveLength(4);
    const stopped = groups[1];
    expect(stopped.head?.item.state).toBe('stopped');
    expect(stopped.subs.map((r) => r.item.execution_id.slice(0, 8))).toEqual(['3eacb8a3', '9b1e7c42']);
    expect(stopped.subs.every((r) => r.sub && !r.orphan)).toBe(true);
  });

  it('names the trial of a re-run that opens a page', () => {
    const list = items(trialsWithReruns);
    // Page 2 read with one item before it: the stopped trial's own run, then its re-run.
    const rows = trialRows(list.slice(1, 3), 1);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ sub: true, orphan: true });
    expect(trialGroups(rows)[0].head).toBeNull();
  });

  it("pairs a stopped row with the run list's own status, never a guess (E18)", () => {
    expect(trialPhrase({ state: 'stopped', run_status: 'cancelled' })).toBe('run list: cancelled');
    expect(trialPhrase({ state: 'stopped', run_status: 'failed' })).toBe('run list: failed');
    expect(trialPhrase({ state: 'stopped', run_status: null })).toBeNull();
    expect(trialPhrase({ state: 'done', run_status: 'completed' })).toBeNull();
    expect(trialPhrase({ state: 'failed', run_status: 'failed' })).toBeNull();
    expect(trialPhrase({ state: 'settings_changed', run_status: 'running' })).toBe('settings changed while it waited');
    expect(trialPhrase({ state: 'didnt_start', run_status: 'failed' })).toBe('Nothing was spent.');
  });

  it('tints the rows that wait for the owner', () => {
    expect(['paused', 'quiet', 'member_waiting', 'settings_changed'].every((state) => trialNeedsYou({ state } as TeamTrialItem))).toBe(true);
    expect(['running', 'stopped', 'done', 'interrupted'].some((state) => trialNeedsYou({ state } as TeamTrialItem))).toBe(false);
  });

  it('says what the page shows, and where the last page is', () => {
    expect(showingWords(0, 25, 57)).toBe('Showing 1–25 of 57 · newest first');
    expect(showingWords(50, 7, 57)).toBe('Showing 51–57 of 57 · newest first');
    expect(showingWords(0, 0, 0)).toBe('Showing 0 of 0 · newest first');
    expect(showingWords(0, 25, 1200)).toBe('Showing 1–25 of 1,200 · newest first');
    expect(lastTrialsPage(57)).toBe(2);
    expect(lastTrialsPage(50)).toBe(1);
    expect(lastTrialsPage(0)).toBe(0);
  });

  it('names the leader and members, with the role when it differs', () => {
    const people = trialPeople(items(trialsList)[0]);
    expect(people.leader && personWords(people.leader)).toBe('lead (planner)');
    expect(people.others.map(personWords)).toEqual(['maker (builder)', 'checker (reviewer)']);
    expect(personWords({ name: 'planner', role: 'planner' })).toBe('planner');
  });
});

// --- the settings wait -----------------------------------------------------------------------

describe("the settings wait's table (SPEC 5.2a, board S8)", () => {
  const changes = (runSettingsStress.body.open_waits[0] as { settings_changes: TeamSettingsChange[] }).settings_changes;

  it('groups the changes as the question does: the whole team first, then each member by name', () => {
    const groups = settingsGroups(changes);
    expect(groups.map((g) => g.member)).toEqual([null, 'a-very-long-team-name-for-the-stress-40c', 'checker', 'maker']);
    expect(groups.reduce((n, g) => n + g.changes.length, 0)).toBe(30);
  });

  it(`shows the first ${CHANGES_SHOWN} changes until Show all`, () => {
    const shown = firstChanges(settingsGroups(changes), CHANGES_SHOWN);
    expect(shown.reduce((n, g) => n + g.changes.length, 0)).toBe(8);
    expect(shown.map((g) => g.member)).toEqual([null, 'a-very-long-team-name-for-the-stress-40c']);
  });

  it('cuts a digest to its first 12 hex, keeps text whole and says (none)', () => {
    const digest = 'ea94ae82321ded604399d0f1b32396724fc3eb88f8edacab14dcfe38361c8aea';
    expect(settingValue(digest, 'sha256')).toEqual({ shown: 'ea94ae82321d', full: digest });
    expect(settingValue(`sha256:${digest}`, 'text')).toEqual({ shown: 'ea94ae82321d', full: `sha256:${digest}` });
    expect(settingValue('claude-sonnet-y', 'text')).toEqual({ shown: 'claude-sonnet-y', full: null });
    expect(settingValue(null, 'sha256')).toEqual({ shown: '(none)', full: null });
    expect(fingerprint(digest).shown).toBe('ea94ae82321d');
    expect(fingerprint('not-a-digest').shown).toBe('not-a-digest');
  });
});

// --- the form on the page --------------------------------------------------------------------

interface Answer {
  status: number;
  body: unknown;
}

/** Serve the reads the form makes, and answer its POSTs in turn ('no reply' fails the request). */
function serveForm(replies: { trials?: (Answer | 'no reply')[]; check?: (Answer | 'no reply')[] } = {}) {
  const sent: { path: string; body: Record<string, unknown> }[] = [];
  const turn: Record<string, number> = {};
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input), 'http://temper.test').pathname;
    let answer: Answer | 'no reply';
    if ((init?.method ?? 'GET') === 'POST') {
      sent.push({ path, body: JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown> });
      const list = path === '/api/team/check' ? replies.check : replies.trials;
      const n = (turn[path] = (turn[path] ?? 0) + 1);
      answer = list?.[Math.min(n - 1, list.length - 1)] ?? { status: 500, body: { detail: 'no reply set' } };
    } else if (path === '/api/team/status') answer = statusOn;
    else if (path === '/api/team/roles') answer = rolesOk;
    else answer = { status: 500, body: { detail: `not served by this test: ${path}` } };
    if (answer === 'no reply') throw new TypeError('Failed to fetch');
    return new Response(JSON.stringify(answer.body), { status: answer.status, headers: { 'content-type': 'application/json' } });
  });
  vi.stubGlobal('fetch', fetchMock);
  return sent;
}

function RunShown() {
  return <p>run {useParams().executionId}</p>;
}

function showForm(ui: ReactNode = <TeamNewTrial />) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/team/new']}>
        <Routes>
          <Route path="/team/new" element={ui} />
          <Route path="/team/runs/:executionId" element={<RunShown />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const memberRow = (n: number) => screen.getByRole('group', { name: `Member ${n}` });

async function fillF3() {
  await screen.findByRole('option', { name: 'planner: Planner' });
  fireEvent.change(document.getElementById('team-goal')!, { target: { value: 'Write a short welcome note.' } });
  const add = screen.getByRole('button', { name: 'Add member' });
  for (let i = 0; i < 3; i++) fireEvent.click(add);
  const pick = [
    ['planner', 'Lead'],
    ['reviewer', 'checker'],
    ['builder', 'temper'],
  ];
  pick.forEach(([role, name], i) => {
    const row = within(memberRow(i + 1));
    fireEvent.change(row.getByLabelText('Role'), { target: { value: role } });
    fireEvent.change(row.getByLabelText('Team name'), { target: { value: name } });
  });
}

describe('the form on the page', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it('puts each problem under its field and its member row, word for word, and lists them all on top', async () => {
    const sent = serveForm({ check: [{ status: 200, body: checkProblems.body }] });
    showForm();
    await fillF3();
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Check' }));
    });
    const top = await screen.findByTestId('team-form-problems');
    expect(within(top).getByRole('heading', { name: 'The check found 7 problems' })).toBeInTheDocument();
    expect(within(top).getAllByRole('listitem').map((li) => li.textContent)).toEqual(PROBLEMS.map((p) => p.text));
    expect(document.getElementById('team-goal-problem-0')).toHaveTextContent(PROBLEMS[1].text);
    expect(document.getElementById('team-goal')).toHaveAttribute('aria-invalid', 'true');
    expect(document.getElementById('team-goal')?.getAttribute('aria-describedby')).toContain('team-goal-problem-0');
    expect(document.getElementById('team-project-problem-0')).toHaveTextContent(PROBLEMS[6].text);
    const members = document.getElementById('team-members-problems')!;
    expect(members).toHaveTextContent(PROBLEMS[0].text);
    expect(members).toHaveTextContent(PROBLEMS[2].text);
    expect(memberRow(1)).toHaveTextContent(PROBLEMS[3].text);
    expect(memberRow(2)).toHaveTextContent(PROBLEMS[4].text);
    expect(memberRow(3)).toHaveTextContent(PROBLEMS[5].text);
    expect(memberRow(4)).not.toHaveTextContent(/member '/);
    // Check sends the form without a request id: it saves and starts nothing.
    expect(sent).toHaveLength(1);
    expect(sent[0].path).toBe('/api/team/check');
    expect(sent[0].body.request_id).toBeUndefined();
  });

  it('Try again after no answer sends the same request id; a changed form gets a new one', async () => {
    const sent = serveForm({ trials: ['no reply', 'no reply', { status: 201, body: trialStart201.body }] });
    showForm();
    await fillF3();
    fireEvent.change(document.getElementById('team-pause')!, { target: { value: '2' } });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Run project' }));
    });
    expect(await screen.findByText(/Temper didn't answer\. Trying again is safe/)).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    });
    await vi.waitFor(() => expect(sent).toHaveLength(2));
    expect(sent[1].body.request_id).toBe(sent[0].body.request_id);
    expect(typeof sent[0].body.request_id).toBe('string');
    fireEvent.change(document.getElementById('team-pause')!, { target: { value: '3' } });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Run project' }));
    });
    expect(await screen.findByText(`run ${trialStart201.body.execution_id}`)).toBeInTheDocument();
    expect(sent).toHaveLength(3);
    expect(sent[2].body.request_id).not.toBe(sent[0].body.request_id);
    expect(sent[2].body.pause_after_rounds).toBe(3);
  });
});
