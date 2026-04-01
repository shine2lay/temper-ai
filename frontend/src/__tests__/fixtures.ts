/**
 * Shared test fixtures matching the backend's actual REST/WS response shapes.
 * Field names use the backend convention (start_time, end_time, error_message, etc.).
 */
import type { WorkflowExecution, StageExecution, AgentExecution, LLMCall, ToolCall, WSEvent } from '@/types';

export const MOCK_LLM_CALL: LLMCall = {
  id: 'llm-001',
  agent_execution_id: 'agent-001',
  provider: 'ollama',
  model: 'qwen3',
  status: 'completed',
  start_time: '2026-02-18T04:10:00Z',
  end_time: '2026-02-18T04:10:05Z',
  duration_seconds: 5,
  latency_ms: 5000,
  prompt_tokens: 200,
  completion_tokens: 150,
  total_tokens: 350,
  estimated_cost_usd: 0.01,
  prompt: [{ role: 'user', content: 'Analyze this decision' }],
  response: 'Here is my analysis...',
};

export const MOCK_TOOL_CALL: ToolCall = {
  id: 'tool-001',
  tool_execution_id: 'tool-001',
  agent_execution_id: 'agent-001',
  tool_name: 'Bash',
  status: 'completed',
  start_time: '2026-02-18T04:10:05Z',
  end_time: '2026-02-18T04:10:06Z',
  duration_seconds: 1,
  input_params: { command: 'echo hello' },
  output_data: { stdout: 'hello' },
  safety_checks_applied: ['command_injection_check'],
};

export const MOCK_AGENT: AgentExecution = {
  id: 'agent-001',
  agent_name: 'optimist',
  status: 'completed',
  stage_execution_id: 'stage-001',
  start_time: '2026-02-18T04:10:00Z',
  end_time: '2026-02-18T04:10:10Z',
  duration_seconds: 10,
  prompt_tokens: 200,
  completion_tokens: 150,
  total_tokens: 350,
  estimated_cost_usd: 0.01,
  confidence_score: 0.85,
  total_llm_calls: 1,
  total_tool_calls: 1,
  llm_calls: [MOCK_LLM_CALL],
  tool_calls: [MOCK_TOOL_CALL],
  output: 'Positive analysis',
  reasoning: 'Based on the evidence...',
  agent_config_snapshot: { agent: { model: 'qwen3', provider: 'ollama', type: 'standard' } },
};

export const MOCK_AGENT_2: AgentExecution = {
  id: 'agent-002',
  agent_name: 'skeptic',
  status: 'running',
  stage_execution_id: 'stage-001',
  start_time: '2026-02-18T04:10:00Z',
  end_time: null,
  duration_seconds: null,
  prompt_tokens: 100,
  completion_tokens: 0,
  total_tokens: 100,
  estimated_cost_usd: 0,
  confidence_score: null,
  total_llm_calls: 0,
  total_tool_calls: 0,
  llm_calls: [],
  tool_calls: [],
  agent_config_snapshot: { agent: { model: 'qwen3', provider: 'ollama', type: 'standard' } },
};

export const MOCK_STAGE: StageExecution = {
  id: 'stage-001',
  name: 'decision',
  stage_name: 'decision',
  type: 'stage',
  status: 'running',
  start_time: '2026-02-18T04:10:00Z',
  end_time: null,
  duration_seconds: null,
  cost_usd: 0.01,
  total_tokens: 450,
  agents: [MOCK_AGENT, MOCK_AGENT_2],
  num_agents_executed: 2,
  num_agents_succeeded: 1,
  num_agents_failed: 0,
  stage_config_snapshot: {
    stage: {
      collaboration: { strategy: 'parallel' },
      execution: { agent_mode: 'parallel' },
    },
  },
};

export const MOCK_WORKFLOW: WorkflowExecution = {
  id: 'wf-test-001',
  workflow_name: 'quick_decision_demo',
  status: 'running',
  start_time: '2026-02-18T04:10:00Z',
  end_time: null,
  duration_seconds: null,
  nodes: [MOCK_STAGE],
  stages: [MOCK_STAGE],
  total_tokens: 450,
  total_cost_usd: 0.01,
};

export const COMPLETED_WORKFLOW: WorkflowExecution = {
  ...MOCK_WORKFLOW,
  status: 'completed',
  end_time: '2026-02-18T04:11:00Z',
  duration_seconds: 60,
  nodes: [{
    ...MOCK_STAGE,
    status: 'completed',
    end_time: '2026-02-18T04:11:00Z',
    duration_seconds: 60,
    agents: [
      { ...MOCK_AGENT, status: 'completed' },
      { ...MOCK_AGENT_2, status: 'completed', end_time: '2026-02-18T04:11:00Z', duration_seconds: 60 },
    ],
  }],
  stages: [{
    ...MOCK_STAGE,
    status: 'completed',
    end_time: '2026-02-18T04:11:00Z',
    duration_seconds: 60,
    agents: [
      { ...MOCK_AGENT, status: 'completed' },
      { ...MOCK_AGENT_2, status: 'completed', end_time: '2026-02-18T04:11:00Z', duration_seconds: 60 },
    ],
  }],
};

// --- WebSocket event fixtures ---

export function makeStageStartEvent(overrides: Partial<WSEvent['data']> = {}): WSEvent {
  return {
    type: 'event',
    event_type: 'stage_start',
    stage_id: 'stage-002',
    timestamp: '2026-02-18T04:12:00Z',
    data: {
      id: 'stage-002',
      stage_id: 'stage-002',
      stage_name: 'review',
      status: 'running',
      start_time: '2026-02-18T04:12:00Z',
      ...overrides,
    },
  };
}

export function makeAgentStartEvent(overrides: Partial<WSEvent['data']> = {}): WSEvent {
  return {
    type: 'event',
    event_type: 'agent_start',
    stage_id: 'stage-001',
    agent_id: 'agent-003',
    timestamp: '2026-02-18T04:12:01Z',
    data: {
      id: 'agent-003',
      agent_id: 'agent-003',
      agent_name: 'reviewer',
      stage_id: 'stage-001',
      status: 'running',
      start_time: '2026-02-18T04:12:01Z',
      ...overrides,
    },
  };
}

export function makeAgentEndEvent(overrides: Partial<WSEvent['data']> = {}): WSEvent {
  return {
    type: 'event',
    event_type: 'agent_end',
    agent_id: 'agent-002',
    timestamp: '2026-02-18T04:12:05Z',
    data: {
      agent_id: 'agent-002',
      agent_name: 'skeptic',
      status: 'completed',
      end_time: '2026-02-18T04:12:05Z',
      duration_seconds: 125,
      total_tokens: 500,
      prompt_tokens: 200,
      completion_tokens: 300,
      estimated_cost_usd: 0.02,
      total_llm_calls: 2,
      total_tool_calls: 0,
      ...overrides,
    },
  };
}

export function makeLlmCallEvent(overrides: Partial<WSEvent['data']> = {}): WSEvent {
  return {
    type: 'event',
    event_type: 'llm_call',
    agent_id: 'agent-001',
    timestamp: '2026-02-18T04:12:10Z',
    data: {
      llm_call_id: 'llm-002',
      id: 'llm-002',
      agent_id: 'agent-001',
      provider: 'ollama',
      model: 'qwen3',
      status: 'completed',
      prompt_tokens: 100,
      completion_tokens: 80,
      total_tokens: 180,
      estimated_cost_usd: 0.005,
      latency_ms: 3000,
      ...overrides,
    },
  };
}

export function makeToolCallEvent(overrides: Partial<WSEvent['data']> = {}): WSEvent {
  return {
    type: 'event',
    event_type: 'tool_call',
    agent_id: 'agent-001',
    timestamp: '2026-02-18T04:12:15Z',
    data: {
      tool_execution_id: 'tool-002',
      id: 'tool-002',
      agent_id: 'agent-001',
      tool_name: 'FileWriter',
      status: 'completed',
      duration_seconds: 0.5,
      input_params: { path: '/tmp/output.txt' },
      output_data: { written: true },
      ...overrides,
    },
  };
}

export function makeStreamBatchEvent(agentId: string, chunks: Array<{ content: string; done?: boolean; chunk_type?: string }>): WSEvent {
  return {
    type: 'event',
    event_type: 'llm_stream_batch',
    agent_id: agentId,
    timestamp: '2026-02-18T04:12:20Z',
    data: {
      chunks: chunks.map((c) => ({ agent_id: agentId, ...c })),
    },
  };
}

export function makeWorkflowEndEvent(overrides: Partial<WSEvent['data']> = {}): WSEvent {
  return {
    type: 'event',
    event_type: 'workflow_end',
    timestamp: '2026-02-18T04:13:00Z',
    data: {
      status: 'completed',
      end_time: '2026-02-18T04:13:00Z',
      duration_seconds: 180,
      ...overrides,
    },
  };
}

export function makeStageEndEvent(overrides: Partial<WSEvent['data']> = {}): WSEvent {
  return {
    type: 'event',
    event_type: 'stage_end',
    stage_id: 'stage-001',
    timestamp: '2026-02-18T04:12:30Z',
    data: {
      stage_id: 'stage-001',
      stage_name: 'decision',
      status: 'completed',
      end_time: '2026-02-18T04:12:30Z',
      duration_seconds: 150,
      ...overrides,
    },
  };
}
