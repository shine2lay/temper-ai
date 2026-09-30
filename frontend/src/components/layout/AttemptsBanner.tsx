/**
 * A run that ran more than once.
 *
 * A run cut off by a crash keeps its id and is started again from where it stopped, so its
 * page holds two attempts (or more). The steps of the earlier ones are in the tree already,
 * merged by name; what is missing is that any of this happened -- and, when temper picked the
 * run up by itself after a restart, who decided to.
 *
 * Says nothing for a run that ran once, which is nearly all of them.
 */
import type { RunAttempt } from '@/types';
import { formatTimestamp } from '@/lib/utils';

interface AttemptsBannerProps {
  attempts?: RunAttempt[] | null;
}

export function AttemptsBanner({ attempts }: AttemptsBannerProps) {
  if (!attempts || attempts.length < 2) return null;

  const earlier = attempts.filter((a) => !a.is_current);
  const pickedUpByTemper = earlier.some((a) => a.picked_up_by_temper);

  return (
    <div
      data-testid="attempts-banner"
      className="px-4 py-3 border-b border-sky-300 bg-sky-50 text-[11px] dark:border-sky-500/20 dark:bg-sky-500/10 shrink-0"
    >
      <div className="font-medium text-sky-800 dark:text-sky-300">
        {pickedUpByTemper
          ? 'Resumed: temper picked this run back up after a restart.'
          : 'Resumed: this run was started again from where it stopped.'}
      </div>
      <ol className="mt-1.5 space-y-0.5 text-sky-900/80 dark:text-sky-200/70">
        {attempts.map((attempt) => (
          <li key={attempt.event_id ?? attempt.attempt} className="flex flex-wrap gap-x-2">
            <span className="font-mono">#{attempt.attempt}</span>
            <span>{formatTimestamp(attempt.start_time)}</span>
            <span>— {attempt.status}</span>
            {attempt.picked_up_by_temper && <span>· picked back up by temper</span>}
            {attempt.is_current && <span>· this one</span>}
            {attempt.error && <span className="opacity-70">· {attempt.error}</span>}
          </li>
        ))}
      </ol>
      <div className="mt-1.5 text-sky-900/60 dark:text-sky-200/50">
        The steps of the earlier attempts are in the tree; a step that ran twice shows its
        latest run.
      </div>
    </div>
  );
}
