/**
 * The Library agent editor's pure half: form ⇄ config.
 *
 * Kept free of React so the two things that have bitten this editor can
 * be asserted directly:
 *
 * 1. Vocabulary. The Type dropdown once offered "Conversational /
 *    Autonomous / Reactive" — words the engine has never had. Every agent
 *    saved with one of them failed its first run with "Unknown agent
 *    type". The engine publishes what it can run at /api/studio/registry;
 *    the editor's job is to offer that list, not invent one.
 *
 * 2. Silent rewrites. A no-op Save used to inject provider, model,
 *    temperature, max_tokens and system_prompt into a *script* agent
 *    (bug 25). A field is written only when the loaded config had it or
 *    the user moved it off the default, and `type` now follows the same
 *    rule: a config with no type key means llm to the engine, and saving
 *    it untouched must not turn that absence into a key.
 */

export interface AgentForm {
  name: string;
  description: string;
  type: string;
  system_prompt: string;
  provider: string;
  model: string;
  temperature: number;
  max_tokens: number;
  tools: string[];
  llm_profile: string | null;
  safety_profile: string | null;
  error_handling_profile: string | null;
  observability_profile: string | null;
  memory_profile: string | null;
}

/** What the engine assumes when a key is absent. `type` mirrors
 *  create_agent's `config.get("type", "llm")`. */
export const EMPTY_FORM: AgentForm = {
  name: '',
  description: '',
  type: 'llm',
  system_prompt: '',
  provider: 'openai',
  model: 'gpt-4o',
  temperature: 0.7,
  max_tokens: 4096,
  tools: [],
  llm_profile: null,
  safety_profile: null,
  error_handling_profile: null,
  observability_profile: null,
  memory_profile: null,
};

/** The fields this form edits, and which are written back only on change. */
const MANAGED_FIELDS = [
  'type',
  'system_prompt',
  'provider',
  'model',
  'temperature',
  'max_tokens',
] as const;

/** Read a loaded agent config into form state. Unknown keys are the
 *  caller's to keep (see buildAgentConfig's `raw`). */
export function formFromAgent(agent: Record<string, unknown>): Partial<AgentForm> {
  return {
    type: String(agent.type ?? EMPTY_FORM.type),
    system_prompt: String(agent.system_prompt ?? EMPTY_FORM.system_prompt),
    provider: String(agent.provider ?? EMPTY_FORM.provider),
    model: String(agent.model ?? EMPTY_FORM.model),
    temperature: Number(agent.temperature ?? EMPTY_FORM.temperature),
    max_tokens: Number(agent.max_tokens ?? EMPTY_FORM.max_tokens),
  };
}

/** Form state → the `{agent: {...}}` envelope the API stores.
 *
 *  `raw` is the agent as loaded (or {} for a new one). Everything in it is
 *  carried through untouched; a managed field is written only if `raw`
 *  already had it or the form moved it off the default. */
export function buildAgentConfig(
  raw: Record<string, unknown>,
  form: AgentForm,
): { agent: Record<string, unknown> } {
  const agent: Record<string, unknown> = { ...raw };
  // Identity is not a default: a config must say what it is. The editor
  // used to leave name out of the body and rely on the URL, which the
  // server now refuses ("Agent config must have 'name'").
  agent.name = form.name;
  if (form.description || 'description' in raw) agent.description = form.description;
  for (const key of MANAGED_FIELDS) {
    const value = form[key];
    if (key in raw || value !== EMPTY_FORM[key]) agent[key] = value;
  }
  if (form.tools.length > 0) agent.tools = form.tools;
  if (form.llm_profile) agent.llm_profile = form.llm_profile;
  if (form.safety_profile) agent.safety_profile = form.safety_profile;
  if (form.error_handling_profile) agent.error_handling_profile = form.error_handling_profile;
  if (form.observability_profile) agent.observability_profile = form.observability_profile;
  if (form.memory_profile) agent.memory_profile = form.memory_profile;
  return { agent };
}

export interface TypeOption {
  value: string;
  label: string;
}

/** Options for the Type dropdown.
 *
 *  `registryTypes` is /api/studio/registry's agent_types, or undefined
 *  while it loads. The current value is always selectable so a loaded
 *  config is displayed as itself; if the registry has arrived and does not
 *  list it, the label says so rather than the dropdown silently showing
 *  the first option as though that were the truth. */
export function agentTypeOptions(
  registryTypes: string[] | undefined,
  current: string,
): TypeOption[] {
  const types = registryTypes ?? [];
  const options: TypeOption[] = types.map((t) => ({ value: t, label: t }));
  if (current && !types.includes(current)) {
    options.unshift({
      value: current,
      label: registryTypes ? `${current} (not registered on this server)` : current,
    });
  }
  return options;
}
