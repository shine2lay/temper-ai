interface EmptyStateProps {
  icon?: string;
  title: string;
  subtitle?: string;
}

export function EmptyState({ icon, title, subtitle }: EmptyStateProps) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center text-temper-text-muted gap-2 py-8">
      {icon && <span className="text-2xl" aria-hidden="true">{icon}</span>}
      <span className="text-sm">{title}</span>
      {subtitle && <span className="text-xs text-temper-text-dim">{subtitle}</span>}
    </div>
  );
}
