/**
 * Tests for the Zustand execution store — the core state layer that processes
 * WebSocket snapshots and events. Verifies that all WS message types correctly
 * update the flat Maps and derived state used by React components.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { useExecutionStore } from '@/store/executionStore';
import {
  MOCK_WORKFLOW,
  COMPLETED_WORKFLOW,
  makeStageStartEvent,
  makeAgentStartEvent,
  makeAgentEndEvent,
  makeLlmCallEvent,
  makeToolCallEvent,
  makeStreamBatchEvent,
  makeWorkflowEndEvent,
  makeStageEndEvent,
} from './fixtures';

function resetStore() {
  useExecutionStore.setState({
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
  });
}

describe('executionStore', () => {
  beforeEach(() => {
    resetStore();
  });

  // =========================================================================
  // applySnapshot
  // =========================================================================

  describe('applySnapshot', () => {
    it('populates workflow and flat maps from snapshot', () => {
      const { applySnapshot } = useExecutionStore.getState();
      applySnapshot(MOCK_WORKFLOW);

      const state = useExecutionStore.getState();
      expect(state.workflow).not.toBeNull();
      expect(state.workflow!.id).toBe('wf-test-001');
      expect(state.workflow!.workflow_name).toBe('quick_decision_demo');
      expect(state.workflow!.status).toBe('running');
    });

    it('populates stages map from snapshot', () => {
      useExecutionStore.getState().applySnapshot(MOCK_WORKFLOW);
      const { stages } = useExecutionStore.getState();

      expect(stages.size).toBe(1);
      expect(stages.has('stage-001')).toBe(true);

      const stage = stages.get('stage-001')!;
      expect(stage.stage_name).toBe('decision');
      expect(stage.status).toBe('running');
    });

    it('populates agents map from snapshot', () => {
      useExecutionStore.getState().applySnapshot(MOCK_WORKFLOW);
      const { agents } = useExecutionStore.getState();

      expect(agents.size).toBe(2);
      expect(agents.has('agent-001')).toBe(true);
      expect(agents.has('agent-002')).toBe(true);

      const agent1 = agents.get('agent-001')!;
      expect(agent1.agent_name).toBe('optimist');
      expect(agent1.total_llm_calls).toBe(1);
      expect(agent1.total_tool_calls).toBe(1);
    });

    it('populates llmCalls map from snapshot', () => {
      useExecutionStore.getState().applySnapshot(MOCK_WORKFLOW);
      const { llmCalls } = useExecutionStore.getState();

      expect(llmCalls.size).toBe(1);
      expect(llmCalls.has('llm-001')).toBe(true);

      const llm = llmCalls.get('llm-001')!;
      expect(llm.provider).toBe('ollama');
      expect(llm.model).toBe('qwen3');
      expect(llm.total_tokens).toBe(350);
    });

    it('populates toolCalls map from snapshot', () => {
      useExecutionStore.getState().applySnapshot(MOCK_WORKFLOW);
      const { toolCalls } = useExecutionStore.getState();

      expect(toolCalls.size).toBe(1);
      expect(toolCalls.has('tool-001')).toBe(true);

      const tool = toolCalls.get('tool-001')!;
      expect(tool.tool_name).toBe('Bash');
      expect(tool.output_data).toEqual({ stdout: 'hello' });
    });

    it('clears previous state on new snapshot', () => {
      const { applySnapshot } = useExecutionStore.getState();

      // Apply first snapshot
      applySnapshot(MOCK_WORKFLOW);
      expect(useExecutionStore.getState().agents.size).toBe(2);

      // Apply second snapshot with different data
      applySnapshot(COMPLETED_WORKFLOW);
      const state = useExecutionStore.getState();
      expect(state.workflow!.status).toBe('completed');
      // Should still have 2 agents (same workflow, different status)
      expect(state.agents.size).toBe(2);
    });

    it('handles empty stages array', () => {
      const emptyWorkflow = { ...MOCK_WORKFLOW, stages: [] };
      useExecutionStore.getState().applySnapshot(emptyWorkflow);

      const state = useExecutionStore.getState();
      expect(state.stages.size).toBe(0);
      expect(state.agents.size).toBe(0);
      expect(state.llmCalls.size).toBe(0);
      expect(state.toolCalls.size).toBe(0);
    });

    it('uses backend field names (start_time, not started_at)', () => {
      useExecutionStore.getState().applySnapshot(MOCK_WORKFLOW);
      const state = useExecutionStore.getState();

      expect(state.workflow!.start_time).toBe('2026-02-18T04:10:00Z');
      expect(state.workflow!.end_time).toBeNull();

      const stage = state.stages.get('stage-001')!;
      expect(stage.start_time).toBe('2026-02-18T04:10:00Z');

      const agent = state.agents.get('agent-001')!;
      expect(agent.start_time).toBe('2026-02-18T04:10:00Z');
      expect(agent.end_time).toBe('2026-02-18T04:10:10Z');
    });
  });

  // =========================================================================
  // applyEvent — stage events
  // =========================================================================

  describe('applyEvent — stages', () => {
    beforeEach(() => {
      useExecutionStore.getState().applySnapshot(MOCK_WORKFLOW);
    });

    it('stage_start creates a new stage in the map', () => {
      const event = makeStageStartEvent();
      useExecutionStore.getState().applyEvent(event);

      const { stages } = useExecutionStore.getState();
      expect(stages.size).toBe(2);
      expect(stages.has('stage-002')).toBe(true);

      const newStage = stages.get('stage-002')!;
      expect(newStage.stage_name).toBe('review');
      expect(newStage.status).toBe('running');
    });

    it('stage_start adds the new stage to workflow.stages array', () => {
      useExecutionStore.getState().applyEvent(makeStageStartEvent());
      const { workflow } = useExecutionStore.getState();

      expect(workflow!.stages.length).toBe(2);
      expect(workflow!.stages[1].stage_name).toBe('review');
    });

    it('stage_end updates existing stage', () => {
      useExecutionStore.getState().applyEvent(makeStageEndEvent());

      const stage = useExecutionStore.getState().stages.get('stage-001')!;
      expect(stage.status).toBe('completed');
      expect(stage.duration_seconds).toBe(150);
    });
  });

  // =========================================================================
  // applyEvent — agent events
  // =========================================================================

  describe('applyEvent — agents', () => {
    beforeEach(() => {
      useExecutionStore.getState().applySnapshot(MOCK_WORKFLOW);
    });

    it('agent_start creates a new agent and links to parent stage', () => {
      useExecutionStore.getState().applyEvent(makeAgentStartEvent());

      const { agents, stages } = useExecutionStore.getState();
      expect(agents.has('agent-003')).toBe(true);

      const newAgent = agents.get('agent-003')!;
      expect(newAgent.agent_name).toBe('reviewer');
      expect(newAgent.status).toBe('running');

      // Should be linked to parent stage
      const parentStage = stages.get('stage-001')!;
      const linkedAgent = parentStage.agents.find((a) => a.id === 'agent-003');
      expect(linkedAgent).toBeDefined();
    });

    it('agent_end updates existing agent with new metrics', () => {
      useExecutionStore.getState().applyEvent(makeAgentEndEvent());

      const agent = useExecutionStore.getState().agents.get('agent-002')!;
      expect(agent.status).toBe('completed');
      expect(agent.total_tokens).toBe(500);
      expect(agent.total_llm_calls).toBe(2);
      expect(agent.duration_seconds).toBe(125);
    });

    it('agent_end uses total_llm_calls field (not num_llm_calls)', () => {
      useExecutionStore.getState().applyEvent(makeAgentEndEvent());
      const agent = useExecutionStore.getState().agents.get('agent-002')!;

      // The event data uses total_llm_calls (matching ObservabilityFields)
      expect(agent.total_llm_calls).toBe(2);
      expect(agent.total_tool_calls).toBe(0);
    });
  });

  // =========================================================================
  // applyEvent — LLM and tool calls
  // =========================================================================

  describe('applyEvent — llm & tool calls', () => {
    beforeEach(() => {
      useExecutionStore.getState().applySnapshot(MOCK_WORKFLOW);
    });

    it('llm_call event adds to llmCalls map (keyed by llm_call_id)', () => {
      useExecutionStore.getState().applyEvent(makeLlmCallEvent());

      const { llmCalls } = useExecutionStore.getState();
      expect(llmCalls.size).toBe(2); // original + new
      expect(llmCalls.has('llm-002')).toBe(true);

      const newLlm = llmCalls.get('llm-002')!;
      expect(newLlm.model).toBe('qwen3');
      expect(newLlm.total_tokens).toBe(180);
    });

    it('tool_call event adds to toolCalls map (keyed by tool_execution_id)', () => {
      useExecutionStore.getState().applyEvent(makeToolCallEvent());

      const { toolCalls } = useExecutionStore.getState();
      expect(toolCalls.size).toBe(2); // original + new
      expect(toolCalls.has('tool-002')).toBe(true);

      const newTool = toolCalls.get('tool-002')!;
      expect(newTool.tool_name).toBe('FileWriter');
      expect(newTool.output_data).toEqual({ written: true });
    });
  });

  // =========================================================================
  // applyEvent — streaming
  // =========================================================================

  describe('applyEvent — streaming', () => {
    beforeEach(() => {
      useExecutionStore.getState().applySnapshot(MOCK_WORKFLOW);
    });

    it('llm_stream_batch accumulates content for agent', () => {
      const event = makeStreamBatchEvent('agent-002', [
        { content: 'Hello ' },
        { content: 'world' },
      ]);
      useExecutionStore.getState().applyEvent(event);

      const entry = useExecutionStore.getState().streamingContent.get('agent-002')!;
      expect(entry.content).toBe('Hello world');
      expect(entry.done).toBe(false);
    });

    it('llm_stream_batch accumulates thinking content separately', () => {
      const event = makeStreamBatchEvent('agent-002', [
        { content: 'Analyzing...', chunk_type: 'thinking' },
        { content: 'The answer is: ', chunk_type: 'content' },
      ]);
      useExecutionStore.getState().applyEvent(event);

      const entry = useExecutionStore.getState().streamingContent.get('agent-002')!;
      expect(entry.thinking).toBe('Analyzing...');
      expect(entry.content).toBe('The answer is: ');
    });

    it('llm_stream_batch sets done flag', () => {
      useExecutionStore.getState().applyEvent(
        makeStreamBatchEvent('agent-002', [{ content: 'Final', done: true }]),
      );

      const entry = useExecutionStore.getState().streamingContent.get('agent-002')!;
      expect(entry.done).toBe(true);
    });

    it('multiple stream batches accumulate incrementally', () => {
      const { applyEvent } = useExecutionStore.getState();

      applyEvent(makeStreamBatchEvent('agent-002', [{ content: 'Part 1. ' }]));
      applyEvent(makeStreamBatchEvent('agent-002', [{ content: 'Part 2. ' }]));
      applyEvent(makeStreamBatchEvent('agent-002', [{ content: 'End.', done: true }]));

      const entry = useExecutionStore.getState().streamingContent.get('agent-002')!;
      expect(entry.content).toBe('Part 1. Part 2. End.');
      expect(entry.done).toBe(true);
    });

  });

  // =========================================================================
  // applyEvent — workflow lifecycle
  // =========================================================================

  describe('applyEvent — workflow lifecycle', () => {
    beforeEach(() => {
      useExecutionStore.getState().applySnapshot(MOCK_WORKFLOW);
    });

    it('workflow_end updates workflow status and timing', () => {
      useExecutionStore.getState().applyEvent(makeWorkflowEndEvent());

      const { workflow } = useExecutionStore.getState();
      expect(workflow!.status).toBe('completed');
      expect(workflow!.duration_seconds).toBe(180);
    });

    it('workflow_end with failed status', () => {
      useExecutionStore.getState().applyEvent(
        makeWorkflowEndEvent({ status: 'failed', error_message: 'Timeout' }),
      );

      const { workflow } = useExecutionStore.getState();
      expect(workflow!.status).toBe('failed');
      expect(workflow!.error_message).toBe('Timeout');
    });
  });

  // =========================================================================
  // applyEvent — event log
  // =========================================================================

  describe('event log', () => {
    beforeEach(() => {
      useExecutionStore.getState().applySnapshot(MOCK_WORKFLOW);
    });

    it('each event is appended to eventLog', () => {
      const { applyEvent } = useExecutionStore.getState();
      applyEvent(makeStageStartEvent());
      applyEvent(makeAgentStartEvent());
      applyEvent(makeAgentEndEvent());

      const { eventLog } = useExecutionStore.getState();
      expect(eventLog.length).toBe(3);
      expect(eventLog[0].event_type).toBe('stage_start');
      expect(eventLog[1].event_type).toBe('agent_start');
      expect(eventLog[2].event_type).toBe('agent_end');
    });

    it('event log entries have labels from event data', () => {
      useExecutionStore.getState().applyEvent(makeStageStartEvent());
      const entry = useExecutionStore.getState().eventLog[0];
      expect(entry.label).toBe('review');
    });
  });

  // =========================================================================
  // Full event sequence (simulates a real workflow execution)
  // =========================================================================

  describe('full event sequence', () => {
    it('processes a complete workflow lifecycle via events', () => {
      const { applySnapshot, applyEvent } = useExecutionStore.getState();

      // Initial snapshot (workflow just started, 1 stage with 2 agents)
      applySnapshot(MOCK_WORKFLOW);
      expect(useExecutionStore.getState().workflow!.status).toBe('running');

      // Agent 2 finishes
      applyEvent(makeAgentEndEvent());
      expect(useExecutionStore.getState().agents.get('agent-002')!.status).toBe('completed');

      // New LLM call comes in
      applyEvent(makeLlmCallEvent());
      expect(useExecutionStore.getState().llmCalls.size).toBe(2);

      // Streaming content for agent-002
      applyEvent(makeStreamBatchEvent('agent-002', [{ content: 'Streaming...', done: true }]));
      expect(useExecutionStore.getState().streamingContent.get('agent-002')!.done).toBe(true);

      // Stage completes
      applyEvent(makeStageEndEvent());
      expect(useExecutionStore.getState().stages.get('stage-001')!.status).toBe('completed');

      // Workflow completes
      applyEvent(makeWorkflowEndEvent());
      const finalState = useExecutionStore.getState();
      expect(finalState.workflow!.status).toBe('completed');
      expect(finalState.eventLog.length).toBe(5);
    });
  });

  // =========================================================================
  // Selection
  // =========================================================================

  describe('selection', () => {
    it('select sets selection state', () => {
      useExecutionStore.getState().select('agent', 'agent-001');
      expect(useExecutionStore.getState().selection).toEqual({ type: 'agent', id: 'agent-001' });
    });

    it('clearSelection clears selection', () => {
      useExecutionStore.getState().select('stage', 'stage-001');
      useExecutionStore.getState().clearSelection();
      expect(useExecutionStore.getState().selection).toBeNull();
    });
  });

  // =========================================================================
  // WS Status
  // =========================================================================

  describe('wsStatus', () => {
    it('setWSStatus merges partial status', () => {
      useExecutionStore.getState().setWSStatus({ connected: true });
      expect(useExecutionStore.getState().wsStatus.connected).toBe(true);
      expect(useExecutionStore.getState().wsStatus.reconnectAttempt).toBe(0);
    });

    it('setWSStatus updates reconnect attempt', () => {
      useExecutionStore.getState().setWSStatus({ reconnectAttempt: 3 });
      expect(useExecutionStore.getState().wsStatus.reconnectAttempt).toBe(3);
    });
  });
});
