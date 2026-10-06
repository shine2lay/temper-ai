import { useLayoutEffect, useRef, useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { MarkdownDisplay } from '@/components/shared/MarkdownDisplay';
import { cn } from '@/lib/utils';
import { teamBtn, teamCard, teamLabel } from '../teamUi';

/** The trial's goal as written: four lines, then the rest on request. */
export function GoalCard({ goal }: { goal: string }) {
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
  }, [goal, all]);

  return (
    <section aria-labelledby="team-goal-title" className={cn(teamCard, 'p-4')}>
      <h2 id="team-goal-title" className={teamLabel}>
        Goal
      </h2>
      <div ref={box} className={cn(!all && 'line-clamp-4')}>
        <MarkdownDisplay content={goal} className="rounded-none border-0 bg-transparent p-0" />
      </div>
      {(long || all) && (
        <button type="button" className={cn(teamBtn.ghostXs, 'mt-1')} aria-expanded={all} onClick={() => setAll((v) => !v)}>
          {all ? <ChevronUp className="h-4 w-4" aria-hidden="true" /> : <ChevronDown className="h-4 w-4" aria-hidden="true" />}
          <span>{all ? 'Show less' : 'Show all'}</span>
        </button>
      )}
    </section>
  );
}
