/**
 * The Team page's words and small rules, kept out of the components so
 * they can be tested on their own.
 *
 * Everything here reads the API's typed fields only: `event_type` is the
 * engine's own label and is never parsed.
 */
import { ensureUTC, formatCost } from '@/lib/utils';
import type { TeamOwnerAction, TeamRun, TeamState, TeamWait } from '@/types/team';

/** Which badge colours a state wears (Design's spec, section 9). */
export type TeamTone = 'pending' | 'running' | 'waiting' | 'interrupted' | 'completed' | 'cancelled' | 'failed';

export const TEAM_STATE_WORDS: Record<TeamState, string> = {
  starting: 'Starting',
  running: 'Running',
  paused: 'Paused',
  quiet: 'Quiet',
  member_waiting: 'Member waiting',
  settings_changed: 'Settings changed',
  interrupted: 'Interrupted',
  done: 'Done',
  stopped: 'Stopped',
  failed: 'Failed',
  didnt_start: "Didn't start",
};

export const TEAM_STATE_TONES: Record<TeamState, TeamTone> = {
  starting: 'pending',
  running: 'running',
  paused: 'waiting',
  quiet: 'waiting',
  member_waiting: 'waiting',
  settings_changed: 'waiting',
  interrupted: 'interrupted',
  done: 'completed',
  stopped: 'cancelled',
  failed: 'failed',
  didnt_start: 'pending',
};

export const TEAM_STATES = Object.keys(TEAM_STATE_WORDS) as TeamState[];

/** A state the server may add later still gets a badge: its own name, neutral. */
export function teamStateWord(state: string): string {
  return (TEAM_STATE_WORDS as Record<string, string>)[state] ?? state.replace(/_/g, ' ');
}

export function teamStateTone(state: string): TeamTone {
  return (TEAM_STATE_TONES as Record<string, TeamTone>)[state] ?? 'pending';
}

export const WAIT_STATES: ReadonlySet<string> = new Set(['paused', 'quiet', 'member_waiting', 'settings_changed']);
export const ENDED_STATES: ReadonlySet<string> = new Set(['done', 'stopped', 'failed', 'didnt_start']);

/** The run's own statuses that never change again. */
const FINAL_RUN_STATUSES: ReadonlySet<string> = new Set(['completed', 'failed', 'cancelled']);

/**
 * A run has ended once the team's outcome is written and the run itself is
 * over. Until then the view keeps reading it (an interrupted run can still
 * be resumed from the run page).
 */
export function teamRunEnded(run: Pick<TeamRun, 'outcome' | 'run_status'>): boolean {
  return run.outcome != null && FINAL_RUN_STATUSES.has(run.run_status);
}

// --- who --------------------------------------------------------------------

export type TeamWhoKind = 'owner' | 'named' | 'unknown';

export interface TeamWhoInfo {
  kind: TeamWhoKind;
  /** What the page writes: "You", the caller's name, or "unknown caller". */
  label: string;
}

/**
 * Who did something, from the server's `by` (or `answered_by`): the owner,
 * a named caller (a key with a name, such as temper-ci) or an unknown
 * caller. Missing means unknown: an action nobody can be named for must
 * stand out, never pass as the owner's.
 */
export function teamWho(by: string | null | undefined): TeamWhoInfo {
  const value = (by ?? '').trim();
  if (value === 'owner') return { kind: 'owner', label: 'You' };
  if (value === '' || value === 'unknown caller') return { kind: 'unknown', label: 'unknown caller' };
  return { kind: 'named', label: value };
}

/** The heading of an owner-words quote, by who wrote them. */
export function ownerWordsLabel(by: string | null | undefined): string {
  const who = teamWho(by);
  if (who.kind === 'owner') return 'Your words';
  if (who.kind === 'unknown') return 'Words from an unknown caller';
  return `${who.label}'s words`;
}

/**
 * Where an action came from, for display only (the stored value is kept).
 * The Team page and the run page are both the dashboard (Architecture,
 * decision A-9 on the Team page contract).
 */
export function teamSource(source: string | null | undefined): { table: string; inline: string } {
  switch (source) {
    case 'team_page':
    case 'run_page':
      return { table: 'Dashboard', inline: 'from the dashboard' };
    case 'chat':
      return { table: 'Chat', inline: 'from a chat' };
    case 'api':
      return { table: 'API', inline: 'through the API' };
    default:
      return { table: 'Unknown', inline: 'from an unknown place' };
  }
}

// --- what an owner action did (Who did what) ---------------------------------

/** "continue at the pause after round 3", "message to backend", ... */
export function ownerActionWhat(action: TeamOwnerAction, run?: Pick<TeamRun, 'timeline'>): string {
  const detail = action.detail ?? {};
  switch (action.kind) {
    case 'start':
      return 'started the trial';
    case 'message':
      return detail.to ? `message to ${detail.to}` : 'sent a message';
    case 'stop':
      return 'stopped the run';
    case 'answer': {
      const answer = detail.answer ?? 'answered';
      const wait = run ? findWait(run, detail.wait_id) : null;
      switch (detail.wait_kind) {
        case 'pause':
          return wait?.round != null ? `${answer} at the pause after round ${wait.round}` : `${answer} at the pause`;
        case 'stalled':
          return `${answer} when the team went quiet`;
        case 'recovery':
          return wait?.member
            ? `${answer} at ${wait.member} turn ${wait.turn_no ?? '?'}`
            : `${answer} at a member's turn`;
        case 'question':
          return wait?.member ? `reply to ${wait.member}'s question` : "reply to a member's question";
        case 'settings':
          return `${answer} at the settings check`;
        default:
          return answer;
      }
    }
    default:
      return action.kind.replace(/_/g, ' ');
  }
}

/** The owner_wait entry an answer was for: it carries the round, member and turn. */
function findWait(run: Pick<TeamRun, 'timeline'>, waitId: string | undefined) {
  if (!waitId) return null;
  for (const entry of run.timeline.entries) {
    if (entry.entry !== 'owner_wait') continue;
    const data = (entry.data ?? {}) as { wait_id?: string; round?: number | null; member?: string | null; turn_no?: number | null };
    if (data.wait_id === waitId) return data;
  }
  return null;
}

// --- text ---------------------------------------------------------------------

/** Characters as the server counts them: code points, so an emoji is one. */
export function countChars(text: string): number {
  return Array.from(text).length;
}

/** "keep going", "done": a decision as words. */
export function decisionWords(decision: string): string {
  return decision.replace(/_/g, ' ');
}

/**
 * The kind's title for a wait ("Paused after round 3", "backend's turn 4
 * failed", "qa asks you (turn 5)"). A recovery wait says how the turn
 * ended, from Temper's `why`: "failed" for a turn that failed, a usage
 * limit, or any other cut-off. Without a why (a closed wait, as the
 * timeline has it) it says only that the turn didn't finish. The card and
 * the timeline both name a wait by this.
 */
export function waitTitle(wait: Pick<TeamWait, 'kind' | 'round' | 'member' | 'turn_no'> & { why?: string | null }): string {
  switch (wait.kind) {
    case 'pause':
      return wait.round != null ? `Paused after round ${wait.round}` : 'Paused';
    case 'stalled':
      return 'Quiet: the team has nothing left to do';
    case 'recovery': {
      const who = wait.member ?? 'A member';
      const turn = wait.turn_no != null ? ` turn ${wait.turn_no}` : ' turn';
      const why = (wait.why ?? '').trim();
      // No why (a closed wait in the timeline): true for a failed turn and a cut-off one.
      if (why === '') return `${who}'s${turn} didn't finish`;
      if (why === 'failed') return `${who}'s${turn} failed`;
      if (why.startsWith('usage limit')) return `${who}'s${turn} was cut off by a usage limit`;
      return `${who}'s${turn} was cut off`;
    }
    case 'question':
      return `${wait.member ?? 'A member'} asks you${wait.turn_no != null ? ` (turn ${wait.turn_no})` : ''}`;
    case 'settings':
      return "A deploy changed the team's settings while it waited";
    default:
      return 'Temper is waiting for you';
  }
}

/**
 * The plain names of temper_ai/pi_agent/settings_wait.py (LABELS and
 * label()), first letter capitalized, so the "What changed" table, the
 * engine's question above it and the stop reason share one vocabulary.
 * A drift-guard test reads that file.
 */
const SETTING_LABELS: Readonly<Record<string, string>> = {
  pi_version: 'Pi version',
  image: 'Box image',
  provider: 'Provider',
  model: 'Model',
  thinking: 'Thinking',
  tools: 'Tools',
  route_host: 'Worker route',
  workflow: 'Workflow',
  agent_config_sha256: 'Agent config',
  cwd: 'Working folder',
  team: 'Team settings',
};

/**
 * A changed setting's name for the "What changed" table: "Model",
 * "Extension probe", "Add-on pi-tldr". A key with no plain name (a bare
 * extensions or add_ons key, or one Temper adds later) gives null: the
 * table then shows the engine's key as it is.
 */
export function settingLabel(key: string): string | null {
  const dot = key.indexOf('.');
  const head = dot < 0 ? key : key.slice(0, dot);
  const name = dot < 0 ? '' : key.slice(dot + 1);
  if (name && head === 'extensions') return `Extension ${name}`;
  if (name && head === 'add_ons') return `Add-on ${name}`;
  return Object.prototype.hasOwnProperty.call(SETTING_LABELS, key) ? SETTING_LABELS[key] : null;
}

/** "11 min ago", "just now", "2 h ago": how long a question has waited. */
export function agoWords(iso: string | null | undefined, now: number = Date.now()): string {
  const d = parse(iso);
  if (!d) return '';
  const minutes = Math.floor((now - d.getTime()) / 60_000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.floor(hours / 24);
  return `${days} ${days === 1 ? 'day' : 'days'} ago`;
}

const NUMBER = new Intl.NumberFormat('en-US');

export function formatNumber(n: number): string {
  return NUMBER.format(n);
}

/** "<n> / <limit>", and how far over when it is. */
export function charCount(text: string, limit: number): { used: number; over: number; label: string } {
  const used = countChars(text);
  const over = Math.max(0, used - limit);
  const base = `${formatNumber(used)} / ${formatNumber(limit)}`;
  return { used, over, label: over > 0 ? `${base} · ${formatNumber(over)} over` : base };
}

/** "$2.21"; nothing spent yet reads "$0.00" (the run page's format otherwise). */
export function teamCost(cost: number | null | undefined): string {
  return cost === 0 ? '$0.00' : formatCost(cost);
}

/** The first `n` characters of an id, as the boards show it. */
export function shortId(id: string | null | undefined, n = 8): string {
  return (id ?? '').slice(0, n);
}

/** The run's first line, for a title: the goal's first non-empty line. */
export function firstLine(text: string | null | undefined): string {
  const line = (text ?? '').split('\n').find((l) => l.trim() !== '');
  return (line ?? '').trim();
}

// --- times ----------------------------------------------------------------------

function parse(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  // Answers carry a zone; the caller's action rows are naive UTC. ensureUTC
  // reads a time without a zone as UTC.
  const d = new Date(ensureUTC(iso));
  return Number.isNaN(d.getTime()) ? null : d;
}

/** "10:42 AM" today, "Oct 4" on an earlier day (the title carries the full time). */
export function teamTime(iso: string | null | undefined, now: Date = new Date()): string {
  const d = parse(iso);
  if (!d) return '';
  if (d.toDateString() === now.toDateString()) {
    return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
  }
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

/** A list's time: "8:36 AM" today, "Oct 4, 11:02 PM" before (board T1). */
export function teamDateTime(iso: string | null | undefined, now: Date = new Date()): string {
  const d = parse(iso);
  if (!d) return '';
  const time = d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
  if (d.toDateString() === now.toDateString()) return time;
  return `${d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}, ${time}`;
}

/** What a failed read says: Temper's words, or the browser's when no answer came. */
export function readFailWords(err: unknown): string {
  if (err && typeof err === 'object' && 'status' in err && 'detail' in err) {
    const { status, detail } = err as { status: number; detail: unknown };
    if (typeof detail === 'string' && detail.trim() !== '') return detail;
    if (detail && typeof detail === 'object') {
      const d = detail as { problem?: unknown; message?: unknown };
      if (typeof d.problem === 'string' && d.problem) return d.problem;
      if (typeof d.message === 'string' && d.message) return d.message;
    }
    return `Temper answered ${status}`;
  }
  // fetch() itself failed: no reply came at all (board T3b).
  if (err instanceof TypeError && err.message) return `network error: ${err.message}`;
  if (err instanceof Error && err.message) return err.message;
  return "Temper didn't answer";
}

/** The full date, time and zone, for a title attribute. */
export function teamTimeFull(iso: string | null | undefined): string {
  const d = parse(iso);
  if (!d) return '';
  return d.toLocaleString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
    timeZoneName: 'short',
  });
}

/** "10:42:05 AM": when the page last heard from Temper. */
export function clockTime(ms: number): string {
  return new Date(ms).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', second: '2-digit', hour12: true });
}

/** ISO for a <time dateTime>, or undefined. */
export function isoOf(iso: string | null | undefined): string | undefined {
  return parse(iso)?.toISOString();
}

// --- messages ---------------------------------------------------------------------

/** The kind chip of a message ("work request", "from you"). */
export function messageKindWord(kind: string, fromOwner: boolean): string {
  if (fromOwner || kind === 'owner_reply') return 'from you';
  return kind.replace(/_/g, ' ');
}

/** Where a message is: delivered, waiting for the next turn, held or not delivered. */
export function messageStateWords(state: string, undelivered?: string | null): string {
  switch (state) {
    case 'consumed':
      return 'delivered';
    case 'pending':
      return 'waiting for the next turn';
    case 'held':
      return 'held until you answer';
    case 'undelivered':
      return undelivered ? `not delivered: ${undelivered.replace(/_/g, ' ')}` : 'not delivered';
    default:
      return state.replace(/_/g, ' ');
  }
}
