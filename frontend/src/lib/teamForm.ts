/**
 * The New trial form (Design's SPEC 3, boards F1-F5, S1, S2, S6).
 *
 * The form checks nothing itself except the character counts: Check and
 * Run trial ask the server, the one place the rules live. Its problems and
 * notes are placed by their field and member (contract E20), never by
 * their text, and shown word for word.
 */
import { TeamApiError } from '@/lib/teamApi';
import { refusalWords } from '@/lib/teamAnswer';
import type { TeamCheckResult, TeamFinding, TeamStatus, TeamTrialInput, TeamTrialStarted } from '@/types/team';

/** A team has 1 to 6 members (SPEC 3). */
export const TEAM_MAX_MEMBERS = 6;

/** Used only when Temper's status doesn't say. */
export const FALLBACK_TOOLS = ['Read', 'Grep', 'Glob', 'Edit', 'Write'];

/** One member row as the owner fills it in. */
export interface FormMember {
  /** The row's own id on the page; never sent. */
  key: string;
  /** The picked role id; '' until one is picked. */
  role: string;
  /** The team name as typed. */
  name: string;
  /** True once the owner typed in the name: picking a role then leaves it alone. */
  named: boolean;
  tools: string[];
}

export interface TrialForm {
  goal: string;
  members: FormMember[];
  /** The leader row's key. */
  leader: string;
  /** The pause field as typed: '' when empty. There is no default. */
  pause: string;
  communication: string;
  project: string;
}

let rowCount = 0;

/** A new, empty member row with Temper's default tools. */
export function newMember(status: Pick<TeamStatus, 'tools'> | null, key?: string): FormMember {
  rowCount += 1;
  return { key: key ?? `m${rowCount}`, role: '', name: '', named: false, tools: [...(status?.tools.default ?? FALLBACK_TOOLS)] };
}

/** The empty form (board F1): one member, who leads; no pause; all can message all. */
export function emptyForm(status: Pick<TeamStatus, 'tools' | 'communication'> | null): TrialForm {
  const first = newMember(status);
  return {
    goal: '',
    members: [first],
    leader: first.key,
    pause: '',
    communication: status?.communication.available[0] ?? 'all',
    project: '',
  };
}

/**
 * Picks a role for a row. The team name follows the role (its id) until the
 * owner types one, except for a reserved name such as temper, which has no
 * default: the name is left for the owner to fill (board F2).
 */
export function pickRole(member: FormMember, role: string, reserved: readonly string[]): FormMember {
  if (member.named) return { ...member, role };
  return { ...member, role, name: isReserved(role, reserved) ? '' : role };
}

export function isReserved(name: string, reserved: readonly string[]): boolean {
  const lower = name.trim().toLowerCase();
  return lower !== '' && reserved.some((r) => r.toLowerCase() === lower);
}

/** Whether the row shows the F2 hint: its role's name is reserved and the name was left empty. */
export function reservedHint(member: FormMember, reserved: readonly string[]): boolean {
  return !member.named && member.name === '' && isReserved(member.role, reserved);
}

/** The F2 hint under such a row's team name. */
export function reservedWords(role: string): string {
  return `'${role}' is a reserved name, so the team name is left for you to fill.`;
}

/** A member's team name as Temper will see it: the name typed, else the role id. */
export function teamNameOf(member: Pick<FormMember, 'role' | 'name'>): string {
  return member.name.trim() || member.role.trim();
}

/**
 * What Check and Run trial send. Names go as typed (left out when empty:
 * Temper then uses the role id); an empty pause field goes as null, so
 * Temper says what's missing.
 */
export function trialInput(form: TrialForm): TeamTrialInput {
  const leader = form.members.find((m) => m.key === form.leader);
  return {
    goal: form.goal,
    members: form.members.map((m) => ({
      role: m.role,
      ...(m.name.trim() !== '' ? { name: m.name } : {}),
      tools: [...m.tools],
    })),
    leader: leader ? teamNameOf(leader) : '',
    pause_after_rounds: form.pause.trim() === '' ? null : Number(form.pause),
    communication: form.communication,
    project_path: form.project === '' ? null : form.project,
  };
}

/** Each row's team name as sent, to place the answer's member problems. */
export interface SentRow {
  key: string;
  name: string;
}

export function sentRows(form: TrialForm): SentRow[] {
  return form.members.map((m) => ({ key: m.key, name: teamNameOf(m) }));
}

/** The form's places a problem or note can sit, besides a member row. */
export type FormField = 'goal' | 'pause_after_rounds' | 'communication' | 'project_path' | 'members';

export type Place = { kind: 'field'; field: FormField } | { kind: 'row'; key: string } | { kind: 'top' };

/**
 * Where a problem or note goes, from its field and member only (SPEC 3,
 * contract E20): goal, pause, communication and project under their
 * field; leader, and members without a member (or a name not on the page),
 * in the Members section's own list; a member's problem at the foot of the
 * row whose team name it names; anything else (field null: roles, safety)
 * in the top list only.
 */
export function placeFinding(finding: Pick<TeamFinding, 'field' | 'member'>, rows: readonly SentRow[]): Place {
  switch (finding.field) {
    case 'goal':
    case 'pause_after_rounds':
    case 'communication':
    case 'project_path':
      return { kind: 'field', field: finding.field };
    case 'leader':
      return { kind: 'field', field: 'members' };
    case 'members': {
      const row = finding.member != null ? rows.find((r) => r.name === finding.member) : undefined;
      return row ? { kind: 'row', key: row.key } : { kind: 'field', field: 'members' };
    }
    default:
      return { kind: 'top' };
  }
}

export interface PlacedFinding {
  finding: TeamFinding;
  place: Place;
}

export interface PlacedFindings {
  /** Every one, in Temper's order, with its place. */
  all: PlacedFinding[];
  fields: Record<FormField, TeamFinding[]>;
  rows: Record<string, TeamFinding[]>;
}

export function placeFindings(findings: readonly TeamFinding[], rows: readonly SentRow[]): PlacedFindings {
  const placed: PlacedFindings = {
    all: [],
    fields: { goal: [], pause_after_rounds: [], communication: [], project_path: [], members: [] },
    rows: {},
  };
  for (const finding of findings) {
    const place = placeFinding(finding, rows);
    placed.all.push({ finding, place });
    if (place.kind === 'field') placed.fields[place.field].push(finding);
    if (place.kind === 'row') (placed.rows[place.key] ??= []).push(finding);
  }
  return placed;
}

/** The element a place's link goes to (null: the top list only, no link). */
export function placeAnchor(place: Place): string | null {
  if (place.kind === 'top') return null;
  if (place.kind === 'row') return memberAnchor(place.key);
  return FIELD_ANCHORS[place.field];
}

/** The ids a field's problems and notes carry, for its aria-describedby. */
export function findingIds(id: string, problems: readonly TeamFinding[], notes: readonly TeamFinding[]): string[] {
  return [...problems.map((_, i) => `${id}-problem-${i}`), ...notes.map((_, i) => `${id}-note-${i}`)];
}

/**
 * Moves to a field from a problem's link: scrolls it into view and focuses
 * it. Returns whether it found the field (the link's own jump is kept when not).
 */
export function goToAnchor(anchor: string): boolean {
  const target = document.getElementById(anchor);
  if (!target) return false;
  target.scrollIntoView?.({ block: 'center' });
  target.focus({ preventScroll: true });
  return true;
}

export const FIELD_ANCHORS: Record<FormField, string> = {
  goal: 'team-goal',
  pause_after_rounds: 'team-pause',
  communication: 'team-communication',
  project_path: 'team-project',
  members: 'team-members-problems',
};

export function memberAnchor(key: string): string {
  return `team-member-${key}`;
}

/** "2 problems" / "1 problem". */
export function problemCount(n: number): string {
  return `${n.toLocaleString('en-US')} ${n === 1 ? 'problem' : 'problems'}`;
}

/** One try at starting a trial. */
export interface TrialTry {
  requestId: string;
  input: TeamTrialInput;
}

export function sameInput(a: TeamTrialInput, b: TeamTrialInput): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/**
 * The request id for Run trial: the last try's when Temper didn't answer it
 * and the form is unchanged, so Temper counts the trial once; else a new one.
 */
export function trialRequestId(
  last: TrialTry | null,
  input: TeamTrialInput,
  make: () => string,
): string {
  if (last && sameInput(last.input, input)) return last.requestId;
  return make();
}

export type StartOutcome =
  | { kind: 'started'; started: TeamTrialStarted }
  /** 400 with Temper's problems (and notes): nothing was saved. */
  | { kind: 'problems'; problems: TeamFinding[]; notes: TeamFinding[] }
  /** Any other refusal, in Temper's own words: the guard, a reused request id. */
  | { kind: 'refused'; words: string; status: number }
  /** No reply: the same request id is kept for Try again. */
  | { kind: 'no_answer'; requestId: string };

export type CheckOutcome =
  | { kind: 'passed'; notes: TeamFinding[] }
  | { kind: 'problems'; problems: TeamFinding[]; notes: TeamFinding[] }
  | { kind: 'refused'; words: string; status: number }
  | { kind: 'no_answer' };

function findingsOf(detail: unknown): { problems: TeamFinding[]; notes: TeamFinding[] } | null {
  if (!detail || typeof detail !== 'object') return null;
  const body = detail as { problems?: unknown; notes?: unknown };
  if (!Array.isArray(body.problems) || body.problems.length === 0) return null;
  return {
    problems: body.problems as TeamFinding[],
    notes: Array.isArray(body.notes) ? (body.notes as TeamFinding[]) : [],
  };
}

export function startFailed(err: unknown, requestId: string): StartOutcome {
  if (err instanceof TeamApiError) {
    const found = err.status === 400 ? findingsOf(err.detail) : null;
    if (found) return { kind: 'problems', ...found };
    return { kind: 'refused', words: refusalWords(err.detail, err.status), status: err.status };
  }
  return { kind: 'no_answer', requestId };
}

export function checkAnswered(result: TeamCheckResult): CheckOutcome {
  const problems = result.problems ?? [];
  const notes = result.notes ?? [];
  return problems.length > 0 ? { kind: 'problems', problems, notes } : { kind: 'passed', notes };
}

export function checkFailed(err: unknown): CheckOutcome {
  if (err instanceof TeamApiError) {
    const found = err.status === 400 ? findingsOf(err.detail) : null;
    if (found) return { kind: 'problems', ...found };
    return { kind: 'refused', words: refusalWords(err.detail, err.status), status: err.status };
  }
  return { kind: 'no_answer' };
}

/** The model line in the side column (board F1): "<model> · <provider> · thinking <level>". */
export function modelParts(status: Pick<TeamStatus, 'defaults'> | null): { model: string; provider: string; thinking: string } | null {
  if (!status?.defaults) return null;
  return { model: status.defaults.model, provider: status.defaults.provider, thinking: status.defaults.thinking };
}
