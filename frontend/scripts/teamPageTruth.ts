/**
 * Team page truth check: does the Team page show what Temper's own records hold?
 *
 * The comparing half of scripts/team-page-truth.mjs, kept free of the browser and of
 * Node so the unit tests (src/__tests__/teamPageTruth.test.ts) can feed it known answers.
 *
 * The page side is what a person sees: the Team list and each Project's run view, read
 * from the rendered pages by role, label and text. The record side is Temper's
 * lower-level records, never the Team API (/api/team/*), which builds the page:
 *   - the run list (GET /api/workflows): each run's status and total_cost_usd;
 *   - the run (GET /api/workflows/{id}): its nodes' cost, workflow_output, stopped, error_message;
 *   - its turns (GET /api/workflows/{id}/agents): each member's turns and their cost;
 *   - its waits (GET /api/runs/{id}/gates, and /decisions for the ones still waiting);
 *   - its configs (GET /api/studio/configs/workflow/<name> and .../agent/<name>): members, roles, leader.
 * The Team API is read only to say where a gap most likely comes from. Where two records
 * disagree, the report names both and picks neither.
 *
 * Five fields per Project (members, state, waits, cost, result), plus whether the Team list
 * shows the Project at all ("listed"). No model calls: every check here is a rule.
 */

export const FIELDS = ['listed', 'members', 'state', 'waits', 'cost', 'result'] as const;
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

/** What Temper's lower-level records hold for one team-trial-* run. */
export interface ProjectRecords {
  executionId: string;
  workflow: string;
  /** The run list's status and total_cost_usd. */
  status: string;
  costUsd: number | null;
  /** GET /api/workflows/{id}; null when it couldn't be read. */
  detail: {
    status: string | null;
    costUsd: number | null;
    /** The sum of its top-level nodes' cost_usd. */
    nodeCostUsd: number | null;
    /** workflow_output.decision. */
    decision: string | null;
    /** workflow_output.reason, else (not completed) stopped.reason, else error_message. */
    reason: string | null;
    reasonFrom: string | null;
  } | null;
  /** GET /api/workflows/{id}/agents, per agent_name: turns and their summed estimated_cost_usd. */
  turns: Record<string, { turns: number; costUsd: number }> | null;
  /** The workflow config's agents, each agent config's role, and the strategy's leader. */
  members: RecordMember[] | null;
  /** GET /api/runs/{id}/gates: each open wait and the member that asked it ("qa asks"). */
  openWaits: Array<{ node: string; asker: string | null }> | null;
  /** GET /api/runs/{id}/decisions still "waiting". */
  waitingDecisions: number | null;
}

/** The Team API's view of a Project: read only to say where a gap comes from. */
export interface TeamApiProject {
  listed: boolean;
  members: Array<{ name: string; role: string | null; leader: boolean; costUsd: number | null }> | null;
  state: string | null;
  runStatus: string | null;
  costUsd: number | null;
  openWaits: number | null;
  decision: string | null;
  reason: string | null;
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

export interface Report {
  base: string;
  at: string;
  runListTotal: number;
  projects: string[];
  rows: Row[];
  totals: Record<Verdict, number>;
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

  const turnSum = (r: ProjectRecords) => (r.turns ? Object.values(r.turns).reduce((s, t) => s + t.costUsd, 0) : null);
  const sources = (r: ProjectRecords): Array<[string, number]> =>
    (
      [
        ['run list total_cost_usd', r.costUsd],
        ['run total_cost_usd', r.detail?.costUsd ?? null],
        ['node cost_usd', r.detail?.nodeCostUsd ?? null],
        ['turns (agents) sum', turnSum(r)],
      ] as Array<[string, number | null]>
    ).filter((s): s is [string, number] => s[1] !== null);
  const recordWords = (r: ProjectRecords) =>
    [
      sources(r)
        .map(([k, v]) => `${k} ${usd(v)}`)
        .join('; '),
      r.turns
        ? `per member: ${Object.entries(r.turns)
            .map(([n, t]) => `${n} ${usd(t.costUsd)}`)
            .join(', ')}`
        : '',
    ]
      .filter(Boolean)
      .join('; ');
  const record = recordWords(rec) || 'none';
  if (rec.costUsd === null) return noRecord(page, record, "the run list's total_cost_usd is missing");

  // A running Project's numbers move while the page is read: an amount that matches either read of
  // the records, or lies between them, counts as right.
  const fits = (v: number | null, a: number, b: number | null): boolean =>
    v !== null && (sameCent(v, a) || (b !== null && (sameCent(v, b) || (v >= Math.min(a, b) && v <= Math.max(a, b)))));
  const memberCost = (r: ProjectRecords | undefined, name: string): number | null =>
    r?.turns ? (r.turns[name]?.costUsd ?? 0) : null;
  const total = rec.costUsd;
  const totalAfter = after?.costUsd ?? null;
  const gaps: string[] = [];
  for (const t of shownTotals) {
    if (!fits(parseMoney(t.value), total, totalAfter)) {
      gaps.push(`${t.place} shows ${t.value}; the run list's total_cost_usd is ${usd(total)}`);
    }
  }
  for (const m of shownMembers) {
    const want = memberCost(rec, m.name);
    if (want === null) continue;
    if (!fits(parseMoney(m.cost), want, memberCost(after, m.name))) {
      gaps.push(`the run view shows ${m.name} ${m.cost}; its turns (agents record) cost ${usd(want)}`);
    }
  }
  if (gaps.length === 0) return result(page, record, [], null, null);

  const vals = sources(rec);
  const split = vals.some(([, a]) => vals.some(([, b]) => !sameCent(a, b)));
  if (split) {
    return result(
      page,
      record,
      gaps,
      'engine record bug',
      `Temper's own records disagree (${vals.map(([k, v]) => `${k} ${usd(v)}`).join(', ')}); which one is right is the temper role's call${
        api?.costUsd != null ? `; the Team API says ${usd(api.costUsd)}` : ''
      }`,
    );
  }
  if (!api || api.costUsd === null) return result(page, record, gaps, 'not known', 'the Team API was not read');
  return sameCent(api.costUsd, rec.costUsd)
    ? result(page, record, gaps, 'page bug', `the Team API says ${usd(api.costUsd)}, as the records do`)
    : result(page, record, gaps, 'Team API bug', `the Team API says ${usd(api.costUsd)}`);
}

function statusDecision(status: string): string | null {
  return ({ completed: 'done', cancelled: 'cancelled', failed: 'failed' } as Record<string, string>)[status] ?? null;
}

function resultField(rec: ProjectRecords, view: PageRunView | undefined, api: TeamApiProject | undefined): FieldResult {
  const ended = ENDED.has(recordStateClass(rec.status));
  const shown = view
    ? view.problem
      ? `not read (${view.problem})`
      : view.outcomeWord
        ? `${view.outcomeWord}${view.outcomeReason ? ` \u2014 "${cut(view.outcomeReason)}"` : ''}`
        : 'no outcome'
    : 'not read';
  if (!ended) {
    const page = `run view: ${shown}`;
    const gaps =
      view?.outcomeWord && ENDED.has(pageStateClass(view.outcomeWord))
        ? [`the run view shows an outcome (${view.outcomeWord}); the run list says ${rec.status}`]
        : [];
    return result(page, `not ended (run list: ${rec.status})`, gaps, gaps.length ? 'not known' : null, gaps.length ? 'the run has no result yet' : null);
  }
  const decision = rec.detail?.decision ?? statusDecision(rec.status);
  const decisionFrom = rec.detail?.decision ? 'workflow_output.decision' : 'run list status';
  const reason = genuineReason(rec.detail?.reason);
  const record = `${decision ?? 'no decision'} (${decisionFrom})${reason ? `; reason (${rec.detail?.reasonFrom}): "${cut(reason)}"` : '; no reason'}`;
  const page = `run view: ${shown}`;
  if (!rec.detail) return noRecord(page, record, 'GET /api/workflows/{id} could not be read');

  const gaps: string[] = [];
  if (!view || view.problem) gaps.push(`the run view wasn't read${view?.problem ? `: ${view.problem}` : ''}`);
  else {
    if (!view.outcomeWord) gaps.push(`the run view shows no outcome; record: ${decision}`);
    else if (!stateAgrees(pageStateClass(view.outcomeWord), recordStateClass(null, decision))) {
      gaps.push(`the run view's outcome is ${view.outcomeWord}; record decision: ${decision}`);
    }
    if (reason && !showsReason(view.outcomeText, reason)) {
      gaps.push(`the run view doesn't show the reason "${cut(reason)}" (${rec.detail.reasonFrom}); it says "${cut(view.outcomeReason) || 'no reason'}"`);
    }
  }
  if (gaps.length === 0) return result(page, record, [], null, null);
  if (!api) return result(page, record, gaps, 'not known', 'the Team API was not read');
  const apiReason = genuineReason(api.reason);
  const apiHasReason = !reason || (apiReason !== null && showsReason(apiReason, reason));
  const apiDecisionOk = api.decision !== null && stateAgrees(recordStateClass(null, api.decision), recordStateClass(null, decision));
  if (apiHasReason && apiDecisionOk) return result(page, record, gaps, 'page bug', "the Team API's outcome matches the record");
  if (api.decision === null) return result(page, record, gaps, 'not known', 'the Team API has no outcome for this ended run');
  // The Team API serves the team's own outcome record (pi_team_outcomes) as it is: when that
  // differs from the run's record, two of Temper's records disagree.
  return result(
    page,
    record,
    gaps,
    'engine record bug',
    `two records disagree: the team's outcome record (pi_team_outcomes, as the Team API serves it) says ${api.decision}${
      api.reason ? ` "${cut(api.reason, 80)}"` : ' with no reason'
    }; the run's record says ${decision}${reason ? ` "${cut(reason, 80)}" (${rec.detail.reasonFrom})` : ''}; which one the page should show is the temper role's call`,
  );
}

// ---------------------------------------------------------------- the report

/** Compare every Project's five fields (and whether it is listed). */
export function compareAll(input: CheckInput): Report {
  const only = input.only && input.only.length > 0 ? new Set(input.only) : null;
  const ids = Object.keys(input.records).filter((id) => !only || only.has(id));
  const rows: Row[] = [];
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
  return { base: input.base, at: input.at, runListTotal: input.runListTotal, projects: ids, rows, totals };
}

/** 0 when nothing mismatches ("no record" rows don't fail it), 1 when anything does. */
export function exitCode(report: Report): number {
  return report.totals.mismatch > 0 ? 1 : 0;
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
    'run list total_cost_usd (also the run\'s total_cost_usd, its nodes\' cost_usd and the turns record, compared with each other); per member: the turns record (GET /api/workflows/{id}/agents) summed per agent_name',
  ],
  [
    'result',
    'run view: flow "Now" word with its sentence (and an interrupted run\'s reason), rounds outcome card heading and "Temper\'s reason"',
    'outcome_view(): the pi_team_outcomes row (decision, reason)',
    'workflow_output.decision and .reason; for a run that didn\'t complete, stopped.reason, else error_message',
  ],
];

function cell(s: string | null | undefined): string {
  return (s ?? '').replace(/\|/g, '\\|').replace(/\s*\n\s*/g, ' ');
}

/** The report as Markdown: totals, the gaps, every Project and field, and the field table. */
export function toMarkdown(report: Report): string {
  const short = (id: string) => (id.length > 8 && id !== '(all)' ? id.slice(0, 8) : id);
  const out: string[] = [];
  out.push('# Team page truth check', '');
  out.push(`Temper ${report.base}, read ${report.at}. Projects checked: ${report.projects.length} (the run list holds ${report.runListTotal} runs).`);
  out.push(
    `Rows (Project \u00d7 field): ${report.totals.match} match, ${report.totals.mismatch} mismatch, ${report.totals['no record']} no record. ` +
      (report.totals.mismatch > 0 ? 'Exit 1: something mismatches.' : 'Exit 0: nothing mismatches.'),
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
  out.push('## Every Project and field', '');
  out.push('| Project | Field | Verdict | Page shows | Records hold |', '|---|---|---|---|---|');
  for (const r of report.rows) out.push(`| ${short(r.project)} | ${r.field} | ${r.verdict} | ${cell(r.page)} | ${cell(r.record)} |`);
  out.push('', 'Projects:', ...report.projects.map((id) => `- ${id} (${report.rows.find((r) => r.project === id)?.workflow ?? ''})`), '');
  out.push('## Where each field comes from', '');
  out.push('| Field | Where the page shows it | What the Team API builds it from | Checked against |', '|---|---|---|---|');
  for (const [f, page, api, rec] of FIELD_TABLE) out.push(`| ${f} | ${cell(page)} | ${cell(api)} | ${cell(rec)} |`);
  out.push(
    '',
    'Costs are compared to the cent: the page\'s amount must be the record rounded to the cent. ' +
      'Where Temper\'s records disagree with each other, the report names every value and picks none. ' +
      'The Team API is read only to name the likely cause: page bug (the Team API agrees with the records), ' +
      'Team API bug (it agrees with the page), engine record bug (the records disagree), no record. ' +
      "For the result, the Team API's outcome is the team's own outcome record (pi_team_outcomes) as it is, " +
      "so where it differs from the run's record, two records disagree.",
    '',
  );
  return out.join('\n');
}
