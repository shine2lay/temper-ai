/**
 * Shared UI primitives for Studio property panels.
 * Used by WorkflowSettingsOverlay, StagePropertiesPanel, and AgentPropertiesPanel.
 */
import { useState, useEffect, type ReactNode } from 'react';

/* ========== Legacy Section (used by older panel code) ========== */

/** Collapsible section with optional badge. */
export function Section({
  title,
  badge,
  defaultOpen = true,
  expandSignal,
  children,
}: {
  title: string;
  badge?: string;
  defaultOpen?: boolean;
  /** When non-zero and changes: positive -> expand, negative -> collapse. */
  expandSignal?: number;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);

  useEffect(() => {
    if (expandSignal != null && expandSignal !== 0) {
      setOpen(expandSignal > 0);
    }
  }, [expandSignal]);

  return (
    <div className="border-b border-temper-border/50">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 w-full px-3 py-2 text-left hover:bg-temper-surface/30 transition-colors"
      >
        <span className="text-[10px] text-temper-text-dim">
          {open ? '\u25BC' : '\u25B6'}
        </span>
        <span className="text-xs font-semibold text-temper-text">{title}</span>
        {badge && (
          <span className="ml-auto text-[10px] text-temper-text-dim">{badge}</span>
        )}
      </button>
      {open && <div className="px-3 pb-3 flex flex-col gap-3">{children}</div>}
    </div>
  );
}

/** Labeled form field with optional hint text. */
export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div>
      <label className="text-[11px] font-medium text-temper-text-muted">{label}</label>
      {hint && <p className="text-[10px] text-temper-text-dim mt-0.5">{hint}</p>}
      <div className="mt-1">{children}</div>
    </div>
  );
}

/** Standard text input styling for Studio panels. */
export const inputClass =
  'w-full px-2 py-1.5 text-xs bg-temper-surface border border-temper-border rounded text-temper-text';

/** Standard select styling for Studio panels. */
export const selectClass =
  'w-full px-2 py-1.5 text-xs bg-temper-surface border border-temper-border rounded text-temper-text';

/** Standard textarea styling for Studio panels. */
export const textareaClass =
  'w-full px-2 py-1.5 text-xs bg-temper-surface border border-temper-border rounded text-temper-text resize-y min-h-[48px]';

/** Standard checkbox styling. */
export function Checkbox({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2 cursor-pointer">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="accent-temper-accent"
      />
      <span className="text-xs text-temper-text">{label}</span>
    </label>
  );
}

/* ========== Inline-edit shared primitives ========== */

/** CSS class constant for section headers. */
export const sectionHeaderClass =
  'text-[10px] font-semibold text-temper-text-muted uppercase tracking-wider mb-1.5';

/** Small ? circle with hover popup tooltip — used on section headers. */
export function InfoTooltip({ text }: { text: string }) {
  return (
    <span className="relative group/tip inline-flex ml-1">
      <span className="w-3 h-3 inline-flex items-center justify-center rounded-full border border-temper-text-dim/40 text-[7px] text-temper-text-dim cursor-help leading-none">
        ?
      </span>
      <span className="pointer-events-none absolute left-0 top-full mt-1 z-50 w-56 rounded border border-temper-border bg-temper-panel px-2.5 py-2 text-[10px] leading-relaxed text-temper-text normal-case font-normal tracking-normal shadow-lg opacity-0 group-hover/tip:opacity-100 transition-opacity whitespace-pre-line">
        {text}
      </span>
    </span>
  );
}

/** Section header with title + optional tooltip. */
export function SectionHeader({ title, tooltip }: { title: string; tooltip?: string }) {
  return (
    <div className={`${sectionHeaderClass} flex items-center`}>
      {title}
      {tooltip && <InfoTooltip text={tooltip} />}
    </div>
  );
}

/** Collapsible section with arrow toggle + optional tooltip. */
export function CollapsibleSection({
  title,
  tooltip,
  children,
  defaultOpen = false,
}: {
  title: string;
  tooltip?: string;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border-b border-temper-border/30">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full px-3 py-1.5 flex items-center gap-1 text-[10px] font-semibold text-temper-text-muted uppercase tracking-wider hover:text-temper-text hover:bg-temper-surface/30 transition-colors cursor-pointer select-none"
      >
        <span className="text-[8px]">{open ? '\u25BE' : '\u25B8'}</span>
        {title}
        {tooltip && <InfoTooltip text={tooltip} />}
      </button>
      {open && <div className="px-3 pb-2">{children}</div>}
    </div>
  );
}

/** Tiny ? tooltip next to individual field labels. */
export function FieldTip({ text }: { text: string }) {
  return (
    <span className="relative group/ftip inline-flex">
      <span className="w-2.5 h-2.5 inline-flex items-center justify-center rounded-full text-[6px] text-temper-text-dim/60 border border-temper-text-dim/30 cursor-help leading-none">?</span>
      <span className="pointer-events-none absolute left-full top-1/2 -translate-y-1/2 ml-1.5 z-50 w-52 rounded border border-temper-border bg-temper-panel px-2 py-1.5 text-[10px] leading-relaxed text-temper-text normal-case font-normal tracking-normal shadow-lg opacity-0 group-hover/ftip:opacity-100 transition-opacity whitespace-pre-line">
        {text}
      </span>
    </span>
  );
}

/** Label: [control] row with optional per-field tooltip. */
export function ExpandedField({
  label,
  tip,
  children,
  labelWidth,
}: {
  label: string;
  tip?: string;
  children: ReactNode;
  /** Tailwind width class for label column (default w-16). */
  labelWidth?: string;
}) {
  return (
    <div className="flex items-start gap-2 mb-1.5">
      <span className={`text-[10px] text-temper-text-dim ${labelWidth ?? 'w-16'} shrink-0 pt-0.5 flex items-center gap-0.5`}>
        {label}:
        {tip && <FieldTip text={tip} />}
      </span>
      <div className="flex-1 flex items-center gap-0 flex-wrap">{children}</div>
    </div>
  );
}

/* ========== Array, Outputs, and Key-Value editors ========== */

/** Inline chip-style string[] editor. */
export function CompactArrayEditor({
  values,
  onChange,
  placeholder,
}: {
  values: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1">
      {values.map((v, i) => (
        <span
          key={i}
          className="inline-flex items-center gap-0.5 px-1.5 py-0.5 text-[10px] bg-temper-surface border border-temper-border/50 rounded text-temper-text"
        >
          <input
            type="text"
            value={v}
            onChange={(e) => {
              const next = [...values];
              next[i] = e.target.value;
              onChange(next);
            }}
            className="bg-transparent outline-none w-20 text-[10px]"
            placeholder={placeholder}
          />
          <button
            onClick={() => onChange(values.filter((_, j) => j !== i))}
            className="text-[10px] text-red-400 hover:text-red-300"
          >
            &times;
          </button>
        </span>
      ))}
      <button
        onClick={() => onChange([...values, ''])}
        className="text-[9px] text-temper-accent hover:underline"
      >
        + Add
      </button>
    </div>
  );
}

/** Name <- source pair editor for workflow outputs. */
export function CompactOutputsEditor({
  outputs,
  onChange,
}: {
  outputs: { name: string; description: string; source: string }[];
  onChange: (outputs: { name: string; description: string; source: string }[]) => void;
}) {
  return (
    <div className="flex flex-col gap-1 w-full">
      {outputs.map((o, i) => (
        <div
          key={i}
          className="flex items-center gap-1 p-1 bg-temper-surface/50 rounded border border-temper-border/50"
        >
          <input
            type="text"
            value={o.name}
            onChange={(e) => {
              const next = [...outputs];
              next[i] = { ...next[i], name: e.target.value };
              onChange(next);
            }}
            className="flex-1 px-1.5 py-0.5 text-[10px] bg-temper-surface border border-temper-border rounded text-temper-text"
            placeholder="name"
          />
          <span className="text-[8px] text-temper-text-dim">{'\u2190'}</span>
          <input
            type="text"
            value={o.source}
            onChange={(e) => {
              const next = [...outputs];
              next[i] = { ...next[i], source: e.target.value };
              onChange(next);
            }}
            className="flex-1 px-1.5 py-0.5 text-[10px] bg-temper-surface border border-temper-border rounded text-temper-text-muted"
            placeholder="stage.output"
          />
          <button
            onClick={() => onChange(outputs.filter((_, j) => j !== i))}
            className="text-[10px] text-red-400 hover:text-red-300 px-0.5 shrink-0"
          >
            &times;
          </button>
        </div>
      ))}
      <button
        onClick={() => onChange([...outputs, { name: '', description: '', source: '' }])}
        className="text-[9px] text-temper-accent hover:underline self-start"
      >
        + Add output
      </button>
    </div>
  );
}

/** Generic Record<string, string> key-value pair editor. */
export function CompactKeyValueEditor({
  entries,
  onChange,
  keyPlaceholder = 'key',
  valuePlaceholder = 'value',
  readOnlyKeys = false,
}: {
  entries: Record<string, string>;
  onChange: (entries: Record<string, string>) => void;
  keyPlaceholder?: string;
  valuePlaceholder?: string;
  readOnlyKeys?: boolean;
}) {
  const pairs = Object.entries(entries);

  return (
    <div className="flex flex-col gap-1 w-full">
      {pairs.map(([k, v]) => (
        <div
          key={k}
          className="flex items-center gap-1 p-1 bg-temper-surface/50 rounded border border-temper-border/50"
        >
          <input
            type="text"
            value={k}
            readOnly={readOnlyKeys}
            onChange={(e) => {
              if (readOnlyKeys) return;
              const newKey = e.target.value;
              const next: Record<string, string> = {};
              for (const [ek, ev] of pairs) {
                next[ek === k ? newKey : ek] = ev;
              }
              onChange(next);
            }}
            className={`w-24 px-1.5 py-0.5 text-[10px] bg-temper-surface border border-temper-border rounded text-temper-text ${readOnlyKeys ? 'opacity-60' : ''}`}
            placeholder={keyPlaceholder}
          />
          <span className="text-[8px] text-temper-text-dim">:</span>
          <input
            type="text"
            value={v}
            onChange={(e) => {
              onChange({ ...entries, [k]: e.target.value });
            }}
            className="flex-1 px-1.5 py-0.5 text-[10px] bg-temper-surface border border-temper-border rounded text-temper-text"
            placeholder={valuePlaceholder}
          />
          <button
            onClick={() => {
              const next = { ...entries };
              delete next[k];
              onChange(next);
            }}
            className="text-[10px] text-red-400 hover:text-red-300 px-0.5 shrink-0"
          >
            &times;
          </button>
        </div>
      ))}
      <button
        onClick={() => {
          const newKey = `${keyPlaceholder}_${pairs.length}`;
          onChange({ ...entries, [newKey]: '' });
        }}
        className="text-[9px] text-temper-accent hover:underline self-start"
      >
        + Add
      </button>
    </div>
  );
}
