/**
 * Workflow-level property form for the Studio editor.
 * Shown in the right panel when no stage is selected.
 * Organized into collapsible sections: General, Execution, Safety, I/O.
 */
import { useDesignStore, type WorkflowMeta, type WorkflowOutput } from '@/store/designStore';
import { Section, Field } from './shared';

function ArrayEditor({
  label,
  hint,
  values,
  onChange,
  placeholder,
}: {
  label: string;
  hint?: string;
  values: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
}) {
  return (
    <Field label={label} hint={hint}>
      <div className="flex flex-col gap-1">
        {values.map((v, i) => (
          <div key={i} className="flex items-center gap-1">
            <input
              type="text"
              value={v}
              onChange={(e) => {
                const next = [...values];
                next[i] = e.target.value;
                onChange(next);
              }}
              className="flex-1 px-2 py-1 text-xs bg-temper-surface border border-temper-border rounded text-temper-text"
              placeholder={placeholder}
            />
            <button
              onClick={() => onChange(values.filter((_, j) => j !== i))}
              className="text-xs text-red-400 hover:text-red-300 px-1"
              aria-label={`Remove ${v}`}
            >
              &times;
            </button>
          </div>
        ))}
        <button
          onClick={() => onChange([...values, ''])}
          className="text-[10px] text-temper-accent hover:underline self-start"
        >
          + Add
        </button>
      </div>
    </Field>
  );
}

function OutputsEditor({
  outputs,
  onChange,
}: {
  outputs: WorkflowOutput[];
  onChange: (outputs: WorkflowOutput[]) => void;
}) {
  return (
    <Field
      label="Outputs"
      hint="Values the workflow produces when complete"
    >
      <div className="flex flex-col gap-1.5">
        {outputs.map((o, i) => (
          <div key={i} className="flex flex-col gap-0.5 p-1.5 bg-temper-surface/50 rounded border border-temper-border/50">
            <div className="flex items-center gap-1">
              <input
                type="text"
                value={o.name}
                onChange={(e) => {
                  const next = [...outputs];
                  next[i] = { ...next[i], name: e.target.value };
                  onChange(next);
                }}
                className="flex-1 px-2 py-1 text-xs bg-temper-surface border border-temper-border rounded text-temper-text"
                placeholder="Output name"
              />
              <button
                onClick={() => onChange(outputs.filter((_, j) => j !== i))}
                className="text-xs text-red-400 hover:text-red-300 px-1"
                aria-label={`Remove output ${o.name}`}
              >
                &times;
              </button>
            </div>
            <input
              type="text"
              value={o.source}
              onChange={(e) => {
                const next = [...outputs];
                next[i] = { ...next[i], source: e.target.value };
                onChange(next);
              }}
              className="px-2 py-1 text-[10px] bg-temper-surface border border-temper-border rounded text-temper-text-muted"
              placeholder="Source (e.g., stage_name.output_key)"
            />
          </div>
        ))}
        <button
          onClick={() => onChange([...outputs, { name: '', description: '', source: '' }])}
          className="text-[10px] text-temper-accent hover:underline self-start"
        >
          + Add
        </button>
      </div>
    </Field>
  );
}

/* ---------- Main panel ---------- */

export function WorkflowPropertiesPanel() {
  const meta = useDesignStore((s) => s.meta);
  const setMeta = useDesignStore((s) => s.setMeta);
  const stages = useDesignStore((s) => s.stages);

  return (
    <div className="flex flex-col">
      {/* Header */}
      <div className="px-3 py-2 border-b border-temper-border">
        <h3 className="text-xs font-semibold text-temper-text">Workflow Properties</h3>
        {stages.length > 0 && (
          <p className="text-[10px] text-temper-text-dim mt-0.5">
            {stages.length} stage{stages.length !== 1 ? 's' : ''}
            {meta.description && ` \u2014 ${meta.description.slice(0, 50)}${meta.description.length > 50 ? '...' : ''}`}
          </p>
        )}
      </div>

      {/* General */}
      <Section title="General" defaultOpen={true}>
        <Field label="Name">
          <input
            type="text"
            value={meta.name}
            onChange={(e) => setMeta({ name: e.target.value })}
            className="w-full px-2 py-1.5 text-sm bg-temper-surface border border-temper-border rounded text-temper-text"
            placeholder="my_workflow"
          />
        </Field>
        <Field label="Description">
          <textarea
            value={meta.description}
            onChange={(e) => setMeta({ description: e.target.value })}
            className="w-full px-2 py-1.5 text-xs bg-temper-surface border border-temper-border rounded text-temper-text resize-y min-h-[48px]"
            placeholder="What does this workflow do?"
            rows={2}
          />
        </Field>
      </Section>

      {/* Execution */}
      <Section title="Execution" defaultOpen={false}>
        <Field
          label="Timeout"
          hint="Max seconds before the workflow is stopped"
        >
          <div className="flex items-center gap-2">
            <input
              type="number"
              value={meta.timeout_seconds}
              onChange={(e) => setMeta({ timeout_seconds: Number(e.target.value) || 0 })}
              className="w-24 px-2 py-1.5 text-xs bg-temper-surface border border-temper-border rounded text-temper-text"
              min={0}
            />
            <span className="text-[10px] text-temper-text-dim">seconds</span>
          </div>
        </Field>
        <Field
          label="Cost Limit"
          hint="Max LLM spend before halting (optional)"
        >
          <div className="flex items-center gap-2">
            <span className="text-xs text-temper-text-dim">$</span>
            <input
              type="number"
              value={meta.max_cost_usd ?? ''}
              onChange={(e) =>
                setMeta({ max_cost_usd: e.target.value ? Number(e.target.value) : null })
              }
              className="w-24 px-2 py-1.5 text-xs bg-temper-surface border border-temper-border rounded text-temper-text"
              placeholder="No limit"
              min={0}
              step={0.01}
            />
          </div>
        </Field>
        <Field
          label="On Stage Failure"
          hint="What happens if a stage fails"
        >
          <select
            value={meta.on_stage_failure}
            onChange={(e) =>
              setMeta({ on_stage_failure: e.target.value as WorkflowMeta['on_stage_failure'] })
            }
            className="w-full px-2 py-1.5 text-xs bg-temper-surface border border-temper-border rounded text-temper-text"
          >
            <option value="halt">Halt workflow</option>
            <option value="continue">Continue to next stage</option>
            <option value="skip">Skip failed stage</option>
          </select>
        </Field>
      </Section>

      {/* Safety */}
      <Section title="Safety" defaultOpen={false}>
        <Field
          label="Safety Mode"
          hint="Controls how agent actions are verified"
        >
          <select
            value={meta.global_safety_mode}
            onChange={(e) =>
              setMeta({ global_safety_mode: e.target.value as WorkflowMeta['global_safety_mode'] })
            }
            className="w-full px-2 py-1.5 text-xs bg-temper-surface border border-temper-border rounded text-temper-text"
          >
            <option value="execute">Execute — agents run actions directly</option>
            <option value="monitor">Monitor — log actions but still execute</option>
            <option value="audit">Audit — require approval before actions</option>
          </select>
        </Field>
      </Section>

      {/* I/O */}
      <Section title="Inputs / Outputs" defaultOpen={true}>
        <ArrayEditor
          label="Required Inputs"
          hint="Values that must be provided when the workflow starts"
          values={meta.required_inputs}
          onChange={(v) => setMeta({ required_inputs: v })}
          placeholder="e.g., user_prompt"
        />
        <ArrayEditor
          label="Optional Inputs"
          hint="Values that may be provided"
          values={meta.optional_inputs}
          onChange={(v) => setMeta({ optional_inputs: v })}
          placeholder="e.g., context"
        />
        <OutputsEditor
          outputs={meta.outputs}
          onChange={(v) => setMeta({ outputs: v })}
        />
      </Section>
    </div>
  );
}
