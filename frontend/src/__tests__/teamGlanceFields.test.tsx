/** Final FLOW fields, D114-D119 and D121. Known-answer contracts, no server/model. */
import { render, cleanup } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MomentText } from '@/components/team/glance/glanceUi';
import { NowVersion } from '@/components/team/glance/NowVersion';
import { teamRunPollingEnded } from '@/hooks/useTeamRun';
import { flowRunEnded, toGlanceEvent, toGlanceEventPage, toGlanceRun } from '@/lib/teamGlanceAdapter';
import {
  activityRow, activityRows, fileNameParts, latestMoments, memberChip, memberLine,
  nowCell, phaseEnded, runningWords, spendCell, starterAttribution, youCell, type GlanceEvent, type Moment,
} from '@/lib/teamGlance';
import type { TeamRun } from '@/types/team';

type Raw = Record<string, unknown>;
const ROOT = '../../e2e/fixtures/team/flow/';
const JSONS = {
  ...import.meta.glob<Raw>('../../e2e/fixtures/team/flow/real-g7/*.json', { eager: true, import: 'default' }),
  ...import.meta.glob<Raw>('../../e2e/fixtures/team/flow/real-g6/*.json', { eager: true, import: 'default' }),
  ...import.meta.glob<Raw>('../../e2e/fixtures/team/flow/real/*.json', { eager: true, import: 'default' }),
};
const TEXT = import.meta.glob<string>('../../e2e/fixtures/team/flow/real-g7/*', { eager: true, query: '?raw', import: 'default' });
const copy = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
function raw(name: string, feed = false): Raw {
  const v = JSONS[`${ROOT}${name}${feed ? '-events' : ''}.json`];
  if (!v) throw new Error(`no sample ${name}`);
  return copy(v);
}
function event(v: Raw): GlanceEvent {
  const e = toGlanceEvent(v);
  if (!e) throw new Error('no event');
  return e;
}
const text = (m: Moment) => m.parts.map((p) => p.text).join('');
const base = () => toGlanceRun(raw('real-g6/conflict'));
const refusal = (extra: Raw = {}) => event({ seq: 24, kind: 'share_refused', member: 'checker', why: 'refused', reason: null, paths: [], ...extra });
const refusalText = (extra: Raw = {}) => text(activityRow(refusal(extra), base()));
function lists(name: string, change?: (events: Raw[]) => void) {
  const r = toGlanceRun(raw(name));
  const feed = raw(name, true);
  change?.(feed.events as Raw[]);
  const events = toGlanceEventPage(feed, 0).events;
  return {
    all: activityRows(events, r).map(text),
    latest: latestMoments(events, r.leader, 1000, false, new Set(r.members.map((m) => m.name)), r).map(text),
  };
}
afterEach(() => { cleanup(); vi.unstubAllEnvs(); });

it('D121 has no future-version promise in Now; ordinary starting/empty keeps its existing words', () => {
  const { getByTestId, rerender } = render(<NowVersion latest={null} agesAt={null} failedToStart />);
  expect(getByTestId('glance-version').textContent).toBe('No shared version.');
  rerender(<NowVersion latest={null} agesAt={null} />);
  expect(getByTestId('glance-version').textContent).toBe('No shared version yet.');
});

const G7 = ['starting', 'check_in_not_asked', 'draining', 'stopped', 'stopped_check_in', 'failed', 'didnt_start'] as const;
async function sha(s: string) {
  const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s));
  return [...new Uint8Array(bytes)].map((n) => n.toString(16).padStart(2, '0')).join('');
}
describe('G7 hash-bound real serializer pairs', () => {
  it('pins the manifest and all fourteen sample lines; seven exact pairs, no extra file', async () => {
    const root = ROOT + 'real-g7/';
    const manifest = TEXT[root + 'G7-INPUTS.sha256'];
    expect(await sha(manifest)).toBe('330b21cdff6123de4906332257b7c512f3adf39daa7a295892b61bd3f405a85d');
    const all = manifest.trim().split('\n');
    expect(all[0]).toMatch(/^# backend f928ed03/); // one comment line, then the hash lines
    const lines = all.filter((l) => !l.startsWith('#'));
    expect(lines).toHaveLength(15); // the exporter's line (checked privately, not part of the frontend) and 14 samples
    const pairs = lines.map((l) => /^([0-9a-f]{64}) [ *]api-fixtures-g7\/(.+)$/.exec(l)).filter((m) => m !== null);
    expect(pairs).toHaveLength(14);
    for (const m of pairs) expect(await sha(TEXT[root + m[2]]), m[2]).toBe(m[1]);
    expect(Object.keys(TEXT).map((p) => p.slice(root.length)).sort()).toEqual(['G7-INPUTS.sha256', ...G7.flatMap((n) => [n + '.json', n + '-events.json'])].sort());
  });
  it.each(G7)('%s: exact phase, known member states and feed, honest event count', (name) => {
    const body = raw('real-g7/' + name);
    const run = toGlanceRun(body);
    const feed = toGlanceEventPage(raw('real-g7/' + name, true), 0);
    expect(run.phase.name).toBe((body.phase as Raw).name);
    expect(run.phase.name).not.toBe('unknown');
    expect(run.members.map((m) => m.state)).not.toContain('unknown');
    expect(feed.events.map((e) => e.kind)).not.toContain('other');
    expect(run.eventsTotal).toBe(feed.events.length);
  });
});

describe('D114 and S2: reason and literal code file names', () => {
  it('uses the real conflict reason, not its refusal kind (seq24)', () => {
    const e = (raw('real-g6/conflict', true).events as Raw[]).find((e) => e.seq === 24)!;
    expect(e.kind).toBe('share_refused');
    // The f928ed03 export's own reason (the notice at seq 23, first sentence), shown as given.
    expect(e.reason).toBe("Not shared: these files still hold git's conflict markers: part.md");
    expect(refusalText(e)).toBe("checker’s version wasn’t shared: Not shared: these files still hold git's conflict markers: part.md");
  });
  it.each([
    [['part.md'], 'it clashes with the shared version in part.md.'],
    [['part.md', 'two.md', 'three.md'], 'it clashes with the shared version in 3 files.'],
    [[], 'it clashes with the shared version.'],
  ])('null reason, conflict paths %j has the exact fallback', (paths, reason) => {
    expect(refusalText({ why: 'conflict', paths })).toBe(`checker’s version wasn’t shared: ${reason}`);
  });
  it('null refused keeps D107; reason wins over kind and paths', () => {
    expect(refusalText()).toBe('checker’s version wasn’t shared. Temper gave no reason.');
    expect(refusalText({ why: 'conflict', reason: 'A real explanation.', paths: ['part.md'] })).toBe('checker’s version wasn’t shared: A real explanation.');
  });
  it('uses exact names longest-first, all repeats; absent names do not become code', () => {
    const parts = fileNameParts('otherpart.md, part.md and otherpart.md; absent.md', ['part.md', 'otherpart.md', 'missing.md']);
    expect(parts.filter((p) => p.code).map((p) => p.text)).toEqual(['otherpart.md', 'part.md', 'otherpart.md']);
    expect(parts.map((p) => p.text).join('')).toBe('otherpart.md, part.md and otherpart.md; absent.md');
  });
  it('renders link/bold markup and HTML as literal code/plain React text, never a link', () => {
    const name = '[part](https://evil.invalid/**bold**)<img src=x>.md';
    const row = activityRow(refusal({ reason: `Fix ${name}; then ${name}.`, paths: [name] }), base());
    const { container } = render(<MomentText parts={row.parts} />);
    expect(container.textContent).toBe(`checker’s version wasn’t shared: Fix ${name}; then ${name}.`);
    expect([...container.querySelectorAll('code')].map((n) => n.textContent)).toEqual([name, name]);
    expect(container.querySelectorAll('a,img,script')).toHaveLength(0);
    for (const code of container.querySelectorAll('code')) expect(code.className).toContain('[overflow-wrap:anywhere]');
  });
});

describe('D115, D86 and D117: who asked and who restarted', () => {
  it.each([['owner', 'You restarted the team'], ['temper', 'Temper restarted the team'], [null, 'The team carried on']])('limit_over by %s', (by, words) => {
    expect(text(activityRow(event({ kind: 'limit_over', seq: 19, at: new Date(2026, 9, 10, 21, 2).toISOString(), by }), base()))).toBe(`The usage limit is over. ${words} at 9:02 PM.`);
  });
  it('D86 null why ends cleanly, no dangling colon or empty quotation', () => {
    const row = text(activityRow(event({ kind: 'wait_answered', seq: 1, answer: 'continue', by: 'owner', wait_kind: 'pause', applied: false, why: null }), base()));
    expect(row).toBe('You answered Temper: continue. Not applied.');
  });
  it.each([
    ['pause', 'guide'],
    ['pause', 'stop'],
    ['settings', 'go on'],
  ])('Temper %s answer %s names Temper', (waitKind, answer) => {
    const row = text(activityRow(event({ kind: 'wait_answered', seq: 1, answer, by: 'owner', wait_kind: waitKind }), base()));
    expect(row).toBe(`You answered Temper: ${answer}`);
  });
  it('the restart Temper records (restart_deferred) reads restart with its D86 mark; an unlisted code word is never shown', () => {
    const restart = text(activityRow(event({ kind: 'wait_answered', seq: 1, answer: 'restart_deferred', by: 'owner', wait_kind: 'limit' }), base()));
    expect(restart).toBe('You answered Temper: restart. Not applied: Temper couldn\u2019t confirm the usage limit has reset.');
    const unlisted = text(activityRow(event({ kind: 'wait_answered', seq: 1, answer: 'restart', by: 'owner', wait_kind: 'limit' }), base()));
    expect(unlisted).toBe('You answered Temper.');
  });
  it('one member answer with text is the same named reply in Latest and All activity', () => {
    const s = lists('real-g6/member_question');
    for (const rows of [s.all, s.latest]) expect(rows.filter((r) => r.startsWith('You answered'))).toEqual(['You answered checker: “yes”']);
  });
  it.each(['empty message', 'no message'])('member answer with %s has one named period-only row', (mode) => {
    const s = lists('real-g6/member_question', (events) => {
      const i = events.findIndex((e) => e.kind === 'message' && e.from === 'owner');
      if (mode === 'empty message') events[i].text = null;
      else events.splice(i, 1);
    });
    for (const rows of [s.all, s.latest]) expect(rows.filter((r) => r.startsWith('You answered'))).toEqual(['You answered checker.']);
  });
});

describe('D118-D119: no engine token or generic reason', () => {
  it.each([
    ['done', 'team_done', 'Project ended.'], ['done', 'run_completed', 'Project ended.'],
    ['stopped', 'team_stopped', 'Stopped'], ['cancelled', 'run_cancelled', 'Cancelled'],
    ['failed', 'account_refused', 'Failed: the model account refused a call.'],
  ])('end %s with %s', (decision, reason, words) => {
    expect(text(activityRow(event({ kind: 'ended', seq: 1, decision, reason }), base()))).toBe(words);
  });
  it('completed turn is finished, cap wording is unchanged', () => {
    expect(text(activityRow(event({ kind: 'turn_end', seq: 1, member: 'checker', turn_no: 1, ended: 'completed' }), base()))).toBe('checker finished turn 1.');
    expect(text(activityRow(event({ kind: 'turn_end', seq: 1, member: 'checker', turn_no: 1, ended: 'completed', ended_by: 'time_limit' }), base()))).toBe('checker’s turn 1 ended at its time limit.');
  });
  it.each(['the run ended (interrupted) without the team ending', 'THE RUN ENDED (Other_STATUS) WITHOUT THE TEAM ENDING!!!'])('generic %s is not a reason', (reason) => {
    const body = raw('real-g6/interrupted');
    (body.phase as Raw).reason = reason;
    const run = toGlanceRun(body);
    expect(nowCell(run, Date.parse(run.asOf!)).reason).toBeUndefined();
    expect(activityRows([], run).map(text)).toEqual(['Interrupted. Temper gave no reason.']);
  });
  it('genuine reason stays verbatim in activity; Now capitalises its first letter only', () => {
    const body = raw('real-g6/interrupted');
    (body.phase as Raw).reason = 'the API timed out; CSV work is kept.';
    const run = toGlanceRun(body);
    expect(nowCell(run, null).reason).toBe('The API timed out; CSV work is kept.');
    expect(activityRows([], run).map(text)).toEqual(['Interrupted: the API timed out; CSV work is kept.']);
  });
});

describe('H11 D119: only Now explanations gain an initial capital', () => {
  it.each([
    ['stopped', 'The run was cancelled'],
    ['failed', 'Account anthropic-4 refused the call (not allowed for this organization); the team was stopped'],
  ])('real %s: first letter only, all remaining characters exact', (name, wanted) => {
    const body = raw('real-g7/' + name);
    const supplied = (body.phase as Raw).reason as string;
    expect(supplied[0]).toBe(supplied[0].toLowerCase());
    const shown = nowCell(toGlanceRun(body), null).sentence;
    expect(shown).toBe(wanted);
    expect(shown?.slice(1)).toBe(supplied.slice(1));
  });
  it.each([
    ['stopped', 'team_done', null], ['stopped', 'run_completed', null],
    ['stopped', 'team_stopped', null], ['failed', 'run_cancelled', null],
    ['failed', 'account_refused', 'The model account refused a call.'],
  ])('Now %s with %s keeps token handling/outcome; no engine word leaks', (name, reason, wanted) => {
    const body = raw('real-g7/' + name);
    (body.phase as Raw).reason = reason;
    const cell = nowCell(toGlanceRun(body), null);
    expect(cell.word).toBe(name === 'failed' ? 'Failed' : 'Stopped');
    expect(cell.sentence).toBe(wanted);
  });
  it('Interrupted remains capitalised and lowercase D121 remains exactly supplied', () => {
    const body = raw('real-g6/interrupted');
    (body.phase as Raw).reason = 'the API timed out; CSV work is kept.';
    expect(nowCell(toGlanceRun(body), null).reason).toBe('The API timed out; CSV work is kept.');
    const neverStarted = raw('real-g7/didnt_start');
    const supplied = (neverStarted.phase as Raw).reason as string;
    expect(supplied.startsWith('the team')).toBe(true);
    expect(nowCell(toGlanceRun(neverStarted), null).sentence).toBe(supplied);
  });
  it('timeline, Latest and member quotations are unchanged lowercase text', () => {
    const run = toGlanceRun(raw('real-g7/stopped'));
    const ended = event({ kind: 'ended', seq: 1, decision: 'stopped', reason: 'the run was cancelled' });
    expect(text(activityRow(ended, run))).toBe('Stopped: the run was cancelled');
    const quote = event({ kind: 'message', seq: 2, from: 'owner', to: 'lead', message_kind: 'guide', text: 'the CSV stays “as given”.' });
    expect(text(activityRow(quote, run))).toBe('You messaged lead: “the CSV stays “as given”.”');
    const rows = latestMoments([ended, quote], run.leader, 1000, false, new Set(run.members.map((m) => m.name)), run).map(text);
    expect(rows).toEqual(['Stopped: the run was cancelled']); // An ordinary guide isn't a Latest big moment.
    const all = activityRows([ended, quote], run).map(text);
    expect(all).toContain('Stopped: the run was cancelled');
    expect(all).toContain('You messaged lead: “the CSV stays “as given”.”');
  });
});

describe('G7: an unasked pause wait is not an answer request yet (D27)', () => {
  it('retains the real wait but offers no answer while turns finish; stale stays past-tense', () => {
    const run = toGlanceRun(raw('real-g7/check_in_not_asked'));
    expect(run.you.count).toBe(1);
    expect(run.you.first?.kind).toBe('pause');
    expect(youCell(run)).toMatchObject({ title: 'Nothing needs you yet', line: "You'll be asked to carry on once these turns finish.", action: null, waitId: null });
    expect(youCell(run, '15 min')).toMatchObject({ title: 'Nothing needed you 15 min ago', action: null });
    expect(youCell({ ...run, phase: { ...run.phase, asked: true } })).toMatchObject({ title: 'Needs you: carry on?', action: 'answers', waitId: run.you.first!.waitId });
    const member = { ...run, you: { count: 1, first: { ...run.you.first!, kind: 'question', member: 'checker', words: 'Use CSV?' } } };
    expect(youCell(member)).toMatchObject({ title: 'Needs you: “Use CSV?”', action: 'answer', waitId: run.you.first!.waitId });
  });
});

describe('D121: truthful failure before work starts', () => {
  const failed = () => toGlanceRun(raw('real-g7/didnt_start'));
  it('known terminal, exact words/reason, empty feed and no synthetic events', () => {
    const body = raw('real-g7/didnt_start');
    const run = failed();
    expect(run.phase.name).toBe('didnt_start');
    expect(phaseEnded(run.phase.name)).toBe(true);
    expect(flowRunEnded(body)).toBe(true);
    expect(teamRunPollingEnded(body as unknown as TeamRun)).toBe(true);
    expect(nowCell(run, null)).toMatchObject({ word: 'Failed to start', sentence: (body.phase as Raw).reason, edge: 'red', icon: 'alert', countLine: null });
    expect(nowCell(run, null).reason).toBeUndefined();
    expect(youCell(run)).toMatchObject({ title: 'Nothing needs you', line: 'You can start a new project.', action: 'next', tone: 'ended' });
    expect(starterAttribution(run)).toBe('Start requested by you');
    expect(runningWords(run, Date.now())).toBeNull();
    expect(run.eventsTotal).toBe(0);
    const feed = toGlanceEventPage(raw('real-g7/didnt_start', true), 0);
    expect(feed.events).toEqual([]);
    expect(activityRows(feed.events, run)).toEqual([]);
    expect(latestMoments(feed.events, run.leader)).toEqual([]);
  });
  it.each([
    ['phase reason', 'Exact phase reason.', 'outcome reason', 'Failed: phase words', 'Exact phase reason.'],
    ['outcome reason', null, 'Exact outcome reason.', 'Failed: phase words', 'Exact outcome reason.'],
    ['phase words', '', null, 'Failed: Exact words.', 'Exact words.'],
    ['exact prefix only', null, null, 'FAILED: Other words.', 'FAILED: Other words.'],
    ['fallback', null, null, null, "The project couldn't start. Temper gave no reason."],
  ])('%s precedence', (_name, reason, outcome, words, wanted) => {
    const body = raw('real-g7/didnt_start');
    Object.assign(body.phase as Raw, { reason, words });
    Object.assign(body.outcome as Raw, { reason: outcome });
    expect(nowCell(toGlanceRun(body), null).sentence).toBe(wanted);
  });
  it('role and missing starter are not invented; a start row uses the supplied role title', () => {
    const run = { ...failed(), startedBy: 'product', starterTitle: 'Product' };
    expect(starterAttribution(run)).toBe('Start requested by Product');
    expect(starterAttribution({ ...run, startedBy: null })).toBeNull();
    expect(text(activityRow(event({ kind: 'message', seq: 1, from: 'owner', from_kind: 'owner', to: 'lead', message_kind: 'goal', text: 'goal' }), run))).toBe('Product started the project; lead has the goal');
  });
  it('actual nonzero spend, with no next-check-in or finishing-turn promise', () => {
    const body = raw('real-g7/didnt_start');
    (body.spend as Raw).cost_usd = 7.25;
    body.cost_usd = 7.25;
    const cell = spendCell(toGlanceRun(body));
    expect(cell.amount).toBe('$7.25');
    expect(JSON.stringify(cell)).not.toMatch(/If you continue|finishing|next check-in/);
  });
  it('zero-turn assigned goal is not Last work; absent history and actual history stay distinct', () => {
    const run = failed();
    for (const m of run.members) {
      expect(memberChip(m, run.phase, null)).toMatchObject({ text: 'Ended', tone: 'grey', busy: false });
      expect(memberLine(m, run.phase)).toEqual({ label: 'Last:', text: 'No work started.', quoted: false });
    }
    const m = run.members[0];
    expect(memberLine({ ...m, turnsSupplied: false, on: null }, run.phase)).toMatchObject({ text: 'No last work recorded.', quoted: false });
    const realWork = { ...m, turns: 1, hasTurnHistory: true, on: { kind: 'work_request', text: 'Checked CSV 😀 quotes.', from: 'lead', to: null, at: null, messageId: null } };
    expect(memberLine(realWork, run.phase)).toMatchObject({ label: 'Last:', text: 'Checked CSV 😀 quotes.', quoted: true });
  });
  it('new ended fields/since are read, but obsolete live fields never survive an ended member', () => {
    const body = raw('real-g7/failed');
    Object.assign((body.members as Raw[])[0], { turn_no: 99, tools_now: [{ name: 'bash', count: 99 }], wait_id: 'stale', idle_note: 'stale', idle_reason: 'no_tool_call' });
    const run = toGlanceRun(body);
    const m = run.members[0];
    expect(m.state).toBe('ended');
    expect(m.since).toBe((body.members as Raw[])[0].since);
    expect(m).toMatchObject({ turnNo: null, toolsNow: null, waitId: null, idleNote: null, idleReason: null });
  });
  it('old ended derivation and Last: remain, without message counts; conflicts remain', () => {
    const body = raw('real-g6/interrupted');
    for (const m of body.members as Raw[]) Object.assign(m, { state: 'idle', ready_messages: 2 });
    const run = toGlanceRun(body);
    for (const m of run.members) {
      expect(memberChip(m, run.phase, null).text).toBe('Ended');
      const line = memberLine(m, run.phase);
      expect(line?.label).toBe('Last:');
      expect(line?.messages).toBeUndefined();
    }
  });
  it('starting zero turns stays live; failed TEAM keeps real Last; older failed MEMBER remains recovery', () => {
    const starting = toGlanceRun(raw('real-g7/starting'));
    expect(starting.members.every((m) => m.turns === 0)).toBe(true);
    expect(nowCell(starting, null).word).toBe('Starting');
    expect(phaseEnded(starting.phase.name)).toBe(false);
    const failedTeam = toGlanceRun(raw('real-g7/failed'));
    expect(nowCell(failedTeam, null).word).toBe('Failed');
    expect(failedTeam.members.some((m) => m.turns > 0)).toBe(true);
    expect(memberLine(failedTeam.members[0], failedTeam.phase)?.text).not.toBe('No work started.');
    expect(toGlanceRun(raw('real/failed')).phase.name).toBe('waiting_for_owner');
    expect(phaseEnded(toGlanceRun(raw('real/failed')).phase.name)).toBe(false);
  });
});
