/**
 * The free-flowing Team page's model and words (lib/teamGlance.ts) read
 * through its one adapter (lib/teamGlanceAdapter.ts), on Temper's own
 * serializer replies (e2e/fixtures/team/flow/real, FLOW #80) and the states
 * derived from them (flow/derived, made by scripts/make_flow_fixtures.mjs).
 * Pure functions only: nothing renders and nothing starts a server.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

import roundRun from '../../e2e/fixtures/team/run-running.json';

import { isFlowRun, toGlanceEvent, toGlanceEventPage, toGlanceRun, toGlanceTimelineDone } from '@/lib/teamGlanceAdapter';
import { freshByClock, GLANCE_FRESH_MS } from '@/hooks/useTeamGlanceEvents';
import { teamRunPollingEnded } from '@/hooks/useTeamRun';
import {
  DOT_MAX_AT_ONCE,
  DOT_MS,
  DOT_STAGGER_MS,
  clockOf,
  conflictLine,
  countLine,
  dotPlan,
  durationWords,
  extraWords,
  glanceClock,
  hourRows,
  justSent,
  latestMoments,
  listOrder,
  mapLines,
  mapSlots,
  memberChip,
  memberLine,
  messagesOf,
  msOf,
  nowCell,
  receiverName,
  agoText,
  sentLabel,
  shortAgo,
  sinceWords,
  JUST_SENT_MS,
  spendCell,
  teamCountWords,
  toolsLine,
  turnsLine,
  youCell,
  type GlanceEvent,
  type GlanceMember,
  type GlanceMessageEvent,
  type GlanceRun,
} from '@/lib/teamGlance';

type Raw = Record<string, unknown>;

const FILES = import.meta.glob<Raw>(['../../e2e/fixtures/team/flow/real/*.json', '../../e2e/fixtures/team/flow/derived/*.json'], {
  eager: true,
  import: 'default',
});

/** Temper's nine real replies (FLOW #80), each with its -events feed. */
const REAL = ['working', 'idle', 'share', 'check_in', 'closing', 'done', 'done_refused', 'stalled', 'failed'] as const;
/** The states Temper didn't send, each derived from one real reply. */
const DERIVED = [
  'starting',
  'start',
  'burst',
  'settings',
  'limit',
  'limit_asked',
  'limit_spent',
  'limit_unavailable',
  'limit_start_check',
  'draining',
  'interrupted',
  'waiting',
  'member_question',
  'check_in_running',
  'resumed',
  'stopped',
  'run_failed',
] as const;
type Name = (typeof REAL)[number] | (typeof DERIVED)[number];
const ALL: Name[] = [...REAL, ...DERIVED];

const isReal = (name: string) => (REAL as readonly string[]).includes(name);

/** A fixture's raw JSON, as a fresh copy a test may change. */
function rawOf(name: Name, feed = false): Raw {
  const key = `../../e2e/fixtures/team/flow/${isReal(name) ? 'real' : 'derived'}/${name}${feed ? '-events' : ''}.json`;
  const body = FILES[key];
  if (!body) throw new Error(`no fixture ${key}`);
  return JSON.parse(JSON.stringify(body)) as Raw;
}

interface Story {
  raw: Raw;
  feedRaw: Raw;
  run: GlanceRun;
  events: GlanceEvent[];
  /** The page's clock: the newest of the two replies' as_of (D4, D14). */
  now: number | null;
}

/** The wait Temper says needs the owner first (you.first), read from the reply itself. */
function firstWait(name: Name): string {
  return ((rawOf(name, false).you as Raw).first as Raw).wait_id as string;
}

function story(name: Name, change?: (raw: Raw) => void): Story {
  const raw = rawOf(name);
  change?.(raw);
  const feedRaw = rawOf(name, true);
  const run = toGlanceRun(raw);
  const page = toGlanceEventPage(feedRaw, 0);
  return { raw, feedRaw, run, events: page.events, now: glanceClock(run.asOf, page.asOf) };
}

const rawMembers = (raw: Raw) => raw.members as Raw[];
function rawMember(raw: Raw, name: string): Raw {
  const m = rawMembers(raw).find((x) => x.name === name);
  if (!m) throw new Error(`no member ${name}`);
  return m;
}
function member(run: GlanceRun, name: string): GlanceMember {
  const m = run.members.find((x) => x.name === name);
  if (!m) throw new Error(`no member ${name}`);
  return m;
}
// As the page calls it: the whole phase, so a pause knows whether its question is open (D88).
const chip = (s: Story, name: string) => memberChip(member(s.run, name), s.run.phase, s.now);
/** Latest as the page reads it: a limit row names its check only while the team is in its limit phase. */
// As the page calls it: the run names the starter and the cards (D110: All activity's words).
const momentText = (s: Story) =>
  latestMoments(s.events, s.run.leader, 5, s.run.phase.name === 'limit', null, s.run).map((m) => m.parts.map((p) => p.text).join(''));

/** The value at a dotted path of a raw reply, or undefined. */
function at(raw: unknown, path: string): unknown {
  let v: unknown = raw;
  for (const key of path.split('.')) {
    if (!v || typeof v !== 'object' || Array.isArray(v)) return undefined;
    v = (v as Raw)[key];
  }
  return v;
}

/**
 * A field Temper sent reaches the model: only a null (or missing) field may
 * read as not known. Text may be cut to its first line, never changed; a list
 * keeps its length.
 */
function expectRead(where: string, sent: unknown, read: unknown) {
  if (sent === null || sent === undefined) return;
  expect(read ?? null, `${where}: Temper sent ${JSON.stringify(sent)}, the page reads it as not known`).not.toBeNull();
  if (typeof sent === 'string') {
    expect(typeof read, where).toBe('string');
    expect(sent, where).toContain(read as string);
    if (sent.trim() !== '') expect((read as string).length, where).toBeGreaterThan(0);
  } else if (Array.isArray(sent)) {
    expect(Array.isArray(read) ? read.length : read, where).toBe(sent.length);
  } else {
    expect(read, where).toEqual(sent);
  }
}

/** api-fields.md section 2-3: the run reply's fields and where the model keeps them. */
const RUN_FIELDS: Array<[string, (r: GlanceRun) => unknown]> = [
  ['execution_id', (r) => r.executionId],
  ['trial.goal', (r) => r.goal],
  ['trial.leader', (r) => r.leader],
  ['started_at', (r) => r.startedAt],
  ['trial.started_by', (r) => r.startedBy],
  ['elapsed_s', (r) => r.elapsedS],
  ['last_activity_at', (r) => r.lastActivityAt],
  ['trial.project.source', (r) => r.project],
  ['as_of', (r) => r.asOf],
  ['trial.max_parallel', (r) => r.maxParallel],
  ['phase.name', (r) => r.phase.name],
  ['phase.words', (r) => r.phase.words],
  ['phase.since', (r) => r.phase.since],
  ['phase.running', (r) => r.phase.running],
  ['phase.asked', (r) => r.phase.asked],
  ['phase.reason', (r) => r.phase.reason],
  ['phase.resumes_at', (r) => r.phase.resumesAt],
  ['phase.resets_known', (r) => r.phase.resetsKnown],
  ['phase.resume_verified', (r) => r.phase.resumeVerified],
  ['phase.usage.status', (r) => r.phase.usage?.status],
  ['phase.usage.observed_at', (r) => (r.phase.usage?.status === 'ok' ? r.phase.usage.observedAt : null)],
  ['phase.usage.windows', (r) => (r.phase.usage?.status === 'ok' ? r.phase.usage.windows : null)],
  ['phase.usage.reason', (r) => (r.phase.usage?.status === 'unavailable' ? r.phase.usage.reason : null)],
  ['phase.usage_checked_at', (r) => r.phase.usageCheckedAt],
  ['phase.blocked_windows', (r) => r.phase.blockedWindows],
  ['spend.cost_usd', (r) => r.spend?.cost],
  ['spend.pause_every_usd', (r) => r.spend?.pauseEvery],
  ['spend.last_check_in_usd', (r) => r.spend?.lastCheckIn],
  ['spend.next_check_in_usd', (r) => r.spend?.nextCheckIn],
  ['spend.since_check_in_usd', (r) => r.spend?.sinceCheckIn],
  ['spend.check_ins', (r) => r.spend?.checkIns],
  ['you.count', (r) => r.you.count],
  ['you.first.wait_id', (r) => r.you.first?.waitId],
  ['you.first.kind', (r) => r.you.first?.kind],
  ['you.first.member', (r) => r.you.first?.member],
  ['you.first.header', (r) => r.you.first?.header],
  ['you.first.words', (r) => r.you.first?.words],
  ['you.first.opened_at', (r) => r.you.first?.openedAt],
  ['counts.members', (r) => r.counts.members],
  ['counts.working', (r) => r.counts.working],
  ['counts.ready', (r) => r.counts.ready],
  ['counts.idle', (r) => r.counts.idle],
  ['counts.held', (r) => r.counts.held],
  ['counts.failed', (r) => r.counts.failed],
  ['counts.ended', (r) => r.counts.ended],
  ['members', (r) => r.members],
  ['links', (r) => r.links],
  ['work.latest.version_no', (r) => r.work.latest?.versionNo],
  ['work.latest.commit_short', (r) => r.work.latest?.commitShort],
  ['work.latest.by', (r) => r.work.latest?.by],
  ['work.latest.at', (r) => r.work.latest?.at],
  ['work.latest.note', (r) => r.work.latest?.note],
  ['work.latest.files_changed', (r) => r.work.latest?.filesChanged],
  ['work.latest.files_total', (r) => r.work.latest?.filesTotal],
  ['work.shares', (r) => r.work.shares],
  ['work.shares_total', (r) => r.work.total],
  ['work.summary', (r) => r.work.summary],
  ['events_cursor', (r) => r.eventsCursor],
  ['events_total', (r) => r.eventsTotal],
];

/** api-fields.md section 4: a member's fields. */
const MEMBER_FIELDS: Array<[string, (m: GlanceMember) => unknown]> = [
  ['name', (m) => m.name],
  ['role', (m) => m.role],
  ['leader', (m) => m.leader],
  ['state', (m) => m.state],
  ['since', (m) => m.since],
  ['turn_no', (m) => m.turnNo],
  ['on.kind', (m) => m.on?.kind],
  ['on.text', (m) => m.on?.text],
  ['on.from', (m) => m.on?.from],
  ['on.to', (m) => m.on?.to],
  ['on.at', (m) => m.on?.at],
  ['on.message_id', (m) => m.on?.messageId],
  ['idle_note', (m) => m.idleNote],
  ['idle_reason', (m) => m.idleReason],
  ['tools_now', (m) => m.toolsNow],
  ['ready_messages', (m) => m.readyMessages],
  ['last_sent.to', (m) => m.lastSent?.to],
  ['last_sent.kind', (m) => m.lastSent?.kind],
  ['last_sent.text', (m) => m.lastSent?.text],
  ['last_sent.at', (m) => m.lastSent?.at],
  ['last_sent.message_id', (m) => m.lastSent?.messageId],
  ['last_share.note', (m) => m.lastShareNote],
  ['conflicts', (m) => m.conflicts],
  ['wait_id', (m) => m.waitId],
  ['turns', (m) => m.turns],
  ['cost_usd', (m) => m.cost],
  ['last_turn.retry_of', (m) => m.retryOf],
  ['last_turn.error', (m) => m.lastError],
];

/** api-fields.md section 6: each event kind's own fields (raw name, model name). */
const EVENT_FIELDS: Record<string, Array<[string, string]>> = {
  message: [
    ['from', 'from'],
    ['from_kind', 'fromKind'],
    ['to', 'to'],
    ['message_kind', 'messageKind'],
    ['text', 'text'],
    ['message_id', 'messageId'],
  ],
  turn_start: [
    ['turn_no', 'turnNo'],
    ['retry_of', 'retryOf'],
  ],
  turn_end: [
    ['turn_no', 'turnNo'],
    ['ended', 'ended'],
    ['ended_by', 'endedBy'],
    ['cost_usd', 'cost'],
    ['tool_calls', 'toolCalls'],
  ],
  share: [
    ['version_no', 'versionNo'],
    ['commit_short', 'commitShort'],
    ['note', 'note'],
    ['files_changed', 'filesChanged'],
  ],
  idle: [
    ['note', 'note'],
    ['reason', 'reason'],
  ],
  wake: [['by', 'by']],
  wait_opened: [
    ['wait_id', 'waitId'],
    ['wait_kind', 'waitKind'],
    ['words', 'words'],
  ],
  wait_answered: [
    ['wait_id', 'waitId'],
    ['wait_kind', 'waitKind'],
    ['answer', 'answer'],
    ['by', 'by'],
  ],
  check_in: [['at_usd', 'atUsd']],
  closing: [['summary', 'summary']],
  done: [
    ['summary', 'summary'],
    ['version_no', 'versionNo'],
    ['commit_short', 'commitShort'],
  ],
  done_refused: [['reasons', 'reasons']],
  limit: [
    ['resumes_at', 'resumesAt'],
    ['resets_known', 'resetsKnown'],
  ],
  ended: [
    ['decision', 'decision'],
    ['reason', 'reason'],
  ],
};

/** Every field Temper sent reads as sent (the per-reply contract check). */
function expectMirror(name: Name) {
  const s = story(name);
  for (const [path, pick] of RUN_FIELDS) expectRead(`${name}: ${path}`, at(s.raw, path), pick(s.run));
  expect(s.run.phase.name, `${name}: phase`).not.toBe('unknown');
  for (const raw of rawMembers(s.raw)) {
    const m = member(s.run, raw.name as string);
    for (const [path, pick] of MEMBER_FIELDS) expectRead(`${name}: ${m.name}.${path}`, at(raw, path), pick(m));
    expect(m.state, `${name}: ${m.name}.state`).not.toBe('unknown');
    if (m.waitId) expect(m.waitWords, `${name}: ${m.name}'s wait words`).not.toBeNull();
  }
  for (const raw of s.raw.links as Raw[]) {
    const l = s.run.links.find((x) => x.from === raw.from && x.to === raw.to);
    expectRead(`${name}: link ${String(raw.from)}->${String(raw.to)}`, raw.count, l?.count);
    expectRead(`${name}: link ${String(raw.from)}->${String(raw.to)} last_at`, raw.last_at, l?.lastAt);
  }
  const page = toGlanceEventPage(s.feedRaw, 0);
  expectRead(`${name}: events cursor`, s.feedRaw.cursor, page.cursor);
  expectRead(`${name}: events more`, s.feedRaw.more, page.more);
  expectRead(`${name}: events as_of`, s.feedRaw.as_of, page.asOf);
  for (const raw of s.feedRaw.events as Raw[]) {
    const e = toGlanceEvent(raw);
    const where = `${name}: event ${String(raw.seq)} ${String(raw.kind)}`;
    expect(e, where).not.toBeNull();
    expect(e?.kind, where).toBe(raw.kind);
    const read = e as unknown as Raw;
    for (const key of ['seq', 'at', 'member']) expectRead(`${where}.${key}`, raw[key], read[key]);
    for (const [from, to] of EVENT_FIELDS[String(raw.kind)] ?? []) expectRead(`${where}.${from}`, raw[from], read[to]);
  }
}

/** Words of the free-flowing page that must never show (rounds era, invented progress). */
const ROUND_WORDS = /\bround|\breview|verdict|pauses after|%|\bETA\b|work left|summary of/i;

/** Every word the model puts on the screen for one reply. */
function screenWords(s: Story): string[] {
  const r = s.run;
  return [
    JSON.stringify(nowCell(r, s.now)),
    JSON.stringify(youCell(r)),
    JSON.stringify(spendCell(r)),
    teamCountWords(r),
    ...r.members.flatMap((m) => [
      memberChip(m, r.phase.name, s.now).text,
      JSON.stringify(memberLine(m)),
      toolsLine(m) ?? '',
      turnsLine(m),
      conflictLine(m) ?? '',
    ]),
    ...momentText(s),
    JSON.stringify(justSent(s.events, r)),
    // D44: the hour list under the map.
    ...hourRows(mapLines(r), msOf(r.asOf)).flatMap((h) => [h.pair, h.time]),
  ];
}

afterEach(() => {
  vi.useRealTimers();
});

describe("Temper's real replies: every field it sends is read (api-fields.md)", () => {
  it.each(REAL)('%s', (name) => {
    expectMirror(name);
    if (name === 'done') {
      const timeline = rawOf(name).timeline as { entries: Raw[] };
      const entry = timeline.entries.find((e) => e.entry === 'decision')!;
      const data = entry.data as Raw;
      expect(toGlanceTimelineDone(entry)).toMatchObject({ kind: 'done', versionNo: data.version_no, commitShort: data.commit_short, summary: data.summary });
      expect(toGlanceTimelineDone({ data: { kind: 'decision' } })).toBeNull();
    }
  });

  it.each(DERIVED)('derived %s', (name) => {
    expectMirror(name);
  });

  it('no flow reply carries a round or reviews (D21)', () => {
    for (const name of ALL) {
      const raw = rawOf(name);
      expect(raw, name).not.toHaveProperty('round');
      expect(raw, name).not.toHaveProperty('reviews');
    }
  });

  it('in every reply seq order is time order, and nothing happens after as_of (D26)', () => {
    const after = (iso: unknown, asOf: string) => typeof iso === 'string' && Date.parse(iso) > Date.parse(asOf);
    for (const name of ALL) {
      const raw = rawOf(name);
      const asOf = raw.as_of as string;
      const events = rawOf(name, true).events as Raw[];
      events.forEach((e, i) => {
        expect(after(e.at, asOf), `${name} event ${e.seq}`).toBe(false);
        if (i > 0) {
          expect(e.seq as number, `${name} seq`).toBeGreaterThan(events[i - 1].seq as number);
          expect(Date.parse(e.at as string), `${name} event ${e.seq} time`).toBeGreaterThanOrEqual(Date.parse(events[i - 1].at as string));
        }
      });
      for (const m of raw.members as Raw[]) {
        for (const [field, value] of [
          ['since', m.since],
          ['last_sent.at', (m.last_sent as Raw | null)?.at],
          ['on.at', (m.on as Raw | null)?.at],
        ] as const) {
          expect(after(value, asOf), `${name} ${m.name}.${field}`).toBe(false);
        }
      }
      for (const w of raw.open_waits as Raw[]) expect(after(w.opened_at, asOf), `${name} wait`).toBe(false);
    }
  });

  it('only the derived fixtures say what they were derived from; none is provisional', () => {
    for (const name of ALL) {
      const raw = rawOf(name);
      if (isReal(name)) expect(raw, name).not.toHaveProperty('_fixture');
      else expect(String(raw._fixture), name).toMatch(/^derived from (working|idle|share|check_in|closing|done|done_refused|stalled|failed): /);
      expect(JSON.stringify(raw), name).not.toMatch(/provisional/i);
    }
  });
});

describe('the screen never reads "not known" for a field Temper sent', () => {
  it.each(ALL)('%s', (name) => {
    const s = story(name);
    const words = screenWords(s);
    expect(words.join(' \u00b7 ')).not.toMatch(/not known/i);
    expect(words.join(' \u00b7 ')).not.toMatch(ROUND_WORDS);
    expect(s.events.filter((e) => e.kind === 'other')).toEqual([]);
    // D3: while links count messages there is always a "Just sent".
    if (s.run.links.some((l) => l.count > 0)) expect(justSent(s.events, s.run)).not.toBeNull();
  });
});

describe('run mode switch (adapter)', () => {
  it('sends only kind "flow" to the glance page; old round runs keep their page', () => {
    for (const name of ALL) expect(isFlowRun(rawOf(name)), name).toBe(true);
    expect(isFlowRun(roundRun.body)).toBe(false);
    expect(isFlowRun({ ...(roundRun.body as object), kind: 'rounds' })).toBe(false);
    expect(isFlowRun(null)).toBe(false);
    expect(isFlowRun('flow')).toBe(false);
  });

  it('reads a reply missing every field without throwing, and guesses nothing', () => {
    const r = toGlanceRun({ kind: 'flow' });
    expect(r.members).toEqual([]);
    expect(r.spend).toBeNull();
    expect(spendCell(r).amount).toBe('Not known');
    expect(r.phase.name).toBe('unknown');
    expect(nowCell(r, null).word).toBe('State not known');
    expect(r.eventsTotal).toBeNull();
    expect(r.asOf).toBeNull();
  });

  it("keeps Temper's own words for a phase this page doesn't know", () => {
    const r = toGlanceRun({ kind: 'flow', phase: { name: 'tidying', words: 'Tidying the shared copy' } });
    expect(r.phase.name).toBe('unknown');
    expect(nowCell(r, null)).toMatchObject({ word: 'Tidying the shared copy', edge: 'grey' });
  });
});

describe("Temper's clock (D4, D14)", () => {
  it('is the newest as_of of the run and events replies', () => {
    const s = story('working');
    const run = msOf(s.run.asOf) ?? 0;
    const feed = msOf(s.feedRaw.as_of as string) ?? 0;
    expect(s.now).toBe(Math.max(run, feed));
    expect(glanceClock(null, undefined, 'not a time')).toBeNull();
  });

  it('ages count to it, never to the device clock', () => {
    const s = story('burst');
    const before = [nowCell(s.run, s.now).sentence, chip(s, 'builder').text];
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2031-01-01T00:00:00Z'));
    expect([nowCell(s.run, s.now).sentence, chip(s, 'builder').text]).toEqual(before);
    // D59: "5 s ago" never breaks apart.
    expect(before).toEqual(['2 of 3 members working. Last activity 5\u00a0s\u00a0ago.', 'Working \u00b7 40 s']);
  });

  it('without a clock no age shows at all', () => {
    const s = story('working');
    expect(nowCell(s.run, null).sentence).toBe('3 of 3 members working.');
    expect(memberChip(member(s.run, 'lead'), 'working', null).text).toBe('Working');
  });

  it('an ended run keeps the elapsed_s Temper froze at its end (interrupted: Temper #80)', () => {
    const s = story('interrupted');
    expect(s.run.elapsedS).toBe(70);
    expect((msOf(s.run.asOf) ?? 0) - (msOf(s.run.startedAt) ?? 0)).toBeGreaterThan(5 * 60_000);
  });
});

describe('events_total is the count; events_cursor only a position (D14)', () => {
  it('closing: 18 events though the cursor is at 19', () => {
    const s = story('closing');
    expect(s.run.eventsTotal).toBe(18);
    expect(s.run.eventsCursor).toBe(19);
    expect(s.events).toHaveLength(18);
  });

  it('no events_total, no count: never the cursor or a page length', () => {
    const r = story('closing', (raw) => {
      delete raw.events_total;
    }).run;
    expect(r.eventsTotal).toBeNull();
    expect(r.eventsCursor).toBe(19);
  });
});

describe('Now: phase -> word, sentence and band edge', () => {
  const NOW: Array<[Name, string, string | null, string, string]> = [
    // D63: Temper's own count first, then the leader's goal by its `on`.
    ['starting', 'Starting', 'No one is working yet. The leader has the goal.', 'blue', 'play'],
    // D69: the age stays on one line.
    ['start', 'Working', 'The leader is working; 2 members wait for its first message. Last activity 0\u00a0s\u00a0ago.', 'blue', 'play'],
    // SPEC Now table: "N of M members working."; "Check-in at $X" uses spend.cost_usd.
    ['working', 'Working', '3 of 3 members working. Last activity 0\u00a0s\u00a0ago.', 'blue', 'play'],
    ['idle', 'Working', '0 of 3 members working. Last activity 0\u00a0s\u00a0ago.', 'blue', 'play'],
    // D95: a check-in that is not asking yet says why in its word while turns finish.
    ['check_in_running', 'Check-in at $100.40: finishing turns', 'No new work starts. 1 member is finishing its turn.', 'blue', 'pause'],
    // D112: asked, and Temper counts no member working and no turn running.
    ['check_in', 'Check-in at $105.00', 'No one is working until you answer.', 'yellow', 'pause'],
    ['closing', 'Finishing up', 'The leader said done.', 'blue', 'flag'],
    ['done', 'Done', null, 'green', 'check'],
    ['stalled', 'Everyone is idle', 'No one is working until you answer.', 'yellow', 'moon'],
    ['failed', 'Waiting for you', 'No one is working until you answer.', 'yellow', 'hand'],
    ['settings', 'Settings changed', 'No one is working until you answer.', 'yellow', 'settings'],
    ['draining', 'Temper is restarting', 'The team carries on after it.', 'grey', 'restart'],
    ['stopped', 'Stopped', 'The owner stopped the team.', 'grey', 'stop'],
    ['run_failed', 'Failed', "builder's turn 1 failed after its automatic retry, and you stopped the team.", 'red', 'alert'],
    // SPEC Now table: one fixed sentence, whatever Temper's phase.reason says.
    ['interrupted', 'Interrupted', 'The run ended without the team ending.', 'red', 'alert'],
  ];

  it.each(NOW)('%s: %s', (name, word, sentence, edge, icon) => {
    const s = story(name);
    expect(nowCell(s.run, s.now)).toMatchObject({ word, sentence, edge, icon });
  });

  // D112: "No one is working until you answer." only when the owner is asked, Temper counts no member working and no
  // turn is still running; otherwise each phase keeps its own sentence (SPEC 155-160), and an unknown count says nothing.
  it('says no one is working only while the owner is asked and Temper counts no one working (D112)', () => {
    const busy = story('check_in', (raw) => {
      (raw.phase as Raw).running = 1;
    });
    expect(nowCell(busy.run, busy.now).sentence).toBe('No new work starts until you answer.');
    const working = story('failed', (raw) => {
      Object.assign(raw.counts as Raw, { working: 1 });
    });
    expect(nowCell(working.run, working.now).sentence).toBe('Nothing runs until you answer.');
    const settings = story('settings', (raw) => {
      Object.assign(raw.counts as Raw, { working: 2 });
    });
    expect(nowCell(settings.run, settings.now).sentence).toBe('A setting changed while the team waited.');
    const quiet = story('stalled', (raw) => {
      delete (raw.counts as Raw).working;
    });
    expect(nowCell(quiet.run, quiet.now).sentence).toBe('Nothing is waiting for the team. Last activity 0\u00a0s\u00a0ago.');
    // A phase that asks nothing never says it; with no turn finishing, the check-in word has no ": finishing turns" (D95).
    const notAsked = story('check_in_running', (raw) => {
      Object.assign(raw.counts as Raw, { working: 0 });
      (raw.phase as Raw).running = 0;
    });
    const cell = nowCell(notAsked.run, notAsked.now);
    expect(cell.word).toBe('Check-in at $100.40');
    expect(cell.sentence).not.toBe('No one is working until you answer.');
  });

  it('the count line names who is not working', () => {
    const line = (name: Name) => {
      const s = story(name);
      return nowCell(s.run, s.now).countLine;
    };
    expect(line('working')).toBeNull();
    expect(line('idle')).toBe('3 idle');
    expect(line('burst')).toBe('1 idle');
    expect(line('done_refused')).toBe('1 ready \u00b7 2 idle');
  });

  it("a 5-hour limit: Temper's words, the pending allowance check, then the finishing turns (D31)", () => {
    const s = story('limit');
    const check = clockOf(s.run.phase.resumesAt);
    expect(check).not.toBeNull();
    // Before any check: no reading, nothing known to be blocked, nothing verified.
    expect(s.run.phase).toMatchObject({ resetsKnown: true, resumeVerified: false, usage: null, usageCheckedAt: null, blockedWindows: [] });
    expect(nowCell(s.run, s.now)).toMatchObject({
      word: 'Usage limit',
      sentence: `The account hit its usage limit; it carries on only after fresh usage shows room. Next allowance check at ${check}. 2 turns finishing.`,
      edge: 'grey',
      icon: 'clock',
    });
    // No usable reset time: the same check first, then the missing reset (Design's limit row).
    const unknown = story('limit', (raw) => {
      (raw.phase as Raw).resets_known = false;
      (raw.phase as Raw).words = null;
    });
    expect(nowCell(unknown.run, unknown.now).sentence).toBe(
      `The account hit its usage limit. Next allowance check at ${check}. No usable reset time. 2 turns finishing.`,
    );
    // A verified weekly reading while turns still finish: no check is pending, nothing is asked yet.
    const verified = story('limit', (raw) => {
      Object.assign(raw.phase as Raw, {
        words: 'The account hit its weekly limit; the team waits, then asks you before restarting',
        resume_verified: true,
        resets_known: false,
      });
    });
    expect(nowCell(verified.run, verified.now).sentence).toBe(
      'The account hit its weekly limit; the team waits, then asks you before restarting. 2 turns finishing.',
    );
    expect(youCell(verified.run)).toMatchObject({ tone: 'calm', title: 'Nothing needs you', action: null });
  });

  it('a weekly limit asks restart or stop only once Temper verified room and lists its wait (D31)', () => {
    const s = story('limit_asked');
    expect(s.run.phase).toMatchObject({ asked: true, resumeVerified: true, resetsKnown: false, blockedWindows: [] });
    expect(s.run.phase.usage).toMatchObject({ status: 'ok' });
    // D89: its own yellow word, like an asked check-in; D112: no one works, so the sentence says so.
    expect(nowCell(s.run, s.now)).toMatchObject({
      word: 'Usage limit: waiting for you',
      sentence: 'No one is working until you answer.',
      edge: 'yellow',
      icon: 'pause',
    });
    const wait = (s.raw.open_waits as Raw[])[0];
    expect(wait.answers).toEqual([
      expect.objectContaining({ answer: 'restart' }),
      expect.objectContaining({ answer: 'stop' }),
    ]);
    // D94: Temper's own words, not quoted.
    expect(youCell(s.run)).toMatchObject({
      tone: 'needs',
      title: `Needs you: ${String(wait.words)}`,
      action: 'answers',
      waitId: firstWait('limit_asked'),
    });
  });

  it('still spent after the reset, or a reading that failed: it keeps waiting and asks nothing (D31)', () => {
    for (const [name, words] of [
      ['limit_spent', 'The account hit its weekly limit; the team waits, then asks you before restarting'],
      ['limit_unavailable', 'Usage cannot be checked; the team keeps waiting'],
    ] as const) {
      const s = story(name);
      expect(s.run.phase, name).toMatchObject({ asked: false, resumeVerified: false, resetsKnown: false });
      expect(s.run.you.count, name).toBe(0);
      expect(nowCell(s.run, s.now).sentence, name).toBe(`${words}. Next allowance check at ${clockOf(s.run.phase.resumesAt)}. No usable reset time.`);
      expect(youCell(s.run), name).toMatchObject({
        tone: 'calm',
        title: 'Nothing needs you',
        line: 'Stop stays at the top if you want to end it.',
        action: null,
      });
      expect(screenWords(s).join(' '), name).not.toMatch(/available again|restart or stop/i);
    }
    expect(story('limit_spent').run.phase.blockedWindows).toEqual(['7d']);
    expect(story('limit_unavailable').run.phase).toMatchObject({ reason: 'helper_unreachable', usage: { status: 'unavailable', reason: 'helper_unreachable' } });
  });

  it('a passed reset or check time, or a reading alone, never makes a question or a restart (D31)', () => {
    // Temper's clock an hour past the check, no new reading: the page says only what Temper said.
    const late = story('limit', (raw) => {
      raw.as_of = new Date(Date.parse((raw.phase as Raw).resumes_at as string) + 3_600_000).toISOString();
    });
    expect(late.now).toBeGreaterThan(msOf(late.run.phase.resumesAt) ?? Infinity);
    expect(nowCell(late.run, late.now).sentence).toMatch(/^The account hit its usage limit; it carries on only after fresh usage shows room\. Next allowance check at /);
    expect(youCell(late.run)).toMatchObject({ tone: 'calm', action: null });
    // Verified room in the reading, but Temper lists no wait yet: still nothing to answer.
    const verified = story('limit_spent', (raw) => {
      Object.assign(raw.phase as Raw, { resume_verified: true, blocked_windows: [], words: null });
    });
    expect(youCell(verified.run)).toMatchObject({ tone: 'calm', title: 'Nothing needs you', action: null });
    expect(nowCell(verified.run, verified.now).sentence).toBe('The account hit its usage limit.');
  });

  it("reads an allowance reading it doesn't know without guessing (api-fields section 3)", () => {
    const odd = toGlanceRun({ kind: 'flow', phase: { name: 'limit', usage: { status: 'partial' }, blocked_windows: '7d' } });
    expect(odd.phase).toMatchObject({ usage: { status: 'unknown' }, usageCheckedAt: null, blockedWindows: [], resumeVerified: null, resetsKnown: null });
    const none = toGlanceRun({ kind: 'flow', phase: { name: 'limit' } });
    expect(none.phase.usage).toBeNull();
    expect(nowCell(none, null)).toMatchObject({ word: 'Usage limit', sentence: 'The account hit its usage limit.' });
    expect(youCell(none)).toMatchObject({ tone: 'calm', action: null });
  });
});

describe('member state + team phase -> chip, ring and line', () => {
  it('start: the others wait for the leader, with no line of their own', () => {
    const s = story('start');
    // D77: a clock (a dashed circle on an empty ring read as loading).
    expect(chip(s, 'builder')).toMatchObject({ text: 'Waiting for the leader', icon: 'clock', ring: 'dotted-grey' });
    expect(memberLine(member(s.run, 'builder'))).toBeNull();
    expect(turnsLine(member(s.run, 'builder'))).toBe('0 turns \u00b7 $0.00');
    expect(memberLine(member(s.run, 'lead'))).toEqual({ label: 'On:', text: s.run.goal, quoted: true });
    expect(teamCountWords(s.run)).toBe('1 working \u00b7 2 waiting for the leader');
    expect(teamCountWords(story('starting').run)).toBe('1 ready \u00b7 2 waiting for the leader');
  });

  it('working: busy ring, the leader shows what it sent, the others the work they are on', () => {
    const s = story('working');
    for (const name of ['lead', 'builder', 'checker']) {
      expect(chip(s, name)).toEqual({ text: 'Working \u00b7 0 s', icon: 'play', ring: 'solid-blue', tone: 'blue', busy: true });
      expect(toolsLine(member(s.run, name))).toBe('Edit \u00d74 \u00b7 Bash \u00d72');
    }
    expect(memberLine(member(s.run, 'lead'))).toEqual({ label: 'Sent checker:', text: 'Build the checker part and share it.', quoted: true });
    expect(memberLine(member(s.run, 'builder'))).toEqual({ label: 'On:', text: 'Build the builder part and share it.', quoted: true });
    expect(teamCountWords(s.run)).toBe('3 working');
  });

  it("idle: Temper's idle note, no tool count, turns and cost", () => {
    const s = story('idle');
    expect(chip(s, 'lead')).toMatchObject({ text: 'Idle \u00b7 0 s', icon: 'moon', ring: 'dotted-grey' });
    expect(memberLine(member(s.run, 'lead'))).toEqual({ label: 'Idle:', text: 'lead: waiting for the next part', quoted: true });
    expect(s.run.members.map((m) => toolsLine(m))).toEqual([null, null, null]);
    expect(turnsLine(member(s.run, 'lead'))).toBe('1 turn \u00b7 $5.00');
  });

  it('a ready leader waits for a free turn; its messages go on the On line (D95)', () => {
    const s = story('done_refused');
    expect(chip(s, 'lead')).toMatchObject({ text: 'Ready \u00b7 waiting for a free turn', icon: 'ready', ring: 'solid-grey' });
    expect(memberLine(member(s.run, 'lead'), s.run.phase)).toMatchObject({ messages: '1\u00a0message' });
  });

  it("a held member shows its own wait's words (D13)", () => {
    const s = story('failed');
    const builder = member(s.run, 'builder');
    const words = "builder's turn 1 failed: builder turn failed after its automatic retry.";
    expect(chip(s, 'builder')).toMatchObject({ text: 'Needs you', icon: 'alert', ring: 'dashed-yellow' });
    expect(memberLine(builder)).toEqual({ label: null, text: words, quoted: false });
    expect(builder.lastError).toBe('builder turn failed after its automatic retry');
    expect(teamCountWords(s.run)).toBe('2 idle \u00b7 1 needs you');
    const waiting = story('waiting');
    // Temper's words as sent: its first sentence ends only at ". ", so a question mark keeps the next sentence.
    expect(memberLine(member(waiting.run, 'lead'))?.text).toBe(
      'Should the README cover Windows setup too, or only macOS and Linux? The project has no Windows notes yet.',
    );
    expect(memberLine(member(waiting.run, 'checker'))?.text).toBe(
      'Is it fine to run the install commands on this machine to check them? They download about 200 MB.',
    );
  });

  it("D13 fallbacks: the first question's words, then its question's first sentence, then the generic line", () => {
    const wait = (raw: Raw) => (raw.open_waits as Raw[])[0];
    const noWords = story('failed', (raw) => {
      delete wait(raw).words;
    });
    expect(member(noWords.run, 'builder').waitWords).toBe("builder's turn 1 failed: builder turn failed after its automatic retry.");
    const questionOnly = story('waiting', (raw) => {
      for (const w of raw.open_waits as Raw[]) delete w.words;
    });
    expect(member(questionOnly.run, 'checker').waitWords).toBe('Is it fine to run the install commands on this machine to check them?');
    const none = story('failed', (raw) => {
      raw.open_waits = [];
      raw.you = { count: 0, first: null };
    });
    expect(memberLine(member(none.run, 'builder'))).toEqual({ label: null, text: 'Its question is waiting for you.', quoted: false });
  });

  it('a failed turn waits for its retry; a running retry says so (D18)', () => {
    const s = story('working', (raw) => {
      rawMember(raw, 'builder').state = 'failed';
      Object.assign(raw.counts as Raw, { working: 2, failed: 1 });
      (rawMember(raw, 'checker').last_turn as Raw).retry_of = 1;
    });
    expect(chip(s, 'builder')).toMatchObject({ text: 'Turn failed \u00b7 retry pending', icon: 'retry', ring: 'dashed-red', busy: false });
    expect(chip(s, 'checker')).toMatchObject({ text: 'Working on a retry \u00b7 0 s', icon: 'retry', busy: true });
    expect(countLine(s.run.counts)).toBe('1 awaiting retry');
    expect(teamCountWords(s.run)).toBe('2 working \u00b7 1 awaiting retry');
  });

  it('turns that finish before the check-in say so', () => {
    const s = story('check_in_running');
    expect(chip(s, 'checker').text).toBe('Finishing its turn \u00b7 0 s');
    expect(toolsLine(member(s.run, 'checker'))).toBe('Bash \u00d73');
    expect(turnsLine(member(s.run, 'checker'))).toBe('1 turn \u00b7 $45.40');
    // SPEC 5: counted in the card's own words.
    expect(teamCountWords(s.run)).toBe('1 finishing \u00b7 2 idle');
    expect(chip(story('limit'), 'builder').text).toBe('Finishing its turn \u00b7 30 s');
  });

  it('draining: a ready member is paused, and the team count says so (D1, D12)', () => {
    const s = story('draining');
    // D88: a pause that waits on Temper is grey, not the owner's yellow.
    expect(chip(s, 'lead')).toMatchObject({ text: 'Paused: Temper is restarting', icon: 'pause', ring: 'dashed-grey', tone: 'grey' });
    expect(chip(s, 'builder').text).toBe('Finishing its turn \u00b7 15 s');
    expect(teamCountWords(s.run)).toBe('2 finishing \u00b7 1 paused');
  });

  it('closing: only the leader may take a turn (D1, D12)', () => {
    const s = story('closing', (raw) => {
      rawMember(raw, 'lead').state = 'ready';
      rawMember(raw, 'builder').state = 'ready';
      Object.assign(raw.counts as Raw, { ready: 2, idle: 1 });
    });
    expect(chip(s, 'builder')).toMatchObject({ text: 'Paused: the team is finishing up', ring: 'dashed-grey', tone: 'grey' });
    expect(chip(s, 'lead').text).toMatch(/^Ready \u00b7 waiting for a free turn/);
    expect(teamCountWords(s.run)).toBe('1 ready \u00b7 1 paused \u00b7 1 idle');
  });

  // D88: the pause is yellow only while its question is open to the owner; before that, grey.
  it('a check-in pauses a ready member: yellow once it asks you, grey before (D88)', () => {
    const asked = story('check_in', (raw) => {
      rawMember(raw, 'builder').state = 'ready';
    });
    expect(chip(asked, 'builder')).toMatchObject({ text: 'Paused: check-in', ring: 'dashed-yellow', tone: 'yellow' });
    const finishing = story('check_in_running', (raw) => {
      rawMember(raw, 'lead').state = 'ready';
    });
    expect(chip(finishing, 'lead')).toMatchObject({ text: 'Paused: check-in', ring: 'dashed-grey', tone: 'grey' });
    // A paused card shows no waiting messages (SPEC 244).
    expect(memberLine(member(finishing.run, 'lead'), finishing.run.phase)?.messages).toBeUndefined();
  });

  it('ended: every card ends, and says what it was last on (SPEC 252)', () => {
    for (const name of ['done', 'stopped', 'interrupted'] as const) {
      const s = story(name);
      for (const m of s.run.members) expect(chip(s, m.name), name).toMatchObject({ text: 'Ended', icon: 'stop', ring: 'thin-grey' });
      // SPEC 5: "an ended run reads '5 members \u00b7 all ended'".
      expect(teamCountWords(s.run), name).toBe('3 members \u00b7 all ended');
      // SPEC 252: "Last:", the leader too (what it sent last), and never a message count.
      const lead = memberLine(member(s.run, 'lead'), s.run.phase);
      expect(lead, name).toMatchObject({ label: 'Last:', quoted: true });
      expect(lead?.messages, name).toBeUndefined();
    }
    // Temper's contract (10-10 12:17): an interrupted run can leave a member ready with messages waiting; its card
    // still reads Ended with "Last:" and no count (D95's count is for a live ready member only, SPEC 244).
    const cut = story('interrupted', (raw) => {
      Object.assign(rawMember(raw, 'builder'), { state: 'ready', ready_messages: 2 });
    });
    expect(chip(cut, 'builder')).toMatchObject({ text: 'Ended', ring: 'thin-grey' });
    const line = memberLine(member(cut.run, 'builder'), cut.run.phase);
    expect(line).toMatchObject({ label: 'Last:' });
    expect(line?.messages).toBeUndefined();
  });

  it('a merge conflict is counted in files', () => {
    const s = story('working', (raw) => {
      rawMember(raw, 'builder').conflicts = ['README.md', 'docs/install.md'];
    });
    expect(conflictLine(member(s.run, 'builder'))).toBe('2 files in conflict');
    expect(conflictLine(member(s.run, 'checker'))).toBeNull();
  });
});

describe('lines between members', () => {
  it('one line per pair, from the links count of the last hour', () => {
    expect(mapLines(story('working').run).map((l) => [l.a, l.b, l.count])).toEqual([
      ['builder', 'lead', 1],
      ['checker', 'lead', 1],
    ]);
    expect(mapLines(story('burst').run).map((l) => [l.a, l.b, l.count])).toEqual([
      ['builder', 'lead', 5],
      ['checker', 'lead', 4],
    ]);
    // D44: the hour list names each pair once, with the count on its line and the time of its last message.
    const burst = story('burst');
    expect(hourRows(mapLines(burst.run), msOf(burst.run.asOf)).map((r) => r.pair)).toEqual([
      'builder and lead: 5\u00a0messages',
      'checker and lead: 4\u00a0messages',
    ]);
  });

  it("links hold members only; the owner's and Temper's messages are in the feed", () => {
    for (const name of REAL) {
      const s = story(name);
      const names = new Set(s.run.members.map((m) => m.name));
      for (const l of s.run.links) expect(names.has(l.from) && names.has(l.to), `${name}: ${l.from}->${l.to}`).toBe(true);
    }
  });

  it('joins both directions of a pair and adds their counts', () => {
    const lines = mapLines({
      members: story('working').run.members,
      links: [
        { from: 'lead', to: 'builder', count: 3, lastAt: '2026-10-09T10:12:00Z' },
        { from: 'builder', to: 'lead', count: 2, lastAt: '2026-10-09T10:13:00Z' },
        { from: 'builder', to: 'ghost', count: 9, lastAt: null },
        { from: 'checker', to: 'checker', count: 1, lastAt: null },
        { from: 'checker', to: 'lead', count: 0, lastAt: null },
      ],
    });
    expect(lines).toEqual([{ a: 'builder', b: 'lead', count: 5, lastAt: '2026-10-09T10:13:00Z' }]);
  });

  it("has no line before the leader's first message", () => {
    expect(mapLines(story('start').run)).toEqual([]);
  });

  // The router, the counts' spots and the hub's port (D52, D57, D58, D5) are tested in teamGlanceMap.test.ts.
});

describe('layout order', () => {
  it('map: the leader in the centre column, the others around it in member order', () => {
    expect(mapSlots(story('working').run.members)).toEqual({
      rows: 1,
      slots: [
        { name: 'lead', col: 2, row: 1 },
        { name: 'builder', col: 1, row: 1 },
        { name: 'checker', col: 3, row: 1 },
      ],
    });
    const five = story('working', (raw) => {
      const extra = ['writer', 'styler'].map((name) => ({ ...rawMember(raw, 'checker'), name, leader: false }));
      raw.members = [...rawMembers(raw), ...extra];
    });
    expect(mapSlots(five.run.members).slots.slice(1).map((s) => [s.name, s.col, s.row])).toEqual([
      ['builder', 1, 1],
      ['checker', 3, 1],
      ['writer', 3, 2],
      ['styler', 1, 2],
    ]);
  });

  it('phone list: working first, then needs you, the leader first in its group', () => {
    expect(listOrder(story('failed').run.members).map((m) => m.name)).toEqual(['builder', 'lead', 'checker']);
    expect(listOrder(story('waiting').run.members).map((m) => m.name)).toEqual(['lead', 'checker', 'builder']);
  });
});

describe('Latest: big moments only, newest first, at most 5', () => {
  it('ends on the done moment and leaves idle and wake rows out', () => {
    const rows = momentText(story('done'));
    expect(rows.length).toBeLessThanOrEqual(5);
    expect(rows.slice(0, 2)).toEqual(['Done: v1 is the result', 'builder shared v1: \u201cBuilder\'s part is shared\u201d']);
    expect(rows.join(' ')).not.toMatch(/\bidle\b|woke/i);
  });

  it('folds a same-second fan-out into one row', () => {
    expect(momentText(story('idle'))).toEqual(['lead sent work to 2 members', 'You started the project; lead has the goal']);
  });

  it('a check-in, a refused done, a question and a stall each get their row', () => {
    expect(momentText(story('check_in'))).toEqual([
      'Spend reached $100.00: check-in. No new work starts.',
      'builder shared v1: \u201cBuilder\'s part is shared\u201d',
      'lead sent work to 2 members',
      'You started the project; lead has the goal',
    ]);
    expect(momentText(story('closing'))[0]).toMatch(/^lead said done: \u201c.+\u201d$/);
    expect(momentText(story('done_refused'))[0]).toBe('Done refused: A new message reached the leader');
    expect(momentText(story('failed'))[0]).toMatch(/^builder asked you: \u201cbuilder's turn 1 failed/);
    expect(momentText(story('stalled'))[0]).toBe(
      'Temper asked you: \u201cThe team is stalled: nothing is running, nothing is waiting to be delivered and lead has not said done.\u201d',
    );
  });

  it('a usage limit schedules an allowance check, never an automatic resume (D31)', () => {
    const s = story('limit');
    expect(momentText(s)[0]).toBe(`Usage limit: next allowance check at ${clockOf(s.run.phase.resumesAt)}`);
    // After Temper's check the feed's limit carries its current schedule: no usable reset time.
    for (const name of ['limit_asked', 'limit_spent', 'limit_unavailable'] as const) {
      const t = story(name);
      const limit = t.events.find((e) => e.kind === 'limit');
      expect(momentText(t)[0], name).toBe(
        `Usage limit: next allowance check at ${clockOf(limit?.kind === 'limit' ? limit.resumesAt : null)}; no usable reset time`,
      );
    }
  });

  it("Temper's hidden allowance check is never an event; the count stays events_total (D14)", () => {
    expect(toGlanceEvent({ seq: 17, at: '2026-10-09T13:00:00Z', kind: 'limit_checked', member: 'checker', status: 'held' })).toBeNull();
    for (const name of ['limit_asked', 'limit_spent', 'limit_unavailable'] as const) {
      const s = story(name);
      expect(s.run.eventsTotal, name).toBe(16);
      expect(s.run.eventsCursor, name).toBe(17);
      expect(s.events, name).toHaveLength(16);
      expect(s.events.some((e) => (e.kind as string) === 'limit_checked'), name).toBe(false);
    }
  });

  it("the owner's answers and the end", () => {
    expect(momentText(story('resumed'))[0]).toBe('You answered: guide');
    // D41: the label once, then the reason.
    expect(momentText(story('stopped')).slice(0, 2)).toEqual(['Stopped: The owner stopped the team.', 'You answered: stop']);
    expect(momentText(story('run_failed'))[0]).toMatch(/^Failed: builder's turn 1 failed/);
  });
});

describe('message dots and Just sent', () => {
  const msg = (seq: number, at: string, id: string | null = `m${seq}`, to = 'builder'): GlanceMessageEvent => ({
    kind: 'message',
    seq,
    at,
    member: 'lead',
    from: 'lead',
    fromKind: 'member',
    to,
    messageKind: 'work_request',
    text: `message ${seq}`,
    messageId: id,
  });

  it('a burst in one second staggers 120 ms; past 6 at once the rest only bump the count (D10)', () => {
    const burst = Array.from({ length: 8 }, (_, i) => msg(i + 1, `2026-10-09T10:13:23.${i}00+00:00`));
    const plan = dotPlan(burst);
    expect(plan.dots).toHaveLength(DOT_MAX_AT_ONCE);
    expect(plan.dots.map((d) => d.delay)).toEqual([0, 1, 2, 3, 4, 5].map((i) => i * DOT_STAGGER_MS));
    expect(plan.extra).toBe(2);
    expect(extraWords(plan.extra)).toBe('+2 more sent');
  });

  it('separate seconds fly one after another', () => {
    const plan = dotPlan([msg(2, '2026-10-09T10:13:24.000+00:00'), msg(1, '2026-10-09T10:13:23.000+00:00')]);
    expect(plan.dots.map((d) => [d.event.seq, d.delay])).toEqual([
      [1, 0],
      [2, DOT_MS],
    ]);
  });

  it('each message id flies once (D6)', () => {
    const plan = dotPlan([msg(1, '2026-10-09T10:13:23.000+00:00', 'same'), msg(2, '2026-10-09T10:13:23.100+00:00', 'same')]);
    expect(plan.dots).toHaveLength(1);
    for (const name of ALL) {
      const ids = messagesOf(story(name).events).map((e) => e.messageId);
      expect(ids.every((id) => id !== null), name).toBe(true);
      expect(new Set(ids).size, name).toBe(ids.length);
    }
  });

  it("a message flies only if it is at most 12 s old by Temper's clock, never the device's (D4)", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2031-01-01T00:00:00Z'));
    // The owner's Guide, read 4 s after it was sent: flies, though the team was quiet for a minute.
    const resumed = story('resumed');
    const readAt = resumed.feedRaw.as_of as string;
    const guide = messagesOf(resumed.events).find((e) => e.fromKind === 'owner')!;
    expect(freshByClock(guide, readAt)).toBe(true);
    // The same message read 64 s later (a hidden tab): history, it stays still.
    expect(freshByClock(guide, new Date(Date.parse(guide.at!) + 64_000).toISOString())).toBe(false);
    expect(GLANCE_FRESH_MS).toBe(12_000);
    // A future release cannot be fresh (D22/D26), even if both timestamps parse.
    expect(freshByClock({ at: new Date(Date.parse(readAt) + 1).toISOString() }, readAt)).toBe(false);
    // No time on either side: its age isn't known, so it flies.
    expect(freshByClock(guide, null)).toBe(true);
    expect(freshByClock({ at: null }, readAt)).toBe(true);
    vi.useRealTimers();
  });

  it("the burst fixture: 9 dots and one '+1 more sent'", () => {
    const plan = dotPlan(messagesOf(story('burst').events));
    expect([plan.dots.length, plan.extra]).toEqual([9, 1]);
  });

  it('Just sent repeats the newest message in words, owner and Temper by name', () => {
    const working = story('working');
    expect(justSent(working.events, working.run)).toMatchObject({ from: 'lead', to: 'checker', text: 'Build the checker part and share it.' });
    const refused = story('done_refused');
    expect(justSent(refused.events, refused.run)).toMatchObject({ from: 'You', to: 'lead', text: 'Done was refused: a new message reached you.' });
    const start = story('start');
    expect(justSent(start.events, start.run)).toMatchObject({ from: 'Temper', to: 'lead', text: start.run.goal });
    const burst = story('burst');
    expect(justSent(burst.events, burst.run)).toMatchObject({ from: 'lead', to: 'builder', text: "Use the project's name as the title." });
  });

  it('a same-second burst is counted for "N messages in the same second, last: \u2026" (D74), each message id once', () => {
    // The real start: Temper's goal and the leader's two work messages share one second.
    const working = story('working');
    expect(justSent(working.events, working.run)?.burst).toBe(3);
    const burst = story('burst');
    expect(justSent(burst.events, burst.run)?.burst).toBe(7);
    // A message seen twice in the feed counts once.
    const newest = messagesOf(burst.events).at(-1)!;
    expect(justSent([...burst.events, { ...newest, seq: newest.seq + 100 }], burst.run)?.burst).toBe(7);
    // A lone message, and the fallbacks without a feed, are 1: no burst words.
    expect(justSent(story('draining').events, story('draining').run)?.burst).toBe(1);
    expect(justSent([], working.run)?.burst).toBe(1);
  });

  it("with no message loaded: the newest last_sent, else the newest link without text (D3)", () => {
    const s = story('working');
    expect(justSent([], s.run)).toMatchObject({ from: 'lead', to: 'checker', text: 'Build the checker part and share it.' });
    const noSent = { ...s.run, members: s.run.members.map((m) => ({ ...m, lastSent: null })) };
    const toChecker = (s.raw.links as Raw[]).find((l) => l.to === 'checker')!;
    expect(justSent([], noSent)).toEqual({ from: 'lead', to: 'checker', text: null, at: toChecker.last_at, burst: 1 });
    expect(justSent([], { members: noSent.members, links: [] })).toBeNull();
  });

  it('a receiver with no card on this run is named, never placed: "(not on this team)" (D33)', () => {
    const s = story('working');
    const [lead] = messagesOf(s.events).filter((m) => m.from === 'lead');
    const toMarketing = { ...lead, seq: lead.seq + 100, to: 'Marketing' };
    expect(justSent([...s.events, toMarketing], s.run)).toMatchObject({ from: 'lead', to: 'Marketing (not on this team)' });
    // A member, You and Temper keep their names; without the run's members a name is kept as supplied.
    expect(receiverName('checker', s.run)).toBe('checker');
    expect(receiverName('owner', s.run)).toBe('You');
    expect(receiverName('temper', s.run)).toBe('Temper');
    expect(receiverName('Marketing')).toBe('Marketing');
    // An unnamed receiver (a last_sent without `to`) is someone not on this team.
    expect(receiverName(null, s.run)).toBe('someone not on this team');
    const unnamed = s.run.members.map((m) => (m.lastSent ? { ...m, lastSent: { ...m.lastSent, to: null as unknown as string } } : m));
    expect(justSent([], { members: unnamed, links: [] })).toMatchObject({ to: 'someone not on this team' });
    // The links fallback names an absent receiver the same way.
    const links = [{ from: 'lead', to: 'Marketing', count: 1, lastAt: s.run.links[0].lastAt }];
    const noSent = s.run.members.map((m) => ({ ...m, lastSent: null }));
    expect(justSent([], { members: noSent, links })).toMatchObject({ to: 'Marketing (not on this team)', text: null });
  });

  it('the newer of two sends in one millisecond is told apart by its microseconds', () => {
    // Keep the real pairs, but pin the two timestamps inside one millisecond.
    // A new serializer export can put its 0.5 ms interval across a millisecond boundary.
    const run = story('working').run;
    const second = run.links.find((l) => l.to === 'builder')!.lastAt!.slice(0, 19);
    const links = run.links.filter((l) => l.to === 'builder' || l.to === 'checker').map((l) => ({
      ...l, lastAt: `${second}.123${l.to === 'builder' ? '100' : '600'}Z`,
    }));
    expect(Date.parse(links[0].lastAt)).toBe(Date.parse(links[1].lastAt));
    const members = run.members.map((m) => ({ ...m, lastSent: null }));
    expect(justSent([], { members, links })).toMatchObject({ to: 'checker' });
    expect(justSent([], { members, links: [...links].reverse() })).toMatchObject({ to: 'checker' });
  });

  it("'Just sent' only while the run goes on and the message is at most 60 s old; else 'Last message' (D22)", () => {
    const working = story('working');
    const sent = justSent(working.events, working.run)!;
    const at = msOf(sent.at)!;
    expect(sentLabel(sent, 'working', working.now)).toEqual({ label: 'Just sent', time: '0 s ago' });
    expect(sentLabel(sent, 'working', at + JUST_SENT_MS)).toEqual({ label: 'Just sent', time: '1 min ago' });
    expect(sentLabel(sent, 'working', at + JUST_SENT_MS + 1000)).toEqual({ label: 'Last message', time: '1 min ago' });
    // An ended run: always the last message, however fresh.
    const done = story('done');
    const last = justSent(done.events, done.run)!;
    expect(sentLabel(last, 'done', done.now)).toMatchObject({ label: 'Last message' });
    const interrupted = story('interrupted');
    expect(sentLabel(justSent(interrupted.events, interrupted.run)!, 'interrupted', interrupted.now)).toEqual({
      label: 'Last message',
      time: '5 min ago',
    });
    // No clock to compare with: no age, the time it records.
    expect(sentLabel(sent, 'working', null)).toEqual({ label: 'Last message', time: `recorded at ${clockOf(sent.at)}` });
    // A time after Temper's clock has no age: never "0 s ago".
    expect(sentLabel(sent, 'working', at - 5000)).toEqual({ label: 'Last message', time: `recorded at ${clockOf(sent.at)}` });
    expect(sentLabel({ at: null }, 'working', working.now)).toEqual({ label: 'Last message', time: null });
    // Stale data: nothing is green, so never "Just sent"; the age counts to the device's present (D64, D75).
    expect(sentLabel(sent, 'working', at + 30_000, true)).toEqual({ label: 'Last message', time: '30 s ago' });
  });
});

describe("a time after Temper's clock has no age (D22)", () => {
  it('shows the time it records, never "0 s ago"', () => {
    const s = story('working');
    const now = s.now!;
    const future = new Date(now + 90_000).toISOString();
    const at = clockOf(future)!;
    expect(agoText(future, now)).toBe(`recorded at ${at}`);
    expect(shortAgo(future, now)).toBe(at);
    expect(sinceWords(future, now)).toBe(`since ${at}`);
    const ahead = story('working', (raw) => {
      raw.last_activity_at = future;
      rawMember(raw, 'lead').since = future;
    });
    expect(nowCell(ahead.run, ahead.now).sentence).toBe(`3 of 3 members working. Last activity recorded at ${at}.`);
    expect(chip(ahead, 'lead').text).toBe(`Working \u00b7 since ${at}`);
    // Now itself is still an age.
    const present = new Date(now).toISOString();
    expect([agoText(present, now), shortAgo(present, now), sinceWords(present, now)]).toEqual(['0 s ago', '0 s', '0 s']);
  });
});

describe('You and Spend', () => {
  it('nothing needs you while the team works; the Spend line fits a phone (D2)', () => {
    const s = story('working');
    expect(youCell(s.run)).toMatchObject({ tone: 'calm', title: 'Nothing needs you', line: 'Questions and check-ins show up here.', action: null });
    expect(spendCell(s.run)).toEqual({
      amount: '$0.00',
      of: 'of $100',
      fraction: 0,
      line: 'At $100 the team pauses and asks you.',
      tone: 'ok',
    });
  });

  it('the asked check-in offers its answers; Continue sets the next one from the spend (D11)', () => {
    const s = story('check_in');
    expect(youCell(s.run)).toMatchObject({ tone: 'needs', title: 'Needs you: carry on?', action: 'answers', waitId: firstWait('check_in') });
    expect(spendCell(s.run)).toEqual({
      amount: '$105.00',
      of: 'of $100',
      fraction: 1,
      line: 'If you continue, the next check-in is at $205.',
      tone: 'warn',
    });
  });

  it('while turns finish before the check-in question, only the step is promised (D11)', () => {
    const s = story('check_in_running');
    expect(youCell(s.run)).toMatchObject({ tone: 'calm', title: 'Nothing needs you yet', line: "You'll be asked to carry on once these turns finish." });
    expect(spendCell(s.run)).toMatchObject({ amount: '$100.40', line: 'If you continue, the next check-in comes $100 later.', tone: 'warn' });
  });

  it("each open question gets its own title; more questions are counted", () => {
    // D94: every question Temper writes ends with "?"; quotes only around a person's words.
    expect(youCell(story('stalled').run)).toMatchObject({ title: 'Needs you: nudge the team or stop?', waitId: firstWait('stalled') });
    expect(youCell(story('settings').run)).toMatchObject({ title: 'Needs you: go on or stop?', waitId: firstWait('settings') });
    // A held turn's words are Temper's own: not quoted.
    expect(youCell(story('failed').run)).toMatchObject({
      title: "Needs you: builder's turn 1 failed: builder turn failed after its automatic retry.",
      waitId: firstWait('failed'),
    });
    // A member's own question is a person's words: quoted.
    const asks = youCell(story('waiting').run);
    expect(asks.title).toMatch(/^Needs you: \u201c.+\u201d$/);
    // SPEC You table: "and N more" goes with the title, not on the line.
    expect(youCell(story('waiting').run)).toMatchObject({ tone: 'needs', more: 1, line: null, from: 'From lead' });
    expect(youCell(story('limit').run)).toMatchObject({ tone: 'calm', line: 'Stop stays at the top if you want to end it.' });
  });

  it('after a guided check-in the bar measures to the next one', () => {
    const cell = spendCell(story('resumed').run);
    expect(cell).toMatchObject({ amount: '$105.00', of: 'of $205', line: 'At $205 the team pauses and asks you.', tone: 'ok' });
    expect(cell.fraction).toBeCloseTo(105 / 205, 3);
  });

  it('ended: nothing needs you, and no more check-ins (D16, D19)', () => {
    for (const name of ['stopped', 'run_failed', 'interrupted'] as const) {
      expect(youCell(story(name).run), name).toEqual({
        tone: 'ended',
        title: 'Nothing needs you',
        line: 'Read what it made below, or start a new project.',
        hint: false,
        from: null,
        waitId: null,
        more: 0,
        action: 'next',
      });
    }
    expect(youCell(story('done').run)).toMatchObject({ tone: 'calm', title: 'Nothing needs you', line: null });
    expect(spendCell(story('done').run)).toEqual({
      amount: '$105.00',
      of: null,
      fraction: null,
      // D67: no next check-in, said once.
      line: 'Spent in all. 0 check-ins, none to come \u00b7 1 shared version.',
      tone: 'ok',
    });
    expect(spendCell(story('stopped').run).line).toBe('Spent in all. 1 check-in, none to come \u00b7 1 shared version.');
    expect(spendCell(story('interrupted').run)).toMatchObject({ amount: '$0.00', line: 'Spent in all. 0 check-ins, none to come.' });
  });

  it('a missing spend is not known, never $0.00 (D17)', () => {
    const s = story('working', (raw) => {
      delete raw.spend;
      delete raw.cost_usd;
    });
    expect(spendCell(s.run)).toEqual({ amount: 'Not known', of: null, fraction: null, line: null, tone: 'ok' });
  });
});

describe('left for part 2, checked on the real replies', () => {
  it('the events route answers events, cursor, more and as_of', () => {
    for (const name of REAL) {
      expect(Object.keys(rawOf(name, true)).sort(), name).toEqual(['as_of', 'cursor', 'events', 'more']);
    }
  });

  it('the check-in wait is kind "pause" with continue, guide (words required) and stop', () => {
    const wait = (rawOf('check_in').open_waits as Raw[])[0];
    expect(wait.kind).toBe('pause');
    expect((wait.answers as Raw[]).map((a) => [a.answer, a.needs_text])).toEqual([
      ['continue', 'none'],
      ['guide', 'required'],
      ['stop', 'optional'],
    ]);
  });

  it('tools_now comes with working members only', () => {
    for (const name of REAL) {
      for (const m of rawMembers(rawOf(name))) {
        expect(Array.isArray(m.tools_now), `${name}: ${String(m.name)}`).toBe(m.state === 'working');
      }
    }
  });

  it('flow polling stops for every ended phase, even interrupted without an outcome; rounds stay unchanged', () => {
    const ended = (name: Name) => teamRunPollingEnded(rawOf(name) as unknown as Parameters<typeof teamRunPollingEnded>[0]);
    expect(ended('done')).toBe(true);
    expect(ended('stopped')).toBe(true);
    expect(ended('run_failed')).toBe(true);
    expect(ended('working')).toBe(false);
    expect(ended('check_in')).toBe(false);
    expect(ended('interrupted')).toBe(true);
    expect(teamRunPollingEnded(roundRun.body as unknown as Parameters<typeof teamRunPollingEnded>[0])).toBe(false);
  });
});

describe('durations', () => {
  it('seconds, minutes, then hours and minutes', () => {
    expect(durationWords(12_000)).toBe('12 s');
    expect(durationWords(17 * 60_000)).toBe('17 min');
    expect(durationWords(72 * 60_000)).toBe('1 h 12 min');
  });
});
