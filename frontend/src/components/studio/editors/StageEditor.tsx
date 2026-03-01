/**
 * Full-page stage editor with profile selector and YAML panel.
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { useConfig, useCreateConfig, useUpdateConfig, useConfigs } from '@/hooks/useConfigAPI';
import { Field, inputClass, selectClass } from '../shared';
import { ProfileSelector } from './ProfileSelector';
import { YAMLPanel } from './YAMLPanel';

interface StageEditorProps {
  name: string | null;
}

interface StageForm {
  name: string;
  description: string;
  agents: string[];
  execution_mode: string;
  timeout_seconds: number;
  error_handling_profile: string | null;
  success_criteria: string;
}

const EMPTY_FORM: StageForm = {
  name: '',
  description: '',
  agents: [],
  execution_mode: 'sequential',
  timeout_seconds: 300,
  error_handling_profile: null,
  success_criteria: '',
};

export function StageEditor({ name }: StageEditorProps) {
  const navigate = useNavigate();
  const isNew = !name;
  const { data, isLoading } = useConfig('stage', name);
  const createMutation = useCreateConfig('stage');
  const updateMutation = useUpdateConfig('stage', name ?? '');
  const { data: agentList } = useConfigs('agent');

  const [form, setForm] = useState<StageForm>(EMPTY_FORM);

  useEffect(() => {
    if (data?.config_data) {
      const d = data.config_data as Record<string, unknown>;
      const stage = (d.stage ?? d) as Record<string, unknown>;
      setForm({
        name: data.name ?? '',
        description: data.description ?? '',
        agents: Array.isArray(stage.agents) ? stage.agents.map(String) : [],
        execution_mode: String(stage.execution_mode ?? stage.agent_mode ?? 'sequential'),
        timeout_seconds: Number(stage.timeout_seconds ?? 300),
        error_handling_profile: stage.error_handling_profile
          ? String(stage.error_handling_profile)
          : null,
        success_criteria: String(stage.success_criteria ?? ''),
      });
    }
  }, [data]);

  const update = useCallback(
    <K extends keyof StageForm>(key: K, value: StageForm[K]) => {
      setForm((f) => ({ ...f, [key]: value }));
    },
    [],
  );

  const toConfigData = useCallback((): Record<string, unknown> => {
    const stage: Record<string, unknown> = {
      agents: form.agents,
      execution_mode: form.execution_mode,
      timeout_seconds: form.timeout_seconds,
    };
    if (form.success_criteria) stage.success_criteria = form.success_criteria;
    if (form.error_handling_profile) stage.error_handling_profile = form.error_handling_profile;
    return { stage };
  }, [form]);

  const handleSave = useCallback(() => {
    const config_data = toConfigData();
    if (isNew) {
      createMutation.mutate(
        { name: form.name, description: form.description, config_data },
        {
          onSuccess: () => {
            toast.success('Stage created');
            navigate(`/library/stage/${form.name}`);
          },
          onError: (err) => toast.error(err.message),
        },
      );
    } else {
      updateMutation.mutate(
        { description: form.description, config_data },
        {
          onSuccess: () => toast.success('Stage saved'),
          onError: (err) => toast.error(err.message),
        },
      );
    }
  }, [isNew, form, toConfigData, createMutation, updateMutation, navigate]);

  const toggleAgent = useCallback(
    (agentName: string) => {
      setForm((f) => ({
        ...f,
        agents: f.agents.includes(agentName)
          ? f.agents.filter((a) => a !== agentName)
          : [...f.agents, agentName],
      }));
    },
    [],
  );

  if (!isNew && isLoading) {
    return <p className="p-6 text-sm text-temper-text-muted">Loading...</p>;
  }

  const isPending = createMutation.isPending || updateMutation.isPending;

  return (
    <div className="h-full flex flex-col bg-temper-bg">
      <div className="flex items-center justify-between px-6 py-4 border-b border-temper-border">
        <h1 className="text-lg font-semibold text-temper-text">
          {isNew ? 'New Stage' : `Edit: ${name}`}
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

      <div className="flex-1 overflow-y-auto px-6 py-4 max-w-2xl">
        <div className="flex flex-col gap-3 mb-6">
          {isNew && (
            <Field label="Name">
              <input
                className={inputClass}
                value={form.name}
                onChange={(e) => update('name', e.target.value)}
                placeholder="my-stage"
              />
            </Field>
          )}
          <Field label="Description">
            <input
              className={inputClass}
              value={form.description}
              onChange={(e) => update('description', e.target.value)}
            />
          </Field>
          <Field label="Execution Mode">
            <select
              className={selectClass}
              value={form.execution_mode}
              onChange={(e) => update('execution_mode', e.target.value)}
            >
              <option value="sequential">Sequential</option>
              <option value="parallel">Parallel</option>
              <option value="adaptive">Adaptive</option>
            </select>
          </Field>
          <Field label="Timeout (seconds)">
            <input
              type="number"
              className={inputClass}
              value={form.timeout_seconds}
              onChange={(e) => update('timeout_seconds', Number(e.target.value))}
              min={1}
            />
          </Field>
          <Field label="Success Criteria">
            <input
              className={inputClass}
              value={form.success_criteria}
              onChange={(e) => update('success_criteria', e.target.value)}
              placeholder="Optional success criteria expression"
            />
          </Field>
        </div>

        {/* Agent picker */}
        <div className="mb-6">
          <label className="text-[11px] font-medium text-temper-text-muted">
            Agents
          </label>
          <div className="mt-1 flex flex-col gap-1">
            {agentList?.configs.map((agent) => (
              <label
                key={agent.name}
                className="flex items-center gap-2 px-3 py-2 rounded bg-temper-panel border border-temper-border/50 cursor-pointer hover:bg-temper-surface transition-colors"
              >
                <input
                  type="checkbox"
                  checked={form.agents.includes(agent.name)}
                  onChange={() => toggleAgent(agent.name)}
                  className="accent-temper-accent"
                />
                <span className="text-xs text-temper-text">{agent.name}</span>
                {agent.description && (
                  <span className="text-[10px] text-temper-text-dim ml-auto truncate max-w-48">
                    {agent.description}
                  </span>
                )}
              </label>
            ))}
            {(!agentList || agentList.configs.length === 0) && (
              <p className="text-[10px] text-temper-text-dim py-2">
                No agents available. Create agents first.
              </p>
            )}
          </div>
        </div>

        <ProfileSelector
          profileType="error_handling"
          selectedProfile={form.error_handling_profile}
          onSelect={(p) => update('error_handling_profile', p)}
        />

        <div className="mt-6">
          <YAMLPanel configData={toConfigData()} onChange={() => {}} />
        </div>
      </div>
    </div>
  );
}
