import { memo } from 'react';

interface MetricCellProps {
  label: string;
  value: string;
  compact?: boolean;
}

export const MetricCell = memo(function MetricCell({ label, value, compact }: MetricCellProps) {
  return (
    <div className={`flex flex-col rounded-md bg-temper-panel ${compact ? 'px-2 py-1' : 'p-2'}`}>
      <span className="text-xs text-temper-text-dim">{label}</span>
      <span className={`font-medium text-temper-text ${compact ? 'text-xs' : 'text-sm'}`}>{value}</span>
    </div>
  );
});
