/**
 * Type definitions for the Workflow Studio design store.
 */

export type AgentMode = 'sequential' | 'parallel' | 'adaptive';
export type CollaborationStrategy = 'independent' | 'leader' | 'consensus' | 'debate' | 'round_robin';

export interface DesignStage {
  name: string;
  stage_ref: string | null;
  depends_on: string[];
  loops_back_to: string | null;
  max_loops: number | null;
  condition: string | null;
  inputs: Record<string, { source: string }>;
  /** Agent names — only used for inline stages (no stage_ref). */
  agents: string[];
  agent_mode: AgentMode;
  collaboration_strategy: CollaborationStrategy;

  // --- Execution ---
  timeout_seconds: number;

  // --- Collaboration ---
  collaboration_max_rounds: number;
  collaboration_convergence_threshold: number;
  collaboration_dialogue_mode: boolean;
  collaboration_roles: Record<string, string>;
  collaboration_round_budget_usd: number | null;
  collaboration_max_dialogue_rounds: number;
  collaboration_context_window_rounds: number;

  // --- Conflict Resolution ---
  conflict_strategy: string;
  conflict_metrics: string[];
  conflict_metric_weights: Record<string, string>;
  conflict_auto_resolve_threshold: number;
  conflict_escalation_threshold: number;

  // --- Safety ---
  safety_mode: string;
  safety_dry_run_first: boolean;
  safety_require_approval: boolean;

  // --- Error Handling ---
  error_on_agent_failure: string;
  error_min_successful_agents: number;
  error_retry_failed_agents: boolean;
  error_max_agent_retries: number;

  // --- Quality Gates ---
  quality_gates_enabled: boolean;
  quality_gates_min_confidence: number;
  quality_gates_min_findings: number;
  quality_gates_require_citations: boolean;
  quality_gates_on_failure: string;
  quality_gates_max_retries: number;

  // --- Convergence ---
  convergence_enabled: boolean;
  convergence_max_iterations: number;
  convergence_similarity_threshold: number;
  convergence_method: string;

  // --- Identity ---
  description: string;
  version: string;

  // --- Outputs ---
  outputs: Record<string, string>;
}

export interface WorkflowOutput {
  name: string;
  description: string;
  source: string;
}

export interface WorkflowMeta {
  // --- General ---
  name: string;
  description: string;
  version: string;
  product_type: string | null;

  // --- Execution ---
  timeout_seconds: number;
  max_iterations: number;
  convergence_detection: boolean;
  tool_cache_enabled: boolean;
  predecessor_injection: boolean;

  // --- Budget ---
  max_cost_usd: number | null;
  max_tokens: number | null;
  budget_action_on_exceed: 'halt' | 'continue' | 'notify';

  // --- Error Handling ---
  on_stage_failure: 'halt' | 'continue' | 'skip' | 'retry';
  max_stage_retries: number;
  escalation_policy: string;
  enable_rollback: boolean;

  // --- Safety ---
  global_safety_mode: 'execute' | 'monitor' | 'audit';
  safety_composition_strategy: string;
  approval_required_stages: string[];
  dry_run_stages: string[];

  // --- Inputs / Outputs ---
  required_inputs: string[];
  optional_inputs: string[];
  outputs: WorkflowOutput[];

  // --- Rate Limiting ---
  rate_limit_enabled: boolean;
  rate_limit_max_rpm: number;
  rate_limit_block_on_limit: boolean;
  rate_limit_max_wait_seconds: number;

  // --- Planning Pass ---
  planning_enabled: boolean;
  planning_provider: string;
  planning_model: string;
  planning_temperature: number;
  planning_max_tokens: number;

  // --- Observability ---
  observability_console_mode: 'minimal' | 'standard' | 'verbose';
  observability_trace_everything: boolean;
  observability_export_format: string[];
  observability_dag_visualization: boolean;
  observability_waterfall: boolean;

  // --- Autonomous Loop ---
  autonomous_enabled: boolean;
  autonomous_learning: boolean;
  autonomous_goals: boolean;
  autonomous_portfolio: boolean;
  autonomous_auto_apply_learning: boolean;
  autonomous_auto_apply_goals: boolean;
  autonomous_prompt_optimization: boolean;
  autonomous_agent_memory_sync: boolean;

  // --- Lifecycle ---
  lifecycle_enabled: boolean;
  lifecycle_profile: string | null;
  lifecycle_auto_classify: boolean;

  // --- Metadata ---
  tags: string[];
  owner: string | null;
}

export interface ValidationState {
  status: 'idle' | 'validating' | 'valid' | 'invalid';
  errors: string[];
}

/** Per-agent summary resolved from agent config files. */
export interface ResolvedAgentSummary {
  name: string;
  model: string;
  provider: string;
  type: string;
  toolCount: number;
  toolNames: string[];
  temperature: number;
  safetyMode: string;

  // Identity
  description: string;
  version: string;

  // Inference
  maxTokens: number;
  topP: number;
  timeoutSeconds: number;

  // Capability flags
  memoryEnabled: boolean;
  memoryType: string | null;
  reasoningEnabled: boolean;
  persistent: boolean;
  hasOutputSchema: boolean;
  hasPreCommands: boolean;
  preCommandCount: number;

  // Safety
  riskLevel: string;
  maxToolCalls: number;

  // Error handling
  retryStrategy: string;
  maxRetries: number;

  // Per-agent I/O
  promptInputs: string[];
  outputSchemaFields: { name: string; type: string }[];
}

/** Resolved agent info from stage configs (fetched at load time). */
export interface ResolvedStageInfo {
  agents: string[];
  agentMode: string;
  collaborationStrategy: string;
  description: string;
  timeoutSeconds: number | null;
  safetyMode: string | null;
  /** Stage-level input wiring from the stage config YAML. */
  inputs: Record<string, { source: string }>;
  outputs: { name: string; type: string; description: string }[];
  errorHandling: {
    onAgentFailure: string;
    minSuccessfulAgents: number | null;
    retryFailedAgents: boolean;
    maxAgentRetries: number | null;
  } | null;
  leaderAgent: string | null;

  // --- Expanded config details ---
  version: string | null;
  collaborationMaxRounds: number | null;
  collaborationConvergenceThreshold: number | null;
  collaborationDialogueMode: boolean | null;
  collaborationRoles: Record<string, string>;
  conflictResolution: {
    strategy: string;
    metrics: string[];
    metricWeights: Record<string, string>;
    autoResolveThreshold: number;
    escalationThreshold: number;
  } | null;
  safetyDryRunFirst: boolean | null;
  safetyRequireApproval: boolean | null;
  qualityGates: {
    enabled: boolean;
    minConfidence: number;
    minFindings: number;
    requireCitations: boolean;
    onFailure: string;
    maxRetries: number;
  } | null;
  convergence: {
    enabled: boolean;
    maxIterations: number;
    similarityThreshold: number;
    method: string;
  } | null;
}

export interface DesignState {
  configName: string | null;
  isDirty: boolean;
  meta: WorkflowMeta;
  stages: DesignStage[];
  selectedStageName: string | null;
  selectedAgentName: string | null;
  nodePositions: Record<string, { x: number; y: number }>;
  validation: ValidationState;
  /** Agent info resolved from stage_ref configs. Keyed by stage name. */
  resolvedStageInfo: Record<string, ResolvedStageInfo>;
  /** Per-agent summaries resolved from agent configs. Keyed by agent name. */
  resolvedAgentSummaries: Record<string, ResolvedAgentSummary>;

  /** Undo/redo history stacks. */
  _historyPast: import('./designHistory').DesignSnapshot[];
  _historyFuture: import('./designHistory').DesignSnapshot[];

  setMeta: (partial: Partial<WorkflowMeta>) => void;
  addStage: (stage: DesignStage) => void;
  updateStage: (name: string, partial: Partial<Omit<DesignStage, 'name'>>) => void;
  renameStage: (oldName: string, newName: string) => void;
  removeStage: (name: string) => void;
  addDependency: (source: string, target: string) => void;
  removeDependency: (source: string, target: string) => void;
  setLoopBack: (source: string, target: string | null, maxLoops?: number | null) => void;
  selectStage: (name: string | null) => void;
  selectAgent: (name: string | null) => void;
  setNodePosition: (name: string, x: number, y: number) => void;
  setValidation: (validation: ValidationState) => void;
  setResolvedStageInfo: (stageName: string, info: ResolvedStageInfo) => void;
  setResolvedAgentSummary: (name: string, summary: ResolvedAgentSummary) => void;
  markSaved: (name: string) => void;
  loadFromConfig: (name: string, config: Record<string, unknown>) => void;
  reset: () => void;
  toWorkflowConfig: () => Record<string, unknown>;

  /** Undo the last state-mutating action. */
  undo: () => void;
  /** Redo the last undone action. */
  redo: () => void;
  /** True when there is at least one undoable state. */
  canUndo: boolean;
  /** True when there is at least one redoable state. */
  canRedo: boolean;
}
