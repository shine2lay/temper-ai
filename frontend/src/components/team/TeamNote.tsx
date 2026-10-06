import type { ReactNode } from 'react';
import type { LucideIcon } from 'lucide-react';
import { CircleCheck, CircleX, Info, TriangleAlert } from 'lucide-react';
import { cn } from '@/lib/utils';

export type TeamNoteTone = 'neutral' | 'info' | 'warn' | 'bad' | 'ok';

const TONES: Record<TeamNoteTone, { box: string; icon: string; Icon: LucideIcon }> = {
  neutral: {
    box: 'bg-temper-panel border-temper-border',
    icon: 'text-temper-text-muted',
    Icon: Info,
  },
  info: {
    box: 'bg-[var(--badge-running-bg)] border-[var(--badge-running-border)]',
    icon: 'text-[var(--badge-running-text)]',
    Icon: Info,
  },
  warn: {
    box: 'bg-[var(--badge-waiting-bg)] border-[var(--badge-waiting-border)]',
    icon: 'text-[var(--badge-waiting-text)]',
    Icon: TriangleAlert,
  },
  bad: {
    box: 'bg-[var(--badge-failed-bg)] border-[var(--badge-failed-border)]',
    icon: 'text-[var(--badge-failed-text)]',
    Icon: CircleX,
  },
  ok: {
    box: 'bg-[var(--badge-completed-bg)] border-[var(--badge-completed-border)]',
    icon: 'text-[var(--badge-completed-text)]',
    Icon: CircleCheck,
  },
};

/**
 * A one-message notice: icon and text, the run page's alert pattern. The
 * tone is never the only signal (the words say it), and `action` sits at
 * the right (a "Try now" button, a link).
 */
export function TeamNote({
  tone,
  title,
  children,
  action,
  icon,
  live,
  className,
}: {
  tone: TeamNoteTone;
  title?: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  icon?: LucideIcon;
  /** Announce changes politely (a refresh that failed). */
  live?: boolean;
  className?: string;
}) {
  const t = TONES[tone];
  const Icon = icon ?? t.Icon;
  return (
    <div
      data-note={tone}
      role={live ? 'status' : undefined}
      className={cn('flex items-start gap-2 rounded-lg border px-3 py-2 text-sm text-temper-text', t.box, className)}
    >
      <Icon className={cn('mt-0.5 h-4 w-4 shrink-0', t.icon)} aria-hidden="true" />
      <div className="min-w-0 flex-1">
        {title && <p className="m-0 font-semibold">{title}</p>}
        {children && <div className={cn(title ? 'mt-0.5' : '', 'text-temper-text')}>{children}</div>}
      </div>
      {action && <div className="shrink-0 self-center">{action}</div>}
    </div>
  );
}
