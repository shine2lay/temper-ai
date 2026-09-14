/**
 * Side-by-side comparison of 2–3 runs.
 *
 * The list has always offered a checkbox per row and a Compare button, but
 * the button only raised a "coming in v1.1" toast — so the most prominent
 * affordance on the busiest screen was a dead end, while "same workflow,
 * different model? compare results" is one of the project's stated reasons
 * to exist.
 *
 * The comparison is deliberately factual: run-level totals, then every node
 * across the runs with its status, duration and cost. Differences are
 * highlighted rather than interpreted.
 */
import { useMemo } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQueries } from '@tanstack/react-query';
import { AlertCircle } from 'lucide-react';
import { authFetch } from '@/lib/authFetch';
import { useDocumentTitle } from '@/hooks/useDocumentTitle';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { formatCost, formatDuration, formatTokens } from '@/lib/utils';
import type { NodeExecution, WorkflowExecution } from '@/types';

function nodeMap(run: WorkflowExecution | undefined): Map<string, NodeExecution> {
  const map = new Map<string, NodeExecution>();
  const walk = (nodes: NodeExecution[] | undefined) => {
    for (const n of nodes ?? []) {
      if (n.name) map.set(n.name, n);
      walk(n.child_nodes);
    }
  };
  walk(run?.nodes);
  return map;
}

/** True when the values differ across runs — used to highlight a row. */
function differs(values: (string | number | null | undefined)[]): boolean {
  const seen = values.map((v) => (v == null ? '' : String(v)));
  return new Set(seen).size > 1;
}

export function CompareView() {
  const [params] = useSearchParams();
  const ids = useMemo(
    () => (params.get('ids') ?? '').split(',').map((s) => s.trim()).filter(Boolean),
    [params],
  );
  useDocumentTitle(`Compare ${ids.length} runs`);

  const queries = useQueries({
    queries: ids.map((id) => ({
      queryKey: ['workflow', id],
      queryFn: async () => {
        const res = await authFetch(`/api/workflows/${id}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return (await res.json()) as WorkflowExecution;
      },
    })),
  });

  const runs = queries.map((q) => q.data);
  const loading = queries.some((q) => q.isLoading);
  const maps = useMemo(() => runs.map(nodeMap), [runs]);

  const nodeNames = useMemo(() => {
    const names: string[] = [];
    for (const m of maps) {
      for (const name of m.keys()) if (!names.includes(name)) names.push(name);
    }
    return names;
  }, [maps]);

  if (ids.length < 2) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 bg-temper-bg p-6 text-center">
        <AlertCircle className="size-8 text-temper-text-muted" aria-hidden />
        <h1 className="text-lg font-semibold text-temper-text">Pick at least two runs</h1>
        <p className="max-w-md text-sm text-temper-text-muted">
          Select two or three runs on the Workflows page, then choose Compare.
        </p>
        <Link to="/" className="text-sm text-temper-accent hover:underline">
          Back to workflows
        </Link>
      </div>
    );
  }

  const summaryRows: { label: string; values: (string | number | null)[] }[] = [
    { label: 'Status', values: runs.map((r) => r?.status ?? null) },
    { label: 'Started', values: runs.map((r) => (r?.start_time ? new Date(r.start_time + 'Z').toLocaleString() : null)) },
    { label: 'Duration', values: runs.map((r) => (r?.duration_seconds != null ? formatDuration(r.duration_seconds) : null)) },
    { label: 'Tokens', values: runs.map((r) => (r?.total_tokens != null ? formatTokens(r.total_tokens) : null)) },
    { label: 'Cost', values: runs.map((r) => (r?.total_cost_usd != null ? formatCost(r.total_cost_usd) : null)) },
    { label: 'LLM calls', values: runs.map((r) => r?.total_llm_calls ?? null) },
    { label: 'Tool calls', values: runs.map((r) => r?.total_tool_calls ?? null) },
  ];

  return (
    <div className="flex h-full flex-col overflow-auto bg-temper-bg">
      <header className="shrink-0 border-b border-temper-border bg-temper-panel px-6 py-3">
        <div className="mx-auto flex max-w-[1600px] items-center gap-3">
          <Link to="/" className="text-sm text-temper-accent hover:underline">
            ← Workflows
          </Link>
          <h1 className="text-lg font-semibold text-temper-text">
            Comparing {ids.length} runs
          </h1>
          {loading && <span className="text-xs text-temper-text-muted">Loading…</span>}
        </div>
      </header>

      <div className="mx-auto w-full max-w-[1600px] p-6">
        <table className="w-full table-fixed border-collapse text-sm">
          <thead>
            <tr>
              <th className="w-40 border-b border-temper-border p-2 text-left text-xs font-medium uppercase tracking-wide text-temper-text-dim">
                Run
              </th>
              {runs.map((run, i) => (
                <th key={ids[i]} className="border-b border-temper-border p-2 text-left">
                  <Link
                    to={`/workflow/${ids[i]}`}
                    className="font-medium text-temper-text hover:text-temper-accent"
                  >
                    {run?.workflow_name ?? ids[i].slice(0, 8)}
                  </Link>
                  <div className="font-mono text-[10px] text-temper-text-dim">
                    {ids[i].slice(0, 8)}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {summaryRows.map((row) => (
              <tr
                key={row.label}
                className={differs(row.values) ? 'bg-temper-accent/5' : undefined}
              >
                <td className="border-b border-temper-border/50 p-2 text-xs text-temper-text-muted">
                  {row.label}
                </td>
                {row.values.map((v, i) => (
                  <td key={ids[i]} className="border-b border-temper-border/50 p-2 text-temper-text">
                    {row.label === 'Status' && v ? (
                      <StatusBadge status={String(v)} />
                    ) : (
                      <span className="font-mono text-xs">{v ?? '—'}</span>
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>

        <h2 className="mt-8 mb-2 text-sm font-semibold text-temper-text">Nodes</h2>
        <table className="w-full table-fixed border-collapse text-sm">
          <thead>
            <tr>
              <th className="w-40 border-b border-temper-border p-2 text-left text-xs font-medium uppercase tracking-wide text-temper-text-dim">
                Node
              </th>
              {ids.map((id) => (
                <th
                  key={id}
                  className="border-b border-temper-border p-2 text-left text-xs font-medium uppercase tracking-wide text-temper-text-dim"
                >
                  status · duration · cost
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {nodeNames.map((name) => {
              const cells = maps.map((m) => m.get(name));
              return (
                <tr
                  key={name}
                  className={
                    differs(cells.map((c) => c?.status)) ? 'bg-temper-accent/5' : undefined
                  }
                >
                  <td className="border-b border-temper-border/50 p-2 font-mono text-xs text-temper-text">
                    {name}
                  </td>
                  {cells.map((node, i) => (
                    <td key={ids[i]} className="border-b border-temper-border/50 p-2">
                      {node ? (
                        <span className="flex items-center gap-2">
                          <StatusBadge status={node.status} />
                          <span className="font-mono text-xs text-temper-text-muted">
                            {node.duration_seconds != null ? formatDuration(node.duration_seconds) : '—'}
                            {node.cost_usd ? ` · ${formatCost(node.cost_usd)}` : ''}
                          </span>
                        </span>
                      ) : (
                        <span className="text-xs text-temper-text-dim">not in this run</span>
                      )}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
