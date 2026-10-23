/**
 * Team page truth check: does the Team page show what Temper's own records hold?
 *
 * The comparing half of scripts/team-page-truth.mjs, kept free of the browser and of
 * Node so the unit tests (src/__tests__/teamPageTruth.test.ts) can feed it known answers.
 *
 * The page side is what a person sees: the Team list and each Project's run view, read
 * from the rendered pages by role, label and text. The record side is Temper's own records,
 * and for each field the one record Temper names as the truth, which the page is judged by:
 *   - members: the configs (GET /api/studio/configs/workflow/<name> and .../agent/<name>:
 *     members, roles, leader) and the names in the turns record;
 *   - state: the run list's status (GET /api/workflows) and workflow_output.decision;
 *   - waits: the open gates (GET /api/runs/{id}/gates, and /decisions for the ones still waiting);
 *   - cost: the recorded model calls, i.e. the turns record (GET /api/workflows/{id}/agents)
 *     summed, and per member summed per agent_name;
 *   - result: the decision (workflow_output.decision, else the run list's status), the team's
 *     outcome reason (workflow_output.reason), and the words given with a stop: the team's stop
 *     record, the last owner_actions entry of kind "stop" in GET /api/team/runs/{id}
 *     (detail.reason and by), which is where Temper records them;
 *   - memberWork: whether each member card says its member is at work (its chip: "Working",
 *     "Working on a retry", "Finishing its turn") against the turns record: a row of that
 *     agent_name with status "running" in GET /api/workflows/{id}/agents, read before and after
 *     the page (a member whose turn started or ended between the reads may match either read). An
 *     ended Project has no member at work. Idle, ready and held can't be told apart from any
 *     record but the Team API, which builds the page, so they stay a manual check.
 * Temper's other records of the same things (the run list's and the run's total_cost_usd, the
 * nodes' cost_usd, the run's stopped.reason and error_message) are compared with that record,
 * not with the page: where they hold something else, the report lists them under "Temper's
 * records disagree" for the temper role, and they are not page mismatches. Apart from the stop
 * record, the Team API (/api/team/*), which builds the page, is read only to say where a gap
 * most likely comes from. A turn the turns record still holds as running in an ended run is listed
 * the same way (memberWork), not held against the page.
 *
 * Six fields per Project (members, state, waits, cost, result, memberWork), plus whether the Team
 * list shows the Project at all ("listed"). No model calls: every check here is a rule.
 */

export const FIELDS = ['listed', 'members', 'state', 'waits', 'cost', 'result', 'memberWork'] as const;
export type Field = (typeof FIELDS)[number];
export type Verdict = 'match' | 'mismatch' | 'no record';
export type Cause = 'page bug' | 'Team API bug' | 'engine record bug' | 'no record' | 'not known';

/** A member as the page shows it. */
export interface PageMember {
  name: string;
  /** The role the page shows; null when it shows none (the page leaves out a role equal to the name). */
  role: string | null;
  leader: boolean;
  /** Its cost as shown ("$5.04"); null where the page shows none (the Team list). */
  cost: string | null;
  /** Its state chip as shown, without the live duration ("Working", "Idle", "Ended"); null when the
   * card shows none; left out where the page has no chip (the Team list). */
  stateWord?: string | null;
}

/** One row of the Team list. */
export interface PageListRow {
  executionId: string;
  /** Shown as a re-run or fork under another Project's row. */
  subRow: boolean;
  /** The leader first; empty for a sub-row. */
  members: PageMember[];
  stateWord: string | null;
  needsYou: boolean;
  /** "cancelled" from the row's "run list: cancelled"; null when the row doesn't say. */
  runListWord: string | null;
  cost: string | null;
}

/** A stop-words quote as the page shows it: a figure named by its caption, the words in its blockquote. */
export interface PageWords {
  /** The caption, which names the figure: "Your words", "temper's words", "Words from an unknown caller". */
  label: string;
  words: string;
}

/** One Project's run view (/app/team/runs/<id>). */
export interface PageRunView {
  executionId: string;
  kind: 'flow' | 'rounds' | null;
  /** The view didn't load, or isn't a Team run: what happened instead. */
  problem: string | null;
  stateWord: string | null;
  members: PageMember[] | null;
  /** Every place the view shows the Project's total cost ("Spend", "Cost", ...). */
  costs: Array<{ place: string; value: string }>;
  /** The open waits it shows: how many (null where it doesn't count them) and who asked. */
  waits: { any: boolean; count: number | null; from: string[] } | null;
  /** The ended Project's outcome word ("Done", "Stopped"); null while it runs. */
  outcomeWord: string | null;
  /** The reason or sentence shown with the outcome, for the report. */
  outcomeReason: string | null;
  /** All text of the outcome area, searched for the record's reason. */
  outcomeText: string | null;
  /** The stop-words quotes the outcome shows (flow: the Status band; rounds: the outcome card). */
  stopWords: PageWords[];
}

export interface PageRead {
  /** "Showing 1–7 of 7" -> 7; null when the list doesn't say. */
  listTotal: number | null;
  rows: PageListRow[];
  views: Record<string, PageRunView>;
}

export interface RecordMember {
  name: string;
  role: string | null;
  leader: boolean;
}

/** The words given with a stop, from the record that keeps them. */
export interface StopRecord {
  /** "stop": the last owner_actions entry of kind "stop" (a cancel; its words are detail.reason).
   * "stop answer": a team a stop answer ended, whose words the team's outcome record keeps. */
  from: 'stop' | 'stop answer';
  /** Who stopped it, as the record names them ("owner", "temper", "unknown caller"). */
  by: string | null;
  /** The words, trimmed; null when none were given. */
  words: string | null;
  at: string | null;
}

/** The run's own record (GET /api/workflows/{id}), the fields read here. */
export interface RunDetail {
  status: string | null;
  costUsd: number | null;
  /** The sum of its top-level nodes' cost_usd. */
  nodeCostUsd: number | null;
  /** workflow_output.decision and .reason: the team's outcome as the run keeps it. */
  decision: string | null;
  outputReason: string | null;
  stoppedReason: string | null;
  errorMessage: string | null;
}

/** What Temper's records hold for one team-trial-* run. */
export interface ProjectRecords {
  executionId: string;
  workflow: string;
  /** The run list's status and total_cost_usd (the total is compared with the turns record, not the page). */
  status: string;
  costUsd: number | null;
  /** GET /api/workflows/{id}; null when it couldn't be read. */
  detail: RunDetail | null;
  /** GET /api/workflows/{id}/agents, per agent_name: turns and their summed estimated_cost_usd (the recorded model calls),
   * and how many of its turns are still "running" (left out: none). */
  turns: Record<string, { turns: number; costUsd: number; running?: number }> | null;
  /** The workflow config's agents, each agent config's role, and the strategy's leader. */
  members: RecordMember[] | null;
  /** GET /api/runs/{id}/gates: each open wait and the member that asked it ("qa asks"). */
  openWaits: Array<{ node: string; asker: string | null }> | null;
  /** GET /api/runs/{id}/decisions still "waiting". */
  waitingDecisions: number | null;
  /** The team's stop record (GET /api/team/runs/{id}); null when nothing stopped the team. */
  stop: StopRecord | null;
  /** Whether GET /api/team/runs/{id} could be read: without it the stop record isn't known. */
  stopRead: boolean;
}

/** The Team API's view of a Project: read only to say where a gap comes from. */
export interface TeamApiProject {
  listed: boolean;
  /** state: the member's state as the Team API serves it (flow: working, idle, ready, held, failed, ended;
   * rounds: its activity, working, idle, waiting_on_owner, ended, failed); null or left out when not read. */
  members: Array<{ name: string; role: string | null; leader: boolean; costUsd: number | null; state?: string | null }> | null;
  state: string | null;
  runStatus: string | null;
  costUsd: number | null;
  openWaits: number | null;
  decision: string | null;
  reason: string | null;
  /** The outcome's owner_words: the stop words the page shows. */
  ownerWords: string | null;
}

export interface CheckInput {
  base: string;
  at: string;
  /** The run list's total (every run, team or not). */
  runListTotal: number;
  /** Every team-trial-* run in the run list, by execution id. */
  records: Record<string, ProjectRecords>;
  /** The same records read again after the page, for Projects still running (their numbers move). */
  recordsAfter?: Record<string, ProjectRecords>;
  page: PageRead;
  teamApi: Record<string, TeamApiProject>;
  /** Only these Projects were asked for: rows for other Projects and the list's total aren't checked. */
  only?: string[] | null;
}

export interface Row {
  project: string;
  workflow: string | null;
  field: Field;
  verdict: Verdict;
  page: string;
  record: string;
  /** Each difference, with both values. */
  gaps: string[];
  cause: Cause | null;
  why: string | null;
}

/** A field on which Temper's own records disagree: listed for the temper role, never a page mismatch. */
export interface Disagreement {
  project: string;
  workflow: string | null;
  field: Field;
  /** The record (or records) the page is judged by, with what it holds. */
  judgedBy: Array<{ record: string; value: string }>;
  /** Each other record that holds something else, with what it holds. */
  differ: Array<{ record: string; value: string }>;
  /** The other records, which agree. */
  agree: string[];
  /** Who fixes the records. */
  owner: 'temper';
}

export interface Report {
  base: string;
  at: string;
  runListTotal: number;
  projects: string[];
  rows: Row[];
  totals: Record<Verdict, number>;
  disagreements: Disagreement[];
}

// ---------------------------------------------------------------- the records' answers

/** The fields of GET /api/workflows/{id} read here. */
export interface RunBody {
  status?: string | null;
  total_cost_usd?: number | string | null;
  nodes?: Array<{ cost_usd?: number | string | null } | null> | null;
  workflow_output?: unknown;
  stopped?: { reason?: string | null } | null;
  error_message?: string | null;
}

/** One row of GET /api/workflows/{id}/agents: one per turn, with its model calls' cost. */
export interface TurnRow {
  agent_name?: string | null;
  estimated_cost_usd?: number | string | null;
  /** "running" while the turn is under way; "completed", "failed", "interrupted" ... after. */
  status?: string | null;
}

/** One entry of GET /api/team/runs/{id}'s owner_actions (a stop's words are its detail.reason). */
export interface OwnerAction {
  at?: string | null;
  kind?: string | null;
  by?: string | null;
  source?: string | null;
  request_id?: string | null;
  detail?: Record<string, unknown> | null;
}

/** The fields of GET /api/team/runs/{id} read here: its owner_actions and its outcome (the team's outcome record). */
export interface TeamRunBody {
  owner_actions?: Array<OwnerAction | null> | null;
  outcome?: {
    decision?: string | null;
    reason?: string | null;
    owner_words?: string | null;
    problems?: unknown;
    by?: string | null;
    at?: string | null;
    done?: unknown;
  } | null;
}

/** A record's number: null when missing, empty or not a number. */
export function numberOf(v: unknown): number | null {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

/** A record's text, trimmed: null when missing or empty. */
function textOf(v: unknown): string | null {
  if (v === null || v === undefined || typeof v === 'object') return null;
  const s = String(v).trim();
  return s || null;
}

/** GET /api/workflows/{id} -> the run's own record. */
export function runDetail(d: RunBody): RunDetail {
  const wo = d.workflow_output && typeof d.workflow_output === 'object' ? (d.workflow_output as Record<string, unknown>) : null;
  const costs = (Array.isArray(d.nodes) ? d.nodes : []).map((n) => numberOf(n?.cost_usd)).filter((v): v is number => v !== null);
  return {
    status: textOf(d.status),
    costUsd: numberOf(d.total_cost_usd),
    nodeCostUsd: costs.length ? costs.reduce((s, v) => s + v, 0) : null,
    decision: textOf(wo?.decision),
    outputReason: textOf(wo?.reason),
    stoppedReason: textOf(d.stopped?.reason),
    errorMessage: textOf(d.error_message),
  };
}

/** GET /api/workflows/{id}/agents (one row per turn) -> per member: how many turns, their summed cost,
 * and how many are still running. */
export function turnsRecord(rows: ReadonlyArray<TurnRow | null>): Record<string, { turns: number; costUsd: number; running: number }> {
  const out: Record<string, { turns: number; costUsd: number; running: number }> = {};
  for (const a of rows) {
    const name = textOf(a?.agent_name);
    if (!name) continue;
    out[name] ??= { turns: 0, costUsd: 0, running: 0 };
    out[name].turns += 1;
    out[name].costUsd += numberOf(a?.estimated_cost_usd) ?? 0;
    if (a?.status === 'running') out[name].running += 1;
  }
  return out;
}

/**
 * GET /api/team/runs/{id} -> the team's stop record: the last owner_actions entry of kind "stop"
 * (its detail.reason and by). For a team a stop answer ended (outcome decision "stopped", no stop
 * entry), the team's outcome record, which keeps that answer's words (owner_words, by). Null when
 * nothing stopped the team.
 */
export function stopRecord(body: TeamRunBody | null | undefined): StopRecord | null {
  const list = body?.owner_actions;
  let last: OwnerAction | null = null;
  for (const a of Array.isArray(list) ? list : []) if (a?.kind === 'stop') last = a;
  if (last) return { from: 'stop', by: textOf(last.by), words: textOf(last.detail?.reason), at: textOf(last.at) };
  const o = body?.outcome;
  if (o?.decision === 'stopped') return { from: 'stop answer', by: textOf(o.by), words: textOf(o.owner_words), at: textOf(o.at) };
  return null;
}

// ---------------------------------------------------------------- small rules

/** "$10.22" -> 10.22, "$0.0058" -> 0.0058, "$62" -> 62; anything else -> null. */
export function parseMoney(text: string | null | undefined): number | null {
  if (!text) return null;
  const m = /\$\s*(\d+(?:\.\d+)?)/.exec(text.replace(/,/g, ''));
  return m ? Number(m[1]) : null;
}

/** To the cent: the page's amount is the record rounded to the cent (either way at an exact half cent). */
export function sameCent(page: number, record: number): boolean {
  return Math.abs(page - record) <= 0.005 + 1e-9;
}

/** A record's dollar amount as it stands (to 7 places, without float noise): "$0.0", "$10.224325". */
export function usd(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return 'none';
  const r = Math.round(n * 1e7) / 1e7;
  return `$${Number.isInteger(r) ? r.toFixed(1) : String(r)}`;
}

export type StateClass = 'done' | 'stopped' | 'failed' | 'didnt_start' | 'interrupted' | 'live' | 'unknown';

const PAGE_WORDS: Record<string, StateClass> = {
  done: 'done',
  "done: the leader's version was approved": 'done',
  stopped: 'stopped',
  cancelled: 'stopped',
  failed: 'failed',
  "didn't start": 'didnt_start',
  'failed to start': 'didnt_start',
  interrupted: 'interrupted',
  'state not known': 'unknown',
};

/** The class of a state word the page shows; every word not ended is a live one ("Running", "Paused", ...). */
export function pageStateClass(word: string | null | undefined): StateClass {
  if (!word) return 'unknown';
  const w = word
    .replace(/^last seen:\s*/i, '')
    .trim()
    .toLowerCase()
    .replace(/[\u2018\u2019]/g, "'");
  return PAGE_WORDS[w] ?? 'live';
}

/** The class the records give: the team's decision when it recorded one, else the run's status. */
export function recordStateClass(status: string | null | undefined, decision?: string | null): StateClass {
  switch ((decision ?? '').toLowerCase()) {
    case 'done':
      return 'done';
    case 'stopped':
    case 'cancelled':
      return 'stopped';
    case 'failed':
      return 'failed';
    case 'didnt_start':
      return 'didnt_start';
  }
  switch ((status ?? '').toLowerCase()) {
    case 'completed':
      return 'done';
    case 'cancelled':
      return 'stopped';
    case 'failed':
      return 'failed';
    case 'running':
    case 'pending':
    case 'queued':
    case 'waiting':
    case 'paused':
      return 'live';
    default:
      return 'unknown';
  }
}

/** Whether a page state agrees with a record state. "Interrupted" is the Team's word for a run that
 * stopped moving without ending; "Didn't start" ends as failed or cancelled. */
export function stateAgrees(page: StateClass, record: StateClass): boolean {
  if (page === 'unknown' || record === 'unknown') return false;
  if (page === record) return true;
  if (page === 'interrupted') return record === 'live' || record === 'failed' || record === 'stopped';
  if (page === 'didnt_start') return record === 'failed' || record === 'stopped';
  return false;
}

const ENDED: ReadonlySet<StateClass> = new Set(['done', 'stopped', 'failed', 'didnt_start']);

const END_TOKENS: ReadonlySet<string> = new Set(['team_done', 'run_completed', 'team_stopped', 'run_cancelled']);

/** A reason worth showing: not empty and not an engine end token. */
export function genuineReason(reason: string | null | undefined): string | null {
  const s = (reason ?? '').trim();
  const bare = s.toLowerCase().replace(/[\s.!?\u2026:;,]+$/, '');
  return !bare || END_TOKENS.has(bare) ? null : s;
}

function norm(s: string): string {
  return s
    .toLowerCase()
    .replace(/[\u2018\u2019]/g, "'")
    .replace(/[\u201c\u201d]/g, '"')
    .replace(/\s+/g, ' ')
    .trim();
}

/**
 * Whether the page's text shows the reason: whole (case and spacing aside), or cut short with
 * "…" on a line whose last 40 characters before it are the reason's.
 */
export function showsReason(text: string | null | undefined, reason: string): boolean {
  if (!text) return false;
  const want = norm(reason).replace(/[.!?;:,]+$/, '');
  if (!want) return true;
  if (norm(text).includes(want)) return true;
  return text.split('\n').some((line) => {
    const t = norm(line);
    if (!t.endsWith('\u2026')) return false;
    const stem = t.slice(0, -1).trim();
    return stem.length >= 40 && want.includes(stem.slice(-40));
  });
}

/** The same words: verbatim, with each run of whitespace as one space. */
export function sameWords(a: string | null | undefined, b: string | null | undefined): boolean {
  const w = (s: string | null | undefined) => (s ?? '').replace(/\s+/g, ' ').trim();
  return w(a) === w(b);
}

const UNKNOWN_CALLER = 'unknown caller';

/** Who a record says gave the words: its name ("owner", "temper"), or "unknown caller" when none is
 * recorded (Temper stores an unknown caller as "unknown caller"). */
export function recordWho(by: string | null | undefined): string {
  const b = (by ?? '').trim();
  return !b || b === UNKNOWN_CALLER ? UNKNOWN_CALLER : b;
}

/** The caption a person should see over the words from `by` (the page's rule: "owner" is "Your words"). */
export function captionFor(by: string | null | undefined): string {
  const who = recordWho(by);
  if (who === 'owner') return 'Your words';
  if (who === UNKNOWN_CALLER) return 'Words from an unknown caller';
  return `${who}'s words`;
}

/** Who a stop-words caption names: "Your words" -> owner, "Words from an unknown caller" ->
 * unknown caller, "<who>'s words" -> who; null for any other caption. */
export function captionWho(label: string): string | null {
  const t = label.replace(/[\u2018\u2019]/g, "'").replace(/\s+/g, ' ').trim();
  if (/^your words$/i.test(t)) return 'owner';
  if (/^words from an unknown caller$/i.test(t)) return UNKNOWN_CALLER;
  const m = /^(.+)'s words$/i.exec(t);
  return m ? m[1].trim() : null;
}

/** Whether a caption names the one the record says gave the words (case aside). */
export function captionMatches(label: string, by: string | null | undefined): boolean {
  return (captionWho(label) ?? '').toLowerCase() === recordWho(by).toLowerCase();
}

/** Whether a member card's chip says its member is at work: "Working", "Working on a retry" or
 * "Finishing its turn" (the glance chips of a member whose turn runs). Idle, ready, held, failed,
 * ended and not known aren't. */
export function pageWorking(word: string | null | undefined): boolean {
  return /^(working|finishing its turn)\b/i.test((word ?? '').trim());
}

function cut(s: string | null | undefined, n = 140): string {
  const t = (s ?? '').replace(/\s+/g, ' ').trim();
  return t.length > n ? `${t.slice(0, n - 1)}\u2026` : t;
}

function memberWords(ms: Array<{ name: string; role: string | null; leader: boolean }>): string {
  return ms
    .map((m) => `${m.name}${m.role && m.role !== m.name ? ` (${m.role})` : ''}${m.leader ? ' [leader]' : ''}`)
    .join(', ');
}

// ---------------------------------------------------------------- the fields

interface FieldResult {
  verdict: Verdict;
  page: string;
  record: string;
  gaps: string[];
  cause: Cause | null;
  why: string | null;
}

function result(page: string, record: string, gaps: string[], cause: Cause | null, why: string | null): FieldResult {
  return gaps.length > 0
    ? { verdict: 'mismatch', page, record, gaps, cause, why }
    : { verdict: 'match', page, record, gaps, cause: null, why: null };
}

function noRecord(page: string, record: string, why: string): FieldResult {
  return { verdict: 'no record', page, record, gaps: [], cause: 'no record', why };
}

function listed(id: string, rec: ProjectRecords, row: PageListRow | undefined, api: TeamApiProject | undefined): FieldResult {
  const record = `${rec.workflow} in the run list (${rec.status})`;
  if (row) return result(row.subRow ? 'listed as a re-run or fork' : 'listed', record, [], null, null);
  const apiHas = api?.listed ?? null;
  return result(
    'no row on the Team list',
    record,
    [`the Team list has no row for ${id}; the run list has ${rec.workflow}`],
    apiHas === null ? 'not known' : apiHas ? 'page bug' : 'Team API bug',
    apiHas === null ? 'the Team API was not read' : apiHas ? 'GET /api/team/trials lists it' : 'GET /api/team/trials leaves it out',
  );
}

function compareMemberList(where: string, shown: PageMember[], rec: RecordMember[], gaps: string[]): void {
  const byName = new Map(shown.map((m) => [m.name, m]));
  for (const r of rec) {
    const s = byName.get(r.name);
    if (!s) {
      gaps.push(`${where} doesn't show member ${r.name}`);
      continue;
    }
    const shownRole = s.role ?? s.name;
    if (r.role && shownRole !== r.role) gaps.push(`${where} shows ${r.name}'s role as ${shownRole}; record: ${r.role}`);
    if (s.leader !== r.leader) {
      gaps.push(r.leader ? `${where} doesn't mark ${r.name} as the leader` : `${where} marks ${r.name} as the leader; record: not the leader`);
    }
  }
  for (const s of shown) {
    if (!rec.some((r) => r.name === s.name)) gaps.push(`${where} shows member ${s.name}; the record has no such member`);
  }
}

function members(rec: ProjectRecords, row: PageListRow | undefined, view: PageRunView | undefined, api: TeamApiProject | undefined): FieldResult {
  const pageParts: string[] = [];
  if (row && !row.subRow) pageParts.push(`list: ${memberWords(row.members)}`);
  if (view?.members) pageParts.push(`run view: ${memberWords(view.members)}`);
  const page = pageParts.join('; ') || 'not shown';
  const ran = rec.turns ? Object.keys(rec.turns) : null;
  const recordParts: string[] = [];
  if (rec.members) recordParts.push(`config: ${memberWords(rec.members)}`);
  if (ran) recordParts.push(`turns by: ${ran.join(', ') || 'nobody'}`);
  const record = recordParts.join('; ') || 'none';
  if (!rec.members && !ran) return noRecord(page, record, 'neither the configs nor the turns could be read');

  const gaps: string[] = [];
  // Without the configs, only the names of members who took turns can be checked.
  const want: RecordMember[] = rec.members ?? (ran ?? []).map((name) => ({ name, role: null, leader: false }));
  const loose = !rec.members;
  const check = (where: string, shown: PageMember[]) => {
    if (loose) {
      for (const name of ran ?? []) if (!shown.some((m) => m.name === name)) gaps.push(`${where} doesn't show member ${name}, who took turns`);
    } else compareMemberList(where, shown, want, gaps);
  };
  if (row && !row.subRow) check('the Team list', row.members);
  if (view?.members) check('the run view', view.members);
  else if (view) gaps.push(`the run view shows no members${view.problem ? ` (${view.problem})` : ''}`);

  const strays = rec.members && ran ? ran.filter((n) => !rec.members!.some((m) => m.name === n)) : [];
  if (gaps.length === 0) return result(page, record, [], null, null);
  if (strays.length > 0) {
    return result(page, record, gaps, 'engine record bug', `turns by ${strays.join(', ')}, not in the workflow config`);
  }
  if (api?.members) {
    const apiShown: PageMember[] = api.members.map((m) => ({ name: m.name, role: m.role, leader: m.leader, cost: null }));
    const apiGaps: string[] = [];
    compareMemberList('the Team API', apiShown, want, apiGaps);
    return apiGaps.length > 0
      ? result(page, record, gaps, 'Team API bug', `the Team API's members differ too: ${apiGaps.join('; ')}`)
      : result(page, record, gaps, 'page bug', "the Team API's members match the record");
  }
  return result(page, record, gaps, 'not known', 'the Team API was not read');
}

function state(rec: ProjectRecords, after: ProjectRecords | undefined, row: PageListRow | undefined, view: PageRunView | undefined, api: TeamApiProject | undefined): FieldResult {
  const parts: string[] = [];
  if (row) parts.push(`list: ${row.stateWord ?? 'no word'}${row.runListWord ? ` (run list: ${row.runListWord})` : ''}`);
  if (view) parts.push(`run view: ${view.stateWord ?? (view.problem ? `not read (${view.problem})` : 'no word')}`);
  const page = parts.join('; ') || 'not shown';
  const decision = rec.detail?.decision ?? null;
  const record = `run list: ${rec.status}${decision ? `; decision: ${decision}` : ''}`;

  const gapsFor = (r: ProjectRecords): string[] => {
    const g: string[] = [];
    const want = recordStateClass(r.status, r.detail?.decision ?? null);
    const wantWords = `run list ${r.status}${r.detail?.decision ? `, decision ${r.detail.decision}` : ''}`;
    if (row) {
      if (!stateAgrees(pageStateClass(row.stateWord), want)) g.push(`the Team list says ${row.stateWord ?? 'nothing'}; record: ${wantWords}`);
      if (row.runListWord && row.runListWord !== r.status) g.push(`the Team list says "run list: ${row.runListWord}"; the run list says ${r.status}`);
    }
    if (view && !view.problem && !stateAgrees(pageStateClass(view.stateWord), want)) {
      g.push(`the run view says ${view.stateWord ?? 'nothing'}; record: ${wantWords}`);
    }
    if (view?.problem) g.push(`the run view wasn't read: ${view.problem}`);
    return g;
  };
  let gaps = gapsFor(rec);
  if (gaps.length > 0 && after) {
    const later = gapsFor(after);
    if (later.length === 0) gaps = [];
  }
  if (gaps.length === 0) return result(page, record, [], null, null);
  if (!api) return result(page, record, gaps, 'not known', 'the Team API was not read');
  if (api.runStatus && api.runStatus !== rec.status) {
    return result(page, record, gaps, 'Team API bug', `the Team API's run_status is ${api.runStatus}; the run list says ${rec.status}`);
  }
  const apiWord = api.state === 'didnt_start' ? "didn't start" : (api.state ?? '').replace(/_/g, ' ');
  return stateAgrees(pageStateClass(apiWord), recordStateClass(rec.status, decision))
    ? result(page, record, gaps, 'page bug', `the Team API's state ${api.state} agrees with the record`)
    : result(page, record, gaps, 'Team API bug', `the Team API's state is ${api.state}`);
}

function waits(rec: ProjectRecords, after: ProjectRecords | undefined, row: PageListRow | undefined, view: PageRunView | undefined, api: TeamApiProject | undefined): FieldResult {
  const parts: string[] = [];
  if (row) parts.push(`list: ${row.needsYou ? '"needs you"' : 'no "needs you"'}`);
  if (view?.waits) {
    const w = view.waits;
    parts.push(`run view: ${w.any ? `${w.count ?? 'some'} open${w.from.length ? `, from ${w.from.join(', ')}` : ''}` : 'nothing needs you'}`);
  } else if (view) parts.push(`run view: not read${view.problem ? ` (${view.problem})` : ''}`);
  const page = parts.join('; ') || 'not shown';
  if (!rec.openWaits) return noRecord(page, 'gates not read', 'GET /api/runs/{id}/gates could not be read');
  const askers = (r: ProjectRecords) => (r.openWaits ?? []).map((w) => w.asker).filter((a): a is string => Boolean(a));
  const record = `${rec.openWaits.length} open gate${rec.openWaits.length === 1 ? '' : 's'}${askers(rec).length ? ` (asked by ${askers(rec).join(', ')})` : ''}${
    rec.waitingDecisions !== null ? `; ${rec.waitingDecisions} decision${rec.waitingDecisions === 1 ? '' : 's'} waiting` : ''
  }`;

  const gapsFor = (r: ProjectRecords): string[] => {
    const g: string[] = [];
    const n = (r.openWaits ?? []).length;
    if (row && row.needsYou !== n > 0) {
      g.push(n > 0 ? `the Team list shows no "needs you"; ${n} gate${n === 1 ? ' is' : 's are'} open` : `the Team list shows "needs you"; no gate is open`);
    }
    if (view?.waits) {
      const w = view.waits;
      if (w.any !== n > 0) g.push(n > 0 ? `the run view says nothing needs you; ${n} gate${n === 1 ? ' is' : 's are'} open` : 'the run view shows a wait; no gate is open');
      else if (w.count !== null && w.count !== n) g.push(`the run view shows ${w.count} open waits; ${n} gates are open`);
      const first = (r.openWaits ?? [])[0]?.asker;
      if (w.any && first && !w.from.includes(first)) g.push(`the run view doesn't say the first wait is from ${first}`);
      for (const f of w.from) if (!askers(r).includes(f)) g.push(`the run view says a wait is from ${f}; no open gate was asked by ${f}`);
    }
    return g;
  };
  let gaps = gapsFor(rec);
  if (gaps.length > 0 && after?.openWaits && gapsFor(after).length === 0) gaps = [];
  if (gaps.length === 0) return result(page, record, [], null, null);
  if (rec.waitingDecisions !== null && rec.waitingDecisions !== rec.openWaits.length) {
    return result(page, record, gaps, 'engine record bug', `the gates list ${rec.openWaits.length} open, the decisions ${rec.waitingDecisions} waiting`);
  }
  if (!api || api.openWaits === null) return result(page, record, gaps, 'not known', 'the Team API was not read');
  return api.openWaits === rec.openWaits.length
    ? result(page, record, gaps, 'page bug', `the Team API has ${api.openWaits} open waits, as the records do`)
    : result(page, record, gaps, 'Team API bug', `the Team API has ${api.openWaits} open waits; the gates ${rec.openWaits.length}`);
}

/** What the recorded model calls cost: the turns record summed; null when it couldn't be read. */
export function turnsSum(r: ProjectRecords): number | null {
  return r.turns ? Object.values(r.turns).reduce((s, t) => s + t.costUsd, 0) : null;
}

/** Temper's other records of a run's total cost: compared with the recorded model calls, never with the page. */
function otherCosts(r: ProjectRecords): Array<[string, number]> {
  return (
    [
      ['run list total_cost_usd', r.costUsd],
      ['run total_cost_usd', r.detail?.costUsd ?? null],
      ['node cost_usd', r.detail?.nodeCostUsd ?? null],
    ] as Array<[string, number | null]>
  ).filter((s): s is [string, number] => s[1] !== null);
}

const CALLS = 'the recorded model calls (turns record)';

function cost(rec: ProjectRecords, after: ProjectRecords | undefined, row: PageListRow | undefined, view: PageRunView | undefined, api: TeamApiProject | undefined): FieldResult {
  const shownTotals: Array<{ place: string; value: string }> = [];
  if (row && !row.subRow && row.cost !== null) shownTotals.push({ place: 'the Team list', value: row.cost });
  for (const c of view?.costs ?? []) shownTotals.push({ place: `the run view's ${c.place}`, value: c.value });
  const shownMembers = (view?.members ?? []).filter((m) => m.cost !== null);
  const page =
    [
      shownTotals.map((t) => `${t.place.replace(/^the /, '')} ${t.value}`).join('; '),
      shownMembers.length ? `members: ${shownMembers.map((m) => `${m.name} ${m.cost}`).join(', ')}` : '',
    ]
      .filter(Boolean)
      .join('; ') || 'not shown';

  const sum = turnsSum(rec);
  const others = otherCosts(rec);
  const record =
    [
      sum !== null ? `recorded model calls (turns record) ${usd(sum)}` : '',
      rec.turns
        ? `per member: ${Object.entries(rec.turns)
            .map(([n, t]) => `${n} ${usd(t.costUsd)}`)
            .join(', ')}`
        : '',
      others.length ? `other records: ${others.map(([k, v]) => `${k} ${usd(v)}`).join(', ')}` : '',
    ]
      .filter(Boolean)
      .join('; ') || 'none';
  if (sum === null) return noRecord(page, record, 'the turns record (GET /api/workflows/{id}/agents) could not be read');

  // A running Project's numbers move while the page is read: an amount that matches either read of
  // the records, or lies between them, counts as right.
  const fits = (v: number | null, a: number, b: number | null): boolean =>
    v !== null && (sameCent(v, a) || (b !== null && (sameCent(v, b) || (v >= Math.min(a, b) && v <= Math.max(a, b)))));
  const memberCost = (r: ProjectRecords | undefined, name: string): number | null =>
    r?.turns ? (r.turns[name]?.costUsd ?? 0) : null;
  const sumAfter = after ? turnsSum(after) : null;
  const gaps: string[] = [];
  for (const t of shownTotals) {
    if (!fits(parseMoney(t.value), sum, sumAfter)) gaps.push(`${t.place} shows ${t.value}; ${CALLS} sum to ${usd(sum)}`);
  }
  const wrongMembers: string[] = [];
  for (const m of shownMembers) {
    const want = memberCost(rec, m.name);
    if (want === null) continue;
    if (!fits(parseMoney(m.cost), want, memberCost(after, m.name))) {
      wrongMembers.push(m.name);
      gaps.push(`the run view shows ${m.name} ${m.cost}; its recorded model calls (turns record) sum to ${usd(want)}`);
    }
  }
  if (gaps.length === 0) return result(page, record, [], null, null);
  if (!api || api.costUsd === null) return result(page, record, gaps, 'not known', 'the Team API was not read');
  if (!sameCent(api.costUsd, sum)) {
    return result(page, record, gaps, 'Team API bug', `the Team API says ${usd(api.costUsd)}; ${CALLS} sum to ${usd(sum)}`);
  }
  const apiMembersOk = wrongMembers.every((name) => {
    const m = api.members?.find((x) => x.name === name);
    const want = memberCost(rec, name);
    const shown = m?.costUsd ?? null;
    return shown !== null && want !== null && sameCent(shown, want);
  });
  return apiMembersOk
    ? result(page, record, gaps, 'page bug', `the Team API says ${usd(api.costUsd)}, as ${CALLS} do`)
    : result(page, record, gaps, 'Team API bug', `the Team API's member costs differ from ${CALLS} too`);
}

/** Where the run list's and the run's totals and the nodes' costs differ from the recorded model calls. */
function costDisagreement(rec: ProjectRecords, after: ProjectRecords | undefined): Omit<Disagreement, 'project' | 'workflow'> | null {
  const sum = turnsSum(rec);
  if (sum === null) return null;
  const sumAfter = after ? turnsSum(after) : null;
  const later = new Map(after ? otherCosts(after) : []);
  const differ: Array<{ record: string; value: string }> = [];
  const agree: string[] = [];
  for (const [k, v] of otherCosts(rec)) {
    // A running Project's numbers move: a record that agrees in the second read agrees.
    const l = later.get(k);
    if (sameCent(v, sum) || (l !== undefined && sumAfter !== null && sameCent(l, sumAfter))) agree.push(k);
    else differ.push({ record: k, value: usd(v) });
  }
  if (differ.length === 0) return null;
  return { field: 'cost', judgedBy: [{ record: 'recorded model calls (turns record, summed)', value: usd(sum) }], differ, agree, owner: 'temper' };
}

function statusDecision(status: string): string | null {
  return ({ completed: 'done', cancelled: 'cancelled', failed: 'failed' } as Record<string, string>)[status] ?? null;
}

/** The team's generic sentence for a cancelled run: it says nothing the decision doesn't. */
function isGenericCancel(s: string): boolean {
  return norm(s).replace(/[.!?]+$/, '') === 'the run was cancelled';
}

interface ResultRecord {
  decision: string | null;
  decisionFrom: string;
  /** The stop record, for a run that ended without being done. */
  stop: StopRecord | null;
  /** The reason the page must show, and its record; null when there is none to show. */
  reason: string | null;
  reasonFrom: string | null;
  /** The run's other records of why it ended: compared with the stop words and the reason, never the page. */
  others: Array<[string, string]>;
}

/**
 * What the records say an ended run's result is. The decision: workflow_output.decision, else the
 * run list's status. The words given with a stop: the team's stop record. The reason: the team's
 * outcome reason (workflow_output.reason), except its generic "the run was cancelled" where the
 * stop words say why; with no stop recorded and no outcome reason, the run's stopped.reason, else
 * its error_message (then the only record of why). Otherwise stopped.reason and error_message are
 * compared with those, record against record.
 */
function resultRecord(rec: ProjectRecords): ResultRecord {
  const d = rec.detail;
  const decision = d?.decision ?? statusDecision(rec.status);
  const decisionFrom = d?.decision ? 'workflow_output.decision' : 'run list status';
  const stop = recordStateClass(rec.status, decision) === 'done' ? null : rec.stop;
  const words = stop?.words ?? null;
  const output = genuineReason(d?.outputReason);
  const stopped = genuineReason(d?.stoppedReason);
  const error = genuineReason(d?.errorMessage);
  let reason: string | null = null;
  let reasonFrom: string | null = null;
  if (output && !(words && isGenericCancel(output))) [reason, reasonFrom] = [output, 'workflow_output.reason'];
  else if (!output && !stop && rec.status !== 'completed') {
    if (stopped) [reason, reasonFrom] = [stopped, 'stopped.reason'];
    else if (error) [reason, reasonFrom] = [error, 'error_message'];
  }
  const others = (
    [
      ['stopped.reason', stopped],
      ['error_message', error],
    ] as Array<[string, string | null]>
  ).filter((o): o is [string, string] => o[1] !== null && o[0] !== reasonFrom);
  return { decision, decisionFrom, stop, reason, reasonFrom, others };
}

function stopSource(s: StopRecord): string {
  return s.from === 'stop' ? "the team's stop record" : "a stop answer, kept in the team's outcome record";
}

function quoteWords(shown: PageWords[]): string {
  return shown.map((w) => `"${cut(w.words)}" under "${w.label}"`).join(', ');
}

function resultField(rec: ProjectRecords, view: PageRunView | undefined, api: TeamApiProject | undefined): FieldResult {
  const ended = ENDED.has(recordStateClass(rec.status));
  const shownWords = view && !view.problem ? view.stopWords : [];
  const shown = view
    ? view.problem
      ? `not read (${view.problem})`
      : view.outcomeWord
        ? `${view.outcomeWord}${view.outcomeReason ? ` \u2014 "${cut(view.outcomeReason)}"` : ''}`
        : 'no outcome'
    : 'not read';
  const page = `run view: ${shown}${shownWords.length ? `; stop words: ${quoteWords(shownWords)}` : ''}`;
  if (!ended) {
    const gaps =
      view?.outcomeWord && ENDED.has(pageStateClass(view.outcomeWord))
        ? [`the run view shows an outcome (${view.outcomeWord}); the run list says ${rec.status}`]
        : [];
    return result(page, `not ended (run list: ${rec.status})`, gaps, gaps.length ? 'not known' : null, gaps.length ? 'the run has no result yet' : null);
  }
  const r = resultRecord(rec);
  const words = r.stop?.words ?? null;
  const record = [
    `${r.decision ?? 'no decision'} (${r.decisionFrom})`,
    r.reason ? `reason (${r.reasonFrom}): "${cut(r.reason)}"` : 'no reason to show',
    r.stop
      ? words
        ? `stop words (${stopSource(r.stop)}, by ${recordWho(r.stop.by)}): "${cut(words)}"`
        : `stopped by ${recordWho(r.stop.by)} (${stopSource(r.stop)}), no words given`
      : '',
  ]
    .filter(Boolean)
    .join('; ');
  if (!rec.detail) return noRecord(page, record, 'GET /api/workflows/{id} could not be read');
  if (recordStateClass(rec.status, r.decision) !== 'done' && !rec.stopRead) {
    return noRecord(page, record, "GET /api/team/runs/{id}, which holds the team's stop record, could not be read");
  }

  const gaps: string[] = [];
  if (!view || view.problem) gaps.push(`the run view wasn't read${view?.problem ? `: ${view.problem}` : ''}`);
  else {
    if (!view.outcomeWord) gaps.push(`the run view shows no outcome; record: ${r.decision}`);
    else if (!stateAgrees(pageStateClass(view.outcomeWord), recordStateClass(null, r.decision))) {
      gaps.push(`the run view's outcome is ${view.outcomeWord}; record decision: ${r.decision}`);
    }
    if (r.reason && !showsReason(view.outcomeText, r.reason)) {
      gaps.push(`the run view doesn't show the reason "${cut(r.reason)}" (${r.reasonFrom}); it says "${cut(view.outcomeReason) || 'no reason'}"`);
    }
    if (r.stop && words) {
      const by = r.stop.by;
      const want = `"${cut(words)}" (${stopSource(r.stop)}, by ${recordWho(by)})`;
      const same = shownWords.find((w) => sameWords(w.words, words));
      if (!same) {
        gaps.push(shownWords.length ? `the run view's stop words are ${quoteWords(shownWords)}; the record holds ${want}` : `the run view doesn't show the stop words ${want}`);
      } else if (!captionMatches(same.label, by)) {
        gaps.push(`the run view puts the stop words under "${same.label}"; they are from ${recordWho(by)} ("${captionFor(by)}")`);
      }
    } else if (shownWords.length) {
      gaps.push(
        `the run view shows stop words ${quoteWords(shownWords)}; ${
          r.stop ? `the team's stop record holds none (stopped by ${recordWho(r.stop.by)})` : 'no stop is recorded for this run'
        }`,
      );
    }
  }
  if (gaps.length === 0) return result(page, record, [], null, null);
  if (!api) return result(page, record, gaps, 'not known', 'the Team API was not read');
  const apiReason = genuineReason(api.reason);
  const apiHasReason = !r.reason || (apiReason !== null && showsReason(apiReason, r.reason));
  const apiDecisionOk = api.decision !== null && stateAgrees(recordStateClass(null, api.decision), recordStateClass(null, r.decision));
  const apiWordsOk = words ? api.ownerWords !== null && sameWords(api.ownerWords, words) : !api.ownerWords;
  if (apiHasReason && apiDecisionOk && apiWordsOk) return result(page, record, gaps, 'page bug', "the Team API's outcome matches the records");
  if (api.decision === null) return result(page, record, gaps, 'not known', 'the Team API has no outcome for this ended run');
  // The Team API serves the team's own outcome record (pi_team_outcomes) as it is: when that
  // differs from the run's record or from the stop record, two of Temper's records disagree.
  const parts: string[] = [];
  if (!apiHasReason || !apiDecisionOk) {
    parts.push(
      `the team's outcome record (pi_team_outcomes, as the Team API serves it) says ${api.decision}${
        api.reason ? ` "${cut(api.reason, 80)}"` : ' with no reason'
      }; the run's record says ${r.decision}${r.reason ? ` "${cut(r.reason, 80)}" (${r.reasonFrom})` : ''}`,
    );
  }
  if (!apiWordsOk) {
    parts.push(
      `the team's outcome record holds the stop words ${api.ownerWords ? `"${cut(api.ownerWords, 80)}"` : 'none'}; ${
        r.stop ? stopSource(r.stop) : 'no stop record'
      } holds ${words ? `"${cut(words, 80)}"` : 'none'}`,
    );
  }
  return result(page, record, gaps, 'engine record bug', `two records disagree: ${parts.join('; ')}; which one the page should show is the temper role's call`);
}

/** Where the run's stopped.reason or error_message holds something other than the stop words and the reason. */
function resultDisagreement(rec: ProjectRecords): Omit<Disagreement, 'project' | 'workflow'> | null {
  if (!rec.detail || !ENDED.has(recordStateClass(rec.status))) return null;
  const r = resultRecord(rec);
  if (recordStateClass(rec.status, r.decision) !== 'done' && !rec.stopRead) return null;
  const judgedBy: Array<{ record: string; value: string }> = [];
  if (r.stop?.words) judgedBy.push({ record: `stop words (${stopSource(r.stop)}, by ${recordWho(r.stop.by)})`, value: r.stop.words });
  if (r.reason) judgedBy.push({ record: r.reasonFrom ?? 'reason', value: r.reason });
  if (judgedBy.length === 0) return null;
  const differ: Array<{ record: string; value: string }> = [];
  const agree: string[] = [];
  for (const [k, v] of r.others) {
    if (judgedBy.some((j) => sameWords(j.value, v))) agree.push(k);
    else differ.push({ record: k, value: v });
  }
  if (differ.length === 0) return null;
  return { field: 'result', judgedBy, differ, agree, owner: 'temper' };
}

/** The members whose turns record holds a turn still running. */
function runningIn(r: ProjectRecords | undefined): string[] {
  return r?.turns ? Object.keys(r.turns).filter((n) => (r.turns![n].running ?? 0) > 0) : [];
}

/**
 * Whether each member card says its member is at work when the turns record says so. A running
 * Project: a running row of that agent_name in the record read before the page or the one read
 * after it, or a new turn between them, lets the card say Working; no running row in one of them,
 * or a new turn between them, lets it say anything else. An ended Project: no card says Working.
 */
function memberWork(rec: ProjectRecords, after: ProjectRecords | undefined, view: PageRunView | undefined, api: TeamApiProject | undefined): FieldResult {
  const cards = view && !view.problem ? view.members : null;
  const page = cards
    ? cards.map((m) => `${m.name} ${m.stateWord ?? 'no chip'}`).join(', ') || 'no member cards'
    : `run view: ${view?.problem ? `not read (${view.problem})` : view ? 'no member cards' : 'not read'}`;
  const ended = ENDED.has(recordStateClass(rec.status, rec.detail?.decision ?? null));
  const running = runningIn(rec);
  const later = after?.turns ? runningIn(after) : null;
  const record = ended
    ? `ended (run list: ${rec.status}): no member at work`
    : `turns running (turns record): ${running.join(', ') || 'none'}${later ? `; second read: ${later.join(', ') || 'none'}` : ''}`;
  if (!rec.turns) return noRecord(page, record, 'the turns record (GET /api/workflows/{id}/agents) could not be read');

  const gaps: string[] = [];
  if (!view || view.problem) gaps.push(`the run view wasn't read${view?.problem ? `: ${view.problem}` : ''}`);
  else if (!view.members) gaps.push('the run view shows no member cards');
  const wrong: Array<{ name: string; shownWorking: boolean }> = [];
  for (const m of cards ?? []) {
    if (m.stateWord === null || m.stateWord === undefined) {
      gaps.push(`the run view's card for ${m.name} shows no state`);
      continue;
    }
    const shownWorking = pageWorking(m.stateWord);
    let canWork: boolean;
    let canRest: boolean;
    if (ended) [canWork, canRest] = [false, true];
    else {
      const before = rec.turns[m.name];
      const then = after?.turns ? after.turns[m.name] : undefined;
      const runBefore = (before?.running ?? 0) > 0;
      const runAfter = after?.turns ? (then?.running ?? 0) > 0 : runBefore;
      // A new turn between the reads: it started and maybe ended while the page was read.
      const moved = after?.turns ? (then?.turns ?? 0) > (before?.turns ?? 0) : false;
      canWork = runBefore || runAfter || moved;
      canRest = !runBefore || !runAfter || moved;
    }
    if (shownWorking ? canWork : canRest) continue;
    wrong.push({ name: m.name, shownWorking });
    const reads = after?.turns ? ' in either read' : '';
    gaps.push(
      shownWorking
        ? ended
          ? `the run view says ${m.name} is ${m.stateWord}; the run has ended (run list: ${rec.status})`
          : `the run view says ${m.name} is ${m.stateWord}; the turns record has no turn of ${m.name} running${reads}`
        : `the run view says ${m.name} is ${m.stateWord}; the turns record has a turn of ${m.name} running${reads}`,
    );
  }
  if (gaps.length === 0) return result(page, record, [], null, null);
  if (wrong.length === 0) return result(page, record, gaps, 'not known', 'no card was compared');
  if (!api?.members) return result(page, record, gaps, 'not known', 'the Team API was not read');
  // The Team API's member state builds the chip: it agrees with the page (Team API bug) or the record (page bug).
  const apiStates = wrong.map(({ name, shownWorking }) => {
    const s = api.members?.find((x) => x.name === name)?.state ?? null;
    return { name, s, sameAsPage: s === null ? null : (s === 'working') === shownWorking };
  });
  const said = apiStates.map((a) => `${a.name} ${a.s ?? 'no state'}`).join(', ');
  if (apiStates.some((a) => a.sameAsPage === null)) return result(page, record, gaps, 'not known', `the Team API's member states: ${said}`);
  return apiStates.every((a) => a.sameAsPage)
    ? result(page, record, gaps, 'Team API bug', `the Team API's member states agree with the page: ${said}`)
    : result(page, record, gaps, 'page bug', `the Team API's member states agree with the turns record: ${said}`);
}

/** Where an ended run's turns record still holds a turn as running. */
function memberWorkDisagreement(rec: ProjectRecords): Omit<Disagreement, 'project' | 'workflow'> | null {
  if (!ENDED.has(recordStateClass(rec.status, rec.detail?.decision ?? null))) return null;
  const running = runningIn(rec);
  if (running.length === 0) return null;
  return {
    field: 'memberWork',
    judgedBy: [{ record: 'run list status', value: rec.status }],
    differ: [{ record: 'turns record (GET /api/workflows/{id}/agents)', value: `turns still running: ${running.join(', ')}` }],
    agree: [],
    owner: 'temper',
  };
}

// ---------------------------------------------------------------- the report

/** Compare every Project's six fields (and whether it is listed), and list where Temper's own records disagree. */
export function compareAll(input: CheckInput): Report {
  const only = input.only && input.only.length > 0 ? new Set(input.only) : null;
  const ids = Object.keys(input.records).filter((id) => !only || only.has(id));
  const rows: Row[] = [];
  const disagreements: Disagreement[] = [];
  const push = (project: string, workflow: string | null, field: Field, r: FieldResult) => rows.push({ project, workflow, field, ...r });
  for (const id of ids) {
    const rec = input.records[id];
    const after = input.recordsAfter?.[id];
    const row = input.page.rows.find((r) => r.executionId === id);
    const view = input.page.views[id];
    const api = input.teamApi[id];
    push(id, rec.workflow, 'listed', listed(id, rec, row, api));
    push(id, rec.workflow, 'members', members(rec, row, view, api));
    push(id, rec.workflow, 'state', state(rec, after, row, view, api));
    push(id, rec.workflow, 'waits', waits(rec, after, row, view, api));
    push(id, rec.workflow, 'cost', cost(rec, after, row, view, api));
    push(id, rec.workflow, 'result', resultField(rec, view, api));
    push(id, rec.workflow, 'memberWork', memberWork(rec, after, view, api));
    for (const d of [costDisagreement(rec, after), resultDisagreement(rec), memberWorkDisagreement(rec)]) {
      if (d) disagreements.push({ project: id, workflow: rec.workflow, ...d });
    }
  }
  if (!only) {
    for (const r of input.page.rows) {
      if (input.records[r.executionId]) continue;
      push(r.executionId, null, 'listed', {
        verdict: 'mismatch',
        page: r.subRow ? 'listed as a re-run or fork' : 'listed',
        record: 'no team-trial-* run with this id in the run list',
        gaps: [`the Team list shows ${r.executionId}; the run list has no team-trial-* run with that id`],
        cause: 'not known',
        why: 'the run list holds only the runs of its newest 1000 start events; an older run drops off it',
      });
    }
    const want = Object.keys(input.records).length;
    if (input.page.listTotal !== null || want > 0) {
      const shownTotal = input.page.listTotal;
      push('(all)', null, 'listed', {
        ...(shownTotal === want
          ? { verdict: 'match' as const, gaps: [], cause: null, why: null }
          : {
              verdict: 'mismatch' as const,
              gaps: [`the Team list says it has ${shownTotal ?? 'no count of'} Projects; the run list has ${want} team-trial-* runs`],
              cause: 'not known' as const,
              why: 'compare the rows above',
            }),
        page: `the Team list counts ${shownTotal ?? 'nothing'}`,
        record: `${want} team-trial-* runs of the run list's ${input.runListTotal}`,
      });
    }
  }
  const totals: Record<Verdict, number> = { match: 0, mismatch: 0, 'no record': 0 };
  for (const r of rows) totals[r.verdict] += 1;
  return { base: input.base, at: input.at, runListTotal: input.runListTotal, projects: ids, rows, totals, disagreements };
}

/** 1 when the page mismatches a record or a record is missing, else 0. Temper's records that disagree
 * with each other alone don't fail it: they are listed for the temper role. */
export function exitCode(report: Report): number {
  return report.totals.mismatch > 0 || report.totals['no record'] > 0 ? 1 : 0;
}

/** Where each field is shown, what builds it, and what it is checked against (step 2's field table). */
export const FIELD_TABLE: ReadonlyArray<readonly [string, string, string, string]> = [
  [
    'members',
    'list: "Leader X \u00b7 others" line; run view: the member cards (flow: "Team now", name, role, leader tag; rounds: "Members (N)")',
    'trial row members (pi ledger) and members_view (ledger member rows and turns)',
    'workflow config team-trial-<id>: agents, each agent config\'s role, strategy mode.leader; names in the turns record',
  ],
  [
    'state',
    'list: state badge and "run list: X"; run view: flow "Now" word, rounds "Team state" and outcome heading',
    'team_state(): pi_team_outcomes decision, the run list status, ledger open waits',
    'run list status; workflow_output.decision',
  ],
  [
    'waits',
    'list: "needs you" chip; run view: flow "You" cell (Needs you: \u2026, and N more, From X), rounds "Needs you" card',
    'ledger open_waits (open_waits_view)',
    'GET /api/runs/{id}/gates (the asker from its question header "<member> asks"); /decisions still waiting',
  ],
  [
    'cost',
    'list: "Cost $X"; run view: flow "Spend" and each card\'s "N turns \u00b7 $X", rounds header and outcome "Cost" and each member line',
    'TeamReader.usage() and members_view: the ledger turns\' worker usage',
    'the recorded model calls: the turns record (GET /api/workflows/{id}/agents) summed, per member summed per agent_name. Record against record (listed, not a page mismatch): the run list\'s total_cost_usd, the run\'s total_cost_usd, its nodes\' cost_usd',
  ],
  [
    'result',
    'run view: flow "Now" word with its sentence (and an interrupted run\'s reason), rounds outcome card heading and "Temper\'s reason"; the stop-words quote (a figure named by its caption "Your words", "<who>\'s words" or "Words from an unknown caller", the words in its blockquote) in the flow "Status" band and on the rounds outcome card',
    'outcome_view(): the pi_team_outcomes row (decision, reason, owner_words, by)',
    'the decision: workflow_output.decision, else the run list status; the stop words and who gave them: the team\'s stop record, the last owner_actions entry of kind "stop" in GET /api/team/runs/{id} (detail.reason, by; a stop answer\'s words: the team\'s outcome record); the reason: workflow_output.reason, else (no stop recorded, not completed) stopped.reason, else error_message. Record against record (listed, not a page mismatch): stopped.reason and error_message against the stop words and the reason',
  ],
  [
    'memberWork',
    'run view: each member card\'s state chip (flow: "Working", "Working on a retry", "Finishing its turn" are at work; "Idle", "Ready", "Paused", "Needs you", "Ended" ... are not; rounds: the activity chip, "Working" or not)',
    'members_view state (flow: a running ledger participant is "working"; rounds: activity)',
    'the turns record (GET /api/workflows/{id}/agents): a row of that agent_name with status "running", read before and after the page (a turn that started or ended between the reads may match either read); an ended run: no member at work. Record against record (listed, not a page mismatch): a turn still running in an ended run. Idle, ready and held are not checked: only the Team API tells them apart',
  ],
];

function cell(s: string | null | undefined): string {
  return (s ?? '').replace(/\|/g, '\\|').replace(/\s*\n\s*/g, ' ');
}

/** The report as Markdown: totals, the gaps, where Temper's records disagree, every Project and field, and the field table. */
export function toMarkdown(report: Report): string {
  const short = (id: string) => (id.length > 8 && id !== '(all)' ? id.slice(0, 8) : id);
  const out: string[] = [];
  out.push('# Team page truth check', '');
  out.push(`Temper ${report.base}, read ${report.at}. Projects checked: ${report.projects.length} (the run list holds ${report.runListTotal} runs).`);
  out.push(
    `Rows (Project \u00d7 field): ${report.totals.match} match, ${report.totals.mismatch} mismatch, ${report.totals['no record']} no record. ` +
      `Temper's records disagree: ${report.disagreements.length} (listed for the temper role; not page mismatches). ` +
      (exitCode(report) === 1 ? 'Exit 1: the page mismatches a record, or a record is missing.' : 'Exit 0: the page shows what the records it is judged by hold.'),
    '',
  );
  const gaps = report.rows.filter((r) => r.verdict !== 'match');
  out.push('## Gaps', '');
  if (gaps.length === 0) out.push('None: every field matches.', '');
  else {
    out.push('| Project | Field | Verdict | What differs (page vs record) | Likely cause |', '|---|---|---|---|---|');
    for (const r of gaps) {
      out.push(`| ${short(r.project)} | ${r.field} | ${r.verdict} | ${cell(r.gaps.join('<br>') || r.why)} | ${cell(r.cause ?? '')}${r.why ? `: ${cell(r.why)}` : ''} |`);
    }
    out.push('');
  }
  out.push("## Temper's records disagree", '');
  out.push(
    "Each field is judged by one record: the cost by the recorded model calls (the turns record, summed), the words given with a stop by the team's stop record. " +
      "Where another of Temper's records holds something else, it is listed here for the temper role. It is not a page mismatch and doesn't fail the check.",
    '',
  );
  if (report.disagreements.length === 0) out.push("None: Temper's records agree with each other.", '');
  else {
    const value = (field: Field, v: string) => (field === 'cost' ? v : `"${cut(v, 200)}"`);
    out.push('| Project | Field | Judged by | Records that differ | Records that agree | Owner |', '|---|---|---|---|---|---|');
    for (const d of report.disagreements) {
      const judged = d.judgedBy.map((j) => `${j.record}: ${value(d.field, j.value)}`).join('<br>');
      const differ = d.differ.map((x) => `${x.record}: ${value(d.field, x.value)}`).join('<br>');
      out.push(`| ${short(d.project)} | ${d.field} | ${cell(judged)} | ${cell(differ)} | ${cell(d.agree.join(', ') || 'none')} | ${d.owner} |`);
    }
    out.push('');
  }
  out.push('## Every Project and field', '');
  out.push('| Project | Field | Verdict | Page shows | Records hold |', '|---|---|---|---|---|');
  for (const r of report.rows) out.push(`| ${short(r.project)} | ${r.field} | ${r.verdict} | ${cell(r.page)} | ${cell(r.record)} |`);
  out.push('', 'Projects:', ...report.projects.map((id) => `- ${id} (${report.rows.find((r) => r.project === id)?.workflow ?? ''})`), '');
  out.push('## Where each field comes from', '');
  out.push('| Field | Where the page shows it | What the Team API builds it from | Checked against |', '|---|---|---|---|');
  for (const [f, page, api, rec] of FIELD_TABLE) out.push(`| ${f} | ${cell(page)} | ${cell(api)} | ${cell(rec)} |`);
  out.push(
    '',
    "Costs are compared to the cent: the page's amount must be the recorded model calls' sum rounded to the cent. " +
      "Stop words are compared verbatim, each run of whitespace as one space, and who gave them by the quote's caption. " +
      "A member card is at work when its chip says Working, Working on a retry or Finishing its turn; whether an idle member is idle, ready or held is left to a person, since only the Team API tells them apart. " +
      "The Team API is read for the team's stop record (owner_actions) and otherwise only to name a gap's likely cause: page bug (the Team API agrees with the records), " +
      "Team API bug (it agrees with the page), engine record bug (two of Temper's records disagree), no record. " +
      "For the result, the Team API's outcome is the team's own outcome record (pi_team_outcomes) as it is, " +
      "so where it differs from the run's record or the stop record, two records disagree. " +
      'Exit 1 only for a page mismatch or a missing record; records that disagree with each other alone exit 0.',
    '',
  );
  return out.join('\n');
}
