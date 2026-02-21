/**
 * Shared UI primitives for Studio property panels.
 * Extracted from StagePropertiesPanel and WorkflowPropertiesPanel.
 */
import { useState, type ReactNode } from 'react';

/** Collapsible section with optional badge. */
export function Section({
  title,
  badge,
  defaultOpen = true,
  children,
}: {
  title: string;
  badge?: string;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);

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
