import { useLayoutEffect, useRef, useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { MarkdownDisplay } from '@/components/shared/MarkdownDisplay';
import { cn } from '@/lib/utils';
import { teamBtn } from '../teamUi';

/** Tailwind needs each class written out whole. */
const CLAMP = { 3: 'line-clamp-3', 6: 'line-clamp-6' } as const;

/** The "Show all" / "Show less" button under a list or a text cut short. */
export function ShowAll({ all, onToggle, more }: { all: boolean; onToggle: () => void; more: string }) {
  return (
    <button type="button" className={cn(teamBtn.ghostXs, 'mt-1 self-start')} aria-expanded={all} onClick={onToggle}>
      {all ? <ChevronUp className="h-4 w-4" aria-hidden="true" /> : <ChevronDown className="h-4 w-4" aria-hidden="true" />}
      <span>{all ? 'Show less' : more}</span>
    </button>
  );
}

/**
 * The leader's summary, word for word: `lines` lines, then the rest on
 * request. Markdown without raw HTML. "Show all" shows only when the text
 * is cut.
 */
export function ClampedSummary({ content, lines }: { content: string; lines: keyof typeof CLAMP }) {
  const [all, setAll] = useState(false);
  const [long, setLong] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const el = box.current;
    if (!el || all) return;
    const measure = () => setLong(el.scrollHeight > el.clientHeight + 1);
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [content, all]);

  return (
    <div className="flex flex-col">
      <div ref={box} className={cn(!all && CLAMP[lines])}>
        <MarkdownDisplay content={content} className="rounded-none border-0 bg-transparent p-0" />
      </div>
      {(long || all) && <ShowAll all={all} onToggle={() => setAll((v) => !v)} more="Show all" />}
    </div>
  );
}
