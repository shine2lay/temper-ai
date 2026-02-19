/* TypeScript interfaces matching the Python backend exactly (snake_case). */

export interface WorkflowExecution {
  id: string;
  workflow_name: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  start_time: string | null;
  end_time: string | null;
  duration_seconds: number | null;
  workflow_config?: { workflow?: { stages?: StageConfig[] }; stages?: StageConfig[] };
  workflow_config_snapshot?: { workflow?: { stages?: StageConfig[] }; stages?: StageConfig[] };
  stages: StageExecution[];
  total_tokens?: number;
  total_cost_usd?: number;
  total_llm_calls?: number;
  total_tool_calls?: number;
  input_data?: Record<string, unknown>;
  output_data?: Record<string, unknown>;
  error_message?: string;
}

export interface StageConfig {
  name: string;
  depends_on?: string[];
  loops_back_to?: string;
  max_loops?: number;
  execution?: { agent_mode?: string };
  collaboration?: { strategy?: string };
}

export interface StageExecution {
  id: string;
  stage_name: string;
  name?: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  stage_id?: string;
  start_time: string | null;
  end_time: string | null;
  duration_seconds: number | null;
  stage_type?: string;
  agents: AgentExecution[];
  num_agents_executed?: number;
  num_agents_succeeded?: number;
  num_agents_failed?: number;
  input_data?: Record<string, unknown>;
  output_data?: Record<string, unknown>;
  collaboration_events?: CollaborationEvent[];
  stage_config_snapshot?: {
    stage: {
      collaboration?: { strategy?: string };
      execution?: { agent_mode?: string };
    };
  };
  error_message?: string;
}

export interface AgentExecution {
  id: string;
  agent_name: string;
  name?: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  agent_id?: string;
  stage_id?: string;
  stage_execution_id?: string;
  role?: string;
  start_time: string | null;
  end_time: string | null;
  duration_seconds: number | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number;
  confidence_score: number | null;
  total_llm_calls: number;
  total_tool_calls: number;
  llm_calls: LLMCall[];
  tool_calls: ToolCall[];
  input_data?: Record<string, unknown>;
  output_data?: Record<string, unknown>;
  output?: string;
  reasoning?: string;
  agent_config_snapshot?: {
    agent: {
      model?: string;
      type?: string;
      provider?: string;
    };
  };
  error_message?: string;
}

export interface LLMCall {
  id: string;
  llm_call_id?: string;
  agent_id?: string;
  agent_execution_id?: string;
  provider?: string;
  model?: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  start_time: string | null;
  end_time: string | null;
  duration_seconds: number | null;
  latency_ms?: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number;
  prompt?: unknown;
  response?: string;
  error_message?: string;
  tool_calls_made?: number;
}

export interface ToolCall {
  id: string;
  tool_execution_id?: string;
  agent_id?: string;
  agent_execution_id?: string;
  tool_name: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  start_time: string | null;
  end_time: string | null;
  duration_seconds: number | null;
  input_params?: Record<string, unknown>;
  output_data?: unknown;
  safety_checks_applied?: unknown;
  approval_required?: boolean;
  error_message?: string;
}

export interface CollaborationEvent {
  event_type: string;
  from_agent?: string;
  to_agent?: string;
  agents_involved?: string[];
  timestamp?: string;
  data?: Record<string, unknown>;
}

export interface StreamEntry {
  content: string;
  thinking: string;
  done: boolean;
}

/* WebSocket message types */

export interface WSSnapshot {
  type: 'snapshot';
  workflow: WorkflowExecution;
}

export interface WSEvent {
  type: 'event';
  event_type: string;
  workflow_id?: string;
  stage_id?: string;
  agent_id?: string;
  data: Record<string, unknown>;
  timestamp?: string;
}

export interface WSHeartbeat {
  type: 'heartbeat';
  timestamp: string;
}

export type WSMessage = WSSnapshot | WSEvent | WSHeartbeat;

/* Selection state */

export type SelectionType = 'workflow' | 'stage' | 'agent' | 'llmCall' | 'toolCall';

export interface Selection {
  type: SelectionType;
  id: string;
}

/* WebSocket connection status */

export interface WSStatus {
  connected: boolean;
  reconnectAttempt: number;
  lastHeartbeat: string | null;
}

/* Event log entry (stored in Zustand) */

export interface EventLogEntry {
  timestamp: string;
  event_type: string;
  label: string;
  data?: Record<string, unknown>;
}
