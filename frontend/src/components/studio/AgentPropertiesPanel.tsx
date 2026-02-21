/**
 * Agent-level property editor for the Studio.
 * Shown in the right panel when an agent name is selected from a stage.
 * Fetches the agent config independently (local state + TanStack Query).
 */
import { useDesignStore } from '@/store/designStore';
import { useAgentEditor, type AgentFormState, type ToolEntry } from '@/hooks/useAgentEditor';
import { Section, Field, Checkbox, inputClass, selectClass, textareaClass } from './shared';

/* ---------- Sub-section components ---------- */

function PromptSection({
  prompt,
  onChange,
}: {
  prompt: AgentFormState['prompt'];
  onChange: (p: AgentFormState['prompt']) => void;
}) {
  return (
    <Section title="Prompt" defaultOpen={true}>
      <Field label="Mode">
        <select
          value={prompt.mode}
          onChange={(e) =>
            onChange({ ...prompt, mode: e.target.value as 'inline' | 'template' })
          }
          className={selectClass}
        >
          <option value="inline">Inline</option>
          <option value="template">Template file</option>
        </select>
      </Field>

      {prompt.mode === 'inline' ? (
        <Field label="Prompt text" hint="Jinja2 template with {{ variables }}">
          <textarea
            value={prompt.inline}
            onChange={(e) => onChange({ ...prompt, inline: e.target.value })}
            className={textareaClass}
            rows={8}
          />
        </Field>
      ) : (
        <Field label="Template path" hint="Path to .j2 or .txt file">
          <input
            type="text"
            value={prompt.template}
            onChange={(e) => onChange({ ...prompt, template: e.target.value })}
            className={inputClass}
            placeholder="prompts/my_agent.j2"
          />
        </Field>
      )}

      <Field label="Variables" hint="Key-value pairs passed to the template">
        <div className="flex flex-col gap-1">
          {Object.entries(prompt.variables).map(([k, v]) => (
            <div key={k} className="flex items-center gap-1">
              <input
                type="text"
                value={k}
                readOnly
                className="w-24 px-2 py-1 text-xs bg-temper-surface border border-temper-border rounded text-temper-text"
              />
              <span className="text-xs text-temper-text-dim">=</span>
              <input
                type="text"
                value={v}
                onChange={(e) =>
                  onChange({
                    ...prompt,
                    variables: { ...prompt.variables, [k]: e.target.value },
                  })
                }
                className="flex-1 px-2 py-1 text-xs bg-temper-surface border border-temper-border rounded text-temper-text"
              />
              <button
                onClick={() => {
                  const next = { ...prompt.variables };
                  delete next[k];
                  onChange({ ...prompt, variables: next });
                }}
                className="text-xs text-red-400 hover:text-red-300 px-1"
              >
                &times;
              </button>
            </div>
          ))}
          <button
            onClick={() => {
              const key = `var_${Object.keys(prompt.variables).length}`;
              onChange({
                ...prompt,
                variables: { ...prompt.variables, [key]: '' },
              });
            }}
            className="text-[10px] text-temper-accent hover:underline self-start"
          >
            + Add variable
          </button>
        </div>
      </Field>
    </Section>
  );
}

function InferenceSection({
  inference,
  onChange,
}: {
  inference: AgentFormState['inference'];
  onChange: (i: AgentFormState['inference']) => void;
}) {
  return (
    <Section title="Inference" defaultOpen={true}>
      <Field label="Provider">
        <input
          type="text"
          value={inference.provider}
          onChange={(e) => onChange({ ...inference, provider: e.target.value })}
          className={inputClass}
          placeholder="openai, anthropic, vllm, ollama"
        />
      </Field>
      <Field label="Model">
        <input
          type="text"
          value={inference.model}
          onChange={(e) => onChange({ ...inference, model: e.target.value })}
          className={inputClass}
          placeholder="gpt-4o, claude-sonnet-4-20250514, qwen3-next"
        />
      </Field>
      <Field label="Base URL" hint="Custom API endpoint (optional)">
        <input
          type="text"
          value={inference.base_url}
          onChange={(e) => onChange({ ...inference, base_url: e.target.value })}
          className={inputClass}
          placeholder="http://localhost:8000"
        />
      </Field>
      <Field label="API Key Ref" hint="Environment variable name for the API key">
        <input
          type="text"
          value={inference.api_key_ref}
          onChange={(e) => onChange({ ...inference, api_key_ref: e.target.value })}
          className={inputClass}
          placeholder="OPENAI_API_KEY"
        />
      </Field>
      <div className="grid grid-cols-2 gap-2">
        <Field label="Temperature">
          <input
            type="number"
            value={inference.temperature}
            onChange={(e) =>
              onChange({ ...inference, temperature: Number(e.target.value) })
            }
            className={inputClass}
            min={0}
            max={2}
            step={0.1}
          />
        </Field>
        <Field label="Max Tokens">
          <input
            type="number"
            value={inference.max_tokens}
            onChange={(e) =>
              onChange({ ...inference, max_tokens: Number(e.target.value) || 0 })
            }
            className={inputClass}
            min={1}
          />
        </Field>
        <Field label="Top P">
          <input
            type="number"
            value={inference.top_p}
            onChange={(e) =>
              onChange({ ...inference, top_p: Number(e.target.value) })
            }
            className={inputClass}
            min={0}
            max={1}
            step={0.05}
          />
        </Field>
        <Field label="Timeout (s)">
          <input
            type="number"
            value={inference.timeout_seconds}
            onChange={(e) =>
              onChange({
                ...inference,
                timeout_seconds: Number(e.target.value) || 0,
              })
            }
            className={inputClass}
            min={0}
          />
        </Field>
      </div>
    </Section>
  );
}

function ToolsSection({
  tools,
  onChange,
}: {
  tools: AgentFormState['tools'];
  onChange: (t: AgentFormState['tools']) => void;
}) {
  const updateEntry = (idx: number, partial: Partial<ToolEntry>) => {
    const entries = [...tools.entries];
    entries[idx] = { ...entries[idx], ...partial };
    onChange({ ...tools, entries });
  };

  return (
    <Section title="Tools" defaultOpen={false}>
      <Field label="Mode" hint="auto = auto-discover, none = no tools, explicit = listed below">
        <select
          value={tools.mode}
          onChange={(e) => {
            const mode = e.target.value as 'auto' | 'none' | 'explicit';
            onChange({
              mode,
              entries: mode === 'explicit' ? tools.entries : [],
            });
          }}
          className={selectClass}
        >
          <option value="auto">Auto-discover</option>
          <option value="none">No tools</option>
          <option value="explicit">Explicit list</option>
        </select>
      </Field>

      {tools.mode === 'explicit' && (
        <div className="flex flex-col gap-2">
          {tools.entries.map((entry, i) => (
            <div
              key={i}
              className="flex flex-col gap-1 p-1.5 bg-temper-surface/50 rounded border border-temper-border/50"
            >
              <div className="flex items-center gap-1">
                <input
                  type="text"
                  value={entry.name}
                  onChange={(e) => updateEntry(i, { name: e.target.value })}
                  className="flex-1 px-2 py-1 text-xs bg-temper-surface border border-temper-border rounded text-temper-text"
                  placeholder="Tool name"
                />
                <button
                  onClick={() =>
                    onChange({
                      ...tools,
                      entries: tools.entries.filter((_, j) => j !== i),
                    })
                  }
                  className="text-xs text-red-400 hover:text-red-300 px-1"
                >
                  &times;
                </button>
              </div>
              <textarea
                value={entry.config}
                onChange={(e) => updateEntry(i, { config: e.target.value })}
                className="px-2 py-1 text-[10px] font-mono bg-temper-surface border border-temper-border rounded text-temper-text-muted resize-y min-h-[32px]"
                placeholder='{"key": "value"}'
                rows={2}
              />
            </div>
          ))}
          <button
            onClick={() =>
              onChange({
                ...tools,
                entries: [...tools.entries, { name: '', config: '' }],
              })
            }
            className="text-[10px] text-temper-accent hover:underline self-start"
          >
            + Add tool
          </button>
        </div>
      )}
    </Section>
  );
}

function SafetySection({
  safety,
  onChange,
}: {
  safety: AgentFormState['safety'];
  onChange: (s: AgentFormState['safety']) => void;
}) {
  return (
    <Section title="Safety" defaultOpen={false}>
      <Field label="Mode">
        <select
          value={safety.mode}
          onChange={(e) => onChange({ ...safety, mode: e.target.value })}
          className={selectClass}
        >
          <option value="execute">Execute</option>
          <option value="monitor">Monitor</option>
          <option value="audit">Audit</option>
        </select>
      </Field>
      <Field label="Risk Level">
        <select
          value={safety.risk_level}
          onChange={(e) => onChange({ ...safety, risk_level: e.target.value })}
          className={selectClass}
        >
          <option value="low">Low</option>
          <option value="medium">Medium</option>
          <option value="high">High</option>
        </select>
      </Field>
      <div className="grid grid-cols-2 gap-2">
        <Field label="Max Tool Calls">
          <input
            type="number"
            value={safety.max_tool_calls_per_execution}
            onChange={(e) =>
              onChange({
                ...safety,
                max_tool_calls_per_execution: Number(e.target.value) || 0,
              })
            }
            className={inputClass}
            min={0}
          />
        </Field>
        <Field label="Max Exec Time (s)">
          <input
            type="number"
            value={safety.max_execution_time_seconds}
            onChange={(e) =>
              onChange({
                ...safety,
                max_execution_time_seconds: Number(e.target.value) || 0,
              })
            }
            className={inputClass}
            min={0}
          />
        </Field>
      </div>
    </Section>
  );
}

function MemorySection({
  memory,
  onChange,
}: {
  memory: AgentFormState['memory'];
  onChange: (m: AgentFormState['memory']) => void;
}) {
  return (
    <Section title="Memory" defaultOpen={false}>
      <Checkbox
        label="Enable memory"
        checked={memory.enabled}
        onChange={(enabled) => onChange({ ...memory, enabled })}
      />
      {memory.enabled && (
        <>
          <Field label="Type">
            <input
              type="text"
              value={memory.type}
              onChange={(e) => onChange({ ...memory, type: e.target.value })}
              className={inputClass}
              placeholder="conversation, knowledge_graph"
            />
          </Field>
          <Field label="Scope">
            <input
              type="text"
              value={memory.scope}
              onChange={(e) => onChange({ ...memory, scope: e.target.value })}
              className={inputClass}
              placeholder="agent, workflow, global"
            />
          </Field>
          <Field label="Provider">
            <input
              type="text"
              value={memory.provider}
              onChange={(e) => onChange({ ...memory, provider: e.target.value })}
              className={inputClass}
              placeholder="postgres, redis"
            />
          </Field>
        </>
      )}
    </Section>
  );
}

function ErrorHandlingSection({
  errorHandling,
  onChange,
}: {
  errorHandling: AgentFormState['error_handling'];
  onChange: (e: AgentFormState['error_handling']) => void;
}) {
  return (
    <Section title="Error Handling" defaultOpen={false}>
      <Field label="Retry Strategy">
        <select
          value={errorHandling.retry_strategy}
          onChange={(e) =>
            onChange({ ...errorHandling, retry_strategy: e.target.value })
          }
          className={selectClass}
        >
          <option value="ExponentialBackoff">Exponential Backoff</option>
          <option value="LinearBackoff">Linear Backoff</option>
          <option value="FixedDelay">Fixed Delay</option>
          <option value="NoRetry">No Retry</option>
        </select>
      </Field>
      <Field label="Max Retries">
        <input
          type="number"
          value={errorHandling.max_retries}
          onChange={(e) =>
            onChange({
              ...errorHandling,
              max_retries: Number(e.target.value) || 0,
            })
          }
          className={inputClass}
          min={0}
        />
      </Field>
      <Field label="Fallback">
        <select
          value={errorHandling.fallback}
          onChange={(e) =>
            onChange({ ...errorHandling, fallback: e.target.value })
          }
          className={selectClass}
        >
          <option value="GracefulDegradation">Graceful Degradation</option>
          <option value="HardFail">Hard Fail</option>
          <option value="DefaultResponse">Default Response</option>
        </select>
      </Field>
    </Section>
  );
}

function ReasoningSection({
  reasoning,
  onChange,
}: {
  reasoning: AgentFormState['reasoning'];
  onChange: (r: AgentFormState['reasoning']) => void;
}) {
  return (
    <Section title="Reasoning" defaultOpen={false}>
      <Checkbox
        label="Enable reasoning / planning"
        checked={reasoning.enabled}
        onChange={(enabled) => onChange({ ...reasoning, enabled })}
      />
      {reasoning.enabled && (
        <>
          <Field label="Planning Prompt">
            <textarea
              value={reasoning.planning_prompt}
              onChange={(e) =>
                onChange({ ...reasoning, planning_prompt: e.target.value })
              }
              className={textareaClass}
              rows={3}
              placeholder="Think step by step..."
            />
          </Field>
          <Field label="Inject As">
            <select
              value={reasoning.inject_as}
              onChange={(e) =>
                onChange({ ...reasoning, inject_as: e.target.value })
              }
              className={selectClass}
            >
              <option value="system">System message</option>
              <option value="user">User message</option>
              <option value="prefix">Output prefix</option>
            </select>
          </Field>
          <Field label="Max Planning Tokens">
            <input
              type="number"
              value={reasoning.max_planning_tokens}
              onChange={(e) =>
                onChange({
                  ...reasoning,
                  max_planning_tokens: Number(e.target.value) || 0,
                })
              }
              className={inputClass}
              min={0}
            />
          </Field>
        </>
      )}
    </Section>
  );
}

function ObservabilitySection({
  observability,
  onChange,
}: {
  observability: AgentFormState['observability'];
  onChange: (o: AgentFormState['observability']) => void;
}) {
  return (
    <Section title="Observability" defaultOpen={false}>
      <Checkbox
        label="Log inputs"
        checked={observability.log_inputs}
        onChange={(v) => onChange({ ...observability, log_inputs: v })}
      />
      <Checkbox
        label="Log outputs"
        checked={observability.log_outputs}
        onChange={(v) => onChange({ ...observability, log_outputs: v })}
      />
      <Checkbox
        label="Log reasoning"
        checked={observability.log_reasoning}
        onChange={(v) => onChange({ ...observability, log_reasoning: v })}
      />
      <Checkbox
        label="Track latency"
        checked={observability.track_latency}
        onChange={(v) => onChange({ ...observability, track_latency: v })}
      />
      <Checkbox
        label="Track token usage"
        checked={observability.track_token_usage}
        onChange={(v) => onChange({ ...observability, track_token_usage: v })}
      />
    </Section>
  );
}

/* ---------- Main panel ---------- */

export function AgentPropertiesPanel() {
  const selectedAgentName = useDesignStore((s) => s.selectedAgentName);
  const selectAgent = useDesignStore((s) => s.selectAgent);

  const {
    config,
    isDirty,
    isLoading,
    error,
    updateField,
    save,
    validate,
    saveStatus,
    saveError,
    validateResult,
    validateStatus,
  } = useAgentEditor(selectedAgentName);

  if (!selectedAgentName) return null;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-32">
        <p className="text-xs text-temper-text-muted">Loading agent...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col gap-2 p-3">
        <button
          onClick={() => selectAgent(null)}
          className="text-xs text-temper-accent hover:underline self-start"
        >
          &larr; Back to stage
        </button>
        <p className="text-xs text-red-400">
          Failed to load agent: {(error as Error).message}
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-temper-border">
        <button
          onClick={() => selectAgent(null)}
          className="text-xs text-temper-accent hover:underline shrink-0"
          aria-label="Back to stage"
        >
          &larr;
        </button>
        <h3 className="text-xs font-semibold text-temper-text truncate flex-1">
          {config.name || selectedAgentName}
        </h3>
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={() => validate()}
            disabled={validateStatus === 'pending'}
            className="px-2 py-1 text-[10px] rounded border border-temper-border text-temper-text-muted hover:bg-temper-surface disabled:opacity-50"
          >
            {validateStatus === 'pending' ? 'Validating...' : 'Validate'}
          </button>
          <button
            onClick={() => save()}
            disabled={!isDirty || saveStatus === 'pending'}
            className="px-2 py-1 text-[10px] rounded bg-temper-accent text-white hover:opacity-90 disabled:opacity-50"
          >
            {saveStatus === 'pending' ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>

      {/* Status banners */}
      {saveStatus === 'success' && (
        <div className="px-3 py-1.5 text-[10px] text-green-400 bg-green-400/10 border-b border-temper-border/50">
          Agent saved successfully
        </div>
      )}
      {saveError && (
        <div className="px-3 py-1.5 text-[10px] text-red-400 bg-red-400/10 border-b border-temper-border/50">
          Save failed: {saveError.message}
        </div>
      )}
      {validateResult && !validateResult.valid && (
        <div className="px-3 py-1.5 text-[10px] text-yellow-400 bg-yellow-400/10 border-b border-temper-border/50">
          {validateResult.errors.map((e, i) => (
            <p key={i}>{e}</p>
          ))}
        </div>
      )}
      {validateResult?.valid && (
        <div className="px-3 py-1.5 text-[10px] text-green-400 bg-green-400/10 border-b border-temper-border/50">
          Configuration is valid
        </div>
      )}

      {/* General */}
      <Section title="General" defaultOpen={true}>
        <Field label="Name">
          <input
            type="text"
            value={config.name}
            readOnly
            className={`${inputClass} opacity-60 cursor-not-allowed`}
          />
        </Field>
        <Field label="Description">
          <textarea
            value={config.description}
            onChange={(e) =>
              updateField('description', e.target.value)
            }
            className={textareaClass}
            rows={2}
            placeholder="What does this agent do?"
          />
        </Field>
        <div className="grid grid-cols-2 gap-2">
          <Field label="Version">
            <input
              type="text"
              value={config.version}
              onChange={(e) => updateField('version', e.target.value)}
              className={inputClass}
            />
          </Field>
          <Field label="Type">
            <select
              value={config.type}
              onChange={(e) => updateField('type', e.target.value)}
              className={selectClass}
            >
              <option value="standard">Standard</option>
              <option value="router">Router</option>
              <option value="critic">Critic</option>
              <option value="orchestrator">Orchestrator</option>
            </select>
          </Field>
        </div>
      </Section>

      {/* Sections */}
      <PromptSection
        prompt={config.prompt}
        onChange={(p) => updateField('prompt', p)}
      />
      <InferenceSection
        inference={config.inference}
        onChange={(i) => updateField('inference', i)}
      />
      <ToolsSection
        tools={config.tools}
        onChange={(t) => updateField('tools', t)}
      />
      <SafetySection
        safety={config.safety}
        onChange={(s) => updateField('safety', s)}
      />
      <MemorySection
        memory={config.memory}
        onChange={(m) => updateField('memory', m)}
      />
      <ErrorHandlingSection
        errorHandling={config.error_handling}
        onChange={(e) => updateField('error_handling', e)}
      />
      <ReasoningSection
        reasoning={config.reasoning}
        onChange={(r) => updateField('reasoning', r)}
      />
      <ObservabilitySection
        observability={config.observability}
        onChange={(o) => updateField('observability', o)}
      />
    </div>
  );
}
