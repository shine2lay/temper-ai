/**
 * The comparing half of the Team page truth check (scripts/teamPageTruth.ts, run by
 * scripts/team-page-truth.mjs).
 *
 * The check reads the Team page as a person sees it and compares five fields per Project
 * (members, state, waits, cost so far, result) with Temper's lower-level records. These tests
 * feed it made-up Projects whose right answers are known: a clean one must match everywhere,
 * and each planted break must be caught at its own field, with both values in the report.
 */
import { describe, expect, it } from 'vitest';

import {
  compareAll,
  exitCode,
  genuineReason,
  pageStateClass,
  parseMoney,
  recordStateClass,
  sameCent,
  showsReason,
  stateAgrees,
  toMarkdown,
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
    detail: { status: 'completed', costUsd: 3.456789, nodeCostUsd: 3.456789, decision: 'done', reason: null, reasonFrom: null },
    turns: { lead: { turns: 2, costUsd: 1.234567 }, tester: { turns: 1, costUsd: 2.222222 } },
    members: [
      { name: 'lead', role: 'product', leader: true },
      { name: 'tester', role: 'qa', leader: false },
    ],
    openWaits: [],
    waitingDecisions: 0,
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
      { name: 'lead', role: 'product', leader: true, cost: '$1.23' },
      { name: 'tester', role: 'qa', leader: false, cost: '$2.22' },
    ],
    costs: [{ place: 'Spend', value: '$3.46' }],
    waits: { any: false, count: 0, from: [] },
    outcomeWord: 'Done',
    outcomeReason: null,
    outcomeText: 'Done',
    ...over,
  };
}

function teamApi(over: Partial<TeamApiProject> = {}): TeamApiProject {
  return {
    listed: true,
    members: [
      { name: 'lead', role: 'product', leader: true, costUsd: 1.234567 },
      { name: 'tester', role: 'qa', leader: false, costUsd: 2.222222 },
    ],
    state: 'done',
    runStatus: 'completed',
    costUsd: 3.456789,
    openWaits: 0,
    decision: 'done',
    reason: null,
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
});

describe('a Project whose page shows what its records hold', () => {
  it('matches every field and exits 0', () => {
    const r = check();
    expect(mismatches(r)).toEqual([]);
    expect(r.totals).toEqual({ match: 7, mismatch: 0, 'no record': 0 });
    expect(r.rows.map((x) => x.field)).toEqual(['listed', 'members', 'state', 'waits', 'cost', 'result', 'listed']);
    expect(exitCode(r)).toBe(0);
  });

  it('leaves out a role the page doesn\'t repeat when it equals the name', () => {
    const rec = records({
      members: [
        { name: 'lead', role: 'lead', leader: true },
        { name: 'tester', role: 'qa', leader: false },
      ],
    });
    const rows = [listRow({ members: [{ name: 'lead', role: null, leader: true, cost: null }, listRow().members[1]] })];
    const view = runView({ members: [{ name: 'lead', role: null, leader: true, cost: '$1.23' }, runView().members![1]] });
    expect(mismatches(check({ rec, rows, view }))).toEqual([]);
    const wrongRole = runView({ members: [{ name: 'lead', role: 'product', leader: true, cost: '$1.23' }, runView().members![1]] });
    expect(row(check({ rec, rows, view: wrongRole }), 'members').gaps).toEqual(["the run view shows lead's role as product; record: lead"]);
  });

  it('accepts a running Project\'s cost anywhere between two reads of its records', () => {
    const live = { status: 'running', detail: null } as const;
    const rec = records({ ...live, costUsd: 1.0, turns: null });
    const after = records({ ...live, costUsd: 1.2, turns: null });
    const view = runView({ stateWord: 'Running', outcomeWord: null, outcomeText: null, costs: [{ place: 'Spend', value: '$1.10' }], members: null });
    const rows = [listRow({ stateWord: 'Running', cost: '$1.05' })];
    const r = check({ rec, after, rows, view, api: teamApi({ state: 'running', runStatus: 'running', decision: null }) });
    expect(row(r, 'cost').verdict).toBe('match');
    const beyond = check({ rec, after, rows, view: { ...view, costs: [{ place: 'Spend', value: '$1.30' }] } });
    expect(row(beyond, 'cost').verdict).toBe('mismatch');
  });
});

describe('each planted break is caught at its own field', () => {
  it('a cost one cent off', () => {
    const r = check({ rows: [listRow({ cost: '$3.47' })] });
    expect(mismatches(r)).toEqual([`${ID}:cost`]);
    expect(row(r, 'cost').gaps.join(' ')).toContain('the Team list shows $3.47; the run list\'s total_cost_usd is $3.456789');
    expect(row(r, 'cost').cause).toBe('page bug');
    expect(exitCode(r)).toBe(1);
  });

  it('a member\'s cost one cent off', () => {
    const view = runView({ members: [{ name: 'lead', role: 'product', leader: true, cost: '$1.24' }, runView().members![1]] });
    const r = check({ view });
    expect(mismatches(r)).toEqual([`${ID}:cost`]);
    expect(row(r, 'cost').gaps).toEqual(['the run view shows lead $1.24; its turns (agents record) cost $1.234567']);
  });

  it('records that disagree with each other: both named, none picked', () => {
    const rec = records({ costUsd: 0, detail: { ...records().detail!, costUsd: 0 } });
    const r = check({ rec });
    expect(mismatches(r)).toEqual([`${ID}:cost`]);
    const cost = row(r, 'cost');
    expect(cost.cause).toBe('engine record bug');
    expect(cost.why).toContain('run list total_cost_usd $0.0');
    expect(cost.why).toContain('turns (agents) sum $3.456789');
    expect(cost.why).toContain("the temper role's call");
  });

  it('a missing member', () => {
    const rows = [listRow({ members: [listRow().members[0]] })];
    const r = check({ rows, api: teamApi({ members: [teamApi().members![0]] }) });
    expect(mismatches(r)).toEqual([`${ID}:members`]);
    expect(row(r, 'members').gaps).toEqual(["the Team list doesn't show member tester"]);
    expect(row(r, 'members').cause).toBe('Team API bug');
  });

  it('a leader the page doesn\'t mark', () => {
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
    const rec = records({ status: 'cancelled', detail: { ...records().detail!, status: 'cancelled', decision: null, reason: 'stopped by hand', reasonFrom: 'stopped.reason' } });
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

  it('a wrong result: the reason the records hold isn\'t shown', () => {
    const rec = records({
      status: 'cancelled',
      detail: { ...records().detail!, status: 'cancelled', decision: 'stopped', reason: 'stopped at the pause after round 3', reasonFrom: 'workflow_output.reason' },
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
  });

  it("a team outcome record that differs from the run's record: two records disagree", () => {
    const rec = records({
      status: 'cancelled',
      detail: { ...records().detail!, status: 'cancelled', decision: null, reason: 'the stage window ended', reasonFrom: 'stopped.reason' },
    });
    const view = runView({ stateWord: 'Stopped', outcomeWord: 'Stopped', outcomeReason: 'The run was cancelled', outcomeText: 'Stopped\nThe run was cancelled' });
    const rows = [listRow({ stateWord: 'Stopped', runListWord: 'cancelled' })];
    const api = teamApi({ state: 'stopped', runStatus: 'cancelled', decision: 'cancelled', reason: 'the run was cancelled' });
    const r = check({ rec, view, rows, api });
    expect(mismatches(r)).toEqual([`${ID}:result`]);
    expect(row(r, 'result').cause).toBe('engine record bug');
    expect(row(r, 'result').why).toContain('"the run was cancelled"');
    expect(row(r, 'result').why).toContain('"the stage window ended" (stopped.reason)');
  });

  it('a missing Project row, and the list\'s count', () => {
    const r = check({ rows: [], listTotal: 0, api: teamApi({ listed: false }) });
    expect(mismatches(r)).toEqual([`${ID}:listed`, '(all):listed']);
    expect(row(r, 'listed').cause).toBe('Team API bug');
    expect(row(r, 'listed', '(all)').gaps).toEqual(['the Team list says it has 0 Projects; the run list has 1 team-trial-* runs']);
  });

  it('an extra Project row the run list doesn\'t have', () => {
    const r = check({ rows: [listRow(), listRow({ executionId: OTHER })], listTotal: 2 });
    expect(mismatches(r)).toEqual([`${OTHER}:listed`, '(all):listed']);
    expect(row(r, 'listed', OTHER).gaps).toEqual([`the Team list shows ${OTHER}; the run list has no team-trial-* run with that id`]);
  });

  it('a run view that didn\'t load is a mismatch, never a quiet pass', () => {
    const view = runView({ problem: 'the run view showed neither a Status band nor a Members card in 45 s', members: null, waits: null, costs: [], stateWord: null, outcomeWord: null, outcomeText: null });
    const r = check({ view });
    expect(mismatches(r)).toEqual([`${ID}:members`, `${ID}:state`, `${ID}:result`]);
  });
});

describe('missing records', () => {
  it('says "no record" instead of comparing the Team API with itself, and doesn\'t fail for it', () => {
    const rec = records({ members: null, turns: null, openWaits: null, waitingDecisions: null });
    const r = check({ rec });
    expect(row(r, 'members').verdict).toBe('no record');
    expect(row(r, 'waits').verdict).toBe('no record');
    expect(r.totals['no record']).toBe(2);
    expect(exitCode(r)).toBe(0);
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
    expect(md).toContain("| aaaaaaaa | cost | mismatch | the Team list shows $3.47; the run list's total_cost_usd is $3.456789 | page bug: the Team API says $3.456789, as the records do |");
    expect(md).toContain('## Every Project and field');
    expect(md).toContain('## Where each field comes from');
  });
});
