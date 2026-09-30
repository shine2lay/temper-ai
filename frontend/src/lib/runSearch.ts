/**
 * Finding your way around a big run.
 *
 * A run of eighty nodes is a wall: the only way to the one that failed used
 * to be scrolling and hoping. These are the plain functions behind the run
 * page's find bar — what a word matches, which node comes next, what a
 * status filter keeps, and where the trouble is. No React, no React Flow, so
 * they can be read and tested on their own.
 *
 * Nothing here removes a node. Everything is expressed as "which ids are
 * lit"; the page dims the rest, so the shape of the run stays whole.
 */

import type { AgentExecution, NodeExecution } from '@/types';

/** The status filter's choices, in the order the bar shows them. */
export type StatusFilter = 'all' | 'running' | 'failed' | 'waiting';

/** A node as the graph holds it — React Flow's shape, only what we read. */
export interface GraphNode {
  id: string;
  type?: string;
  parentId?: string;
  position?: { x: number; y: number };
  data?: unknown;
}

/** One node of the drawn graph, reduced to what finding needs. */
export interface FindEntry {
  /** The id the graph draws it under (the node execution's id). */
  id: string;
  /** The container it sits in, if any. */
  parentId?: string;
  /** What the workflow calls it. */
  name: string;
  /** The agent's own name, when it differs from the node's. */
  agentName?: string | null;
  /** The model the agent ran on, as the card shows it. */
  model?: string | null;
  /** Its provider, so "anthropic" finds every Claude node. */
  provider?: string | null;
  status: string;
  /** True while a person still has to answer its gate. */
  gateWaiting?: boolean;
  kind: 'stage' | 'agent';
}

/**
 * The drawn graph, reduced to what finding needs, in the order it reads:
 * left to right along the run, and inside a stage, its agents in turn.
 *
 * It reads the same fields the cards show — the node's name, the agent's own
 * name, the model and provider on its badge — so anything you can see on a
 * card, you can type.
 */
export function buildFindEntries(nodes: GraphNode[]): FindEntry[] {
  const entries: FindEntry[] = [];
  const at = new Map<string, { x: number; y: number }>();

  for (const node of nodes) {
    const data = node.data as
      | { stage?: NodeExecution; agent?: AgentExecution | null }
      | undefined;
    const execution = data?.stage;
    if (!execution) continue;
    const isAgent = node.type === 'agentNode';
    const agent = isAgent ? data?.agent ?? null : null;
    const snapshot = agent?.agent_config_snapshot?.agent;

    at.set(node.id, { x: node.position?.x ?? 0, y: node.position?.y ?? 0 });
    entries.push({
      id: node.id,
      parentId: node.parentId,
      name: execution.name ?? execution.stage_name ?? node.id,
      agentName: agent?.agent_name ?? agent?.name ?? null,
      model: snapshot?.model ?? null,
      provider: snapshot?.provider ?? null,
      status: nodeStatus(execution, agent),
      gateWaiting: execution.gate_status === 'waiting',
      kind: isAgent ? 'agent' : 'stage',
    });
  }

  return readingOrder(entries, at);
}

/**
 * The one status of a node, when the node and its agent each have one.
 *
 * Either of them failing is trouble — a script that exits non-zero marks the
 * node while the agent record can still read as finished — and otherwise the
 * agent's own status is the one its card shows.
 */
function nodeStatus(node: NodeExecution, agent: AgentExecution | null): string {
  if (FAILED.has(node.status) || (agent && FAILED.has(agent.status))) return 'failed';
  return agent?.status ?? node.status;
}

/**
 * Graph order: each level left to right, then top to bottom, with a stage
 * followed by what is inside it.
 *
 * The layout engine hands its nodes back in whatever order it solved them,
 * which is not the order a person reads the run in — and "3 of 11" only
 * makes sense if stepping walks the run the way the eye does.
 */
function readingOrder(
  entries: FindEntry[],
  at: Map<string, { x: number; y: number }>,
): FindEntry[] {
  const byParent = new Map<string, FindEntry[]>();
  const known = new Set(entries.map((e) => e.id));
  for (const entry of entries) {
    // A node whose container the graph did not draw reads as top level.
    const key = entry.parentId && known.has(entry.parentId) ? entry.parentId : '';
    const list = byParent.get(key) ?? [];
    list.push(entry);
    byParent.set(key, list);
  }

  const sortLevel = (list: FindEntry[]) =>
    [...list].sort((a, b) => {
      const pa = at.get(a.id) ?? { x: 0, y: 0 };
      const pb = at.get(b.id) ?? { x: 0, y: 0 };
      return pa.x - pb.x || pa.y - pb.y || a.name.localeCompare(b.name);
    });

  const out: FindEntry[] = [];
  const walk = (key: string) => {
    for (const entry of sortLevel(byParent.get(key) ?? [])) {
      out.push(entry);
      walk(entry.id);
    }
  };
  walk('');
  return out;
}

/** Statuses that mean "still going", for the filter and the trouble jump. */
const RUNNING = new Set(['running', 'cancelling', 'resuming']);
/** Statuses that mean "it went wrong". */
const FAILED = new Set(['failed', 'timeout', 'orphaned']);
/** Statuses that mean "nobody is working on it until a person acts". */
const WAITING = new Set(['waiting', 'paused']);

/** What a search word is compared against, all of it lowercased. */
export function haystack(entry: FindEntry): string[] {
  return [entry.name, entry.agentName, entry.model, entry.provider]
    .filter((v): v is string => typeof v === 'string' && v.length > 0)
    .map((v) => v.toLowerCase());
}

/**
 * Does this node answer to that word?
 *
 * Case does not matter and part of a word is enough: "pitch" finds
 * `pitch_b133`, "SONNET" finds `claude-sonnet-4-5`.
 */
export function entryMatches(entry: FindEntry, query: string): boolean {
  const term = query.trim().toLowerCase();
  if (!term) return false;
  return haystack(entry).some((field) => field.includes(term));
}

/** Does this node pass the status filter? */
export function entryPassesStatus(entry: FindEntry, filter: StatusFilter): boolean {
  if (filter === 'all') return true;
  if (filter === 'running') return RUNNING.has(entry.status);
  if (filter === 'failed') return FAILED.has(entry.status);
  return WAITING.has(entry.status) || entry.gateWaiting === true;
}

/**
 * The nodes a word finds, in the order the graph lists them.
 *
 * The status filter narrows them too, so "3 of 11" always counts the same
 * nodes the page is lighting up.
 */
export function findMatches(
  entries: FindEntry[],
  query: string,
  filter: StatusFilter = 'all',
): string[] {
  if (!query.trim()) return [];
  const out: string[] = [];
  for (const entry of entries) {
    if (entryMatches(entry, query) && entryPassesStatus(entry, filter)) out.push(entry.id);
  }
  return out;
}

/**
 * The live panel's agent rows, narrowed by the same word and filter.
 *
 * The panel lists agents the graph has no room for (an earlier round of a
 * loop), so it cannot simply reuse the graph's matches; it runs the same
 * rules over its own rows, and the two stay in step.
 *
 * Answers null when nothing is narrowing, which the panel reads as "show
 * everything at full strength".
 */
export function litRosterIds(
  groups: RosterLike[],
  query: string,
  filter: StatusFilter,
): Set<string> | null {
  const word = query.trim();
  if (!word && filter === 'all') return null;

  const lit = new Set<string>();
  for (const group of groups) {
    for (const agent of group.agents) {
      const entry: FindEntry = {
        id: agent.id,
        // Its stage's name counts as its own: typing a stage name should
        // bring up the agents that ran in it, as it does on the graph.
        name: group.name,
        agentName: agent.name,
        model: agent.model ?? null,
        status: agent.status,
        kind: 'agent',
      };
      const hit = word ? entryMatches(entry, word) : true;
      if (hit && entryPassesStatus(entry, filter)) lit.add(agent.id);
    }
  }
  return lit;
}

/** The live panel's list, as much of it as narrowing needs. */
export interface RosterLike {
  name: string;
  agents: { id: string; name: string; model?: string | null; status: string }[];
}

/**
 * The next match after the one you are on, going round at the end.
 *
 * On nothing found it answers null; on a node that is no longer a match
 * (the word changed under you) it starts from the top.
 */
export function stepMatch(
  matches: string[],
  current: string | null,
  direction: 1 | -1 = 1,
): string | null {
  if (matches.length === 0) return null;
  const at = current ? matches.indexOf(current) : -1;
  if (at === -1) return direction === 1 ? matches[0] : matches[matches.length - 1];
  const next = (at + direction + matches.length) % matches.length;
  return matches[next];
}

/** Which match you are on, counting from 1; 0 when you are on none. */
export function matchPosition(matches: string[], current: string | null): number {
  if (!current) return 0;
  const at = matches.indexOf(current);
  return at === -1 ? 0 : at + 1;
}

/**
 * Where the trouble is: every failed node in run order.
 *
 * Nothing failed means nothing is wrong yet, so it offers what is running
 * instead, and on a run parked at a gate, what is waiting for a person.
 */
export function troubleOrder(entries: FindEntry[]): string[] {
  const failed = entries.filter((e) => FAILED.has(e.status)).map((e) => e.id);
  if (failed.length > 0) return failed;
  const running = entries.filter((e) => RUNNING.has(e.status)).map((e) => e.id);
  if (running.length > 0) return running;
  return entries
    .filter((e) => WAITING.has(e.status) || e.gateWaiting === true)
    .map((e) => e.id);
}

/** What the trouble button is pointing at, for its label and its title. */
export function troubleKind(entries: FindEntry[]): 'failed' | 'running' | 'waiting' | 'none' {
  if (entries.some((e) => FAILED.has(e.status))) return 'failed';
  if (entries.some((e) => RUNNING.has(e.status))) return 'running';
  if (entries.some((e) => WAITING.has(e.status) || e.gateWaiting === true)) return 'waiting';
  return 'none';
}

/**
 * The ids to keep bright, or null when nothing is narrowing the view.
 *
 * Around a hit the page keeps its family: the stages a matching agent sits
 * in stay bright so you can see where it is, and a stage found by name
 * brings its agents with it — otherwise "pitch_b133" would light an empty
 * box. The status filter is stricter: only the node itself and the stages
 * it sits in, or a failed agent would light every sibling.
 */
export function litIds(
  entries: FindEntry[],
  query: string,
  filter: StatusFilter,
): Set<string> | null {
  const searching = query.trim().length > 0;
  const filtering = filter !== 'all';
  if (!searching && !filtering) return null;

  const byId = new Map(entries.map((e) => [e.id, e]));
  const childrenOf = new Map<string, string[]>();
  for (const entry of entries) {
    if (!entry.parentId) continue;
    const list = childrenOf.get(entry.parentId) ?? [];
    list.push(entry.id);
    childrenOf.set(entry.parentId, list);
  }

  const lit = new Set<string>();
  const keepAncestors = (id: string) => {
    let parent = byId.get(id)?.parentId;
    while (parent && !lit.has(parent)) {
      lit.add(parent);
      parent = byId.get(parent)?.parentId;
    }
  };
  const keepDescendants = (id: string) => {
    const stack = [...(childrenOf.get(id) ?? [])];
    while (stack.length) {
      const child = stack.pop()!;
      if (lit.has(child)) continue;
      lit.add(child);
      stack.push(...(childrenOf.get(child) ?? []));
    }
  };

  for (const entry of entries) {
    const hit = searching ? entryMatches(entry, query) : true;
    if (!hit || !entryPassesStatus(entry, filter)) continue;
    lit.add(entry.id);
    keepAncestors(entry.id);
    // A stage found by name brings what is inside it; a status filter does not.
    if (searching && !filtering && entry.kind === 'stage') keepDescendants(entry.id);
  }
  return lit;
}
