/**
 * Generic profile editor for all 6 profile types.
 *
 * Form fields are generated based on the profile type's known schema.
 * Includes a YAML panel for advanced editing.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import {
  useProfile,
  useCreateProfile,
  useUpdateProfile,
} from '@/hooks/useConfigAPI';
import { Field, inputClass, selectClass } from '../shared';
import { YAMLPanel } from './YAMLPanel';

interface ProfileEditorProps {
  profileType: string;
  name: string | null;
}

const PROFILE_LABELS: Record<string, string> = {
  llm: 'LLM Profile',
  safety: 'Safety Profile',
  error_handling: 'Error Handling Profile',
  observability: 'Observability Profile',
  memory: 'Memory Profile',
  budget: 'Budget Profile',
};

// Schema definitions for each profile type — maps field name to type + options
interface FieldDef {
  type: 'string' | 'number' | 'boolean' | 'select';
  label: string;
  options?: string[];
  default?: unknown;
  hint?: string;
}

const PROFILE_SCHEMAS: Record<string, FieldDef[]> = {
  llm: [
    { type: 'string', label: 'Provider', default: 'openai' },
    { type: 'string', label: 'Model', default: 'gpt-4o' },
    { type: 'number', label: 'Temperature', default: 0.7 },
    { type: 'number', label: 'Max Tokens', default: 4096 },
    { type: 'number', label: 'Top P', default: 1.0 },
    { type: 'number', label: 'Timeout Seconds', default: 120 },
    { type: 'number', label: 'Max Retries', default: 3 },
    { type: 'string', label: 'Base URL', hint: 'Custom API endpoint' },
    { type: 'string', label: 'API Key Ref', hint: 'Env var name for API key' },
    {
      type: 'select',
      label: 'Context Strategy',
      options: ['auto', 'truncate', 'summarize', 'sliding_window'],
      default: 'auto',
    },
  ],
  safety: [
    {
      type: 'select',
      label: 'Execution Mode',
      options: ['supervised', 'autonomous', 'restricted'],
      default: 'supervised',
    },
    {
      type: 'select',
      label: 'Risk Level',
      options: ['low', 'medium', 'high'],
      default: 'medium',
    },
    { type: 'number', label: 'Max Tool Calls Per Execution', default: 25 },
    { type: 'number', label: 'Max Execution Time Seconds', default: 300 },
    { type: 'number', label: 'Max Prompt Length', default: 50000 },
    { type: 'number', label: 'Max Tool Result Size', default: 10000 },
  ],
  error_handling: [
    {
      type: 'select',
      label: 'Retry Strategy',
      options: ['exponential', 'linear', 'fixed', 'none'],
      default: 'exponential',
    },
    { type: 'number', label: 'Max Retries', default: 3 },
    { type: 'string', label: 'Fallback', hint: 'Fallback agent or action' },
    { type: 'number', label: 'Escalate To Human After', default: 0 },
    { type: 'number', label: 'Retry Initial Delay', default: 1.0 },
    { type: 'number', label: 'Retry Max Delay', default: 60.0 },
    { type: 'number', label: 'Retry Exponential Base', default: 2.0 },
  ],
  observability: [
    { type: 'boolean', label: 'Log Prompts', default: false },
    { type: 'boolean', label: 'Log Responses', default: false },
    { type: 'boolean', label: 'Log Tool Calls', default: true },
    {
      type: 'select',
      label: 'Console Mode',
      options: ['minimal', 'normal', 'verbose', 'debug'],
      default: 'normal',
    },
    { type: 'boolean', label: 'Enable Tracing', default: false },
    { type: 'string', label: 'Trace Endpoint', hint: 'OTLP endpoint URL' },
  ],
  memory: [
    { type: 'boolean', label: 'Enabled', default: false },
    {
      type: 'select',
      label: 'Provider',
      options: ['chromadb', 'qdrant', 'pinecone', 'in_memory'],
      default: 'chromadb',
    },
    { type: 'string', label: 'Embedding Model', default: 'text-embedding-3-small' },
    { type: 'number', label: 'Retrieval K', default: 5 },
    { type: 'number', label: 'Relevance Threshold', default: 0.7 },
    { type: 'number', label: 'Max Episodes', default: 100 },
    { type: 'number', label: 'Decay Factor', default: 0.95 },
  ],
  budget: [
    { type: 'number', label: 'Max Cost USD', default: 10.0, hint: 'Maximum cost in USD' },
    { type: 'number', label: 'Max Tokens', default: 100000 },
    {
      type: 'select',
      label: 'Action On Exceed',
      options: ['stop', 'warn', 'throttle'],
      default: 'stop',
    },
    { type: 'number', label: 'Rate Limit RPM', default: 0, hint: 'Requests per minute (0 = unlimited)' },
    { type: 'number', label: 'Rate Limit TPM', default: 0, hint: 'Tokens per minute (0 = unlimited)' },
  ],
};

function fieldToKey(label: string): string {
  return label.toLowerCase().replace(/\s+/g, '_');
}

export function ProfileEditor({ profileType, name }: ProfileEditorProps) {
  const navigate = useNavigate();
  const isNew = !name;
  const { data, isLoading } = useProfile(profileType, name);
  const createMutation = useCreateProfile(profileType);
  const updateMutation = useUpdateProfile(profileType, name ?? '');

  const schema = useMemo(() => PROFILE_SCHEMAS[profileType] ?? [], [profileType]);

  const [profileName, setProfileName] = useState('');
  const [description, setDescription] = useState('');
  const [configData, setConfigData] = useState<Record<string, unknown>>(() => {
    const defaults: Record<string, unknown> = {};
    for (const field of schema) {
      if (field.default !== undefined) {
        defaults[fieldToKey(field.label)] = field.default;
      }
    }
    return defaults;
  });

  useEffect(() => {
    if (data) {
      setProfileName(data.name);
      setDescription(data.description ?? '');
      setConfigData(data.config_data ?? {});
    }
  }, [data]);

  const updateField = useCallback((key: string, value: unknown) => {
    setConfigData((d) => ({ ...d, [key]: value }));
  }, []);

  const handleSave = useCallback(() => {
    if (isNew) {
      createMutation.mutate(
        { name: profileName, description, config_data: configData },
        {
          onSuccess: () => {
            toast.success('Profile created');
            navigate(`/library/profile/${profileType}/${profileName}`);
          },
          onError: (err) => toast.error(err.message),
        },
      );
    } else {
      updateMutation.mutate(
        { description, config_data: configData },
        {
          onSuccess: () => toast.success('Profile saved'),
          onError: (err) => toast.error(err.message),
        },
      );
    }
  }, [isNew, profileName, description, configData, profileType, createMutation, updateMutation, navigate]);

  if (!isNew && isLoading) {
    return <p className="p-6 text-sm text-temper-text-muted">Loading...</p>;
  }

  const isPending = createMutation.isPending || updateMutation.isPending;

  return (
    <div className="h-full flex flex-col bg-temper-bg">
      <div className="flex items-center justify-between px-6 py-4 border-b border-temper-border">
        <h1 className="text-lg font-semibold text-temper-text">
          {isNew
            ? `New ${PROFILE_LABELS[profileType] ?? profileType}`
            : `Edit: ${name}`}
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
                value={profileName}
                onChange={(e) => setProfileName(e.target.value)}
                placeholder={`my-${profileType}-profile`}
              />
            </Field>
          )}
          <Field label="Description">
            <input
              className={inputClass}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </Field>
        </div>

        {/* Dynamic fields from schema */}
        <div className="flex flex-col gap-3 mb-6">
          {schema.map((field) => {
            const key = fieldToKey(field.label);
            const value = configData[key];

            if (field.type === 'boolean') {
              return (
                <label key={key} className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={!!value}
                    onChange={(e) => updateField(key, e.target.checked)}
                    className="accent-temper-accent"
                  />
                  <span className="text-xs text-temper-text">{field.label}</span>
                  {field.hint && (
                    <span className="text-[10px] text-temper-text-dim">
                      ({field.hint})
                    </span>
                  )}
                </label>
              );
            }

            if (field.type === 'select') {
              return (
                <Field key={key} label={field.label} hint={field.hint}>
                  <select
                    className={selectClass}
                    value={String(value ?? '')}
                    onChange={(e) => updateField(key, e.target.value)}
                  >
                    {field.options?.map((opt) => (
                      <option key={opt} value={opt}>
                        {opt}
                      </option>
                    ))}
                  </select>
                </Field>
              );
            }

            if (field.type === 'number') {
              return (
                <Field key={key} label={field.label} hint={field.hint}>
                  <input
                    type="number"
                    className={inputClass}
                    value={value !== undefined ? String(value) : ''}
                    onChange={(e) => updateField(key, Number(e.target.value))}
                    step="any"
                  />
                </Field>
              );
            }

            // string
            return (
              <Field key={key} label={field.label} hint={field.hint}>
                <input
                  className={inputClass}
                  value={String(value ?? '')}
                  onChange={(e) => updateField(key, e.target.value)}
                />
              </Field>
            );
          })}
        </div>

        <div className="mt-6">
          <YAMLPanel configData={configData} onChange={setConfigData} />
        </div>
      </div>
    </div>
  );
}
