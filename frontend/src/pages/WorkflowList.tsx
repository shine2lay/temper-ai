import { useMemo, useState, useEffect, useRef } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import * as Dialog from '@radix-ui/react-dialog';
import { AlertCircle, Inbox, SearchX, X, Play } from 'lucide-react';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { EmptyState } from '@/components/shared/EmptyState';
import {
  formatDuration,
  formatRelativeTime,
  formatTokens,
  formatCost,
  getDateGroup,
  cn,
  ensureUTC,
} from '@/lib/utils';
import { useDebounce } from '@/hooks/useDebounce';
import { SEARCH_DEBOUNCE_MS } from '@/lib/constants';
import { authFetch } from '@/lib/authFetch';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface WorkflowSummary {
  id: string;
  workflow_name: string;
  status: string;
  start_time: string | null;
  end_time: string | null;
  duration_seconds: number | null;
  total_tokens: number | null;
  total_cost_usd: number | null;
  total_llm_calls: number | null;
  total_tool_calls: number | null;
}

interface WorkflowConfigSummary {
  name: string;
  description?: string;
}

interface WorkflowConfigList {
  configs: WorkflowConfigSummary[];
  total: number;
}

interface RunResponse {
  execution_id: string;
  status: string;
  message: string;
}

type SortKey = 'time' | 'name' | 'status';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STATUS_ORDER: Record<string, number> = {
  running: 0,
  pending: 1,
  completed: 2,
  failed: 3,
};

const STORAGE_KEY_SEARCH = 'temper-wf-search';
const STORAGE_KEY_FILTER = 'temper-wf-filter';
const STORAGE_KEY_SORT = 'temper-wf-sort';

/** Threshold in seconds above which a still-running workflow is flagged stale. */
const STALE_THRESHOLD_S = 30 * 60;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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

/**
 * Returns true when a running workflow started more than STALE_THRESHOLD_S
 * seconds ago and still has status "running".
 */
function isStaleRun(wf: WorkflowSummary): boolean {
  if (wf.status !== 'running' || !wf.start_time) return false;
  const startMs = new Date(ensureUTC(wf.start_time)).getTime();
  return (Date.now() - startMs) / 1000 > STALE_THRESHOLD_S;
}

/**
 * A failed or completed run with zero tokens and a very short duration is
 * likely an instant failure before any LLM calls were made.
 */
function isInstantFailure(wf: WorkflowSummary): boolean {
  const zeroTokens = !wf.total_tokens || wf.total_tokens === 0;
  const veryShort = wf.duration_seconds != null && wf.duration_seconds <= 0.2;
  return (wf.status === 'failed' || wf.status === 'completed') && zeroTokens && veryShort;
}

// ---------------------------------------------------------------------------
// Cancel mutation (standalone, no queryClient invalidation needed here since
// the poll will pick up the new status)
// ---------------------------------------------------------------------------

async function cancelRun(id: string): Promise<void> {
  const res = await authFetch(`/api/runs/${id}/cancel`, { method: 'POST' });
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(body || `HTTP ${res.status}`);
  }
}

// ---------------------------------------------------------------------------
// WorkflowRow
// ---------------------------------------------------------------------------

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
  const stale = isStaleRun(wf);
  const instant = isInstantFailure(wf);

  const cancelMutation = useMutation<void, Error, string>({
    mutationFn: cancelRun,
  });

  const hasTokenInfo =
    (wf.total_tokens != null && wf.total_tokens > 0) ||
    (wf.total_cost_usd != null && wf.total_cost_usd > 0);

  return (
    <div
      onClick={() => onNavigate(`/workflow/${wf.id}`)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onNavigate(`/workflow/${wf.id}`);
        }
      }}
      role="link"
      tabIndex={0}
      className={cn(
        'flex items-center gap-4 rounded-lg px-4 py-3 border transition-colors cursor-pointer focus:outline-none focus:ring-2 focus:ring-temper-accent/50',
        instant
          ? 'bg-red-950/10 border-red-500/20 hover:bg-red-950/20'
          : 'bg-temper-panel border-temper-border hover:bg-temper-surface',
        wf.status === 'failed' && !instant && 'border-[var(--badge-failed-border)]/30',
      )}
    >
      {/* Checkbox */}
      <input
        type="checkbox"
        checked={selected.has(wf.id)}
        onChange={() => onToggleSelect(wf.id)}
        onClick={(e) => e.stopPropagation()}
        className="shrink-0 accent-temper-accent w-4 h-4 border-2 border-temper-border rounded"
        aria-label={`Select ${wf.workflow_name} for comparison`}
      />

      {/* Name + ID */}
      <div className="flex-1 min-w-0">
        <span className="text-sm font-medium text-temper-text truncate block">
          {wf.workflow_name}
        </span>
        <span className="text-[10px] font-mono text-temper-text-dim">{shortId}</span>
      </div>

      {/* Status + stale badge + cancel */}
      <div className="flex items-center gap-1.5 shrink-0">
        <StatusBadge status={wf.status} />
        {instant && (
          <span
            className="text-[10px] px-1.5 py-0.5 rounded bg-red-500/15 text-red-400 border border-red-500/20 font-medium"
            title="Run completed with 0 tokens — all agents likely failed"
          >
            0 tok
          </span>
        )}
        {stale && (
          <span
            className="text-[10px] px-1.5 py-0.5 rounded bg-yellow-500/20 text-yellow-400 border border-yellow-500/30 font-medium"
            title="This run has been running for over 30 minutes"
          >
            stale?
          </span>
        )}
        {wf.status === 'running' && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              cancelMutation.mutate(wf.id);
            }}
            disabled={cancelMutation.isPending}
            className={cn(
              'text-[10px] px-2 py-0.5 rounded border transition-colors',
              'bg-temper-surface text-temper-text-muted border-temper-border',
              'hover:bg-red-500/10 hover:text-red-400 hover:border-red-500/30',
              'disabled:opacity-50 disabled:cursor-not-allowed',
            )}
            aria-label={`Cancel workflow ${wf.workflow_name}`}
          >
            {cancelMutation.isPending ? 'Cancelling…' : 'Cancel'}
          </button>
        )}
        {cancelMutation.isError && (
          <span className="text-[10px] text-red-400" title={cancelMutation.error.message}>
            cancel failed
          </span>
        )}
      </div>

      {/* Relative time */}
      <span className="text-xs text-temper-text-muted w-36 shrink-0">
        {wf.start_time ? formatRelativeTime(wf.start_time) : '-'}
      </span>

      {/* Duration */}
      <span className="text-xs font-mono text-temper-text-muted w-16 text-right shrink-0">
        {formatDuration(wf.duration_seconds)}
      </span>

      {/* Tokens + cost */}
      <span className="text-xs font-mono text-temper-text-muted w-32 text-right shrink-0">
        {hasTokenInfo ? (
          <>
            <span className="text-temper-text-dim">{formatTokens(wf.total_tokens)}</span>
            <span className="text-temper-text-dim mx-1">tok</span>
            <span className="text-temper-accent/70">·</span>
            <span className="ml-1 text-temper-text-dim">{formatCost(wf.total_cost_usd)}</span>
          </>
        ) : (
          <span className="text-temper-text-dim">—</span>
        )}
      </span>

      {/* LLM / tool calls */}
      <span className="text-xs font-mono text-temper-text-muted w-24 text-right shrink-0">
        {wf.total_llm_calls != null || wf.total_tool_calls != null ? (
          <>
            <span title="LLM calls">{wf.total_llm_calls ?? 0}L</span>
            <span className="text-temper-text-dim mx-0.5">/</span>
            <span title="Tool calls">{wf.total_tool_calls ?? 0}T</span>
          </>
        ) : (
          <span className="text-temper-text-dim">—</span>
        )}
      </span>

      {/* Studio link */}
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

// ---------------------------------------------------------------------------
// NewRunModal
// ---------------------------------------------------------------------------

function NewRunModal({
  open,
  onClose,
  onSuccess,
}: {
  open: boolean;
  onClose: () => void;
  onSuccess: (executionId: string) => void;
}) {
  const [selectedWorkflow, setSelectedWorkflow] = useState('');
  const [inputsJson, setInputsJson] = useState('{}');
  const [jsonError, setJsonError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Fetch available workflow configs
  const { data: configList, isLoading: configsLoading } = useQuery<WorkflowConfigList>({
    queryKey: ['studio', 'configs', 'workflow'],
    queryFn: async () => {
      const res = await authFetch('/api/studio/configs/workflow');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
    enabled: open,
  });

  const workflowNames = useMemo(
    () => (configList?.configs ?? []).map((c) => c.name).sort(),
    [configList],
  );

  // Auto-select first workflow when list loads
  useEffect(() => {
    if (workflowNames.length > 0 && !selectedWorkflow) {
      setSelectedWorkflow(workflowNames[0]);
    }
  }, [workflowNames, selectedWorkflow]);

  const runMutation = useMutation<
    RunResponse,
    Error,
    { workflow: string; inputs: Record<string, unknown> }
  >({
    mutationFn: async ({ workflow, inputs }) => {
      const res = await authFetch('/api/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workflow, inputs }),
      });
      if (!res.ok) {
        const body = await res.text().catch(() => '');
        throw new Error(body || `HTTP ${res.status}`);
      }
      return res.json();
    },
    onSuccess: (data) => {
      onSuccess(data.execution_id);
    },
  });

  function handleRun() {
    setJsonError(null);
    let parsedInputs: Record<string, unknown> = {};
    try {
      const parsed = JSON.parse(inputsJson.trim() || '{}');
      if (typeof parsed !== 'object' || Array.isArray(parsed) || parsed === null) {
        setJsonError('Inputs must be a JSON object, e.g. {"key": "value"}');
        return;
      }
      parsedInputs = parsed;
    } catch {
      setJsonError('Invalid JSON — check your syntax.');
      return;
    }
    if (!selectedWorkflow) {
      setJsonError('Please select a workflow.');
      return;
    }
    runMutation.mutate({ workflow: selectedWorkflow, inputs: parsedInputs });
  }

  // Reset state when dialog closes
  function handleOpenChange(isOpen: boolean) {
    if (!isOpen) {
      setSelectedWorkflow('');
      setInputsJson('{}');
      setJsonError(null);
      runMutation.reset();
      onClose();
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={handleOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <Dialog.Content
          className={cn(
            'fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50',
            'w-full max-w-lg rounded-xl bg-temper-panel border border-temper-border shadow-2xl',
            'p-6 flex flex-col gap-5',
            'data-[state=open]:animate-in data-[state=closed]:animate-out',
            'data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0',
            'data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95',
            'data-[state=closed]:slide-out-to-left-1/2 data-[state=closed]:slide-out-to-top-[48%]',
            'data-[state=open]:slide-in-from-left-1/2 data-[state=open]:slide-in-from-top-[48%]',
          )}
          aria-describedby="new-run-description"
        >
          {/* Header */}
          <div className="flex items-center justify-between">
            <Dialog.Title className="text-base font-semibold text-temper-text">
              New Run
            </Dialog.Title>
            <Dialog.Close
              className="rounded p-1 text-temper-text-muted hover:text-temper-text hover:bg-temper-surface transition-colors focus:outline-none focus:ring-2 focus:ring-temper-accent/50"
              aria-label="Close dialog"
            >
              <X className="w-4 h-4" />
            </Dialog.Close>
          </div>

          <p id="new-run-description" className="text-xs text-temper-text-dim -mt-2">
            Select a workflow, optionally provide JSON inputs, then click Run.
          </p>

          {/* Workflow selector */}
          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="new-run-workflow"
              className="text-xs font-medium text-temper-text-muted"
            >
              Workflow
            </label>
            {configsLoading ? (
              <div className="h-9 rounded-md bg-temper-surface border border-temper-border animate-pulse" />
            ) : (
              <select
                id="new-run-workflow"
                value={selectedWorkflow}
                onChange={(e) => setSelectedWorkflow(e.target.value)}
                className={cn(
                  'h-9 w-full rounded-md bg-temper-surface border border-temper-border',
                  'px-3 text-sm text-temper-text',
                  'focus:outline-none focus:ring-1 focus:ring-temper-accent',
                  'disabled:opacity-50',
                )}
                disabled={runMutation.isPending}
              >
                {workflowNames.length === 0 ? (
                  <option value="">No workflows found</option>
                ) : (
                  workflowNames.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))
                )}
              </select>
            )}
          </div>

          {/* JSON inputs */}
          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="new-run-inputs"
              className="text-xs font-medium text-temper-text-muted"
            >
              Inputs (JSON)
            </label>
            <textarea
              id="new-run-inputs"
              ref={textareaRef}
              value={inputsJson}
              onChange={(e) => {
                setInputsJson(e.target.value);
                setJsonError(null);
              }}
              rows={6}
              spellCheck={false}
              placeholder={'{\n  "key": "value"\n}'}
              className={cn(
                'w-full rounded-md bg-temper-surface border px-3 py-2',
                'text-sm font-mono text-temper-text placeholder:text-temper-text-dim',
                'resize-y focus:outline-none focus:ring-1 focus:ring-temper-accent',
                'disabled:opacity-50',
                jsonError ? 'border-red-500/60' : 'border-temper-border',
              )}
              disabled={runMutation.isPending}
              aria-describedby={jsonError ? 'json-error' : undefined}
              aria-invalid={!!jsonError}
            />
            {jsonError && (
              <span id="json-error" className="text-xs text-red-400" role="alert">
                {jsonError}
              </span>
            )}
          </div>

          {/* Run error */}
          {runMutation.isError && (
            <div className="rounded-md bg-red-500/10 border border-red-500/20 px-3 py-2 text-xs text-red-400" role="alert">
              {runMutation.error.message}
            </div>
          )}

          {/* Footer */}
          <div className="flex justify-end gap-2 pt-1">
            <Dialog.Close
              className={cn(
                'px-3 py-1.5 rounded-md text-xs font-medium transition-colors',
                'bg-temper-surface text-temper-text-muted border border-temper-border',
                'hover:text-temper-text hover:bg-temper-surface/80',
                'focus:outline-none focus:ring-1 focus:ring-temper-accent',
              )}
            >
              Cancel
            </Dialog.Close>
            <button
              onClick={handleRun}
              disabled={runMutation.isPending || !selectedWorkflow}
              className={cn(
                'flex items-center gap-1.5 px-4 py-1.5 rounded-md text-xs font-medium transition-colors',
                'bg-temper-accent text-white hover:opacity-90',
                'focus:outline-none focus:ring-2 focus:ring-temper-accent/50',
                'disabled:opacity-50 disabled:cursor-not-allowed',
              )}
            >
              <Play className="w-3 h-3" />
              {runMutation.isPending ? 'Starting…' : 'Run'}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

// ---------------------------------------------------------------------------
// WorkflowList (page)
// ---------------------------------------------------------------------------

export function WorkflowList() {
  const navigate = useNavigate();
  const [newRunOpen, setNewRunOpen] = useState(false);

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
            {/* New Run button */}
            <button
              onClick={() => setNewRunOpen(true)}
              className="flex items-center gap-1.5 px-3 py-1 rounded-md text-xs font-medium bg-temper-accent text-white hover:opacity-90 transition-colors focus:outline-none focus:ring-2 focus:ring-temper-accent/50"
              aria-label="Start a new workflow run"
            >
              <Play className="w-3 h-3" />
              New Run
            </button>

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

      {/* Column headers */}
      {sorted.length > 0 && (
        <div className="px-6 pt-3 pb-1 max-w-[1600px] mx-auto w-full shrink-0">
          <div className="flex items-center gap-4 px-4 text-[10px] font-medium text-temper-text-dim uppercase tracking-wide">
            <span className="w-4 shrink-0" aria-hidden="true" />
            <span className="flex-1 min-w-0">Workflow</span>
            {/* status + cancel zone */}
            <span className="shrink-0 w-32">Status</span>
            <span className="w-36 shrink-0">Time</span>
            <span className="w-16 text-right shrink-0">Duration</span>
            <span className="w-32 text-right shrink-0">Tokens / Cost</span>
            <span className="w-24 text-right shrink-0">LLM/Tools</span>
            <span className="shrink-0 w-10" aria-hidden="true" />
          </div>
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-6 pt-2 max-w-[1600px] mx-auto w-full">
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
                      <WorkflowRow
                        key={wf.id}
                        wf={wf}
                        selected={selected}
                        onToggleSelect={toggleSelect}
                        onNavigate={navigate}
                      />
                    ))}
                  </div>
                </div>
              ))
            ) : (
              sorted.map((wf) => (
                <WorkflowRow
                  key={wf.id}
                  wf={wf}
                  selected={selected}
                  onToggleSelect={toggleSelect}
                  onNavigate={navigate}
                />
              ))
            )}
          </div>
        )}
      </div>

      {/* New Run modal */}
      <NewRunModal
        open={newRunOpen}
        onClose={() => setNewRunOpen(false)}
        onSuccess={(executionId) => {
          setNewRunOpen(false);
          navigate(`/app/workflow/${executionId}`);
        }}
      />
    </div>
  );
}
