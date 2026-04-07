import { memo } from 'react';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { STATUS_ICONS } from '@/lib/constants';

const STATUS_STYLES: Record<string, string> = {
  completed: 'bg-[var(--badge-completed-bg)] text-[var(--badge-completed-text)] border-[var(--badge-completed-border)]',
  running: 'bg-[var(--badge-running-bg)] text-[var(--badge-running-text)] border-[var(--badge-running-border)]',
  failed: 'bg-[var(--badge-failed-bg)] text-[var(--badge-failed-text)] border-[var(--badge-failed-border)]',
  pending: 'bg-[var(--badge-pending-bg)] text-[var(--badge-pending-text)] border-[var(--badge-pending-border)]',
  cancelled: 'bg-amber-500/15 text-amber-500 border-amber-500/30',
};

export const StatusBadge = memo(function StatusBadge({ status, className }: { status: string; className?: string }) {
  const icon = STATUS_ICONS[status] ?? '';
  return (
    <Badge variant="outline" className={cn('text-xs', STATUS_STYLES[status] ?? STATUS_STYLES.pending, className)}>
      {icon && <span className="mr-1">{icon}</span>}
      {status}
    </Badge>
  );
});
