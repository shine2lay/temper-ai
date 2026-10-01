/**
 * The big view: one full-screen picture of whatever you clicked on the run
 * page — the run itself, a stage, an agent, a script agent, a model call, a
 * tool call. All six share this frame; `shape.ts` decides what fills it.
 *
 * The picture reads as one object:
 *
 *     ┌──────────────────────────────────────────────┐
 *     │ name · status · model · time · tokens · cost │  ← one thin line
 *     ├────────┬───────────────────────┬─────────────┤
 *     │ what   │   the thing itself    │  what came  │
 *     │ went → │   (folds: stream,     │  ← out      │
 *     │ in     │    config, prompt)    │             │
 *     ├────────┴───────────────────────┴─────────────┤
 *     │ everything that happened, in order           │
 *     └──────────────────────────────────────────────┘
 *
 * It is a Radix Dialog, which is what traps focus inside and closes on Escape
 * and on a click outside — no new dependency for any of that. Handing focus
 * back to the thing you clicked is ours: the run page clears the selection on
 * its own (the graph, the live panel, Escape), so the view can be taken away
 * before Radix gets to put focus back.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { Dialog } from 'radix-ui';
import { Layers } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useExecutionStore } from '@/store/executionStore';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { FactStrip } from './FactStrip';
import { SidePane } from './SidePane';
import { Fold } from './Fold';
import { Content } from './Content';
import { Timeline } from './Timeline';
import { buildShape, MISSING_LABEL } from './shape';
import { useShapeSources } from './useShapeSources';
import type { ViewShape } from './types';

export function BigView() {
  const selection = useExecutionStore((s) => s.selection);
  const clearSelection = useExecutionStore((s) => s.clearSelection);
  const sources = useShapeSources();

  const shape = useMemo(() => buildShape(selection, sources), [selection, sources]);

  const open = selection !== null;

  // Remember what had focus when the view opened, and give it back after.
  const opener = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (open) {
      const active = document.activeElement;
      if (active instanceof HTMLElement && active !== document.body) opener.current = active;
      return;
    }
    const back = opener.current;
    opener.current = null;
    if (back && back.isConnected) {
      // After the closing animation, so the page is not scrolled mid-flight.
      requestAnimationFrame(() => back.isConnected && back.focus());
    }
  }, [open]);

  return (
    <Dialog.Root open={open} onOpenChange={(next) => !next && clearSelection()}>
      <Dialog.Portal>
        <Dialog.Overlay className="bv-veil fixed inset-0 z-50 bg-black/60 backdrop-blur-sm" />
        <Dialog.Content
          data-testid="big-view"
          data-kind={shape?.kind}
          data-subject={shape?.id}
          aria-describedby={undefined}
          className={cn(
            'bv-view fixed left-1/2 top-1/2 z-50 flex -translate-x-1/2 -translate-y-1/2 flex-col',
            // At least 80% of the screen on a desktop, all of it on a phone.
            'h-full w-full overflow-hidden border-temper-border bg-temper-bg',
            'md:h-[92vh] md:w-[94vw] md:rounded-2xl md:border md:shadow-2xl',
          )}
        >
          {shape ? (
            <>
              <Dialog.Title className="sr-only">
                {shape.kindLabel}: {shape.title}
              </Dialog.Title>
              <Body shape={shape} onClose={clearSelection} />
            </>
          ) : (
            <>
              <Dialog.Title className="sr-only">Nothing to show</Dialog.Title>
              <Missing kind={selection?.type} onClose={clearSelection} />
            </>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function Body({ shape, onClose }: { shape: ViewShape; onClose: () => void }) {
  const [inOpen, setInOpen] = useState(false);
  const [outOpen, setOutOpen] = useState(false);

  // A new subject closes both arrows, so the frame never carries one
  // thing's open panes over to the next.
  const [seen, setSeen] = useState(shape.id);
  if (seen !== shape.id) {
    setSeen(shape.id);
    setInOpen(false);
    setOutOpen(false);
  }

  const columns = inOpen
    ? outOpen
      ? 'md:grid-cols-[1fr_1.1fr_1fr]'
      : 'md:grid-cols-[1fr_1.4fr_2.75rem]'
    : outOpen
      ? 'md:grid-cols-[2.75rem_1.4fr_1fr]'
      : 'md:grid-cols-[2.75rem_1fr_2.75rem]';

  return (
    <>
      <FactStrip shape={shape} onClose={onClose} />

      <div className="min-h-0 flex-1 overflow-auto">
        {shape.note && (
          <p data-testid="bv-note" className="border-b border-temper-border/40 bg-temper-panel/40 px-3 py-1.5 text-[11px] text-temper-text-dim">
            {shape.note}
          </p>
        )}
        {shape.error && (
          <p
            data-testid="bv-error"
            className="m-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400"
          >
            {shape.error}
          </p>
        )}

        <div
          data-testid="bv-middle"
          className={cn('grid min-h-0 gap-3 p-3 transition-[grid-template-columns] duration-300', columns)}
        >
          <SidePane
            side="in"
            label={shape.in.label}
            value={shape.in.value}
            open={inOpen}
            onToggle={setInOpen}
          />

          <section
            data-testid="bv-box"
            className="flex min-w-0 flex-col gap-2 rounded-xl border border-temper-border bg-temper-panel/30 p-3"
          >
            <CoreHeader shape={shape} />
            {shape.core.map((block) => (
              <Fold
                key={block.key}
                testId={`bv-fold-${block.key}`}
                title={block.title}
                badge={block.badge}
                defaultOpen={block.defaultOpen}
              >
                <Content value={block.value} />
              </Fold>
            ))}
            {shape.core.length === 0 && (
              <p className="py-6 text-center text-xs text-temper-text-dim">Nothing recorded for this one.</p>
            )}
            <Relations shape={shape} />
          </section>

          <SidePane
            side="out"
            label={shape.out.label}
            value={shape.out.value}
            open={outOpen}
            onToggle={setOutOpen}
          />
        </div>

        {shape.timeline && (
          <section data-testid="bv-timeline-section" className="border-t border-temper-border/60 p-3">
            <h3 className="mb-2 flex items-center gap-2 text-[11px] font-medium uppercase tracking-wide text-temper-text-muted">
              What happened
              {shape.timeline.length > 0 && (
                <span className="rounded bg-temper-surface px-1.5 py-0.5 font-mono text-[10px]">
                  {shape.timeline.length}
                </span>
              )}
            </h3>
            <Timeline rows={shape.timeline} subjectId={shape.id} />
          </section>
        )}
      </div>
    </>
  );
}

function CoreHeader({ shape }: { shape: ViewShape }) {
  return (
    <div className="flex items-center gap-2 pb-1">
      <Layers aria-hidden className="size-3.5 text-temper-text-dim" />
      <span className="text-[10px] font-medium uppercase tracking-wide text-temper-text-muted">
        {shape.kindLabel}
      </span>
    </div>
  );
}

/** Its other rounds, and what sits inside it. */
function Relations({ shape }: { shape: ViewShape }) {
  const hasSiblings = shape.siblings.length > 0;
  const hasChildren = shape.children.items.length > 0;
  if (!hasSiblings && !hasChildren) return null;

  return (
    <div className="flex flex-col gap-2">
      {hasSiblings && (
        <Fold testId="bv-fold-siblings" title="Its other rounds" badge={String(shape.siblings.length)}>
          <Content value={{ kind: 'widget', name: 'links', data: shape.siblings }} />
        </Fold>
      )}
      {hasChildren && (
        <Fold
          testId="bv-fold-children"
          title={shape.children.label}
          badge={String(shape.children.items.length)}
        >
          <Content value={{ kind: 'widget', name: 'links', data: shape.children.items }} />
        </Fold>
      )}
    </div>
  );
}

function Missing({ kind, onClose }: { kind?: string; onClose: () => void }) {
  return (
    <div data-testid="bv-missing" className="flex h-full flex-col items-center justify-center gap-3 p-6">
      <StatusBadge status="pending" />
      <p className="text-sm text-temper-text-muted">
        {kind ? MISSING_LABEL[kind as keyof typeof MISSING_LABEL] : 'Nothing to show.'}
      </p>
      <button
        type="button"
        onClick={onClose}
        className="rounded-md border border-temper-border px-3 py-1.5 text-xs text-temper-text-muted transition-colors hover:text-temper-text"
      >
        Close
      </button>
    </div>
  );
}
