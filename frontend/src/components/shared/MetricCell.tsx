interface MetricCellProps {
  label: string;
  value: string;
}

export function MetricCell({ label, value }: MetricCellProps) {
  return (
    <div className="flex flex-col rounded-md bg-temper-panel p-2">
      <span className="text-xs text-temper-text-dim">{label}</span>
      <span className="text-sm font-medium text-temper-text">{value}</span>
    </div>
  );
}
