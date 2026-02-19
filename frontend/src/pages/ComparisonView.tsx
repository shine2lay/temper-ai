import { useSearchParams, Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { formatDuration, formatTokens, formatCost, cn } from '@/lib/utils';
import type { WorkflowExecution, StageExecution } from '@/types';

function WorkflowColumn({ workflow, loading }: { workflow?: WorkflowExecution; loading: boolean }) {
  if (loading) return <div className="text-maf-text-muted text-sm">Loading...</div>;
  if (!workflow) return <div className="text-maf-text-muted text-sm">Not found</div>;

  const metrics = [
    { label: 'Status', value: workflow.status },
    { label: 'Duration', value: formatDuration(workflow.duration_seconds) },
    { label: 'Tokens', value: formatTokens(workflow.total_tokens) },
    { label: 'Cost', value: formatCost(workflow.total_cost_usd) },
    { label: 'LLM Calls', value: String(workflow.total_llm_calls ?? 0) },
    { label: 'Tool Calls', value: String(workflow.total_tool_calls ?? 0) },
    { label: 'Stages', value: String(workflow.stages?.length ?? 0) },
  ];

  return (
    <div className="rounded-lg bg-maf-panel border border-maf-border p-4">
      <div className="flex items-center gap-2 mb-4">
        <h2 className="text-sm font-semibold text-maf-text truncate">{workflow.workflow_name}</h2>
        <StatusBadge status={workflow.status} />
      </div>
      <div className="flex flex-col gap-2">
        {metrics.map((m) => (
          <div key={m.label} className="flex justify-between text-xs">
            <span className="text-maf-text-muted">{m.label}</span>
            <span className="font-mono text-maf-text">{m.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function stageName(s: StageExecution): string {
  return s.stage_name ?? s.name ?? s.id;
}

function StageComparisonTable({
  stagesA,
  stagesB,
  stagesC,
}: {
  stagesA?: StageExecution[];
  stagesB?: StageExecution[];
  stagesC?: StageExecution[];
}) {
  const allNames = new Set([
    ...(stagesA ?? []).map(stageName),
    ...(stagesB ?? []).map(stageName),
    ...(stagesC ?? []).map(stageName),
  ]);

  if (allNames.size === 0) return null;

  const hasC = !!stagesC;

  return (
    <div className="mt-4">
      <h3 className="text-sm font-medium text-maf-text-muted mb-2">Stage Comparison</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-maf-border text-maf-text-muted">
              <th className="text-left py-1.5 px-2">Stage</th>
              <th className="text-center py-1.5 px-2">Status A</th>
              <th className="text-center py-1.5 px-2">Duration A</th>
              <th className="text-center py-1.5 px-2">Status B</th>
              <th className="text-center py-1.5 px-2">Duration B</th>
              {hasC && <th className="text-center py-1.5 px-2">Status C</th>}
              {hasC && <th className="text-center py-1.5 px-2">Duration C</th>}
              <th className="text-center py-1.5 px-2">Diff (B-A)</th>
            </tr>
          </thead>
          <tbody>
            {Array.from(allNames).map((name) => {
              const a = stagesA?.find((s) => stageName(s) === name);
              const b = stagesB?.find((s) => stageName(s) === name);
              const c = stagesC?.find((s) => stageName(s) === name);
              const durA = a?.duration_seconds ?? 0;
              const durB = b?.duration_seconds ?? 0;
              const diff = durB - durA;
              return (
                <tr key={name} className="border-b border-maf-border/30">
                  <td className="py-1.5 px-2 text-maf-text font-medium">{name}</td>
                  <td className="py-1.5 px-2 text-center">
                    {a ? <StatusBadge status={a.status} /> : <span className="text-maf-text-dim">-</span>}
                  </td>
                  <td className="py-1.5 px-2 text-center font-mono text-maf-text-muted">
                    {a ? formatDuration(durA) : '-'}
                  </td>
                  <td className="py-1.5 px-2 text-center">
                    {b ? <StatusBadge status={b.status} /> : <span className="text-maf-text-dim">-</span>}
                  </td>
                  <td className="py-1.5 px-2 text-center font-mono text-maf-text-muted">
                    {b ? formatDuration(durB) : '-'}
                  </td>
                  {hasC && (
                    <td className="py-1.5 px-2 text-center">
                      {c ? <StatusBadge status={c.status} /> : <span className="text-maf-text-dim">-</span>}
                    </td>
                  )}
                  {hasC && (
                    <td className="py-1.5 px-2 text-center font-mono text-maf-text-muted">
                      {c ? formatDuration(c.duration_seconds) : '-'}
                    </td>
                  )}
                  <td
                    className={cn(
                      'py-1.5 px-2 text-center font-mono',
                      diff < 0 ? 'text-emerald-400' : diff > 0 ? 'text-red-400' : 'text-maf-text-muted',
                    )}
                  >
                    {a && b ? `${diff > 0 ? '+' : ''}${formatDuration(diff)}` : '-'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function ComparisonView() {
  const [params] = useSearchParams();
  const idA = params.get('a');
  const idB = params.get('b');
  const idC = params.get('c');

  const queryA = useQuery<WorkflowExecution>({
    queryKey: ['workflow', idA],
    queryFn: async () => (await fetch(`/api/workflows/${idA}`)).json(),
    enabled: !!idA,
  });

  const queryB = useQuery<WorkflowExecution>({
    queryKey: ['workflow', idB],
    queryFn: async () => (await fetch(`/api/workflows/${idB}`)).json(),
    enabled: !!idB,
  });

  const queryC = useQuery<WorkflowExecution>({
    queryKey: ['workflow', idC],
    queryFn: async () => (await fetch(`/api/workflows/${idC}`)).json(),
    enabled: !!idC,
  });

  if (!idA || !idB) {
    return (
      <div className="flex flex-col items-center justify-center h-full bg-maf-bg text-maf-text gap-4">
        <h1 className="text-xl font-semibold">Compare Workflows</h1>
        <p className="text-sm text-maf-text-muted">
          Use URL params: /app/compare?a=ID_1&amp;b=ID_2 (optional: &amp;c=ID_3)
        </p>
        <Link to="/" className="text-maf-accent hover:underline text-sm">
          Back to workflows
        </Link>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-maf-bg">
      <header className="flex items-center gap-4 bg-maf-panel px-6 py-4 border-b border-maf-border shrink-0">
        <Link to="/" className="text-maf-accent hover:underline text-sm">
          Back
        </Link>
        <h1 className="text-lg font-semibold text-maf-text">Compare Workflows</h1>
      </header>

      <div className="flex-1 overflow-auto p-6">
        <div className={cn('grid gap-6', idC ? 'grid-cols-3' : 'grid-cols-2')}>
          <WorkflowColumn workflow={queryA.data} loading={queryA.isLoading} />
          <WorkflowColumn workflow={queryB.data} loading={queryB.isLoading} />
          {idC && <WorkflowColumn workflow={queryC.data} loading={queryC.isLoading} />}
        </div>

        <StageComparisonTable
          stagesA={queryA.data?.stages}
          stagesB={queryB.data?.stages}
          stagesC={idC ? queryC.data?.stages : undefined}
        />
      </div>
    </div>
  );
}
