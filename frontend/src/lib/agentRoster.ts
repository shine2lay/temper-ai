/**
 * The run's agents as the live panel lists them: grouped by the stage they
 * belong to, in run order, each with what it is doing right now.
 */
import type { AgentExecution, NodeExecution } from '@/types';
import type { AgentStory, StoryItem } from '@/lib/agentStory';
import { toolStepLabel } from '@/lib/toolLabels';
import { agentDisplayName, UNNAMED_AGENT } from '@/lib/liveAgents';

const TERMINAL = new Set(['completed', 'failed', 'skipped', 'cancelled', 'timeout', 'interrupted', 'orphaned']);

export function isFinished(status: string | undefined): boolean {
  return TERMINAL.has(status ?? '');
}

export interface RosterAgent {
  id: string;
  /** Its name, and the round when its name is used more than once. */
  name: string;
  roundLabel: string | null;
  status: string;
  /** What it is doing now, in a few words. */
  step: string;
  busy: boolean;
  startTime: string | null;
  durationSeconds: number | null;
  costUsd: number;
  /** When it last said or did anything — who to follow. */
  lastActivity: number;
}

export interface RosterGroup {
  /** The node's id, or its name when the page has no record of it. */
  key: string;
  name: string;
  status: string;
  agents: RosterAgent[];
  /** Every agent of the group has ended. */
  finished: boolean;
}

/** How an agent that has stopped is spoken of. */
export function statusWord(status: string): string {
  if (status === 'completed') return 'Done';
  if (status === 'failed') return 'Failed';
  if (status === 'cancelled') return 'Cancelled';
  if (status === 'skipped') return 'Skipped';
  return status;
}

/** What the agent is doing now, from the last thing in its story. */
export function currentStep(items: StoryItem[] | undefined, status: string): string {
  const last = items && items.length > 0 ? items[items.length - 1] : undefined;
  if (!last) return isFinished(status) ? '' : 'Starting';
  if (last.kind === 'tool') return toolStepLabel(last.toolName, last.args);
  if (last.kind === 'thinking') return last.closed ? 'Thinking' : 'Thinking…';
  return last.closed ? 'Writing' : 'Writing…';
}

function lastActivityAt(story: AgentStory | undefined, agent: AgentExecution): number {
  const items = story?.items ?? [];
  for (let i = items.length - 1; i >= 0; i--) {
    const at = items[i].at;
    if (at) {
      const t = Date.parse(at);
      if (!Number.isNaN(t)) return t;
    }
  }
  const started = agent.start_time ? Date.parse(agent.start_time) : NaN;
  return Number.isNaN(started) ? 0 : started;
}

/**
 * Every agent of the run, grouped by stage in run order.
 *
 * The agent index gives agents the drawn tree has no room for (an earlier
 * round of a loop, a lane that has since ended), so the list is complete
 * even when the graph is not.
 */
export function buildRoster(
  stages: Map<string, NodeExecution>,
  agents: Map<string, AgentExecution>,
  stories: Map<string, AgentStory>,
): RosterGroup[] {
  const groups = new Map<string, RosterGroup>();
  const order: string[] = [];

  // Stage order first, so groups read in the order the run ran them.
  for (const [id, node] of stages) {
    if (node.type === 'stage' || node.type === 'agent' || node.type === 'delegate') {
      groups.set(id, { key: id, name: node.name, status: node.status, agents: [], finished: false });
      order.push(id);
    }
  }

  // A stage by its name, so an agent that only knows the name it ran under
  // (an earlier round, a lane the tree dropped) still lands in its stage
  // instead of starting a second group with the same title.
  const byStageName = new Map<string, string>();
  for (const [id, node] of stages) {
    if (!byStageName.has(node.name)) byStageName.set(node.name, id);
  }

  // Where an agent of this name last ran. In a stage of several agents each
  // one runs under its own name ("scout_a"), which is no stage's name; when a
  // loop comes round again, that name is all the index keeps. Matching it to
  // the stage its namesake sits in keeps a round together, instead of giving
  // every agent a group of its own.
  const byAgentName = new Map<string, string>();
  for (const [id, node] of stages) {
    for (const nested of node.agents ?? []) {
      for (const label of [nested.node_name, agentDisplayName(nested)]) {
        if (label && !byAgentName.has(label)) byAgentName.set(label, id);
      }
    }
  }

  const nameCount = new Map<string, number>();
  for (const agent of agents.values()) {
    const name = agentDisplayName(agent) ?? UNNAMED_AGENT;
    nameCount.set(name, (nameCount.get(name) ?? 0) + 1);
  }

  for (const [id, agent] of agents) {
    const nodeId = [agent.stage_id, agent.stage_execution_id]
      .find((candidate) => candidate && stages.has(candidate))
      ?? (agent.node_name ? byStageName.get(agent.node_name) : undefined)
      ?? (agent.node_name ? byAgentName.get(agent.node_name) : undefined)
      ?? byAgentName.get(agentDisplayName(agent) ?? '')
      ?? null;
    const key = nodeId ?? (agent.node_name ? `name:${agent.node_name}` : 'other');
    let group = groups.get(key);
    if (!group) {
      group = {
        key,
        name: agent.node_name ?? 'elsewhere',
        status: agent.status,
        agents: [],
        finished: false,
      };
      groups.set(key, group);
      order.push(key);
    }
    const name = agentDisplayName(agent) ?? UNNAMED_AGENT;
    const story = stories.get(id);
    group.agents.push({
      id,
      name,
      roundLabel: (agent.round ?? 1) > 1 || (nameCount.get(name) ?? 0) > 1
        ? `round ${agent.round ?? 1}`
        : null,
      status: agent.status,
      step: currentStep(story?.items, agent.status),
      busy: !isFinished(agent.status),
      startTime: agent.start_time,
      durationSeconds: agent.duration_seconds,
      costUsd: agent.estimated_cost_usd ?? 0,
      lastActivity: lastActivityAt(story, agent),
    });
  }

  const out: RosterGroup[] = [];
  for (const key of order) {
    const group = groups.get(key);
    if (!group || group.agents.length === 0) continue;
    group.agents.sort((a, b) => {
      const ta = a.startTime ? Date.parse(a.startTime) : 0;
      const tb = b.startTime ? Date.parse(b.startTime) : 0;
      if (ta !== tb) return ta - tb;
      return a.name.localeCompare(b.name);
    });
    group.finished = group.agents.every((a) => !a.busy);
    out.push(group);
  }
  return out;
}

/** The agent the panel follows: the one busy most recently. */
export function newestBusyAgent(groups: RosterGroup[]): string | null {
  let best: RosterAgent | null = null;
  for (const group of groups) {
    for (const agent of group.agents) {
      if (!agent.busy) continue;
      if (!best || agent.lastActivity > best.lastActivity) best = agent;
    }
  }
  return best?.id ?? null;
}

/** How many other agents are working, for the "Now" line. */
export function busyCount(groups: RosterGroup[]): number {
  let n = 0;
  for (const group of groups) for (const agent of group.agents) if (agent.busy) n += 1;
  return n;
}
