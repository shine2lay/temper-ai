/**
 * Shared helpers, option lists, and default reference for AgentPropertiesPanel tabs.
 */
import type { AgentFormState } from '@/hooks/useAgentEditor';

export function makeDefaults(): AgentFormState {
  return {
    name: '',
    description: '',
    version: '1.0',
    type: 'standard',
    prompt: { mode: 'inline', inline: '', template: '', variables: {} },
    inference: {
      provider: '', model: '', base_url: '', api_key_ref: '',
      temperature: 0.7, max_tokens: 4096, top_p: 1, timeout_seconds: 600,
      max_retries: 3, retry_delay_seconds: 2,
    },
    tools: { mode: 'auto', entries: [] },
    safety: {
      mode: 'execute', risk_level: 'low',
      max_tool_calls_per_execution: 10, max_execution_time_seconds: 600,
      require_approval_for_tools: [], max_prompt_length: 100000, max_tool_result_size: 65536,
    },
    memory: {
      enabled: false, type: '', scope: '', provider: '',
      namespace: '', tenant_id: '', retrieval_k: 10, relevance_threshold: 0.8,
      embedding_model: '', max_episodes: 100, decay_factor: 0.99,
      auto_extract_procedural: false, shared_namespace: '',
    },
    error_handling: {
      retry_strategy: 'ExponentialBackoff', max_retries: 2, fallback: 'GracefulDegradation',
      escalate_to_human_after: 2, retry_initial_delay: 1, retry_max_delay: 30,
      retry_exponential_base: 2.0,
    },
    reasoning: {
      enabled: false, planning_prompt: '', inject_as: 'system',
      max_planning_tokens: 1024, temperature: null,
    },
    observability: {
      log_inputs: true, log_outputs: true, log_reasoning: false,
      track_latency: true, track_token_usage: true, log_full_llm_responses: false,
    },
    context_management: {
      enabled: false, strategy: 'truncate', max_context_tokens: null,
      reserved_output_tokens: 2048, token_counter: 'approximate',
    },
    output_schema: { json_schema: '', enforce_mode: 'validate_only', max_retries: 2, strict: false },
    output_guardrails: { enabled: false, checks: [], max_retries: 2, inject_feedback: true },
    pre_commands: [],
    merit: { enabled: true, track_outcomes: true, domain_expertise: [], decay_enabled: true, half_life_days: 90 },
    persistent: { persistent: false, agent_id: '' },
    dialogue: { dialogue_aware: true, max_dialogue_context_chars: 16384 },
    metadata: { tags: [], owner: '', created: '', last_modified: '', documentation_url: '' },
  };
}

export const AGENT_DEFAULTS = makeDefaults();

/** Check if a nested field differs from default. */
export function isNonDefault(config: AgentFormState, section: string, key: string): boolean {
  const sec = (AGENT_DEFAULTS as unknown as Record<string, unknown>)[section];
  const cur = (config as unknown as Record<string, unknown>)[section];
  if (typeof sec !== 'object' || sec === null || typeof cur !== 'object' || cur === null) return false;
  return (cur as Record<string, unknown>)[key] !== (sec as Record<string, unknown>)[key];
}

export function accent(config: AgentFormState, section: string, key: string): string {
  return isNonDefault(config, section, key) ? 'text-temper-accent' : '';
}

/* ---------- Option lists ---------- */

export const typeOptions = [
  { value: 'standard', label: 'standard' },
  { value: 'llm', label: 'llm' },
  { value: 'script', label: 'script' },
  { value: 'script_v2', label: 'script_v2' },
  { value: 'static_checker', label: 'static_checker' },
  { value: 'router', label: 'router' },
  { value: 'critic', label: 'critic' },
  { value: 'orchestrator', label: 'orchestrator' },
];

export const safetyModeOptions = [
  { value: 'execute', label: 'execute' },
  { value: 'monitor', label: 'monitor' },
  { value: 'audit', label: 'audit' },
];

export const riskOptions = [
  { value: 'low', label: 'low' },
  { value: 'medium', label: 'medium' },
  { value: 'high', label: 'high' },
];

export const retryStrategyOptions = [
  { value: 'ExponentialBackoff', label: 'exponential' },
  { value: 'LinearBackoff', label: 'linear' },
  { value: 'FixedDelay', label: 'fixed' },
  { value: 'NoRetry', label: 'none' },
];

export const fallbackOptions = [
  { value: 'GracefulDegradation', label: 'graceful' },
  { value: 'HardFail', label: 'hard fail' },
  { value: 'DefaultResponse', label: 'default resp' },
];

export const injectAsOptions = [
  { value: 'system', label: 'system' },
  { value: 'user', label: 'user' },
  { value: 'prefix', label: 'prefix' },
];

export const ctxStrategyOptions = [
  { value: 'truncate', label: 'truncate' },
  { value: 'summarize', label: 'summarize' },
  { value: 'sliding_window', label: 'sliding window' },
];

export const tokenCounterOptions = [
  { value: 'approximate', label: 'approximate' },
  { value: 'tiktoken', label: 'tiktoken' },
];

export const enforceModeOptions = [
  { value: 'validate_only', label: 'validate only' },
  { value: 'strict', label: 'strict' },
  { value: 'coerce', label: 'coerce' },
];

export const toolModeOptions = [
  { value: 'auto', label: 'auto-discover' },
  { value: 'none', label: 'no tools' },
  { value: 'explicit', label: 'explicit' },
];
