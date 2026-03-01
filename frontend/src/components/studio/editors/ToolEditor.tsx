/**
 * Full-page tool editor with YAML panel.
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { useConfig, useCreateConfig, useUpdateConfig } from '@/hooks/useConfigAPI';
import { Field, inputClass, textareaClass } from '../shared';
import { YAMLPanel } from './YAMLPanel';

interface ToolEditorProps {
  name: string | null;
}

interface ToolForm {
  name: string;
  description: string;
  tool_class: string;
  default_config: string;
  rate_limit: number;
}

const EMPTY_FORM: ToolForm = {
  name: '',
  description: '',
  tool_class: '',
  default_config: '{}',
  rate_limit: 0,
};

export function ToolEditor({ name }: ToolEditorProps) {
  const navigate = useNavigate();
  const isNew = !name;
  const { data, isLoading } = useConfig('tool', name);
  const createMutation = useCreateConfig('tool');
  const updateMutation = useUpdateConfig('tool', name ?? '');

  const [form, setForm] = useState<ToolForm>(EMPTY_FORM);

  useEffect(() => {
    if (data?.config_data) {
      const d = data.config_data as Record<string, unknown>;
      const tool = (d.tool ?? d) as Record<string, unknown>;
      setForm({
        name: data.name ?? '',
        description: data.description ?? '',
        tool_class: String(tool.class ?? tool.tool_class ?? ''),
        default_config: JSON.stringify(tool.config ?? tool.default_config ?? {}, null, 2),
        rate_limit: Number(tool.rate_limit ?? 0),
      });
    }
  }, [data]);

  const update = useCallback(
    <K extends keyof ToolForm>(key: K, value: ToolForm[K]) => {
      setForm((f) => ({ ...f, [key]: value }));
    },
    [],
  );

  const toConfigData = useCallback((): Record<string, unknown> => {
    let parsedConfig: Record<string, unknown> = {};
    try {
      parsedConfig = JSON.parse(form.default_config);
    } catch {
      // keep empty
    }
    const tool: Record<string, unknown> = {
      class: form.tool_class,
      config: parsedConfig,
    };
    if (form.rate_limit > 0) tool.rate_limit = form.rate_limit;
    return { tool };
  }, [form]);

  const handleSave = useCallback(() => {
    const config_data = toConfigData();
    if (isNew) {
      createMutation.mutate(
        { name: form.name, description: form.description, config_data },
        {
          onSuccess: () => {
            toast.success('Tool created');
            navigate(`/library/tool/${form.name}`);
          },
          onError: (err) => toast.error(err.message),
        },
      );
    } else {
      updateMutation.mutate(
        { description: form.description, config_data },
        {
          onSuccess: () => toast.success('Tool saved'),
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
          {isNew ? 'New Tool' : `Edit: ${name}`}
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
                placeholder="my-tool"
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
          <Field label="Tool Class" hint="Fully qualified Python class name">
            <input
              className={inputClass}
              value={form.tool_class}
              onChange={(e) => update('tool_class', e.target.value)}
              placeholder="temper_ai.tools.web_search.WebSearchTool"
            />
          </Field>
          <Field label="Rate Limit" hint="Max calls per minute (0 = unlimited)">
            <input
              type="number"
              className={inputClass}
              value={form.rate_limit}
              onChange={(e) => update('rate_limit', Number(e.target.value))}
              min={0}
            />
          </Field>
          <Field label="Default Config" hint="JSON object with tool-specific settings">
            <textarea
              className={textareaClass}
              rows={6}
              value={form.default_config}
              onChange={(e) => update('default_config', e.target.value)}
              spellCheck={false}
            />
          </Field>
        </div>

        <div className="mt-6">
          <YAMLPanel configData={toConfigData()} onChange={() => {}} />
        </div>
      </div>
    </div>
  );
}
