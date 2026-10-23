/**
 * Temper #115 on the free-flowing Team page: Temper refusing to run git over a
 * member's folder. Read from Temper's real serializer output
 * (e2e/fixtures/team/flow/real-git, made by scripts/capture_team_fixtures.py
 * --only git): a member Temper rested (idle reason git_refused, Temper's own
 * note as idle_note), sync_refused with a cause whose turn went ahead
 * (planted) and one whose turn didn't start (writer), and share_refused with
 * its cause. Temper's words read as Temper's, never quoted as the member's;
 * no #115 event is an unnamed row; every other idle wording stays as it was.
 * The browser journey (axe, 24 px, both themes) is
 * e2e/team-glance-git-refused.spec.ts. Pure functions only.
 */
import { describe, expect, it } from 'vitest';

import { toGlanceEvent, toGlanceEventPage, toGlanceRun } from '@/lib/teamGlanceAdapter';
import {
  activityRows,
  glanceClock,
  gitRestWords,
  latestMoments,
  limitCheckShown,
  memberChip,
  memberLine,
  teamCountWords,
  type GlanceEvent,
  type GlanceMember,
  type GlanceRun,
  type Moment,
} from '@/lib/teamGlance';

type Raw = Record<string, unknown>;

const DIR = '../../e2e/fixtures/team/flow/real-git/';
const JSONS = import.meta.glob<Raw>('../../e2e/fixtures/team/flow/real-git/*.json', { eager: true, import: 'default' });
const RUNS = ['git_rest', 'git_writer'] as const;
type RunName = (typeof RUNS)[number];

function rawOf(name: RunName, feed = false): Raw {
  const body = JSONS[`${DIR}${name}${feed ? '-events' : ''}.json`];
  if (!body) throw new Error(`no sample ${name}`);
  return JSON.parse(JSON.stringify(body)) as Raw;
}

interface Story {
  raw: Raw;
  feedRaw: Raw;
  run: GlanceRun;
  events: GlanceEvent[];
  now: number | null;
}

function story(name: RunName): Story {
  const raw = rawOf(name);
  const feedRaw = rawOf(name, true);
  const run = toGlanceRun(raw);
  const page = toGlanceEventPage(feedRaw, 0);
  return { raw, feedRaw, run, events: page.events, now: glanceClock(run.asOf, page.asOf) };
}

const textOf = (m: Moment) => m.parts.map((p) => p.text).join('');
const activity = (s: Story) => activityRows(s.events, s.run, limitCheckShown(s.run.phase), { now: s.now }).map(textOf);
function member(s: Story, name: string): GlanceMember {
  const m = s.run.members.find((x) => x.name === name);
  if (!m) throw new Error(`no member ${name}`);
  return m;
}
/** Temper's raw words of the one event of `kind` in the feed. */
function rawEvent(s: Story, kind: string): Raw {
  const hits = (s.feedRaw.events as Raw[]).filter((e) => e.kind === kind && e.member === 'builder');
  expect(hits, `${kind} events`).toHaveLength(1);
  return hits[0];
}

const REST = 'Temper couldn\u2019t share its work twice in a row (its folder holds a .git of its own)';
const SYNC_WENT_AHEAD = ' didn\u2019t get the team\u2019s latest shared work before this turn; the turn went ahead, and Temper told it why.';
const SYNC_NO_TURN = ' didn\u2019t get the team\u2019s latest shared work, so this turn didn\u2019t start.';

describe('Temper #115 on the Team page (real serializer output)', () => {
  it('git_rest: the resting member, its card and the feed read as Temper refusing git, in Temper\u2019s words', () => {
    const s = story('git_rest');
    const builder = member(s, 'builder');
    // What Temper serves: its own note as the member's idle_note.
    expect(builder.idleReason).toBe('git_refused');
    expect(builder.idleNote).toMatch(/^Temper refused to run git over its folder in 2 turns in a row \(planted\)/);

    // The card: Resting, Temper as the actor, not quoted as the member's note.
    expect(memberChip(builder, s.run.phase, s.now).text).toMatch(/^Resting( \u00b7 |$)/);
    expect(memberChip(builder, s.run.phase, s.now)).toMatchObject({ icon: 'moon', ring: 'dotted-grey', tone: 'grey', busy: false });
    expect(memberLine(builder, s.run.phase)).toEqual({ label: null, text: `${REST}. A message wakes it.`, quoted: false });
    // The Team now count uses the card's word.
    expect(teamCountWords(s.run)).toBe('1 working \u00b7 1 resting');

    // The feed: the rest, the turn that went ahead without the team's work, and the refused share.
    const rows = activity(s);
    const sync = rawEvent(s, 'sync_refused');
    expect(sync.cause).toBe('planted');
    expect(rows).toContain(`builder is resting: ${REST}.`);
    expect(rows).toContain(`builder${SYNC_WENT_AHEAD} Temper\u2019s reason: \u201c${sync.reason as string}\u201d`);
    // Temper's own words show only where Temper is the speaker (its message to the leader).
    expect(rows.filter((r) => r.includes('Temper refused to run git') && !r.startsWith('Temper told lead: '))).toEqual([]);
    expect(rows.filter((r) => /went idle: .*Temper/.test(r))).toEqual([]);

    // share_refused keeps its reason words and now carries Temper's cause.
    const share = s.events.find((e): e is Extract<GlanceEvent, { kind: 'share_refused' }> => e.kind === 'share_refused');
    expect(share?.cause).toBe('planted');
    expect(rows).toContain(`builder\u2019s version wasn\u2019t shared: ${rawEvent(s, 'share_refused').reason as string}`);
  });

  it('git_writer: a sync refused for a writer says the turn didn\u2019t start, with Temper\u2019s reason', () => {
    const s = story('git_writer');
    const sync = rawEvent(s, 'sync_refused');
    expect(sync.cause).toBe('writer');
    expect(activity(s)).toContain(`builder${SYNC_NO_TURN} Temper\u2019s reason: \u201c${sync.reason as string}\u201d`);
    // The member's own idle note is still its own.
    expect(memberLine(member(s, 'builder'), s.run.phase)).toEqual({ label: 'Idle:', text: 'part.md shared', quoted: true });
    expect(memberChip(member(s, 'builder'), s.run.phase, s.now).text).toMatch(/^Idle( \u00b7 |$)/);
    expect(teamCountWords(s.run)).toBe('1 working \u00b7 1 idle');
  });

  it('no #115 event is an unnamed row, and none is a big moment', () => {
    for (const name of RUNS) {
      const s = story(name);
      expect(s.events.filter((e) => e.kind === 'other').map((e) => e.seq), name).toEqual([]);
      expect(activity(s).filter((r) => /\bsync_refused\b|\bgit_refused\b/.test(r)), name).toEqual([]);
      const latest = latestMoments(s.events, s.run.leader, 5, false, new Set(s.run.members.map((m) => m.name)), s.run, { now: s.now }).map(textOf);
      expect(latest.filter((r) => r.includes('latest shared work')), name).toEqual([]);
    }
  });

  it('an ended card never quotes Temper\u2019s rest note as the member\u2019s last work', () => {
    const builder = member(story('git_rest'), 'builder');
    // Its last work request stays its own words.
    expect(memberLine(builder, 'interrupted')).toEqual({ label: 'Last:', text: 'Write part.md, then share it.', quoted: true });
    // With no other work, Temper's note (served as `on` of kind idle) reads as Temper's.
    const noWork = { ...builder, on: { kind: 'idle', text: builder.idleNote ?? '', from: 'builder', to: null, at: null, messageId: null } };
    expect(memberLine(noWork, 'interrupted')).toEqual({ label: 'Last:', text: `${REST}.`, quoted: false });
  });

  it('sync_refused: every cause Temper names says whether the turn started', () => {
    const row = (cause: string | null, reason: string | null) => {
      const e = toGlanceEvent({ seq: 5, at: '2026-10-23T17:00:00Z', kind: 'sync_refused', member: 'builder', cause, reason });
      if (!e) throw new Error('no event');
      return textOf(activityRows([e], { startedBy: null, members: null })[0]);
    };
    for (const cause of ['planted', 'entries', 'depth', 'unreadable']) expect(row(cause, 'why'), cause).toContain(SYNC_WENT_AHEAD);
    for (const cause of ['writer', 'stall', 'setup', 'gitlink']) expect(row(cause, 'why'), cause).toContain(SYNC_NO_TURN);
    expect(row('something_new', 'why')).toBe('builder didn\u2019t get the team\u2019s latest shared work before this turn. Temper\u2019s reason: \u201cwhy\u201d');
    expect(row('writer', null)).toBe(`builder${SYNC_NO_TURN} Temper gave no reason.`);
  });

  it('the rest words follow Temper\u2019s count and cause, and say no more than it does', () => {
    const note = (n: number, cause: string) => `Temper refused to run git over its folder in ${n} turns in a row (${cause}); a message wakes it.`;
    expect(gitRestWords(note(3, 'entries'))).toBe('Temper couldn\u2019t share its work in 3 turns in a row (its folder holds too many files to check)');
    expect(gitRestWords(note(2, 'depth'))).toBe('Temper couldn\u2019t share its work twice in a row (its folder nests too deep to check)');
    expect(gitRestWords(note(2, 'unreadable'))).toBe('Temper couldn\u2019t share its work twice in a row (Temper can\u2019t read a folder in it)');
    expect(gitRestWords(note(2, 'brand_new'))).toBe('Temper couldn\u2019t share its work twice in a row');
    expect(gitRestWords(null)).toBe('Temper couldn\u2019t share its work');
  });

  it('every other idle reason reads as before', () => {
    const base = member(story('git_rest'), 'builder');
    const idle = (idleReason: GlanceMember['idleReason'], idleNote: string | null): GlanceMember => ({ ...base, idleReason, idleNote });
    expect(memberLine(idle('idle_call', 'waiting for part.md'))).toEqual({ label: 'Idle:', text: 'waiting for part.md', quoted: true });
    expect(memberChip(idle('idle_call', 'waiting for part.md'), 'working', null).text).toBe('Idle');
    // A member's own note that talks about Temper is still the member's.
    expect(memberLine(idle('idle_call', 'Temper refused my share, trying again later'))).toEqual({
      label: 'Idle:',
      text: 'Temper refused my share, trying again later',
      quoted: true,
    });
    expect(memberLine(idle('no_tool_call', null))).toEqual({ label: null, text: 'Ended its turn without a note', quoted: false });
    expect(memberChip(idle('start', null), 'working', null).text).toBe('Waiting for the leader');

    const rows = (reason: string, note: string | null) => {
      const e = toGlanceEvent({ seq: 7, at: '2026-10-23T17:00:00Z', kind: 'idle', member: 'builder', reason, note });
      if (!e) throw new Error('no event');
      return textOf(activityRows([e], { startedBy: null, members: null })[0]);
    };
    expect(rows('idle_call', 'part.md written')).toBe('builder went idle: \u201cpart.md written\u201d');
    expect(rows('no_tool_call', null)).toBe('builder went idle without a note');
    expect(rows('start', null)).toBe('builder waits for the leader');
  });
});
