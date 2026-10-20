/**
 * The free-flowing Team page at a glance: a typed model of what Temper
 * sends for a free-flowing team (FLOW E5/E6, Temper's field list
 * api-fields.md) and the pure functions that turn it into what the page
 * says. Components read only this model; the API's own field names live in
 * teamGlanceAdapter.ts alone.
 *
 * The words follow Design's glance proposal (GLANCE.md, states tables).
 * Truthfulness rules: a message dot means the message was released, never
 * read or answered; "working" means a member turn is running right now;
 * nothing is guessed (a value Temper doesn't know is null and the page says
 * so or leaves it out); no rounds, no %, no ETA, no work-left claim and no
 * generated summary.
 */

// --- the model ----------------------------------------------------------------------

export type GlancePhaseName =
  | 'starting'
  | 'working'
  | 'closing'
  | 'check_in'
  | 'quiet'
  | 'limit'
  | 'settings'
  | 'waiting_for_owner'
  | 'draining'
  | 'done'
  | 'stopped'
  | 'failed'
  | 'didnt_start'
  | 'interrupted'
  | 'unknown';

export interface GlancePhase {
  name: GlancePhaseName;
  /** Temper's own sentence for the phase (a usage limit's words, D20, and a phase this page doesn't know). */
  words: string | null;
  since: string | null;
  /** Member turns running now. */
  running: number;
  /** The phase's own question is open (check-in, quiet, settings, a weekly limit after reset). */
  asked: boolean;
  /** Why it stopped or failed; for a limit whose usage can't be read, Temper's fixed reason code. */
  reason: string | null;
  /** A limit's next allowance check (never a reset or a promise to resume). */
  resumesAt: string | null;
  /** That check waits for a usable future reset (true) or is a recheck (false). */
  resetsKnown: boolean | null;
  /** A fresh allowance reading succeeded; never inferred from the reset time. */
  resumeVerified: boolean | null;
  /**
   * Temper's latest allowance reading for a limit, carried as sent (null
   * before a reading and outside a limit). The page never turns a reading,
   * a check time or a passed reset into permission or a question: only
   * Temper's words and the waits it lists do that.
   */
  usage: GlanceUsage | null;
  /** When Temper last checked the allowance (null before checking). */
  usageCheckedAt: string | null;
  /** Still-exhausted windows ("5h", "7d", "7d:<model>"); empty before checking. */
  blockedWindows: string[];
}

/** One window of an allowance reading, as Temper read it. */
export interface GlanceUsageWindow {
  key: string;
  usedPercent: number | null;
  resetsAt: string | null;
}

/** Temper's allowance reading: read, could not be read (with its fixed reason), or a status this page doesn't know. */
export type GlanceUsage =
  | { status: 'ok'; observedAt: string | null; windows: GlanceUsageWindow[] }
  | { status: 'unavailable'; reason: string | null }
  | { status: 'unknown' };

export interface GlanceSpend {
  cost: number;
  pauseEvery: number;
  lastCheckIn: number;
  nextCheckIn: number;
  sinceCheckIn: number;
  checkIns: number;
}

export interface GlanceQuestion {
  waitId: string;
  kind: string;
  member: string | null;
  header: string | null;
  words: string;
  openedAt: string | null;
}

export interface GlanceYou {
  count: number;
  first: GlanceQuestion | null;
}

export interface GlanceCounts {
  /** Temper sent its own working count (D63: no count sentence without it). Missing means sent. */
  workingSupplied?: boolean;
  members: number;
  working: number;
  ready: number;
  idle: number;
  held: number;
  failed: number;
  ended: number;
}

export type GlanceMemberState = 'working' | 'ready' | 'idle' | 'held' | 'failed' | 'ended' | 'unknown';
export type GlanceIdleReason = 'start' | 'idle_call' | 'no_tool_call' | null;

export interface GlanceOn {
  kind: 'work_request' | 'share' | 'idle' | 'goal' | 'message' | string;
  text: string;
  from: string | null;
  /** Who it went to: set on the leader's own latest message (kind "message"). */
  to: string | null;
  at: string | null;
  messageId: string | null;
}

export interface GlanceSent {
  to: string;
  kind: string;
  text: string;
  at: string | null;
  messageId: string | null;
}

export interface GlanceToolCount {
  name: string;
  count: number;
}

export interface GlanceMember {
  name: string;
  role: string;
  leader: boolean;
  state: GlanceMemberState;
  since: string | null;
  turnNo: number | null;
  on: GlanceOn | null;
  idleNote: string | null;
  idleReason: GlanceIdleReason;
  /** Tool calls in the running turn; null when Temper didn't send them (the line is left out). */
  toolsNow: GlanceToolCount[] | null;
  readyMessages: number;
  lastSent: GlanceSent | null;
  lastShareNote: string | null;
  conflicts: number;
  /** The open wait that holds it, when held. */
  waitId: string | null;
  /**
   * That wait's own words, when held: the wait's words, else the first
   * question's words when it is the first wait, else the first sentence of
   * its question (at most 160 characters); null when Temper sent none.
   */
  waitWords: string | null;
  /** That wait's kind (`question` for a member's own question); null when Temper sent none. */
  waitKind?: string | null;
  turns: number;
  /** Missing turn evidence is not evidence that no work started (D121). */
  turnsSupplied?: boolean;
  hasTurnHistory?: boolean;
  cost: number | null;
  /** The running or last turn retries this turn number by itself (Temper's one automatic retry). */
  retryOf: number | null;
  /** The last turn's error in a few words, as Temper sent it (shown while the turn has failed). */
  lastError: string | null;
  /** D105: the newest time of its last turn (ended, else started), as Temper recorded it. */
  lastTurnAt?: string | null;
}

export interface GlanceLink {
  from: string;
  to: string;
  count: number;
  lastAt: string | null;
}

export interface GlanceShare {
  versionNo: number;
  commitShort: string | null;
  by: string | null;
  at: string | null;
  note: string | null;
  filesChanged: number | null;
  filesTotal: number | null;
}

/**
 * The words a person gave with a stop (Temper's outcome.owner_words), whole and as sent, and who gave them: the
 * stopping action's caller, else the outcome's (teamStopper, as the rounds outcome card says it). Never empty.
 */
export interface GlanceStopWords {
  words: string;
  by: string | null;
}

export interface GlanceWork {
  latest: GlanceShare | null;
  shares: GlanceShare[];
  total: number;
  /** The leader's own done summary, once it said done (never generated). */
  summary: string | null;
}

export interface GlanceRun {
  executionId: string;
  goal: string;
  leader: string;
  startedAt: string | null;
  startedBy: string | null;
  /** The starter's title from the existing roles list, when supplied. */
  starterTitle?: string | null;
  /** Seconds from the start to the reply (as_of) while live; frozen at the end once ended. */
  elapsedS: number | null;
  lastActivityAt: string | null;
  project: string | null;
  /**
   * When Temper wrote this reply, by its own clock. Every age and duration
   * on the page counts to this, live or ended; never the device's clock.
   */
  asOf: string | null;
  /** How many members may run a turn at once (the number in force). */
  maxParallel: number | null;
  phase: GlancePhase;
  /** The words given with the stop, as Temper recorded them; null when none were given. */
  stopWords: GlanceStopWords | null;
  spend: GlanceSpend | null;
  you: GlanceYou;
  counts: GlanceCounts;
  members: GlanceMember[];
  links: GlanceLink[];
  work: GlanceWork;
  /** A position in the feed (the newest event seq at this reply), never a count. */
  eventsCursor: number;
  /** How many events the full activity list holds; null when Temper didn't say (no count is shown). */
  eventsTotal: number | null;
}

export type GlanceMessageFrom = 'member' | 'owner' | 'temper';

interface EventBase {
  seq: number;
  at: string | null;
  /** Whose event (a message's sender), or null for the team. */
  member: string | null;
}

export type GlanceEvent =
  | (EventBase & {
      kind: 'message';
      from: string;
      fromKind: GlanceMessageFrom;
      to: string;
      messageKind: string;
      text: string;
      /** Every message has its own id; the page counts and animates each id once. */
      messageId: string | null;
    })
  | (EventBase & { kind: 'turn_start'; turnNo: number | null; retryOf: number | null })
  | (EventBase & {
      kind: 'turn_end';
      turnNo: number | null;
      ended: string;
      endedBy: string | null;
      cost: number | null;
      toolCalls: number | null;
    })
  | (EventBase & {
      kind: 'share';
      versionNo: number | null;
      commitShort: string | null;
      note: string | null;
      filesChanged: number | null;
    })
  | (EventBase & { kind: 'share_refused'; why: string | null; reason?: string | null; paths?: string[] })
  | (EventBase & { kind: 'conflict'; paths: number; atStep: string | null })
  | (EventBase & { kind: 'idle'; note: string | null; reason: GlanceIdleReason })
  | (EventBase & { kind: 'wake'; by: string | null })
  | (EventBase & { kind: 'closing'; summary: string | null })
  | (EventBase & { kind: 'done_refused'; reasons: string[] })
  | (EventBase & { kind: 'done'; summary: string | null; versionNo: number | null; commitShort: string | null })
  | (EventBase & { kind: 'wait_opened'; waitId: string | null; waitKind: string; words: string | null })
  | (EventBase & {
      kind: 'wait_answered';
      waitId: string | null;
      waitKind: string;
      answer: string;
      by: string | null;
      /** api-fields:260: false on a settings go on that came too late; absent (null) otherwise. */
      applied: boolean | null;
      /** Temper's reason when `applied` is false, word for word. */
      why: string | null;
    })
  | (EventBase & { kind: 'check_in'; atUsd: number | null })
  | (EventBase & { kind: 'limit'; resumesAt: string | null; resetsKnown: boolean | null })
  | (EventBase & { kind: 'limit_over'; by?: string | null })
  | (EventBase & { kind: 'ended'; decision: string; reason: string | null })
  | (EventBase & { kind: 'other'; raw: string });

export type GlanceMessageEvent = Extract<GlanceEvent, { kind: 'message' }>;

export interface GlanceEventPage {
  events: GlanceEvent[];
  cursor: number;
  more: boolean;
  /** When Temper wrote this page, by its own clock (the page's clock, like the run's as_of). */
  asOf: string | null;
}

// --- small helpers -------------------------------------------------------------------

const ENDED_PHASES: ReadonlySet<GlancePhaseName> = new Set(['done', 'stopped', 'failed', 'didnt_start', 'interrupted']);

export function phaseEnded(name: GlancePhaseName): boolean {
  return ENDED_PHASES.has(name);
}

export function msOf(iso: string | null | undefined): number | null {
  if (!iso) return null;
  // Some of Temper's times have a space where ISO 8601 has the T ("2026-10-09 10:11:48+00:00").
  const t = Date.parse(iso.replace(/^(\d{4}-\d\d-\d\d) /, '$1T'));
  return Number.isNaN(t) ? null : t;
}

/**
 * Microseconds since 1970. Temper writes six digits after the second, and
 * two messages released by one turn's end can share a millisecond; Date.parse
 * keeps only three, so "which is newer" asks this instead.
 */
function usOf(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const parts = /^(.*?[T ]\d\d:\d\d:\d\d)(?:\.(\d+))?(.*)$/.exec(iso);
  if (!parts) {
    const t = msOf(iso);
    return t === null ? null : t * 1000;
  }
  const whole = msOf(`${parts[1]}${parts[3]}`);
  if (whole === null) return null;
  return whole * 1000 + Number((parts[2] ?? '').padEnd(6, '0').slice(0, 6));
}

/** Whether time `a` is after time `b`; a missing time is older than any time. */
function later(a: string | null, b: string | null): boolean {
  return (usOf(a) ?? -Infinity) > (usOf(b) ?? -Infinity);
}

/**
 * The page's clock: the newest of Temper's own reply times (as_of on the run
 * and on the events page). Null when Temper sent none; then no age or
 * duration is shown, never one from the device's clock.
 */
export function glanceClock(...asOf: (string | null | undefined)[]): number | null {
  let now: number | null = null;
  for (const iso of asOf) {
    const t = msOf(iso);
    if (t !== null && (now === null || t > now)) now = t;
  }
  return now;
}

/** "$57.00"; whole dollars "$100" when `whole` and the amount is whole. */
export function money(n: number, whole = false): string {
  if (whole && Math.abs(n - Math.round(n)) < 0.005) return `$${Math.round(n)}`;
  return `$${n.toFixed(2)}`;
}

/** "12 s", "6 min", "1 h 12 min", "2 days 3 h": how long. */
export function durationWords(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  if (h < 24) return m % 60 === 0 ? `${h} h` : `${h} h ${m % 60} min`;
  const d = Math.floor(h / 24);
  return `${d} ${d === 1 ? 'day' : 'days'}${h % 24 ? ` ${h % 24} h` : ''}`;
}

/**
 * Design D22: a time after Temper's clock has no age. It shows the time it
 * records, never "0 s ago" (so a skewed clock can't pass for fresh news).
 */
function isFuture(t: number, now: number): boolean {
  return t > now;
}

/** The short form of a list's time column: "12 s", "4 min", "1 h 12", "2 d"; a future time shows its clock time. */
export function shortAgo(iso: string | null, now: number | null): string {
  const t = msOf(iso);
  if (t === null || now === null) return '';
  if (isFuture(t, now)) return clockDayOf(iso, now) ?? '';
  const s = Math.floor((now - t) / 1000);
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  if (h < 24) return m % 60 === 0 ? `${h} h` : `${h} h ${String(m % 60).padStart(2, '0')}`;
  return `${Math.floor(h / 24)} d`;
}

/**
 * D56: the message box's hint for the chosen member, from its supplied
 * state (SPEC 14 c). `name` is shown in bold before the words; null when
 * the hint speaks of every member. Nothing promises when it is read.
 * `now`: Temper's clock, so a check after today gets its day (D104).
 */
export function composerHint(
  run: Pick<GlanceRun, 'members' | 'phase'>,
  to: string | null,
  now: number | null = null,
): { name: string | null; text: string } {
  const m = to ? run.members.find((x) => x.name === to) : undefined;
  const words: Partial<Record<GlanceMemberState, string>> = {
    working: 'is working: it gets your message during this turn.',
    idle: 'is idle: your message wakes it.',
    ready: 'is ready: it gets your message at its next turn.',
    held: "is waiting for an answer: it gets your message once that's answered.",
  };
  const own = m ? words[m.state] : undefined;
  let text =
    own ??
    'A working member gets your message during its turn, a ready one at its next turn, a waiting one after its answer; an idle one wakes up.';
  if (run.phase.name === 'limit') text += ` No new turn starts before ${clockDayOf(run.phase.resumesAt, now) ?? 'the limit resets'}.`;
  return { name: own && m ? m.name : null, text };
}

/** Latest's time column (D59): "1 s ago", "4 min ago"; a time after Temper's clock shows its clock time (D22), with its day after today (D104). */
export function latestAgo(iso: string | null, now: number | null): string {
  const t = msOf(iso);
  if (t === null || now === null) return '';
  return isFuture(t, now) ? (clockDayOf(iso, now) ?? '') : `${durationWords(now - t)} ago`;
}

/** "12 s ago"; "recorded at 3:00 PM" for a future time (D22; "recorded tomorrow at 3:00 PM" after today, D104); '' when the time (or Temper's clock) isn't known. */
export function agoText(iso: string | null, now: number | null): string {
  const t = msOf(iso);
  if (t === null || now === null) return '';
  return isFuture(t, now) ? `recorded ${atWords(iso, now)}` : `${durationWords(now - t)} ago`;
}

/**
 * How long a state has lasted ("12 s"); "since 3:00 PM" when Temper's own
 * time for it is in the future (D22); null when Temper didn't say since when
 * (or its clock isn't known).
 */
export function sinceWords(iso: string | null, now: number | null): string | null {
  const t = msOf(iso);
  if (t === null || now === null) return null;
  return isFuture(t, now) ? `since ${clockDayOf(iso, now)}` : durationWords(now - t);
}

/** All activity's clock (D46): "15:04:09", 24 h with seconds so same-minute rows read in order, in the viewer's own time. */
export function clockSecOf(iso: string | null | undefined): string | null {
  const t = msOf(iso);
  if (t === null) return null;
  return new Date(t).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
}

/** "3:00 PM" in the viewer's own time. */
export function clockOf(iso: string | null): string | null {
  const t = msOf(iso);
  if (t === null) return null;
  return new Date(t).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
}

/**
 * Design D104: a time after Temper's clock gets its day, by the calendar in
 * the viewer's own time zone; "today" is Temper's day there (`now`, the clock
 * D4's ages count to). '' for later today, "tomorrow", "Mon" within 6 days,
 * "Mon Oct 12" after that. A time that isn't ahead, or one without Temper's
 * clock, has none: past times read as they always did.
 */
export function dayWords(iso: string | null | undefined, now: number | null): string {
  const t = msOf(iso);
  if (t === null || now === null || !isFuture(t, now)) return '';
  const day = new Date(t);
  const today = new Date(now);
  const days = Math.round(
    (Date.UTC(day.getFullYear(), day.getMonth(), day.getDate()) - Date.UTC(today.getFullYear(), today.getMonth(), today.getDate())) /
      86_400_000,
  );
  if (days < 1) return '';
  if (days === 1) return 'tomorrow';
  const weekday = day.toLocaleDateString('en-US', { weekday: 'short' });
  return days <= 6 ? weekday : `${weekday} ${day.toLocaleDateString('en-US', { month: 'short' })} ${day.getDate()}`;
}

/** D104 in a sentence: "at 8:59 PM" today, "tomorrow at 8:59 PM", "Mon at 8:59 PM", "Mon Oct 12 at 8:59 PM"; null without a time. */
export function atWords(iso: string | null | undefined, now: number | null): string | null {
  const clock = clockOf(iso ?? null);
  if (clock === null) return null;
  const day = dayWords(iso, now);
  return day ? `${day} at ${clock}` : `at ${clock}`;
}

/**
 * The header's running time. Live: started_at to as_of; a start after Temper's clock has no age (D22),
 * it shows its clock time, with its day after today (D104). Ended: the frozen elapsed_s (G5), never the
 * clock. A project that didn't start has none: a request time is not working time (D121).
 */
export function runningWords(run: GlanceRun, now: number | null): string | null {
  if (run.phase.name === 'didnt_start') return null;
  const start = msOf(run.startedAt);
  if (!phaseEnded(run.phase.name)) {
    if (start === null || now === null) return null;
    return start > now ? `started ${atWords(run.startedAt, now)}` : `running ${durationWords(now - start)}`;
  }
  if (run.elapsedS !== null) return `ran ${durationWords(run.elapsedS * 1000)}`;
  return null;
}

/** D104 where a bare clock time stands: "8:59 PM" today, "tomorrow at 8:59 PM" (and so on) after today; null without a time. */
export function clockDayOf(iso: string | null | undefined, now: number | null): string | null {
  const clock = clockOf(iso ?? null);
  if (clock === null) return null;
  const day = dayWords(iso, now);
  return day ? `${day} at ${clock}` : clock;
}

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** Temper's words end without a full stop; another sentence may follow them. */
function fullStop(s: string): string {
  return /[.!?…]$/.test(s) ? s : `${s}.`;
}

/** A text's first line, trimmed ('' for none). */
export function firstLineOf(s: string | null | undefined): string {
  return (s ?? '').split('\n')[0].trim();
}

/**
 * Design D62's cut: at most n characters, ending after a whole word (when
 * one ends in the last 40%), then "\u2026"; trailing commas, colons and dashes
 * go too. A text that fits stays whole.
 */
export function cutAt(text: string, n: number): string {
  if (text.length <= n) return text;
  let s = text.slice(0, n - 1);
  const space = s.lastIndexOf(' ');
  if (space >= n * 0.6) s = s.slice(0, space);
  return `${s.replace(/[\s,;:\u2013\u2014-]+$/, '')}\u2026`;
}

/**
 * The waits whose words Temper writes itself (a held turn's recovery, the
 * check-in, the quiet team, settings, the weekly limit): never cut (D62).
 */
const TEMPER_WAIT_KINDS: ReadonlySet<string> = new Set(['pause', 'recovery', 'stalled', 'quiet', 'settings', 'limit']);

/** A member's own question (`ask_owner`, up to 1,000 characters): the only words D62 cuts. */
export function isMemberQuestion(kind: string | null | undefined): boolean {
  return !!kind && !TEMPER_WAIT_KINDS.has(kind);
}

/** A wait's words in the You cell: a member's question cut at 90 after a whole word, Temper's own whole (D62). */
export function bandWords(kind: string | null | undefined, words: string | null | undefined): string {
  const line = firstLineOf(words);
  return isMemberQuestion(kind) ? cutAt(line, 90) : line;
}

/** A wait's words on a card and in activity rows: a member's question cut at 160, Temper's own whole (D62). */
export function rowWords(kind: string | null | undefined, words: string | null | undefined): string {
  const line = firstLineOf(words);
  return isMemberQuestion(kind) ? cutAt(line, 160) : line;
}

/** Keeps a short phrase on one line ("12\u00a0s\u00a0ago", D69). */
export function keepTogether(s: string): string {
  return s.replace(/ /g, '\u00a0');
}

/** A sender or receiver as the page names it: the owner is "You", Temper "Temper". */
export function whoName(name: string | null | undefined, kind?: GlanceMessageFrom): string {
  if (kind === 'owner' || name === 'owner') return 'You';
  if (kind === 'temper' || name === 'temper') return 'Temper';
  return name ?? 'someone';
}

/**
 * The start state (owner bp-8d6a7652): only the leader gets the goal; every
 * other member is idle with 0 turns and no idle note until the leader's first
 * message reaches it. Temper marks it with the idle reason "start"; before
 * that event exists the state alone tells it.
 */
export function waitsForLeader(m: GlanceMember): boolean {
  if (m.leader || m.state !== 'idle') return false;
  return m.idleReason === 'start' || (m.turns === 0 && !m.idleNote && m.idleReason === null);
}

/** Members other than the leader that still wait for its first message. */
export function waitingForLeader(run: Pick<GlanceRun, 'members'>): GlanceMember[] {
  return run.members.filter(waitsForLeader);
}

// --- Now ---------------------------------------------------------------------------------

export type GlanceTone = 'blue' | 'yellow' | 'grey' | 'green' | 'red';
export type GlanceIcon =
  | 'play'
  | 'pause'
  | 'flag'
  | 'moon'
  | 'settings'
  | 'hand'
  | 'clock'
  | 'restart'
  | 'check'
  | 'stop'
  | 'alert'
  | 'circle'
  | 'retry'
  | 'ready'
  | 'wait';

export interface NowCell {
  word: string;
  sentence: string | null;
  /** The small count line under the sentence while the team works ("1 ready · 1 idle"). */
  countLine: string | null;
  edge: GlanceTone;
  icon: GlanceIcon;
  /** D105: the sentence's second line, Temper's reason for an interrupted run (at most 80 characters). */
  reason?: string;
  /** A stopped or failed run's words given with the stop, under the sentence: whole, as sent (plain text). */
  words?: GlanceStopWords;
}

/** The small count line: "1 ready · 1 idle · 1 needs you · 1 awaiting retry" (zeros left out). */
export function countLine(counts: GlanceCounts): string | null {
  const parts: string[] = [];
  if (counts.ready > 0) parts.push(`${counts.ready} ready`);
  if (counts.idle > 0) parts.push(`${counts.idle} idle`);
  if (counts.held > 0) parts.push(`${counts.held} ${counts.held === 1 ? 'needs' : 'need'} you`);
  // D18: a failed member's retry has not started yet.
  if (counts.failed > 0) parts.push(`${counts.failed} awaiting retry`);
  return parts.length ? parts.join(' · ') : null;
}

export interface WorkingRow {
  name: string;
  icon: GlanceIcon;
  tone: GlanceTone;
  /** "working on", "working \u00b7 last shared" or "working". */
  words: string;
  /** What it is on: a first line (quoted), "the goal", or null. */
  text: string | null;
  quoted: boolean;
}

/**
 * D8: who is working, inside Now at every width: at most `max` rows, then
 * "and N more working". The words come from `on` alone, never from the
 * leader's "Sent X:" line (a message it sent is not its work).
 */
export function workingNow(run: Pick<GlanceRun, 'members' | 'phase'>, max = 3): { rows: WorkingRow[]; more: number } {
  const busy = run.members.filter((m) => m.state === 'working');
  const rows = busy.slice(0, max).map((m): WorkingRow => {
    const chip = memberChip(m, run.phase.name, null);
    const on = m.on;
    const text = firstLineOf(on?.text);
    const row = { name: m.name, icon: chip.icon, tone: chip.tone };
    if (on?.kind === 'goal') return { ...row, words: 'working on', text: 'the goal', quoted: false };
    if (on?.kind === 'work_request' && text) return { ...row, words: 'working on', text, quoted: true };
    if (on?.kind === 'share' && text) return { ...row, words: 'working \u00b7 last shared', text, quoted: true };
    return { ...row, words: 'working', text: null, quoted: false };
  });
  return { rows, more: Math.max(0, busy.length - max) };
}

/**
 * D74: Now's sentence already counts the team ("2 of 5 members are working"),
 * so on a phone the header leaves its own "5 members" out. Only when both
 * name the same number.
 */
export function nowCountsMembers(run: GlanceRun): boolean {
  const n = run.members.length;
  const sentence = nowCell(run, null).sentence ?? '';
  return sentence.includes(` of ${n} ${n === 1 ? 'member' : 'members'} `);
}

/**
 * The Now cell: one state word, one sentence with the counts that matter,
 * and the band's edge colour (GLANCE.md, team phase table). While Temper
 * doesn't answer (`stale`), "Last activity" is left out (D64): the stale
 * note already says how long it has been silent. `lastAt`: the newest time
 * Temper recorded in the loaded reply and feed (lastRecordedAt), for an
 * interrupted run with no end time (D105); without it, the reply's own.
 */
export function nowCell(run: GlanceRun, now: number | null, stale = false, lastAt?: string | null): NowCell {
  const cell = phaseNowCell(run, now, stale, lastAt);
  // D112: when the team waits for the owner's answer and no member is working, the sentence says so ("Nothing runs
  // until you answer." didn't tell a cold reader who was busy). Only on Temper's own counts: an unknown count or a
  // turn still running keeps the phase's own sentence.
  return nobodyWorksUntilYouAnswer(run) ? { ...cell, sentence: 'No one is working until you answer.' } : cell;
}

/** D112: the team waits for the owner's answer, Temper says no member works, and no turn is still finishing. */
export function nobodyWorksUntilYouAnswer(run: Pick<GlanceRun, 'phase' | 'counts'>): boolean {
  const { phase, counts } = run;
  const asked =
    phase.name === 'waiting_for_owner' ||
    phase.name === 'quiet' ||
    phase.name === 'settings' ||
    ((phase.name === 'check_in' || phase.name === 'limit') && phase.asked);
  return asked && counts.workingSupplied !== false && counts.working === 0 && phase.running === 0;
}

/**
 * D97: what the latest version holds, for Now's two version lines, from `work.latest`. Line 1: "Latest version v6
 * from Backend \u00b7 4 min ago"; line 2: the member's share note (its own words, quoted, one line: line breaks become
 * spaces), or with no note "4 files changed". Null before any share ("No shared version yet.").
 */
export interface VersionLines {
  versionNo: number;
  /** Who shared it, as Temper named the member; null when it didn't say. */
  by: string | null;
  /** "4 min ago" (a time in the future reads "recorded \u2026", as everywhere on the page); null without a time. */
  ago: string | null;
  /** The share note on one line; null when there is none (a blank note is none). */
  note: string | null;
  /** "4 files changed" / "1 file changed" when there is no note; null when Temper sent no count. */
  files: string | null;
}

export function versionLines(latest: GlanceShare | null, now: number | null): VersionLines | null {
  if (!latest) return null;
  const ago = agoText(latest.at, now) || null;
  const note = (latest.note ?? '').replace(/\s+/g, ' ').trim() || null;
  const files =
    note === null && latest.filesChanged !== null ? plural(latest.filesChanged, 'file changed', 'files changed') : null;
  return { versionNo: latest.versionNo, by: latest.by, ago, note, files };
}

/**
 * D111: a share note too long for its line is cut to the room left, keeping its opening quote and closing it right
 * after the ellipsis ("\u201cExport button and CSV wri\u2026\u201d"), with no space or stray comma before the ellipsis.
 * `keep` is how many of the note's characters stay.
 */
const noteGraphemes = new Intl.Segmenter('en', { granularity: 'grapheme' });

export function cutNote(note: string, keep: number): string {
  if (keep >= note.length) return `\u201c${note}\u201d`;
  // Keep the existing UTF-16 room budget and ASCII output; floor it to a whole visible character.
  let end = 0;
  for (const { index, segment } of noteGraphemes.segment(note)) {
    const boundary = index + segment.length;
    if (boundary > Math.max(0, keep)) break;
    end = boundary;
  }
  return `\u201c${note.slice(0, end).replace(/[\s,;:\u2013\u2014-]+$/, '')}\u2026\u201d`;
}

function phaseNowCell(run: GlanceRun, now: number | null, stale: boolean, lastAt?: string | null): NowCell {
  const { phase, counts } = run;
  const last = stale ? '' : agoText(run.lastActivityAt, now);
  // D69: "12 s ago" stays on one line.
  const lastPart = last ? ` Last activity ${last.endsWith(' ago') ? keepTogether(last) : last}.` : '';
  switch (phase.name) {
    case 'starting': {
      // D63: who works, from Temper's own count (nothing when it sent none);
      // D36: "has the goal" only when the leader's `on` says so.
      const total = counts.members;
      const who =
        counts.workingSupplied === false
          ? ''
          : counts.working > 0
            ? `${counts.working} of ${total} ${total === 1 ? 'member' : 'members'} working. `
            : 'No one is working yet. ';
      const leader = run.members.find((m) => m.leader);
      return {
        word: 'Starting',
        sentence: `${who}${leader?.on?.kind === 'goal' ? 'The leader has the goal.' : 'The leader starts first.'}`,
        countLine: null,
        edge: 'blue',
        icon: 'play',
      };
    }
    case 'working': {
      const waiting = waitingForLeader(run);
      const others = run.members.filter((m) => !m.leader).length;
      if (others > 0 && waiting.length === others) {
        const leader = run.members.find((m) => m.leader);
        const n = plural(waiting.length, 'member waits', 'members wait');
        return {
          word: 'Working',
          sentence:
            leader?.state === 'working'
              ? `The leader is working; ${n} for its first message.${lastPart}`
              : `${n} for the leader's first message.${lastPart}`,
          countLine: null,
          edge: 'blue',
          icon: 'play',
        };
      }
      const total = counts.members;
      return {
        word: 'Working',
        // SPEC Now table, working: "N of M members working."
        sentence: `${counts.working} of ${total} ${total === 1 ? 'member' : 'members'} working.${lastPart}`,
        countLine: countLine(counts),
        edge: 'blue',
        icon: 'play',
      };
    }
    case 'closing':
      return {
        word: 'Finishing up',
        sentence: `The leader said done.${phase.running > 0 ? ` ${plural(phase.running, 'turn is', 'turns are')} finishing.` : ''}`,
        countLine: null,
        edge: 'blue',
        icon: 'flag',
      };
    case 'check_in': {
      // SPEC Now table: "Check-in at $X" uses spend.cost_usd ("Check-in at $100.40").
      const at = run.spend ? ` at ${money(run.spend.cost)}` : '';
      if (!phase.asked) {
        return {
          // D95: the word alone tells "not asked yet" from "asked", only while turns are really finishing.
          word: `Check-in${at}${phase.running > 0 ? ': finishing turns' : ''}`,
          sentence: `No new work starts. ${plural(phase.running, 'member is finishing its turn', 'members are finishing their turns')}.`,
          countLine: null,
          edge: 'blue',
          icon: 'pause',
        };
      }
      return {
        word: `Check-in${at}`,
        sentence: 'No new work starts until you answer.',
        countLine: null,
        edge: 'yellow',
        icon: 'pause',
      };
    }
    case 'quiet':
      return { word: 'Everyone is idle', sentence: `Nothing is waiting for the team.${lastPart}`, countLine: null, edge: 'yellow', icon: 'moon' };
    case 'settings':
      // SPEC Now table, settings: Design's words; You says what is asked.
      return { word: 'Settings changed', sentence: 'A setting changed while the team waited.', countLine: null, edge: 'yellow', icon: 'settings' };
    case 'waiting_for_owner':
      return { word: 'Waiting for you', sentence: 'Nothing runs until you answer.', countLine: null, edge: 'yellow', icon: 'hand' };
    case 'limit': {
      // Temper's own words say which limit it is and what happens next. A
      // known or passed reset never means the team carries on by itself, and
      // never makes a question: only Temper's verified reading and the wait it
      // lists do (D31). resumesAt is the next allowance check, not a reset.
      let sentence = fullStop(phase.words?.split('\n')[0].trim() || 'The account hit its usage limit.');
      // D104: a check after today names its day ("Next allowance check Mon Oct 12 at 8:59 PM.").
      const at = atWords(phase.resumesAt, now);
      // Design SPEC limit row: the pending check first, then the missing reset.
      if (limitCheckShown(phase)) {
        if (at) sentence += ` Next allowance check ${at}.`;
        if (phase.resetsKnown === false) sentence += ' No usable reset time.';
      }
      if (phase.running > 0) sentence += ` ${plural(phase.running, 'turn', 'turns')} finishing.`;
      // D89: usage is back and the team waits for the owner: it reads like an asked check-in (yellow, pause).
      if (phase.asked) return { word: 'Usage limit: waiting for you', sentence, countLine: null, edge: 'yellow', icon: 'pause' };
      return { word: 'Usage limit', sentence, countLine: null, edge: 'grey', icon: 'clock' };
    }
    case 'draining':
      return { word: 'Temper is restarting', sentence: 'The team carries on after it.', countLine: null, edge: 'grey', icon: 'restart' };
    case 'done':
      return { word: 'Done', sentence: null, countLine: null, edge: 'green', icon: 'check' };
    case 'stopped':
      return withStopWords(run, { word: 'Stopped', sentence: nowEndReason(phase.reason), countLine: null, edge: 'grey', icon: 'stop' });
    case 'failed':
      return withStopWords(run, { word: 'Failed', sentence: nowEndReason(phase.reason), countLine: null, edge: 'red', icon: 'alert' });
    case 'didnt_start':
      // D121: failure before a turn is terminal; the adapter resolves only supplied reason fallbacks.
      return { word: 'Failed to start', sentence: phase.reason ?? "The project couldn't start. Temper gave no reason.", countLine: null, edge: 'red', icon: 'alert' };
    case 'interrupted': {
      // D119: Temper's generic run-status template is no explanation. Capitalise a real second line's first letter only.
      const reason = interruptionReason(phase.reason);
      const second = reason ? { reason: cutAt(reason.charAt(0).toUpperCase() + reason.slice(1), 80) } : {};
      if (run.elapsedS === null) {
        // D105: Temper recorded no end time; the newest time it recorded stands in.
        const last = clockDayOf(lastAt === undefined ? lastRecordedAt(run, []) : lastAt, now);
        return {
          word: 'Interrupted',
          sentence: `${last ? `Last activity ${last}. ` : ''}Temper didn\u2019t record when it ended.`,
          countLine: null,
          edge: 'red',
          icon: 'alert',
          ...second,
        };
      }
      // SPEC Now table: one fixed sentence for a run with an end time.
      return { word: 'Interrupted', sentence: 'The run ended without the team ending.', countLine: null, edge: 'red', icon: 'alert', ...second };
    }
    default:
      return { word: phase.words ?? 'State not known', sentence: null, countLine: null, edge: 'grey', icon: 'circle' };
  }
}

/**
 * D105: the newest time Temper recorded in the loaded reply and feed: the
 * run's last activity, every event's time, each member's last turn. Null
 * when it recorded none.
 */
export function lastRecordedAt(run: Pick<GlanceRun, 'lastActivityAt' | 'members'>, events: readonly GlanceEvent[]): string | null {
  const times = [run.lastActivityAt, ...events.map((e) => e.at), ...run.members.map((m) => m.lastTurnAt ?? null)];
  let newest: string | null = null;
  for (const t of times) if (t && msOf(t) !== null && later(t, newest)) newest = t;
  return newest;
}

// --- You -----------------------------------------------------------------------------

export interface YouCell {
  /** `stale`: Temper isn't answering, so the last reply can't say that nothing needs you now (D64). */
  tone: 'calm' | 'needs' | 'ended' | 'stale';
  title: string;
  line: string | null;
  /** The line is the hint a phone leaves out (D9). */
  hint: boolean;
  /** "From <member>": shares its row with Answer (D9). */
  from: string | null;
  /** The wait whose answers go in the cell. */
  waitId: string | null;
  /** More open questions after the first ("and N more", next to the title). */
  more: number;
  /**
   * answers: the team's own question, answered in place; answer: one Answer
   * button that opens the answer view (a member's question or held turn, D9).
   */
  action: 'answers' | 'answer' | 'summary' | 'next' | null;
}

const CALM_LINE = 'Questions and check-ins show up here.';

function calm(title: string, line: string | null, extra: Partial<YouCell> = {}): YouCell {
  return { tone: 'calm', title, line, hint: false, from: null, waitId: null, more: 0, action: null, ...extra };
}

/**
 * The You cell (GLANCE.md: "You says"). Yellow whenever Temper waits on the
 * owner. `staleFor`: how long Temper hasn't answered ("15 min"), while it doesn't.
 */
export function youCell(run: GlanceRun, staleFor: string | null = null): YouCell {
  const { phase, you } = run;
  if (phase.name === 'done') return calm('Nothing needs you', null, { action: run.work.summary ? 'summary' : null });
  if (phase.name === 'didnt_start') return calm('Nothing needs you', 'You can start a new project.', { tone: 'ended', action: 'next' });
  if (phaseEnded(phase.name)) {
    // D16: nothing waits on the owner once it ended; the next action is optional. D90: sentence case.
    return calm('Nothing needs you', 'Read what it made below, or start a new project.', { tone: 'ended', action: 'next' });
  }
  // G7 keeps the pause wait in `you` while turns finish. It is not answerable
  // until phase.asked; a member's own question in this phase still is (D27).
  const first = phase.name === 'check_in' && !phase.asked && you.first?.kind === 'pause' ? null : you.first;
  if (you.count > 0 && first) {
    const more = Math.max(0, you.count - 1);
    const needs = { tone: 'needs' as const, line: null, hint: false, from: null, waitId: first.waitId, more, action: 'answers' as const };
    if (first.kind === 'pause') return { ...needs, title: 'Needs you: carry on?' };
    // D94: quotes mark a person's words only; Temper's own questions are not quoted, and each ends with "?".
    if (phase.name === 'quiet' || first.kind === 'stalled') return { ...needs, title: 'Needs you: nudge the team or stop?' };
    if (phase.name === 'settings' || first.kind === 'settings') return { ...needs, title: 'Needs you: go on or stop?' };
    if (first.kind === 'limit') return { ...needs, title: `Needs you: ${firstLineOf(first.words)}` };
    // A member's question or held turn (D9, D62): its words (a member's own
    // question cut at 90; Temper's whole), "From <member>" beside one Answer.
    // D94: a member's own question is a person's words, in quotes; a held turn's words are Temper's, unquoted.
    const words = bandWords(first.kind, first.words);
    return {
      ...needs,
      title: `Needs you: ${isMemberQuestion(first.kind) ? `\u201c${words}\u201d` : words}`,
      from: first.member ? `From ${first.member}` : null,
      action: 'answer',
    };
  }
  // D64: a held question still shows above; nothing else can be said now.
  if (staleFor) return calm(`Nothing needed you ${staleFor} ago`, 'Questions show up once Temper answers.', { tone: 'stale' });
  if (phase.name === 'check_in' && !phase.asked) {
    return calm('Nothing needs you yet', "You'll be asked to carry on once these turns finish.");
  }
  // SPEC You table: a limit with no open answerable wait.
  if (phase.name === 'limit') return calm('Nothing needs you', 'Stop stays at the top if you want to end it.');
  return calm('Nothing needs you', CALM_LINE, { hint: true });
}

// --- Spend ---------------------------------------------------------------------------

export interface SpendCell {
  amount: string;
  /** "of $100", or null when there is no next check-in to measure against. */
  of: string | null;
  /** Share of the bar, 0..1, or null for no bar. */
  fraction: number | null;
  line: string | null;
  tone: 'ok' | 'warn';
}

/** The Spend cell: spend so far against the next check-in, and what happens there. */
export function spendCell(run: GlanceRun): SpendCell {
  const s = run.spend;
  // D17: a missing spend is not known, never $0.00.
  if (!s) return { amount: 'Not known', of: null, fraction: null, line: null, tone: 'ok' };
  const amount = money(s.cost);
  if (phaseEnded(run.phase.name)) {
    // D19: an ended Project says there is no next check-in, then its counts.
    const versions = run.work.total > 0 ? ` \u00b7 ${plural(run.work.total, 'shared version', 'shared versions')}` : '';
    return {
      amount,
      of: null,
      fraction: null,
      // D67: no next check-in, said once.
      line: `Spent in all. ${plural(s.checkIns, 'check-in', 'check-ins')}, none to come${versions}.`,
      tone: 'ok',
    };
  }
  const of = `of ${money(s.nextCheckIn, true)}`;
  const fraction = s.nextCheckIn > 0 ? Math.min(1, Math.max(0, s.cost / s.nextCheckIn)) : null;
  if (run.phase.name === 'check_in') {
    return {
      amount,
      of,
      fraction: 1,
      // D11: Continue sets the next check-in to the spend at the answer plus
      // pause_every_usd. While turns still finish the spend grows, so only the
      // step is known; once nothing runs the exact amount is.
      line:
        run.phase.running > 0 && !run.phase.asked
          ? `If you continue, the next check-in comes ${money(s.pauseEvery, true)} later.`
          : `If you continue, the next check-in is at ${money(s.cost + s.pauseEvery, true)}.`,
      tone: 'warn',
    };
  }
  return {
    amount,
    of,
    fraction,
    // D2: short enough to stay on a phone's first screen.
    line: `At ${money(s.nextCheckIn, true)} the team pauses and asks you.`,
    tone: s.sinceCheckIn >= s.pauseEvery ? 'warn' : 'ok',
  };
}

// --- members ---------------------------------------------------------------------------

export type RingStyle =
  | 'dotted-grey'
  | 'solid-blue'
  | 'solid-grey'
  | 'dashed-yellow'
  | 'dashed-grey'
  | 'dashed-red'
  | 'thin-grey';

export interface MemberChip {
  text: string;
  icon: GlanceIcon;
  ring: RingStyle;
  tone: GlanceTone;
  /** The member is running a turn (the busy ring may move). */
  busy: boolean;
}

const FINISHING_PHASES: ReadonlySet<GlancePhaseName> = new Set(['closing', 'check_in', 'limit', 'draining']);
const TEAM_WAITS: Partial<Record<GlancePhaseName, string>> = {
  check_in: 'check-in',
  quiet: 'your answer',
  settings: 'your answer',
  waiting_for_owner: 'your answer',
  limit: 'usage limit',
};

/**
 * Why a ready member gets no turn now (D1): draining starts no new turn, and
 * while closing only the leader may take one. Null when it waits for a free turn.
 */
function readyPause(m: GlanceMember, phase: GlancePhaseName): string | null {
  const wait = TEAM_WAITS[phase];
  if (wait) return wait;
  if (phase === 'draining') return 'Temper is restarting';
  if (phase === 'closing' && !m.leader) return 'the team is finishing up';
  return null;
}

const ENDED_CHIP: MemberChip = { text: 'Ended', icon: 'stop', ring: 'thin-grey', tone: 'grey', busy: false };

/** The team phase a card is read in: its name, and whether its own question is open (D88). A bare name is a phase that asks nothing. */
export type CardPhase = GlancePhaseName | Pick<GlancePhase, 'name' | 'asked'>;

function phaseOf(p: CardPhase): Pick<GlancePhase, 'name' | 'asked'> {
  return typeof p === 'string' ? { name: p, asked: false } : p;
}

/**
 * D88: a ready member's pause is yellow only while the owner is asked ("your
 * answer", or a check-in or usage limit that asks); one that waits on Temper
 * or the team is grey, like Now and You for the same wait.
 */
function pauseAsksYou(wait: string, phase: Pick<GlancePhase, 'name' | 'asked'>): boolean {
  if (wait === 'your answer') return true;
  return (phase.name === 'check_in' || phase.name === 'limit') && phase.asked;
}

/** A member's chip, ring and tone (GLANCE.md, member state table). */
export function memberChip(m: GlanceMember, cardPhase: CardPhase, now: number | null): MemberChip {
  const p = phaseOf(cardPhase);
  const phase = p.name;
  // D105: once the run has ended in any way, every card reads Ended, in the neutral tone, with no live duration.
  if (phaseEnded(phase) || m.state === 'ended') return { ...ENDED_CHIP };
  const since = sinceWords(m.since, now);
  const how = since ? ` \u00b7 ${since}` : '';
  switch (m.state) {
    case 'working':
      if (m.retryOf !== null) return { text: `Working on a retry${how}`, icon: 'retry', ring: 'solid-blue', tone: 'blue', busy: true };
      if (FINISHING_PHASES.has(phase)) return { text: `Finishing its turn${how}`, icon: 'play', ring: 'solid-blue', tone: 'blue', busy: true };
      return { text: `Working${how}`, icon: 'play', ring: 'solid-blue', tone: 'blue', busy: true };
    case 'ready': {
      const wait = readyPause(m, phase);
      if (wait) {
        return pauseAsksYou(wait, p)
          ? { text: `Paused: ${wait}`, icon: 'pause', ring: 'dashed-yellow', tone: 'yellow', busy: false }
          : { text: `Paused: ${wait}`, icon: 'pause', ring: 'dashed-grey', tone: 'grey', busy: false };
      }
      // D95: the chip keeps one line; the waiting messages go on the On line (memberLine).
      return { text: 'Ready \u00b7 waiting for a free turn', icon: 'ready', ring: 'solid-grey', tone: 'grey', busy: false };
    }
    case 'idle':
      // D77: a clock on a filled dotted ring; a dashed circle on an empty ring read as loading.
      if (waitsForLeader(m)) return { text: 'Waiting for the leader', icon: 'clock', ring: 'dotted-grey', tone: 'grey', busy: false };
      // The leader before its first turn starts (team phase "starting").
      if (m.leader && m.turns === 0 && !m.idleNote) return { text: 'Has the goal', icon: 'flag', ring: 'dotted-grey', tone: 'grey', busy: false };
      return { text: `Idle${how}`, icon: 'moon', ring: 'dotted-grey', tone: 'grey', busy: false };
    case 'held':
      return { text: 'Needs you', icon: 'alert', ring: 'dashed-yellow', tone: 'yellow', busy: false };
    case 'failed':
      // D18: the retry has not started; a running retry is "Working on a retry".
      return { text: 'Turn failed \u00b7 retry pending', icon: 'retry', ring: 'dashed-red', tone: 'red', busy: false };
    default:
      return { text: 'State not known', icon: 'circle', ring: 'thin-grey', tone: 'grey', busy: false };
  }
}

export interface MemberLine {
  /** "On:", "Sent QA:", "Idle:", "Last:" (an ended card), or null for a line without a label. */
  label: string | null;
  /** The words; empty when the line holds only the waiting messages. */
  text: string;
  /** The text is someone's words (shown in quotes). */
  quoted: boolean;
  /**
   * D95: a ready member's waiting messages ("2\u00a0messages"), after the words on this line (never on the
   * chip), with no-break spaces so "\u00b7 2 messages" stays with the word before it (D69). Only for a ready
   * member that waits for a free turn: never on a paused or an ended card (SPEC 244, 252).
   */
  messages?: string;
}

function onText(m: GlanceMember): string | null {
  if (m.on?.text) return m.on.text;
  if (m.lastShareNote) return m.lastShareNote;
  if (m.idleNote) return m.idleNote;
  return null;
}

/**
 * The card's one line of what the member is on: the work_request it is on,
 * else its last share note, else its idle note. The leader shows the last
 * message it released ("Sent QA: ..."). A member that waits for the leader
 * shows none: no made-up note.
 */
export function memberLine(m: GlanceMember, cardPhase?: CardPhase): MemberLine | null {
  const phase = cardPhase === undefined ? null : phaseOf(cardPhase).name;
  // SPEC 252: an ended card says what the member was last on, "Last: \u201c\u2026\u201d", the leader too, with no
  // message count (SPEC 244), even on an interrupted run whose member still had messages waiting.
  if ((phase !== null && phaseEnded(phase)) || m.state === 'ended') {
    const sent = m.leader ? lastSentOf(m) : null;
    // D121: an assigned goal before any turn is not work performed. Keep actual supplied historical work.
    const noTurns = m.turns === 0 && m.turnsSupplied !== false && !m.hasTurnHistory && !m.lastTurnAt;
    const on = phase === 'didnt_start' && noTurns && m.on?.kind === 'goal' ? null : m.on?.text;
    const text = sent?.text || on || m.lastShareNote || m.idleNote;
    if (text) return { label: 'Last:', text, quoted: true };
    return { label: 'Last:', text: phase === 'didnt_start' && noTurns ? 'No work started.' : 'No last work recorded.', quoted: false };
  }
  const line = liveMemberLine(m);
  // D95: a ready member's waiting messages move from the chip to this line.
  if (m.state !== 'ready' || m.readyMessages <= 0 || (phase !== null && readyPause(m, phase))) return line;
  const messages = plural(m.readyMessages, 'message', 'messages').replace(' ', '\u00a0');
  return line ? { ...line, messages } : { label: null, text: '', quoted: false, messages };
}

/** The message the leader released last: Temper's last_sent, else its `on` of kind "message". */
function lastSentOf(m: GlanceMember): { to: string; text: string } | null {
  return m.lastSent ?? (m.on?.kind === 'message' && m.on.to ? { to: m.on.to, text: m.on.text } : null);
}

function liveMemberLine(m: GlanceMember): MemberLine | null {
  if (waitsForLeader(m)) return null;
  if (m.state === 'idle') {
    if (m.idleReason === 'no_tool_call') return { label: null, text: 'Ended its turn without a note', quoted: false };
    return m.idleNote ? { label: 'Idle:', text: m.idleNote, quoted: true } : null;
  }
  // D13: its own wait's words; the generic line only when Temper sent none.
  // D62: a member's own question keeps 160 characters here; Temper's words stay whole.
  if (m.state === 'held') {
    return { label: null, text: m.waitWords ? rowWords(m.waitKind, m.waitWords) : 'Its question is waiting for you.', quoted: false };
  }
  if (m.state === 'failed') return m.lastError ? { label: null, text: m.lastError, quoted: false } : null;
  // The leader shows the last message it sent, also once the run ended: its
  // `on` of kind "message" is that message, not work it is on.
  const sent = m.leader ? lastSentOf(m) : null;
  if (sent) return { label: `Sent ${whoName(sent.to)}:`, text: sent.text, quoted: true };
  const text = onText(m);
  return text ? { label: 'On:', text, quoted: true } : null;
}

/** "edit ×4 · bash ×2", most used first; null when Temper sent no tool count. */
export function toolsLine(m: GlanceMember): string | null {
  if (m.state !== 'working' || !m.toolsNow || m.toolsNow.length === 0) return null;
  return [...m.toolsNow]
    .sort((a, b) => b.count - a.count)
    .map((t) => `${t.name} \u00d7${t.count}`)
    .join(' \u00b7 ');
}

/** "6 turns · $15.80". */
export function turnsLine(m: GlanceMember): string {
  const turns = plural(m.turns, 'turn', 'turns');
  return m.cost === null ? turns : `${turns} \u00b7 ${money(m.cost)}`;
}

/** "⚠ 2 files in conflict", when a merge left its copy in conflict. */
export function conflictLine(m: GlanceMember): string | null {
  return m.conflicts > 0 ? `${plural(m.conflicts, 'file', 'files')} in conflict` : null;
}

/**
 * "Team now" header count: "4 working · 1 idle", in the cards' own words
 * (SPEC 5, D12, D18): a running turn counts as "finishing" where its card
 * says "Finishing its turn"; a ready member counts as "paused" where its
 * card says "Paused: …" (while the team waits, in draining, and every one
 * but the leader while closing); an ended run reads "3 members · all ended",
 * whatever states Temper left its members in.
 */
export function teamCountWords(run: GlanceRun): string {
  const c = run.counts;
  const phase = run.phase.name;
  if (phaseEnded(phase)) return `${plural(run.members.length, 'member', 'members')} \u00b7 all ended`;
  const waiting = waitingForLeader(run).length;
  const paused = Math.min(c.ready, run.members.filter((m) => m.state === 'ready' && readyPause(m, phase) !== null).length);
  const ready = c.ready - paused;
  const parts: string[] = [];
  if (c.working) parts.push(`${c.working} ${FINISHING_PHASES.has(phase) ? 'finishing' : 'working'}`);
  if (ready) parts.push(`${ready} ready`);
  if (paused) parts.push(`${paused} paused`);
  if (waiting) parts.push(`${waiting} waiting for the leader`);
  if (c.idle - waiting > 0) parts.push(`${c.idle - waiting} idle`);
  if (c.held) parts.push(`${c.held} ${c.held === 1 ? 'needs' : 'need'} you`);
  if (c.failed) parts.push(`${c.failed} awaiting retry`);
  if (c.ended) parts.push(`${c.ended} ended`);
  return parts.join(' \u00b7 ');
}

const LIST_ORDER: Record<GlanceMemberState, number> = { working: 0, held: 1, failed: 2, ready: 3, idle: 4, ended: 5, unknown: 6 };

/** The phone list: working first, then needs you, awaiting retry, ready, idle, ended; the leader first in its group. */
export function listOrder(members: GlanceMember[]): GlanceMember[] {
  return members
    .map((m, i) => ({ m, i }))
    .sort((a, b) => LIST_ORDER[a.m.state] - LIST_ORDER[b.m.state] || Number(b.m.leader) - Number(a.m.leader) || a.i - b.i)
    .map(({ m }) => m);
}

// --- the map --------------------------------------------------------------------------

export interface MapSlot {
  name: string;
  /** 1 left, 2 centre (the leader), 3 right. */
  col: 1 | 2 | 3;
  row: number;
}

/**
 * Where each card sits: the leader in the centre, the others in a ring
 * around it, clockwise from the top left in member order (left column top,
 * right column top to bottom, left column bottom to top). Deterministic, and
 * no two cards can overlap at any width.
 */
export function mapSlots(members: GlanceMember[]): { slots: MapSlot[]; rows: number } {
  const leader = members.find((m) => m.leader) ?? members[0];
  const others = members.filter((m) => m !== leader);
  const rows = Math.max(1, Math.ceil(others.length / 2));
  const ring: Array<{ col: 1 | 3; row: number }> = [{ col: 1, row: 1 }];
  for (let r = 1; r <= rows; r++) ring.push({ col: 3, row: r });
  for (let r = rows; r >= 2; r--) ring.push({ col: 1, row: r });
  const slots: MapSlot[] = [];
  if (leader) slots.push({ name: leader.name, col: 2, row: 1 });
  others.forEach((m, i) => slots.push({ name: m.name, ...ring[i] }));
  return { slots, rows };
}

export interface MapLine {
  /** The pair, in name order. */
  a: string;
  b: string;
  count: number;
  lastAt: string | null;
}

/** One line per pair of members who messaged each other in the last hour, with the count. */
export function mapLines(run: Pick<GlanceRun, 'links' | 'members'>): MapLine[] {
  const known = new Set(run.members.map((m) => m.name));
  const pairs = new Map<string, MapLine>();
  for (const l of run.links) {
    if (l.count <= 0 || l.from === l.to || !known.has(l.from) || !known.has(l.to)) continue;
    const [a, b] = l.from < l.to ? [l.from, l.to] : [l.to, l.from];
    const key = `${a}\u0000${b}`;
    const line = pairs.get(key) ?? { a, b, count: 0, lastAt: null };
    line.count += l.count;
    if (later(l.lastAt, line.lastAt)) line.lastAt = l.lastAt;
    pairs.set(key, line);
  }
  return [...pairs.values()];
}

/** A pair's key in name order, as mapLines orders it: "builder|lead". */
export function pairKey(a: string, b: string): string {
  return a < b ? `${a}|${b}` : `${b}|${a}`;
}

/** D42: a pair is drawn while its newest message is at most 10 min older than Temper's reply (`as_of`). */
export const RECENT_LINE_MS = 10 * 60_000;
/** D42: the map draws at most 4 lines. */
export const MAX_LINES = 4;
/** A drawn line is green (3 px accent) for a minute after a message on it, by Temper's reply time. */
export const GREEN_LINE_MS = 60_000;

const lineSecond = (l: Pick<MapLine, 'lastAt'>) => Math.floor((msOf(l.lastAt) ?? -8.64e15) / 1000);

/**
 * Newest first, to the second (a same-second burst is a tie), then the
 * higher count, then the names A-Z (Design D42, glance.mjs lineOrder).
 */
export function lineOrder(p: MapLine, q: MapLine): number {
  return (
    lineSecond(q) - lineSecond(p) ||
    q.count - p.count ||
    (p.a < q.a ? -1 : p.a > q.a ? 1 : p.b < q.b ? -1 : p.b > q.b ? 1 : 0)
  );
}

/**
 * The lines the map draws (D42): the pairs whose newest message is within
 * 10 min of Temper's reply time (`asOf`, never the device's clock, so stale
 * and ended runs keep their frozen time), at most 4, newest first.
 */
export function drawnLines(lines: MapLine[], asOf: number | null): MapLine[] {
  if (asOf === null) return [];
  return lines
    .filter((l) => {
      const t = msOf(l.lastAt);
      return t !== null && asOf - t <= RECENT_LINE_MS;
    })
    .sort(lineOrder)
    .slice(0, MAX_LINES);
}

/** A drawn line is green for a minute after a message on it, by Temper's reply time. */
export function lineGreen(line: Pick<MapLine, 'lastAt'>, asOf: number | null): boolean {
  const t = msOf(line.lastAt);
  return asOf !== null && t !== null && asOf - t <= GREEN_LINE_MS;
}

export interface HourRow {
  /** The pair's key (pairKey), the same as its drawn line's. */
  key: string;
  /** "builder and lead: 3 messages": the count its badge shows. */
  pair: string;
  /** "last 4 min ago" by Temper's reply time; a time after it shows its clock time (D22); "time not supplied". */
  time: string;
}

/**
 * "Messages in the last hour" (D44): every pair, newest first in the map's
 * order, so the top rows are the drawn lines; each with the count its badge
 * shows and how long ago its last message was.
 */
export function hourRows(lines: MapLine[], asOf: number | null): HourRow[] {
  return [...lines].sort(lineOrder).map((l) => {
    const t = msOf(l.lastAt);
    const time =
      t === null
        ? 'time not supplied'
        : asOf !== null && t <= asOf
          ? `last ${durationWords(asOf - t)} ago`
          : `last ${atWords(l.lastAt, asOf)}`;
    return { key: pairKey(l.a, l.b), pair: `${l.a} and ${l.b}: ${l.count}\u00a0${l.count === 1 ? 'message' : 'messages'}`, time };
  });
}

// --- motion -----------------------------------------------------------------------------

export const DOT_MS = 400;
export const DOT_STAGGER_MS = 120;
export const DOT_MAX_AT_ONCE = 6;

export interface DotPlan {
  dots: Array<{ event: GlanceMessageEvent; delay: number }>;
  /** Messages past the dots allowed at once: one grouped "+N more sent" cue (D10). */
  extra: number;
  /** D82: the corner's batches that light up instead of flying, each at its second's turn in the plan. */
  lights: Array<{ batch: HubBatch; delay: number }>;
}

/** The grouped cue's words (Design D10). */
export function extraWords(extra: number): string {
  return `+${extra} more sent`;
}

/**
 * D82 (Design, HOME-DECISIONS-2026-10-09-2030 Q1 and its 21:10 follow-up):
 * when You or Temper message this many members or more in the same second
 * (Temper's clock), at every width, the map draws no lines and no dots from
 * the corner for them. The sender's tag glows, each receiving ring gets its
 * highlight and one cue names the batch: "Temper \u2192 6 members". Fewer
 * receivers keep D81's lines.
 */
export const HUB_BATCH_MIN = 3;

/** One sender's part of a corner batch: You or Temper, and the members it reached, each once, in release order. */
export interface HubPart {
  fromKind: 'owner' | 'temper';
  to: string[];
}

/**
 * A same-second batch from the corner that lights up (D82). Every line from
 * the corner leaves the same box, so the receivers are counted for the
 * corner as a whole: a batch where You and Temper each message one or two
 * members still has no lines once three members are reached (recorded for
 * Design). Each sender's part keeps its own words.
 */
export interface HubBatch {
  /** The second it was released in, by Temper's clock ("2026-10-09T10:13:23"). */
  second: string;
  /** Each sender's part, in release order. */
  parts: HubPart[];
  /** Every member reached, each once, in release order. */
  to: string[];
  /** Its messages, each id once, oldest first. */
  events: GlanceMessageEvent[];
}

const isCorner = (m: GlanceMessageEvent): m is GlanceMessageEvent & { fromKind: 'owner' | 'temper' } =>
  m.fromKind === 'owner' || m.fromKind === 'temper';

/**
 * D82: the corner's same-second batches that reach at least `min` members.
 * Each message id counts once; a receiver with no card (`members`, when
 * given) doesn't count, and a message with no time is never in a batch.
 */
export function hubBatches(
  messages: GlanceMessageEvent[],
  members: ReadonlySet<string> | null = null,
  min = HUB_BATCH_MIN,
): HubBatch[] {
  const batches = new Map<string, HubBatch>();
  const ids = new Set<string>();
  for (const m of [...messages].sort((a, b) => a.seq - b.seq)) {
    if (!isCorner(m) || (members !== null && !members.has(m.to))) continue;
    const second = (m.at ?? '').slice(0, 19);
    if (!second) continue;
    if (m.messageId !== null) {
      if (ids.has(m.messageId)) continue;
      ids.add(m.messageId);
    }
    let batch = batches.get(second);
    if (!batch) {
      batch = { second, parts: [], to: [], events: [] };
      batches.set(second, batch);
    }
    batch.events.push(m);
    if (!batch.to.includes(m.to)) batch.to.push(m.to);
    let part = batch.parts.find((p) => p.fromKind === m.fromKind);
    if (!part) {
      part = { fromKind: m.fromKind, to: [] };
      batch.parts.push(part);
    }
    if (!part.to.includes(m.to)) part.to.push(m.to);
  }
  return [...batches.values()].filter((b) => b.to.length >= min);
}

/** A sender's part in the cue's words (D82): "Temper \u2192 6 members", "You \u2192 1 member". */
export function hubPartWords(part: HubPart): string {
  const n = part.to.length;
  return `${whoName(null, part.fromKind)} \u2192 ${n} ${n === 1 ? 'member' : 'members'}`;
}

/** The batch `m` belongs to when it lights up, else null. */
function hubBatchOf(batches: HubBatch[], m: GlanceMessageEvent): HubBatch | null {
  return batches.find((b) => b.events.some((e) => e.seq === m.seq)) ?? null;
}

/**
 * The dots for newly released messages, in order: a same-second burst is
 * staggered 120 ms with at most 6 dots; the rest of a burst only adds to
 * the "+N more sent" count. One burst follows the last. Each message id
 * flies once (D6): a message seen twice in the batch gets one dot.
 *
 * With the map's drawn lines (`drawn`, pairKey keys), a dot between two
 * members runs only on a drawn line (D43): a message on a pair the map
 * doesn't draw joins "+N more sent", never a guessed line. You and
 * Temper's dots are not affected; a message with an end not on the team
 * has no dot and no count, as before (D33).
 */
export function dotPlan(messages: GlanceMessageEvent[], drawn?: ReadonlySet<string>, members?: ReadonlySet<string>): DotPlan {
  const dots: DotPlan['dots'] = [];
  const lights: DotPlan['lights'] = [];
  let extra = 0;
  let start = 0;
  // D82: with the members known, the corner's batches of three or more light up instead of flying.
  const lit = members ? hubBatches(messages, members) : [];
  const litSeqs = new Set(lit.flatMap((b) => b.events.map((e) => e.seq)));
  const bursts = new Map<string, GlanceMessageEvent[]>();
  const ids = new Set<string>();
  for (const m of [...messages].sort((a, b) => a.seq - b.seq)) {
    if (m.messageId !== null) {
      if (ids.has(m.messageId)) continue;
      ids.add(m.messageId);
    }
    const key = (m.at ?? '').slice(0, 19) || `seq-${m.seq}`;
    const list = bursts.get(key) ?? [];
    list.push(m);
    bursts.set(key, list);
  }
  // A member-to-member message between two cards on a pair the map doesn't draw.
  const undrawn = (m: GlanceMessageEvent) =>
    drawn !== undefined &&
    m.fromKind === 'member' &&
    m.from !== m.to &&
    (!members || (members.has(m.from) && members.has(m.to))) &&
    !drawn.has(pairKey(m.from, m.to));
  for (const [second, burst] of bursts) {
    const here = lit.filter((b) => b.second === second);
    here.forEach((batch) => lights.push({ batch, delay: start }));
    const rest = burst.filter((m) => !litSeqs.has(m.seq));
    const flying = rest.filter((m) => !undrawn(m));
    const shown = flying.slice(0, DOT_MAX_AT_ONCE);
    shown.forEach((event, i) => dots.push({ event, delay: start + i * DOT_STAGGER_MS }));
    extra += rest.length - shown.length;
    // A light-up takes a dot's time, so the next second's dots follow it.
    if (shown.length > 0 || here.length > 0) start += Math.max(0, shown.length - 1) * DOT_STAGGER_MS + DOT_MS;
  }
  return { dots, extra, lights };
}

// --- words for the newest message and the big moments ------------------------------------

export interface JustSent {
  from: string;
  to: string;
  /** The message's first line; null when only the links count says a message went (D3). */
  text: string | null;
  at: string | null;
  /**
   * Messages released in the same second as this one, itself included (D74: "N messages in the same
   * second, last: \u2026" when more than 1). 1 when it comes from `last_sent` or the links count.
   */
  burst: number;
  /**
   * D82: the sender (You or Temper) messaged this many members in that second, at least HUB_BATCH_MIN:
   * `to` then reads "6 members" and `burst` is 1 ("Temper \u2192 6 members: \u201c\u2026\u201d").
   */
  members?: number;
}

/** "Just sent" only while the newest message is at most this old, by Temper's clock (D22). */
export const JUST_SENT_MS = 60_000;

export interface SentLabel {
  /** "Just sent" (accent dot) or "Last message" (neutral dot). */
  label: 'Just sent' | 'Last message';
  /** "12 s ago"; "recorded at 3:00 PM" when it has no age; null with no time at all. */
  time: string | null;
}

/**
 * Design D22: "Just sent" only while the run goes on and the message is at
 * most 60 s old by Temper's clock. An ended run, an older message, or a time
 * that can't be compared says "Last message". A time after Temper's clock
 * has no age: it shows the time it records, never "0 s ago".
 *
 * On stale data (`stale`: the last read failed) nothing is green, so the
 * cue is never "Just sent" [D75]; `now` is then the device's present, and
 * the age counts to it [D64].
 */
export function sentLabel(
  sent: Pick<JustSent, 'at'>,
  phase: GlancePhaseName,
  now: number | null,
  stale = false,
): SentLabel {
  const at = msOf(sent.at);
  const age = at === null || now === null ? null : now - at;
  const fresh = age !== null && age >= 0 && age <= JUST_SENT_MS;
  const label = fresh && !stale && !phaseEnded(phase) ? 'Just sent' : 'Last message';
  if (age !== null && age >= 0) return { label, time: `${durationWords(age)} ago` };
  return { label, time: at === null ? null : `recorded ${atWords(sent.at, now)}` };
}

/**
 * A receiver as the "Just sent" line names it (Design D33). A supplied name
 * with no card on this run reads "Name (not on this team)" and an unnamed
 * one "someone not on this team": static words, never a guessed card or
 * route. You and Temper keep their own names. Without the run's members
 * the supplied name is kept as it is.
 */
export function receiverName(to: string | null | undefined, run?: { members: readonly { name: string }[] | null }): string {
  if (!to) return 'someone not on this team';
  if (to === 'owner' || to === 'temper') return whoName(to);
  if (run?.members && !run.members.some((m) => m.name === to)) return `${to} (not on this team)`;
  return to;
}

/**
 * "Just sent" (Design D3): the newest released message in the loaded feed;
 * else the newest member `last_sent` on the run reply; else the newest
 * links pair, in words without text. Null only when none of these exist,
 * so "No messages between members yet" never shows while the links count
 * messages. The receiver is named as receiverName says (D33).
 */
export function justSent(events: GlanceEvent[], run?: Pick<GlanceRun, 'members' | 'links'>): JustSent | null {
  let newest: GlanceMessageEvent | null = null;
  for (const e of events) if (e.kind === 'message' && (!newest || e.seq > newest.seq)) newest = e;
  if (newest) {
    const m = newest;
    // D82: the newest is You or Temper's, to three or more members in its second: name the batch.
    const batch = run ? hubBatchOf(hubBatches(messagesOf(events), new Set(run.members.map((x) => x.name))), m) : null;
    const part = batch?.parts.find((p) => p.fromKind === m.fromKind);
    if (part && part.to.length >= HUB_BATCH_MIN) {
      return { from: whoName(m.from, m.fromKind), to: `${part.to.length} members`, text: m.text, at: m.at, burst: 1, members: part.to.length };
    }
    return {
      from: whoName(m.from, m.fromKind),
      to: receiverName(m.to, run),
      text: m.text,
      at: m.at,
      burst: sameSecond(events, m),
    };
  }
  let sent: { from: string; s: GlanceSent } | null = null;
  for (const m of run?.members ?? []) {
    if (m.lastSent && (!sent || later(m.lastSent.at, sent.s.at))) sent = { from: m.name, s: m.lastSent };
  }
  if (sent) return { from: whoName(sent.from), to: receiverName(sent.s.to, run), text: sent.s.text, at: sent.s.at, burst: 1 };
  let link: GlanceLink | null = null;
  for (const l of run?.links ?? []) if (l.count > 0 && (!link || later(l.lastAt, link.lastAt))) link = l;
  return link ? { from: whoName(link.from), to: receiverName(link.to, run), text: null, at: link.lastAt, burst: 1 } : null;
}

/**
 * How many messages in the loaded feed were released in the same second as
 * `newest` (itself included), each message id once, as the dots group a
 * burst (dotPlan). 1 when its time isn't supplied.
 */
function sameSecond(events: GlanceEvent[], newest: GlanceMessageEvent): number {
  const second = (newest.at ?? '').slice(0, 19);
  if (!second) return 1;
  const ids = new Set<string>();
  let count = 0;
  for (const e of events) {
    if (e.kind !== 'message' || (e.at ?? '').slice(0, 19) !== second) continue;
    if (e.messageId !== null) {
      if (ids.has(e.messageId)) continue;
      ids.add(e.messageId);
    }
    count += 1;
  }
  return Math.max(1, count);
}

export interface MomentPart {
  text: string;
  strong?: boolean;
  /** S2: an exact supplied file name, rendered as literal React text in a code span. */
  code?: boolean;
}

/**
 * D85: an All activity row whose words are a cut of a longer text.
 * `whole`: the event holds the whole text (a share or idle note, an ended
 * reason: the row shows its first line), so the whole row is known.
 * `messageId`: a message's row shows Temper's first line of it (at most 120
 * characters); its whole body is read from Temper, and the row is a cut only
 * when the body says more (`messageWholeParts`). `lead` is the row's words
 * before the quoted text; `shown` the text the row quotes.
 */
export type MomentMore = { whole: MomentPart[] } | { messageId: string; lead: MomentPart[]; shown: string };

export interface Moment {
  key: string;
  at: string | null;
  icon: GlanceIcon | 'message' | 'share' | 'start' | 'conflict';
  parts: MomentPart[];
  /** D85: the row's words are (or may be) a cut; see MomentMore. */
  more?: MomentMore;
}

const q = (s: string) => `\u201c${s}\u201d`;

/** A text with more than its first line (the rest is cut from a row that shows the first line). */
function hasMoreThanFirstLine(s: string | null | undefined): s is string {
  return !!s && s.trim() !== firstLineOf(s);
}

/**
 * D85: a message row's whole words once its body is read: the row's lead,
 * then the whole body quoted. Null when the body says no more than the row
 * already shows (that row isn't cut, so it gets no Show all).
 */
export function messageWholeParts(more: { lead: MomentPart[]; shown: string }, body: string | null | undefined): MomentPart[] | null {
  const whole = (body ?? '').trim();
  if (!whole || whole === more.shown.trim()) return null;
  return [...more.lead, { text: `: ${q(whole)}` }];
}

const ENDED_LABELS: Record<string, string> = { done: 'Project ended', stopped: 'Stopped', cancelled: 'Cancelled', failed: 'Failed' };
const END_TOKENS: ReadonlySet<string> = new Set(['team_done', 'run_completed', 'team_stopped', 'run_cancelled']);

/** D118: an engine end token is not a human reason. Preserve every genuine reason. */
export function endReason(reason: string | null | undefined, whole = false): string | null {
  const s = whole ? (reason ?? '').trim() : firstLineOf(reason);
  const bare = s.toLowerCase().replace(/[\s.!?\u2026:;,]+$/, '');
  if (!bare || END_TOKENS.has(bare)) return null;
  return bare === 'account_refused' ? 'the model account refused a call.' : s;
}

/** D119/H17: Now preserves the whole genuine reason, changing only its initial letter; activity stays verbatim. */
function nowEndReason(reason: string | null | undefined): string | null {
  // Classify the whole reason, not its first line: a token followed by an explanation is genuine text.
  const classified = endReason(reason, true);
  // endReason trims for classification. Genuine text keeps every supplied character, including a final newline.
  const explanation = classified === reason?.trim() ? reason : classified;
  return explanation?.replace(/^./u, (first) => first.toUpperCase()) ?? null;
}

/**
 * Design SPEC's stopped row: Now gives the words given with the stop, under its sentence (stopped and failed runs
 * only). Shown, they make Temper's generic "the run was cancelled" (any case, end punctuation ignored) say nothing
 * more, so that sentence is left out, as D119 leaves out a generic reason; every other sentence stays.
 */
function withStopWords(run: Pick<GlanceRun, 'stopWords'>, cell: NowCell): NowCell {
  const words = run.stopWords;
  if (!words?.words.trim()) return cell;
  const generic = !!cell.sentence && /^the run was cancelled[\s.!?\u2026:;,]*$/i.test(cell.sentence.trim());
  return { ...cell, sentence: generic ? null : cell.sentence, words };
}

/** D119: any status in Temper's generic interruption template, case/end punctuation ignored, is no reason. */
export function interruptionReason(reason: string | null | undefined): string | null {
  const s = firstLineOf(reason);
  return !s || /^the run ended \([^)]+\) without the team ending[\s.!?\u2026:;,]*$/i.test(s) ? null : s;
}

/**
 * An ended row (D41): its label, then the reason's first line; a reason
 * that already starts with the label stands alone (no "Stopped: Stopped by you").
 */
export function endedWords(decision: string | null | undefined, reason: string | null | undefined, whole = false): string {
  const label = (decision && ENDED_LABELS[decision]) || 'Ended';
  // D85: `whole` gives the whole reason (the row's Show all).
  const why = endReason(reason, whole);
  if (!why) return decision === 'done' ? `${label}.` : label;
  return why.toLowerCase().startsWith(label.toLowerCase()) ? why : `${label}: ${why}`;
}
/**
 * The words for each answer Temper records (api-fields:260). Never a raw
 * code word: an answer not listed here shows as "<who> answered" alone.
 * `given`: the owner replied to a member's question (his words follow as an
 * owner_reply message), shown as the old `reply`. `invalid` has no words: the
 * answer named none of the choices.
 */
const ANSWER_WORDS: Record<string, string> = {
  continue: 'continue',
  guide: 'guide',
  stop: 'stop',
  nudge: 'nudge',
  accept: 'accept',
  retry: 'retry',
  'go on': 'go on',
  given: 'a reply',
  reply: 'a reply',
  // The choice made was Restart; its mark says it wasn't applied (D86).
  restart_deferred: 'restart',
};

/** D86 (Design's words, g6/TEMPER-D86.md): every mark starts "Not applied". */
export const NOT_APPLIED = {
  settingsLate: 'Not applied: the settings changed before the answer took effect.',
  invalid: 'Not applied: the answer didn\u2019t match any of the choices. Temper asked again.',
  restartDeferred: 'Not applied: Temper couldn\u2019t confirm the usage limit has reset.',
} as const;

type AnswerEvent = Extract<GlanceEvent, { kind: 'wait_answered' }>;

/** An answer's words, or null when the page has none for it. */
export function answerWord(answer: string): string | null {
  return Object.hasOwn(ANSWER_WORDS, answer) ? ANSWER_WORDS[answer] : null;
}

/**
 * D86: the line after an answer that wasn't applied. A settings go on is late
 * only when Temper says applied === false (never inferred from the next
 * settings question), in one fixed sentence whatever its why; any other
 * applied === false says "Not applied" with Temper's why when it gives one.
 */
export function answerMark(e: Pick<AnswerEvent, 'waitKind' | 'answer' | 'applied' | 'why'>): string | null {
  if (e.answer === 'invalid') return NOT_APPLIED.invalid;
  if (e.answer === 'restart_deferred') return NOT_APPLIED.restartDeferred;
  if (e.applied !== false) return null;
  if (e.waitKind === 'settings' && e.answer === 'go on') return NOT_APPLIED.settingsLate;
  const why = e.why?.trim();
  return why ? `Not applied: ${why}` : 'Not applied.';
}

/** The mark as its own part: after the answer, in normal (not muted) text (D86). */
function markParts(e: AnswerEvent): MomentPart[] {
  const mark = answerMark(e);
  return mark ? [{ text: `. ${mark}` }] : [];
}

/**
 * Latest's big moments (SPEC 8; Design's glance.mjs BIG): the start and work
 * requests, shares, the questions to you (a check-in's own row stands for its
 * wait) and their answers, check-ins, limits, conflicts, done and its refusals,
 * and an end other than done (whose Done row says it). A refused share is not
 * one: its row is in All activity, next to the conflict that is in Latest.
 */
function isBigMoment(e: GlanceEvent): boolean {
  switch (e.kind) {
    case 'message':
      return e.messageKind === 'goal' || e.messageKind === 'work_request';
    case 'wait_opened':
      return e.waitKind !== 'pause';
    case 'ended':
      return e.decision !== 'done';
    case 'share':
    case 'wait_answered':
    case 'check_in':
    case 'limit':
    case 'limit_over':
    case 'conflict':
    case 'done_refused':
    case 'closing':
    case 'done':
      return true;
    default:
      return false;
  }
}

/**
 * A big moment's row in Latest: All activity's words for the event, from the
 * one formatter (D110), so the two lists never word an event differently.
 * Latest keeps its own row keys and its alert icon on a refused done; a row
 * there is never opened (Show all is All activity's).
 */
function bigMoment(e: GlanceEvent, run: RowRun, liveLimit: boolean, extra: RowExtra): Moment | null {
  if (e.kind === 'wait_answered' && extra.pairedAnswers?.has(e.seq)) return null;
  if (!isBigMoment(e) && !(e.kind === 'message' && extra.answers?.has(e.seq))) return null;
  const row = activityRow(e, run, liveLimit, extra);
  return { key: `e${e.seq}`, at: row.at, icon: e.kind === 'done_refused' ? 'alert' : row.icon, parts: row.parts };
}

/**
 * D31: a limit's next allowance check is named (in Now, and in Latest's and
 * All activity's limit rows) only while the team is in its limit and neither
 * asked nor verified: a verified recovery shows its status and question,
 * never a pending check.
 */
export function limitCheckShown(phase: Pick<GlancePhase, 'name' | 'asked' | 'resumeVerified'>): boolean {
  return phase.name === 'limit' && !phase.asked && phase.resumeVerified !== true;
}

/**
 * Latest: big moments only, newest first. A same-second fan-out of work
 * requests from one member is one row ("lead sent work to 4 members"), and
 * so is You or Temper messaging three or more members in one second (D82:
 * "Temper sent a message to 6 members"). Plain info and reply messages, turn
 * starts and ends, idle and wake stay in the full list and on the map.
 * `liveLimit`: limitCheckShown(run.phase) (D31), so a limit row may name
 * its next check. `members`: the team's cards (a receiver with none doesn't
 * count towards D82's three). Each row's words are All activity's (D110):
 * `run` names the starter and the cards (without it, the cards in
 * `members`), `extra` gives Temper's clock (D104). The leader's name is no
 * longer used: the shared words never name the leader for a member Temper
 * left out ("The leader said done").
 */
export function latestMoments(
  events: GlanceEvent[],
  _leader: string,
  limit = 5,
  liveLimit = false,
  members: ReadonlySet<string> | null = null,
  run?: RowRun,
  extra: RowExtra = {},
): Moment[] {
  const rowRun: RowRun = run ?? { startedBy: null, members: members ? [...members].map((name) => ({ name })) : null };
  // D117: pair member answers once, with the same context and words in both lists.
  const rowExtra: RowExtra = { ...answerContext(events), ...extra };
  const momentOf = (e: GlanceEvent) => bigMoment(e, rowRun, liveLimit, rowExtra);
  const sorted = [...events].sort((a, b) => a.seq - b.seq);
  const out: Moment[] = [];
  // A sender's part of three or more is one row, where its first message is; its other messages
  // have none. A smaller part of a lit batch keeps its usual rows.
  const partRows = new Map<number, Moment>();
  const litSeqs = new Set<number>();
  for (const batch of hubBatches(messagesOf(sorted), members)) {
    for (const part of batch.parts) {
      if (part.to.length < HUB_BATCH_MIN) continue;
      const mine = batch.events.filter((e) => e.fromKind === part.fromKind);
      mine.forEach((e) => litSeqs.add(e.seq));
      partRows.set(mine[0].seq, {
        key: `hub${mine[0].seq}`,
        at: mine[0].at,
        icon: 'message',
        parts: [{ text: whoName(null, part.fromKind), strong: true }, { text: ` sent a message to ${part.to.length} members` }],
      });
    }
  }
  let fan: { from: string; second: string; first: GlanceMessageEvent; count: number } | null = null;
  const flush = () => {
    if (!fan) return;
    if (fan.count > 1) {
      out.push({
        key: `fan${fan.first.seq}`,
        at: fan.first.at,
        icon: 'message',
        parts: [{ text: whoName(fan.first.from, fan.first.fromKind), strong: true }, { text: ` sent work to ${fan.count} members` }],
      });
    } else {
      const m = momentOf(fan.first);
      if (m) out.push(m);
    }
    fan = null;
  };
  for (const e of sorted) {
    if (litSeqs.has(e.seq)) {
      flush();
      const row = partRows.get(e.seq);
      if (row) out.push(row);
      // The start keeps its own row.
      const start = e.kind === 'message' && e.messageKind === 'goal' ? momentOf(e) : null;
      if (start) out.push(start);
      continue;
    }
    if (e.kind === 'message' && e.messageKind === 'work_request') {
      const second = (e.at ?? '').slice(0, 19);
      if (fan && fan.from === e.from && fan.second === second && second !== '') {
        fan.count += 1;
        continue;
      }
      flush();
      fan = { from: e.from, second, first: e, count: 1 };
      continue;
    }
    // Wakes and turn starts come between a fan-out's messages: they don't break it.
    if (fan && (e.kind === 'wake' || e.kind === 'turn_start')) continue;
    flush();
    const m = momentOf(e);
    if (m) out.push(m);
  }
  flush();
  return out.reverse().slice(0, limit);
}

/** All activity's first page (SPEC 9): the 12 newest events, then "Show older (N)". */
export const ACTIVITY_FIRST = 12;

// The owner's messages have their own verbs (D108: answerSeqs); Temper sends no `owner` or `guide` kind (api-fields:248).
const MESSAGE_VERBS: Record<string, string> = {
  work_request: ' asked ',
  info: ' told ',
  reply: ' replied to ',
  notice: ' told ',
};

/** The run as a row's words need it: who started it, and the team's cards (a receiver with none is named so, D33). */
export interface RowRun {
  startedBy: string | null;
  starterTitle?: string | null;
  /** Null: the cards aren't known, so every receiver keeps its name. */
  members: readonly { name: string }[] | null;
}

/** What a row's words may need beyond its event and the run. */
export interface RowExtra {
  /** Temper's clock (D4): a future time in a row gets its day (D104). */
  now?: number | null;
  /** D108: the owner's messages that answer their receiver's question (answerSeqs of the loaded feed). */
  answers?: ReadonlySet<number>;
  /** D117: wait rows replaced by their owner's reply in both lists. */
  pairedAnswers?: ReadonlySet<number>;
  answerAskers?: ReadonlyMap<number, string>;
}

function fromOwner(e: GlanceMessageEvent): boolean {
  return e.fromKind === 'owner' || e.from === 'owner';
}

/** The answers that are the owner's reply to a member's question (`given`; `reply` before Oct 9, api-fields:260). */
const GIVEN_ANSWERS: ReadonlySet<string> = new Set(['given', 'reply']);

/**
 * D108: the owner's messages that answer a member's question. A message from
 * the owner to M answers when it pairs with an answer given to one of M's
 * own waits: the nearest earlier one, with no other message from the owner
 * to M between them. Every other one is a message ("You messaged M"),
 * a check-in guide's words to the leader too. A wait is M's own when its
 * answer, or the question it answers, names M as the member.
 */
export function answerSeqs(events: readonly GlanceEvent[]): Set<number> {
  return answerContext(events).answers;
}

/** D117: combine a recorded member-wait answer and its subsequent owner reply, never free messages or guides. */
function answerContext(events: readonly GlanceEvent[]) {
  const askers = new Map<string, string>();
  for (const e of events) if (e.kind === 'wait_opened' && e.waitId && e.member) askers.set(e.waitId, e.member);
  const pending = new Map<string, number>();
  const answers = new Set<number>();
  const pairedAnswers = new Set<number>();
  const answerAskers = new Map<number, string>();
  for (const e of [...events].sort((a, b) => a.seq - b.seq)) {
    if (e.kind === 'wait_answered') {
      const asker = isMemberQuestion(e.waitKind) ? (e.member ?? (e.waitId ? askers.get(e.waitId) : undefined)) : undefined;
      answerAskers.set(e.seq, asker ?? 'Temper');
      if (asker && GIVEN_ANSWERS.has(e.answer)) pending.set(asker, e.seq);
    } else if (e.kind === 'message' && fromOwner(e)) {
      const answer = pending.get(e.to);
      if (answer !== undefined) {
        pending.delete(e.to);
        answers.add(e.seq);
        pairedAnswers.add(answer);
      }
    }
  }
  return { answers, pairedAnswers, answerAskers };
}

/** Existing role title when known; otherwise the supplied id, never an invented actor. */
export function starterName(run: Pick<RowRun, 'startedBy' | 'starterTitle'>): string | null {
  return run.startedBy === 'owner' ? 'You' : run.startedBy ? (run.starterTitle || run.startedBy) : null;
}

/** D121: distinguish a recorded request from a successful start; omit absent attribution. */
export function starterAttribution(run: Pick<GlanceRun, 'startedBy' | 'starterTitle' | 'phase'>): string | null {
  const who = starterName(run);
  if (!who) return null;
  return run.phase.name === 'didnt_start' ? `Start requested by ${run.startedBy === 'owner' ? 'you' : who}` : `Started by ${who}`;
}

/** S2: exact supplied names, longest first, plain parts only; no markdown or link parser. */
export function fileNameParts(text: string, paths: readonly string[]): MomentPart[] {
  const names = [...new Set(paths.filter(Boolean))].sort((a, b) => b.length - a.length);
  const parts: MomentPart[] = [];
  let plain = '';
  for (let at = 0; at < text.length;) {
    const name = names.find((path) => text.startsWith(path, at));
    if (!name) { plain += text[at++]; continue; }
    if (plain) parts.push({ text: plain });
    plain = '';
    parts.push({ text: name, code: true });
    at += name.length;
  }
  if (plain) parts.push({ text: plain });
  return parts;
}

/** D107: a refused share's reason as Temper gives it; null when it gives none or only repeats the verb. */
const REFUSAL_VERBS: ReadonlySet<string> = new Set(['refused', 'share refused', 'share_refused']);

export function refusalWhy(why: string | null | undefined): string | null {
  const s = (why ?? '').trim();
  const bare = s.toLowerCase().replace(/[\s.!?\u2026:;,]+$/, '');
  return !bare || REFUSAL_VERBS.has(bare) ? null : s;
}

/** D106: a turn Temper ended at a cap; it gives no limit number (tool_calls counts the calls made, not the cap). */
const TURN_CAPS: Record<string, string> = {
  call_cap: 'its tool-call limit',
  time_limit: 'its time limit',
};

/**
 * One All activity row (SPEC 9; Design's eventRow in glance.mjs): every
 * event of the feed, one row per kind, in the event's own words. A row's
 * icon is the member state's own icon (D66, D77). `liveLimit`:
 * limitCheckShown(run.phase) (D31), so a limit row may name its next check;
 * an ended or verified hold has none (home decision 2, resumes_at null).
 *
 * D110: the one formatter of an event's words; Latest takes its rows' words
 * from here. A colon goes before quoted words.
 */
export function activityRow(e: GlanceEvent, run: RowRun, liveLimit = false, extra: RowExtra = {}): Moment {
  const key = `a${e.seq}`;
  const who = whoName(e.member);
  switch (e.kind) {
    case 'message': {
      if (e.messageKind === 'goal') {
        const by = starterName(run) ?? 'Someone';
        return {
          key,
          at: e.at,
          icon: 'start',
          parts: [{ text: by, strong: true }, { text: ' started the project; ' }, { text: whoName(e.to), strong: true }, { text: ' has the goal' }],
        };
      }
      // D108: the owner's words to a member answer its question, or are a message.
      const verb = fromOwner(e) ? (extra.answers?.has(e.seq) ? ' answered ' : ' messaged ') : (MESSAGE_VERBS[e.messageKind] ?? ' messaged ');
      const lead: MomentPart[] = [
        { text: whoName(e.from, e.fromKind), strong: true },
        { text: verb },
        { text: receiverName(e.to, run), strong: true },
      ];
      const shown = firstLineOf(e.text);
      return {
        key,
        at: e.at,
        icon: 'message',
        parts: [...lead, { text: shown ? `: ${q(shown)}` : '.' }],
        // D85: the feed carries Temper's first line of the message; its body may say more.
        ...(e.messageId ? { more: { messageId: e.messageId, lead, shown } } : {}),
      };
    }
    case 'share': {
      const lead: MomentPart[] = [
        { text: who, strong: true },
        { text: ' shared ' },
        { text: e.versionNo !== null ? `v${e.versionNo}` : 'a version', strong: true },
      ];
      return {
        key,
        at: e.at,
        icon: 'share',
        parts: [...lead, { text: e.note ? `: ${q(firstLineOf(e.note))}` : '' }],
        ...(hasMoreThanFirstLine(e.note) ? { more: { whole: [...lead, { text: `: ${q(e.note.trim())}` }] } } : {}),
      };
    }
    case 'conflict':
      return {
        key,
        at: e.at,
        icon: 'conflict',
        parts: [{ text: who, strong: true }, { text: ` has ${plural(e.paths, 'file', 'files')} in conflict after a ${e.atStep === 'share' ? 'share' : 'sync'}` }],
      };
    case 'share_refused': {
      // D114: reason is the explanation; why is the refusal kind. S2 keeps exact file names literal.
      const why = refusalWhy(e.reason === undefined && e.why !== 'conflict' ? e.why : e.reason);
      const paths = e.paths ?? [];
      const reason = why ?? (e.why === 'conflict' ? `it clashes with the shared version${paths.length === 1 ? ` in ${paths[0]}` : paths.length > 1 ? ` in ${paths.length} files` : ''}.` : null);
      return {
        key,
        at: e.at,
        icon: 'conflict',
        parts: [{ text: who, strong: true }, ...fileNameParts(reason ? `\u2019s version wasn\u2019t shared: ${reason}` : '\u2019s version wasn\u2019t shared. Temper gave no reason.', paths)],
      };
    }
    case 'idle':
      // D66, D77: waiting for the leader has the cards' clock; went idle the moon.
      return e.reason === 'start'
        ? { key, at: e.at, icon: 'clock', parts: [{ text: who, strong: true }, { text: ' waits for the leader' }] }
        : {
            key,
            at: e.at,
            icon: 'moon',
            parts: [{ text: who, strong: true }, { text: e.note ? ` went idle: ${q(firstLineOf(e.note))}` : ' went idle without a note' }],
            ...(hasMoreThanFirstLine(e.note) ? { more: { whole: [{ text: who, strong: true }, { text: ` went idle: ${q(e.note.trim())}` }] } } : {}),
          };
    case 'wake':
      return { key, at: e.at, icon: 'play', parts: [{ text: who, strong: true }, { text: ' woke up: a message from ' }, { text: e.by === 'owner' ? 'you' : whoName(e.by), strong: true }] };
    case 'turn_start': {
      const n = e.turnNo ?? '?';
      return {
        key,
        at: e.at,
        icon: 'play',
        parts: [{ text: who, strong: true }, { text: e.retryOf !== null ? ` started turn ${n} (Temper\u2019s retry of turn ${e.retryOf})` : ` started turn ${n}` }],
      };
    }
    case 'turn_end': {
      const icon = e.ended === 'failed' ? 'alert' : 'stop';
      const cap = e.endedBy ? TURN_CAPS[e.endedBy] : undefined;
      if (cap) return { key, at: e.at, icon, parts: [{ text: who, strong: true }, { text: `\u2019s turn ${e.turnNo ?? '?'} ended at ${cap}.` }] };
      if (e.ended === 'completed') return { key, at: e.at, icon, parts: [{ text: who, strong: true }, { text: ` finished turn ${e.turnNo ?? '?'}.` }] };
      // D118 changes completed turns; retain the existing words for other recorded turn outcomes.
      return { key, at: e.at, icon, parts: [{ text: who, strong: true }, { text: ` ended turn ${e.turnNo ?? '?'}: ${e.ended}${e.endedBy ? ` (${e.endedBy.replace(/_/g, ' ')})` : ''}` }] };
    }
    case 'wait_opened': {
      // D110: the asker is named: the member for its own question, Temper for its own waits.
      // D62: a member's own question keeps 160 characters in a row; Temper's words stay whole.
      const words = rowWords(e.waitKind, e.words);
      return {
        key,
        at: e.at,
        icon: 'hand',
        parts: [{ text: e.member ? who : 'Temper', strong: true }, { text: words ? ` asked you: ${q(words)}` : ' asked you' }],
      };
    }
    case 'wait_answered': {
      const word = answerWord(e.answer);
      const asker = extra.answerAskers?.get(e.seq) ?? (isMemberQuestion(e.waitKind) && e.member ? who : 'Temper');
      const reply = GIVEN_ANSWERS.has(e.answer);
      const mark = markParts(e);
      return {
        key,
        at: e.at,
        icon: 'check',
        parts: [{ text: e.by ? whoName(e.by) : 'Someone', strong: true }, { text: ' answered ' }, { text: asker, strong: true }, { text: reply || !word ? (mark.length ? '' : '.') : `: ${word}` }, ...mark],
      };
    }
    case 'check_in':
      return {
        key,
        at: e.at,
        icon: 'pause',
        parts: [{ text: 'Spend reached ' }, { text: e.atUsd !== null ? money(e.atUsd) : 'the check-in', strong: true }, { text: ': check-in. No new work starts.' }],
      };
    case 'limit': {
      // A historical limit event schedules a check, never automatic permission
      // (Design's row: "Usage limit: next allowance check at 07:00; no usable reset time").
      // The check time shows only while the team is in its limit phase: once the
      // hold is over there is no next check (Temper rm-d7e610c0). D104: after today it has its day.
      const at = liveLimit ? atWords(e.resumesAt, extra.now ?? null) : null;
      const text = at ? `Usage limit: next allowance check ${at}${e.resetsKnown === false ? '; no usable reset time' : ''}` : 'Usage limit';
      return { key, at: e.at, icon: 'clock', parts: [{ text }] };
    }
    case 'limit_over': {
      // D115: name the supplied restarter only, retaining D109 for older samples without it.
      const at = atWords(e.at, extra.now ?? null);
      const restart = e.by === 'owner' ? 'You restarted the team' : e.by === 'temper' ? 'Temper restarted the team' : 'The team carried on';
      return { key, at: e.at, icon: 'play', parts: [{ text: `The usage limit is over. ${restart}${at ? ` ${at}` : ''}.` }] };
    }
    case 'closing': {
      const summary = firstLineOf(e.summary);
      return {
        key,
        at: e.at,
        icon: 'flag',
        parts: [{ text: e.member ? who : 'The leader', strong: true }, { text: summary ? ` said done: ${q(summary)}` : ' said done' }],
      };
    }
    case 'done_refused':
      return { key, at: e.at, icon: 'conflict', parts: [{ text: e.reasons.length ? `Done refused: ${e.reasons.join('; ')}` : 'Done refused' }] };
    case 'done':
      return {
        key,
        at: e.at,
        icon: 'check',
        parts: [{ text: 'Done: ' }, { text: e.versionNo !== null ? `v${e.versionNo}` : 'the shared version', strong: true }, { text: ' is the result' }],
      };
    case 'ended':
      return {
        key,
        at: e.at,
        icon: e.decision === 'failed' ? 'alert' : 'stop',
        parts: [{ text: endedWords(e.decision, e.reason) }],
        ...(hasMoreThanFirstLine(e.reason) ? { more: { whole: [{ text: endedWords(e.decision, e.reason, true) }] } } : {}),
      };
    default:
      return { key, at: e.at, icon: 'circle', parts: [{ text: e.raw || 'event' }] };
  }
}

/** D105's reason row's key (it is no event of Temper's: All activity doesn't count it as an entry). */
export const REASON_ROW_KEY = 'reason';

/**
 * D105: an interrupted run's reason is always in All activity, as a final
 * row "Interrupted: <reason>", at phase.since when Temper gives it, otherwise
 * last of all and without a time. Stopped and failed runs keep theirs where
 * it shows already (Now's sentence, their ended row).
 */
export function reasonRow(phase: Pick<GlancePhase, 'name' | 'reason' | 'since'>): Moment | null {
  if (phase.name !== 'interrupted') return null;
  const reason = interruptionReason(phase.reason);
  if (!reason) return { key: REASON_ROW_KEY, at: phase.since, icon: 'alert', parts: [{ text: 'Interrupted. Temper gave no reason.' }] };
  return {
    key: REASON_ROW_KEY,
    at: phase.since,
    icon: 'alert',
    parts: [{ text: `Interrupted: ${reason}` }],
    ...(hasMoreThanFirstLine(phase.reason) ? { more: { whole: [{ text: `Interrupted: ${(phase.reason ?? '').trim()}` }] } } : {}),
  };
}

/**
 * All activity's rows (SPEC 9): every event, newest first, and D105's reason
 * row for an interrupted run: at its time among them, or first in the list
 * (last of all) without one. D108's answers are found in the loaded feed
 * unless `extra` gives them.
 */
export function activityRows(
  events: GlanceEvent[],
  run: RowRun & { phase?: Pick<GlancePhase, 'name' | 'reason' | 'since'> },
  liveLimit = false,
  extra: RowExtra = {},
): Moment[] {
  const rowExtra: RowExtra = { ...answerContext(events), ...extra };
  const rows = [...events].filter((e) => e.kind !== 'wait_answered' || !rowExtra.pairedAnswers?.has(e.seq)).sort((a, b) => b.seq - a.seq).map((e) => activityRow(e, run, liveLimit, rowExtra));
  const reason = run.phase ? reasonRow(run.phase) : null;
  if (!reason) return rows;
  const t = msOf(reason.at);
  const before = t === null ? 0 : rows.findIndex((r) => (msOf(r.at) ?? -Infinity) <= t);
  rows.splice(before === -1 ? rows.length : before, 0, reason);
  return rows;
}

/** Messages in a batch, for the dots (released ones only: every message event is a release). */
export function messagesOf(events: GlanceEvent[]): GlanceMessageEvent[] {
  return events.filter((e): e is GlanceMessageEvent => e.kind === 'message');
}
