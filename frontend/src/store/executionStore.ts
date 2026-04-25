/**
 * Zustand store for workflow execution state.
 * Adapted for v1 composable graph model: nodes instead of stages.
 */
import { create } from 'zustand';
import { immer } from 'zustand/middleware/immer';
import { enableMapSet } from 'immer';
import { MAX_EVENT_LOG_SIZE } from '@/lib/constants';
import type {
  WorkflowExecution,
  NodeExecution,
  AgentExecution,
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

// Re-export StageExecution as NodeExecution for backward compat
export type StageExecution = NodeExecution;

interface ExecutionState {
  workflow: WorkflowExecution | null;
  stages: Map<string, NodeExecution>;  // keep name 'stages' for component compat
  agents: Map<string, AgentExecution>;
  llmCalls: Map<string, LLMCall>;
  toolCalls: Map<string, ToolCall>;
  streamingContent: Map<string, StreamEntry>;
  selection: Selection | null;
  /** Id of the node the cursor is currently over. Drives "hover-to-reveal"
   *  edge highlighting — connected edges go full opacity, others dim. */
  hoveredNodeId: string | null;
  wsStatus: WSStatus;
  eventLog: EventLogEntry[];
  expandedStages: Set<string>;
  stageDetailId: string | null;
  /** When set, the DAG highlights state at this checkpoint sequence. null = show current/live state. */
  checkpointPreview: { sequence: number; completedNodes: Set<string>; failedNodes: Set<string> } | null;

  applySnapshot: (workflow: WorkflowExecution) => void;
  applyEvent: (msg: WSEvent) => void;
  reset: () => void;
  select: (type: Selection['type'], id: string) => void;
  clearSelection: () => void;
  setHoveredNodeId: (id: string | null) => void;
  setWSStatus: (partial: Partial<WSStatus>) => void;
  toggleStageExpanded: (stageName: string) => void;
  openStageDetail: (stageId: string) => void;
  closeStageDetail: () => void;
  setCheckpointPreview: (preview: { sequence: number; completedNodes: Set<string>; failedNodes: Set<string> } | null) => void;
}

/** Extract all agents from a node (handles both agent and stage nodes). */
function _nodeAgents(node: NodeExecution): AgentExecution[] {
  if (node.type === 'agent' && node.agent) return [node.agent];
  return node.agents || [];
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

  for (const node of workflow.nodes ?? []) {
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
    agents: new Map(),
    llmCalls: new Map(),
    toolCalls: new Map(),
    streamingContent: new Map(),
    selection: null,
    wsStatus: { connected: false, reconnectAttempt: 0, lastHeartbeat: null, wsError: null },
    eventLog: [],
    expandedStages: new Set(),
    stageDetailId: null,
    hoveredNodeId: null,
    checkpointPreview: null,

    applySnapshot: (workflow) =>
      set((state) => {
        state.selection = null;

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

        for (const node of workflow.nodes ?? []) {
          // Normalize: ensure .agents is always an array (for agent-type nodes, move .agent into .agents)
          const normalizedNode = { ...node };
          if (node.type === 'agent' && node.agent && (!node.agents || node.agents.length === 0)) {
            normalizedNode.agents = [node.agent];
          }
          normalizedNode.stage_name = normalizedNode.stage_name ?? normalizedNode.name;
          // Preserve DAG metadata for dependency arrows
          normalizedNode.depends_on = normalizedNode.depends_on ?? [];
          normalizedNode.loop_to = normalizedNode.loop_to ?? undefined;
          normalizedNode.max_loops = normalizedNode.max_loops ?? undefined;
          // Store in stages map (backward compat with components)
          state.stages.set(normalizedNode.id, normalizedNode);
          for (const agent of _nodeAgents(normalizedNode)) {
            state.agents.set(agent.id, agent);
            for (const llm of agent.llm_calls ?? []) {
              const llmCopy = { ...llm, agent_id: agent.id, agent_execution_id: agent.id };
              state.llmCalls.set(llmCopy.id, llmCopy);
            }
            for (const tool of agent.tool_calls ?? []) {
              state.toolCalls.set(tool.id, { ...tool });
            }
          }
        }

        // Seed streamingContent for running agents so the LiveStreamBar
        // shows activity even after a page refresh mid-execution.
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
            const nodeData = {
              ...data,
              id: data.id ?? stageId,
              name: data.name ?? '',
              type: data.type ?? 'agent',
            } as unknown as NodeExecution;
            const existing = state.stages.get(stageId);
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
            const stage = state.stages.get(sid);
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
            if (existingAgent) {
              Object.assign(existingAgent, agentData);
            } else {
              state.agents.set(agentId, agentData);
              // Try to add to parent node
              const parentStageId = data.stage_id as string | undefined;
              if (parentStageId) {
                const parentStage = state.stages.get(parentStageId);
                if (parentStage) {
                  if (parentStage.type === 'agent') {
                    parentStage.agent = agentData;
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
            const aid = (data.agent_id ?? data.event_id ?? msg.agent_id) as string;
            const agent = state.agents.get(aid);
            if (agent) Object.assign(agent, data);
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
            }>;
            for (const chunk of chunks) {
              const agId = chunk.agent_id;
              if (!agId) continue;
              let entry = state.streamingContent.get(agId);
              if (!entry) {
                entry = { content: '', thinking: '', activeToolCall: '', done: false, toolActivity: [] };
                state.streamingContent.set(agId, entry);
              }
              if (chunk.chunk_type === 'thinking') {
                entry.thinking += chunk.content;
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

    reset: () =>
      set((state) => {
        state.workflow = null;
        state.stages = new Map();
        state.agents = new Map();
        state.llmCalls = new Map();
        state.toolCalls = new Map();
        state.streamingContent = new Map();
        state.eventLog = [];
        state.selection = { type: 'workflow', id: '' };
        state.wsStatus = { connected: false, reconnectAttempt: 0, lastHeartbeat: null, wsError: null };
      }),

    select: (type, id) =>
      set((state) => {
        state.selection = { type, id };
      }),

    clearSelection: () =>
      set((state) => {
        state.selection = null;
      }),

    setHoveredNodeId: (id) =>
      set((state) => {
        state.hoveredNodeId = id;
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

    openStageDetail: (stageId) =>
      set((state) => {
        state.stageDetailId = stageId;
      }),

    closeStageDetail: () =>
      set((state) => {
        state.stageDetailId = null;
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
