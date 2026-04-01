import { useMemo, useState, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import { AlertCircle, Inbox, SearchX } from 'lucide-react';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { EmptyState } from '@/components/shared/EmptyState';
import { formatDuration, formatRelativeTime, getDateGroup, cn } from '@/lib/utils';
import { useDebounce } from '@/hooks/useDebounce';
import { SEARCH_DEBOUNCE_MS } from '@/lib/constants';
import { authFetch } from '@/lib/authFetch';

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

const STORAGE_KEY_SEARCH = 'temper-wf-search';
const STORAGE_KEY_FILTER = 'temper-wf-filter';
const STORAGE_KEY_SORT = 'temper-wf-sort';

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

function WorkflowRow({
  wf,
  selected,
  onToggleSelect,
  onNavigate,
}: {
  wf: WorkflowSummary;
  selected: Set<string>;
  onToggleSelect: (id: string) => void;
  onNavigate: (path: string) => void;
}) {
  const shortId = wf.id.replace('wf-', '').slice(0, 8);
  return (
    <div
      onClick={() => onNavigate(`/workflow/${wf.id}`)}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onNavigate(`/workflow/${wf.id}`); } }}
      role="link"
      tabIndex={0}
      className="flex items-center gap-4 rounded-lg bg-temper-panel px-4 py-3 border border-temper-border hover:bg-temper-surface transition-colors cursor-pointer focus:outline-none focus:ring-2 focus:ring-temper-accent/50"
    >
      <input
        type="checkbox"
        checked={selected.has(wf.id)}
        onChange={() => onToggleSelect(wf.id)}
        onClick={(e) => e.stopPropagation()}
        className="shrink-0 accent-temper-accent w-4 h-4 border-2 border-temper-border rounded"
        aria-label={`Select ${wf.workflow_name} for comparison`}
      />
      <div className="flex-1 min-w-0">
        <span className="text-sm font-medium text-temper-text truncate block">
          {wf.workflow_name}
        </span>
        <span className="text-[10px] font-mono text-temper-text-dim">{shortId}</span>
      </div>
      <StatusBadge status={wf.status} />
      <span className="text-xs text-temper-text-muted w-36">
        {wf.start_time ? formatRelativeTime(wf.start_time) : '-'}
      </span>
      <span className="text-xs font-mono text-temper-text-muted w-20 text-right">
        {formatDuration(wf.duration_seconds)}
      </span>
      <Link
        to={`/studio/${wf.workflow_name}`}
        onClick={(e) => e.stopPropagation()}
        className="text-[10px] px-2 py-0.5 rounded bg-temper-surface text-temper-text-muted hover:text-temper-accent hover:bg-temper-accent/10 transition-colors shrink-0"
      >
        Studio
      </Link>
    </div>
  );
}

export function WorkflowList() {
  const navigate = useNavigate();
  const { data: workflows, isLoading, error, dataUpdatedAt, refetch } = useQuery<WorkflowSummary[]>({
    queryKey: ['workflows'],
    queryFn: async () => {
      const res = await authFetch('/api/workflows');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      // v1 API returns {runs: [...], total: int}
      return data.runs ?? data;
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
  const [selected, setSelected] = useState<Set<string>>(new Set());

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else if (next.size < 3) {
        next.add(id);
      }
      return next;
    });
  }

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

  const grouped = useMemo(() => {
    if (sortBy !== 'time') return null;
    const groups: Array<{ label: string; items: WorkflowSummary[] }> = [];
    let currentLabel = '';
    for (const wf of sorted) {
      const label = getDateGroup(wf.start_time);
      if (label !== currentLabel) {
        currentLabel = label;
        groups.push({ label, items: [wf] });
      } else {
        groups[groups.length - 1].items.push(wf);
      }
    }
    return groups;
  }, [sorted, sortBy]);

  return (
    <div className="flex flex-col h-full bg-temper-bg">
      <header className="bg-temper-panel px-6 py-4 border-b border-temper-border shrink-0">
        <div className="flex items-center gap-4 flex-wrap max-w-[1600px] mx-auto">
        <h1 className="text-xl font-semibold text-temper-text">Workflows</h1>
        <span className="text-xs text-temper-text-muted">
          {filtered.length}/{workflows?.length ?? 0} workflows
        </span>

        <input
          type="text"
          placeholder="Search workflows..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="px-3 py-1.5 rounded-md bg-temper-surface border border-temper-border text-sm text-temper-text placeholder:text-temper-text-dim focus:outline-none focus:ring-1 focus:ring-temper-accent w-64"
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
                  ? 'bg-temper-accent/20 text-temper-accent'
                  : 'text-temper-text-muted hover:text-temper-text',
              )}
              aria-pressed={statusFilter === s || (s === 'all' && !statusFilter)}
            >
              {s}
            </button>
          ))}
        </div>

        <div className="ml-auto flex items-center gap-2">
          {selected.size >= 2 && (
            <button
              onClick={() => {
                const ids = [...selected];
                const params = new URLSearchParams({ a: ids[0], b: ids[1] });
                if (ids[2]) params.set('c', ids[2]);
                navigate(`/compare?${params}`);
              }}
              className="px-3 py-1 rounded-md text-xs font-medium bg-temper-accent text-white hover:opacity-90 transition-colors"
            >
              Compare ({selected.size})
            </button>
          )}
          {selected.size > 0 && (
            <button
              onClick={() => setSelected(new Set())}
              className="text-xs text-temper-text-muted hover:text-temper-text transition-colors"
            >
              Clear selection
            </button>
          )}
          <span className="text-xs text-temper-text-muted">Sort:</span>
          {(['time', 'name', 'status'] as const).map((s) => (
            <button
              key={s}
              onClick={() => setSortBy(s)}
              className={cn(
                'px-2 py-0.5 rounded text-xs transition-colors',
                sortBy === s
                  ? 'bg-temper-accent/20 text-temper-accent'
                  : 'text-temper-text-muted hover:text-temper-text',
              )}
              aria-pressed={sortBy === s}
            >
              {s}
            </button>
          ))}
          <button
            onClick={() => refetch()}
            className="px-2 py-1 rounded text-xs bg-temper-surface text-temper-text-muted hover:text-temper-text transition-colors"
          >
            Refresh
          </button>
          {dataUpdatedAt > 0 && (
            <span className="text-[10px] text-temper-text-dim">
              Updated {new Date(dataUpdatedAt).toLocaleTimeString()}
            </span>
          )}
        </div>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto p-6 max-w-[1600px] mx-auto w-full">
        {isLoading && (
          <EmptyState title="Loading workflows..." />
        )}

        {error && (
          <EmptyState
            icon={AlertCircle}
            title="Failed to load workflows"
            subtitle={(error as Error).message}
          />
        )}

        {workflows && workflows.length === 0 && (
          <EmptyState
            icon={Inbox}
            title="No workflows found"
            subtitle="Run a workflow to see it here, or create one in Studio."
            action={
              <Link to="/studio" className="text-temper-accent hover:underline text-sm">
                Create Workflow
              </Link>
            }
          />
        )}

        {workflows && workflows.length > 0 && sorted.length === 0 && (
          <EmptyState
            icon={SearchX}
            title="No workflows match your filters"
            subtitle="Try adjusting your search or status filter."
          />
        )}

        {sorted.length > 0 && (
          <div className="flex flex-col gap-2">
            {grouped ? (
              grouped.map((group) => (
                <div key={group.label}>
                  <h3 className="text-xs font-medium text-temper-text-dim mb-2 mt-3 first:mt-0">{group.label}</h3>
                  <div className="flex flex-col gap-2">
                    {group.items.map((wf) => (
                      <WorkflowRow key={wf.id} wf={wf} selected={selected} onToggleSelect={toggleSelect} onNavigate={navigate} />
                    ))}
                  </div>
                </div>
              ))
            ) : (
              sorted.map((wf) => (
                <WorkflowRow key={wf.id} wf={wf} selected={selected} onToggleSelect={toggleSelect} onNavigate={navigate} />
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
}
