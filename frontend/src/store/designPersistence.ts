/**
 * Config serialization/deserialization helpers for the design store.
 * Handles loading from YAML workflow configs and serializing back to them.
 */
import type { WorkflowMeta, DesignStage, AgentMode, CollaborationStrategy } from './designTypes';
import { defaultMeta, defaultDesignStage, normalizeOutputs } from './designDefaults';

/** Parse a raw workflow config object into WorkflowMeta. */
export function parseWorkflowMeta(name: string, config: Record<string, unknown>): WorkflowMeta {
  const wf = (config as { workflow?: Record<string, unknown> }).workflow ?? config;
  const inner = wf as Record<string, unknown>;

  const cfg = (inner.config ?? {}) as Record<string, unknown>;
  const exec = (inner.execution ?? {}) as Record<string, unknown>;
  const budget = (cfg.budget ?? {}) as Record<string, unknown>;
  const rateLimit = (cfg.rate_limit ?? {}) as Record<string, unknown>;
  const planning = (cfg.planning ?? {}) as Record<string, unknown>;
  const errHandling = (inner.error_handling ?? {}) as Record<string, unknown>;
  const safety = (inner.safety ?? {}) as Record<string, unknown>;
  const obs = (inner.observability ?? {}) as Record<string, unknown>;
  const autoLoop = (inner.autonomous_loop ?? {}) as Record<string, unknown>;
  const lifecycle = (inner.lifecycle ?? {}) as Record<string, unknown>;
  const metadata = (inner.metadata ?? {}) as Record<string, unknown>;
  const wfDefaults = (inner.defaults ?? {}) as Record<string, unknown>;

  const inputsObj = (inner.inputs ?? {}) as Record<string, unknown>;
  const reqInputs =
    (inner.required_inputs as string[]) ?? (inputsObj.required as string[]) ?? [];
  const optInputs =
    (inner.optional_inputs as string[]) ?? (inputsObj.optional as string[]) ?? [];

  const pick = <T>(...candidates: unknown[]): T | undefined =>
    candidates.find((c) => c !== undefined && c !== null) as T | undefined;

  const defaults = defaultMeta();

  return {
    name: (inner.name as string) ?? name,
    description: (inner.description as string) ?? '',
    version: (inner.version as string) ?? defaults.version,
    product_type: (inner.product_type as string | null) ?? defaults.product_type,

    default_provider: (wfDefaults.provider as string) ?? defaults.default_provider,
    default_model: (wfDefaults.model as string) ?? defaults.default_model,

    timeout_seconds:
      pick<number>(inner.timeout_seconds, exec.timeout_seconds, cfg.timeout_seconds) ?? defaults.timeout_seconds,
    max_iterations:
      pick<number>(inner.max_iterations, exec.max_iterations, cfg.max_iterations) ?? defaults.max_iterations,
    convergence_detection:
      pick<boolean>(cfg.convergence_detection, exec.convergence_detection) ?? defaults.convergence_detection,
    tool_cache_enabled:
      pick<boolean>(cfg.tool_cache_enabled, exec.tool_cache_enabled) ?? defaults.tool_cache_enabled,
    predecessor_injection:
      pick<boolean>(inner.predecessor_injection, cfg.predecessor_injection) ?? defaults.predecessor_injection,

    max_cost_usd: pick<number | null>(inner.max_cost_usd, budget.max_cost_usd) ?? defaults.max_cost_usd,
    max_tokens: pick<number | null>(budget.max_tokens, inner.max_tokens) ?? defaults.max_tokens,
    budget_action_on_exceed:
      (pick<string>(budget.action_on_exceed, inner.budget_action_on_exceed) as WorkflowMeta['budget_action_on_exceed']) ??
      defaults.budget_action_on_exceed,

    on_stage_failure:
      (pick<string>(inner.on_stage_failure, errHandling.on_stage_failure) as WorkflowMeta['on_stage_failure']) ??
      defaults.on_stage_failure,
    max_stage_retries:
      pick<number>(errHandling.max_stage_retries, inner.max_stage_retries) ?? defaults.max_stage_retries,
    escalation_policy:
      pick<string>(errHandling.escalation_policy, inner.escalation_policy) ?? defaults.escalation_policy,
    enable_rollback:
      pick<boolean>(errHandling.enable_rollback, inner.enable_rollback) ?? defaults.enable_rollback,

    global_safety_mode:
      (pick<string>(inner.global_safety_mode, safety.global_mode) as WorkflowMeta['global_safety_mode']) ??
      defaults.global_safety_mode,
    safety_composition_strategy:
      pick<string>(safety.composition_strategy, inner.safety_composition_strategy) ?? defaults.safety_composition_strategy,
    approval_required_stages: (safety.approval_required_stages as string[]) ?? defaults.approval_required_stages,
    dry_run_stages: (safety.dry_run_stages as string[]) ?? defaults.dry_run_stages,

    required_inputs: reqInputs,
    optional_inputs: optInputs,
    outputs: normalizeOutputs(inner.outputs),

    rate_limit_enabled: pick<boolean>(rateLimit.enabled) ?? defaults.rate_limit_enabled,
    rate_limit_max_rpm: pick<number>(rateLimit.max_rpm) ?? defaults.rate_limit_max_rpm,
    rate_limit_block_on_limit: pick<boolean>(rateLimit.block_on_limit) ?? defaults.rate_limit_block_on_limit,
    rate_limit_max_wait_seconds: pick<number>(rateLimit.max_wait_seconds) ?? defaults.rate_limit_max_wait_seconds,

    planning_enabled: pick<boolean>(planning.enabled) ?? defaults.planning_enabled,
    planning_provider: pick<string>(planning.provider) ?? defaults.planning_provider,
    planning_model: pick<string>(planning.model) ?? defaults.planning_model,
    planning_temperature: pick<number>(planning.temperature) ?? defaults.planning_temperature,
    planning_max_tokens: pick<number>(planning.max_tokens) ?? defaults.planning_max_tokens,

    observability_console_mode:
      (pick<string>(obs.console_mode) as WorkflowMeta['observability_console_mode']) ??
      defaults.observability_console_mode,
    observability_trace_everything:
      pick<boolean>(obs.trace_everything) ?? defaults.observability_trace_everything,
    observability_export_format: (obs.export_format as string[]) ?? defaults.observability_export_format,
    observability_dag_visualization:
      pick<boolean>(obs.generate_dag_visualization, obs.dag_visualization) ?? defaults.observability_dag_visualization,
    observability_waterfall:
      pick<boolean>(obs.waterfall_in_console, obs.waterfall) ?? defaults.observability_waterfall,

    autonomous_enabled: pick<boolean>(autoLoop.enabled) ?? defaults.autonomous_enabled,
    autonomous_learning: pick<boolean>(autoLoop.learning_enabled) ?? defaults.autonomous_learning,
    autonomous_goals: pick<boolean>(autoLoop.goals_enabled) ?? defaults.autonomous_goals,
    autonomous_portfolio: pick<boolean>(autoLoop.portfolio_enabled) ?? defaults.autonomous_portfolio,
    autonomous_auto_apply_learning:
      pick<boolean>(autoLoop.auto_apply_learning) ?? defaults.autonomous_auto_apply_learning,
    autonomous_auto_apply_goals:
      pick<boolean>(autoLoop.auto_apply_goals) ?? defaults.autonomous_auto_apply_goals,
    autonomous_prompt_optimization:
      pick<boolean>(autoLoop.prompt_optimization_enabled) ?? defaults.autonomous_prompt_optimization,
    autonomous_agent_memory_sync:
      pick<boolean>(autoLoop.agent_memory_sync_enabled) ?? defaults.autonomous_agent_memory_sync,

    lifecycle_enabled: pick<boolean>(lifecycle.enabled) ?? defaults.lifecycle_enabled,
    lifecycle_profile: pick<string | null>(lifecycle.profile) ?? defaults.lifecycle_profile,
    lifecycle_auto_classify: pick<boolean>(lifecycle.auto_classify) ?? defaults.lifecycle_auto_classify,

    tags: (inner.tags as string[]) ?? (metadata.tags as string[]) ?? defaults.tags,
    owner: pick<string | null>(metadata.owner, inner.owner) ?? defaults.owner,
  };
}

/**
 * Parse stage inputs from either `inputs` (nested) or `input_map` (flat) format.
 * `input_map: { key: "source_ref" }` → `{ key: { source: "source_ref" } }`
 * `inputs: { key: { source: "ref" } }` used as-is.
 * `input_map` takes precedence when both are present.
 */
function parseStageInputs(rs: Record<string, unknown>): Record<string, { source: string }> {
  const inputMap = rs.input_map as Record<string, string> | undefined;
  if (inputMap && typeof inputMap === 'object') {
    const result: Record<string, { source: string }> = {};
    for (const [k, v] of Object.entries(inputMap)) {
      if (typeof v === 'string') result[k] = { source: v };
    }
    return result;
  }
  const explicit = (rs.inputs as Record<string, { source: string }>) ?? {};
  if (Object.keys(explicit).length > 0) return explicit;

  // Auto-generate inputs from depends_on so the Studio shows implicit data flow.
  // At runtime the executor injects upstream outputs as `other_agents`; mirror that here.
  const deps = (rs.depends_on as string[]) ?? [];
  if (deps.length > 0) {
    const result: Record<string, { source: string }> = {};
    for (const dep of deps) {
      result[`${dep}_output`] = { source: `${dep}.output` };
    }
    return result;
  }
  return {};
}

/** Normalize agents — handles plain strings, {agent, task_template} objects, and singular `agent` field. */
function normalizeAgentNames(agentsRaw: unknown, agentSingular?: unknown): string[] {
  if (Array.isArray(agentsRaw) && agentsRaw.length > 0) {
    return agentsRaw.map((item) => {
      if (typeof item === 'string') return item;
      if (typeof item === 'object' && item !== null) {
        return (item as Record<string, unknown>).agent as string ?? (item as Record<string, unknown>).name as string ?? '';
      }
      return String(item);
    }).filter(Boolean);
  }
  // Singular agent field (type: agent nodes)
  if (typeof agentSingular === 'string' && agentSingular) return [agentSingular];
  return [];
}

/** Parse raw stage entries from a workflow config. */
export function parseWorkflowStages(config: Record<string, unknown>): DesignStage[] {
  const wf = (config as { workflow?: Record<string, unknown> }).workflow ?? config;
  const inner = wf as Record<string, unknown>;
  const rawStages = (inner.stages ?? inner.nodes) as Array<Record<string, unknown>> ?? [];

  return rawStages.map((rs) => {
    const def = defaultDesignStage();
    const stageExec = rs.execution as Record<string, unknown> | undefined;
    const collab = rs.collaboration as Record<string, unknown> | undefined;
    const collabCfg = collab?.config as Record<string, unknown> | undefined;
    const conflict = rs.conflict_resolution as Record<string, unknown> | undefined;
    const stageSafety = rs.safety as Record<string, unknown> | undefined;
    const errH = rs.error_handling as Record<string, unknown> | undefined;
    const qg = rs.quality_gates as Record<string, unknown> | undefined;
    const conv = rs.convergence as Record<string, unknown> | undefined;
    const rawOutputs = rs.outputs as Record<string, unknown> | undefined;

    const outputs: Record<string, string> = {};
    if (rawOutputs && typeof rawOutputs === 'object') {
      for (const [k, v] of Object.entries(rawOutputs)) {
        if (typeof v === 'string') outputs[k] = v;
        else if (typeof v === 'object' && v !== null) {
          outputs[k] = (v as Record<string, unknown>).type as string ?? 'string';
        }
      }
    }

    return {
      name: (rs.name as string) ?? '',
      stage_ref: (rs.stage_ref as string | null) ?? (rs.ref as string | null) ?? (rs.stage as string | null) ?? null,
      depends_on: (rs.depends_on as string[]) ?? [],
      loops_back_to: (rs.loops_back_to as string | null) ?? (rs.loop_to as string | null) ?? null,
      max_loops: (rs.max_loops as number | null) ?? null,
      condition: (rs.condition as string | null) ?? null,
      inputs: parseStageInputs(rs),
      agents: normalizeAgentNames(rs.agents, rs.agent),
      agent_mode: (stageExec?.agent_mode as AgentMode) ?? (rs.strategy as AgentMode) ?? def.agent_mode,
      collaboration_strategy: (collab?.strategy as CollaborationStrategy) ?? (rs.strategy === 'leader' ? 'leader' as CollaborationStrategy : def.collaboration_strategy),
      timeout_seconds: (stageExec?.timeout_seconds as number) ?? def.timeout_seconds,
      collaboration_max_rounds: (collabCfg?.max_rounds as number) ?? def.collaboration_max_rounds,
      collaboration_convergence_threshold: (collabCfg?.convergence_threshold as number) ?? def.collaboration_convergence_threshold,
      collaboration_dialogue_mode: (collabCfg?.dialogue_mode as boolean) ?? def.collaboration_dialogue_mode,
      collaboration_roles: (collabCfg?.roles as Record<string, string>) ?? def.collaboration_roles,
      collaboration_round_budget_usd: (collabCfg?.round_budget_usd as number | null) ?? def.collaboration_round_budget_usd,
      collaboration_max_dialogue_rounds: (collabCfg?.max_dialogue_rounds as number) ?? def.collaboration_max_dialogue_rounds,
      collaboration_context_window_rounds: (collabCfg?.context_window_rounds as number) ?? def.collaboration_context_window_rounds,
      conflict_strategy: (conflict?.strategy as string) ?? def.conflict_strategy,
      conflict_metrics: (conflict?.metrics as string[]) ?? def.conflict_metrics,
      conflict_metric_weights: (conflict?.metric_weights as Record<string, string>) ?? def.conflict_metric_weights,
      conflict_auto_resolve_threshold: (conflict?.auto_resolve_threshold as number) ?? def.conflict_auto_resolve_threshold,
      conflict_escalation_threshold: (conflict?.escalation_threshold as number) ?? def.conflict_escalation_threshold,
      safety_mode: (stageSafety?.mode as string) ?? def.safety_mode,
      safety_dry_run_first: (stageSafety?.dry_run_first as boolean) ?? def.safety_dry_run_first,
      safety_require_approval: (stageSafety?.require_approval as boolean) ?? def.safety_require_approval,
      error_on_agent_failure: (errH?.on_agent_failure as string) ?? def.error_on_agent_failure,
      error_min_successful_agents: (errH?.min_successful_agents as number) ?? def.error_min_successful_agents,
      error_retry_failed_agents: (errH?.retry_failed_agents as boolean) ?? def.error_retry_failed_agents,
      error_max_agent_retries: (errH?.max_agent_retries as number) ?? def.error_max_agent_retries,
      quality_gates_enabled: (qg?.enabled as boolean) ?? def.quality_gates_enabled,
      quality_gates_min_confidence: (qg?.min_confidence as number) ?? def.quality_gates_min_confidence,
      quality_gates_min_findings: (qg?.min_findings as number) ?? def.quality_gates_min_findings,
      quality_gates_require_citations: (qg?.require_citations as boolean) ?? def.quality_gates_require_citations,
      quality_gates_on_failure: (qg?.on_failure as string) ?? def.quality_gates_on_failure,
      quality_gates_max_retries: (qg?.max_retries as number) ?? def.quality_gates_max_retries,
      convergence_enabled: (conv?.enabled as boolean) ?? def.convergence_enabled,
      convergence_max_iterations: (conv?.max_iterations as number) ?? def.convergence_max_iterations,
      convergence_similarity_threshold: (conv?.similarity_threshold as number) ?? def.convergence_similarity_threshold,
      convergence_method: (conv?.method as string) ?? def.convergence_method,
      description: (rs.description as string) ?? def.description,
      version: (rs.version as string) ?? def.version,
      outputs,
    };
  });
}

/** Serialize a stage to a workflow config entry (only non-default fields). */
function serializeStage(s: DesignStage): Record<string, unknown> {
  const def = defaultDesignStage();
  const entry: Record<string, unknown> = { name: s.name };

  // v1 format: single-agent = {type: "agent", agent: "name"},
  // multi-agent = {type: "stage", strategy: "parallel", agents: [...]}
  const isSingleAgent = !s.stage_ref && s.agents.length === 1;
  const isMultiAgent = !s.stage_ref && s.agents.length > 1;

  if (isSingleAgent) {
    entry.type = 'agent';
    entry.agent = s.agents[0];
  } else if (isMultiAgent) {
    entry.type = 'stage';
    // v1 uses top-level strategy field (parallel/sequential/leader)
    const strategy = s.collaboration_strategy !== 'independent'
      ? s.collaboration_strategy  // leader, consensus, etc.
      : s.agent_mode;            // parallel, sequential
    entry.strategy = strategy;
    entry.agents = s.agents.map((a) => ({ agent: a }));
  }

  if (s.stage_ref) entry.ref = s.stage_ref;
  if (s.depends_on.length > 0) entry.depends_on = s.depends_on;
  if (s.loops_back_to) entry.loop_to = s.loops_back_to;
  if (s.max_loops != null && s.max_loops > 1) entry.max_loops = s.max_loops;
  if (s.condition) entry.condition = s.condition;
  // Write input_map, but skip auto-generated entries (dep_output → dep.output)
  // that were synthesized from depends_on for Studio display only.
  const deps = new Set(s.depends_on);
  const manualInputs: Record<string, string> = {};
  for (const [k, v] of Object.entries(s.inputs)) {
    const isAutoGenerated = deps.has(k.replace(/_output$/, '')) && v.source === `${k.replace(/_output$/, '')}.output`;
    if (!isAutoGenerated) {
      manualInputs[k] = v.source;
    }
  }
  if (Object.keys(manualInputs).length > 0) {
    entry.input_map = manualInputs;
  }
  if (s.description) entry.description = s.description;
  if (s.version !== def.version) entry.version = s.version;
  if (s.outputs && Object.keys(s.outputs).length > 0) entry.outputs = s.outputs;

  const conflictObj: Record<string, unknown> = {};
  if (s.conflict_strategy) conflictObj.strategy = s.conflict_strategy;
  const metricsChanged = s.conflict_metrics.length !== def.conflict_metrics.length ||
    s.conflict_metrics.some((v, i) => v !== def.conflict_metrics[i]);
  if (metricsChanged) conflictObj.metrics = s.conflict_metrics;
  if (Object.keys(s.conflict_metric_weights).length > 0) conflictObj.metric_weights = s.conflict_metric_weights;
  if (s.conflict_auto_resolve_threshold !== def.conflict_auto_resolve_threshold) conflictObj.auto_resolve_threshold = s.conflict_auto_resolve_threshold;
  if (s.conflict_escalation_threshold !== def.conflict_escalation_threshold) conflictObj.escalation_threshold = s.conflict_escalation_threshold;
  if (Object.keys(conflictObj).length > 0) entry.conflict_resolution = conflictObj;

  const safetyObj: Record<string, unknown> = {};
  if (s.safety_mode !== def.safety_mode) safetyObj.mode = s.safety_mode;
  if (s.safety_dry_run_first !== def.safety_dry_run_first) safetyObj.dry_run_first = s.safety_dry_run_first;
  if (s.safety_require_approval !== def.safety_require_approval) safetyObj.require_approval = s.safety_require_approval;
  if (Object.keys(safetyObj).length > 0) entry.safety = safetyObj;

  const errObj: Record<string, unknown> = {};
  if (s.error_on_agent_failure !== def.error_on_agent_failure) errObj.on_agent_failure = s.error_on_agent_failure;
  if (s.error_min_successful_agents !== def.error_min_successful_agents) errObj.min_successful_agents = s.error_min_successful_agents;
  if (s.error_retry_failed_agents !== def.error_retry_failed_agents) errObj.retry_failed_agents = s.error_retry_failed_agents;
  if (s.error_max_agent_retries !== def.error_max_agent_retries) errObj.max_agent_retries = s.error_max_agent_retries;
  if (Object.keys(errObj).length > 0) entry.error_handling = errObj;

  const qgObj: Record<string, unknown> = {};
  if (s.quality_gates_enabled !== def.quality_gates_enabled) qgObj.enabled = s.quality_gates_enabled;
  if (s.quality_gates_min_confidence !== def.quality_gates_min_confidence) qgObj.min_confidence = s.quality_gates_min_confidence;
  if (s.quality_gates_min_findings !== def.quality_gates_min_findings) qgObj.min_findings = s.quality_gates_min_findings;
  if (s.quality_gates_require_citations !== def.quality_gates_require_citations) qgObj.require_citations = s.quality_gates_require_citations;
  if (s.quality_gates_on_failure !== def.quality_gates_on_failure) qgObj.on_failure = s.quality_gates_on_failure;
  if (s.quality_gates_max_retries !== def.quality_gates_max_retries) qgObj.max_retries = s.quality_gates_max_retries;
  if (Object.keys(qgObj).length > 0) entry.quality_gates = qgObj;

  const convObj: Record<string, unknown> = {};
  if (s.convergence_enabled !== def.convergence_enabled) convObj.enabled = s.convergence_enabled;
  if (s.convergence_max_iterations !== def.convergence_max_iterations) convObj.max_iterations = s.convergence_max_iterations;
  if (s.convergence_similarity_threshold !== def.convergence_similarity_threshold) convObj.similarity_threshold = s.convergence_similarity_threshold;
  if (s.convergence_method !== def.convergence_method) convObj.method = s.convergence_method;
  if (Object.keys(convObj).length > 0) entry.convergence = convObj;

  return entry;
}

/** Serialize the complete workflow meta + stages into a workflow config object. */
export function serializeWorkflowConfig(meta: WorkflowMeta, stages: DesignStage[]): Record<string, unknown> {
  const defaults = defaultMeta();
  // Build in display order: name, description, defaults, nodes, then config sections
  const wfConfig: Record<string, unknown> = { name: meta.name };

  wfConfig.description = meta.description || '';
  if (meta.version !== defaults.version) wfConfig.version = meta.version;
  if (meta.product_type != null) wfConfig.product_type = meta.product_type;

  // Defaults — provider/model inherited by all agents (before nodes for readability)
  if (meta.default_provider || meta.default_model) {
    const dfObj: Record<string, string> = {};
    if (meta.default_provider) dfObj.provider = meta.default_provider;
    if (meta.default_model) dfObj.model = meta.default_model;
    wfConfig.defaults = dfObj;
  }

  // Nodes come after defaults
  wfConfig.nodes = stages.map(serializeStage);
  if (meta.predecessor_injection !== defaults.predecessor_injection)
    wfConfig.predecessor_injection = meta.predecessor_injection;

  const budgetObj: Record<string, unknown> = {};
  if (meta.max_cost_usd != null) budgetObj.max_cost_usd = meta.max_cost_usd;
  if (meta.max_tokens != null) budgetObj.max_tokens = meta.max_tokens;
  if (meta.budget_action_on_exceed !== defaults.budget_action_on_exceed)
    budgetObj.action_on_exceed = meta.budget_action_on_exceed;

  const rateLimitObj: Record<string, unknown> = {};
  if (meta.rate_limit_enabled !== defaults.rate_limit_enabled) rateLimitObj.enabled = meta.rate_limit_enabled;
  if (meta.rate_limit_max_rpm !== defaults.rate_limit_max_rpm) rateLimitObj.max_rpm = meta.rate_limit_max_rpm;
  if (meta.rate_limit_block_on_limit !== defaults.rate_limit_block_on_limit) rateLimitObj.block_on_limit = meta.rate_limit_block_on_limit;
  if (meta.rate_limit_max_wait_seconds !== defaults.rate_limit_max_wait_seconds) rateLimitObj.max_wait_seconds = meta.rate_limit_max_wait_seconds;

  const planningObj: Record<string, unknown> = {};
  if (meta.planning_enabled !== defaults.planning_enabled) planningObj.enabled = meta.planning_enabled;
  if (meta.planning_provider !== defaults.planning_provider) planningObj.provider = meta.planning_provider;
  if (meta.planning_model !== defaults.planning_model) planningObj.model = meta.planning_model;
  if (meta.planning_temperature !== defaults.planning_temperature) planningObj.temperature = meta.planning_temperature;
  if (meta.planning_max_tokens !== defaults.planning_max_tokens) planningObj.max_tokens = meta.planning_max_tokens;

  const cfgObj: Record<string, unknown> = {};
  if (meta.timeout_seconds !== defaults.timeout_seconds) cfgObj.timeout_seconds = meta.timeout_seconds;
  if (meta.max_iterations !== defaults.max_iterations) cfgObj.max_iterations = meta.max_iterations;
  if (meta.convergence_detection !== defaults.convergence_detection) cfgObj.convergence_detection = meta.convergence_detection;
  if (meta.tool_cache_enabled !== defaults.tool_cache_enabled) cfgObj.tool_cache_enabled = meta.tool_cache_enabled;
  if (Object.keys(budgetObj).length > 0) cfgObj.budget = budgetObj;
  if (Object.keys(rateLimitObj).length > 0) cfgObj.rate_limit = rateLimitObj;
  if (Object.keys(planningObj).length > 0) cfgObj.planning = planningObj;
  if (Object.keys(cfgObj).length > 0) wfConfig.config = cfgObj;

  const errObj: Record<string, unknown> = {
    on_stage_failure: meta.on_stage_failure,
    max_stage_retries: meta.max_stage_retries,
    escalation_policy: meta.escalation_policy,
    enable_rollback: meta.enable_rollback,
  };
  wfConfig.error_handling = errObj;

  const safetyObj: Record<string, unknown> = {};
  if (meta.global_safety_mode !== defaults.global_safety_mode) safetyObj.global_mode = meta.global_safety_mode;
  if (meta.safety_composition_strategy !== defaults.safety_composition_strategy) safetyObj.composition_strategy = meta.safety_composition_strategy;
  if (meta.approval_required_stages.length > 0) safetyObj.approval_required_stages = meta.approval_required_stages;
  if (meta.dry_run_stages.length > 0) safetyObj.dry_run_stages = meta.dry_run_stages;
  if (Object.keys(safetyObj).length > 0) wfConfig.safety = safetyObj;

  const obsObj: Record<string, unknown> = {};
  if (meta.observability_console_mode !== defaults.observability_console_mode) obsObj.console_mode = meta.observability_console_mode;
  if (meta.observability_trace_everything !== defaults.observability_trace_everything) obsObj.trace_everything = meta.observability_trace_everything;
  const fmtChanged = meta.observability_export_format.length !== defaults.observability_export_format.length ||
    meta.observability_export_format.some((v, i) => v !== defaults.observability_export_format[i]);
  if (fmtChanged) obsObj.export_format = meta.observability_export_format;
  if (meta.observability_dag_visualization !== defaults.observability_dag_visualization) obsObj.generate_dag_visualization = meta.observability_dag_visualization;
  if (meta.observability_waterfall !== defaults.observability_waterfall) obsObj.waterfall_in_console = meta.observability_waterfall;
  if (Object.keys(obsObj).length > 0) wfConfig.observability = obsObj;

  const autoObj: Record<string, unknown> = {};
  if (meta.autonomous_enabled !== defaults.autonomous_enabled) autoObj.enabled = meta.autonomous_enabled;
  if (meta.autonomous_learning !== defaults.autonomous_learning) autoObj.learning_enabled = meta.autonomous_learning;
  if (meta.autonomous_goals !== defaults.autonomous_goals) autoObj.goals_enabled = meta.autonomous_goals;
  if (meta.autonomous_portfolio !== defaults.autonomous_portfolio) autoObj.portfolio_enabled = meta.autonomous_portfolio;
  if (meta.autonomous_auto_apply_learning !== defaults.autonomous_auto_apply_learning) autoObj.auto_apply_learning = meta.autonomous_auto_apply_learning;
  if (meta.autonomous_auto_apply_goals !== defaults.autonomous_auto_apply_goals) autoObj.auto_apply_goals = meta.autonomous_auto_apply_goals;
  if (meta.autonomous_prompt_optimization !== defaults.autonomous_prompt_optimization) autoObj.prompt_optimization_enabled = meta.autonomous_prompt_optimization;
  if (meta.autonomous_agent_memory_sync !== defaults.autonomous_agent_memory_sync) autoObj.agent_memory_sync_enabled = meta.autonomous_agent_memory_sync;
  if (Object.keys(autoObj).length > 0) wfConfig.autonomous_loop = autoObj;

  const lcObj: Record<string, unknown> = {};
  if (meta.lifecycle_enabled !== defaults.lifecycle_enabled) lcObj.enabled = meta.lifecycle_enabled;
  if (meta.lifecycle_profile != null) lcObj.profile = meta.lifecycle_profile;
  if (meta.lifecycle_auto_classify !== defaults.lifecycle_auto_classify) lcObj.auto_classify = meta.lifecycle_auto_classify;
  if (Object.keys(lcObj).length > 0) wfConfig.lifecycle = lcObj;

  const metaObj: Record<string, unknown> = {};
  if (meta.tags.length > 0) metaObj.tags = meta.tags;
  if (meta.owner != null) metaObj.owner = meta.owner;
  if (Object.keys(metaObj).length > 0) wfConfig.metadata = metaObj;

  if (meta.required_inputs.length > 0 || meta.optional_inputs.length > 0) {
    const inputsObj: Record<string, unknown> = {};
    if (meta.required_inputs.length > 0) inputsObj.required = meta.required_inputs;
    if (meta.optional_inputs.length > 0) inputsObj.optional = meta.optional_inputs;
    wfConfig.inputs = inputsObj;
  }
  if (meta.outputs.length > 0) {
    wfConfig.outputs = meta.outputs.map((o) => {
      const entry: Record<string, string> = { name: o.name };
      if (o.description) entry.description = o.description;
      if (o.source) entry.source = o.source;
      return entry;
    });
  }

  return { workflow: wfConfig };
}
