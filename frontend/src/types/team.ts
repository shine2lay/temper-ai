/**
 * The Team page API (/api/team/*), as the server answers today.
 *
 * Written from the routes' own responses (docs/pi-team-api.md and the
 * captured fixtures in e2e/fixtures/team/). Fields the page never reads
 * are left out; anything the server may send as null is typed so.
 */

/** The eleven states of a team run, chosen by the server (team_run.state). */
export type TeamState =
  | 'starting'
  | 'running'
  | 'paused'
  | 'quiet'
  | 'member_waiting'
  | 'settings_changed'
  | 'interrupted'
  | 'done'
  | 'stopped'
  | 'failed'
  | 'didnt_start';

export type TeamGuardMode = 'off' | 'record' | 'enforce';

export interface TeamLimits {
  goal_max_chars: number;
  message_max_chars: number;
  guide_max_chars: number;
  reply_max_chars: number;
  nudge_max_chars: number;
  stop_reason_max_chars: number;
  name_pattern: string;
  reserved_names: string[];
}

export interface TeamStatus {
  api_version: string;
  roles_configured: boolean;
  roles_problem: string | null;
  defaults: { provider: string; model: string; thinking: string; source: string };
  tools: {
    available: string[];
    default: string[];
    source: string;
    bash_allowed: boolean;
    bash_why: string | null;
  };
  communication: { available: string[]; later: string[] };
  limits: TeamLimits;
  project_roots: string[];
  project_problems: unknown[];
  guard_mode: TeamGuardMode;
}

export interface TeamTrialMember {
  name: string;
  role: string;
  tools: string[];
  leader: boolean;
}

export interface TeamTrial {
  goal: string;
  leader: string;
  members: TeamTrialMember[];
  pause_after_rounds: number;
  communication: string;
  project: { source: string | null; start_commit: string | null } | null;
  started_at: string | null;
  started_by?: string | null;
  request_id?: string | null;
}

export interface TeamTurn {
  turn_no: number;
  state: string;
  started_at: string | null;
  ended_at: string | null;
  error: string | null;
}

export interface TeamMember {
  name: string;
  role: string;
  leader: boolean;
  /** idle, working, waiting_on_owner, failed or ended; shown as the server says. */
  activity: string;
  turns: number;
  cost_usd: number | null;
  model: string | null;
  thinking: string | null;
  effective: { model: string | null; thinking: string | null } | null;
  last_turn: TeamTurn | null;
}

export interface TeamAnswerOption {
  answer: string;
  needs_text: 'none' | 'required' | 'optional';
  means: string;
}

/**
 * One changed setting at a settings wait (contract E24): typed, never parsed
 * from the question. value_kind sha256 holds full 64-hex digests.
 */
export interface TeamSettingsChange {
  scope: 'team' | 'member' | string;
  /** The member's team name; null for the whole team. */
  member: string | null;
  /** The engine's key id: model, image, extensions.<name>, add_ons.<name>... */
  key: string;
  value_kind: 'text' | 'sha256' | string;
  old: string | null;
  new: string | null;
}

/** A member's settings fingerprint before and after (full 64-hex digests). */
export interface TeamSettingsPin {
  member: string;
  pin_old: string | null;
  pin_new: string | null;
}

export interface TeamWait {
  wait_id: string;
  asked: boolean;
  kind: 'pause' | 'stalled' | 'recovery' | 'question' | 'settings' | string;
  header: string | null;
  question: string | null;
  answers: TeamAnswerOption[];
  round: number | null;
  member: string | null;
  turn_no: number | null;
  why: string | null;
  asked_again: number | null;
  opened_at: string | null;
  /** Only on a settings wait; null for every other kind. */
  settings_changes?: TeamSettingsChange[] | null;
  pins?: TeamSettingsPin[] | null;
}

export interface TeamView {
  verdict: string;
  note: string | null;
}

export interface TeamReview {
  review_id: string;
  round: number;
  state: string;
  commit: string | null;
  files_count: number | null;
  views: Record<string, TeamView>;
  decision: string | null;
  refusal: string | null;
  summary: string | null;
}

/** Fields every timeline entry has; the page reads the typed ones only. */
interface TeamEntryBase {
  /** The engine's own label. Never parsed: the typed fields say what it is. */
  event_type: string;
  from_agent: string | null;
  to_agent?: string | null;
  /** Missing on a few entries (a stop's decision). */
  timestamp?: string | null;
  round?: number | null;
}

export interface TeamMessageEntry extends TeamEntryBase {
  entry: 'message';
  message_kind: string;
  data: {
    message_id: string;
    state: string;
    deliveries?: number;
    review_id?: string | null;
    undelivered?: string | null;
    preview?: string | null;
  };
}

export interface TeamReviewRoundEntry extends TeamEntryBase {
  entry: 'review_round';
  data: {
    review_id: string;
    state?: string;
    commit?: string | null;
    files?: Record<string, string> | null;
  };
}

export interface TeamViewEntry extends TeamEntryBase {
  entry: 'view';
  data: { review_id: string; verdict: string; note?: string | null };
}

/**
 * A leader's decision. A refused done comes as decision keep_going whose
 * review (data.review_id) reads done_refused with Temper's refusal: see
 * lib/teamReview.ts. The entry itself never carries the refusal.
 */
export interface TeamDecisionEntry extends TeamEntryBase {
  entry: 'decision';
  decision: string;
  data: { review_id?: string; summary?: string | null; reason?: string | null };
}

export interface TeamOwnerWaitEntry extends TeamEntryBase {
  entry: 'owner_wait';
  wait_kind: string;
  data: {
    wait_id: string;
    state?: string;
    round?: number | null;
    header?: string | null;
    answer?: string | null;
    member?: string | null;
    turn_no?: number | null;
  };
}

export interface TeamOwnerAnswerEntry extends TeamEntryBase {
  entry: 'owner_answer';
  wait_kind: string;
  answered_by: string | null;
  answered_source: string | null;
  request_id?: string | null;
  /** applied false: a settings go on that came too late (a new settings wait opened). */
  data: { wait_id: string; answer: string; applied?: boolean };
}

export interface TeamMemberTurnEntry extends TeamEntryBase {
  entry: 'member_turn';
  data: {
    turn_id?: string;
    turn_no: number;
    state: string;
    ended_at?: string | null;
    error?: string | null;
  };
}

/** An entry type the page doesn't know yet: shown as one plain line. */
export interface TeamOtherEntry extends TeamEntryBase {
  entry: string;
  data?: Record<string, unknown>;
}

export type TeamEntry =
  | TeamMessageEntry
  | TeamReviewRoundEntry
  | TeamViewEntry
  | TeamDecisionEntry
  | TeamOwnerWaitEntry
  | TeamOwnerAnswerEntry
  | TeamMemberTurnEntry;

export interface TeamOwnerAction {
  at: string;
  kind: 'start' | 'answer' | 'message' | 'stop' | string;
  by: string | null;
  source: string | null;
  request_id: string | null;
  detail: {
    to?: string;
    message_id?: string;
    wait_id?: string;
    wait_kind?: string;
    answer?: string;
    workflow?: string;
    trial_id?: string;
    /** A stop's own words (the person's reason). */
    reason?: string;
  } | null;
}

/** The branch made for an approved version (null when the trial had no project). */
export interface TeamBranch {
  name: string;
  made: boolean;
  /** Why it wasn't made, in Temper's words ('exists', 'denied: ...'). */
  why: string | null;
}

export interface TeamObjection {
  member: string;
  verdict: string;
  note: string | null;
  view_round?: number | null;
}

/** What a done outcome carries: the approved version. */
export interface TeamDone {
  review_id: string;
  round: number;
  commit: string | null;
  commit_short?: string | null;
  summary: string | null;
  files: Array<{ path: string; sha256?: string | null }>;
  objections: TeamObjection[];
  branch: TeamBranch | null;
  rounds: number | null;
  cost_usd: number | null;
}

export interface TeamOutcome {
  /** done, stopped, cancelled, failed or didnt_start. */
  decision: string;
  reason: string | null;
  owner_words: string | null;
  problems: unknown[];
  by: string | null;
  at: string | null;
  done?: TeamDone | null;
}

export interface TeamRun {
  execution_id: string;
  trial_id: string;
  workflow: string;
  /** The run's own status, as the run list shows it. */
  run_status: string;
  state: TeamState;
  cost_usd: number | null;
  trial: TeamTrial;
  round: { current: number; keep_goings: number; pause_after_rounds: number };
  members: TeamMember[];
  open_waits: TeamWait[];
  reviews: TeamReview[];
  timeline: { entries: Array<TeamEntry | TeamOtherEntry>; not_shown: number };
  owner_actions: TeamOwnerAction[];
  outcome: TeamOutcome | null;
}

/** What POST .../waits/{wait_id}/answer sends. */
export interface TeamAnswerRequest {
  /** One per answer, the same on a retry: Temper counts it once. */
  request_id: string;
  answer: string;
  text: string;
}

/** Temper's 200 to an answer. */
export interface TeamAnswerResult {
  status: string;
  wait_id: string;
  answer: string;
  text: string | null;
  /** The same request had already reached Temper; it counted once. */
  repeated: boolean;
  carries_on: boolean;
  /** Kept, but the run isn't running: it needs Resume on the run page. */
  needs_resume: boolean;
  /** Temper's own words when the answer needs Resume. */
  message?: string | null;
  by: string | null;
  at: string | null;
}

/** A 409 to an answer: the question was already settled, and by whom. */
export interface TeamAnswerConflict {
  reason: string;
  message: string;
  answered_by?: string | null;
  answered_at?: string | null;
  answered_source?: string | null;
}

/** Temper's 200 to Stop run: the run's own status after the stop. */
export interface TeamCancelResult {
  status: string;
  execution_id: string;
}

/** A problem or note from the check or a start: placed by field and member, never by its text. */
export interface TeamFinding {
  /** goal, members, leader, pause_after_rounds, communication, project_path; null for the whole request. */
  field: string | null;
  /** The member's team name as sent, for a members problem about one member. */
  member?: string | null;
  text: string;
}

/** POST /api/team/check: every check a start makes; nothing is written. */
export interface TeamCheckResult {
  ok: boolean;
  problems: TeamFinding[];
  notes: TeamFinding[];
}

/** One member as the form sends it. A name left empty is not sent: the server uses the role id. */
export interface TeamTrialMemberInput {
  role: string;
  name?: string;
  tools: string[];
}

/** What POST /api/team/trials (and /check, without request_id) sends. */
export interface TeamTrialInput {
  goal: string;
  members: TeamTrialMemberInput[];
  leader: string;
  /** As typed: a number, or null when the field is empty (the server says what's wrong). */
  pause_after_rounds: number | null;
  communication: string;
  project_path: string | null;
}

export interface TeamTrialRequest extends TeamTrialInput {
  /** One per submission, the same on a retry: Temper counts it once. */
  request_id: string;
}

/** Temper's 201 to a trial start. */
export interface TeamTrialStarted {
  trial_id: string;
  execution_id: string;
  status: string;
  workflow: string;
  repeated: boolean;
  notes: TeamFinding[];
}

/** One run of a trial's workflow in GET /api/team/trials (its own run, a re-run or a fork). */
export interface TeamTrialItem {
  trial_id: string;
  execution_id: string;
  workflow: string;
  goal_first_line: string;
  leader: string | null;
  members: Array<{ name: string; role: string }>;
  state: TeamState | string;
  /** The run list's own status for this run. */
  run_status: string | null;
  decision: string | null;
  /** 0 before the first review round. */
  round: number;
  cost_usd: number | null;
  started_at: string | null;
  started_by: string | null;
  ended_at: string | null;
}

export interface TeamTrialsPage {
  total: number;
  trials: TeamTrialItem[];
}

export interface TeamRole {
  id: string;
  title: string | null;
  /** The role's about.md, untrusted: shown as markdown, never as HTML. */
  about: string | null;
  has_home_chat: boolean;
  /** Why it can't join a team, word for word; empty when it can. */
  problems: string[];
}

export interface TeamRoles {
  configured: boolean;
  problem: string | null;
  roles: TeamRole[];
}

/** What POST /api/team/runs/{id}/messages sends. */
export interface TeamMessageRequest {
  request_id: string;
  to: string;
  body: string;
}

/** Temper's 201 to a message: pending (next turn) or held (after the open wait). */
export interface TeamMessageSent {
  message_id: string;
  to: string;
  state: 'pending' | 'held' | string;
  delivers: 'next_turn' | 'after_open_wait' | string;
  repeated: boolean;
  by: string | null;
  at: string | null;
}

export interface TeamMessage {
  message_id: string;
  from: string;
  to: string;
  kind: string;
  state: string;
  undelivered_reason: string | null;
  review_id: string | null;
  body: string;
  created_at: string | null;
  delivered_at: string | null;
}
