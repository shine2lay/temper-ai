/**
 * The Trials tab (Design's SPEC 4, boards T1-T3b): one row per run of a
 * trial's workflow, newest first. team_trials lists a trial's own run and
 * then its re-runs and forks from the run page (contract A-8), next to each
 * other; the page shows those as sub-rows under their trial.
 */
import { formatNumber, WAIT_STATES } from './teamText';
import type { TeamRunKind, TeamTrialItem } from '@/types/team';

export const TRIALS_PAGE_SIZE = 25;

/** How often the open Trials tab reads the list again (SPEC 6). */
export const TEAM_TRIALS_POLL_MS = 5_000;

export interface TrialsRead {
  limit: number;
  offset: number;
  /** Items read before the page, only to know whether its first row continues a trial. */
  lead: number;
}

/**
 * The read for page `page` (0-based). A page after the first also reads
 * the item just before it: when that item is the same trial, the page's
 * first row is a re-run or fork whose trial row is on the page before.
 */
export function trialsRead(page: number, size: number = TRIALS_PAGE_SIZE): TrialsRead {
  const offset = Math.max(0, Math.floor(page)) * size;
  const lead = offset > 0 ? 1 : 0;
  return { limit: size + lead, offset: offset - lead, lead };
}

export interface TrialRow {
  item: TeamTrialItem;
  /** A re-run or fork of the trial in the row above. */
  sub: boolean;
  /** A sub-row whose trial row is on the page before: it names its trial. */
  orphan: boolean;
}

/** One group per trial on the page: its own run's row (unless it is on the page before) and its re-runs. */
export interface TrialGroup {
  key: string;
  head: TrialRow | null;
  subs: TrialRow[];
}

/** The page's rows, from the items read (the first `lead` are only context). */
export function trialRows(items: TeamTrialItem[], lead: number): TrialRow[] {
  const rows: TrialRow[] = [];
  for (let i = lead; i < items.length; i += 1) {
    const prev = i > 0 ? items[i - 1] : null;
    const sub = prev !== null && prev.trial_id === items[i].trial_id;
    rows.push({ item: items[i], sub, orphan: sub && i === lead });
  }
  return rows;
}

/** The rows grouped under their trials, in order. */
export function trialGroups(rows: TrialRow[]): TrialGroup[] {
  const groups: TrialGroup[] = [];
  for (const row of rows) {
    const last = groups[groups.length - 1];
    // A sub-row's trial is the row above it, so the group before (an orphan has none).
    if (row.sub && last) last.subs.push(row);
    else
      groups.push({
        key: `${row.item.trial_id}:${row.item.execution_id}`,
        head: row.sub ? null : row,
        subs: row.sub ? [row] : [],
      });
  }
  return groups;
}

/** A free-flowing team (kind 'flow') has no rounds: its row says nothing about them. */
export function hasRounds(item: Pick<TeamTrialItem, 'kind'>): boolean {
  return item.kind !== 'flow';
}

/** The Round column keeps its name unless every row on the page is a free-flowing team. */
export function roundColumnNamed(rows: readonly TrialRow[]): boolean {
  return rows.length === 0 || rows.some((row) => hasRounds(row.item));
}

/** Whether the row waits for the owner: amber tint and the "needs you" chip. */
export function trialNeedsYou(item: Pick<TeamTrialItem, 'state'>): boolean {
  return WAIT_STATES.has(item.state);
}

/** The run list's status a team state normally comes with; any other is said. */
const RUN_STATUS_OF: Record<string, string> = { done: 'completed', failed: 'failed' };

/**
 * The muted line under a row's state badge (board T1). A stopped row
 * always says the run list's own status, never a guess: a stop reads
 * cancelled, a stop at a member's failed or unfinished turn failed (E18).
 * An old review-round run (kind "rounds", said only by the new engine)
 * can't be resumed (Design's SPEC 14 b 7).
 */
export function trialPhrase(item: Pick<TeamTrialItem, 'state' | 'run_status' | 'kind'>): string | null {
  const status = item.run_status ?? null;
  switch (item.state) {
    case 'quiet':
      return 'nothing left to do';
    case 'interrupted':
      return item.kind === 'rounds' ? "interrupted; this Temper can't resume a round run" : 'resume it from the run page';
    case 'settings_changed':
      return 'settings changed while it waited';
    case 'didnt_start':
      return 'Nothing was spent.';
    case 'stopped':
      return status ? `run list: ${status}` : null;
    default: {
      const usual = RUN_STATUS_OF[item.state];
      return usual && status && status !== usual ? `run list: ${status}` : null;
    }
  }
}

export interface TrialPerson {
  name: string;
  role: string | null;
}

/** The leader and the other members, by team name, with the role when it differs. */
export function trialPeople(item: Pick<TeamTrialItem, 'leader' | 'members'>): {
  leader: TrialPerson | null;
  others: TrialPerson[];
} {
  const members = item.members ?? [];
  const lead = item.leader ? members.find((m) => m.name === item.leader) : undefined;
  return {
    leader: item.leader ? { name: item.leader, role: lead?.role ?? null } : null,
    others: members.filter((m) => m.name !== item.leader).map((m) => ({ name: m.name, role: m.role })),
  };
}

/** "maker (backend)" when the team name isn't the role id, else just the name. */
export function personWords(person: TrialPerson): string {
  return person.role && person.role !== person.name ? `${person.name} (${person.role})` : person.name;
}

/**
 * The line under "No projects yet" when there are none. The new engine's
 * (Design's SPEC 14 b 6) says how a free-flowing team starts; today's
 * server keeps today's words.
 */
export function noProjectsWords(engine: TeamRunKind): string {
  return engine === 'flow'
    ? 'Start one: the leader gets your goal and messages the others their work, and Temper checks in with you as spend grows.'
    : "A project puts a few pi roles on one goal. They work in rounds, review each other's work and stop when the leader's version is approved. Start one with New project at the top right.";
}

/** The footer: "Showing 1–25 of 57 · newest first". */
export function showingWords(offset: number, count: number, total: number): string {
  const of = formatNumber(total);
  if (count === 0) return `Showing 0 of ${of} · newest first`;
  return `Showing ${formatNumber(offset + 1)}–${formatNumber(offset + count)} of ${of} · newest first`;
}

/** The last page that has rows (0-based). */
export function lastTrialsPage(total: number, size: number = TRIALS_PAGE_SIZE): number {
  return Math.max(0, Math.ceil(total / size) - 1);
}
