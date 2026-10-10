/**
 * Design's word and state rows outside the map (D8, D9, D41-D77), read on
 * Temper's final replies (flow-teams 76a1d5c7): first a working team as the
 * owner sees it, then the contract points the rows and the backend fix
 * (a member's own question, the start check) add. Pure functions only.
 */
import { describe, expect, it } from 'vitest';

import { teamWaits } from '@/lib/teamAnswer';
import { toGlanceEventPage, toGlanceRun } from '@/lib/teamGlanceAdapter';
import {
  bandWords,
  clockSecOf,
  composerHint,
  cutAt,
  glanceClock,
  latestAgo,
  latestMoments,
  memberLine,
  nowCell,
  nowCountsMembers,
  rowWords,
  spendCell,
  workingNow,
  youCell,
  type GlanceEvent,
  type GlanceRun,
} from '@/lib/teamGlance';
import type { TeamRun } from '@/types/team';

type Raw = Record<string, unknown>;

const FILES = import.meta.glob<Raw>(['../../e2e/fixtures/team/flow/real/*.json', '../../e2e/fixtures/team/flow/derived/*.json'], {
  eager: true,
  import: 'default',
});

/** A fixture's raw JSON (real first, then derived), as a fresh copy a test may change. */
function rawOf(name: string, feed = false): Raw {
  const file = `${name}${feed ? '-events' : ''}.json`;
  const body = FILES[`../../e2e/fixtures/team/flow/real/${file}`] ?? FILES[`../../e2e/fixtures/team/flow/derived/${file}`];
  if (!body) throw new Error(`no fixture ${file}`);
  return JSON.parse(JSON.stringify(body)) as Raw;
}

interface Story {
  raw: Raw;
  run: GlanceRun;
  events: GlanceEvent[];
  now: number | null;
}

function story(name: string, change?: (raw: Raw) => void): Story {
  const raw = rawOf(name);
  change?.(raw);
  const run = toGlanceRun(raw);
  const page = toGlanceEventPage(rawOf(name, true), 0);
  return { raw, run, events: page.events, now: glanceClock(run.asOf, page.asOf) };
}

const firstOf = (raw: Raw) => (raw.you as Raw).first as Raw;
const textOf = (parts: { text: string }[]) => parts.map((p) => p.text).join('');
/** The quoted words of a "Needs you: “…”" title. */
const quoted = (title: string) => /\u201c(.*)\u201d$/.exec(title)?.[1] ?? '';

describe('a working team at a glance', () => {
  it('says who works on what, that nothing needs you, the spend and how long ago, in Design words', () => {
    const s = story('working');
    // Now: Temper's count, then who works (D8) from `on` alone: the leader's
    // released message is not work it is on.
    expect(nowCell(s.run, s.now)).toMatchObject({
      word: 'Working',
      sentence: '3 of 3 members working. Last activity 0\u00a0s\u00a0ago.',
    });
    expect(workingNow(s.run)).toEqual({
      rows: [
        { name: 'lead', icon: 'play', tone: 'blue', words: 'working', text: null, quoted: false },
        { name: 'builder', icon: 'play', tone: 'blue', words: 'working on', text: 'Build the builder part and share it.', quoted: true },
        { name: 'checker', icon: 'play', tone: 'blue', words: 'working on', text: 'Build the checker part and share it.', quoted: true },
      ],
      more: 0,
    });
    // D74: Now already counts the team, so the phone header leaves "3 members" out.
    expect(nowCountsMembers(s.run)).toBe(true);
    // You: calm, with the hint a phone leaves out (D9).
    expect(youCell(s.run)).toMatchObject({
      tone: 'calm',
      title: 'Nothing needs you',
      line: 'Questions and check-ins show up here.',
      hint: true,
      from: null,
      action: null,
    });
    expect(spendCell(s.run)).toMatchObject({ amount: '$0.00', of: 'of $100', line: 'At $100 the team pauses and asks you.' });
    // D56: the message box says when the chosen member reads it.
    expect(composerHint(s.run, 'builder')).toEqual({ name: 'builder', text: 'is working: it gets your message during this turn.' });
    expect(composerHint(s.run, null)).toEqual({
      name: null,
      text: 'A working member gets your message during its turn, a ready one at its next turn, a waiting one after its answer; an idle one wakes up.',
    });
    // D59: Latest's ages read "… ago"; D46: All activity's clock has seconds.
    const moments = latestMoments(s.events, s.run.leader, 5, false);
    expect(moments.length).toBeGreaterThan(0);
    for (const m of moments) expect(latestAgo(m.at, s.now)).toMatch(/^\d[\d\u00a0 a-z]* ago$/);
    expect(clockSecOf(s.run.asOf)).toMatch(/^\d{2}:\d{2}:\d{2}$/);
  });
});

describe('a member asks the owner itself (ask_owner)', () => {
  const s = story('member_question');
  const first = firstOf(s.raw);
  const words = first.words as string;

  it('names the asking member, cuts its words at 90 in the band and 160 on cards, and keeps the whole question for the answer view', () => {
    // The asker is the member, never "owner"; the header comes as Temper sends it.
    expect(first).toMatchObject({ kind: 'question', member: 'builder', header: 'builder asks' });
    const cell = youCell(s.run);
    expect(cell).toMatchObject({ tone: 'needs', from: 'From builder', action: 'answer', more: 0, waitId: first.wait_id });
    // D62: the first line, cut after a whole word at 90 characters, then "…".
    const band = quoted(cell.title);
    expect(band).toBe(cutAt(words, 90));
    expect(band.length).toBeLessThanOrEqual(90);
    expect(band.endsWith('\u2026')).toBe(true);
    expect(words.startsWith(band.slice(0, -1))).toBe(true);
    // The cut ends where a word ends.
    expect(words.charAt(band.length - 1)).toMatch(/[^\p{L}\p{N}]/u);
    // Card and activity rows keep 160; Temper's own sentence cut is already shorter.
    expect(rowWords('question', words)).toBe(cutAt(words, 160));
    const builder = s.run.members.find((m) => m.name === 'builder');
    expect(builder && memberLine(builder)).toEqual({ label: null, text: rowWords('question', words), quoted: false });
    // The answer view's question and Temper's fixed note, exactly as sent.
    const { wait } = teamWaits(s.raw as unknown as TeamRun);
    expect(wait).toMatchObject({ wait_id: first.wait_id, member: 'builder', header: 'builder asks' });
    expect(wait?.question).toHaveLength(906);
    expect(wait?.note).toBe("A team member's words, not Temper's. Never put a key or password in an answer.");
    // While Temper doesn't answer, a held question still shows (D64).
    expect(youCell(s.run, '2 min')).toMatchObject({ tone: 'needs', title: cell.title });
    // D56: the held member reads a message once its question is answered.
    expect(composerHint(s.run, 'builder')).toEqual({
      name: 'builder',
      text: "is waiting for an answer: it gets your message once that's answered.",
    });
  });

  it("never cuts Temper's own words", () => {
    const long = `${'Temper could not finish the turn because the account stopped answering in time; '.repeat(3)}Retry or stop.`;
    for (const kind of ['recovery', 'pause', 'stalled', 'settings', 'limit']) {
      expect(bandWords(kind, long)).toBe(long);
      expect(rowWords(kind, long)).toBe(long);
    }
    expect(bandWords('question', long)).toBe(cutAt(long, 90));
    const failed = story('failed', (raw) => {
      firstOf(raw).words = long;
    });
    expect(youCell(failed.run)).toMatchObject({ title: `Needs you: \u201c${long}\u201d`, from: 'From builder', action: 'answer' });
  });
});

describe('the usage limit', () => {
  it("shows the question Temper asks as it comes, with the run's own account", () => {
    const s = story('limit_asked');
    const words = firstOf(s.raw).words as string;
    expect(youCell(s.run).title).toBe(`Needs you: \u201c${words}\u201d`);
    expect(words).toContain('anthropic-4');
    const { wait } = teamWaits(s.raw as unknown as TeamRun);
    expect(wait?.question?.startsWith(words)).toBe(true);
    expect(wait?.note ?? null).toBeNull();
  });

  it('names the next check only while the team is in its limit, and never promises a resume (D65)', () => {
    const s = story('limit_start_check');
    expect(s.run.phase).toMatchObject({ name: 'limit', resumeVerified: false, resetsKnown: false });
    const sentence = nowCell(s.run, s.now).sentence ?? '';
    expect(sentence).toMatch(/^Usage cannot be checked; the team keeps waiting\. Next allowance check at .+\. No usable reset time\.$/);
    expect(sentence).not.toMatch(/resume|carries on|starts again/i);
    expect(youCell(s.run)).toMatchObject({ tone: 'calm', title: 'Nothing needs you' });
    const live = latestMoments(s.events, s.run.leader, 5, true).map((m) => textOf(m.parts));
    expect(live).toContainEqual(expect.stringMatching(/^Usage limit: next allowance check at .+; no usable reset time$/));
    // Once the team has left its limit, the old row keeps no time.
    const after = latestMoments(s.events, s.run.leader, 5, false).map((m) => textOf(m.parts));
    expect(after).toContain('Usage limit');
    expect(after.join('\n')).not.toMatch(/allowance check at/);
    expect(composerHint(s.run, null).text).toMatch(/ No new turn starts before .+\.$/);
  });
});

describe('the start (D36, D63)', () => {
  it("counts who works from Temper's own count, then the leader's goal by its `on`", () => {
    expect(nowCell(story('starting').run, null).sentence).toBe('No one is working yet. The leader has the goal.');
    const one = story('starting', (raw) => {
      (raw.counts as Raw).working = 1;
    });
    expect(nowCell(one.run, null).sentence).toBe('1 of 3 members working. The leader has the goal.');
    expect(nowCountsMembers(one.run)).toBe(true);
    const none = story('starting', (raw) => {
      delete (raw.counts as Raw).working;
    });
    expect(nowCell(none.run, null).sentence).toBe('The leader has the goal.');
    const noGoal = story('starting', (raw) => {
      for (const m of raw.members as Raw[]) if (m.leader) m.on = null;
    });
    expect(nowCell(noGoal.run, null).sentence).toBe('No one is working yet. The leader starts first.');
  });
});

describe('while Temper does not answer (D64)', () => {
  it('leaves out "Last activity" and says when something last needed you', () => {
    const s = story('working');
    expect(nowCell(s.run, s.now, true).sentence).toBe('3 of 3 members working.');
    expect(youCell(s.run, '15 min')).toMatchObject({
      tone: 'stale',
      title: 'Nothing needed you 15 min ago',
      line: 'Questions show up once Temper answers.',
      hint: false,
    });
  });
});

describe('cutAt (D62)', () => {
  it('keeps text that fits, cuts after a whole word, and drops a trailing comma or dash', () => {
    expect(cutAt('Short words stay whole.', 90)).toBe('Short words stay whole.');
    expect(cutAt('x'.repeat(120), 90)).toBe(`${'x'.repeat(89)}\u2026`);
    expect(cutAt(`${'word '.repeat(17)}tailpiece and more words`, 90)).toBe(`${'word '.repeat(17).trimEnd()}\u2026`);
    expect(cutAt(`${'a'.repeat(80)}, ${'b'.repeat(20)}`, 90)).toBe(`${'a'.repeat(80)}\u2026`);
    expect(cutAt(`${'a'.repeat(80)} - ${'b'.repeat(20)}`, 90)).toBe(`${'a'.repeat(80)}\u2026`);
  });
});
