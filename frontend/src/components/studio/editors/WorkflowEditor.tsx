/**
 * Workflow editor — name, description, profile selectors, and YAML panel.
 *
 * The DAG canvas is handled by the existing StudioPage (accessed via /studio/:name).
 * This editor handles the metadata and profile fields that wrap around the DAG.
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { useConfig, useCreateConfig, useUpdateConfig } from '@/hooks/useConfigAPI';
import { Field, inputClass, textareaClass } from '../shared';
import { ProfileSelector } from './ProfileSelector';
import { YAMLPanel } from './YAMLPanel';

interface WorkflowEditorProps {
  name: string | null;
}

interface WorkflowForm {
  name: string;
  description: string;
  safety_profile: string | null;
  observability_profile: string | null;
  budget_profile: string | null;
  inputs_schema: string;
}

const EMPTY_FORM: WorkflowForm = {
  name: '',
  description: '',
  safety_profile: null,
  observability_profile: null,
  budget_profile: null,
  inputs_schema: '',
};

export function WorkflowEditor({ name }: WorkflowEditorProps) {
  const navigate = useNavigate();
  const isNew = !name;
  const { data, isLoading } = useConfig('workflow', name);
  const createMutation = useCreateConfig('workflow');
  const updateMutation = useUpdateConfig('workflow', name ?? '');

  const [form, setForm] = useState<WorkflowForm>(EMPTY_FORM);

  useEffect(() => {
    if (data?.config_data) {
      const d = data.config_data as Record<string, unknown>;
      const wf = (d.workflow ?? d) as Record<string, unknown>;
      setForm({
        name: data.name ?? '',
        description: data.description ?? String(wf.description ?? ''),
        safety_profile: wf.safety_profile ? String(wf.safety_profile) : null,
        observability_profile: wf.observability_profile
          ? String(wf.observability_profile)
          : null,
        budget_profile: wf.budget_profile ? String(wf.budget_profile) : null,
        inputs_schema: wf.inputs
          ? JSON.stringify(wf.inputs, null, 2)
          : '',
      });
    }
  }, [data]);

  const update = useCallback(
    <K extends keyof WorkflowForm>(key: K, value: WorkflowForm[K]) => {
      setForm((f) => ({ ...f, [key]: value }));
    },
    [],
  );

  const toConfigData = useCallback((): Record<string, unknown> => {
    const workflow: Record<string, unknown> = {
      name: isNew ? form.name : name,
      description: form.description,
    };
    if (form.safety_profile) workflow.safety_profile = form.safety_profile;
    if (form.observability_profile) workflow.observability_profile = form.observability_profile;
    if (form.budget_profile) workflow.budget_profile = form.budget_profile;
    if (form.inputs_schema) {
      try {
        workflow.inputs = JSON.parse(form.inputs_schema);
      } catch {
        // invalid JSON — skip
      }
    }
    return { workflow };
  }, [form, isNew, name]);

  const handleSave = useCallback(() => {
    const config_data = toConfigData();
    if (isNew) {
      createMutation.mutate(
        { name: form.name, description: form.description, config_data },
        {
          onSuccess: () => {
            toast.success('Workflow created');
            navigate(`/studio/${form.name}`);
          },
          onError: (err) => toast.error(err.message),
        },
      );
    } else {
      updateMutation.mutate(
        { description: form.description, config_data },
        {
          onSuccess: () => toast.success('Workflow saved'),
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
      <div className="flex items-center justify-between px-6 py-4 border-b border-temper-border">
        <h1 className="text-lg font-semibold text-temper-text">
          {isNew ? 'New Workflow' : `Edit: ${name}`}
        </h1>
        <div className="flex items-center gap-2">
          {!isNew && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => navigate(`/studio/${name}`)}
            >
              Open in Studio
            </Button>
          )}
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
                placeholder="my-workflow"
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
          <Field label="Inputs Schema" hint="JSON object defining workflow input parameters">
            <textarea
              className={textareaClass}
              rows={6}
              value={form.inputs_schema}
              onChange={(e) => update('inputs_schema', e.target.value)}
              spellCheck={false}
              placeholder='{"topic": {"type": "string", "required": true}}'
            />
          </Field>
        </div>

        <ProfileSelector
          profileType="safety"
          selectedProfile={form.safety_profile}
          onSelect={(p) => update('safety_profile', p)}
        />
        <div className="my-4" />
        <ProfileSelector
          profileType="observability"
          selectedProfile={form.observability_profile}
          onSelect={(p) => update('observability_profile', p)}
        />
        <div className="my-4" />
        <ProfileSelector
          profileType="budget"
          selectedProfile={form.budget_profile}
          onSelect={(p) => update('budget_profile', p)}
        />

        <div className="mt-6">
          <YAMLPanel configData={toConfigData()} onChange={() => {}} />
        </div>
      </div>
    </div>
  );
}
