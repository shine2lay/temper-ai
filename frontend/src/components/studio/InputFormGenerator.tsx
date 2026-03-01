/**
 * Dynamic input form generator for the "Run" dialog.
 *
 * Reads the workflow's `inputs` schema and generates form fields:
 *   - string → text input
 *   - string + options → select dropdown
 *   - boolean → toggle checkbox
 *   - number/integer → number input
 *   - required fields marked with asterisk
 *   - defaults pre-filled
 */
import { useState, useMemo, useCallback } from 'react';
import { Button } from '@/components/ui/button';
import { inputClass, selectClass } from './shared';

export interface InputSchema {
  [key: string]: {
    type?: string;
    required?: boolean;
    default?: unknown;
    description?: string;
    options?: string[];
  };
}

interface InputFormGeneratorProps {
  schema: InputSchema;
  onSubmit: (values: Record<string, unknown>) => void;
  onCancel: () => void;
  isSubmitting?: boolean;
}

export function InputFormGenerator({
  schema,
  onSubmit,
  onCancel,
  isSubmitting = false,
}: InputFormGeneratorProps) {
  const fields = useMemo(() => Object.entries(schema), [schema]);

  const [values, setValues] = useState<Record<string, unknown>>(() => {
    const initial: Record<string, unknown> = {};
    for (const [key, spec] of fields) {
      if (spec.default !== undefined) {
        initial[key] = spec.default;
      } else if (spec.type === 'boolean') {
        initial[key] = false;
      } else {
        initial[key] = '';
      }
    }
    return initial;
  });

  const [errors, setErrors] = useState<Record<string, string>>({});

  const setValue = useCallback((key: string, value: unknown) => {
    setValues((prev) => ({ ...prev, [key]: value }));
    setErrors((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }, []);

  const handleSubmit = useCallback(() => {
    const newErrors: Record<string, string> = {};
    for (const [key, spec] of fields) {
      if (spec.required && (values[key] === '' || values[key] === undefined)) {
        newErrors[key] = 'Required';
      }
    }
    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors);
      return;
    }

    // Convert types
    const result: Record<string, unknown> = {};
    for (const [key, spec] of fields) {
      const v = values[key];
      if (v === '' && !spec.required) continue;
      if (spec.type === 'number' || spec.type === 'integer') {
        result[key] = Number(v);
      } else {
        result[key] = v;
      }
    }
    onSubmit(result);
  }, [fields, values, onSubmit]);

  if (fields.length === 0) {
    return (
      <div className="flex flex-col gap-4">
        <p className="text-xs text-temper-text-muted">
          This workflow has no input parameters.
        </p>
        <div className="flex justify-end gap-2">
          <Button size="sm" variant="outline" onClick={onCancel}>
            Cancel
          </Button>
          <Button size="sm" onClick={() => onSubmit({})} disabled={isSubmitting}>
            {isSubmitting ? 'Starting...' : 'Run'}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {fields.map(([key, spec]) => (
        <InputField
          key={key}
          name={key}
          spec={spec}
          value={values[key]}
          error={errors[key]}
          onChange={(v) => setValue(key, v)}
        />
      ))}
      <div className="flex justify-end gap-2 pt-2 border-t border-temper-border/50">
        <Button size="sm" variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        <Button size="sm" onClick={handleSubmit} disabled={isSubmitting}>
          {isSubmitting ? 'Starting...' : 'Run'}
        </Button>
      </div>
    </div>
  );
}

function InputField({
  name,
  spec,
  value,
  error,
  onChange,
}: {
  name: string;
  spec: InputSchema[string];
  value: unknown;
  error?: string;
  onChange: (value: unknown) => void;
}) {
  const label = `${name}${spec.required ? ' *' : ''}`;

  // Boolean → checkbox
  if (spec.type === 'boolean') {
    return (
      <div>
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={!!value}
            onChange={(e) => onChange(e.target.checked)}
            className="accent-temper-accent"
          />
          <span className="text-xs text-temper-text">{label}</span>
        </label>
        {spec.description && (
          <p className="text-[10px] text-temper-text-dim mt-0.5 ml-5">
            {spec.description}
          </p>
        )}
      </div>
    );
  }

  // String with options → select
  if (spec.options && spec.options.length > 0) {
    return (
      <div>
        <label className="text-[11px] font-medium text-temper-text-muted">
          {label}
        </label>
        {spec.description && (
          <p className="text-[10px] text-temper-text-dim mt-0.5">
            {spec.description}
          </p>
        )}
        <select
          className={`${selectClass} mt-1`}
          value={String(value ?? '')}
          onChange={(e) => onChange(e.target.value)}
        >
          {!spec.required && <option value="">-- Select --</option>}
          {spec.options.map((opt) => (
            <option key={opt} value={opt}>
              {opt}
            </option>
          ))}
        </select>
        {error && <p className="text-[10px] text-red-400 mt-0.5">{error}</p>}
      </div>
    );
  }

  // Number / integer → number input
  if (spec.type === 'number' || spec.type === 'integer') {
    return (
      <div>
        <label className="text-[11px] font-medium text-temper-text-muted">
          {label}
        </label>
        {spec.description && (
          <p className="text-[10px] text-temper-text-dim mt-0.5">
            {spec.description}
          </p>
        )}
        <input
          type="number"
          value={String(value ?? '')}
          onChange={(e) => onChange(e.target.value)}
          step={spec.type === 'integer' ? 1 : 'any'}
          className={`${inputClass} mt-1`}
        />
        {error && <p className="text-[10px] text-red-400 mt-0.5">{error}</p>}
      </div>
    );
  }

  // Default: string → text input
  return (
    <div>
      <label className="text-[11px] font-medium text-temper-text-muted">
        {label}
      </label>
      {spec.description && (
        <p className="text-[10px] text-temper-text-dim mt-0.5">
          {spec.description}
        </p>
      )}
      <input
        type="text"
        value={String(value ?? '')}
        onChange={(e) => onChange(e.target.value)}
        className={`${inputClass} mt-1`}
        placeholder={spec.description}
      />
      {error && <p className="text-[10px] text-red-400 mt-0.5">{error}</p>}
    </div>
  );
}
