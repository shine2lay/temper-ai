/**
 * Full-page agent editor with profile selectors and YAML panel.
 *
 * Loads an existing agent config by name or starts with empty state.
 * Saves via Config CRUD API (Plan 2).
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { useUnsavedChangesGuard } from '@/hooks/useUnsavedChangesGuard';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { useConfig, useCreateConfig, useUpdateConfig } from '@/hooks/useConfigAPI';
import { Field, inputClass, selectClass, textareaClass } from '../shared';
import { ProfileSelector } from './ProfileSelector';
import { YAMLPanel } from './YAMLPanel';
import { useRegistry } from '@/hooks/useRegistry';
import {
  EMPTY_FORM,
  agentTypeOptions,
  buildAgentConfig,
  formFromAgent,
  type AgentForm,
} from './agentEditorConfig';

interface AgentEditorProps {
  name: string | null;
}


export function AgentEditor({ name }: AgentEditorProps) {
  const navigate = useNavigate();
  const isNew = !name;
  const { data, isLoading } = useConfig('agent', name);
  const createMutation = useCreateConfig('agent');
  const updateMutation = useUpdateConfig('agent', name ?? '');

  const [form, setForm] = useState<AgentForm>(EMPTY_FORM);
  // Snapshot of the loaded config, so leaving with unsaved edits can warn.
  const loadedRef = useRef<string>(JSON.stringify(EMPTY_FORM));
  // The form only covers LLM fields. A script agent also carries
  // script_template, timeout_seconds and dispatch ops, and rebuilding the
  // config from the form alone silently deleted them — turning a script
  // agent into an empty LLM one and erasing its runtime routing.
  const rawAgentRef = useRef<Record<string, unknown>>({});
  useUnsavedChangesGuard(JSON.stringify(form) !== loadedRef.current);

  // Load existing config.
  //
  // The config endpoint returns the raw config — `{agent: {...}}` — not a
  // `config_data` wrapper. Reading only the wrapper meant the form never
  // loaded: it sat on its blank defaults (openai / gpt-4o) while claiming
  // to be editing a real agent, and saving would have written those
  // defaults over the stored config. Accept both shapes.
  useEffect(() => {
    const raw = (data?.config_data ?? data) as Record<string, unknown> | undefined;
    if (raw) {
      const d = raw;
      const agent = (d.agent ?? d) as Record<string, unknown>;
      rawAgentRef.current = agent;
      const loaded: AgentForm = {
        name: (data?.name as string | undefined) ?? (agent.name as string | undefined) ?? name ?? '',
        description:
          (data?.description as string | undefined)
          ?? (agent.description as string | undefined)
          ?? '',
        ...(formFromAgent(agent) as Pick<
          AgentForm,
          'type' | 'system_prompt' | 'provider' | 'model' | 'temperature' | 'max_tokens'
        >),
        tools: Array.isArray(agent.tools) ? agent.tools.map(String) : [],
        llm_profile: agent.llm_profile ? String(agent.llm_profile) : null,
        safety_profile: agent.safety_profile ? String(agent.safety_profile) : null,
        error_handling_profile: agent.error_handling_profile
          ? String(agent.error_handling_profile)
          : null,
        observability_profile: agent.observability_profile
          ? String(agent.observability_profile)
          : null,
        memory_profile: agent.memory_profile ? String(agent.memory_profile) : null,
      };
      setForm(loaded);
      loadedRef.current = JSON.stringify(loaded);
    }
  }, [data]);

  const update = useCallback(
    <K extends keyof AgentForm>(key: K, value: AgentForm[K]) => {
      setForm((f) => ({ ...f, [key]: value }));
    },
    [],
  );

  // Pure and tested in agentEditorConfig.ts: carries unknown keys through,
  // writes a managed field only when it was there or the user changed it.
  const toConfigData = useCallback(
    (): Record<string, unknown> => buildAgentConfig(rawAgentRef.current ?? {}, form),
    [form],
  );

  // The engine publishes the types it can run. Offering anything else here
  // produced agents that saved fine and failed their first run.
  const { data: registry } = useRegistry();
  const typeOptions = agentTypeOptions(registry?.agent_types, form.type);

  const handleSave = useCallback(() => {
    const config_data = toConfigData();
    if (isNew) {
      createMutation.mutate(
        { name: form.name, description: form.description, config_data },
        {
          onSuccess: () => {
            toast.success('Agent created');
            navigate(`/library/agent/${form.name}`);
          },
          onError: (err) => toast.error(err.message),
        },
      );
    } else {
      updateMutation.mutate(
        { description: form.description, config_data },
        {
          onSuccess: () => toast.success('Agent saved'),
          onError: (err) => toast.error(err.message),
        },
      );
    }
  }, [isNew, form, toConfigData, createMutation, updateMutation, navigate]);

  if (!isNew && isLoading) {
    return <p className="p-6 text-sm text-temper-text-muted">Loading...</p>;
  }

  const isPending = createMutation.isPending || updateMutation.isPending;

  return (
    <div className="h-full flex flex-col bg-temper-bg">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-temper-border">
        <h1 className="text-lg font-semibold text-temper-text">
          {isNew ? 'New Agent' : `Edit: ${name}`}
        </h1>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" onClick={() => navigate(-1)}>
            Cancel
          </Button>
          <Button size="sm" onClick={handleSave} disabled={isPending}>
            {isPending ? 'Saving...' : 'Save'}
          </Button>
        </div>
      </div>

      {/* Form */}
      <div className="flex-1 overflow-y-auto px-6 py-4 max-w-2xl">
        {/* Basic Info */}
        <div className="flex flex-col gap-3 mb-6">
          {isNew && (
            <Field label="Name">
              <input
                className={inputClass}
                value={form.name}
                onChange={(e) => update('name', e.target.value)}
                placeholder="my-agent"
              />
            </Field>
          )}
          <Field label="Description">
            <input
              className={inputClass}
              value={form.description}
              onChange={(e) => update('description', e.target.value)}
              placeholder="What this agent does"
            />
          </Field>
          <Field label="Type">
            <select
              className={selectClass}
              value={form.type}
              onChange={(e) => update('type', e.target.value)}
            >
              {typeOptions.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
            {form.type !== 'llm' && (
              <p className="mt-1 text-[11px] text-temper-text-muted">
                This form edits the LLM fields. A <code>{form.type}</code> agent&apos;s other
                fields (for a script agent, <code>script_template</code>) are kept from the
                loaded config and can be edited in the YAML panel below.
              </p>
            )}
          </Field>
        </div>

        {/* Prompt */}
        <div className="mb-6">
          <Field label="System Prompt">
            <textarea
              className={textareaClass}
              rows={6}
              value={form.system_prompt}
              onChange={(e) => update('system_prompt', e.target.value)}
              placeholder="You are a helpful agent..."
            />
          </Field>
        </div>

        {/* Inference (inline when no LLM profile) */}
        <ProfileSelector
          profileType="llm"
          selectedProfile={form.llm_profile}
          onSelect={(p) => update('llm_profile', p)}
        >
          <div className="flex flex-col gap-3 pl-2 border-l-2 border-temper-accent/20">
            <Field label="Provider">
              <input
                className={inputClass}
                value={form.provider}
                onChange={(e) => update('provider', e.target.value)}
              />
            </Field>
            <Field label="Model">
              <input
                className={inputClass}
                value={form.model}
                onChange={(e) => update('model', e.target.value)}
              />
            </Field>
            <div className="flex gap-3">
              <Field label="Temperature">
                <input
                  type="number"
                  className={inputClass}
                  value={form.temperature}
                  onChange={(e) => update('temperature', Number(e.target.value))}
                  min={0}
                  max={2}
                  step={0.1}
                />
              </Field>
              <Field label="Max Tokens">
                <input
                  type="number"
                  className={inputClass}
                  value={form.max_tokens}
                  onChange={(e) => update('max_tokens', Number(e.target.value))}
                  min={1}
                />
              </Field>
            </div>
          </div>
        </ProfileSelector>

        <div className="my-4" />

        {/* Profile selectors */}
        <ProfileSelector
          profileType="safety"
          selectedProfile={form.safety_profile}
          onSelect={(p) => update('safety_profile', p)}
        />

        <div className="my-4" />

        <ProfileSelector
          profileType="error_handling"
          selectedProfile={form.error_handling_profile}
          onSelect={(p) => update('error_handling_profile', p)}
        />

        <div className="my-4" />

        <ProfileSelector
          profileType="observability"
          selectedProfile={form.observability_profile}
          onSelect={(p) => update('observability_profile', p)}
        />

        <div className="my-4" />

        <ProfileSelector
          profileType="memory"
          selectedProfile={form.memory_profile}
          onSelect={(p) => update('memory_profile', p)}
        />

        {/* YAML panel */}
        <div className="mt-6">
          <YAMLPanel
            configData={toConfigData()}
            onChange={(cfg) => {
              const agent = (cfg.agent ?? cfg) as Record<string, unknown>;
              // The YAML is the whole agent, so it becomes the new raw
              // config — not just a source for the six LLM fields. Before
              // this, a script_template typed into the YAML panel reached
              // the form and was dropped on save.
              rawAgentRef.current = agent;
              setForm((f) => ({ ...f, ...formFromAgent(agent) }));
            }}
          />
        </div>
      </div>
    </div>
  );
}
