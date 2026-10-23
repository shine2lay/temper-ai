/**
 * The comparing half of the Team page truth check (scripts/teamPageTruth.ts, run by
 * scripts/team-page-truth.mjs).
 *
 * The check reads the Team page as a person sees it and compares six fields per Project
 * (members, state, waits, cost so far, result, whether each member card says its member is at
 * work) with Temper's records, each field judged by the one record Temper names as its truth
 * (cost: the recorded model calls; the words given with a stop: the team's stop record; a member
 * at work: a running turn in the turns record). Where Temper's other records disagree with that one, they are
 * listed apart for the temper role and don't count against the page. These tests feed it made-up
 * Projects whose right answers are known: a clean one must match everywhere, each planted break
 * must be caught at its own field with both values in the report, and records that disagree must
 * be listed without failing a page that is right.
 */
import { describe, expect, it } from 'vitest';

import {
  captionFor,
  captionMatches,
  captionWho,
  compareAll,
  exitCode,
  genuineReason,
  pageStateClass,
  pageWorking,
  parseMoney,
  recordStateClass,
  runDetail,
  sameCent,
  sameWords,
  showsReason,
  stateAgrees,
  stopRecord,
  toMarkdown,
  turnsRecord,
  usd,
  type CheckInput,
  type PageListRow,
  type PageRunView,
  type ProjectRecords,
  type Report,
  type TeamApiProject,
} from '../../scripts/teamPageTruth.ts';

const ID = 'aaaaaaaa-0000-4000-8000-000000000001';
const OTHER = 'bbbbbbbb-0000-4000-8000-000000000002';

function records(over: Partial<ProjectRecords> = {}): ProjectRecords {
  return {
    executionId: ID,
    workflow: 'team-trial-aaaa',
    status: 'completed',
    costUsd: 3.456789,
    detail: { status: 'completed', costUsd: 3.456789, nodeCostUsd: 3.456789, decision: 'done', outputReason: null, stoppedReason: null, errorMessage: null },
    turns: { lead: { turns: 2, costUsd: 1.234567 }, tester: { turns: 1, costUsd: 2.222222 } },
    members: [
      { name: 'lead', role: 'product', leader: true },
      { name: 'tester', role: 'qa', leader: false },
    ],
    openWaits: [],
    waitingDecisions: 0,
    stop: null,
    stopRead: true,
    ...over,
  };
}

function listRow(over: Partial<PageListRow> = {}): PageListRow {
  return {
    executionId: ID,
    subRow: false,
    members: [
      { name: 'lead', role: 'product', leader: true, cost: null },
      { name: 'tester', role: 'qa', leader: false, cost: null },
    ],
    stateWord: 'Done',
    needsYou: false,
    runListWord: null,
    cost: '$3.46',
    ...over,
  };
}

function runView(over: Partial<PageRunView> = {}): PageRunView {
  return {
    executionId: ID,
    kind: 'flow',
    problem: null,
    stateWord: 'Done',
    members: [
      { name: 'lead', role: 'product', leader: true, cost: '$1.23', stateWord: 'Ended' },
      { name: 'tester', role: 'qa', leader: false, cost: '$2.22', stateWord: 'Ended' },
    ],
    costs: [{ place: 'Spend', value: '$3.46' }],
    waits: { any: false, count: 0, from: [] },
    outcomeWord: 'Done',
    outcomeReason: null,
    outcomeText: 'Done',
    stopWords: [],
    ...over,
  };
}

function teamApi(over: Partial<TeamApiProject> = {}): TeamApiProject {
  return {
    listed: true,
    members: [
      { name: 'lead', role: 'product', leader: true, costUsd: 1.234567, state: 'ended' },
      { name: 'tester', role: 'qa', leader: false, costUsd: 2.222222, state: 'ended' },
    ],
    state: 'done',
    runStatus: 'completed',
    costUsd: 3.456789,
    openWaits: 0,
    decision: 'done',
    reason: null,
    ownerWords: null,
    ...over,
  };
}

interface Parts {
  rec?: ProjectRecords;
  after?: ProjectRecords;
  rows?: PageListRow[];
  view?: PageRunView;
  api?: TeamApiProject;
  listTotal?: number | null;
}

function check({ rec = records(), after, rows = [listRow()], view = runView(), api = teamApi(), listTotal = 1 }: Parts = {}): Report {
  const input: CheckInput = {
    base: 'http://127.0.0.1:8420',
    at: '2026-10-19T12:00:00Z',
    runListTotal: 40,
    records: { [ID]: rec },
    recordsAfter: after ? { [ID]: after } : undefined,
    page: { listTotal, rows, views: { [ID]: view } },
    teamApi: { [ID]: api },
  };
  return compareAll(input);
}

const mismatches = (r: Report) => r.rows.filter((x) => x.verdict === 'mismatch').map((x) => `${x.project}:${x.field}`);
const row = (r: Report, field: string, project = ID) => r.rows.find((x) => x.project === project && x.field === field)!;

/** The words given with a stop, made up (neutral). */
const WORDS = 'Paused for the night; pick it up after the review.';

/** A Project its stop ended, the stop words in the team's stop record, the run's records agreeing,
 * and a page that shows it all: Stopped, and the words under the stopper's caption. */
function stopped(over: { rec?: Partial<ProjectRecords>; view?: Partial<PageRunView>; api?: Partial<TeamApiProject> } = {}): Parts {
  return {
    rec: records({
      status: 'cancelled',
      detail: { status: 'cancelled', costUsd: 3.456789, nodeCostUsd: 3.456789, decision: null, outputReason: null, stoppedReason: WORDS, errorMessage: WORDS },
      stop: { from: 'stop', by: 'temper', words: WORDS, at: '2026-10-12T19:00:00+00:00' },
      ...over.rec,
    }),
    rows: [listRow({ stateWord: 'Stopped', runListWord: 'cancelled' })],
    view: runView({
      stateWord: 'Stopped',
      outcomeWord: 'Stopped',
      outcomeReason: 'The run was cancelled',
      outcomeText: `Stopped\nThe run was cancelled\ntemper's words\n${WORDS}`,
      stopWords: [{ label: "temper's words", words: WORDS }],
      ...over.view,
    }),
    api: teamApi({ state: 'stopped', runStatus: 'cancelled', decision: 'cancelled', reason: 'the run was cancelled', ownerWords: WORDS, ...over.api }),
  };
}

describe('small rules', () => {
  it('reads dollar amounts the way the page writes them', () => {
    expect(parseMoney('$10.22')).toBe(10.22);
    expect(parseMoney('Cost $1,234.50')).toBe(1234.5);
    expect(parseMoney('$0.0058')).toBe(0.0058);
    expect(parseMoney('$62')).toBe(62);
    expect(parseMoney('Not known')).toBeNull();
    expect(parseMoney(null)).toBeNull();
  });

  it('compares money to the cent', () => {
    expect(sameCent(10.22, 10.224325)).toBe(true);
    expect(sameCent(2.25, 2.242693)).toBe(false);
    expect(sameCent(2.24, 2.245)).toBe(true);
    expect(sameCent(0, 0.004)).toBe(true);
    expect(sameCent(0, 10.224325)).toBe(false);
  });

  it('writes a record amount as it stands, without float noise', () => {
    expect(usd(0)).toBe('$0.0');
    expect(usd(10.224325)).toBe('$10.224325');
    expect(usd(57.00454239999999)).toBe('$57.0045424');
    expect(usd(null)).toBe('none');
  });

  it('sorts the page state words and the records into the same classes', () => {
    expect(pageStateClass('Done')).toBe('done');
    expect(pageStateClass("Done: the leader's version was approved")).toBe('done');
    expect(pageStateClass('Didn\u2019t start')).toBe('didnt_start');
    expect(pageStateClass('Last seen: Running')).toBe('live');
    expect(pageStateClass('Waiting for you')).toBe('live');
    expect(pageStateClass(null)).toBe('unknown');
    expect(recordStateClass('cancelled')).toBe('stopped');
    expect(recordStateClass('cancelled', 'done')).toBe('done');
    expect(recordStateClass('running')).toBe('live');
    expect(recordStateClass('mystery')).toBe('unknown');
  });

  it('lets the Team words for runs that stopped moving agree with what the run list says', () => {
    expect(stateAgrees('interrupted', 'live')).toBe(true);
    expect(stateAgrees('didnt_start', 'failed')).toBe(true);
    expect(stateAgrees('done', 'stopped')).toBe(false);
    expect(stateAgrees('unknown', 'unknown')).toBe(false);
  });

  it('treats engine end tokens and blanks as no reason', () => {
    expect(genuineReason('team_done')).toBeNull();
    expect(genuineReason('  ')).toBeNull();
    expect(genuineReason('the budget ran out')).toBe('the budget ran out');
  });

  it('finds a reason shown whole, or cut short with an ellipsis', () => {
    const reason = 'the leader stopped because the budget for this round ran out and nobody asked for more';
    expect(showsReason('Stopped\nThe Leader stopped because the budget  for this round ran out and nobody asked for more.', reason)).toBe(true);
    expect(showsReason('Stopped\nthe leader stopped because the budget for this round ran out and nobody\u2026', reason)).toBe(true);
    expect(showsReason('Stopped\nThe run was cancelled', reason)).toBe(false);
    expect(showsReason(null, reason)).toBe(false);
  });

  it('compares stop words verbatim, each run of whitespace as one space', () => {
    expect(sameWords('Stop  here,\nthanks. ', 'Stop here, thanks.')).toBe(true);
    expect(sameWords('stop here, thanks.', 'Stop here, thanks.')).toBe(false);
    expect(sameWords('Stop here, thanks', 'Stop here, thanks.')).toBe(false);
  });

  it('reads who a stop-words caption names, the way the page writes it', () => {
    expect(captionFor('owner')).toBe('Your words');
    expect(captionFor('temper')).toBe("temper's words");
    expect(captionFor(null)).toBe('Words from an unknown caller');
    expect(captionFor('unknown caller')).toBe('Words from an unknown caller');
    expect(captionWho('Your words')).toBe('owner');
    expect(captionWho('temper-ci\u2019s words')).toBe('temper-ci');
    expect(captionWho('Words from an unknown caller')).toBe('unknown caller');
    expect(captionWho("Temper's reason")).toBeNull();
    expect(captionMatches("temper's words", 'temper')).toBe(true);
    expect(captionMatches('Your words', 'temper')).toBe(false);
    expect(captionMatches('Words from an unknown caller', '')).toBe(true);
  });
});

describe("reading Temper's records as its API sends them", () => {
  it("finds the team's stop record: the last owner_actions entry of kind stop, its words and who", () => {
    const body = {
      kind: 'flow',
      state: 'stopped',
      owner_actions: [
        { at: '2026-10-12T18:00:00+00:00', kind: 'start', by: 'owner', source: 'team_page', request_id: 'r-1', detail: { workflow: 'team-trial-aaaa', trial_id: 'aaaa' } },
        { at: '2026-10-12T18:20:00+00:00', kind: 'stop', by: 'temper', source: 'api', request_id: 'r-2', detail: { reason: 'First words.' } },
        { at: '2026-10-12T18:30:00+00:00', kind: 'answer', by: 'owner', source: 'team_page', request_id: 'r-3', detail: { wait_id: 'w-1', wait_kind: 'pause', answer: 'continue' } },
        { at: '2026-10-12T19:00:00+00:00', kind: 'stop', by: 'owner', source: 'api', request_id: 'r-4', detail: { reason: '  Stop here, thanks.  ' } },
      ],
      outcome: { decision: 'cancelled', reason: 'the run was cancelled', owner_words: 'Stop here, thanks.', problems: [], by: 'owner', at: '2026-10-12T19:00:01+00:00', done: null },
    };
    expect(stopRecord(body)).toEqual({ from: 'stop', by: 'owner', words: 'Stop here, thanks.', at: '2026-10-12T19:00:00+00:00' });
    const noWords = { owner_actions: [{ at: '2026-10-12T19:00:00+00:00', kind: 'stop', by: 'unknown caller', source: 'api', request_id: 'r-5', detail: {} }] };
    expect(stopRecord(noWords)).toEqual({ from: 'stop', by: 'unknown caller', words: null, at: '2026-10-12T19:00:00+00:00' });
  });

  it("takes a stop answer's words from the team's outcome record, and finds nothing for a run nobody stopped", () => {
    const answered = {
      owner_actions: [{ at: '2026-10-12T18:00:00+00:00', kind: 'answer', by: 'owner', source: 'team_page', request_id: 'r-1', detail: { wait_id: 'w-1', wait_kind: 'pause', answer: 'stop' } }],
      outcome: { decision: 'stopped', reason: 'stopped at the pause after round 3', owner_words: 'Enough for today.', problems: [], by: 'owner', at: '2026-10-12T18:00:02+00:00', done: null },
    };
    expect(stopRecord(answered)).toEqual({ from: 'stop answer', by: 'owner', words: 'Enough for today.', at: '2026-10-12T18:00:02+00:00' });
    const done = { owner_actions: [], outcome: { decision: 'done', reason: 'built', owner_words: null, problems: [], by: null, at: null, done: {} } };
    expect(stopRecord(done)).toBeNull();
    expect(stopRecord(null)).toBeNull();
  });

  it("reads the run's own record, sums the recorded model calls per member and counts the turns still running", () => {
    const run = {
      id: ID,
      workflow_name: 'team-trial-aaaa',
      status: 'cancelled',
      total_cost_usd: 0,
      nodes: [
        { id: 'n-1', name: 'trial', type: 'agent', status: 'cancelled', cost_usd: 10.2243246 },
        { id: 'n-2', name: 'after', type: 'agent', status: 'skipped', cost_usd: null },
      ],
      workflow_output: null,
      error_message: WORDS,
      stopped: { path: 'trial', reason: WORDS, at: '2026-10-12T19:00:00+00:00', mode: 'cancel', held: false },
    };
    expect(runDetail(run)).toEqual({
      status: 'cancelled',
      costUsd: 0,
      nodeCostUsd: 10.2243246,
      decision: null,
      outputReason: null,
      stoppedReason: WORDS,
      errorMessage: WORDS,
    });
    expect(runDetail({ status: 'cancelled', workflow_output: { decision: 'stopped', reason: 'stopped at the pause after round 3' } })).toMatchObject({
      decision: 'stopped',
      outputReason: 'stopped at the pause after round 3',
      costUsd: null,
      nodeCostUsd: null,
    });
    const agents = {
      execution_id: ID,
      agents: [
        { id: 'a-1', agent_name: 'lead', round: 1, status: 'completed', estimated_cost_usd: 1.2, role: 'product', model: 'm' },
        { id: 'a-2', agent_name: 'lead', round: 2, status: 'completed', estimated_cost_usd: 0.034567, role: 'product', model: 'm' },
        { id: 'a-3', agent_name: 'tester', round: 1, status: 'failed', estimated_cost_usd: null, role: 'qa', model: 'm' },
        { id: 'a-4', agent_name: null, round: 1, status: 'completed', estimated_cost_usd: 9, role: null, model: 'm' },
      ],
    };
    const turns = turnsRecord(agents.agents);
    expect(Object.keys(turns)).toEqual(['lead', 'tester']);
    expect(turns.lead.turns).toBe(2);
    expect(turns.lead.costUsd).toBeCloseTo(1.234567, 9);
    expect(turns.tester).toEqual({ turns: 1, costUsd: 0, running: 0 });
    expect(turns.lead.running).toBe(0);
    const live = turnsRecord([
      { agent_name: 'lead', status: 'completed', estimated_cost_usd: 1 },
      { agent_name: 'lead', status: 'running', estimated_cost_usd: null },
      { agent_name: 'tester', status: 'interrupted', estimated_cost_usd: 0.5 },
    ]);
    expect(live.lead).toEqual({ turns: 2, costUsd: 1, running: 1 });
    expect(live.tester).toEqual({ turns: 1, costUsd: 0.5, running: 0 });
  });
});

describe('a Project whose page shows what its records hold', () => {
  it('matches every field, lists no disagreement and exits 0', () => {
    const r = check();
    expect(mismatches(r)).toEqual([]);
    expect(r.totals).toEqual({ match: 8, mismatch: 0, 'no record': 0 });
    expect(r.rows.map((x) => x.field)).toEqual(['listed', 'members', 'state', 'waits', 'cost', 'result', 'memberWork', 'listed']);
    expect(r.disagreements).toEqual([]);
    expect(exitCode(r)).toBe(0);
  });

  it('a stopped one, its stop words shown under the caption that names who gave them', () => {
    const r = check(stopped());
    expect(mismatches(r)).toEqual([]);
    expect(r.disagreements).toEqual([]);
    expect(row(r, 'result').record).toContain(`stop words (the team's stop record, by temper): "${WORDS}"`);
    expect(row(r, 'result').page).toContain(`stop words: "${WORDS}" under "temper's words"`);
    expect(exitCode(r)).toBe(0);
  });

  it('stop words shown with other spacing are the same words', () => {
    const r = check(stopped({ view: { stopWords: [{ label: "temper's words", words: 'Paused for the  night;\npick it up after the review.' }] } }));
    expect(mismatches(r)).toEqual([]);
  });

  it("a stop answer's words from the owner, and a stop with no words given", () => {
    const answer = stopped({
      rec: { stop: { from: 'stop answer', by: 'owner', words: 'Enough for today.', at: null }, detail: { ...records().detail!, status: 'cancelled', decision: 'stopped', stoppedReason: null, errorMessage: null } },
      view: { stopWords: [{ label: 'Your words', words: 'Enough for today.' }] },
      api: { decision: 'stopped', ownerWords: 'Enough for today.' },
    });
    expect(mismatches(check(answer))).toEqual([]);
    const none = stopped({
      rec: { stop: { from: 'stop', by: 'owner', words: null, at: null }, detail: { ...records().detail!, status: 'cancelled', decision: null, stoppedReason: 'Workflow cancelled by user', errorMessage: 'Workflow cancelled by user' } },
      view: { stopWords: [] },
      api: { ownerWords: null },
    });
    const r = check(none);
    expect(mismatches(r)).toEqual([]);
    expect(r.disagreements).toEqual([]);
  });

  it("leaves out a role the page doesn't repeat when it equals the name", () => {
    const rec = records({
      members: [
        { name: 'lead', role: 'lead', leader: true },
        { name: 'tester', role: 'qa', leader: false },
      ],
    });
    const rows = [listRow({ members: [{ name: 'lead', role: null, leader: true, cost: null }, listRow().members[1]] })];
    const view = runView({ members: [{ name: 'lead', role: null, leader: true, cost: '$1.23', stateWord: 'Ended' }, runView().members![1]] });
    expect(mismatches(check({ rec, rows, view }))).toEqual([]);
    const wrongRole = runView({ members: [{ name: 'lead', role: 'product', leader: true, cost: '$1.23', stateWord: 'Ended' }, runView().members![1]] });
    expect(row(check({ rec, rows, view: wrongRole }), 'members').gaps).toEqual(["the run view shows lead's role as product; record: lead"]);
  });

  it("accepts a running Project's cost anywhere between two reads of its recorded model calls", () => {
    const live = { status: 'running', detail: null } as const;
    const rec = records({ ...live, costUsd: 1.0, turns: { lead: { turns: 1, costUsd: 1.0 } } });
    const after = records({ ...live, costUsd: 1.2, turns: { lead: { turns: 2, costUsd: 1.2 } } });
    const view = runView({ stateWord: 'Running', outcomeWord: null, outcomeText: null, costs: [{ place: 'Spend', value: '$1.10' }], members: null });
    const rows = [listRow({ stateWord: 'Running', cost: '$1.05' })];
    const api = teamApi({ state: 'running', runStatus: 'running', decision: null, costUsd: 1.1 });
    const r = check({ rec, after, rows, view, api });
    expect(row(r, 'cost').verdict).toBe('match');
    expect(r.disagreements).toEqual([]);
    const beyond = check({ rec, after, rows, view: { ...view, costs: [{ place: 'Spend', value: '$1.30' }] }, api });
    expect(row(beyond, 'cost').verdict).toBe('mismatch');
  });
});

describe("Temper's records that disagree with each other", () => {
  it('cost: the page is judged by the recorded model calls; a run list total of $0.0 is listed for temper, and exits 0', () => {
    const rec = records({ costUsd: 0, detail: { ...records().detail!, costUsd: 0 } });
    const r = check({ rec });
    expect(mismatches(r)).toEqual([]);
    expect(row(r, 'cost').verdict).toBe('match');
    expect(r.disagreements).toEqual([
      {
        project: ID,
        workflow: 'team-trial-aaaa',
        field: 'cost',
        judgedBy: [{ record: 'recorded model calls (turns record, summed)', value: '$3.456789' }],
        differ: [
          { record: 'run list total_cost_usd', value: '$0.0' },
          { record: 'run total_cost_usd', value: '$0.0' },
        ],
        agree: ['node cost_usd'],
        owner: 'temper',
      },
    ]);
    expect(exitCode(r)).toBe(0);
  });

  it("result: the run's stopped.reason holds other words than the team's stop record; listed, the page still right", () => {
    const r = check(stopped({ rec: { detail: { ...stopped().rec!.detail!, stoppedReason: 'Workflow cancelled by user' } } }));
    expect(mismatches(r)).toEqual([]);
    expect(r.disagreements).toEqual([
      {
        project: ID,
        workflow: 'team-trial-aaaa',
        field: 'result',
        judgedBy: [{ record: "stop words (the team's stop record, by temper)", value: WORDS }],
        differ: [{ record: 'stopped.reason', value: 'Workflow cancelled by user' }],
        agree: ['error_message'],
        owner: 'temper',
      },
    ]);
    expect(exitCode(r)).toBe(0);
  });
});

describe('each planted break is caught at its own field', () => {
  it('a cost one cent off', () => {
    const r = check({ rows: [listRow({ cost: '$3.47' })] });
    expect(mismatches(r)).toEqual([`${ID}:cost`]);
    expect(row(r, 'cost').gaps).toEqual(['the Team list shows $3.47; the recorded model calls (turns record) sum to $3.456789']);
    expect(row(r, 'cost').cause).toBe('page bug');
    expect(exitCode(r)).toBe(1);
  });

  it('a page that shows the run list\'s $0.0 instead of what the model calls cost', () => {
    const rec = records({ costUsd: 0, detail: { ...records().detail!, costUsd: 0 } });
    const rows = [listRow({ cost: '$0.00' })];
    const view = runView({ costs: [{ place: 'Spend', value: '$0.00' }] });
    const r = check({ rec, rows, view });
    expect(mismatches(r)).toEqual([`${ID}:cost`]);
    expect(row(r, 'cost').gaps).toEqual([
      'the Team list shows $0.00; the recorded model calls (turns record) sum to $3.456789',
      "the run view's Spend shows $0.00; the recorded model calls (turns record) sum to $3.456789",
    ]);
    expect(r.disagreements.map((d) => `${d.project}:${d.field}`)).toEqual([`${ID}:cost`]);
    expect(exitCode(r)).toBe(1);
  });

  it("a member's cost one cent off", () => {
    const view = runView({ members: [{ name: 'lead', role: 'product', leader: true, cost: '$1.24', stateWord: 'Ended' }, runView().members![1]] });
    const r = check({ view });
    expect(mismatches(r)).toEqual([`${ID}:cost`]);
    expect(row(r, 'cost').gaps).toEqual(['the run view shows lead $1.24; its recorded model calls (turns record) sum to $1.234567']);
  });

  it('a missing member', () => {
    const rows = [listRow({ members: [listRow().members[0]] })];
    const r = check({ rows, api: teamApi({ members: [teamApi().members![0]] }) });
    expect(mismatches(r)).toEqual([`${ID}:members`]);
    expect(row(r, 'members').gaps).toEqual(["the Team list doesn't show member tester"]);
    expect(row(r, 'members').cause).toBe('Team API bug');
  });

  it("a leader the page doesn't mark", () => {
    const view = runView({ members: [{ ...runView().members![0], leader: false }, runView().members![1]] });
    const r = check({ view });
    expect(mismatches(r)).toEqual([`${ID}:members`]);
    expect(row(r, 'members').gaps).toEqual(["the run view doesn't mark lead as the leader"]);
    expect(row(r, 'members').cause).toBe('page bug');
  });

  it('a wrong state', () => {
    const r = check({ rows: [listRow({ stateWord: 'Failed' })] });
    expect(mismatches(r)).toEqual([`${ID}:state`]);
    expect(row(r, 'state').gaps).toEqual(['the Team list says Failed; record: run list completed, decision done']);
  });

  it('a "run list: X" phrase that isn\'t what the run list says', () => {
    const rec = records({ status: 'cancelled', detail: { ...records().detail!, status: 'cancelled', decision: null, stoppedReason: 'stopped by hand' } });
    const rows = [listRow({ stateWord: 'Stopped', runListWord: 'failed' })];
    const view = runView({ stateWord: 'Stopped', outcomeWord: 'Stopped', outcomeText: 'Stopped\nstopped by hand' });
    const r = check({ rec, rows, view, api: teamApi({ state: 'stopped', runStatus: 'cancelled', decision: 'cancelled', reason: 'stopped by hand' }) });
    expect(mismatches(r)).toEqual([`${ID}:state`]);
    expect(row(r, 'state').gaps).toEqual(['the Team list says "run list: failed"; the run list says cancelled']);
  });

  it('an open wait the page hides', () => {
    const rec = records({ openWaits: [{ node: 'trial', asker: 'tester' }], waitingDecisions: 1 });
    const r = check({ rec, api: teamApi({ openWaits: 1 }) });
    expect(mismatches(r)).toEqual([`${ID}:waits`]);
    expect(row(r, 'waits').gaps).toEqual([
      'the Team list shows no "needs you"; 1 gate is open',
      'the run view says nothing needs you; 1 gate is open',
    ]);
    expect(row(r, 'waits').cause).toBe('page bug');
  });

  it('a wait shown as asked by the wrong member', () => {
    const rec = records({ openWaits: [{ node: 'trial', asker: 'tester' }], waitingDecisions: 1 });
    const rows = [listRow({ needsYou: true })];
    const view = runView({ waits: { any: true, count: 1, from: ['lead'] } });
    const r = check({ rec, rows, view, api: teamApi({ openWaits: 1 }) });
    expect(mismatches(r)).toEqual([`${ID}:waits`]);
    expect(row(r, 'waits').gaps).toEqual([
      "the run view doesn't say the first wait is from tester",
      'the run view says a wait is from lead; no open gate was asked by lead',
    ]);
  });

  it("a wrong result: the reason the records hold isn't shown", () => {
    const rec = records({
      status: 'cancelled',
      detail: { ...records().detail!, status: 'cancelled', decision: 'stopped', outputReason: 'stopped at the pause after round 3', errorMessage: 'stopped at the pause after round 3' },
      stop: { from: 'stop answer', by: 'owner', words: null, at: null },
    });
    const view = runView({ stateWord: 'Stopped', outcomeWord: 'Stopped', outcomeReason: 'stopped at the pause after round 2', outcomeText: "Stopped\nTemper's reason\nstopped at the pause after round 2" });
    const rows = [listRow({ stateWord: 'Stopped', runListWord: 'cancelled' })];
    const api = teamApi({ state: 'stopped', runStatus: 'cancelled', decision: 'stopped', reason: 'stopped at the pause after round 3' });
    const r = check({ rec, view, rows, api });
    expect(mismatches(r)).toEqual([`${ID}:result`]);
    expect(row(r, 'result').gaps).toEqual([
      'the run view doesn\'t show the reason "stopped at the pause after round 3" (workflow_output.reason); it says "stopped at the pause after round 2"',
    ]);
    expect(row(r, 'result').cause).toBe('page bug');
    expect(r.disagreements).toEqual([]);
  });

  it("a team outcome record that differs from the run's record: two records disagree", () => {
    const rec = records({
      status: 'cancelled',
      detail: { ...records().detail!, status: 'cancelled', decision: null, stoppedReason: 'the time slot ran out' },
    });
    const view = runView({ stateWord: 'Stopped', outcomeWord: 'Stopped', outcomeReason: 'The run was cancelled', outcomeText: 'Stopped\nThe run was cancelled' });
    const rows = [listRow({ stateWord: 'Stopped', runListWord: 'cancelled' })];
    const api = teamApi({ state: 'stopped', runStatus: 'cancelled', decision: 'cancelled', reason: 'the run was cancelled' });
    const r = check({ rec, view, rows, api });
    expect(mismatches(r)).toEqual([`${ID}:result`]);
    expect(row(r, 'result').cause).toBe('engine record bug');
    expect(row(r, 'result').why).toContain('"the run was cancelled"');
    expect(row(r, 'result').why).toContain('"the time slot ran out" (stopped.reason)');
  });

  it('stop words that differ from the stop record', () => {
    const r = check(stopped({ view: { stopWords: [{ label: "temper's words", words: 'Other words entirely.' }] } }));
    expect(mismatches(r)).toEqual([`${ID}:result`]);
    expect(row(r, 'result').gaps).toEqual([
      `the run view's stop words are "Other words entirely." under "temper's words"; the record holds "${WORDS}" (the team's stop record, by temper)`,
    ]);
    expect(row(r, 'result').cause).toBe('page bug');
    expect(exitCode(r)).toBe(1);
  });

  it('stop words in other letters are other words', () => {
    const r = check(stopped({ view: { stopWords: [{ label: "temper's words", words: WORDS.toLowerCase() }] } }));
    expect(mismatches(r)).toEqual([`${ID}:result`]);
  });

  it('a stopped run whose page drops its stop words', () => {
    const r = check(stopped({ view: { stopWords: [] } }));
    expect(mismatches(r)).toEqual([`${ID}:result`]);
    expect(row(r, 'result').gaps).toEqual([`the run view doesn't show the stop words "${WORDS}" (the team's stop record, by temper)`]);
    expect(row(r, 'result').cause).toBe('page bug');
  });

  it('stop words under a caption that names someone else', () => {
    const r = check(stopped({ view: { stopWords: [{ label: 'Your words', words: WORDS }] } }));
    expect(mismatches(r)).toEqual([`${ID}:result`]);
    expect(row(r, 'result').gaps).toEqual([`the run view puts the stop words under "Your words"; they are from temper ("temper's words")`]);
    const unknown = check(stopped({ rec: { stop: { from: 'stop', by: 'unknown caller', words: WORDS, at: null } }, view: { stopWords: [{ label: 'Your words', words: WORDS }] } }));
    expect(row(unknown, 'result').gaps).toEqual([`the run view puts the stop words under "Your words"; they are from unknown caller ("Words from an unknown caller")`]);
  });

  it("stop words the Team API serves wrong: the team's outcome record and its stop record disagree", () => {
    const r = check(stopped({ view: { stopWords: [{ label: "temper's words", words: 'Other words.' }] }, api: { ownerWords: 'Other words.' } }));
    expect(mismatches(r)).toEqual([`${ID}:result`]);
    expect(row(r, 'result').cause).toBe('engine record bug');
    expect(row(r, 'result').why).toContain(`the team's outcome record holds the stop words "Other words."; the team's stop record holds "${WORDS}"`);
  });

  it('stop words on a run nobody stopped', () => {
    const r = check({ view: runView({ stopWords: [{ label: 'Your words', words: 'Stray words.' }] }) });
    expect(mismatches(r)).toEqual([`${ID}:result`]);
    expect(row(r, 'result').gaps).toEqual(['the run view shows stop words "Stray words." under "Your words"; no stop is recorded for this run']);
  });

  it("a missing Project row, and the list's count", () => {
    const r = check({ rows: [], listTotal: 0, api: teamApi({ listed: false }) });
    expect(mismatches(r)).toEqual([`${ID}:listed`, '(all):listed']);
    expect(row(r, 'listed').cause).toBe('Team API bug');
    expect(row(r, 'listed', '(all)').gaps).toEqual(['the Team list says it has 0 Projects; the run list has 1 team-trial-* runs']);
  });

  it("an extra Project row the run list doesn't have", () => {
    const r = check({ rows: [listRow(), listRow({ executionId: OTHER })], listTotal: 2 });
    expect(mismatches(r)).toEqual([`${OTHER}:listed`, '(all):listed']);
    expect(row(r, 'listed', OTHER).gaps).toEqual([`the Team list shows ${OTHER}; the run list has no team-trial-* run with that id`]);
  });

  it("a run view that didn't load is a mismatch, never a quiet pass", () => {
    const view = runView({ problem: 'the run view showed neither a Status band nor a Members card in 45 s', members: null, waits: null, costs: [], stateWord: null, outcomeWord: null, outcomeText: null });
    const r = check({ view });
    expect(mismatches(r)).toEqual([`${ID}:members`, `${ID}:state`, `${ID}:result`, `${ID}:memberWork`]);
  });
});

/** A running Project: lead's turn under way, tester waiting; the records read before and after the page. */
function running(over: { rec?: Partial<ProjectRecords>; after?: Partial<ProjectRecords> | null; lead?: string; tester?: string; api?: Partial<TeamApiProject> } = {}): Parts {
  const live = { status: 'running', detail: { ...records().detail!, status: 'running', decision: null } };
  const turns = { lead: { turns: 2, costUsd: 1.234567, running: 1 }, tester: { turns: 1, costUsd: 2.222222, running: 0 } };
  return {
    rec: records({ ...live, turns, ...over.rec }),
    after: over.after === null ? undefined : records({ ...live, turns, ...over.after }),
    rows: [listRow({ stateWord: 'Running' })],
    view: runView({
      stateWord: 'Running',
      outcomeWord: null,
      outcomeText: null,
      members: [
        { name: 'lead', role: 'product', leader: true, cost: '$1.23', stateWord: over.lead ?? 'Working' },
        { name: 'tester', role: 'qa', leader: false, cost: '$2.22', stateWord: over.tester ?? 'Idle' },
      ],
    }),
    api: teamApi({
      state: 'running',
      runStatus: 'running',
      decision: null,
      members: [
        { name: 'lead', role: 'product', leader: true, costUsd: 1.234567, state: 'working' },
        { name: 'tester', role: 'qa', leader: false, costUsd: 2.222222, state: 'idle' },
      ],
      ...over.api,
    }),
  };
}

describe('whether each member card says Working when its turn runs (memberWork)', () => {
  it('reads the chips that mean at work', () => {
    expect(pageWorking('Working')).toBe(true);
    expect(pageWorking('Working on a retry')).toBe(true);
    expect(pageWorking('Finishing its turn')).toBe(true);
    for (const w of ['Idle', 'Ready', 'Paused: your answer', 'Needs you', 'Turn failed', 'Waiting for the leader', 'Has the goal', 'Ended', 'Waiting on you', 'State not known', '', null]) {
      expect(pageWorking(w)).toBe(false);
    }
  });

  it('a working member whose turn runs, and an idle one whose turn does not: match', () => {
    const r = check(running());
    expect(mismatches(r)).toEqual([]);
    expect(row(r, 'memberWork').verdict).toBe('match');
    expect(row(r, 'memberWork').page).toBe('lead Working, tester Idle');
    expect(row(r, 'memberWork').record).toBe('turns running (turns record): lead; second read: lead');
    expect(row(check(running({ lead: 'Finishing its turn', tester: 'Ready' })), 'memberWork').verdict).toBe('match');
  });

  it('a stale Working with no running turn: page bug when the Team API agrees with the record', () => {
    const stale = { lead: { turns: 2, costUsd: 1.234567, running: 0 }, tester: { turns: 1, costUsd: 2.222222, running: 0 } };
    const api = { members: [{ name: 'lead', role: 'product', leader: true, costUsd: 1.234567, state: 'idle' }, teamApi().members![1]] };
    const r = check(running({ rec: { turns: stale }, after: { turns: stale }, api }));
    expect(mismatches(r)).toEqual([`${ID}:memberWork`]);
    expect(row(r, 'memberWork').gaps).toEqual(['the run view says lead is Working; the turns record has no turn of lead running in either read']);
    expect(row(r, 'memberWork').cause).toBe('page bug');
    expect(exitCode(r)).toBe(1);
  });

  it("a stale Working the Team API serves too: Team API bug", () => {
    const stale = { lead: { turns: 2, costUsd: 1.234567, running: 0 }, tester: { turns: 1, costUsd: 2.222222, running: 0 } };
    const r = check(running({ rec: { turns: stale }, after: { turns: stale } }));
    expect(mismatches(r)).toEqual([`${ID}:memberWork`]);
    expect(row(r, 'memberWork').cause).toBe('Team API bug');
    expect(row(r, 'memberWork').why).toBe("the Team API's member states agree with the page: lead working");
  });

  it('a running turn whose card does not say Working: page bug', () => {
    const r = check(running({ lead: 'Idle' }));
    expect(mismatches(r)).toEqual([`${ID}:memberWork`]);
    expect(row(r, 'memberWork').gaps).toEqual(['the run view says lead is Idle; the turns record has a turn of lead running in either read']);
    expect(row(r, 'memberWork').cause).toBe('page bug');
  });

  it('a turn that started or ended between the reads may show either way', () => {
    const idle = { lead: { turns: 2, costUsd: 1.234567, running: 0 }, tester: { turns: 1, costUsd: 2.222222, running: 0 } };
    const startedTester = { ...idle, tester: { turns: 2, costUsd: 2.222222, running: 1 } };
    // tester's turn started between the reads: Working and Idle both match.
    expect(mismatches(check(running({ rec: { turns: idle }, after: { turns: startedTester }, lead: 'Idle', tester: 'Working' })))).toEqual([]);
    expect(mismatches(check(running({ rec: { turns: idle }, after: { turns: startedTester }, lead: 'Idle', tester: 'Idle' })))).toEqual([]);
    // lead's turn ended between the reads: Working and Idle both match.
    expect(mismatches(check(running({ after: { turns: idle }, lead: 'Working' })))).toEqual([]);
    expect(mismatches(check(running({ after: { turns: idle }, lead: 'Idle' })))).toEqual([]);
    // A whole turn of tester between the reads (started and ended): either way.
    const oneMore = { ...idle, tester: { turns: 2, costUsd: 2.3, running: 0 } };
    expect(mismatches(check(running({ rec: { turns: idle }, after: { turns: oneMore }, lead: 'Idle', tester: 'Working' })))).toEqual([]);
    // Without a second read, the one read decides.
    const one = check(running({ after: null, lead: 'Idle' }));
    expect(row(one, 'memberWork').gaps).toEqual(['the run view says lead is Idle; the turns record has a turn of lead running']);
  });

  it("agents that couldn't be read: no record", () => {
    const r = check(running({ rec: { turns: null }, after: { turns: null } }));
    expect(row(r, 'memberWork').verdict).toBe('no record');
    expect(row(r, 'memberWork').why).toContain('GET /api/workflows/{id}/agents');
    expect(exitCode(r)).toBe(1);
  });

  it('an ended Project: every card not at work; a Working card is a mismatch', () => {
    const r = check();
    expect(row(r, 'memberWork').verdict).toBe('match');
    expect(row(r, 'memberWork').record).toBe('ended (run list: completed): no member at work');
    const view = runView({ members: [{ ...runView().members![0], stateWord: 'Working' }, runView().members![1]] });
    const bad = check({ view });
    expect(mismatches(bad)).toEqual([`${ID}:memberWork`]);
    expect(row(bad, 'memberWork').gaps).toEqual(['the run view says lead is Working; the run has ended (run list: completed)']);
    expect(row(bad, 'memberWork').cause).toBe('page bug');
  });

  it("an ended run's turns record that still holds a turn as running: listed for temper, the page still right", () => {
    const rec = records({ turns: { lead: { turns: 2, costUsd: 1.234567, running: 1 }, tester: { turns: 1, costUsd: 2.222222 } } });
    const r = check({ rec });
    expect(mismatches(r)).toEqual([]);
    expect(r.disagreements).toEqual([
      {
        project: ID,
        workflow: 'team-trial-aaaa',
        field: 'memberWork',
        judgedBy: [{ record: 'run list status', value: 'completed' }],
        differ: [{ record: 'turns record (GET /api/workflows/{id}/agents)', value: 'turns still running: lead' }],
        agree: [],
        owner: 'temper',
      },
    ]);
    expect(exitCode(r)).toBe(0);
  });

  it('a card without a state chip is a mismatch, never a quiet pass', () => {
    const view = runView({ members: [{ ...runView().members![0], stateWord: null }, runView().members![1]] });
    const r = check({ view });
    expect(mismatches(r)).toEqual([`${ID}:memberWork`]);
    expect(row(r, 'memberWork').gaps).toEqual(["the run view's card for lead shows no state"]);
  });
});

describe('missing records', () => {
  it('says "no record" instead of comparing the Team API with itself, and fails: a field without its record is unchecked', () => {
    const rec = records({ members: null, turns: null, openWaits: null, waitingDecisions: null });
    const r = check({ rec });
    expect(row(r, 'members').verdict).toBe('no record');
    expect(row(r, 'waits').verdict).toBe('no record');
    expect(row(r, 'cost').verdict).toBe('no record');
    expect(row(r, 'memberWork').verdict).toBe('no record');
    expect(r.totals['no record']).toBe(4);
    expect(r.disagreements).toEqual([]);
    expect(exitCode(r)).toBe(1);
  });

  it("a stopped run whose team record couldn't be read: its stop words aren't known", () => {
    const r = check(stopped({ rec: { stop: null, stopRead: false } }));
    expect(row(r, 'result').verdict).toBe('no record');
    expect(row(r, 'result').why).toContain("the team's stop record");
    expect(exitCode(r)).toBe(1);
  });
});

describe('only some Projects asked for', () => {
  it('checks those and leaves the rest of the list alone', () => {
    const input: CheckInput = {
      base: 'http://127.0.0.1:8420',
      at: '2026-10-19T12:00:00Z',
      runListTotal: 40,
      records: { [ID]: records(), [OTHER]: records({ executionId: OTHER, workflow: 'team-trial-bbbb' }) },
      page: { listTotal: 5, rows: [listRow(), listRow({ executionId: 'cccccccc-0000-4000-8000-000000000003' })], views: { [ID]: runView() } },
      teamApi: { [ID]: teamApi() },
      only: [ID],
    };
    const r = compareAll(input);
    expect(r.projects).toEqual([ID]);
    expect(mismatches(r)).toEqual([]);
    expect(r.rows.some((x) => x.project === '(all)')).toBe(false);
  });
});

describe('the Markdown report', () => {
  it('puts each gap first, with both values and its likely cause, then every row and the field table', () => {
    const md = toMarkdown(check({ rows: [listRow({ cost: '$3.47' })] }));
    expect(md).toContain('1 mismatch');
    expect(md).toContain(
      '| aaaaaaaa | cost | mismatch | the Team list shows $3.47; the recorded model calls (turns record) sum to $3.456789 | page bug: the Team API says $3.456789, as the recorded model calls (turns record) do |',
    );
    expect(md).toContain("## Temper's records disagree");
    expect(md).toContain("None: Temper's records agree with each other.");
    expect(md).toContain('## Every Project and field');
    expect(md).toContain('## Where each field comes from');
    expect(md).toContain('Exit 1');
  });

  it("lists Temper's records that disagree apart, with each value and the temper role, and exits 0", () => {
    const md = toMarkdown(check({ rec: records({ costUsd: 0, detail: { ...records().detail!, costUsd: 0 } }) }));
    expect(md).toContain('0 mismatch');
    expect(md).toContain("Temper's records disagree: 1");
    expect(md).toContain('| aaaaaaaa | cost | recorded model calls (turns record, summed): $3.456789 | run list total_cost_usd: $0.0<br>run total_cost_usd: $0.0 | node cost_usd | temper |');
    expect(md).toContain('Exit 0');
  });
});
