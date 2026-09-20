/* TypeScript interfaces matching the v1 Python backend (snake_case). */

/**
 * Every status the backend can report.
 *
 * The narrow four-value unions this replaces predated `cancelled` (a user
 * cancel, distinct from a failure), `queued` (external execution mode, before
 * a worker claims the run), `waiting` (parked at a human gate) and the
 * reaper's `interrupted`/`orphaned`, so TypeScript rejected perfectly valid
 * comparisons against them.
 */
export type ExecutionStatus =
  | 'pending'
  | 'queued'
  | 'running'
  | 'waiting'
  | 'cancelling'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'interrupted'
  | 'orphaned'
  | 'skipped';

export interface WorkflowExecution {
  id: string;
  workflow_name: string;
  status: ExecutionStatus;
  start_time: string | null;
  end_time: string | null;
  duration_seconds: number | null;
  nodes: NodeExecution[];
  // Backward compat alias — components that reference .stages get the same data
  stages?: NodeExecution[];
  total_tokens?: number;
  total_cost_usd?: number;
  total_llm_calls?: number;
  total_tool_calls?: number;
  input_data?: Record<string, unknown>;
  output_data?: Record<string, unknown>;
  error_message?: string;
  workflow_config?: Record<string, unknown>;
  workflow_config_snapshot?: Record<string, unknown>;
}

export interface NodeExecution {
  id: string;
  name: string;
  type: 'agent' | 'stage' | 'delegate';
  status: ExecutionStatus;
  start_time: string | null;
  end_time: string | null;
  duration_seconds: number | null;
  cost_usd: number;
  total_tokens: number;
  total_llm_calls?: number;
  total_tool_calls?: number;
  // For agent nodes (type='agent'):
  agent?: AgentExecution;
  // For stage nodes (type='stage'):
  agents?: AgentExecution[];
  child_nodes?: NodeExecution[];
  strategy?: string;
  error_message?: string;
  // Backward compat fields — old components reference these
  stage_name?: string;
  stage_id?: string;
  stage_type?: string;
  num_agents_executed?: number;
  num_agents_succeeded?: number;
  num_agents_failed?: number;
  input_data?: Record<string, unknown>;
  output_data?: Record<string, unknown>;
  // DAG metadata (from executor event data)
  depends_on?: string[];
  loop_to?: string;
  max_loops?: number;
  // Delegate metadata
  delegated_by?: string;
  delegate_source?: string;
  // Dispatch metadata (runtime DAG mutation — see stage/dispatch.py)
  // Populated by api/data_service.py._annotate_dispatch_relationships.
  dispatched_by?: string;            // dispatcher node that ADDED this node
  dispatched_children?: string[];    // (this node is a dispatcher) names it added
  // input_map entries that pointed at something that did not exist; the
  // agent ran with nulls in their place (see stage/executor.py).
  unresolved_inputs?: string[];
  // Human gate (stage/executor.py `_wait_for_gate`): `gate` marks the node as
  // gated at all, `gate_status` is 'waiting' until someone approves it.
  gate?: boolean;
  gate_status?: 'waiting' | 'approved';
  removed_children?: string[];       // (this node is a dispatcher) names it removed
  // Backward compat
  collaboration_events?: CollaborationEvent[];
  stage_config_snapshot?: {
    stage?: {
      collaboration?: { strategy?: string };
      execution?: { agent_mode?: string };
    };
  };
}

export interface StageConfig {
  name: string;
  depends_on?: string[];
  loops_back_to?: string;
  max_loops?: number;
  execution?: { agent_mode?: string };
  collaboration?: { strategy?: string };
}

// Backward compat alias — many components still reference StageExecution
export type StageExecution = NodeExecution;

export interface AgentExecution {
  id: string;
  agent_name: string;
  name?: string;
  status: ExecutionStatus;
  start_time: string | null;
  end_time: string | null;
  duration_seconds: number | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number;
  confidence_score?: number | null;
  total_llm_calls: number;
  total_tool_calls: number;
  llm_calls: LLMCall[];
  tool_calls: ToolCall[];
  output?: string;
  reasoning?: string;
  error_message?: string;
  // Backward compat
  agent_id?: string;
  stage_id?: string;
  stage_execution_id?: string;
  role?: string;
  input_data?: Record<string, unknown>;
  output_data?: Record<string, unknown>;
  agent_config_snapshot?: {
    agent?: {
      model?: string;
      type?: string;
      provider?: string;
      temperature?: number;
      max_tokens?: number;
      token_budget?: number;
      max_iterations?: number;
      system_prompt?: string;
      task_template?: string;
      tools?: string[];
      memory?: Record<string, unknown>;
      inputs?: Record<string, unknown>;
      outputs?: Record<string, unknown>;
    };
  };
}

export interface LLMCall {
  id: string;
  provider?: string;
  model?: string;
  status: ExecutionStatus;
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
  thinking?: string;
  tool_calls?: { name: string; id?: string }[];
  error_message?: string;
  // Backward compat
  llm_call_id?: string;
  agent_id?: string;
  agent_execution_id?: string;
  tool_calls_made?: number;
}

export interface ToolCall {
  id: string;
  tool_name: string;
  status: ExecutionStatus;
  // Where the call went and who ran it. transport "mcp" means a named MCP
  // server; "builtin" means a tool of whoever executed it. executed_by is
  // "temper" for tools temper ran, or a provider name (e.g. "claude") for
  // tools the provider ran inside its own process — Claude Code runs Bash,
  // WebSearch and every MCP server it is given that way, and those were
  // invisible here until the provider started reporting them.
  transport?: 'mcp' | 'builtin' | string | null;
  server?: string | null;
  executed_by?: string | null;
  call_id?: string | null;
  start_time: string | null;
  end_time: string | null;
  duration_seconds: number | null;
  input_params?: Record<string, unknown>;
  input_data?: Record<string, unknown>;
  output_data?: unknown;
  approval_required?: boolean;
  error_message?: string;
  // Backward compat
  tool_execution_id?: string;
  agent_id?: string;
  agent_execution_id?: string;
  safety_checks_applied?: unknown;
}

export interface CollaborationEvent {
  event_type: string;
  from_agent?: string;
  to_agent?: string;
  agents_involved?: string[];
  timestamp?: string;
  data?: Record<string, unknown>;
}

export interface ToolActivity {
  toolName: string;
  status: ExecutionStatus;
  startedAt: string;
  completedAt?: string;
  durationSeconds?: number;
  args?: Record<string, unknown>;
}

export interface StreamEntry {
  content: string;
  thinking: string;
  /** Currently streaming tool call (name + arguments as they arrive). */
  activeToolCall: string;
  done: boolean;
  toolActivity: ToolActivity[];
}

/* WebSocket message types */

export interface WSSnapshot {
  type: 'snapshot';
  workflow: WorkflowExecution;
}

export interface WSEvent {
  type: 'event';
  event_type: string;
  execution_id?: string;
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
  wsError: 'auth_failed' | 'max_retries' | null;
}

/* Event log entry (stored in Zustand) */

export interface EventLogEntry {
  timestamp: string;
  event_type: string;
  label: string;
  data?: Record<string, unknown>;
}

/* Helper: get all agents from a node (works for both agent and stage nodes) */
export function getNodeAgents(node: NodeExecution): AgentExecution[] {
  if (node.type === 'agent' && node.agent) {
    return [node.agent];
  }
  return node.agents || [];
}

/* Helper: get node display name */
export function getNodeDisplayName(node: NodeExecution): string {
  return node.name;
}

/* Helper: adapt WorkflowExecution to old stages-based format for backward compat */
export function getStages(workflow: WorkflowExecution): NodeExecution[] {
  return workflow.nodes || [];
}
