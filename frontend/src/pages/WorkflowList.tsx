import { useMemo, useState, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { formatDuration, formatTimestamp, cn } from '@/lib/utils';
import { useDebounce } from '@/hooks/useDebounce';
import { SEARCH_DEBOUNCE_MS } from '@/lib/constants';

interface WorkflowSummary {
  id: string;
  workflow_name: string;
  status: string;
  start_time: string | null;
  duration_seconds: number | null;
}

type SortKey = 'time' | 'name' | 'status';

const STATUS_ORDER: Record<string, number> = {
  running: 0,
  pending: 1,
  completed: 2,
  failed: 3,
};

const STORAGE_KEY_SEARCH = 'maf-wf-search';
const STORAGE_KEY_FILTER = 'maf-wf-filter';
const STORAGE_KEY_SORT = 'maf-wf-sort';

function sortWorkflows(workflows: WorkflowSummary[], sortBy: SortKey): WorkflowSummary[] {
  const sorted = [...workflows];
  switch (sortBy) {
    case 'time':
      sorted.sort((a, b) => {
        const ta = a.start_time ?? '';
        const tb = b.start_time ?? '';
        return tb.localeCompare(ta);
      });
      break;
    case 'name':
      sorted.sort((a, b) => a.workflow_name.localeCompare(b.workflow_name));
      break;
    case 'status':
      sorted.sort(
        (a, b) => (STATUS_ORDER[a.status] ?? 4) - (STATUS_ORDER[b.status] ?? 4),
      );
      break;
  }
  return sorted;
}

export function WorkflowList() {
  const { data: workflows, isLoading, error, dataUpdatedAt, refetch } = useQuery<WorkflowSummary[]>({
    queryKey: ['workflows'],
    queryFn: async () => {
      const res = await fetch('/api/workflows');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
    refetchInterval: 5000,
  });

  const [sortBy, setSortBy] = useState<SortKey>(
    () => (localStorage.getItem(STORAGE_KEY_SORT) as SortKey) ?? 'time',
  );
  const [search, setSearch] = useState(
    () => localStorage.getItem(STORAGE_KEY_SEARCH) ?? '',
  );
  const [statusFilter, setStatusFilter] = useState<string | null>(
    () => localStorage.getItem(STORAGE_KEY_FILTER),
  );

  const debouncedSearch = useDebounce(search, SEARCH_DEBOUNCE_MS);

  // Persist filters to localStorage
  useEffect(() => {
    localStorage.setItem(STORAGE_KEY_SEARCH, search);
  }, [search]);

  useEffect(() => {
    if (statusFilter) {
      localStorage.setItem(STORAGE_KEY_FILTER, statusFilter);
    } else {
      localStorage.removeItem(STORAGE_KEY_FILTER);
    }
  }, [statusFilter]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY_SORT, sortBy);
  }, [sortBy]);

  const filtered = useMemo(() => {
    if (!workflows) return [];
    return workflows
      .filter((wf) => !debouncedSearch || wf.workflow_name.toLowerCase().includes(debouncedSearch.toLowerCase()))
      .filter((wf) => !statusFilter || wf.status === statusFilter);
  }, [workflows, debouncedSearch, statusFilter]);

  const sorted = useMemo(
    () => sortWorkflows(filtered, sortBy),
    [filtered, sortBy],
  );

  return (
    <div className="flex flex-col h-full bg-maf-bg">
      <header className="flex items-center gap-4 bg-maf-panel px-6 py-4 border-b border-maf-border shrink-0 flex-wrap">
        <h1 className="text-xl font-semibold text-maf-text">MAF Workflows</h1>
        <span className="text-xs text-maf-text-muted">
          {filtered.length}/{workflows?.length ?? 0} workflows
        </span>

        <input
          type="text"
          placeholder="Search workflows..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="px-3 py-1.5 rounded-md bg-maf-surface border border-maf-border text-sm text-maf-text placeholder:text-maf-text-dim focus:outline-none focus:ring-1 focus:ring-maf-accent w-64"
          aria-label="Search workflows by name"
        />

        <div className="flex items-center gap-2" role="group" aria-label="Filter by status">
          {(['all', 'running', 'completed', 'failed'] as const).map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s === 'all' ? null : s)}
              className={cn(
                'px-2 py-0.5 rounded text-xs transition-colors',
                (statusFilter === s || (s === 'all' && !statusFilter))
                  ? 'bg-maf-accent/20 text-maf-accent'
                  : 'text-maf-text-muted hover:text-maf-text',
              )}
              aria-pressed={statusFilter === s || (s === 'all' && !statusFilter)}
            >
              {s}
            </button>
          ))}
        </div>

        <div className="ml-auto flex items-center gap-2">
          <span className="text-xs text-maf-text-muted">Sort:</span>
          {(['time', 'name', 'status'] as const).map((s) => (
            <button
              key={s}
              onClick={() => setSortBy(s)}
              className={cn(
                'px-2 py-0.5 rounded text-xs transition-colors',
                sortBy === s
                  ? 'bg-maf-accent/20 text-maf-accent'
                  : 'text-maf-text-muted hover:text-maf-text',
              )}
              aria-pressed={sortBy === s}
            >
              {s}
            </button>
          ))}
          <button
            onClick={() => refetch()}
            className="px-2 py-1 rounded text-xs bg-maf-surface text-maf-text-muted hover:text-maf-text transition-colors"
          >
            Refresh
          </button>
          {dataUpdatedAt > 0 && (
            <span className="text-[10px] text-maf-text-dim">
              Updated {new Date(dataUpdatedAt).toLocaleTimeString()}
            </span>
          )}
        </div>
      </header>

      <div className="flex-1 overflow-y-auto p-6">
        {isLoading && (
          <p className="text-maf-text-muted text-sm">Loading workflows...</p>
        )}

        {error && (
          <p className="text-maf-failed text-sm">
            Failed to load workflows: {(error as Error).message}
          </p>
        )}

        {workflows && workflows.length === 0 && (
          <p className="text-maf-text-muted text-sm">No workflows found.</p>
        )}

        {workflows && workflows.length > 0 && sorted.length === 0 && (
          <p className="text-maf-text-muted text-sm">No workflows match your filters.</p>
        )}

        {sorted.length > 0 && (
          <div className="flex flex-col gap-2">
            {sorted.map((wf) => (
              <Link
                key={wf.id}
                to={`/workflow/${wf.id}`}
                className="flex items-center gap-4 rounded-lg bg-maf-panel px-4 py-3 border border-maf-border hover:bg-maf-surface transition-colors"
              >
                <span className="text-sm font-medium text-maf-text flex-1 truncate">
                  {wf.workflow_name}
                </span>
                <StatusBadge status={wf.status} />
                <span className="text-xs text-maf-text-muted w-36">
                  {wf.start_time ? formatTimestamp(wf.start_time) : '-'}
                </span>
                <span className="text-xs font-mono text-maf-text-muted w-20 text-right">
                  {formatDuration(wf.duration_seconds)}
                </span>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
