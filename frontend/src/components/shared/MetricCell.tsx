interface MetricCellProps {
  label: string;
  value: string;
}

export function MetricCell({ label, value }: MetricCellProps) {
  return (
    <div className="flex flex-col rounded-md bg-maf-panel p-2">
      <span className="text-xs text-maf-text-dim">{label}</span>
      <span className="text-sm font-medium text-maf-text">{value}</span>
    </div>
  );
}
