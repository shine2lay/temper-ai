import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { STATUS_ICONS } from '@/lib/constants';

const STATUS_STYLES: Record<string, string> = {
  completed: 'bg-[#66bb6a]/20 text-[#66bb6a] border-[#66bb6a]/30',
  running: 'bg-[#4fc3f7]/20 text-[#4fc3f7] border-[#4fc3f7]/30',
  failed: 'bg-[#ef5350]/20 text-[#ef5350] border-[#ef5350]/30',
  pending: 'bg-[#6a7080]/20 text-[#6a7080] border-[#6a7080]/30',
};

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const icon = STATUS_ICONS[status] ?? '';
  return (
    <Badge variant="outline" className={cn('text-xs', STATUS_STYLES[status] ?? STATUS_STYLES.pending, className)}>
      {icon && <span className="mr-1">{icon}</span>}
      {status}
    </Badge>
  );
}
