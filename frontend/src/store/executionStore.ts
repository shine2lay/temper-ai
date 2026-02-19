/**
 * Zustand store for workflow execution state.
 * Port of the vanilla JS DataStore with flat Maps for O(1) lookups.
 */
import { create } from 'zustand';
import { immer } from 'zustand/middleware/immer';
import { enableMapSet } from 'immer';
import { MAX_EVENT_LOG_SIZE } from '@/lib/constants';
import type {
  WorkflowExecution,
  StageExecution,
  AgentExecution,
  LLMCall,
  ToolCall,
  StreamEntry,
  Selection,
  WSStatus,
  WSEvent,
  EventLogEntry,
} from '@/types';

enableMapSet();

interface ExecutionState {
  workflow: WorkflowExecution | null;
  stages: Map<string, StageExecution>;
  agents: Map<string, AgentExecution>;
  llmCalls: Map<string, LLMCall>;
  toolCalls: Map<string, ToolCall>;
  streamingContent: Map<string, StreamEntry>;
  selection: Selection | null;
  wsStatus: WSStatus;
  eventLog: EventLogEntry[];
  expandedStages: Set<string>;
  stageDetailId: string | null;

  applySnapshot: (workflow: WorkflowExecution) => void;
  applyEvent: (msg: WSEvent) => void;
  select: (type: Selection['type'], id: string) => void;
  clearSelection: () => void;
  setWSStatus: (partial: Partial<WSStatus>) => void;
  toggleStageExpanded: (stageName: string) => void;
  openStageDetail: (stageId: string) => void;
  closeStageDetail: () => void;
}

/**
 * Generate synthetic event log entries by diffing old state against a new snapshot.
 * Enables event log population for DB-polled (cross-process) workflows.
 */
function _diffSnapshotEvents(
  oldWorkflow: WorkflowExecution | null,
  oldStages: Map<string, StageExecution>,
  oldAgents: Map<string, AgentExecution>,
  newWorkflow: WorkflowExecution,
): EventLogEntry[] {
  const now = new Date().toISOString();
  const events: EventLogEntry[] = [];

  // Workflow status change
  if (oldWorkflow && oldWorkflow.status !== newWorkflow.status) {
    const eventType = newWorkflow.status === 'running' ? 'workflow_start' : 'workflow_end';
    events.push({
      timestamp: now,
      event_type: eventType,
      label: `${newWorkflow.workflow_name} — ${newWorkflow.status}`,
      data: { workflow_id: newWorkflow.id, status: newWorkflow.status },
    });
  }

  // Stage changes
  for (const stage of newWorkflow.stages ?? []) {
    const oldStage = oldStages.get(stage.id);
    if (!oldStage) {
      events.push({
        timestamp: now,
        event_type: 'stage_start',
        label: stage.stage_name ?? stage.name ?? stage.id,
        data: { stage_id: stage.id, status: stage.status },
      });
    } else if (oldStage.status !== stage.status) {
      const eventType = stage.status === 'running' ? 'stage_start' : 'stage_end';
      events.push({
        timestamp: now,
        event_type: eventType,
        label: stage.stage_name ?? stage.name ?? stage.id,
        data: { stage_id: stage.id, status: stage.status },
      });
    }

    // Agent changes
    for (const agent of stage.agents ?? []) {
      const oldAgent = oldAgents.get(agent.id);
      if (!oldAgent) {
        events.push({
          timestamp: now,
          event_type: 'agent_start',
          label: agent.agent_name ?? agent.name ?? agent.id,
          data: { agent_id: agent.id, stage_id: stage.id, status: agent.status },
        });
      } else if (oldAgent.status !== agent.status) {
        const eventType = agent.status === 'running' ? 'agent_start' : 'agent_end';
        events.push({
          timestamp: now,
          event_type: eventType,
          label: agent.agent_name ?? agent.name ?? agent.id,
          data: { agent_id: agent.id, stage_id: stage.id, status: agent.status },
        });
      }
    }
  }

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
    wsStatus: { connected: false, reconnectAttempt: 0, lastHeartbeat: null },
    eventLog: [],
    expandedStages: new Set(),
    stageDetailId: null,

    applySnapshot: (workflow) =>
      set((state) => {
        // Generate synthetic events from snapshot diff (for DB-polled workflows)
        if (state.workflow) {
          const syntheticEvents = _diffSnapshotEvents(
            state.workflow, state.stages, state.agents, workflow,
          );
          for (const evt of syntheticEvents) {
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

        for (const stage of workflow.stages ?? []) {
          state.stages.set(stage.id, stage);
          for (const agent of stage.agents ?? []) {
            state.agents.set(agent.id, agent);
            for (const llm of agent.llm_calls ?? []) {
              state.llmCalls.set(llm.id, llm);
            }
            for (const tool of agent.tool_calls ?? []) {
              state.toolCalls.set(tool.id, tool);
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

        // Evict oldest entries when log exceeds size limit
        if (state.eventLog.length > MAX_EVENT_LOG_SIZE) {
          state.eventLog = state.eventLog.slice(-MAX_EVENT_LOG_SIZE);
        }

        switch (msg.event_type) {
          case 'workflow_start':
          case 'workflow_end':
            if (state.workflow) {
              Object.assign(state.workflow, data);
            } else if (msg.event_type === 'workflow_start') {
              state.workflow = {
                id: (data.workflow_id ?? msg.workflow_id) as string,
                ...data,
                stages: [],
              } as unknown as WorkflowExecution;
            }
            break;

          case 'stage_start': {
            const stageId = (data.stage_id ?? msg.stage_id) as string;
            const stageData = { ...data, id: data.id ?? stageId } as unknown as StageExecution;
            const existing = state.stages.get(stageId);
            if (existing) {
              Object.assign(existing, stageData);
            } else {
              if (!stageData.agents) stageData.agents = [];
              state.stages.set(stageId, stageData);
              if (state.workflow) {
                if (!state.workflow.stages) state.workflow.stages = [];
                state.workflow.stages.push(stageData);
              }
            }
            break;
          }

          case 'stage_end': {
            const sid = (data.stage_id ?? msg.stage_id) as string;
            const stage = state.stages.get(sid);
            if (stage) Object.assign(stage, data);
            break;
          }

          case 'agent_start': {
            const agentId = (data.agent_id ?? msg.agent_id) as string;
            const agentData = { ...data, id: data.id ?? agentId } as unknown as AgentExecution;
            const existingAgent = state.agents.get(agentId);
            if (existingAgent) {
              Object.assign(existingAgent, agentData);
            } else {
              if (!agentData.llm_calls) agentData.llm_calls = [];
              if (!agentData.tool_calls) agentData.tool_calls = [];
              state.agents.set(agentId, agentData);
              const parentStageId = data.stage_id as string | undefined;
              if (parentStageId) {
                const parentStage = state.stages.get(parentStageId);
                if (parentStage) {
                  if (!parentStage.agents) parentStage.agents = [];
                  const exists = parentStage.agents.some((a) => a.id === agentId);
                  if (!exists) parentStage.agents.push(agentData);
                }
              }
            }
            break;
          }

          case 'agent_end':
          case 'agent_output': {
            const aid = (data.agent_id ?? msg.agent_id) as string;
            const agent = state.agents.get(aid);
            if (agent) Object.assign(agent, data);
            // Evict streaming content on agent completion
            if (msg.event_type === 'agent_end') {
              state.streamingContent.delete(aid);
            }
            break;
          }

          case 'llm_call': {
            const llmId = data.llm_call_id as string;
            state.llmCalls.set(llmId, data as unknown as LLMCall);
            break;
          }

          case 'tool_call': {
            const toolId = data.tool_execution_id as string;
            state.toolCalls.set(toolId, data as unknown as ToolCall);
            break;
          }

          case 'llm_stream_batch': {
            const chunks = (data.chunks ?? []) as Array<{
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
                entry = { content: '', thinking: '', done: false };
                state.streamingContent.set(agId, entry);
              }
              if (chunk.chunk_type === 'thinking') {
                entry.thinking += chunk.content;
              } else {
                entry.content += chunk.content;
              }
              if (chunk.done) entry.done = true;
            }
            break;
          }
        }
      }),

    select: (type, id) =>
      set((state) => {
        state.selection = { type, id };
      }),

    clearSelection: () =>
      set((state) => {
        state.selection = null;
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
  })),
);

/** Extract a human-readable label from a WS event. */
function _eventLabel(msg: WSEvent): string {
  const data = msg.data ?? {};
  if (msg.event_type.startsWith('stage_')) {
    return (data.stage_name ?? data.name ?? msg.stage_id ?? '') as string;
  }
  if (msg.event_type.startsWith('agent_')) {
    return (data.agent_name ?? data.name ?? msg.agent_id ?? '') as string;
  }
  if (msg.event_type === 'llm_call') {
    return (data.model ?? data.provider ?? '') as string;
  }
  if (msg.event_type === 'tool_call') {
    return (data.tool_name ?? '') as string;
  }
  return msg.event_type;
}
