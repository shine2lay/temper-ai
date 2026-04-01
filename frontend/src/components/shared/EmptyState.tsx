import type { ReactNode } from 'react';
import type { LucideIcon } from 'lucide-react';
import { cn } from '@/lib/utils';

interface EmptyStateProps {
  icon?: LucideIcon | string;
  title: string;
  subtitle?: string;
  action?: ReactNode;
  className?: string;
}

export function EmptyState({ icon: Icon, title, subtitle, action, className }: EmptyStateProps) {
  return (
    <div className={cn('flex-1 flex flex-col items-center justify-center text-temper-text-muted gap-3 py-12', className)}>
      {Icon && typeof Icon !== 'string' ? (
        <Icon className="w-8 h-8 text-temper-text-dim" aria-hidden="true" />
      ) : Icon ? (
        <span className="text-2xl" aria-hidden="true">{Icon}</span>
      ) : null}
      <span className="text-sm font-medium">{title}</span>
      {subtitle && <span className="text-xs text-temper-text-dim max-w-sm text-center">{subtitle}</span>}
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}
