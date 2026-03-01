/**
 * Full-page agent editor with profile selectors and YAML panel.
 *
 * Loads an existing agent config by name or starts with empty state.
 * Saves via Config CRUD API (Plan 2).
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { useConfig, useCreateConfig, useUpdateConfig } from '@/hooks/useConfigAPI';
import { Field, inputClass, selectClass, textareaClass } from '../shared';
import { ProfileSelector } from './ProfileSelector';
import { YAMLPanel } from './YAMLPanel';

interface AgentEditorProps {
  name: string | null;
}

interface AgentForm {
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

const EMPTY_FORM: AgentForm = {
  name: '',
  description: '',
  type: 'conversational',
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

export function AgentEditor({ name }: AgentEditorProps) {
  const navigate = useNavigate();
  const isNew = !name;
  const { data, isLoading } = useConfig('agent', name);
  const createMutation = useCreateConfig('agent');
  const updateMutation = useUpdateConfig('agent', name ?? '');

  const [form, setForm] = useState<AgentForm>(EMPTY_FORM);

  // Load existing config
  useEffect(() => {
    if (data?.config_data) {
      const d = data.config_data as Record<string, unknown>;
      const agent = (d.agent ?? d) as Record<string, unknown>;
      setForm({
        name: data.name ?? '',
        description: data.description ?? '',
        type: String(agent.type ?? 'conversational'),
        system_prompt: String(agent.system_prompt ?? ''),
        provider: String(agent.provider ?? 'openai'),
        model: String(agent.model ?? 'gpt-4o'),
        temperature: Number(agent.temperature ?? 0.7),
        max_tokens: Number(agent.max_tokens ?? 4096),
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
      });
    }
  }, [data]);

  const update = useCallback(
    <K extends keyof AgentForm>(key: K, value: AgentForm[K]) => {
      setForm((f) => ({ ...f, [key]: value }));
    },
    [],
  );

  const toConfigData = useCallback((): Record<string, unknown> => {
    const agent: Record<string, unknown> = {
      type: form.type,
      system_prompt: form.system_prompt,
      provider: form.provider,
      model: form.model,
      temperature: form.temperature,
      max_tokens: form.max_tokens,
    };
    if (form.tools.length > 0) agent.tools = form.tools;
    if (form.llm_profile) agent.llm_profile = form.llm_profile;
    if (form.safety_profile) agent.safety_profile = form.safety_profile;
    if (form.error_handling_profile) agent.error_handling_profile = form.error_handling_profile;
    if (form.observability_profile) agent.observability_profile = form.observability_profile;
    if (form.memory_profile) agent.memory_profile = form.memory_profile;
    return { agent };
  }, [form]);

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
              <option value="conversational">Conversational</option>
              <option value="autonomous">Autonomous</option>
              <option value="reactive">Reactive</option>
            </select>
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
              setForm((f) => ({
                ...f,
                type: String(agent.type ?? f.type),
                system_prompt: String(agent.system_prompt ?? f.system_prompt),
                provider: String(agent.provider ?? f.provider),
                model: String(agent.model ?? f.model),
                temperature: Number(agent.temperature ?? f.temperature),
                max_tokens: Number(agent.max_tokens ?? f.max_tokens),
              }));
            }}
          />
        </div>
      </div>
    </div>
  );
}
