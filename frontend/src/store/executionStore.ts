/**
 * Zustand store for workflow execution state.
 * Adapted for v1 composable graph model: nodes instead of stages.
 */
import { create } from 'zustand';
import { immer } from 'zustand/middleware/immer';
import { enableMapSet } from 'immer';
import { MAX_EVENT_LOG_SIZE } from '@/lib/constants';
import { appendChunk, finishTool, newStory, startTool, type AgentStory } from '@/lib/agentStory';
import type { StatusFilter } from '@/lib/runSearch';
import type {
  WorkflowExecution,
  NodeExecution,
  AgentExecution,
  AgentIndexEntry,
  LLMCall,
  ToolCall,
  ToolActivity,
  StreamEntry,
  Selection,
  WSStatus,
  WSEvent,
  EventLogEntry,
} from '@/types';
// getNodeAgents available from types if needed

enableMapSet();

/** The story of one agent, created the first time it says anything. */
function _story(state: { stories: Map<string, AgentStory> }, agentId: string): AgentStory {
  let story = state.stories.get(agentId);
  if (!story) {
    story = newStory();
    state.stories.set(agentId, story);
  }
  return story;
}

// Re-export StageExecution as NodeExecution for backward compat
export type StageExecution = NodeExecution;

interface ExecutionState {
  workflow: WorkflowExecution | null;
  stages: Map<string, NodeExecution>;  // keep name 'stages' for component compat
  /** The nodes that sit inside another node, which `stages` has no key for.
   *
   *  `stages` is what the graph draws: the top level plus the rounds a
   *  dispatcher added, lifted out. A node nested inside another one stays
   *  nested there, so its id was in no map and its panel read "Stage not
   *  found". This map holds exactly those nodes — never a second copy of one
   *  `stages` already has, or a live update would land on one copy and leave
   *  the other stale. Look a stage up through `findStage` / `useStageLookup`,
   *  which read both. Counts and the graph keep reading `stages` alone. */
  nestedStages: Map<string, NodeExecution>;
  agents: Map<string, AgentExecution>;
  llmCalls: Map<string, LLMCall>;
  toolCalls: Map<string, ToolCall>;
  streamingContent: Map<string, StreamEntry>;
  /** Per agent: what it thought, said and did, in the order it happened.
   *  The live panel tells this story; see lib/agentStory.ts. */
  stories: Map<string, AgentStory>;
  selection: Selection | null;
  /**
   * The agent the live panel is pinned to, or null while it follows whichever
   * agent is working. It lives here, not in the panel, so that clicking an
   * agent anywhere on the page (the graph, a stage's list, the side panel)
   * brings the panel with it. The count goes up on every pick, so choosing
   * the same agent twice still scrolls the panel's list to it.
   */
  livePick: { id: string; nonce: number } | null;
  /** Id of the node the cursor is currently over. Drives "hover-to-reveal"
   *  edge highlighting — connected edges go full opacity, others dim. */
  hoveredNodeId: string | null;
  wsStatus: WSStatus;
  eventLog: EventLogEntry[];
  expandedStages: Set<string>;
  /** Node name whose gate modal is open, or null. A gate is asked per node,
   *  not per stage event: a loop re-gates the same name. */
  gateNodeName: string | null;
  /** Node name -> the dispatcher that added it. `dispatch.applied` arrives
   *  before the added nodes start, so the relationship waits here for them. */
  dispatchedByName: Map<string, string>;
  /** When set, the DAG highlights state at this checkpoint sequence. null = show current/live state. */
  checkpointPreview: { sequence: number; completedNodes: Set<string>; failedNodes: Set<string> } | null;
  /** The find bar of the run page: the word typed and the status filter.
   *  It lives here because the graph and the live panel both narrow by it,
   *  and a run of eighty nodes is only findable if they stay in step. */
  findQuery: string;
  findStatus: StatusFilter;
  /** Agents whose output streams in but that the page has no record of
   *  yet: useAgentLookup asks the server who they are. */
  unknownAgentIds: Set<string>;

  applySnapshot: (workflow: WorkflowExecution) => void;
  applyEvent: (msg: WSEvent) => void;
  /** Records for agents of the run's agent index the page does not have. */
  applyAgentIndex: (index: AgentIndexEntry[]) => void;
  /** The server could not name these agents: show their output unnamed. */
  giveUpAgentLookup: (ids: string[]) => void;
  reset: () => void;
  select: (type: Selection['type'], id: string) => void;
  clearSelection: () => void;
  /** Pins the live panel to an agent without opening the side panel. */
  pickLiveAgent: (agentId: string) => void;
  /** The live panel's Follow button: back to whichever agent is working. */
  clearLivePick: () => void;
  setHoveredNodeId: (id: string | null) => void;
  setWSStatus: (partial: Partial<WSStatus>) => void;
  toggleStageExpanded: (stageName: string) => void;
  openGate: (nodeName: string) => void;
  closeGate: () => void;
  setCheckpointPreview: (preview: { sequence: number; completedNodes: Set<string>; failedNodes: Set<string> } | null) => void;
  setFindQuery: (query: string) => void;
  setFindStatus: (status: StatusFilter) => void;
}

/** Extract all agents from a node (handles both agent and stage nodes). */
function _nodeAgents(node: NodeExecution): AgentExecution[] {
  if (node.type === 'agent' && node.agent) return [node.agent];
  return node.agents || [];
}

const TERMINAL = new Set(['completed', 'failed', 'skipped', 'cancelled', 'timeout']);

/** Every node in the tree, parents before their children. */
function _allNodes(nodes: NodeExecution[] | undefined): NodeExecution[] {
  const out: NodeExecution[] = [];
  const walk = (list: NodeExecution[] | undefined) => {
    for (const n of list ?? []) {
      out.push(n);
      walk(n.child_nodes);
    }
  };
  walk(nodes);
  return out;
}

/**
 * The nodes the store keeps: the top level plus every node added at
 * runtime, lifted out of the dispatcher the API nests it in, in the order
 * dispatched. Live events add dispatched nodes at the top level, so a REST
 * refresh has to give the same shape: when it didn't, the counts dropped to
 * the one top-level node and the DAG redrew from a different tree.
 */
function _liftDispatched(nodes: NodeExecution[] | undefined): NodeExecution[] {
  const out: NodeExecution[] = [];
  const seen = new Set<string>();
  const visit = (node: NodeExecution) => {
    const children = node.child_nodes ?? [];
    const lifted = children.filter((c) => c.dispatched_by);
    const kept = children.filter((c) => !c.dispatched_by);
    if (!seen.has(node.id)) {
      seen.add(node.id);
      out.push(lifted.length === 0 ? node : { ...node, child_nodes: kept.length > 0 ? kept : undefined });
    }
    for (const child of lifted) visit(child);
  };
  for (const n of nodes ?? []) visit(n);
  return out;
}

/** A snapshot is older than the live events it may overlap: it can report
 *  running a node the WS already closed. Keep the later truth. */
function _keepFinished<
  T extends { status?: string; end_time?: string | null; duration_seconds?: number | null },
>(prev: T | undefined, next: T): T {
  if (prev && TERMINAL.has(prev.status ?? '') && !TERMINAL.has(next.status ?? '')) {
    return {
      ...next,
      status: prev.status,
      end_time: next.end_time ?? prev.end_time,
      duration_seconds: next.duration_seconds ?? prev.duration_seconds,
    };
  }
  return next;
}

/** For every node, the node it sits in — empty for the top level. */
function _parentOf(nodes: NodeExecution[] | undefined): Map<string, NodeExecution> {
  const parents = new Map<string, NodeExecution>();
  const walk = (list: NodeExecution[] | undefined, parent: NodeExecution | null) => {
    for (const n of list ?? []) {
      if (parent) parents.set(n.id, parent);
      walk(n.child_nodes, n);
    }
  };
  walk(nodes, null);
  return parents;
}

/**
 * The stage an agent belongs to, for "Back to Stage" and for grouping.
 * An agent node the graph draws a box of its own for — a top-level one, or a
 * dispatched round lifted out — is that box. One nested inside a stage has no
 * box of its own, so its agent belongs to the stage around it.
 */
function _agentHome(
  node: NodeExecution,
  parents: Map<string, NodeExecution>,
  drawn: Map<string, NodeExecution>,
): string {
  if (node.type !== 'agent' || drawn.has(node.id)) return node.id;
  let up = parents.get(node.id);
  while (up) {
    if (drawn.has(up.id) || up.type === 'stage') return up.id;
    up = parents.get(up.id);
  }
  return node.id;
}

/** A node as the panels want it: agents always an array, DAG fields filled. */
function _normalizeNode(node: NodeExecution): NodeExecution {
  const normalized = { ...node };
  if (node.type === 'agent' && node.agent && (!node.agents || node.agents.length === 0)) {
    normalized.agents = [node.agent];
  }
  normalized.stage_name = normalized.stage_name ?? normalized.name;
  // Preserve DAG metadata for dependency arrows
  normalized.depends_on = normalized.depends_on ?? [];
  normalized.loop_to = normalized.loop_to ?? undefined;
  normalized.max_loops = normalized.max_loops ?? undefined;
  return normalized;
}

/** The node with this id, wherever it sits: drawn, or inside another node. */
function _findStage(
  state: { stages: Map<string, NodeExecution>; nestedStages: Map<string, NodeExecution> },
  id: string | undefined,
): NodeExecution | undefined {
  if (!id) return undefined;
  return state.stages.get(id) ?? state.nestedStages.get(id);
}

/** A record for an agent known only from the run's agent index. */
function _agentFromIndex(e: AgentIndexEntry, knownNodes: Set<string>): AgentExecution {
  const type = e.agent_type ?? (e.provider || e.model ? 'llm' : undefined);
  return {
    id: e.id,
    agent_name: e.agent_name,
    status: e.status,
    start_time: e.start_time,
    end_time: e.end_time,
    duration_seconds: e.duration_seconds,
    prompt_tokens: e.prompt_tokens ?? 0,
    completion_tokens: e.completion_tokens ?? 0,
    total_tokens: e.total_tokens ?? 0,
    estimated_cost_usd: e.estimated_cost_usd ?? 0,
    total_llm_calls: 0,
    total_tool_calls: 0,
    llm_calls: [],
    tool_calls: [],
    error_message: e.error_message ?? undefined,
    role: e.role ?? undefined,
    round: e.round,
    node_name: e.node_name,
    // Only a node the page has a record of: an earlier round's node is not
    // in the tree at all, but a node nested inside another one is.
    stage_id: e.node_id && knownNodes.has(e.node_id) ? e.node_id : undefined,
    summary_only: true,
    agent_config_snapshot: type || e.provider || e.model
      ? { agent: { type: type ?? undefined, provider: e.provider ?? undefined, model: e.model ?? undefined } }
      : undefined,
  };
}

/**
 * Give every agent of the run's index a record. The tree names only the
 * newest agent of each name, so an earlier loop round or an attempt a
 * resume replaced was known to the page only by the id its output streamed
 * under, and its panel had nothing to open. A record from an earlier
 * snapshot keeps its calls and output; the index brings its status.
 */
function _mergeAgentIndex(
  agents: Map<string, AgentExecution>,
  knownNodes: Set<string>,
  unknown: Set<string>,
  index: AgentIndexEntry[],
  prevAgents: Map<string, AgentExecution>,
): void {
  for (const e of index) {
    const current = agents.get(e.id);
    if (current && !current.summary_only) {
      if (current.round !== e.round || current.node_name !== e.node_name) {
        agents.set(e.id, { ...current, round: e.round, node_name: e.node_name });
      }
      continue;
    }
    const light = _agentFromIndex(e, knownNodes);
    const prev = current ?? prevAgents.get(e.id);
    const next = prev && !prev.summary_only
      ? {
          ...prev,
          status: light.status,
          end_time: light.end_time ?? prev.end_time,
          duration_seconds: light.duration_seconds ?? prev.duration_seconds,
          error_message: light.error_message ?? prev.error_message,
          round: e.round,
          node_name: e.node_name,
        }
      : light;
    agents.set(e.id, _keepFinished(prev, next));
  }
  for (const id of Array.from(unknown)) {
    if (agents.has(id)) unknown.delete(id);
  }
}

/** Streamed thinking, marked where it came in the text. */
function _addThinking(entry: StreamEntry, text: string): void {
  if (!text) return;
  const marks = entry.thinkingMarks ?? (entry.thinkingMarks = []);
  const from = entry.thinking.length;
  const last = marks[marks.length - 1];
  if (last && last.at === entry.content.length && last.to === from) {
    last.to = from + text.length;
  } else {
    marks.push({ at: entry.content.length, from, to: from + text.length });
  }
  entry.thinking += text;
}

/** Fields of a completion or update that describe the thing, not the event. */
function _outcome(data: Record<string, unknown>): Record<string, unknown> {
  const { event_id: _e, parent_id: _p, ...rest } = data;
  void _e;
  void _p;
  return rest;
}

/** Build a full chronological event log from a workflow snapshot. */
function _buildSnapshotEvents(workflow: WorkflowExecution): EventLogEntry[] {
  const events: EventLogEntry[] = [];

  if (workflow.start_time) {
    events.push({
      timestamp: workflow.start_time,
      event_type: 'workflow_start',
      label: workflow.workflow_name,
      data: { execution_id: workflow.id, status: workflow.status },
    });
  }

  for (const node of _allNodes(workflow.nodes)) {
    const nodeLabel = node.name || node.id;

    if (node.start_time) {
      events.push({
        timestamp: node.start_time,
        event_type: 'stage_start',
        label: nodeLabel,
        data: { stage_id: node.id, status: node.status },
      });
    }

    for (const agent of _nodeAgents(node)) {
      const agentLabel = agent.agent_name ?? agent.name ?? agent.id;

      if (agent.start_time) {
        events.push({
          timestamp: agent.start_time,
          event_type: 'agent_start',
          label: agentLabel,
          data: { agent_id: agent.id, stage_id: node.id, status: agent.status },
        });
      }

      for (const llm of agent.llm_calls ?? []) {
        if (llm.start_time) {
          events.push({
            timestamp: llm.start_time,
            event_type: 'llm_call',
            label: llm.model ?? llm.provider ?? '',
            data: { llm_call_id: llm.id, agent_id: agent.id },
          });
        }
      }

      for (const tool of agent.tool_calls ?? []) {
        if (tool.start_time) {
          events.push({
            timestamp: tool.start_time,
            event_type: 'tool_call',
            label: tool.tool_name ?? '',
            data: { tool_execution_id: tool.id, agent_id: agent.id },
          });
        }
      }

      if (agent.end_time) {
        events.push({
          timestamp: agent.end_time,
          event_type: 'agent_end',
          label: agentLabel,
          data: { agent_id: agent.id, stage_id: node.id, status: agent.status },
        });
      }
    }

    if (node.end_time) {
      events.push({
        timestamp: node.end_time,
        event_type: 'stage_end',
        label: nodeLabel,
        data: { stage_id: node.id, status: node.status },
      });
    }
  }

  if (workflow.end_time) {
    events.push({
      timestamp: workflow.end_time,
      event_type: 'workflow_end',
      label: workflow.workflow_name,
      data: { execution_id: workflow.id, status: workflow.status },
    });
  }

  events.sort((a, b) => a.timestamp.localeCompare(b.timestamp));
  return events;
}

export const useExecutionStore = create<ExecutionState>()(
  immer((set) => ({
    workflow: null,
    stages: new Map(),
    nestedStages: new Map(),
    agents: new Map(),
    llmCalls: new Map(),
    toolCalls: new Map(),
    streamingContent: new Map(),
    stories: new Map(),
    selection: null,
    livePick: null,
    wsStatus: { connected: false, reconnectAttempt: 0, lastHeartbeat: null, wsError: null },
    eventLog: [],
    expandedStages: new Set(),
    gateNodeName: null,
    dispatchedByName: new Map(),
    hoveredNodeId: null,
    checkpointPreview: null,
    findQuery: '',
    findStatus: 'all',
    unknownAgentIds: new Set(),

    applySnapshot: (workflow) =>
      set((state) => {
        const prevStages = state.stages;
        const prevNested = state.nestedStages;
        const prevAgents = state.agents;
        const stillActive = !TERMINAL.has(workflow.status ?? '');

        if (!state.workflow) {
          const snapshotEvents = _buildSnapshotEvents(workflow);
          for (const evt of snapshotEvents) {
            state.eventLog.push(evt);
          }
          if (state.eventLog.length > MAX_EVENT_LOG_SIZE) {
            state.eventLog = state.eventLog.slice(-MAX_EVENT_LOG_SIZE);
          }
        }

        state.workflow = workflow;
        state.stages = new Map();
        state.agents = new Map();
        state.llmCalls = new Map();
        state.toolCalls = new Map();

        for (const node of _allNodes(workflow.nodes)) {
          if (node.dispatched_by) state.dispatchedByName.set(node.name, node.dispatched_by);
        }

        for (const node of _liftDispatched(workflow.nodes)) {
          // Store in stages map (backward compat with components)
          const normalizedNode = _normalizeNode(node);
          state.stages.set(normalizedNode.id, _keepFinished(prevStages.get(normalizedNode.id), normalizedNode));
        }

        // Agents of every node, nested ones included: the agents map is
        // looked up by id and counted, it is not what the DAG draws from.
        const parents = _parentOf(workflow.nodes);
        for (const node of _allNodes(workflow.nodes)) {
          const home = _agentHome(node, parents, state.stages);
          for (const raw of _nodeAgents(node)) {
            // Where the snapshot puts an agent is where it belongs: keep that
            // link, so the live panel can group by stage even when the agent
            // record itself does not name one.
            const agent = {
              ...raw,
              stage_execution_id: raw.stage_execution_id ?? home,
              node_name: raw.node_name ?? node.name,
            };
            state.agents.set(agent.id, _keepFinished(prevAgents.get(agent.id), agent));
            for (const llm of agent.llm_calls ?? []) {
              const llmCopy = { ...llm, agent_id: agent.id, agent_execution_id: agent.id };
              state.llmCalls.set(llmCopy.id, llmCopy);
            }
            for (const tool of agent.tool_calls ?? []) {
              state.toolCalls.set(tool.id, { ...tool });
            }
          }
        }

        _mergeAgentIndex(
          state.agents,
          new Set(_allNodes(workflow.nodes).map((n) => n.id)),
          state.unknownAgentIds,
          workflow.agent_index ?? [],
          prevAgents,
        );

        // A poll can be taken just before a node starts and land just
        // after its live start event: keep what the WS added until a
        // snapshot catches up, or the node blinks out for a poll.
        if (stillActive) {
          for (const [id, stage] of prevStages) {
            if (!state.stages.has(id)) state.stages.set(id, stage);
          }
          for (const [id, agent] of prevAgents) {
            if (!state.agents.has(id)) state.agents.set(id, agent);
          }
        }

        // Every node the drawn map has no key for, so its panel can open.
        // Built after the step above, so a node the WS put in `stages` is
        // never also in here.
        state.nestedStages = new Map();
        for (const node of _allNodes(workflow.nodes)) {
          if (state.stages.has(node.id)) continue;
          state.nestedStages.set(
            node.id,
            _keepFinished(prevNested.get(node.id), _normalizeNode(node)),
          );
        }
        if (stillActive) {
          for (const [id, stage] of prevNested) {
            if (!state.nestedStages.has(id) && !state.stages.has(id)) {
              state.nestedStages.set(id, stage);
            }
          }
        }

        // A refresh every few seconds used to drop whatever the user had
        // clicked. Keep it while the thing it points at still exists.
        const sel = state.selection;
        if (sel && sel.type !== 'workflow') {
          const exists =
            (sel.type === 'stage' && (state.stages.has(sel.id) || state.nestedStages.has(sel.id)))
            || (sel.type === 'agent' && state.agents.has(sel.id))
            || (sel.type === 'llmCall' && state.llmCalls.has(sel.id))
            || (sel.type === 'toolCall' && state.toolCalls.has(sel.id));
          if (!exists) state.selection = null;
        }

        // Same for the agent the live panel is pinned to: an agent the run
        // no longer has would leave the panel showing nothing.
        if (state.livePick && !state.agents.has(state.livePick.id)) {
          state.livePick = null;
        }

        // Seed streamingContent for running agents so the graph's cards and
        // the header show activity even after a page refresh mid-execution.
        // (The live panel builds its own story; this is for everything else.)
        if (workflow.status === 'running') {
          for (const [agentId, agent] of state.agents) {
            if (agent.status === 'running' && !state.streamingContent.has(agentId)) {
              // Seed tool activity from any currently-running tool calls
              const runningTools: ToolActivity[] = (agent.tool_calls ?? [])
                .filter((tc) => tc.status === 'running')
                .map((tc) => ({
                  toolName: tc.tool_name,
                  status: 'running' as const,
                  startedAt: tc.start_time ?? new Date().toISOString(),
                  args: tc.input_params,
                }));
              state.streamingContent.set(agentId, {
                content: '',
                thinking: '',
                activeToolCall: '',
                done: false,
                toolActivity: runningTools,
              });
            }
          }
        }
      }),

    applyEvent: (msg) =>
      set((state) => {
        const data = msg.data ?? {};
        const label = _eventLabel(msg);
        state.eventLog.push({
          timestamp: msg.timestamp ?? new Date().toISOString(),
          event_type: msg.event_type,
          label,
          data,
        });

        if (state.eventLog.length > MAX_EVENT_LOG_SIZE) {
          state.eventLog = state.eventLog.slice(-MAX_EVENT_LOG_SIZE);
        }

        switch (msg.event_type) {
          case 'workflow_start':
          case 'workflow_end':
          case 'workflow.started':
          case 'workflow.completed':
          case 'workflow.failed':
            if (state.workflow) {
              Object.assign(state.workflow, data);
            } else if (msg.event_type.includes('start')) {
              state.workflow = {
                id: (data.execution_id ?? msg.execution_id) as string,
                ...data,
                nodes: [],
              } as unknown as WorkflowExecution;
            }
            break;

          case 'stage_start':
          case 'stage.started': {
            const stageId = (data.stage_id ?? data.event_id ?? msg.stage_id) as string;
            const name = (data.name ?? '') as string;
            const dispatcher = state.dispatchedByName.get(name);
            const nodeData = {
              ...data,
              id: data.id ?? stageId,
              name,
              type: data.type ?? 'agent',
              start_time: data.start_time ?? msg.timestamp,
              ...(dispatcher ? { dispatched_by: dispatcher } : {}),
            } as unknown as NodeExecution;
            const existing = _findStage(state, stageId);
            if (existing) {
              Object.assign(existing, nodeData);
            } else {
              state.stages.set(stageId, nodeData);
              if (state.workflow) {
                if (!state.workflow.nodes) state.workflow.nodes = [];
                state.workflow.nodes.push(nodeData);
              }
            }
            break;
          }

          case 'stage_end':
          case 'stage.completed':
          case 'stage.failed': {
            const sid = (data.stage_id ?? data.event_id ?? msg.stage_id) as string;
            const stage = _findStage(state, sid);
            if (stage) Object.assign(stage, data);
            break;
          }

          case 'agent_start':
          case 'agent.started': {
            const agentId = (data.agent_id ?? data.event_id ?? msg.agent_id) as string;
            const agentData = {
              ...data,
              id: data.id ?? agentId,
              llm_calls: [],
              tool_calls: [],
            } as unknown as AgentExecution;
            const existingAgent = state.agents.get(agentId);
            state.unknownAgentIds.delete(agentId);
            if (existingAgent) {
              Object.assign(existingAgent, agentData);
            } else {
              state.agents.set(agentId, agentData);
              // Try to add to parent node. The event names its node by
              // parent_id (the node's start event); without the link a
              // node started live had no agent and drew as an empty pill.
              const parentStageId = (data.stage_id ?? data.parent_id) as string | undefined;
              if (parentStageId) {
                const parentStage = _findStage(state, parentStageId);
                if (parentStage) {
                  if (parentStage.type === 'agent') {
                    parentStage.agent = agentData;
                    parentStage.agents = [agentData];
                  } else {
                    if (!parentStage.agents) parentStage.agents = [];
                    const exists = parentStage.agents.some((a) => a.id === agentId);
                    if (!exists) parentStage.agents.push(agentData);
                  }
                }
              }
            }
            break;
          }

          case 'agent_end':
          case 'agent_output':
          case 'agent.completed':
          case 'agent.failed': {
            // A completion is an event of its own; parent_id is the start
            // event, which is the agent's id. Looking the agent up by the
            // completion's own id found nothing, so an agent started live
            // stayed running until a refresh.
            const parentId = data.parent_id as string | undefined;
            const aid = (data.agent_id
              ?? (parentId && state.agents.has(parentId) ? parentId : undefined)
              ?? data.event_id ?? msg.agent_id) as string;
            const agent = state.agents.get(aid);
            if (agent) {
              Object.assign(agent, _outcome(data));
              if (!agent.end_time && msg.event_type !== 'agent_output') {
                agent.end_time = msg.timestamp ?? new Date().toISOString();
              }
            }
            if (msg.event_type.includes('end') || msg.event_type.includes('completed') || msg.event_type.includes('failed')) {
              // Don't delete — keep the streamed content around so the user
              // can still scroll through the LLM trace after the agent
              // finishes. Just mark it done so the live "streaming" pulse
              // stops and the UI can render it as a completed transcript.
              const entry = state.streamingContent.get(aid);
              if (entry) entry.done = true;
            }
            break;
          }

          case 'event.updated': {
            // How the engine closes a node (and the run): an update of its
            // start event. Unhandled, a node started live stayed running
            // until the next snapshot -- at the end of the run.
            const eid = data.event_id as string | undefined;
            if (!eid) break;
            const outcome = _outcome(data);
            if (outcome.status == null) delete outcome.status;
            const ended = TERMINAL.has((outcome.status ?? '') as string);
            const at = msg.timestamp ?? new Date().toISOString();
            const stage = _findStage(state, eid);
            if (stage) {
              Object.assign(stage, outcome);
              if (ended && !stage.end_time) stage.end_time = at;
            }
            const agent = state.agents.get(eid);
            if (agent) {
              Object.assign(agent, outcome);
              if (ended && !agent.end_time) agent.end_time = at;
            }
            if (state.workflow && state.workflow.id === eid) {
              Object.assign(state.workflow, outcome);
            }
            break;
          }

          case 'dispatch.applied': {
            const dispatcher = data.dispatcher as string | undefined;
            const added = ((data.added ?? []) as unknown[]).filter(
              (n): n is string => typeof n === 'string',
            );
            if (!dispatcher || added.length === 0) break;
            // The added nodes start after this event: remember the link
            // for their start, and stamp any that are already here.
            for (const name of added) state.dispatchedByName.set(name, dispatcher);
            for (const stage of state.stages.values()) {
              if (stage.name === dispatcher) {
                const kids = stage.dispatched_children ?? [];
                stage.dispatched_children = [...kids, ...added.filter((n) => !kids.includes(n))];
              } else if (added.includes(stage.name) && !stage.dispatched_by) {
                stage.dispatched_by = dispatcher;
              }
            }
            break;
          }

          case 'llm_call':
          case 'llm.call.completed': {
            const llmId = (data.llm_call_id ?? data.event_id) as string;
            if (llmId) state.llmCalls.set(llmId, data as unknown as LLMCall);
            break;
          }

          case 'tool_call_start':
          case 'tool.call.started': {
            const agId = (data.agent_id ?? msg.agent_id) as string;
            if (!agId) break;
            let entry = state.streamingContent.get(agId);
            if (!entry) {
              entry = { content: '', thinking: '', activeToolCall: '', done: false, toolActivity: [] };
              state.streamingContent.set(agId, entry);
            }
            // Re-activate stream so the live bar shows tool calls between LLM iterations
            entry.done = false;
            entry.toolActivity.push({
              toolName: data.tool_name as string,
              status: 'running',
              startedAt: msg.timestamp ?? new Date().toISOString(),
              args: (data.input_params ?? data.input_data) as Record<string, unknown> | undefined,
            } satisfies ToolActivity);
            startTool(_story(state, agId), {
              toolId: (data.tool_execution_id ?? data.event_id) as string | undefined,
              toolName: data.tool_name as string,
              args: (data.input_params ?? data.input_data) as Record<string, unknown> | undefined,
              at: msg.timestamp ?? new Date().toISOString(),
            });
            break;
          }

          case 'tool_call':
          case 'tool.call.completed':
          case 'tool.call.failed': {
            const toolId = (data.tool_execution_id ?? data.event_id) as string;
            if (toolId) state.toolCalls.set(toolId, data as unknown as ToolCall);
            const agId = (data.agent_id ?? msg.agent_id) as string;
            if (agId) {
              const entry = state.streamingContent.get(agId);
              if (entry?.toolActivity) {
                const toolName = data.tool_name as string;
                const running = [...entry.toolActivity]
                  .reverse()
                  .find((t) => t.toolName === toolName && t.status === 'running');
                if (running) {
                  running.status = (data.status as string) === 'success' ? 'completed' : 'failed';
                  running.completedAt = msg.timestamp ?? new Date().toISOString();
                  running.durationSeconds = data.duration_seconds as number | undefined;
                }
              }
              const failed = msg.event_type === 'tool.call.failed'
                || (data.status != null && data.status !== 'success' && data.status !== 'completed');
              finishTool(_story(state, agId), {
                toolId: toolId || undefined,
                toolName: data.tool_name as string | undefined,
                status: failed ? 'failed' : 'completed',
                durationSeconds: data.duration_seconds as number | undefined,
                result: data.output_data ?? data.output,
                error: data.error_message as string | undefined,
                args: (data.input_params ?? data.input_data) as Record<string, unknown> | undefined,
                at: msg.timestamp ?? new Date().toISOString(),
              });
            }
            break;
          }

          case 'llm_stream_batch':
          case 'llm.stream.chunk': {
            const chunks = (data.chunks ?? [data]) as Array<{
              agent_id?: string;
              chunk_type?: string;
              content: string;
              done?: boolean;
              call_id?: string | null;
            }>;
            for (const chunk of chunks) {
              const agId = chunk.agent_id;
              if (!agId) continue;
              // Output of an agent the last snapshot did not have (it
              // started since, or it is a round the tree does not keep).
              if (!state.agents.has(agId) && !state.unknownAgentIds.has(agId)) {
                state.unknownAgentIds.add(agId);
              }
              let entry = state.streamingContent.get(agId);
              if (!entry) {
                entry = { content: '', thinking: '', activeToolCall: '', done: false, toolActivity: [] };
                state.streamingContent.set(agId, entry);
              }
              appendChunk(_story(state, agId), chunk, msg.timestamp ?? new Date().toISOString());
              // `done` ends one model call, not the agent: output after it
              // is the agent's next call.
              if (chunk.content) entry.done = false;
              if (chunk.chunk_type === 'thinking') {
                _addThinking(entry, chunk.content);
              } else if (chunk.chunk_type === 'tool_call') {
                entry.activeToolCall += chunk.content;
              } else {
                // Regular content — if there was an active tool call, finalize it
                if (entry.activeToolCall) {
                  entry.content += entry.activeToolCall + ')\n\n';
                  entry.activeToolCall = '';
                }
                entry.content += chunk.content;
              }
              if (chunk.done) {
                // Finalize any pending tool call
                if (entry.activeToolCall) {
                  entry.content += entry.activeToolCall + ')\n\n';
                  entry.activeToolCall = '';
                }
                entry.done = true;
              }
            }
            break;
          }
        }
      }),

    applyAgentIndex: (index) =>
      set((state) => {
        _mergeAgentIndex(
          state.agents,
          new Set([...state.stages.keys(), ...state.nestedStages.keys()]),
          state.unknownAgentIds,
          index,
          state.agents,
        );
      }),

    giveUpAgentLookup: (ids) =>
      set((state) => {
        for (const id of ids) {
          state.unknownAgentIds.delete(id);
          if (state.agents.has(id)) continue;
          state.agents.set(id, {
            id,
            agent_name: '',
            status: 'running',
            start_time: null,
            end_time: null,
            duration_seconds: null,
            prompt_tokens: 0,
            completion_tokens: 0,
            total_tokens: 0,
            estimated_cost_usd: 0,
            total_llm_calls: 0,
            total_tool_calls: 0,
            llm_calls: [],
            tool_calls: [],
            summary_only: true,
          });
        }
      }),

    reset: () =>
      set((state) => {
        state.workflow = null;
        state.stages = new Map();
        state.nestedStages = new Map();
        state.agents = new Map();
        state.llmCalls = new Map();
        state.toolCalls = new Map();
        state.streamingContent = new Map();
        state.stories = new Map();
        state.unknownAgentIds = new Set();
        state.eventLog = [];
        state.dispatchedByName = new Map();
        // Nothing selected. This was `{ type: 'workflow' }`, which the first
        // snapshot used to wipe; now that a refresh keeps the selection, it
        // opened Workflow Details over the canvas on every page load.
        state.selection = null;
        // Another run is another run: the panel starts by following it.
        state.livePick = null;
        // Another run is another search: a word typed on the last page would
        // otherwise dim most of this one before it had finished loading.
        state.findQuery = '';
        state.findStatus = 'all';
        state.wsStatus = { connected: false, reconnectAttempt: 0, lastHeartbeat: null, wsError: null };
      }),

    select: (type, id) =>
      set((state) => {
        state.selection = { type, id };
        // Choosing an agent anywhere on the page chooses it in the live
        // panel too, so the two never show different agents.
        if (type === 'agent') {
          state.livePick = { id, nonce: (state.livePick?.nonce ?? 0) + 1 };
        }
      }),

    clearSelection: () =>
      set((state) => {
        state.selection = null;
      }),

    pickLiveAgent: (agentId) =>
      set((state) => {
        state.livePick = { id: agentId, nonce: (state.livePick?.nonce ?? 0) + 1 };
      }),

    clearLivePick: () =>
      set((state) => {
        state.livePick = null;
      }),

    setHoveredNodeId: (id) =>
      set((state) => {
        state.hoveredNodeId = id;
      }),

    setFindQuery: (query) =>
      set((state) => {
        state.findQuery = query;
      }),

    setFindStatus: (status) =>
      set((state) => {
        state.findStatus = status;
      }),

    setWSStatus: (partial) =>
      set((state) => {
        Object.assign(state.wsStatus, partial);
      }),

    toggleStageExpanded: (stageName) =>
      set((state) => {
        if (state.expandedStages.has(stageName)) {
          state.expandedStages.delete(stageName);
        } else {
          state.expandedStages.add(stageName);
        }
      }),

    openGate: (nodeName) =>
      set((state) => {
        state.gateNodeName = nodeName;
        // The gate is the thing to answer; don't bury it under the big view.
        state.selection = null;
      }),

    closeGate: () =>
      set((state) => {
        state.gateNodeName = null;
      }),

    setCheckpointPreview: (preview) =>
      set((state) => {
        state.checkpointPreview = preview;
      }),
  })),
);

/** Extract a human-readable label from a WS event. */
function _eventLabel(msg: WSEvent): string {
  const data = msg.data ?? {};
  if (msg.event_type.includes('stage') || msg.event_type.includes('node')) {
    return (data.name ?? data.stage_name ?? msg.stage_id ?? '') as string;
  }
  if (msg.event_type.includes('agent')) {
    return (data.agent_name ?? data.name ?? msg.agent_id ?? '') as string;
  }
  if (msg.event_type.includes('llm')) {
    return (data.model ?? data.provider ?? msg.event_type) as string;
  }
  if (msg.event_type.includes('tool')) {
    return (data.tool_name ?? msg.event_type) as string;
  }
  return msg.event_type;
}
