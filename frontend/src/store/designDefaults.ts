/**
 * Default factory functions and normalization helpers for the design store.
 */
import type { WorkflowMeta, WorkflowOutput, DesignStage } from './designTypes';

const DEFAULT_TIMEOUT = 600;

/** Normalize outputs from YAML — handles both string[] and object[] formats. */
export function normalizeOutputs(raw: unknown): WorkflowOutput[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => {
    if (typeof item === 'string') {
      return { name: item, description: '', source: '' };
    }
    if (typeof item === 'object' && item !== null) {
      const obj = item as Record<string, unknown>;
      return {
        name: (obj.name as string) ?? '',
        description: (obj.description as string) ?? '',
        source: (obj.source as string) ?? '',
      };
    }
    return { name: String(item), description: '', source: '' };
  });
}

export function defaultMeta(): WorkflowMeta {
  return {
    // General
    name: '',
    description: '',
    version: '1.0',
    product_type: null,

    // Defaults
    default_provider: '',
    default_model: '',

    // Execution
    timeout_seconds: DEFAULT_TIMEOUT,
    max_iterations: 100,
    convergence_detection: false,
    tool_cache_enabled: false,
    predecessor_injection: false,

    // Budget
    max_cost_usd: null,
    max_tokens: null,
    budget_action_on_exceed: 'halt',

    // Error Handling
    on_stage_failure: 'halt',
    max_stage_retries: 3,
    escalation_policy: 'GracefulDegradation',
    enable_rollback: true,

    // Safety
    global_safety_mode: 'execute',
    safety_composition_strategy: 'MostRestrictive',
    approval_required_stages: [],
    dry_run_stages: [],

    // Inputs / Outputs
    required_inputs: [],
    optional_inputs: [],
    outputs: [],

    // Rate Limiting
    rate_limit_enabled: false,
    rate_limit_max_rpm: 60,
    rate_limit_block_on_limit: true,
    rate_limit_max_wait_seconds: 60,

    // Planning Pass
    planning_enabled: false,
    planning_provider: 'openai',
    planning_model: 'gpt-4o-mini',
    planning_temperature: 0.3,
    planning_max_tokens: 2048,

    // Observability
    observability_console_mode: 'standard',
    observability_trace_everything: true,
    observability_export_format: ['json', 'sqlite'],
    observability_dag_visualization: true,
    observability_waterfall: true,

    // Autonomous Loop
    autonomous_enabled: false,
    autonomous_learning: true,
    autonomous_goals: true,
    autonomous_portfolio: true,
    autonomous_auto_apply_learning: false,
    autonomous_auto_apply_goals: false,
    autonomous_prompt_optimization: false,
    autonomous_agent_memory_sync: false,

    // Lifecycle
    lifecycle_enabled: false,
    lifecycle_profile: null,
    lifecycle_auto_classify: true,

    // Metadata
    tags: [],
    owner: null,
  };
}

export function defaultDesignStage(name: string = ''): DesignStage {
  return {
    name,
    stage_ref: null,
    depends_on: [],
    loops_back_to: null,
    max_loops: null,
    condition: null,
    inputs: {},
    agents: [],
    agent_mode: 'sequential',
    collaboration_strategy: 'independent',
    // Execution
    timeout_seconds: 1800,
    // Collaboration
    collaboration_max_rounds: 3,
    collaboration_convergence_threshold: 0.8,
    collaboration_dialogue_mode: false,
    collaboration_roles: {},
    collaboration_round_budget_usd: null,
    collaboration_max_dialogue_rounds: 3,
    collaboration_context_window_rounds: 2,
    // Conflict Resolution
    conflict_strategy: '',
    conflict_metrics: ['confidence'],
    conflict_metric_weights: {},
    conflict_auto_resolve_threshold: 0.85,
    conflict_escalation_threshold: 0.5,
    // Safety
    safety_mode: 'execute',
    safety_dry_run_first: false,
    safety_require_approval: false,
    // Error Handling
    error_on_agent_failure: 'continue_with_remaining',
    error_min_successful_agents: 1,
    error_retry_failed_agents: true,
    error_max_agent_retries: 2,
    // Quality Gates
    quality_gates_enabled: false,
    quality_gates_min_confidence: 0.7,
    quality_gates_min_findings: 5,
    quality_gates_require_citations: true,
    quality_gates_on_failure: 'retry_stage',
    quality_gates_max_retries: 2,
    // Convergence
    convergence_enabled: false,
    convergence_max_iterations: 5,
    convergence_similarity_threshold: 0.95,
    convergence_method: 'exact_hash',
    // Identity
    description: '',
    version: '1.0',
    // Outputs
    outputs: {},
  };
}
