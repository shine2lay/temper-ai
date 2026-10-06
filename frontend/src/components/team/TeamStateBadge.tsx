import type { LucideIcon } from 'lucide-react';
import {
  Ban,
  Check,
  CirclePause,
  CircleSlash,
  FileDiff,
  Hourglass,
  LoaderCircle,
  Play,
  Square,
  TriangleAlert,
  X,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { teamStateTone, teamStateWord, type TeamTone } from '@/lib/teamText';

const ICONS: Record<string, LucideIcon> = {
  starting: LoaderCircle,
  running: Play,
  paused: CirclePause,
  quiet: Hourglass,
  member_waiting: TriangleAlert,
  settings_changed: FileDiff,
  interrupted: CircleSlash,
  done: Check,
  stopped: Square,
  failed: X,
  didnt_start: Ban,
};

/** Badge colours per tone; the text colours are measured on the badge over the panel. */
const TONE_CLASSES: Record<TeamTone, string> = {
  pending: 'bg-[var(--badge-pending-bg)] text-[var(--badge-pending-text)] border-[var(--badge-pending-border)]',
  running: 'bg-[var(--badge-running-bg)] text-[var(--badge-running-text)] border-[var(--badge-running-border)]',
  waiting: 'bg-[var(--badge-waiting-bg)] text-[var(--badge-waiting-text)] border-[var(--badge-waiting-border)]',
  interrupted:
    'bg-[var(--badge-interrupted-bg)] text-[var(--badge-interrupted-text)] border-[var(--badge-interrupted-border)]',
  completed: 'bg-[var(--badge-completed-bg)] text-[var(--badge-completed-text)] border-[var(--badge-completed-border)]',
  cancelled: 'bg-[var(--badge-cancelled-bg)] text-[var(--badge-cancelled-text)] border-[var(--badge-cancelled-border)]',
  failed: 'bg-[var(--badge-failed-bg)] text-[var(--badge-failed-text)] border-[var(--badge-failed-border)]',
};

/**
 * A team run's state: icon and word, always both, so the state never rests
 * on colour alone. Eleven states (Design's K1 board); one the page doesn't know
 * yet shows its own name in the neutral colours.
 */
export function TeamStateBadge({ state, className }: { state: string; className?: string }) {
  const Icon = ICONS[state] ?? CircleSlash;
  return (
    <span
      data-component="team-state-badge"
      data-state={state}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold leading-[18px] whitespace-nowrap',
        TONE_CLASSES[teamStateTone(state)],
        className,
      )}
    >
      <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      <span>{teamStateWord(state)}</span>
    </span>
  );
}
