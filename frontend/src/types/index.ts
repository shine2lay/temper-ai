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
  /** Every agent the run started (see AgentIndexEntry). Absent from servers
   *  that predate it. */
  agent_index?: AgentIndexEntry[];
  /** Where the run stopped, when a failure stopped it. */
  stopped?: RunStopped | null;
  /** The clean-ups the run is holding back so a resume can use the same setup. */
  hold?: CleanupHoldInfo | null;
  /** Every attempt of this run, oldest first "" a run cut off and started again from where
   *  it stopped keeps its id and gets another one. One entry (or none) means it ran once. */
  attempts?: RunAttempt[] | null;
  /** Still marked running, but nothing new for longer than this workflow's
   *  threshold (``quiet_after``, 30 minutes by default). A run waiting at a
   *  gate is never quiet -- that is `waiting_on_you`. */
  quiet?: boolean;
  /** How long it has been quiet, in words: "2h 14m". */
  quiet_for?: string;
  /** When it last did anything, ISO. */
  quiet_since?: string | null;
  quiet_seconds?: number;
  /** The last thing it did, e.g. the deploy step running bash. */
  last_step?: string;
  last_activity?: string | null;
  /** Parked at a gate: healthy, and yours to answer. */
  waiting_on_you?: boolean;
  /** How long it has been waiting for you: "10h". */
  waiting_for?: string;
  /** Waiting for the model allowance to reopen: every account's ceiling is
   *  spent, so the run set itself aside and will carry on by itself. Healthy,
   *  never quiet, and nothing for anyone to do. */
  parked?: boolean;
  /** When it expects to carry on, ISO. */
  parked_until?: string | null;
  /** A parked Pi run while the Pi switch is off, in words: it waits, with any
   *  answer kept, and carries on once the switch is back on (runner/parked.py). */
  pi_switched_off?: string;
  /** Why a queued run hasn't started, in words: "waiting for the Pi lane" for a Pi run
   *  the Pi lane hasn't claimed, while another Pi run holds it or the lane is down or
   *  switched off. It never starts anywhere else (docs/pi-lane.md). */
  queued_reason?: string;
}

/** One attempt of a run: when it ran, how it ended, and who started it again. */
export interface RunAttempt {
  /** 1 for the first attempt, 2 for the next... */
  attempt: number;
  event_id: string | null;
  start_time: string | null;
  status: ExecutionStatus;
  error?: string | null;
  /** The attempt shown as the run's own state; the others are history. */
  is_current: boolean;
  /** temper picked this attempt back up itself after a crash, rather than a person. */
  picked_up_by_temper: boolean;
  picked_up_at?: string | null;
}

/** Where a run stopped and what it is keeping back (the engine's stage/failure.py). */
export interface RunStopped {
  /** The step it stopped at, by its full path. */
  path: string;
  reason: string;
  /** When it stopped. */
  at: string | null;
  mode: 'hold' | 'cleanup';
  held: { path: string; undoes: string[] }[];
}

/** A run's held clean-ups: what is being kept, and until when. */
export interface CleanupHoldInfo {
  execution_id: string;
  workflow_name: string;
  cleanups: { path: string; undoes: string[] }[];
  deadline: string | null;
  seconds_left: number | null;
  stopped_at: string | null;
  stop_reason: string | null;
}

/**
 * One agent the run started, from the server's agent index. The node tree
 * keeps one node per name, so an earlier loop round or an attempt a resume
 * replaced is not in it, while its output still streams to the page; the
 * index names every one of them. Light: no calls, prompts, inputs or
 * outputs. Also served on its own by GET /api/workflows/{id}/agents.
 */
export interface AgentIndexEntry {
  id: string;
  agent_name: string;
  /** 1 for the first agent of this name in the run, 2 for the next... */
  round: number;
  status: ExecutionStatus;
  node_id: string | null;
  node_name: string | null;
  start_time: string | null;
  end_time: string | null;
  duration_seconds: number | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number;
  error_message?: string | null;
  role?: string | null;
  agent_type?: string | null;
  provider?: string | null;
  model?: string | null;
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
  // gated at all, `gate_status` is 'waiting' until someone approves it
  // ('rejected': the run was stopped there; 'replaced': the run was picked up
  // again and a later wait took this one's place).
  gate?: boolean;
  gate_status?: 'waiting' | 'approved' | 'rejected' | 'replaced';
  /** Who answered the wait: the person, or what they answered through. */
  gate_decided_by?: string | null;
  gate_decided_at?: string | null;
  /** The caller that sent the answer: a named key, slack:<user id>, telegram:<user id>... */
  gate_caller?: string | null;
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
  /** From the agent index: which run of its name this is, and its node. */
  round?: number;
  node_name?: string | null;
  /** Built from the agent index alone: no calls or output on the page. */
  summary_only?: boolean;
  /** A script agent's saved log, in figures (its completion event): the log itself is read
   *  page by page, never carried here. */
  log?: ScriptLogSummary | null;
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

/** Where streamed thinking (chunk_type "thinking") sits in the text: the
 *  slice thinking[from, to) arrived when content was `at` long. */
export interface ThinkingMark {
  at: number;
  from: number;
  to: number;
}

export interface StreamEntry {
  content: string;
  thinking: string;
  /** Currently streaming tool call (name + arguments as they arrive). */
  activeToolCall: string;
  /** The last model call ended (a done chunk). An agent makes many calls,
   *  so more output can follow; the agent's own status says when it ends. */
  done: boolean;
  toolActivity: ToolActivity[];
  /** Order of thinking and text, so the live strip shows them interleaved. */
  thinkingMarks?: ThinkingMark[];
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

/** One saved row of a script agent's log, sent as it is saved (see lib/scriptLog.ts). */
export interface WSScriptLog {
  type: 'script_log';
  execution_id?: string;
  data: unknown;
}

export type WSMessage = WSSnapshot | WSEvent | WSHeartbeat | WSScriptLog;

/** What a script agent's completion says about its saved log. */
export interface ScriptLogSummary {
  rows?: number;
  saved_bytes?: number;
  dropped_bytes?: number;
  lost_bytes?: number;
  limit?: number;
  truncated?: boolean;
  /** False when the end of the log (its end note included) could not be saved. */
  complete?: boolean;
}

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
