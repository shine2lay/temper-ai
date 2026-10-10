/**
 * The free-flowing Team page on Temper's real G6 runs: twelve runs its real
 * engine made without a model (FLOW/G6-INPUTS.sha256, pinned by Frontend's
 * g6/INPUTS.md entry 3), copied byte for byte into
 * e2e/fixtures/team/flow/real-g6. The samples are Temper's bytes; every run
 * reads through the one adapter; the fields the glance page had no real
 * sample for are read from them; and the words #21 fixed say what the
 * binding sources say: every answer Temper records (api-fields:260) and
 * D86's "Not applied" marks, the Now and You lines (SPEC's tables), a
 * limit's check (D31) and Latest's big moments (SPEC 8).
 * Pure functions only: nothing renders and nothing starts a server.
 */
import { describe, expect, it } from 'vitest';

import { toGlanceEvent, toGlanceEventPage, toGlanceRun } from '@/lib/teamGlanceAdapter';
import { teamWaits } from '@/lib/teamAnswer';
import { glanceAnswerLabel } from '@/components/team/glance/glanceStyle';
import {
  NOT_APPLIED,
  activityRows,
  answerMark,
  answerWord,
  clockOf,
  conflictLine,
  glanceClock,
  latestMoments,
  limitCheckShown,
  memberChip,
  memberLine,
  nowCell,
  spendCell,
  teamCountWords,
  youCell,
  type GlanceEvent,
  type GlanceMember,
  type GlanceRun,
  type Moment,
} from '@/lib/teamGlance';
import type { TeamRun } from '@/types/team';

type Raw = Record<string, unknown>;

const DIR = '../../e2e/fixtures/team/flow/real-g6/';
/** Every file of the folder as committed, as text. */
const TEXT = import.meta.glob<string>('../../e2e/fixtures/team/flow/real-g6/*', {
  eager: true,
  query: '?raw',
  import: 'default',
});
const JSONS = import.meta.glob<Raw>('../../e2e/fixtures/team/flow/real-g6/*.json', { eager: true, import: 'default' });

/** Temper's manifest, as g6/INPUTS.md entry 3 pins it (Temper rm-ceebbee9, backend 76a1d5c7). */
const MANIFEST = 'G6-INPUTS.sha256';
const MANIFEST_SHA256 = '5aa6d58995145faa60598cb67b32074ffa4c044a07dbbd3353a1d0eea5e828f3';

const RUNS = [
  'member_question',
  'retry',
  'interrupted',
  'interrupted_no_end',
  'limit_waiting',
  'limit_unavailable',
  'limit_ready',
  'limit_ended',
  'restart_deferred',
  'conflict',
  'settings_late',
  'invalid',
] as const;
type RunName = (typeof RUNS)[number];

async function sha256(text: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

/** The manifest's sample lines: [sha256, file name in real-g6/] (its other lines name Temper's export script). */
function listed(): [string, string][] {
  return TEXT[DIR + MANIFEST].split('\n')
    .map((line) => /^([0-9a-f]{64}) [ *]api-fixtures-g6\/(.+)$/.exec(line))
    .filter((m): m is RegExpExecArray => m !== null)
    .map((m) => [m[1], m[2]]);
}

/** A sample's raw JSON, as a fresh copy a test may change. */
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
  /** The page's clock: the newer of the two replies' as_of. */
  now: number | null;
}

/** A run as the page reads it; `change` edits the feed first (a contract-shaped field Temper hasn't sent yet). */
function story(name: RunName, change?: (feed: Raw[]) => void): Story {
  const raw = rawOf(name);
  const feedRaw = rawOf(name, true);
  change?.(feedRaw.events as Raw[]);
  const run = toGlanceRun(raw);
  const page = toGlanceEventPage(feedRaw, 0);
  return { raw, feedRaw, run, events: page.events, now: glanceClock(run.asOf, page.asOf) };
}

const textOf = (m: Moment) => m.parts.map((p) => p.text).join('');
/** Latest as LatestMoments.tsx reads it. */
const latest = (s: Story) =>
  latestMoments(s.events, s.run.leader, 5, limitCheckShown(s.run.phase), new Set(s.run.members.map((m) => m.name)), s.run, {
    now: s.now,
  }).map(textOf);
/** All activity as AllActivity.tsx reads it, newest first. */
const activity = (s: Story) => activityRows(s.events, s.run, limitCheckShown(s.run.phase), { now: s.now }).map(textOf);
function member(s: Story, name: string): GlanceMember {
  const m = s.run.members.find((x) => x.name === name);
  if (!m) throw new Error(`no member ${name}`);
  return m;
}
const chip = (s: Story, name: string) => memberChip(member(s, name), s.run.phase.name, s.now);
const rawEvents = (s: Story) => s.feedRaw.events as Raw[];
const rawPhase = (s: Story) => s.raw.phase as Raw;
function eventsOf<K extends GlanceEvent['kind']>(s: Story, kind: K): Extract<GlanceEvent, { kind: K }>[] {
  return s.events.filter((e): e is Extract<GlanceEvent, { kind: K }> => e.kind === kind);
}
/** The feed's one wait_answered event, for a contract-shaped field Temper hasn't sent yet. */
function answeredEvent(events: Raw[]): Raw {
  const found = events.filter((e) => e.kind === 'wait_answered');
  expect(found).toHaveLength(1);
  return found[0];
}

describe('real G6 samples are Temper\u2019s bytes (FLOW/G6-INPUTS.sha256, g6/INPUTS.md entry 3)', () => {
  it('real-g6 fixtures match Temper\u2019s manifest', async () => {
    expect(await sha256(TEXT[DIR + MANIFEST])).toBe(MANIFEST_SHA256);
    const samples = listed();
    expect(samples).toHaveLength(24);
    for (const [sha, name] of samples) {
      expect(TEXT[DIR + name], name).toBeTypeOf('string');
      expect(await sha256(TEXT[DIR + name]), name).toBe(sha);
    }
    // The folder holds the manifest and its samples, nothing else: a run and its feed for each pinned run.
    const files = Object.keys(TEXT).map((k) => k.slice(DIR.length));
    expect(files.sort()).toEqual([MANIFEST, ...samples.map(([, n]) => n)].sort());
    expect(samples.map(([, n]) => n).sort()).toEqual(RUNS.flatMap((r) => [`${r}-events.json`, `${r}.json`]).sort());
  });

  it('hold no private path or host name', () => {
    for (const [name, text] of Object.entries(TEXT)) expect(text, name).not.toMatch(/\/home\/|tailbb|spark/);
  });
});

describe('every pinned run reads through the typed adapter', () => {
  it.each(RUNS)('%s', (name) => {
    const s = story(name);
    expect(s.run.executionId).toBe(s.raw.execution_id);
    expect(s.run.phase.name).not.toBe('unknown');
    expect(s.run.members.map((m) => m.state)).not.toContain('unknown');
    // The whole feed in one page: every event kept and known (Temper hides limit_checked itself).
    expect(s.feedRaw.more).toBe(false);
    expect(s.events).toHaveLength(rawEvents(s).length);
    expect(s.events.filter((e) => e.kind === 'other')).toEqual([]);
    // The count is events_total; seq numbers skip (hidden events) and are never counted.
    expect(s.run.eventsTotal).toBe(s.raw.events_total);
    expect(s.run.eventsTotal).toBe(s.events.length);
  });

  it('a re-make\u2019s other seq numbers change nothing the owner reads (seqs start at 1 and differ each time)', () => {
    for (const name of RUNS) {
      const s = story(name);
      const moved = story(name, (events) => {
        for (const e of events) e.seq = (e.seq as number) + 1000;
      });
      expect(latest(moved), name).toEqual(latest(s));
      expect(activity(moved), name).toEqual(activity(s));
    }
  });
});

describe('#18\u2019s G6 gaps, read from the real samples (g6/G6-FIELDS.md)', () => {
  it('a usage limit: next check, reset known, usage reading, check time, held windows', () => {
    const waiting = story('limit_waiting');
    expect(waiting.run.phase).toMatchObject({
      name: 'limit',
      asked: false,
      resumesAt: rawPhase(waiting).resumes_at,
      resetsKnown: true,
      blockedWindows: ['5h'],
    });
    expect(waiting.run.phase.resumesAt).toBeTypeOf('string');
    expect(story('limit_unavailable').run.phase).toMatchObject({
      reason: 'helper_unreachable',
      resetsKnown: false,
      usage: { status: 'unavailable', reason: 'helper_unreachable' },
    });
    const ready = story('limit_ready');
    const usage = rawPhase(ready).usage as Raw;
    expect(ready.run.phase).toMatchObject({
      asked: true,
      resumeVerified: true,
      usageCheckedAt: rawPhase(ready).usage_checked_at,
      usage: {
        status: 'ok',
        observedAt: usage.observed_at,
        windows: (usage.windows as Raw[]).map((w) => ({ key: w.key, usedPercent: w.used_percent, resetsAt: w.resets_at })),
      },
    });
    expect(ready.run.phase.usageCheckedAt).toBeTypeOf('string');
    expect(story('restart_deferred').run.phase.blockedWindows).toEqual(['7d']);
  });

  it('an interrupted run: Temper\u2019s reason, and its length frozen at the end or not known', () => {
    const s = story('interrupted');
    expect(s.run.phase).toMatchObject({ name: 'interrupted', reason: rawPhase(s).reason });
    expect(s.run.phase.reason).toBeTypeOf('string');
    expect(s.run.elapsedS).toBe(45);
    expect(story('interrupted_no_end').run.elapsedS).toBeNull();
  });

  it('a member\u2019s own question: its header and Temper\u2019s note (open_waits, read through teamWaits)', () => {
    const s = story('member_question');
    const raw = (s.raw.open_waits as Raw[]).find((w) => w.kind === 'question') as Raw;
    expect(raw.note).toBeTypeOf('string');
    const { wait } = teamWaits(s.raw as unknown as TeamRun);
    expect(wait).toMatchObject({ kind: 'question', member: 'builder', header: 'builder asks', note: raw.note });
    expect(s.run.you).toMatchObject({ count: 1, first: { kind: 'question', member: 'builder', header: 'builder asks' } });
  });

  it('members: a file in conflict and a retried turn', () => {
    expect(member(story('conflict'), 'checker').conflicts).toBe(1);
    expect(member(story('retry'), 'builder').retryOf).toBe(1);
  });

  it('events: a retry, how turns end, a conflict and a refused share', () => {
    const retry = story('retry');
    expect(eventsOf(retry, 'turn_start').filter((e) => e.retryOf !== null)).toMatchObject([{ member: 'builder', turnNo: 2, retryOf: 1 }]);
    const ends = eventsOf(retry, 'turn_end');
    expect(ends.find((e) => e.member === 'lead')).toMatchObject({ ended: 'completed', endedBy: 'no_tool_call' });
    expect(ends.find((e) => e.member === 'checker')).toMatchObject({ endedBy: 'call_cap' });
    expect(ends.find((e) => e.member === 'builder')).toMatchObject({ ended: 'failed' });
    const conflict = story('conflict');
    expect(eventsOf(conflict, 'conflict')).toMatchObject([{ member: 'checker', paths: 1, atStep: 'sync' }]);
    expect(eventsOf(conflict, 'share_refused')).toMatchObject([{ member: 'checker', why: 'refused' }]);
  });

  it('events: an answer to a member\u2019s question, the owner\u2019s words, a limit and its end', () => {
    const s = story('member_question');
    const answered = eventsOf(s, 'wait_answered');
    expect(answered).toMatchObject([{ member: 'checker', waitKind: 'question', answer: 'given', by: 'owner', applied: null, why: null }]);
    expect(answered[0].waitId).toBeTypeOf('string');
    expect(eventsOf(s, 'message').filter((e) => e.messageKind === 'owner_reply')).toMatchObject([
      { from: 'owner', fromKind: 'owner', to: 'checker', text: 'yes' },
    ]);
    const waiting = story('limit_waiting');
    expect(eventsOf(waiting, 'limit')).toMatchObject([{ member: 'builder', resumesAt: rawPhase(waiting).resumes_at, resetsKnown: true }]);
    expect(eventsOf(story('limit_unavailable'), 'limit')).toMatchObject([{ resetsKnown: false }]);
    expect(eventsOf(story('limit_ended'), 'limit_over')).toHaveLength(1);
  });

  it('drops limit_checked: hidden by contract (api-fields.md:140), so the page never shows one', () => {
    expect(toGlanceEvent({ seq: 17, at: '2026-10-10T03:40:52Z', kind: 'limit_checked', member: 'builder' })).toBeNull();
    // Temper hides it before the feed: limit_waiting counts 16 events while its cursor is past the check's seq 17.
    const s = story('limit_waiting');
    expect(rawEvents(s).map((e) => e.kind)).not.toContain('limit_checked');
    expect(s.run.eventsTotal).toBe(16);
    expect(s.run.eventsCursor).toBe(17);
  });
});

/** One answer, contract-shaped (api-fields:260), by the owner. */
function answer(word: string, extra: Raw = {}): GlanceEvent {
  const e = toGlanceEvent({
    seq: 20,
    at: '2026-10-10T03:59:08Z',
    kind: 'wait_answered',
    member: null,
    wait_id: 'w-1',
    wait_kind: 'pause',
    answer: word,
    by: 'owner',
    ...extra,
  });
  if (!e) throw new Error('no event');
  return e;
}
const RUN = story('invalid').run;
const rowOf = (e: GlanceEvent) => textOf(activityRows([e], RUN)[0]);
const latestOf = (e: GlanceEvent) => latestMoments([e], RUN.leader).map(textOf)[0];

describe('answer words: every answer Temper records (api-fields:260), never a raw code word', () => {
  it.each([
    ['continue', 'You answered: continue'],
    ['guide', 'You answered: guide'],
    ['stop', 'You answered: stop'],
    ['nudge', 'You answered: nudge'],
    ['accept', 'You answered: accept'],
    ['retry', 'You answered: retry'],
    ['go on', 'You answered: go on'],
    // The owner replied to a member's question: as the old `reply` (D86 note 6).
    ['given', 'You answered: a reply'],
    ['reply', 'You answered: a reply'],
    ['invalid', `You answered. ${NOT_APPLIED.invalid}`],
    ['restart_deferred', `You answered: restart. ${NOT_APPLIED.restartDeferred}`],
  ])('%s', (word, row) => {
    expect(rowOf(answer(word))).toBe(row);
    // D110: Latest words an event as All activity does.
    expect(latestOf(answer(word))).toBe(row);
  });

  it('an answer the page has no words for says who answered, without the word', () => {
    expect(answerWord('later_maybe')).toBeNull();
    expect(answerWord('constructor')).toBeNull();
    expect(rowOf(answer('later_maybe'))).toBe('You answered');
    expect(latestOf(answer('later_maybe'))).toBe('You answered');
  });

  it('member_question: the owner\u2019s reply reads as a reply, then his words answer checker (D108)', () => {
    const s = story('member_question');
    const rows = activity(s);
    expect(rows.slice(0, 2)).toEqual(['You answered checker: \u201cyes\u201d', 'You answered: a reply']);
    expect(latest(s)[0]).toBe('You answered: a reply');
    for (const text of [...rows, ...latest(s)]) expect(text).not.toMatch(/\bgiven\b/);
  });

  it('no raw answer word on any pinned run', () => {
    for (const name of RUNS) {
      const s = story(name);
      for (const text of [...activity(s), ...latest(s)]) expect(text, name).not.toMatch(/\b(given|invalid|restart_deferred)\b/);
    }
  });
});

describe('D86: an answer that wasn\u2019t applied says so (g6/TEMPER-D86.md)', () => {
  const late = (applied: unknown, why: unknown) =>
    story('settings_late', (events) => Object.assign(answeredEvent(events), { applied, why }));

  it('1. a settings go on with applied false: one fixed sentence, whatever Temper\u2019s why', () => {
    for (const why of ['the settings changed again before the answer took effect', null]) {
      const s = late(false, why);
      expect(activity(s)).toContain(`You answered: go on. ${NOT_APPLIED.settingsLate}`);
      expect(latest(s)).toContain(`You answered: go on. ${NOT_APPLIED.settingsLate}`);
    }
    expect(NOT_APPLIED.settingsLate).toBe('Not applied: the settings changed before the answer took effect.');
    // The mark is its own part after the answer, in normal text (not bold).
    const row = activityRows(late(false, null).events, RUN).find((m) => textOf(m).includes('Not applied'));
    expect(row?.parts.at(-1)).toEqual({ text: `. ${NOT_APPLIED.settingsLate}` });
  });

  it('1b. without applied (the real sample) or with applied true: an ordinary go on, never inferred from the next question', () => {
    for (const s of [story('settings_late'), late(true, null)]) {
      expect(activity(s)).toContain('You answered: go on');
      expect(latest(s)).toContain('You answered: go on');
      expect([...activity(s), ...latest(s)].join('\n')).not.toMatch(/Not applied/);
    }
    // The real sample: the go on, then the new settings question (Temper asked again) with its own words.
    const rows = activity(story('settings_late'));
    // D110: Temper asked it (a settings question is Temper's own wait).
    expect(rows.slice(0, 2)).toEqual([expect.stringMatching(/^Temper asked you: .*fixture-3\u201d$/), 'You answered: go on']);
  });

  it('2. invalid (the real sample): who answered, no word, then the mark', () => {
    const s = story('invalid');
    expect(activity(s)).toContain(`You answered. ${NOT_APPLIED.invalid}`);
    expect(latest(s)[0]).toBe(`You answered. ${NOT_APPLIED.invalid}`);
    expect(NOT_APPLIED.invalid).toBe('Not applied: the answer didn\u2019t match any of the choices. Temper asked again.');
  });

  it('3. restart_deferred (the real sample): answered restart, then the mark', () => {
    const s = story('restart_deferred');
    expect(activity(s)).toContain(`You answered: restart. ${NOT_APPLIED.restartDeferred}`);
    expect(latest(s)).toContain(`You answered: restart. ${NOT_APPLIED.restartDeferred}`);
    expect(NOT_APPLIED.restartDeferred).toBe('Not applied: Temper couldn\u2019t confirm the usage limit has reset.');
  });

  it('4. applied false on any other answer: "Not applied", plus Temper\u2019s why word for word', () => {
    const withWhy = answer('continue', { applied: false, why: 'the check-in had already closed' });
    expect(rowOf(withWhy)).toBe('You answered: continue. Not applied: the check-in had already closed');
    expect(latestOf(withWhy)).toBe('You answered: continue. Not applied: the check-in had already closed');
    const bare = answer('continue', { applied: false });
    expect(rowOf(bare)).toBe('You answered: continue. Not applied.');
    expect(latestOf(bare)).toBe('You answered: continue. Not applied.');
    // A go on to a question that isn't a settings one is "any other row".
    expect(answerMark({ waitKind: 'pause', answer: 'go on', applied: false, why: null })).toBe('Not applied.');
    expect(answerMark({ waitKind: 'settings', answer: 'go on', applied: null, why: 'x' })).toBeNull();
  });
});

describe('the binding words the real runs showed missing (#21 fixes)', () => {
  it('working: "N of M members working." (SPEC Now table)', () => {
    expect(nowCell(story('retry').run, story('retry').now)).toMatchObject({
      word: 'Working',
      sentence: '1 of 3 members working. Last activity 0\u00a0s\u00a0ago.',
      countLine: '2 idle',
    });
  });

  it('a limit with nothing to answer: Stop stays at the top (SPEC You table)', () => {
    for (const name of ['limit_waiting', 'limit_unavailable', 'restart_deferred'] as const) {
      expect(youCell(story(name).run), name).toMatchObject({
        tone: 'calm',
        title: 'Nothing needs you',
        line: 'Stop stays at the top if you want to end it.',
        action: null,
      });
    }
  });

  it('interrupted: SPEC\u2019s one sentence with an end time, D105\u2019s without one; Temper\u2019s reason second; the D16 line', () => {
    for (const name of ['interrupted', 'interrupted_no_end'] as const) {
      const s = story(name);
      // D105: Temper recorded no end time for interrupted_no_end (elapsed_s null).
      const sentence =
        name === 'interrupted'
          ? 'The run ended without the team ending.'
          : `Last activity ${clockOf(s.raw.last_activity_at as string)}. Temper didn\u2019t record when it ended.`;
      expect(nowCell(s.run, s.now), name).toMatchObject({
        word: 'Interrupted',
        sentence,
        reason: 'the run ended (interrupted) without the team ending',
        edge: 'red',
      });
      expect(youCell(s.run), name).toMatchObject({
        tone: 'ended',
        title: 'Nothing needs you',
        line: 'Read what it made below, or start a new Project.',
        action: 'next',
      });
    }
  });

  it('settings: "A setting changed while the team waited." and "go on or stop?" (SPEC tables)', () => {
    const s = story('settings_late');
    expect(nowCell(s.run, s.now)).toMatchObject({ word: 'Settings changed', sentence: 'A setting changed while the team waited.' });
    expect(youCell(s.run)).toMatchObject({ tone: 'needs', title: 'Needs you: go on or stop?', action: 'answers' });
    const { wait } = teamWaits(s.raw as unknown as TeamRun);
    expect(wait?.question).toContain('fixture-3');
    expect(wait?.answers.map((a) => glanceAnswerLabel(a))).toEqual(['Go on', 'Stop']);
  });

  it('check-in: "Check-in at $X" from spend.cost_usd (SPEC Now table)', () => {
    const s = story('invalid');
    expect(nowCell(s.run, s.now)).toMatchObject({ word: 'Check-in at $105.00', sentence: 'No new work starts until you answer.' });
    expect(youCell(s.run)).toMatchObject({ tone: 'needs', title: 'Needs you: carry on?' });
  });

  it('a verified limit names no pending check anywhere; a waiting one names it in Now and its row (D31)', () => {
    const ready = story('limit_ready');
    expect(limitCheckShown(ready.run.phase)).toBe(false);
    expect(nowCell(ready.run, ready.now).sentence).toBe('Usage is available again: restart or stop?');
    expect(latest(ready)[0]).toBe('Usage limit');
    expect(activity(ready)[0]).toBe('Usage limit');
    expect([...latest(ready), ...activity(ready)].join('\n')).not.toMatch(/allowance check at|reset at/i);

    const waiting = story('limit_waiting');
    const at = clockOf(rawPhase(waiting).resumes_at as string);
    expect(limitCheckShown(waiting.run.phase)).toBe(true);
    expect(nowCell(waiting.run, waiting.now).sentence).toBe(
      `The account hit its usage limit; it carries on only after fresh usage shows room. Next allowance check at ${at}.`,
    );
    expect(latest(waiting)[0]).toBe(`Usage limit: next allowance check at ${at}`);
    const unavailable = story('limit_unavailable');
    const at2 = clockOf(rawPhase(unavailable).resumes_at as string);
    expect(nowCell(unavailable.run, unavailable.now).sentence).toBe(
      `Usage cannot be checked; the team keeps waiting. Next allowance check at ${at2}. No usable reset time.`,
    );
    expect(latest(unavailable)[0]).toBe(`Usage limit: next allowance check at ${at2}; no usable reset time`);
  });

  it('Team now counts in the cards\u2019 own words (SPEC 5): paused in a limit, all ended once the run has ended', () => {
    for (const name of ['limit_waiting', 'limit_unavailable', 'limit_ready', 'restart_deferred'] as const) {
      const s = story(name);
      expect(chip(s, 'builder').text, name).toBe('Paused: usage limit');
      expect(teamCountWords(s.run), name).toBe('1 paused \u00b7 2 idle');
    }
    // Temper leaves an interrupted run's members idle; the run has ended all the same.
    for (const name of ['interrupted', 'interrupted_no_end'] as const) {
      const s = story(name);
      expect(s.run.members.every((m) => m.state === 'idle'), name).toBe(true);
      expect(teamCountWords(s.run), name).toBe('3 members \u00b7 all ended');
    }
    expect(teamCountWords(story('member_question').run)).toBe('1 ready \u00b7 1 idle \u00b7 1 needs you');
    expect(teamCountWords(story('retry').run)).toBe('1 working \u00b7 2 idle');
    expect(teamCountWords(story('settings_late').run)).toBe('3 idle');
  });

  it('Latest: a conflict is a big moment, a refused share is not (SPEC 8); both rows are in All activity', () => {
    const s = story('conflict');
    expect(latest(s)[0]).toBe('checker has 1 file in conflict after a sync');
    expect(latest(s).join('\n')).not.toMatch(/refused|shared\./);
    expect(activity(s).slice(0, 4)).toEqual([
      // D107: Temper's why only repeats the verb.
      'checker\u2019s version wasn\u2019t shared. Temper gave no reason.',
      'Temper told checker: \u201cNot shared: these files still hold git\'s conflict markers: part.md. Remove the markers and share again.\u201d',
      'checker ended turn 2: completed',
      'checker has 1 file in conflict after a sync',
    ]);
  });
});

describe('each pinned run against its binding rows (g6/G6-TRUTH.md)', () => {
  it('member_question: the question needs you though the phase is working; the others wait or idle', () => {
    const s = story('member_question');
    expect(s.run.phase.name).toBe('working');
    expect(nowCell(s.run, s.now)).toMatchObject({
      sentence: '0 of 3 members working. Last activity 0\u00a0s\u00a0ago.',
      countLine: '1 ready \u00b7 1 idle \u00b7 1 needs you',
    });
    const you = youCell(s.run);
    expect(you).toMatchObject({ tone: 'needs', from: 'From builder', action: 'answer', more: 0 });
    // D62: the first line cut after a whole word at 90 characters, with "…".
    expect(you.title).toBe(
      'Needs you: \u201cMay I rename the docs folder to guide? Three links in the README would change with it\u2026\u201d',
    );
    expect(chip(s, 'builder').text).toBe('Needs you');
    expect(memberLine(member(s, 'builder'))?.text).toBe((s.raw.you as { first: { words: string } }).first.words);
    expect(chip(s, 'checker').text).toBe('Ready \u00b7 waiting for a free turn \u00b7 1 message');
    expect(chip(s, 'lead').text).toMatch(/^Idle \u00b7 /);
  });

  it('retry: a retried turn, a turn ended without a note, a turn ended by its call cap', () => {
    const s = story('retry');
    expect(chip(s, 'builder')).toMatchObject({ text: 'Working on a retry \u00b7 0 s', busy: true });
    expect(chip(s, 'lead').text).toMatch(/^Idle \u00b7 /);
    expect(memberLine(member(s, 'lead'))).toMatchObject({ text: 'Ended its turn without a note', quoted: false });
    expect(activity(s).slice(0, 6)).toEqual([
      'builder started turn 2 (Temper\u2019s retry of turn 1)',
      'builder ended turn 1: failed',
      'checker went idle: \u201cchecker: waiting for the next part\u201d',
      'checker\u2019s turn 1 ended at its tool-call limit.',
      'lead went idle without a note',
      'lead ended turn 1: completed (no tool call)',
    ]);
  });

  it('interrupted: frozen at the end, nothing to answer', () => {
    for (const name of ['interrupted', 'interrupted_no_end'] as const) {
      const s = story(name);
      expect(teamWaits(s.raw as unknown as TeamRun).wait, name).toBeNull();
      expect(spendCell(s.run), name).toMatchObject({ amount: '$105.00', of: null });
    }
  });

  it('limit_waiting: Temper\u2019s own 5-hour wait asks nothing; the ready member is paused', () => {
    const s = story('limit_waiting');
    expect(s.run.you.count).toBe(0);
    expect(s.raw.open_waits).toEqual([]);
    expect(nowCell(s.run, s.now)).toMatchObject({ word: 'Usage limit', edge: 'grey' });
    expect(chip(s, 'builder')).toMatchObject({ text: 'Paused: usage limit', ring: 'dashed-yellow' });
  });

  it('limit_ready: a verified weekly limit asks restart or stop', () => {
    const s = story('limit_ready');
    const words = (s.raw.you as { first: { words: string } }).first.words;
    expect(youCell(s.run)).toMatchObject({ tone: 'needs', title: `Needs you: \u201c${words}\u201d`, action: 'answers' });
    const { wait } = teamWaits(s.raw as unknown as TeamRun);
    expect(wait?.kind).toBe('limit');
    expect(wait?.answers.map((a) => glanceAnswerLabel(a))).toEqual(['Restart', 'Stop']);
  });

  it('limit_ended: the limit and its end, never a reset time', () => {
    const s = story('limit_ended');
    // D109: no `by`, so nobody is named.
    const over = `The usage limit is over. The team carried on at ${clockOf(eventsOf(s, 'limit_over')[0].at)}.`;
    expect(activity(s).slice(0, 2)).toEqual([over, 'Usage limit']);
    expect(latest(s).slice(0, 2)).toEqual([over, 'Usage limit']);
    expect([...activity(s), ...latest(s)].join('\n')).not.toMatch(/reset at|carries on at/i);
    expect(youCell(s.run)).toMatchObject({ tone: 'calm', title: 'Nothing needs you' });
  });

  it('conflict: "1 file in conflict" on the card (singular)', () => {
    const s = story('conflict');
    expect(conflictLine(member(s, 'checker'))).toBe('1 file in conflict');
    expect(conflictLine(member(s, 'builder'))).toBeNull();
  });
});
