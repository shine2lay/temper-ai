/**
 * One of the two arrows beside the middle box.
 *
 * Closed, it is a thin rail with an arrow pointing into the box, so the
 * picture reads left-to-right: what went in → the thing itself → what came
 * out. Opened, the rail becomes a column holding the content.
 *
 * On a phone there is no room for three columns, so the rail lies flat above
 * and below the box instead; it is the same component either way.
 */
import { ArrowLeft, ArrowRight } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Content } from './Content';
import type { ContentValue } from './types';

interface SidePaneProps {
  side: 'in' | 'out';
  label: string;
  value: ContentValue;
  open: boolean;
  onToggle: (open: boolean) => void;
}

export function SidePane({ side, label, value, open, onToggle }: SidePaneProps) {
  const isIn = side === 'in';
  // Closed, the arrow points at the box; open, it points back out of it.
  const Arrow = isIn ? (open ? ArrowLeft : ArrowRight) : open ? ArrowRight : ArrowLeft;

  return (
    <aside
      data-testid={`bv-${side}`}
      data-open={open ? 'true' : 'false'}
      className={cn(
        'flex min-h-0 min-w-0 overflow-hidden rounded-xl border',
        isIn ? 'border-sky-500/30 bg-sky-500/5' : 'border-emerald-500/30 bg-emerald-500/5',
        open ? 'flex-col' : 'flex-row md:flex-col',
      )}
    >
      <button
        type="button"
        onClick={() => onToggle(!open)}
        aria-expanded={open}
        data-testid={`bv-${side}-toggle`}
        className={cn(
          'flex shrink-0 items-center gap-2 transition-colors',
          isIn ? 'text-sky-400 hover:bg-sky-500/10' : 'text-emerald-400 hover:bg-emerald-500/10',
          open
            ? 'w-full px-3 py-2'
            : // Closed on desktop: a tall, narrow rail with the label running
              // down it. Closed on a phone: an ordinary full-width bar.
              'w-full px-3 py-2 md:h-full md:w-10 md:flex-col md:justify-start md:px-0 md:py-3',
        )}
      >
        <Arrow className="size-4 shrink-0" />
        <span
          className={cn(
            'truncate text-[11px] font-medium uppercase tracking-wide',
            !open && 'md:[writing-mode:vertical-rl] md:max-h-48 md:rotate-180',
          )}
        >
          {label}
        </span>
      </button>

      {open && (
        <div
          data-testid={`bv-${side}-body`}
          className={cn(
            'min-h-0 flex-1 overflow-auto border-t px-3 pb-3',
            isIn ? 'border-sky-500/20 bv-arrow-in' : 'border-emerald-500/20 bv-arrow-out',
          )}
        >
          <Content value={value} maxHeight={560} />
        </div>
      )}
    </aside>
  );
}
