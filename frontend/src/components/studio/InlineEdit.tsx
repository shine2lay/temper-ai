/**
 * Click-to-edit primitives for inline editing on the canvas overlay.
 * InlineEdit: text/number input, InlineSelect: dropdown.
 */
import { useState, useRef, useEffect, useCallback } from 'react';

const readClass =
  'text-xs text-temper-text cursor-pointer border-b border-transparent hover:border-dashed hover:border-temper-accent/40 transition-colors';
const inputClass =
  'text-xs bg-temper-surface border border-temper-accent/60 rounded px-1.5 py-0.5 text-temper-text outline-none';

/* ---------- InlineEdit ---------- */

interface InlineEditProps {
  value: string | number | null;
  onChange: (value: string | number | null) => void;
  type?: 'text' | 'number' | 'textarea';
  tooltip?: string;
  placeholder?: string;
  emptyLabel?: string;
  className?: string;
  min?: number;
  max?: number;
  step?: number;
  /** When true, display as read-only text with dimmed styling (no click-to-edit). */
  readOnly?: boolean;
}

export function InlineEdit({
  value,
  onChange,
  type = 'text',
  tooltip,
  placeholder,
  emptyLabel = 'click to edit',
  className,
  min,
  max,
  step,
  readOnly,
}: InlineEditProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement>(null);

  const startEdit = useCallback(() => {
    if (readOnly) return;
    setDraft(value != null ? String(value) : '');
    setEditing(true);
  }, [value, readOnly]);

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editing]);

  const commit = useCallback(() => {
    setEditing(false);
    if (type === 'number') {
      const trimmed = draft.trim();
      onChange(trimmed === '' ? null : Number(trimmed));
    } else {
      onChange(draft);
    }
  }, [draft, onChange, type]);

  const cancel = useCallback(() => {
    setEditing(false);
  }, []);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && type !== 'textarea') {
        e.preventDefault();
        commit();
      } else if (e.key === 'Escape') {
        e.preventDefault();
        cancel();
      }
    },
    [commit, cancel, type],
  );

  const handleReadKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        startEdit();
      }
    },
    [startEdit],
  );

  if (!editing) {
    const isEmpty = value == null || value === '';
    const roClass = readOnly ? 'text-xs text-temper-text-dim cursor-default opacity-60' : readClass;
    return (
      <span
        role={readOnly ? undefined : 'button'}
        tabIndex={readOnly ? undefined : 0}
        className={`${roClass} ${className ?? ''}`}
        onClick={readOnly ? undefined : startEdit}
        onKeyDown={readOnly ? undefined : handleReadKeyDown}
        title={tooltip}
        aria-label={tooltip ? `Edit ${tooltip}` : undefined}
      >
        {isEmpty ? (
          <span className="italic text-temper-text-dim">{emptyLabel}</span>
        ) : (
          String(value)
        )}
      </span>
    );
  }

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setDraft(e.target.value);

  if (type === 'textarea') {
    return (
      <textarea
        ref={inputRef as React.RefObject<HTMLTextAreaElement>}
        value={draft}
        onChange={handleChange}
        onBlur={commit}
        onKeyDown={handleKeyDown}
        className={`${inputClass} ${className ?? ''} resize-y min-h-[36px] w-full`}
        placeholder={placeholder}
        rows={2}
      />
    );
  }

  return (
    <input
      ref={inputRef as React.RefObject<HTMLInputElement>}
      value={draft}
      onChange={handleChange}
      onBlur={commit}
      onKeyDown={handleKeyDown}
      className={`${inputClass} ${className ?? ''}`}
      placeholder={placeholder}
      type={type}
      min={min}
      max={max}
      step={step}
    />
  );
}

/* ---------- InlineToggle ---------- */

interface InlineToggleProps {
  value: boolean;
  onChange: (value: boolean) => void;
  tooltip?: string;
  className?: string;
  /** When true, display as read-only text with dimmed styling. */
  readOnly?: boolean;
}

export function InlineToggle({ value, onChange, tooltip, className, readOnly }: InlineToggleProps) {
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (readOnly) return;
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        onChange(!value);
      }
    },
    [value, onChange, readOnly],
  );

  const roClass = readOnly ? 'text-xs text-temper-text-dim cursor-default opacity-60' : readClass;

  return (
    <span
      role="switch"
      tabIndex={readOnly ? undefined : 0}
      aria-checked={value}
      className={`${roClass} ${className ?? ''} select-none ${value ? 'text-temper-accent' : 'text-temper-text-dim'}`}
      onClick={readOnly ? undefined : () => onChange(!value)}
      onKeyDown={readOnly ? undefined : handleKeyDown}
      title={tooltip}
    >
      {value ? 'on' : 'off'}
    </span>
  );
}

/* ---------- InlineSelect ---------- */

interface InlineSelectProps {
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
  tooltip?: string;
  className?: string;
  /** When true, display as read-only text with dimmed styling (no click-to-edit). */
  readOnly?: boolean;
}

export function InlineSelect({
  value,
  options,
  onChange,
  tooltip,
  className,
  readOnly,
}: InlineSelectProps) {
  const [editing, setEditing] = useState(false);
  const selectRef = useRef<HTMLSelectElement>(null);

  const startEdit = useCallback(() => {
    if (readOnly) return;
    setEditing(true);
  }, [readOnly]);

  useEffect(() => {
    if (editing && selectRef.current) {
      selectRef.current.focus();
    }
  }, [editing]);

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLSelectElement>) => {
      onChange(e.target.value);
      setEditing(false);
    },
    [onChange],
  );

  const handleBlur = useCallback(() => {
    setEditing(false);
  }, []);

  const handleReadKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        startEdit();
      }
    },
    [startEdit],
  );

  const handleSelectKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        setEditing(false);
      }
    },
    [],
  );

  if (!editing) {
    const currentLabel =
      options.find((o) => o.value === value)?.label ?? value;
    const roClass = readOnly ? 'text-xs text-temper-text-dim cursor-default opacity-60' : readClass;
    return (
      <span
        role={readOnly ? undefined : 'button'}
        tabIndex={readOnly ? undefined : 0}
        className={`${roClass} ${className ?? ''} inline-flex items-center gap-0.5`}
        onClick={readOnly ? undefined : startEdit}
        onKeyDown={readOnly ? undefined : handleReadKeyDown}
        title={tooltip}
        aria-label={tooltip ? `Edit ${tooltip}` : undefined}
      >
        {currentLabel}
        {!readOnly && (
          <span className="text-[8px] text-temper-text-dim ml-0.5">{'\u25BE'}</span>
        )}
      </span>
    );
  }

  return (
    <select
      ref={selectRef}
      value={value}
      onChange={handleChange}
      onBlur={handleBlur}
      onKeyDown={handleSelectKeyDown}
      className={`${inputClass} ${className ?? ''}`}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}
