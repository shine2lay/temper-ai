/**
 * Design's real-run words, D102 and D104-D110 (Design's home decisions of
 * 2026-10-10 06:00; Frontend task #26), on Temper's own samples: its G6 runs
 * (e2e/fixtures/team/flow/real-g6), its earlier real runs (real/) and the
 * derived flow states (derived/). A state no sample shows is a pure transform
 * of one: an existing field takes another value, or an existing event is
 * copied; no key is invented (`patch` checks it).
 * D104's day words follow the viewer's calendar, so this file sets TZ itself
 * and puts it back. Pure functions only: nothing renders, no server starts.
 */
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';

import { toGlanceEvent, toGlanceEventPage, toGlanceRun } from '@/lib/teamGlanceAdapter';
import {
  REASON_ROW_KEY,
  activityRows,
  atWords,
  clockDayOf,
  composerHint,
  dayWords,
  glanceClock,
  hubBatches,
  hubPartWords,
  lastRecordedAt,
  latestMoments,
  limitCheckShown,
  memberChip,
  nowCell,
  phaseEnded,
  refusalWhy,
  type GlanceEvent,
  type GlanceMessageEvent,
  type GlanceRun,
  type Moment,
} from '@/lib/teamGlance';

type Raw = Record<string, unknown>;

const ROOT = '../../e2e/fixtures/team/flow/';
const SAMPLES: Record<string, Raw> = {
  ...import.meta.glob<Raw>('../../e2e/fixtures/team/flow/real-g6/*.json', { eager: true, import: 'default' }),
  ...import.meta.glob<Raw>('../../e2e/fixtures/team/flow/real/*.json', { eager: true, import: 'default' }),
  ...import.meta.glob<Raw>('../../e2e/fixtures/team/flow/derived/*.json', { eager: true, import: 'default' }),
};
/** Every sample with a reply and a feed: 'real-g6/retry', 'derived/resumed', and so on. */
const NAMES = Object.keys(SAMPLES)
  .filter((p) => p.endsWith('-events.json'))
  .map((p) => p.slice(ROOT.length, -'-events.json'.length))
  .filter((n) => `${ROOT}${n}.json` in SAMPLES)
  .sort();

function copy<T>(x: T): T {
  return JSON.parse(JSON.stringify(x)) as T;
}

function must<T>(x: T | undefined | null, what: string): T {
  if (x === undefined || x === null) throw new Error(`no ${what}`);
  return x;
}

/** A transform's one edit: fields the sample already has take new values; a missing key fails the test. */
function patch(target: Raw, values: Raw): Raw {
  for (const [k, v] of Object.entries(values)) {
    expect(Object.hasOwn(target, k), `the sample has ${k}`).toBe(true);
    target[k] = v;
  }
  return target;
}

interface Story {
  raw: Raw;
  feed: Raw;
  run: GlanceRun;
  events: GlanceEvent[];
  /** The page's clock: the newer of the two replies' as_of (D4). */
  now: number | null;
}

/** A sample as the page reads it, through the one adapter; `change` transforms its reply and feed first. */
function story(name: string, change?: (raw: Raw, events: Raw[], feed: Raw) => void): Story {
  const raw = copy(must(SAMPLES[`${ROOT}${name}.json`], `sample ${name}`));
  const feed = copy(must(SAMPLES[`${ROOT}${name}-events.json`], `feed of ${name}`));
  change?.(raw, feed.events as Raw[], feed);
  const run = toGlanceRun(raw);
  const page = toGlanceEventPage(feed, 0);
  return { raw, feed, run, events: page.events, now: glanceClock(run.asOf, page.asOf) };
}

const textOf = (m: Moment) => m.parts.map((p) => p.text).join('');
/** Latest as LatestMoments.tsx reads it; a `limit` past five shows every big moment. */
const latestOf = (s: Story, limit = 5) =>
  latestMoments(s.events, s.run.leader, limit, limitCheckShown(s.run.phase), new Set(s.run.members.map((m) => m.name)), s.run, {
    now: s.now,
  });
const latest = (s: Story) => latestOf(s).map(textOf);
/** All activity as AllActivity.tsx reads it, newest first. */
const activityOf = (s: Story) => activityRows(s.events, s.run, limitCheckShown(s.run.phase), { now: s.now });
const activity = (s: Story) => activityOf(s).map(textOf);
const feedOf = (s: Story) => s.feed.events as Raw[];
function one(events: Raw[], kind: string): Raw {
  const found = events.filter((e) => e.kind === kind);
  expect(found, `one ${kind} event`).toHaveLength(1);
  return found[0];
}
/** Now as StatusBand.tsx reads it: the newest time Temper recorded stands in for a missing end (D105). */
const nowOf = (s: Story) => nowCell(s.run, s.now, false, lastRecordedAt(s.run, s.events));

/** Los Angeles: the zone #21 read Temper's G6 runs in; D104's calendar is the viewer's. */
const ZONE = 'America/Los_Angeles';
beforeAll(() => {
  vi.stubEnv('TZ', ZONE);
});
afterAll(() => {
  vi.unstubAllEnvs();
});
function inZone<T>(zone: string, fn: () => T): T {
  vi.stubEnv('TZ', zone);
  try {
    return fn();
  } finally {
    vi.stubEnv('TZ', ZONE);
  }
}
/** A wall-clock time in Los Angeles in October 2026 (PDT), as an ISO time Temper sends. */
const la = (wall: string) => new Date(`${wall}-07:00`).toISOString();

describe('D104: a future time gets its day, by Temper’s clock, on the viewer’s calendar', () => {
  // Temper's clock: Fri Oct 9 2026, 8:00 PM in Los Angeles.
  const now = Date.parse(la('2026-10-09T20:00:00'));

  it('today, tomorrow, within 6 days, later; 23:59 vs 00:00 and day 6 vs day 7', () => {
    const cases: [wall: string, inSentence: string, asTime: string][] = [
      ['2026-10-09T20:00:30', 'at 8:00 PM', '8:00 PM'],
      ['2026-10-09T23:59:00', 'at 11:59 PM', '11:59 PM'],
      ['2026-10-10T00:00:00', 'tomorrow at 12:00 AM', 'tomorrow at 12:00 AM'],
      ['2026-10-10T23:59:00', 'tomorrow at 11:59 PM', 'tomorrow at 11:59 PM'],
      ['2026-10-11T00:00:00', 'Sun at 12:00 AM', 'Sun at 12:00 AM'],
      ['2026-10-12T20:59:00', 'Mon at 8:59 PM', 'Mon at 8:59 PM'],
      ['2026-10-15T23:59:00', 'Thu at 11:59 PM', 'Thu at 11:59 PM'],
      ['2026-10-16T00:00:00', 'Fri Oct 16 at 12:00 AM', 'Fri Oct 16 at 12:00 AM'],
      ['2026-10-26T08:05:00', 'Mon Oct 26 at 8:05 AM', 'Mon Oct 26 at 8:05 AM'],
    ];
    for (const [wall, inSentence, asTime] of cases) {
      expect(atWords(la(wall), now), wall).toBe(inSentence);
      expect(clockDayOf(la(wall), now), wall).toBe(asTime);
    }
  });

  it('the ruling’s example: a check 7 days on is "Mon Oct 12 at 8:59 PM"', () => {
    expect(atWords(la('2026-10-12T20:59:00'), Date.parse(la('2026-10-05T20:00:00')))).toBe('Mon Oct 12 at 8:59 PM');
  });

  it('past times are unchanged; without Temper’s clock a time has no day', () => {
    expect(atWords(la('2026-10-09T19:59:00'), now)).toBe('at 7:59 PM');
    expect(atWords(la('2026-10-07T09:00:00'), now)).toBe('at 9:00 AM');
    expect(clockDayOf(la('2026-10-07T09:00:00'), now)).toBe('9:00 AM');
    expect(dayWords(la('2026-10-16T00:00:00'), null)).toBe('');
    expect(atWords(la('2026-10-16T00:00:00'), null)).toBe('at 12:00 AM');
    expect(atWords(null, now)).toBeNull();
  });

  it('"today" is Temper’s day, whatever the machine’s clock says', () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    try {
      vi.setSystemTime(new Date('2031-03-01T12:00:00Z'));
      expect(atWords(la('2026-10-10T00:00:00'), now)).toBe('tomorrow at 12:00 AM');
      expect(atWords(la('2026-10-09T23:59:00'), now)).toBe('at 11:59 PM');
    } finally {
      vi.useRealTimers();
    }
  });

  it('the calendar is the viewer’s: the same instants read in Tokyo', () => {
    // Temper's clock there: Sat Oct 10, 12:00 PM. 00:00 in Los Angeles is 4:00 PM that day in Tokyo.
    inZone('Asia/Tokyo', () => {
      expect(atWords(la('2026-10-10T00:00:00'), now)).toBe('at 4:00 PM');
      expect(atWords(la('2026-10-10T08:00:00'), now)).toBe('tomorrow at 12:00 AM');
    });
  });

  it('restart_deferred (real-g6): Now, the composer, Latest and All activity give the check its day', () => {
    // Temper's clock: Fri Oct 9, 8:59 PM; its next allowance check: Mon Oct 12, 8:59 PM.
    const s = story('real-g6/restart_deferred');
    expect(nowOf(s).sentence).toContain(' Next allowance check Mon at 8:59 PM.');
    expect(composerHint(s.run, null, s.now).text).toContain(' No new turn starts before Mon at 8:59 PM.');
    const row = /^Usage limit: next allowance check Mon at 8:59 PM(;|$)/;
    expect(latest(s)).toContainEqual(expect.stringMatching(row));
    expect(activity(s)).toContainEqual(expect.stringMatching(row));
  });

  it.each([
    ['2026-10-12T03:59:08.000000+00:00', 'tomorrow at 8:59 PM'],
    ['2026-10-06T03:59:08.000000+00:00', 'Mon Oct 12 at 8:59 PM'],
  ])('restart_deferred read at %s: "Next allowance check %s."', (asOf, words) => {
    const s = story('real-g6/restart_deferred', (raw, _events, feed) => {
      patch(raw, { as_of: asOf });
      if (Object.hasOwn(feed, 'as_of')) patch(feed, { as_of: asOf });
    });
    expect(nowOf(s).sentence).toContain(` Next allowance check ${words}.`);
    expect(activity(s)).toContainEqual(expect.stringMatching(new RegExp(`^Usage limit: next allowance check ${words}(;|$)`)));
  });
});

describe('D105: an ended run reads as ended', () => {
  const ended = NAMES.filter((n) => phaseEnded(story(n).run.phase.name));
  const live = NAMES.filter((n) => !ended.includes(n));

  it('the samples end in every way a run ends', () => {
    expect(new Set(ended.map((n) => story(n).run.phase.name))).toEqual(new Set(['done', 'stopped', 'failed', 'interrupted']));
  });

  it.each(ended)('%s: every card reads "Ended", neutral, with no live duration', (name) => {
    const s = story(name);
    for (const m of s.run.members) {
      expect(memberChip(m, s.run.phase.name, s.now), m.name).toMatchObject({ text: 'Ended', tone: 'grey', busy: false });
    }
  });

  it('a live run’s cards never read "Ended"', () => {
    for (const name of live) {
      const s = story(name);
      for (const m of s.run.members) expect(memberChip(m, s.run.phase.name, s.now).text, `${name} ${m.name}`).not.toBe('Ended');
    }
  });

  it('interrupted_no_end (real-g6): the newest time Temper recorded, and that it recorded no end', () => {
    const s = story('real-g6/interrupted_no_end');
    expect(s.run.elapsedS).toBeNull();
    expect(nowOf(s)).toMatchObject({
      word: 'Interrupted',
      sentence: 'Last activity 8:40 PM. Temper didn\u2019t record when it ended.',
      reason: 'the run ended (interrupted) without the team ending',
    });
  });

  it('"Last activity" is the newest time in the reply and the feed: a member’s turn, an event', () => {
    const turn = story('real-g6/interrupted_no_end', (raw) => {
      patch((raw.members as Raw[])[1].last_turn as Raw, { ended_at: '2026-10-10T03:52:00.000000+00:00' });
    });
    expect(nowOf(turn).sentence).toBe('Last activity 8:52 PM. Temper didn\u2019t record when it ended.');
    const event = story('real-g6/interrupted_no_end', (_raw, events) => {
      patch(events[events.length - 1], { at: '2026-10-10T03:45:00.000000+00:00' });
    });
    expect(nowOf(event).sentence).toBe('Last activity 8:45 PM. Temper didn\u2019t record when it ended.');
    expect(nowCell(event.run, event.now, false, null).sentence).toBe('Temper didn\u2019t record when it ended.');
  });

  it('interrupted (real-g6): Temper’s reason is Now’s second line and, with no time, the newest row of All activity', () => {
    const s = story('real-g6/interrupted');
    expect(nowOf(s)).toMatchObject({
      word: 'Interrupted',
      sentence: 'The run ended without the team ending.',
      reason: 'the run ended (interrupted) without the team ending',
    });
    const rows = activityOf(s);
    expect(rows[0]).toMatchObject({ key: REASON_ROW_KEY, at: null });
    expect(textOf(rows[0])).toBe('Interrupted: the run ended (interrupted) without the team ending');
    expect(rows.filter((r) => r.key === REASON_ROW_KEY)).toHaveLength(1);
  });

  it('a reason of 80 characters shows whole; a longer one is cut in Now and whole in All activity', () => {
    const eighty = `${'Temper restarted while 3 turns were running and kept their work on the branch'.padEnd(79, '.')}.`;
    expect(eighty).toHaveLength(80);
    const whole = story('real-g6/interrupted', (raw) => void patch(raw.phase as Raw, { reason: eighty }));
    expect(nowOf(whole).reason).toBe(eighty);
    const long = 'Temper restarted while 3 turns were running, and the team could not pick their work up again afterwards.';
    const cut = story('real-g6/interrupted', (raw) => void patch(raw.phase as Raw, { reason: long }));
    const reason = must(nowOf(cut).reason, 'reason line');
    expect(reason.length).toBeLessThanOrEqual(80);
    expect(reason).toMatch(/\u2026$/);
    expect(long.startsWith(reason.slice(0, -1))).toBe(true);
    expect(activity(cut)).toContain(`Interrupted: ${long}`);
  });

  it('with phase.since the reason row stands at its time among the events', () => {
    let since = '';
    const s = story('real-g6/interrupted', (raw, events) => {
      since = String(events[Math.floor(events.length / 2)].at);
      patch(raw.phase as Raw, { since });
    });
    const rows = activityOf(s);
    const i = rows.findIndex((r) => r.key === REASON_ROW_KEY);
    expect(i).toBeGreaterThan(0);
    expect(rows[i].at).toBe(since);
    const t = Date.parse(since);
    for (const r of rows.slice(0, i)) expect(Date.parse(String(r.at))).toBeGreaterThan(t);
    for (const r of rows.slice(i + 1)) expect(Date.parse(String(r.at))).toBeLessThanOrEqual(t);
  });

  it.each(['derived/stopped', 'derived/run_failed'])('%s: the reason stays where it shows, in Now; no reason row', (name) => {
    const s = story(name);
    const reason = String((s.raw.phase as Raw).reason);
    expect(nowOf(s).sentence).toContain(reason.slice(0, 30));
    expect(activityOf(s).some((r) => r.key === REASON_ROW_KEY)).toBe(false);
  });
});

describe('D106: a turn ended at its cap', () => {
  it('retry (real-g6): the tool-call limit, with no number (tool_calls counts the calls made)', () => {
    const rows = activity(story('real-g6/retry'));
    expect(rows.filter((r) => /limit/.test(r))).toEqual(['checker\u2019s turn 1 ended at its tool-call limit.']);
    expect(rows).toContain('lead ended turn 1: completed (no tool call)');
  });

  it('time_limit, by analogy (the same turn, ended by its time limit)', () => {
    const s = story('real-g6/retry', (_raw, events) => {
      patch(must(events.find((e) => e.ended_by === 'call_cap'), 'capped turn'), { ended_by: 'time_limit' });
    });
    expect(activity(s)).toContain('checker\u2019s turn 1 ended at its time limit.');
  });
});

describe('D107: a share Temper refused', () => {
  const noReason = 'checker\u2019s version wasn\u2019t shared. Temper gave no reason.';

  it('conflict (real-g6): Temper’s why is only the verb, so it gave no reason', () => {
    const s = story('real-g6/conflict');
    expect(one(feedOf(s), 'share_refused').why).toBe('refused');
    expect(activity(s)).toContain(noReason);
  });

  it.each([null, '', '  ', 'Refused.', ' share refused ', 'Share refused!', 'share_refused', 'SHARE_REFUSED\u2026'])(
    'why %j is no reason',
    (why) => {
      expect(refusalWhy(why)).toBeNull();
      const s = story('real-g6/conflict', (_raw, events) => void patch(one(events, 'share_refused'), { why }));
      expect(activity(s)).toContain(noReason);
    },
  );

  it('a real reason is given word for word', () => {
    const why = 'part.md changed on the shared branch while checker worked';
    const s = story('real-g6/conflict', (_raw, events) => void patch(one(events, 'share_refused'), { why }));
    expect(activity(s)).toContain(`checker\u2019s version wasn\u2019t shared: ${why}`);
    expect(refusalWhy('refused twice')).toBe('refused twice');
  });

  it('no row of any sample gives the verb as its reason', () => {
    for (const name of NAMES) for (const row of activity(story(name))) expect(row, name).not.toMatch(/refused: refused/i);
  });
});

describe('D108: an answer or a message', () => {
  const owners = (events: Raw[]) => events.filter((e) => e.kind === 'message' && e.from === 'owner');

  it('member_question (real-g6): your words to checker after your answer to its own question answer it', () => {
    expect(activity(story('real-g6/member_question'))).toContain('You answered checker: \u201cyes\u201d');
  });

  it('a second message to checker, with no answer between, is a message', () => {
    const s = story('real-g6/member_question', (_raw, events) => {
      const again = copy(owners(events)[0]);
      patch(again, { seq: Math.max(...events.map((e) => Number(e.seq))) + 1 });
      if (Object.hasOwn(again, 'message_id')) patch(again, { message_id: `${String(again.message_id)}-again` });
      events.push(again);
    });
    const rows = activity(s);
    expect(rows[0]).toBe('You messaged checker: \u201cyes\u201d');
    expect(rows.filter((r) => r === 'You answered checker: \u201cyes\u201d')).toHaveLength(1);
  });

  it('your words to a member whose own question you didn’t answer are a message', () => {
    const s = story('real-g6/member_question', (_raw, events) => void patch(owners(events)[0], { to: 'builder' }));
    expect(activity(s)).toContain('You messaged builder: \u201cyes\u201d');
  });

  it('resumed: a check-in answered with Guide keeps its own answer row; the guide’s words are a message', () => {
    const s = story('derived/resumed');
    const rows = activity(s);
    const guided = 'You messaged lead: \u201cKeep the README under 40 lines and add a Usage section.\u201d';
    expect(rows).toEqual(expect.arrayContaining(['You answered: guide', guided]));
    expect(rows.indexOf('You answered: guide') - rows.indexOf(guided)).toBe(1);
    expect(rows).toContainEqual(expect.stringMatching(/^Temper asked you: \u201cThe team has spent \$105\.00/));
    expect(latest(s)).toContain('You answered: guide');
  });
});

describe('D109: the usage limit is over', () => {
  it('limit_ended (real-g6): when the team carried on, naming nobody (Temper’s event has no `by`)', () => {
    const s = story('real-g6/limit_ended');
    expect(Object.hasOwn(one(feedOf(s), 'limit_over'), 'by')).toBe(false);
    const words = 'The usage limit is over. The team carried on at 8:40 PM.';
    expect(latest(s)).toContain(words);
    expect(activity(s)).toContain(words);
  });
});

describe('D110: one formatter for Latest and All activity', () => {
  it.each(NAMES)('%s: Latest says what All activity says, event by event', (name) => {
    const s = story(name);
    const rows = new Map(activityOf(s).map((r) => [r.key, textOf(r)]));
    for (const m of latestOf(s, 1000).filter((x) => /^e\d+$/.test(x.key))) {
      expect(textOf(m), `${name} ${m.key}`).toBe(rows.get(`a${m.key.slice(1)}`));
    }
  });

  it.each(NAMES)('%s: the asker is named, never "The team"; a colon before quoted words', (name) => {
    const s = story(name);
    for (const text of [...activity(s), ...latestOf(s, 1000).map(textOf)]) {
      expect(text).not.toMatch(/The team asked you/);
      expect(text).not.toMatch(/(?<!: )\u201c/);
    }
  });

  it('a member’s own question names it; Temper’s own wait names Temper', () => {
    expect(activity(story('real-g6/member_question'))).toContainEqual(expect.stringMatching(/^checker asked you: \u201c/));
    expect(activity(story('real-g6/settings_late'))).toContainEqual(expect.stringMatching(/^Temper asked you: \u201c/));
  });
});

describe('D102: the corner cue names both senders (D82’s words)', () => {
  it('your message and Temper’s in one second are one batch, both named', () => {
    const s = story('derived/map_burst');
    const base = must(
      feedOf(s).find((e) => e.kind === 'message' && e.from_kind === 'temper'),
      'a message from Temper',
    );
    const names = s.run.members.map((m) => m.name);
    expect(names).toHaveLength(6);
    const sent = [...names.map((to) => ['temper', to]), ['owner', names[0]]].map(([from, to], i) => {
      const e = patch(copy(base), { seq: 1000 + i, from, from_kind: from, to });
      if (Object.hasOwn(e, 'member')) patch(e, { member: from });
      if (Object.hasOwn(e, 'message_id')) patch(e, { message_id: `cue-${i}` });
      return toGlanceEvent(e);
    });
    const messages = sent.filter((e): e is GlanceMessageEvent => e?.kind === 'message');
    expect(messages).toHaveLength(7);
    const batches = hubBatches(messages, new Set(names));
    expect(batches).toHaveLength(1);
    // TeamMap.tsx joins a batch's parts with " · " (D82).
    expect(batches[0].parts.map(hubPartWords).join(' \u00b7 ')).toBe('Temper \u2192 6 members \u00b7 You \u2192 1 member');
  });
});
