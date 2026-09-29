/**
 * Which agents the run page shows as at work, and what it calls them.
 */
import type { AgentExecution, StreamEntry } from '@/types';

/** What the page calls an agent: its name, never its id. */
export function agentDisplayName(
  agent: Pick<AgentExecution, 'agent_name' | 'name'> | null | undefined,
): string | null {
  return agent?.agent_name || agent?.name || null;
}

/** Shown for an agent the server could not name either. */
export const UNNAMED_AGENT = 'unnamed agent';

/** Agent statuses after which it streams nothing more. */
const STOPPED = new Set<string>([
  'completed',
  'failed',
  'cancelled',
  'interrupted',
  'orphaned',
  'skipped',
  'timeout',
]);

/** Run statuses in which its agents can still be at work. */
const RUN_ACTIVE = new Set<string>([
  'running',
  'queued',
  'pending',
  'waiting',
  'resuming',
  'cancelling',
]);

export interface LiveAgent {
  id: string;
  name: string;
  entry: StreamEntry;
  agent: AgentExecution;
}

/**
 * The agents at work, for the live strip and the header: each agent with
 * streamed output that its record says is still going, while the run is.
 *
 * The record, not the stream, says when an agent is done. A done chunk ends
 * one model call and an agent makes many, so the strip used to drop an
 * agent after its first call. An agent with no record yet is left out until
 * the page has looked it up (useAgentLookup), so it never shows as an id.
 */
export function liveAgents(
  streamingContent: Map<string, StreamEntry>,
  agents: Map<string, AgentExecution>,
  runStatus: string | undefined,
): LiveAgent[] {
  if (runStatus && !RUN_ACTIVE.has(runStatus)) return [];
  const out: LiveAgent[] = [];
  for (const [id, entry] of streamingContent) {
    const agent = agents.get(id);
    if (!agent || STOPPED.has(agent.status)) continue;
    out.push({ id, name: agentDisplayName(agent) ?? UNNAMED_AGENT, entry, agent });
  }
  // Two at work under one name (parallel lanes, a loop's next round):
  // their round tells them apart.
  const seen = new Map<string, number>();
  for (const live of out) seen.set(live.name, (seen.get(live.name) ?? 0) + 1);
  for (const live of out) {
    if ((seen.get(live.name) ?? 0) > 1 && live.agent.round) {
      live.name = `${live.name} #${live.agent.round}`;
    }
  }
  return out;
}
