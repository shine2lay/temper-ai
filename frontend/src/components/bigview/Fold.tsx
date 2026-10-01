/**
 * One fold: a title you click, and the thing itself underneath.
 *
 * Built on Radix Collapsible, so a closed fold renders nothing at all — that
 * is what keeps an agent with fifty calls instant — and the open/close
 * movement is the shared `.bv-fold` animation.
 */
import { useState, type ReactNode } from 'react';
import { ChevronRight } from 'lucide-react';
import { Collapsible as CollapsiblePrimitive } from 'radix-ui';
import { cn } from '@/lib/utils';

interface FoldProps {
  title: ReactNode;
  badge?: ReactNode;
  defaultOpen?: boolean;
  /** Lets a parent drive the fold (the timeline opens rows from outside). */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  testId?: string;
  className?: string;
  tone?: 'plain' | 'in' | 'out';
  children: ReactNode;
}

const TONES = {
  plain: 'border-temper-border/60 hover:bg-temper-surface/60',
  in: 'border-sky-500/30 hover:bg-sky-500/10',
  out: 'border-emerald-500/30 hover:bg-emerald-500/10',
} as const;

export function Fold({
  title,
  badge,
  defaultOpen = false,
  open,
  onOpenChange,
  testId,
  className,
  tone = 'plain',
  children,
}: FoldProps) {
  const [ownOpen, setOwnOpen] = useState(defaultOpen);
  const isOpen = open ?? ownOpen;
  const setOpen = (next: boolean) => {
    if (open === undefined) setOwnOpen(next);
    onOpenChange?.(next);
  };

  return (
    <CollapsiblePrimitive.Root
      open={isOpen}
      onOpenChange={setOpen}
      data-testid={testId}
      data-open={isOpen ? 'true' : 'false'}
      className={cn('overflow-hidden rounded-lg border bg-temper-panel/40', TONES[tone], className)}
    >
      <CollapsiblePrimitive.Trigger
        data-testid={testId ? `${testId}-trigger` : undefined}
        className="flex w-full items-center gap-2 px-3 py-2 text-left transition-colors"
      >
        <ChevronRight
          aria-hidden
          className={cn(
            'size-3.5 shrink-0 text-temper-text-dim transition-transform duration-200',
            isOpen && 'rotate-90',
          )}
        />
        <span className="min-w-0 flex-1 truncate text-xs font-medium text-temper-text">{title}</span>
        {badge != null && (
          <span className="shrink-0 rounded bg-temper-surface px-1.5 py-0.5 font-mono text-[10px] text-temper-text-muted">
            {badge}
          </span>
        )}
      </CollapsiblePrimitive.Trigger>
      <CollapsiblePrimitive.Content className="bv-fold overflow-hidden">
        <div className="border-t border-temper-border/40 p-3">{children}</div>
      </CollapsiblePrimitive.Content>
    </CollapsiblePrimitive.Root>
  );
}
