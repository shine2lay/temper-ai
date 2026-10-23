/**
 * The one place that knows the Team API's field names for a free-flowing
 * team. It turns Temper's JSON (GET /api/team/runs/{id} and
 * GET /api/team/runs/{id}/events) into the typed glance model of
 * teamGlance.ts; every component reads that model, never raw fields.
 *
 * The names follow Temper's field list for free-flowing teams (FLOW
 * api-fields.md, 2026-10-09, including verified usage) and its real serializer replies (FLOW
 * #80, e2e/fixtures/team/flow/real/). If a name moves, this file is the only
 * one to change. Anything missing or of the wrong type reads as "not known"
 * (null, 0 or an empty list), never as a guess.
 */
import type { TeamOwnerAction } from '@/types/team';
import { phaseEnded } from './teamGlance';
import { teamStopper } from './teamOutcome';
import type {
  GlanceCounts,
  GlanceEvent,
  GlanceEventPage,
  GlanceIdleReason,
  GlanceLink,
  GlanceMember,
  GlanceMemberState,
  GlanceMessageFrom,
  GlancePhase,
  GlancePhaseName,
  GlanceQuestion,
  GlanceRun,
  GlanceShare,
  GlanceSpend,
  GlanceStopWords,
  GlanceUsage,
  GlanceUsageWindow,
} from './teamGlance';

type Raw = Record<string, unknown>;

const obj = (v: unknown): Raw | null => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Raw) : null);
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const str = (v: unknown): string | null => (typeof v === 'string' ? v : null);
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const bool = (v: unknown): boolean | null => (typeof v === 'boolean' ? v : null);
const firstLine = (s: string | null): string | null => {
  if (s === null) return null;
  const line = s.split('\n').find((l) => l.trim() !== '');
  return line ? line.trim() : null;
};

/** Temper's one-line rule for a question's words: its first sentence, at most 160 characters. */
const WORDS_MAX = 160;
function firstSentence(s: string | null): string | null {
  const line = firstLine(s);
  if (!line) return null;
  const end = line.search(/[.!?](\s|$)/);
  const sentence = end >= 0 ? line.slice(0, end + 1) : line;
  return sentence.length > WORDS_MAX ? `${sentence.slice(0, WORDS_MAX - 1).trimEnd()}\u2026` : sentence;
}

/** The run's kind: only `kind: "flow"` gets the glance page; anything else is an old round run. */
export function isFlowRun(raw: unknown): boolean {
  return obj(raw)?.kind === 'flow';
}

const PHASES: ReadonlySet<string> = new Set([
  'starting',
  'working',
  'closing',
  'check_in',
  'quiet',
  'limit',
  'settings',
  'waiting_for_owner',
  'draining',
  'done',
  'stopped',
  'failed',
  'didnt_start',
  'interrupted',
]);

const MEMBER_STATES: ReadonlySet<string> = new Set(['working', 'ready', 'idle', 'held', 'failed', 'ended']);
// Temper #115: git_refused is a rest Temper put the member in after refusing to run git over its folder.
const IDLE_REASONS: ReadonlySet<string> = new Set(['start', 'idle_call', 'no_tool_call', 'git_refused']);

function idleReason(v: unknown): GlanceIdleReason {
  const s = str(v);
  return s && IDLE_REASONS.has(s) ? (s as GlanceIdleReason) : null;
}

/** `phase.usage` (api-fields §3): null before a reading; `ok` with its windows; `unavailable` with a fixed reason code. */
function usageOf(v: unknown): GlanceUsage | null {
  const u = obj(v);
  if (!u) return null;
  const status = str(u.status);
  if (status === 'ok') {
    const windows: GlanceUsageWindow[] = arr(u.windows)
      .map(obj)
      .filter((w): w is Raw => w !== null && str(w.key) !== null)
      .map((w) => ({ key: str(w.key) as string, usedPercent: num(w.used_percent), resetsAt: str(w.resets_at) }));
    return { status, observedAt: str(u.observed_at), windows };
  }
  if (status === 'unavailable') return { status, reason: str(u.reason) };
  return { status: 'unknown' };
}

function phaseOf(v: unknown): GlancePhase {
  const p = obj(v) ?? {};
  const name = str(p.name);
  return {
    name: name && PHASES.has(name) ? (name as GlancePhaseName) : 'unknown',
    words: str(p.words),
    since: str(p.since),
    running: num(p.running) ?? 0,
    asked: bool(p.asked) ?? false,
    reason: str(p.reason),
    resumesAt: str(p.resumes_at),
    resetsKnown: bool(p.resets_known),
    resumeVerified: bool(p.resume_verified),
    usage: usageOf(p.usage),
    usageCheckedAt: str(p.usage_checked_at),
    blockedWindows: arr(p.blocked_windows).filter((k): k is string => typeof k === 'string'),
  };
}

/** Flow polling ends with its phase, including interrupted without an outcome. */
export function flowRunEnded(raw: unknown): boolean {
  return isFlowRun(raw) && phaseEnded(phaseOf(obj(raw)?.phase).name);
}

function spendOf(v: unknown, topCost: number | null): GlanceSpend | null {
  const s = obj(v);
  if (!s) return null;
  const cost = num(s.cost_usd) ?? topCost;
  const pauseEvery = num(s.pause_every_usd);
  if (cost === null || pauseEvery === null) return null;
  const lastCheckIn = num(s.last_check_in_usd) ?? 0;
  return {
    cost,
    pauseEvery,
    lastCheckIn,
    nextCheckIn: num(s.next_check_in_usd) ?? lastCheckIn + pauseEvery,
    sinceCheckIn: num(s.since_check_in_usd) ?? cost - lastCheckIn,
    checkIns: num(s.check_ins) ?? 0,
  };
}

function questionOf(v: unknown): GlanceQuestion | null {
  const q = obj(v);
  const waitId = str(q?.wait_id);
  if (!q || !waitId) return null;
  return {
    waitId,
    kind: str(q.kind) ?? 'question',
    member: str(q.member),
    header: str(q.header),
    words: firstLine(str(q.words)) ?? '',
    openedAt: str(q.opened_at),
  };
}

/**
 * Each open wait's own words, by wait id, for a held member's card (Design
 * D13): the wait's `words`; else `you.first.words` when it is the first
 * wait; else the first sentence of its question.
 */
function waitWordsOf(r: Raw): Map<string, string> {
  const first = obj(obj(r.you)?.first);
  const firstId = str(first?.wait_id);
  const firstWords = firstLine(str(first?.words));
  const out = new Map<string, string>();
  for (const w of arr(r.open_waits).map(obj)) {
    const id = str(w?.wait_id);
    if (!w || !id) continue;
    const words = firstLine(str(w.words)) ?? (id === firstId ? firstWords : null) ?? firstSentence(str(w.question));
    if (words) out.set(id, words);
  }
  if (firstId && firstWords && !out.has(firstId)) out.set(firstId, firstWords);
  return out;
}

/** One open wait's words, by the cards' rule, or null (All activity's question rows, D62). */
export function glanceWaitWords(raw: unknown, waitId: string | null | undefined): string | null {
  const r = obj(raw);
  if (!r || !waitId) return null;
  return waitWordsOf(r).get(waitId) ?? null;
}

/** Each open wait's kind, by wait id (a member's own question is `question`; D62 cuts only those). */
function waitKindsOf(r: Raw): Map<string, string> {
  const out = new Map<string, string>();
  for (const w of arr(r.open_waits).map(obj)) {
    const id = str(w?.wait_id);
    const kind = str(w?.kind);
    if (id && kind) out.set(id, kind);
  }
  const first = obj(obj(r.you)?.first);
  const firstId = str(first?.wait_id);
  const firstKind = str(first?.kind);
  if (firstId && firstKind && !out.has(firstId)) out.set(firstId, firstKind);
  return out;
}

function memberOf(v: unknown, waitWords: Map<string, string>, waitKinds: Map<string, string>): GlanceMember | null {
  const m = obj(v);
  const name = str(m?.name);
  if (!m || !name) return null;
  const state = str(m.state);
  const on = obj(m.on);
  const sent = obj(m.last_sent);
  const share = obj(m.last_share);
  const turn = obj(m.last_turn);
  const waitId = str(m.wait_id);
  const memberState: GlanceMemberState = state && MEMBER_STATES.has(state) ? (state as GlanceMemberState) : 'unknown';
  const tools = Array.isArray(m.tools_now)
    ? m.tools_now
        .map(obj)
        .filter((t): t is Raw => t !== null && str(t.name) !== null && num(t.count) !== null)
        .map((t) => ({ name: str(t.name) as string, count: num(t.count) as number }))
    : null;
  return {
    name,
    role: str(m.role) ?? '',
    leader: bool(m.leader) ?? false,
    state: memberState,
    since: str(m.since),
    turnNo: memberState === 'ended' ? null : num(m.turn_no),
    on:
      on && str(on.text)
        ? {
            kind: str(on.kind) ?? 'work_request',
            text: str(on.text) as string,
            from: str(on.from),
            to: str(on.to),
            at: str(on.at),
            messageId: str(on.message_id),
          }
        : null,
    idleNote: memberState === 'ended' ? null : str(m.idle_note),
    idleReason: memberState === 'ended' ? null : idleReason(m.idle_reason),
    toolsNow: memberState === 'ended' ? null : tools,
    readyMessages: num(m.ready_messages) ?? 0,
    lastSent:
      sent && str(sent.to) && str(sent.text)
        ? {
            to: str(sent.to) as string,
            kind: str(sent.kind) ?? 'info',
            text: str(sent.text) as string,
            at: str(sent.at),
            messageId: str(sent.message_id),
          }
        : null,
    lastShareNote: share ? str(share.note) : null,
    conflicts: arr(m.conflicts).length,
    waitId: memberState === 'ended' ? null : waitId,
    waitWords: memberState !== 'ended' && waitId ? (waitWords.get(waitId) ?? null) : null,
    waitKind: memberState !== 'ended' && waitId ? (waitKinds.get(waitId) ?? null) : null,
    turns: num(m.turns) ?? 0,
    turnsSupplied: num(m.turns) !== null,
    hasTurnHistory: turn !== null,
    cost: num(m.cost_usd),
    retryOf: num(turn?.retry_of),
    // Carried as Temper sends it; the card shows it while the turn has failed.
    lastError: str(turn?.error),
    // D105: when Temper last recorded this member's turn (its end, else its start).
    lastTurnAt: str(turn?.ended_at) ?? str(turn?.started_at),
  };
}

function countsOf(v: unknown, members: GlanceMember[]): GlanceCounts {
  const c = obj(v);
  const count = (s: GlanceMemberState) => members.filter((m) => m.state === s).length;
  return {
    // D63: a sentence built on Temper's own working count says nothing when it sent none.
    workingSupplied: num(c?.working) !== null,
    members: num(c?.members) ?? members.length,
    working: num(c?.working) ?? count('working'),
    ready: num(c?.ready) ?? count('ready'),
    idle: num(c?.idle) ?? count('idle'),
    held: num(c?.held) ?? count('held'),
    failed: num(c?.failed) ?? count('failed'),
    ended: num(c?.ended) ?? count('ended'),
  };
}

function shareOf(v: unknown): GlanceShare | null {
  const s = obj(v);
  const versionNo = num(s?.version_no);
  if (!s || versionNo === null) return null;
  return {
    versionNo,
    commitShort: str(s.commit_short) ?? (str(s.commit)?.slice(0, 12) ?? null),
    by: str(s.by),
    at: str(s.at),
    note: str(s.note),
    filesChanged: num(s.files_changed),
    filesTotal: num(s.files_total),
  };
}

/**
 * `outcome.owner_words`, the words given with the action that ended the run (a stop's reason), whole and as sent, and
 * who gave them: teamStopper's caller (the stopping owner action's `by`, else the outcome's), as the rounds outcome
 * card says it. Null when none were given (missing, empty or only blanks).
 */
function stopWordsOf(r: Raw): GlanceStopWords | null {
  const outcome = obj(r.outcome);
  const words = str(outcome?.owner_words);
  if (!outcome || !words?.trim()) return null;
  const actions: TeamOwnerAction[] = arr(r.owner_actions)
    .map(obj)
    .filter((a): a is Raw => a !== null)
    .map((a) => ({
      at: str(a.at) ?? '',
      kind: str(a.kind) ?? '',
      by: str(a.by),
      source: str(a.source),
      request_id: str(a.request_id),
      detail: { answer: str(obj(a.detail)?.answer) ?? undefined },
    }));
  const { by } = teamStopper({
    owner_actions: actions,
    outcome: {
      decision: str(outcome.decision) ?? 'stopped',
      reason: str(outcome.reason),
      owner_words: words,
      problems: [],
      by: str(outcome.by),
      at: str(outcome.at),
    },
  });
  return { words, by };
}

/** GET /api/team/runs/{id} of a free-flowing team, as the glance model. */
export function toGlanceRun(raw: unknown): GlanceRun {
  const r = obj(raw) ?? {};
  const trial = obj(r.trial) ?? {};
  const phase = phaseOf(r.phase);
  if (phase.name === 'didnt_start') {
    // D121: no diagnosis generated, no duplicate words. Missing is not loading.
    const supplied = (v: unknown) => { const s = str(v); return s?.trim() ? s : null; };
    phase.reason = supplied(phase.reason) ?? supplied(obj(r.outcome)?.reason) ??
      supplied(phase.words?.replace(/^Failed:/, '').trim()) ?? "The project couldn't start. Temper gave no reason.";
  }
  const waitWords = waitWordsOf(r);
  const waitKinds = waitKindsOf(r);
  const members = arr(r.members)
    .map((m) => memberOf(m, waitWords, waitKinds))
    .filter((m): m is GlanceMember => m !== null);
  const links: GlanceLink[] = arr(r.links)
    .map(obj)
    .filter((l): l is Raw => l !== null && str(l.from) !== null && str(l.to) !== null)
    .map((l) => ({ from: str(l.from) as string, to: str(l.to) as string, count: num(l.count) ?? 0, lastAt: str(l.last_at) }));
  const work = obj(r.work) ?? {};
  const shares = arr(work.shares)
    .map(shareOf)
    .filter((s): s is GlanceShare => s !== null);
  const you = obj(r.you);
  const project = obj(trial.project);
  return {
    executionId: str(r.execution_id) ?? '',
    goal: str(trial.goal) ?? '',
    leader: str(trial.leader) ?? members.find((m) => m.leader)?.name ?? '',
    startedAt: str(r.started_at) ?? str(trial.started_at),
    startedBy: str(trial.started_by),
    elapsedS: num(r.elapsed_s),
    lastActivityAt: str(r.last_activity_at),
    project: project ? str(project.source) : null,
    asOf: str(r.as_of),
    maxParallel: num(trial.max_parallel),
    phase,
    stopWords: stopWordsOf(r),
    spend: spendOf(r.spend, num(r.cost_usd)),
    you: { count: num(you?.count) ?? 0, first: questionOf(you?.first) },
    counts: countsOf(r.counts, members),
    members,
    links,
    work: {
      latest: shareOf(work.latest) ?? shares[0] ?? null,
      shares,
      total: num(work.shares_total) ?? shares.length,
      summary: str(work.summary),
    },
    // A position for after=, never a count: seq skips numbers and doesn't start at 1.
    eventsCursor: num(r.events_cursor) ?? 0,
    // The count; when Temper doesn't send it the page shows none (never the cursor or a page length).
    eventsTotal: num(r.events_total),
  };
}

const FROM_KINDS: ReadonlySet<string> = new Set(['member', 'owner', 'temper']);

/** One event of the feed, as the glance model; an unknown kind is kept as `other`. */
export function toGlanceEvent(raw: unknown): GlanceEvent | null {
  const e = obj(raw);
  const seq = num(e?.seq);
  const kind = str(e?.kind);
  if (!e || seq === null || !kind) return null;
  const base = { seq, at: str(e.at), member: str(e.member) };
  switch (kind) {
    case 'message': {
      const from = str(e.from);
      const to = str(e.to);
      if (!from || !to) return null;
      const fk = str(e.from_kind);
      return {
        ...base,
        kind,
        from,
        fromKind: fk && FROM_KINDS.has(fk) ? (fk as GlanceMessageFrom) : 'member',
        to,
        messageKind: str(e.message_kind) ?? 'info',
        text: firstLine(str(e.text)) ?? '',
        messageId: str(e.message_id),
      };
    }
    case 'turn_start':
      return { ...base, kind, turnNo: num(e.turn_no), retryOf: num(e.retry_of) };
    case 'turn_end':
      return {
        ...base,
        kind,
        turnNo: num(e.turn_no),
        ended: str(e.ended) ?? 'completed',
        endedBy: str(e.ended_by),
        cost: num(e.cost_usd),
        toolCalls: num(e.tool_calls),
      };
    case 'share':
      return {
        ...base,
        kind,
        versionNo: num(e.version_no),
        commitShort: str(e.commit_short),
        note: str(e.note),
        filesChanged: num(e.files_changed),
      };
    case 'share_refused':
      return {
        ...base,
        kind,
        why: firstLine(str(e.why)),
        reason: Object.hasOwn(e, 'reason') ? firstLine(str(e.reason)) : undefined,
        paths: arr(e.paths).filter((p): p is string => typeof p === 'string'),
        // Temper #115: why Temper refused to run git (planted, entries, ...); the reason's words already say it.
        cause: str(e.cause),
      };
    case 'sync_refused':
      // Temper #115: Temper refused to bring the team's latest work into the member's folder before a turn.
      return { ...base, kind, cause: str(e.cause), reason: firstLine(str(e.reason)) };
    case 'conflict':
      return { ...base, kind, paths: arr(e.paths).length, atStep: str(e.at_step) };
    case 'idle':
      return { ...base, kind, note: str(e.note), reason: idleReason(e.reason) };
    case 'wake':
      return { ...base, kind, by: str(e.by) };
    case 'closing':
      return { ...base, kind, summary: str(e.summary) };
    case 'done_refused':
      return {
        ...base,
        kind,
        reasons: arr(e.reasons)
          .map((x) => str(obj(x)?.words))
          .filter((w): w is string => w !== null),
      };
    case 'done':
      return { ...base, kind, summary: str(e.summary), versionNo: num(e.version_no), commitShort: str(e.commit_short) };
    case 'wait_opened':
      return {
        ...base,
        kind,
        waitId: str(e.wait_id),
        waitKind: str(e.wait_kind) ?? 'question',
        words: firstLine(str(e.words)),
      };
    case 'wait_answered':
      return {
        ...base,
        kind,
        waitId: str(e.wait_id),
        waitKind: str(e.wait_kind) ?? 'question',
        answer: str(e.answer) ?? '',
        by: str(e.by),
        // api-fields:260 (D86): a settings go on that came too late; only these fields say so.
        applied: bool(e.applied),
        why: str(e.why),
      };
    case 'check_in':
      return { ...base, kind, atUsd: num(e.at_usd) };
    case 'limit':
      return { ...base, kind, resumesAt: str(e.resumes_at), resetsKnown: bool(e.resets_known) };
    case 'limit_over':
      return { ...base, kind, by: str(e.by) };
    case 'limit_checked':
      // Temper's hidden bookkeeping for an allowance check: never a feed row,
      // a big moment or a reason to think the team may carry on.
      return null;
    case 'ended':
      return { ...base, kind, decision: str(e.decision) ?? 'stopped', reason: str(e.reason) };
    default:
      return { ...base, kind: 'other', raw: kind };
  }
}

/** The existing timeline carries a flow done event in its data (§7). */
export function toGlanceTimelineDone(raw: unknown): Extract<GlanceEvent, { kind: 'done' }> | null {
  const event = toGlanceEvent(obj(raw)?.data);
  return event?.kind === 'done' ? event : null;
}

/**
 * GET /api/team/runs/{id}/events?after=&limit=: the events, the cursor to ask
 * from next, whether more wait, and Temper's clock when it answered.
 */
export function toGlanceEventPage(raw: unknown, after: number): GlanceEventPage {
  const r = obj(raw) ?? {};
  const events = arr(r.events)
    .map(toGlanceEvent)
    .filter((e): e is GlanceEvent => e !== null);
  const newest = events.reduce((n, e) => Math.max(n, e.seq), after);
  return { events, cursor: num(r.cursor) ?? newest, more: bool(r.more) ?? false, asOf: str(r.as_of) };
}
