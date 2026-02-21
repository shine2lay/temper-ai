/**
 * Custom hook encapsulating the agent editing lifecycle.
 * Fetches an agent config from the Studio API, normalizes it into form state,
 * and provides save/validate mutations.
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { useStudioConfig, useSaveAgent, useValidateAgent } from './useStudioAPI';

/* ---------- Form state types ---------- */

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
  };
  memory: {
    enabled: boolean;
    type: string;
    scope: string;
    provider: string;
  };
  error_handling: {
    retry_strategy: string;
    max_retries: number;
    fallback: string;
  };
  reasoning: {
    enabled: boolean;
    planning_prompt: string;
    inject_as: string;
    max_planning_tokens: number;
  };
  observability: {
    log_inputs: boolean;
    log_outputs: boolean;
    log_reasoning: boolean;
    track_latency: boolean;
    track_token_usage: boolean;
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

function defaultFormState(): AgentFormState {
  return {
    name: '',
    description: '',
    version: '1.0',
    type: 'standard',
    prompt: { mode: 'inline', inline: '', template: '', variables: {} },
    inference: {
      provider: '',
      model: '',
      base_url: '',
      api_key_ref: '',
      temperature: DEFAULT_TEMPERATURE,
      max_tokens: DEFAULT_MAX_TOKENS,
      top_p: DEFAULT_TOP_P,
      timeout_seconds: DEFAULT_TIMEOUT,
    },
    tools: { mode: 'auto', entries: [] },
    safety: {
      mode: 'execute',
      risk_level: 'low',
      max_tool_calls_per_execution: DEFAULT_MAX_TOOL_CALLS,
      max_execution_time_seconds: DEFAULT_MAX_EXEC_TIME,
    },
    memory: { enabled: false, type: '', scope: '', provider: '' },
    error_handling: {
      retry_strategy: 'ExponentialBackoff',
      max_retries: DEFAULT_MAX_RETRIES,
      fallback: 'GracefulDegradation',
    },
    reasoning: {
      enabled: false,
      planning_prompt: '',
      inject_as: 'system',
      max_planning_tokens: DEFAULT_MAX_PLANNING_TOKENS,
    },
    observability: {
      log_inputs: true,
      log_outputs: true,
      log_reasoning: false,
      track_latency: true,
      track_token_usage: true,
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

  // Determine prompt mode
  const hasInline = typeof prompt?.inline === 'string' && prompt.inline !== '';
  const hasTemplate = typeof prompt?.template === 'string' && prompt.template !== '';

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
      mode: hasTemplate && !hasInline ? 'template' : 'inline',
      inline: (prompt?.inline as string) ?? '',
      template: (prompt?.template as string) ?? '',
      variables,
    },
    inference: {
      provider: (inference?.provider as string) ?? '',
      model: (inference?.model as string) ?? '',
      base_url: (inference?.base_url as string) ?? '',
      api_key_ref: (inference?.api_key_ref as string) ?? '',
      temperature: (inference?.temperature as number) ?? DEFAULT_TEMPERATURE,
      max_tokens: (inference?.max_tokens as number) ?? DEFAULT_MAX_TOKENS,
      top_p: (inference?.top_p as number) ?? DEFAULT_TOP_P,
      timeout_seconds: (inference?.timeout_seconds as number) ?? DEFAULT_TIMEOUT,
    },
    tools: { mode: toolsMode, entries: toolEntries },
    safety: {
      mode: (safety?.mode as string) ?? 'execute',
      risk_level: (safety?.risk_level as string) ?? 'low',
      max_tool_calls_per_execution:
        (safety?.max_tool_calls_per_execution as number) ?? DEFAULT_MAX_TOOL_CALLS,
      max_execution_time_seconds:
        (safety?.max_execution_time_seconds as number) ?? DEFAULT_MAX_EXEC_TIME,
    },
    memory: {
      enabled: (memory?.enabled as boolean) ?? false,
      type: (memory?.type as string) ?? '',
      scope: (memory?.scope as string) ?? '',
      provider: (memory?.provider as string) ?? '',
    },
    error_handling: {
      retry_strategy: (errorHandling?.retry_strategy as string) ?? 'ExponentialBackoff',
      max_retries: (errorHandling?.max_retries as number) ?? DEFAULT_MAX_RETRIES,
      fallback: (errorHandling?.fallback as string) ?? 'GracefulDegradation',
    },
    reasoning: {
      enabled: (reasoning?.enabled as boolean) ?? false,
      planning_prompt: (reasoning?.planning_prompt as string) ?? '',
      inject_as: (reasoning?.inject_as as string) ?? 'system',
      max_planning_tokens:
        (reasoning?.max_planning_tokens as number) ?? DEFAULT_MAX_PLANNING_TOKENS,
    },
    observability: {
      log_inputs: (observability?.log_inputs as boolean) ?? true,
      log_outputs: (observability?.log_outputs as boolean) ?? true,
      log_reasoning: (observability?.log_reasoning as boolean) ?? false,
      track_latency: (observability?.track_latency as boolean) ?? true,
      track_token_usage: (observability?.track_token_usage as boolean) ?? true,
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

  // Prompt
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

  // Inference
  const inf: AnyRecord = {};
  if (form.inference.provider) inf.provider = form.inference.provider;
  if (form.inference.model) inf.model = form.inference.model;
  if (form.inference.base_url) inf.base_url = form.inference.base_url;
  if (form.inference.api_key_ref) inf.api_key_ref = form.inference.api_key_ref;
  inf.temperature = form.inference.temperature;
  inf.max_tokens = form.inference.max_tokens;
  if (form.inference.top_p !== DEFAULT_TOP_P) inf.top_p = form.inference.top_p;
  if (form.inference.timeout_seconds !== DEFAULT_TIMEOUT) {
    inf.timeout_seconds = form.inference.timeout_seconds;
  }
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

  // Safety
  agent.safety = {
    mode: form.safety.mode,
    risk_level: form.safety.risk_level,
    max_tool_calls_per_execution: form.safety.max_tool_calls_per_execution,
    max_execution_time_seconds: form.safety.max_execution_time_seconds,
  };

  // Memory
  agent.memory = { enabled: form.memory.enabled };
  if (form.memory.enabled) {
    if (form.memory.type) (agent.memory as AnyRecord).type = form.memory.type;
    if (form.memory.scope) (agent.memory as AnyRecord).scope = form.memory.scope;
    if (form.memory.provider) (agent.memory as AnyRecord).provider = form.memory.provider;
  }

  // Error handling
  agent.error_handling = {
    retry_strategy: form.error_handling.retry_strategy,
    max_retries: form.error_handling.max_retries,
    fallback: form.error_handling.fallback,
  };

  // Reasoning (only include if enabled)
  if (form.reasoning.enabled) {
    agent.reasoning = {
      enabled: true,
      planning_prompt: form.reasoning.planning_prompt,
      inject_as: form.reasoning.inject_as,
      max_planning_tokens: form.reasoning.max_planning_tokens,
    };
  }

  // Observability
  agent.observability = {
    log_inputs: form.observability.log_inputs,
    log_outputs: form.observability.log_outputs,
    log_reasoning: form.observability.log_reasoning,
    track_latency: form.observability.track_latency,
    track_token_usage: form.observability.track_token_usage,
  };

  return { agent };
}

/* ---------- Hook ---------- */

export interface ValidateResult {
  valid: boolean;
  errors: string[];
}

export function useAgentEditor(agentName: string | null) {
  const { data, isLoading, error } = useStudioConfig('agents', agentName);
  const saveMutation = useSaveAgent();
  const validateMutation = useValidateAgent();

  const [config, setConfig] = useState<AgentFormState>(defaultFormState);
  const initialRef = useRef<string>('');

  // Populate form when server data arrives
  useEffect(() => {
    if (data) {
      const parsed = parseConfig(data);
      setConfig(parsed);
      initialRef.current = JSON.stringify(parsed);
    }
  }, [data]);

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
      isNew: false,
    });
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
