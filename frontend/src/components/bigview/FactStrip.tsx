/**
 * The thin line of facts across the top: name, status, model, how long,
 * tokens, cost, which stage it belongs to, and a way back to its parent.
 *
 * It is deliberately one line that scrolls sideways rather than wrapping —
 * a strip that grows into a block is the thing the old sheet did wrong.
 */
import { ArrowUpLeft, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { StatusBadge } from '@/components/shared/StatusBadge';
import type { Fact as ShapeFact, ShapeLink, ViewShape } from './types';

interface FactStripProps {
  shape: ViewShape;
  onClose: () => void;
}

export function FactStrip({ shape, onClose }: FactStripProps) {
  return (
    <header
      data-testid="bv-strip"
      className="flex h-11 shrink-0 items-center gap-3 border-b border-temper-border bg-temper-panel/80 px-3 backdrop-blur"
    >
      {shape.parent && <ParentLink link={shape.parent} />}

      <h2
        data-testid="bv-title"
        className="min-w-0 shrink truncate text-sm font-semibold text-temper-text"
        title={shape.title}
      >
        {shape.title}
      </h2>

      {shape.status && (
        <span data-testid="bv-status" className="shrink-0">
          <StatusBadge status={shape.status} />
        </span>
      )}

      <div
        data-testid="bv-facts"
        className="flex min-w-0 flex-1 items-center gap-3 overflow-x-auto whitespace-nowrap [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
      >
        {shape.facts.map((fact) => (
          <Fact key={fact.label} fact={fact} />
        ))}
      </div>

      <button
        type="button"
        onClick={onClose}
        aria-label="Close"
        data-testid="bv-close"
        className="shrink-0 rounded-md p-1.5 text-temper-text-muted transition-colors hover:bg-temper-surface hover:text-temper-text"
      >
        <X className="size-4" />
      </button>
    </header>
  );
}

function Fact({ fact }: { fact: ShapeFact }) {
  return (
    <span className="flex shrink-0 items-baseline gap-1 text-xs" title={fact.title ?? `${fact.label}: ${fact.value}`}>
      <span className="text-[10px] uppercase tracking-wide text-temper-text-dim">{fact.label}</span>
      <span
        className={cn(
          'font-mono text-temper-text-muted',
          fact.tone === 'accent' && 'text-temper-accent',
          fact.tone === 'warn' && 'text-amber-400',
          fact.tone === 'danger' && 'text-red-400',
          fact.tone === 'money' && 'text-emerald-400',
        )}
      >
        {fact.value}
      </span>
    </span>
  );
}

function ParentLink({ link }: { link: ShapeLink }) {
  return (
    <button
      type="button"
      onClick={link.open}
      data-testid="bv-parent"
      title={`Back to ${link.label}`}
      className="flex shrink-0 items-center gap-1 rounded-md px-1.5 py-1 text-xs text-temper-text-muted transition-colors hover:bg-temper-surface hover:text-temper-text"
    >
      <ArrowUpLeft className="size-3.5" />
      <span className="max-w-32 truncate">{link.label}</span>
    </button>
  );
}
