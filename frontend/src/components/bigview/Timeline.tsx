/**
 * Everything that happened, in the order it happened.
 *
 * Model calls and tool calls share one stream — there is no separate "LLM
 * Calls" and "Tool Calls" list any more — and a row opens in place to show
 * its own in and out.
 *
 * Two things keep it quick on a long run: a closed row derives nothing (the
 * panes are built only when it opens) and only a window of rows is mounted,
 * the same treatment the agent list got.
 */
import { useMemo, useState } from 'react';
import { Bot, Wrench, Sparkles, AlertTriangle } from 'lucide-react';
import { cn } from '@/lib/utils';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { useReducedMotion } from '@/hooks/useReducedMotion';
import { Content } from './Content';
import { rowPanes } from './shape';
import type { TimelineRow } from './types';

/** Rows mounted at once. A longer stream grows by this much per "show more". */
export const TIMELINE_PAGE = 40;
/** Rows past this one arrive together, so a long stream never stalls. */
const STAGGER_CAP = 12;

interface TimelineProps {
  rows: TimelineRow[];
  /** Resets which rows are open when the big view changes subject. */
  subjectId: string;
}

export function Timeline({ rows, subjectId }: TimelineProps) {
  const [shown, setShown] = useState(TIMELINE_PAGE);
  const [openRows, setOpenRows] = useState<Set<string>>(() => new Set());
  const still = useReducedMotion();

  // A new subject starts fresh: nothing open, back to the first page.
  const [seen, setSeen] = useState(subjectId);
  if (seen !== subjectId) {
    setSeen(subjectId);
    setShown(TIMELINE_PAGE);
    setOpenRows(new Set());
  }

  const visible = useMemo(() => rows.slice(0, shown), [rows, shown]);

  if (rows.length === 0) {
    return (
      <p data-testid="bv-timeline-empty" className="px-3 py-4 text-xs text-temper-text-dim">
        Nothing happened here yet.
      </p>
    );
  }

  const toggle = (id: string) => {
    setOpenRows((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div data-testid="bv-timeline" data-rows={rows.length} className="flex flex-col gap-1.5">
      {visible.map((row, i) => (
        <Row
          key={row.id}
          row={row}
          index={i}
          open={openRows.has(row.id)}
          onToggle={() => toggle(row.id)}
          still={still}
        />
      ))}

      {shown < rows.length && (
        <button
          type="button"
          data-testid="bv-timeline-more"
          onClick={() => setShown((n) => n + TIMELINE_PAGE)}
          className="rounded-md border border-dashed border-temper-border px-3 py-2 text-xs text-temper-text-muted transition-colors hover:border-temper-accent hover:text-temper-accent"
        >
          Show {Math.min(TIMELINE_PAGE, rows.length - shown)} more of {rows.length}
        </button>
      )}
    </div>
  );
}

function Row({
  row,
  index,
  open,
  onToggle,
  still,
}: {
  row: TimelineRow;
  index: number;
  open: boolean;
  onToggle: () => void;
  still: boolean;
}) {
  const Icon = row.type === 'llm' ? Bot : Wrench;
  // Only an open row is worth building panes for.
  const panes = useMemo(() => (open ? rowPanes(row) : null), [open, row]);

  return (
    <div
      data-testid="bv-row"
      data-row-type={row.type}
      data-open={open ? 'true' : 'false'}
      className={cn(
        'bv-row overflow-hidden rounded-lg border bg-temper-panel/40',
        row.type === 'llm' ? 'border-temper-accent/25' : 'border-amber-500/25',
        row.status === 'failed' && 'border-red-500/40',
      )}
      style={
        still ? undefined : ({ '--bv-row-delay': `${Math.min(index, STAGGER_CAP) * 18}ms` } as React.CSSProperties)
      }
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        data-testid="bv-row-trigger"
        className="flex w-full items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-temper-surface/50"
      >
        <span className="shrink-0 font-mono text-[10px] text-temper-text-dim">{index + 1}</span>
        <Icon
          aria-hidden
          className={cn('size-3.5 shrink-0', row.type === 'llm' ? 'text-temper-accent' : 'text-amber-500')}
        />
        <span className="min-w-0 flex-1 truncate text-xs text-temper-text">{row.title}</span>
        {row.thinking && <Sparkles aria-hidden className="size-3 shrink-0 text-violet-400" />}
        {row.error && <AlertTriangle aria-hidden className="size-3 shrink-0 text-red-400" />}
        {row.chips.map((chip) => (
          <span key={chip} className="hidden shrink-0 font-mono text-[10px] text-temper-text-dim sm:inline">
            {chip}
          </span>
        ))}
        <StatusBadge status={row.status} />
      </button>

      {open && panes && (
        <div data-testid="bv-row-body" className="border-t border-temper-border/40 p-3">
          {row.error && (
            <p className="mb-2 rounded-md border border-red-500/30 bg-red-500/10 px-2 py-1 text-xs text-red-400">
              {row.error}
            </p>
          )}
          <div className="grid gap-3 md:grid-cols-2">
            <section data-testid="bv-row-in" className="min-w-0 rounded-lg border border-sky-500/25 bg-sky-500/5 p-2">
              <h4 className="mb-1 text-[10px] font-medium uppercase tracking-wide text-sky-400">{panes.in.label}</h4>
              <Content value={panes.in.value} maxHeight={320} />
            </section>
            <section
              data-testid="bv-row-out"
              className="min-w-0 rounded-lg border border-emerald-500/25 bg-emerald-500/5 p-2"
            >
              <h4 className="mb-1 text-[10px] font-medium uppercase tracking-wide text-emerald-400">
                {panes.out.label}
              </h4>
              <Content value={panes.out.value} maxHeight={320} />
            </section>
          </div>
          {panes.thinking && (
            <div className="mt-3" data-testid="bv-row-thinking">
              <Content value={{ kind: 'thinking', text: panes.thinking }} maxHeight={320} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
