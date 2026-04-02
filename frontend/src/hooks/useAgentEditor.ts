/**
 * Custom hook encapsulating the agent editing lifecycle.
 * Fetches an agent config from the Studio API, normalizes it into form state,
 * and provides save/validate mutations.
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { useValidateAgent, useSaveAgentDB } from './useStudioAPI';
import { useConfig } from './useConfigAPI';

/* ---------- Form state types ---------- */

/** Type-safe updater for AgentFormState fields. */
export type AgentFieldUpdater = <K extends keyof AgentFormState>(section: K, value: AgentFormState[K]) => void;

export interface ToolEntry {
  name: string;
  config: string;
}

export interface AgentFormState {
  name: string;
  description: string;
  version: string;
  type: string;
  prompt: {
    mode: 'inline' | 'template';
    inline: string;
    template: string;
    variables: Record<string, string>;
  };
  inference: {
    provider: string;
    model: string;
    base_url: string;
    api_key_ref: string;
    temperature: number;
    max_tokens: number;
    top_p: number;
    timeout_seconds: number;
    max_retries: number;
    retry_delay_seconds: number;
  };
  tools: {
    mode: 'auto' | 'none' | 'explicit';
    entries: ToolEntry[];
  };
  safety: {
    mode: string;
    risk_level: string;
    max_tool_calls_per_execution: number;
    max_execution_time_seconds: number;
    require_approval_for_tools: string[];
    max_prompt_length: number;
    max_tool_result_size: number;
  };
  memory: {
    enabled: boolean;
    type: string;
    scope: string;
    provider: string;
    namespace: string;
    tenant_id: string;
    retrieval_k: number;
    relevance_threshold: number;
    embedding_model: string;
    max_episodes: number;
    decay_factor: number;
    auto_extract_procedural: boolean;
    shared_namespace: string;
  };
  error_handling: {
    retry_strategy: string;
    max_retries: number;
    fallback: string;
    escalate_to_human_after: number;
    retry_initial_delay: number;
    retry_max_delay: number;
    retry_exponential_base: number;
  };
  reasoning: {
    enabled: boolean;
    planning_prompt: string;
    inject_as: string;
    max_planning_tokens: number;
    temperature: number | null;
  };
  observability: {
    log_inputs: boolean;
    log_outputs: boolean;
    log_reasoning: boolean;
    track_latency: boolean;
    track_token_usage: boolean;
    log_full_llm_responses: boolean;
  };
  context_management: {
    enabled: boolean;
    strategy: string;
    max_context_tokens: number | null;
    reserved_output_tokens: number;
    token_counter: string;
  };
  output_schema: {
    json_schema: string;
    enforce_mode: string;
    max_retries: number;
    strict: boolean;
  };
  output_guardrails: {
    enabled: boolean;
    checks: string[];
    max_retries: number;
    inject_feedback: boolean;
  };
  pre_commands: {
    name: string;
    command: string;
    timeout_seconds: number;
  }[];
  merit: {
    enabled: boolean;
    track_outcomes: boolean;
    domain_expertise: string[];
    decay_enabled: boolean;
    half_life_days: number;
  };
  persistent: {
    persistent: boolean;
    agent_id: string;
  };
  dialogue: {
    dialogue_aware: boolean;
    max_dialogue_context_chars: number;
  };
  metadata: {
    tags: string[];
    owner: string;
    created: string;
    last_modified: string;
    documentation_url: string;
  };
}

/* ---------- Defaults ---------- */

const DEFAULT_TEMPERATURE = 0.7;
const DEFAULT_MAX_TOKENS = 4096;
const DEFAULT_TOP_P = 1;
const DEFAULT_TIMEOUT = 600;
const DEFAULT_MAX_RETRIES = 2;
const DEFAULT_MAX_TOOL_CALLS = 10;
const DEFAULT_MAX_EXEC_TIME = 600;
const DEFAULT_MAX_PLANNING_TOKENS = 1024;
const DEFAULT_INFERENCE_MAX_RETRIES = 3;
const DEFAULT_INFERENCE_RETRY_DELAY = 2;
const DEFAULT_MAX_PROMPT_LENGTH = 100000;
const DEFAULT_MAX_TOOL_RESULT_SIZE = 65536;
const DEFAULT_RETRIEVAL_K = 10;
const DEFAULT_RELEVANCE_THRESHOLD = 0.8;
const DEFAULT_MAX_EPISODES = 100;
const DEFAULT_DECAY_FACTOR = 0.99;
const DEFAULT_ESCALATE_AFTER = 2;
const DEFAULT_RETRY_INITIAL_DELAY = 1;
const DEFAULT_RETRY_MAX_DELAY = 30;
const DEFAULT_RETRY_EXP_BASE = 2.0;
const DEFAULT_RESERVED_OUTPUT_TOKENS = 2048;
const DEFAULT_OUTPUT_SCHEMA_RETRIES = 2;
const DEFAULT_GUARDRAIL_RETRIES = 2;
const DEFAULT_HALF_LIFE_DAYS = 90;
const DEFAULT_MAX_DIALOGUE_CHARS = 16384;

function defaultFormState(): AgentFormState {
  return {
    name: '',
    description: '',
    version: '1.0',
    type: 'standard',
    prompt: { mode: 'inline', inline: '', template: '', taskTemplate: '', variables: {} },
    inference: {
      provider: '',
      model: '',
      base_url: '',
      api_key_ref: '',
      temperature: DEFAULT_TEMPERATURE,
      max_tokens: DEFAULT_MAX_TOKENS,
      top_p: DEFAULT_TOP_P,
      timeout_seconds: DEFAULT_TIMEOUT,
      max_retries: DEFAULT_INFERENCE_MAX_RETRIES,
      retry_delay_seconds: DEFAULT_INFERENCE_RETRY_DELAY,
    },
    tools: { mode: 'auto', entries: [] },
    safety: {
      mode: 'execute',
      risk_level: 'low',
      max_tool_calls_per_execution: DEFAULT_MAX_TOOL_CALLS,
      max_execution_time_seconds: DEFAULT_MAX_EXEC_TIME,
      require_approval_for_tools: [],
      max_prompt_length: DEFAULT_MAX_PROMPT_LENGTH,
      max_tool_result_size: DEFAULT_MAX_TOOL_RESULT_SIZE,
    },
    memory: {
      enabled: false,
      type: '',
      scope: '',
      provider: '',
      namespace: '',
      tenant_id: '',
      retrieval_k: DEFAULT_RETRIEVAL_K,
      relevance_threshold: DEFAULT_RELEVANCE_THRESHOLD,
      embedding_model: '',
      max_episodes: DEFAULT_MAX_EPISODES,
      decay_factor: DEFAULT_DECAY_FACTOR,
      auto_extract_procedural: false,
      shared_namespace: '',
    },
    error_handling: {
      retry_strategy: 'ExponentialBackoff',
      max_retries: DEFAULT_MAX_RETRIES,
      fallback: 'GracefulDegradation',
      escalate_to_human_after: DEFAULT_ESCALATE_AFTER,
      retry_initial_delay: DEFAULT_RETRY_INITIAL_DELAY,
      retry_max_delay: DEFAULT_RETRY_MAX_DELAY,
      retry_exponential_base: DEFAULT_RETRY_EXP_BASE,
    },
    reasoning: {
      enabled: false,
      planning_prompt: '',
      inject_as: 'system',
      max_planning_tokens: DEFAULT_MAX_PLANNING_TOKENS,
      temperature: null,
    },
    observability: {
      log_inputs: true,
      log_outputs: true,
      log_reasoning: false,
      track_latency: true,
      track_token_usage: true,
      log_full_llm_responses: false,
    },
    context_management: {
      enabled: false,
      strategy: 'truncate',
      max_context_tokens: null,
      reserved_output_tokens: DEFAULT_RESERVED_OUTPUT_TOKENS,
      token_counter: 'approximate',
    },
    output_schema: {
      json_schema: '',
      enforce_mode: 'validate_only',
      max_retries: DEFAULT_OUTPUT_SCHEMA_RETRIES,
      strict: false,
    },
    output_guardrails: {
      enabled: false,
      checks: [],
      max_retries: DEFAULT_GUARDRAIL_RETRIES,
      inject_feedback: true,
    },
    pre_commands: [],
    merit: {
      enabled: true,
      track_outcomes: true,
      domain_expertise: [],
      decay_enabled: true,
      half_life_days: DEFAULT_HALF_LIFE_DAYS,
    },
    persistent: {
      persistent: false,
      agent_id: '',
    },
    dialogue: {
      dialogue_aware: true,
      max_dialogue_context_chars: DEFAULT_MAX_DIALOGUE_CHARS,
    },
    metadata: {
      tags: [],
      owner: '',
      created: '',
      last_modified: '',
      documentation_url: '',
    },
  };
}

/* ---------- Parsing & serialization ---------- */

type AnyRecord = Record<string, unknown>;

/** Parse server agent config into form state. */
function parseConfig(data: AnyRecord): AgentFormState {
  const agent = (data.agent ?? data) as AnyRecord;
  const prompt = agent.prompt as AnyRecord | undefined;
  const inference = agent.inference as AnyRecord | undefined;
  const rawTools = agent.tools;
  const safety = agent.safety as AnyRecord | undefined;
  const memory = agent.memory as AnyRecord | undefined;
  const errorHandling = agent.error_handling as AnyRecord | undefined;
  const reasoning = agent.reasoning as AnyRecord | undefined;
  const observability = agent.observability as AnyRecord | undefined;
  const contextMgmt = agent.context_management as AnyRecord | undefined;
  const outputSchemaObj = agent.output_schema as AnyRecord | undefined;
  const guardrails = agent.output_guardrails as AnyRecord | undefined;
  const preCommands = agent.pre_commands as unknown[] | undefined;
  const meritObj = agent.merit as AnyRecord | undefined;
  const dialogueObj = agent.dialogue as AnyRecord | undefined;
  const metadataObj = agent.metadata as AnyRecord | undefined;

  // Read top-level prompt fields (backend format) as fallback for nested format
  const topLevelSystemPrompt = agent.system_prompt as string | undefined;
  const topLevelTaskTemplate = agent.task_template as string | undefined;
  const topLevelProvider = agent.provider as string | undefined;
  const topLevelModel = agent.model as string | undefined;
  const topLevelTemperature = agent.temperature as number | undefined;
  const topLevelMaxTokens = agent.max_tokens as number | undefined;

  // Determine prompt mode
  const hasInline = typeof prompt?.inline === 'string' && prompt.inline !== '';
  const hasTemplate = typeof prompt?.template === 'string' && prompt.template !== '';
  const hasTopLevelPrompt = !!topLevelSystemPrompt;

  // Determine tools mode
  let toolsMode: 'auto' | 'none' | 'explicit' = 'auto';
  let toolEntries: ToolEntry[] = [];
  if (rawTools === null || rawTools === undefined) {
    toolsMode = 'auto';
  } else if (Array.isArray(rawTools) && rawTools.length === 0) {
    toolsMode = 'none';
  } else if (Array.isArray(rawTools)) {
    toolsMode = 'explicit';
    toolEntries = rawTools.map((t: unknown) => {
      const tool = t as AnyRecord;
      return {
        name: (tool.name as string) ?? '',
        config: tool.config ? JSON.stringify(tool.config, null, 2) : '',
      };
    });
  }

  // Parse prompt variables
  const rawVars = prompt?.variables as AnyRecord | undefined;
  const variables: Record<string, string> = {};
  if (rawVars) {
    for (const [k, v] of Object.entries(rawVars)) {
      variables[k] = String(v);
    }
  }

  return {
    name: (agent.name as string) ?? '',
    description: (agent.description as string) ?? '',
    version: (agent.version as string) ?? '1.0',
    type: (agent.type as string) ?? 'standard',
    prompt: {
      mode: hasTemplate && !hasInline && !hasTopLevelPrompt ? 'template' : 'inline',
      inline: (prompt?.inline as string) || topLevelSystemPrompt || '',
      template: (prompt?.template as string) ?? '',
      taskTemplate: topLevelTaskTemplate ?? '',
      variables,
    },
    inference: {
      provider: (inference?.provider as string) || topLevelProvider || '',
      model: (inference?.model as string) || topLevelModel || '',
      base_url: (inference?.base_url as string) ?? '',
      api_key_ref: (inference?.api_key_ref as string) ?? '',
      temperature: (inference?.temperature as number) ?? topLevelTemperature ?? DEFAULT_TEMPERATURE,
      max_tokens: (inference?.max_tokens as number) ?? topLevelMaxTokens ?? DEFAULT_MAX_TOKENS,
      top_p: (inference?.top_p as number) ?? DEFAULT_TOP_P,
      timeout_seconds: (inference?.timeout_seconds as number) ?? DEFAULT_TIMEOUT,
      max_retries: (inference?.max_retries as number) ?? DEFAULT_INFERENCE_MAX_RETRIES,
      retry_delay_seconds: (inference?.retry_delay_seconds as number) ?? DEFAULT_INFERENCE_RETRY_DELAY,
    },
    tools: { mode: toolsMode, entries: toolEntries },
    safety: {
      mode: (safety?.mode as string) ?? 'execute',
      risk_level: (safety?.risk_level as string) ?? 'low',
      max_tool_calls_per_execution:
        (safety?.max_tool_calls_per_execution as number) ?? DEFAULT_MAX_TOOL_CALLS,
      max_execution_time_seconds:
        (safety?.max_execution_time_seconds as number) ?? DEFAULT_MAX_EXEC_TIME,
      require_approval_for_tools: (safety?.require_approval_for_tools as string[]) ?? [],
      max_prompt_length: (safety?.max_prompt_length as number) ?? DEFAULT_MAX_PROMPT_LENGTH,
      max_tool_result_size: (safety?.max_tool_result_size as number) ?? DEFAULT_MAX_TOOL_RESULT_SIZE,
    },
    memory: {
      enabled: (memory?.enabled as boolean) ?? false,
      type: (memory?.type as string) ?? '',
      scope: (memory?.scope as string) ?? '',
      provider: (memory?.provider as string) ?? '',
      namespace: (memory?.namespace as string) ?? '',
      tenant_id: (memory?.tenant_id as string) ?? '',
      retrieval_k: (memory?.retrieval_k as number) ?? DEFAULT_RETRIEVAL_K,
      relevance_threshold: (memory?.relevance_threshold as number) ?? DEFAULT_RELEVANCE_THRESHOLD,
      embedding_model: (memory?.embedding_model as string) ?? '',
      max_episodes: (memory?.max_episodes as number) ?? DEFAULT_MAX_EPISODES,
      decay_factor: (memory?.decay_factor as number) ?? DEFAULT_DECAY_FACTOR,
      auto_extract_procedural: (memory?.auto_extract_procedural as boolean) ?? false,
      shared_namespace: (memory?.shared_namespace as string) ?? '',
    },
    error_handling: {
      retry_strategy: (errorHandling?.retry_strategy as string) ?? 'ExponentialBackoff',
      max_retries: (errorHandling?.max_retries as number) ?? DEFAULT_MAX_RETRIES,
      fallback: (errorHandling?.fallback as string) ?? 'GracefulDegradation',
      escalate_to_human_after: (errorHandling?.escalate_to_human_after as number) ?? DEFAULT_ESCALATE_AFTER,
      retry_initial_delay: (errorHandling?.retry_initial_delay as number) ?? DEFAULT_RETRY_INITIAL_DELAY,
      retry_max_delay: (errorHandling?.retry_max_delay as number) ?? DEFAULT_RETRY_MAX_DELAY,
      retry_exponential_base: (errorHandling?.retry_exponential_base as number) ?? DEFAULT_RETRY_EXP_BASE,
    },
    reasoning: {
      enabled: (reasoning?.enabled as boolean) ?? false,
      planning_prompt: (reasoning?.planning_prompt as string) ?? '',
      inject_as: (reasoning?.inject_as as string) ?? 'system',
      max_planning_tokens:
        (reasoning?.max_planning_tokens as number) ?? DEFAULT_MAX_PLANNING_TOKENS,
      temperature: (reasoning?.temperature as number | null) ?? null,
    },
    observability: {
      log_inputs: (observability?.log_inputs as boolean) ?? true,
      log_outputs: (observability?.log_outputs as boolean) ?? true,
      log_reasoning: (observability?.log_reasoning as boolean) ?? false,
      track_latency: (observability?.track_latency as boolean) ?? true,
      track_token_usage: (observability?.track_token_usage as boolean) ?? true,
      log_full_llm_responses: (observability?.log_full_llm_responses as boolean) ?? false,
    },
    context_management: {
      enabled: (contextMgmt?.enabled as boolean) ?? false,
      strategy: (contextMgmt?.strategy as string) ?? 'truncate',
      max_context_tokens: (contextMgmt?.max_context_tokens as number | null) ?? null,
      reserved_output_tokens: (contextMgmt?.reserved_output_tokens as number) ?? DEFAULT_RESERVED_OUTPUT_TOKENS,
      token_counter: (contextMgmt?.token_counter as string) ?? 'approximate',
    },
    output_schema: {
      json_schema: outputSchemaObj?.json_schema
        ? (typeof outputSchemaObj.json_schema === 'string'
            ? outputSchemaObj.json_schema
            : JSON.stringify(outputSchemaObj.json_schema, null, 2))
        : '',
      enforce_mode: (outputSchemaObj?.enforce_mode as string) ?? 'validate_only',
      max_retries: (outputSchemaObj?.max_retries as number) ?? DEFAULT_OUTPUT_SCHEMA_RETRIES,
      strict: (outputSchemaObj?.strict as boolean) ?? false,
    },
    output_guardrails: {
      enabled: (guardrails?.enabled as boolean) ?? false,
      checks: (guardrails?.checks as string[]) ?? [],
      max_retries: (guardrails?.max_retries as number) ?? DEFAULT_GUARDRAIL_RETRIES,
      inject_feedback: (guardrails?.inject_feedback as boolean) ?? true,
    },
    pre_commands: Array.isArray(preCommands)
      ? preCommands.map((pc) => {
          const cmd = pc as AnyRecord;
          return {
            name: (cmd.name as string) ?? '',
            command: (cmd.command as string) ?? '',
            timeout_seconds: (cmd.timeout_seconds as number) ?? 30,
          };
        })
      : [],
    merit: {
      enabled: (meritObj?.enabled as boolean) ?? true,
      track_outcomes: (meritObj?.track_outcomes as boolean) ?? true,
      domain_expertise: (meritObj?.domain_expertise as string[]) ?? [],
      decay_enabled: (meritObj?.decay_enabled as boolean) ?? true,
      half_life_days: (meritObj?.half_life_days as number) ?? DEFAULT_HALF_LIFE_DAYS,
    },
    persistent: {
      persistent: (agent.persistent as boolean) ?? false,
      agent_id: (agent.agent_id as string) ?? '',
    },
    dialogue: {
      dialogue_aware: (dialogueObj?.dialogue_aware as boolean) ?? true,
      max_dialogue_context_chars: (dialogueObj?.max_dialogue_context_chars as number) ?? DEFAULT_MAX_DIALOGUE_CHARS,
    },
    metadata: {
      tags: (metadataObj?.tags as string[]) ?? [],
      owner: (metadataObj?.owner as string) ?? '',
      created: (metadataObj?.created as string) ?? '',
      last_modified: (metadataObj?.last_modified as string) ?? '',
      documentation_url: (metadataObj?.documentation_url as string) ?? '',
    },
  };
}

/** Convert form state back to the server agent config envelope. */
function toAgentConfig(form: AgentFormState): AnyRecord {
  const agent: AnyRecord = {
    name: form.name,
    description: form.description,
    version: form.version,
    type: form.type,
  };

  // Prompt — backend reads system_prompt and task_template at the TOP LEVEL,
  // not nested under prompt.inline. Write both for compat.
  if (form.prompt.mode === 'inline' && form.prompt.inline) {
    // Split on first blank line or treat entire text as system_prompt
    const text = form.prompt.inline;
    agent.system_prompt = text;
    agent.task_template = form.prompt.taskTemplate ?? '{{ task }}';
  } else if (form.prompt.template) {
    agent.prompt = { template: form.prompt.template };
  }
  // Also write nested prompt for forward-compat with future backends
  const promptObj: AnyRecord = {};
  if (form.prompt.mode === 'inline') {
    promptObj.inline = form.prompt.inline;
  } else {
    promptObj.template = form.prompt.template;
  }
  if (Object.keys(form.prompt.variables).length > 0) {
    promptObj.variables = form.prompt.variables;
  }
  agent.prompt = promptObj;

  // Inference — backend reads provider, model, temperature, max_tokens at TOP LEVEL.
  // Write both top-level and nested for compatibility.
  if (form.inference.provider) agent.provider = form.inference.provider;
  if (form.inference.model) agent.model = form.inference.model;
  if (form.inference.temperature != null) agent.temperature = form.inference.temperature;
  if (form.inference.max_tokens != null) agent.max_tokens = form.inference.max_tokens;

  // Also write nested inference for forward-compat
  const inf: AnyRecord = {};
  if (form.inference.provider) inf.provider = form.inference.provider;
  if (form.inference.model) inf.model = form.inference.model;
  inf.temperature = form.inference.temperature;
  inf.max_tokens = form.inference.max_tokens;
  agent.inference = inf;

  // Tools
  if (form.tools.mode === 'none') {
    agent.tools = [];
  } else if (form.tools.mode === 'explicit') {
    agent.tools = form.tools.entries.map((e) => {
      const entry: AnyRecord = { name: e.name };
      if (e.config.trim()) {
        try {
          entry.config = JSON.parse(e.config);
        } catch {
          entry.config = {};
        }
      }
      return entry;
    });
  }
  // mode === 'auto' → omit tools key entirely

  // Safety — agent-level safety is phantom (safety is workflow-level only).
  // Only write if non-default for forward-compatibility.
  if (form.safety.mode !== 'standard') {
    agent.safety = { mode: form.safety.mode };
  }

  // Memory
  agent.memory = { enabled: form.memory.enabled };
  if (form.memory.enabled) {
    if (form.memory.type) (agent.memory as AnyRecord).type = form.memory.type;
    if (form.memory.scope) (agent.memory as AnyRecord).scope = form.memory.scope;
    if (form.memory.provider) (agent.memory as AnyRecord).provider = form.memory.provider;
    if (form.memory.namespace) (agent.memory as AnyRecord).namespace = form.memory.namespace;
    if (form.memory.tenant_id) (agent.memory as AnyRecord).tenant_id = form.memory.tenant_id;
    // Backend reads 'recall_limit', not 'retrieval_k'
    if (form.memory.retrieval_k !== DEFAULT_RETRIEVAL_K) (agent.memory as AnyRecord).recall_limit = form.memory.retrieval_k;
    if (form.memory.relevance_threshold !== DEFAULT_RELEVANCE_THRESHOLD) (agent.memory as AnyRecord).relevance_threshold = form.memory.relevance_threshold;
    if (form.memory.embedding_model) (agent.memory as AnyRecord).embedding_model = form.memory.embedding_model;
    if (form.memory.max_episodes !== DEFAULT_MAX_EPISODES) (agent.memory as AnyRecord).max_episodes = form.memory.max_episodes;
    if (form.memory.decay_factor !== DEFAULT_DECAY_FACTOR) (agent.memory as AnyRecord).decay_factor = form.memory.decay_factor;
    if (form.memory.auto_extract_procedural) (agent.memory as AnyRecord).auto_extract_procedural = form.memory.auto_extract_procedural;
    if (form.memory.shared_namespace) (agent.memory as AnyRecord).shared_namespace = form.memory.shared_namespace;
  }

  // Error handling — backend uses server-level retry; keep minimal for forward-compat
  if (form.error_handling.max_retries !== 2 || form.error_handling.retry_strategy !== 'ExponentialBackoff') {
    agent.error_handling = {
      retry_strategy: form.error_handling.retry_strategy,
      max_retries: form.error_handling.max_retries,
      fallback: form.error_handling.fallback,
    };
  }

  // Backend-used fields that need top-level placement:
  // max_iterations — controls tool-calling loop cap
  if ((form as AnyRecord).max_iterations) agent.max_iterations = (form as AnyRecord).max_iterations;
  // token_budget — controls prompt truncation
  if ((form as AnyRecord).token_budget) agent.token_budget = (form as AnyRecord).token_budget;

  // Phantom sections removed from serialization:
  // reasoning, observability, context_management, output_schema,
  // output_guardrails, pre_commands, merit, persistent, dialogue
  // — these features are not implemented in the backend yet.

  // Metadata
  const metaSer: AnyRecord = {};
  if (form.metadata.tags.length > 0) metaSer.tags = form.metadata.tags;
  if (form.metadata.owner) metaSer.owner = form.metadata.owner;
  if (form.metadata.documentation_url) metaSer.documentation_url = form.metadata.documentation_url;
  if (Object.keys(metaSer).length > 0) agent.metadata = metaSer;

  return { agent };
}

/* ---------- Hook ---------- */

export interface ValidateResult {
  valid: boolean;
  errors: string[];
}

export function useAgentEditor(agentName: string | null) {
  const { data: rawData, isLoading, error } = useConfig('agent', agentName);
  const saveMutation = useSaveAgentDB();
  const validateMutation = useValidateAgent();

  const [config, setConfig] = useState<AgentFormState>(defaultFormState);
  const initialRef = useRef<string>('');
  const isExistingRef = useRef(false);

  // Populate form when server data arrives — unwrap config_data from ConfigDetail
  useEffect(() => {
    if (rawData) {
      isExistingRef.current = true;
      const parsed = parseConfig((rawData.config_data ?? rawData) as Record<string, unknown>);
      setConfig(parsed);
      initialRef.current = JSON.stringify(parsed);
    }
  }, [rawData]);

  const isDirty = JSON.stringify(config) !== initialRef.current;

  const updateField = useCallback(
    <K extends keyof AgentFormState>(section: K, value: AgentFormState[K]) => {
      setConfig((prev) => ({ ...prev, [section]: value }));
    },
    [],
  );

  const save = useCallback(async () => {
    const payload = toAgentConfig(config);
    await saveMutation.mutateAsync({
      name: config.name,
      data: payload,
      isNew: !isExistingRef.current,
    });
    isExistingRef.current = true;
    initialRef.current = JSON.stringify(config);
  }, [config, saveMutation]);

  const validate = useCallback(async (): Promise<ValidateResult> => {
    const payload = toAgentConfig(config);
    return validateMutation.mutateAsync(payload) as Promise<ValidateResult>;
  }, [config, validateMutation]);

  return {
    config,
    isDirty,
    isLoading,
    error,
    updateField,
    save,
    validate,
    saveStatus: saveMutation.status,
    saveError: saveMutation.error,
    validateResult: validateMutation.data as ValidateResult | undefined,
    validateStatus: validateMutation.status,
  };
}
