/**
 * Checkpoint panel — shows checkpoint history for a workflow execution.
 * Allows resuming from the last checkpoint or forking from a specific point.
 * Clicking a checkpoint highlights the DAG state at that point.
 */
import { useState, useCallback } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { useExecutionStore } from '@/store/executionStore';
import { authFetch } from '@/lib/authFetch';
import { formatDuration, formatTimestamp, cn } from '@/lib/utils';

interface Checkpoint {
  id: string;
  sequence: number;
  event_type: string;
  node_name: string | null;
  agent_name: string | null;
  status: string;
  cost_usd: number;
  total_tokens: number;
  duration_seconds: number;
  error: string | null;
  metadata: Record<string, unknown>;
  timestamp: string;
}

interface CheckpointResponse {
  execution_id: string;
  checkpoints: Checkpoint[];
  total: number;
}

async function fetchCheckpoints(executionId: string): Promise<CheckpointResponse> {
  const res = await authFetch(`/api/runs/${executionId}/checkpoints`);
  if (!res.ok) throw new Error(`Failed to fetch checkpoints: ${res.status}`);
  return res.json();
}

async function resumeRun(executionId: string): Promise<{ execution_id: string; status: string }> {
  const res = await authFetch(`/api/runs/${executionId}/resume`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  });
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(body || `HTTP ${res.status}`);
  }
  return res.json();
}

async function forkRun(
  sourceExecutionId: string,
  sequence: number,
  workflowName: string,
): Promise<{ execution_id: string; status: string }> {
  const res = await authFetch(`/api/runs/fork`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      source_execution_id: sourceExecutionId,
      sequence,
      workflow: workflowName,
    }),
  });
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(body || `HTTP ${res.status}`);
  }
  return res.json();
}

/** Build sets of completed/failed nodes at a given checkpoint sequence. */
function buildNodeSetsAtSequence(checkpoints: Checkpoint[], targetSequence: number) {
  const completedNodes = new Set<string>();
  const failedNodes = new Set<string>();
  for (const cp of checkpoints) {
    if (cp.sequence > targetSequence) break;
    const name = cp.node_name;
    if (!name) continue;
    if (cp.status === 'completed') {
      completedNodes.add(name);
      failedNodes.delete(name); // could have been retried
    } else if (cp.status === 'failed') {
      failedNodes.add(name);
    }
  }
  return { completedNodes, failedNodes };
}

interface CheckpointPanelProps {
  onSwitchTab?: (tab: string) => void;
}

export function CheckpointPanel({ onSwitchTab }: CheckpointPanelProps) {
  const workflow = useExecutionStore((s) => s.workflow);
  const setCheckpointPreview = useExecutionStore((s) => s.setCheckpointPreview);
  const checkpointPreview = useExecutionStore((s) => s.checkpointPreview);
  const navigate = useNavigate();
  const executionId = workflow?.id;
  const workflowName = workflow?.workflow_name;

  const { data, isLoading, error } = useQuery<CheckpointResponse>({
    queryKey: ['checkpoints', executionId],
    queryFn: () => fetchCheckpoints(executionId!),
    enabled: !!executionId,
  });

  const resumeMutation = useMutation({
    mutationFn: () => resumeRun(executionId!),
    onSuccess: (result) => {
      navigate(`/workflow/${result.execution_id}`);
    },
  });

  const forkMutation = useMutation({
    mutationFn: (sequence: number) => forkRun(executionId!, sequence, workflowName!),
    onSuccess: (result) => {
      navigate(`/workflow/${result.execution_id}`);
    },
  });

  const [selectedCheckpoint, setSelectedCheckpoint] = useState<string | null>(null);

  const handleViewOnDag = useCallback(
    (checkpoints: Checkpoint[], sequence: number) => {
      const { completedNodes, failedNodes } = buildNodeSetsAtSequence(checkpoints, sequence);
      setCheckpointPreview({ sequence, completedNodes, failedNodes });
      onSwitchTab?.('dag');
    },
    [setCheckpointPreview, onSwitchTab],
  );

  const handleClearPreview = useCallback(() => {
    setCheckpointPreview(null);
  }, [setCheckpointPreview]);

  if (!executionId) return null;

  const checkpoints = data?.checkpoints ?? [];
  const isTerminal = workflow?.status !== 'running';
  const hasFailed = checkpoints.some((cp) => cp.status === 'failed');
  const canResume = (workflow?.status === 'failed' || workflow?.status === 'cancelled') ||
    (isTerminal && hasFailed);
  const hasCheckpoints = checkpoints.length > 0;
  const isPreviewActive = checkpointPreview !== null;

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      {/* Header with resume button */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-temper-border/30 shrink-0">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-temper-text">Checkpoints</h3>
          <span className="text-xs text-temper-text-dim">{checkpoints.length} saved</span>
        </div>
        <div className="flex items-center gap-2">
          {isPreviewActive && (
            <button
              onClick={handleClearPreview}
              className="px-2 py-1 rounded text-[10px] font-medium bg-amber-500/15 text-amber-400 hover:bg-amber-500/25 transition-colors"
            >
              Clear DAG preview
            </button>
          )}
          {canResume && hasCheckpoints && (
            <button
              onClick={() => resumeMutation.mutate()}
              disabled={resumeMutation.isPending}
              className={cn(
                'px-3 py-1.5 rounded text-xs font-medium transition-colors',
                'bg-temper-accent text-white hover:bg-temper-accent-dim',
                'disabled:opacity-50 disabled:cursor-not-allowed',
              )}
            >
              {resumeMutation.isPending ? 'Resuming...' : 'Resume from Last Checkpoint'}
            </button>
          )}
        </div>
      </div>

      {/* Error/loading states */}
      {isLoading && (
        <div className="flex-1 flex items-center justify-center text-temper-text-dim text-sm">Loading checkpoints...</div>
      )}
      {error && (
        <div className="px-4 py-3 text-sm text-red-400">Failed to load checkpoints: {(error as Error).message}</div>
      )}
      {resumeMutation.isError && (
        <div className="px-4 py-2 bg-red-500/10 text-xs text-red-400 border-b border-red-500/20 shrink-0">
          Resume failed: {(resumeMutation.error as Error).message}
        </div>
      )}
      {forkMutation.isError && (
        <div className="px-4 py-2 bg-red-500/10 text-xs text-red-400 border-b border-red-500/20 shrink-0">
          Re-run failed: {(forkMutation.error as Error).message}
        </div>
      )}

      {/* Checkpoint list — scrollable */}
      {!isLoading && (
        <div className="flex-1 overflow-y-auto min-h-0">
          {checkpoints.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-temper-text-dim gap-2 px-4">
              <span className="text-2xl">📍</span>
              <span className="text-sm">No checkpoints recorded</span>
              <span className="text-xs text-center">
                Checkpoints are saved automatically after each stage completes.
                {workflow?.status === 'running' && ' They will appear as stages finish.'}
              </span>
            </div>
          ) : (
            <div className="px-4 py-2">
              {/* Timeline */}
              <div className="relative">
                {/* Vertical line */}
                <div className="absolute left-3 top-4 bottom-4 w-px bg-temper-border/40" />

                {checkpoints.map((cp, idx) => {
                  const isLast = idx === checkpoints.length - 1;
                  const isSelected = selectedCheckpoint === cp.id;
                  const isCompleted = cp.status === 'completed';
                  const isFailed = cp.status === 'failed';
                  const isRewind = cp.event_type === 'loop_rewind';
                  const canFork = isTerminal && !!workflowName && (isCompleted || isFailed);
                  const isPreviewed = checkpointPreview?.sequence === cp.sequence;

                  return (
                    <div
                      key={cp.id}
                      onClick={() => setSelectedCheckpoint(isSelected ? null : cp.id)}
                      className={cn(
                        'relative pl-8 py-2 cursor-pointer rounded transition-colors',
                        isPreviewed
                          ? 'bg-amber-500/15 ring-1 ring-amber-500/30'
                          : isSelected
                            ? 'bg-temper-accent/10'
                            : 'hover:bg-temper-surface/50',
                      )}
                    >
                      {/* Dot on timeline */}
                      <div className={cn(
                        'absolute left-1.5 top-3.5 w-3 h-3 rounded-full border-2',
                        isRewind ? 'bg-amber-400 border-amber-600' :
                        isFailed ? 'bg-red-400 border-red-600' :
                        isCompleted ? 'bg-emerald-400 border-emerald-600' :
                        'bg-temper-text-dim border-temper-border',
                        isLast && 'ring-2 ring-temper-accent/30',
                      )} />

                      {/* Content */}
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium text-temper-text">
                          {cp.node_name ?? 'unknown'}
                        </span>
                        <span className={cn(
                          'text-[9px] px-1 py-px rounded',
                          isRewind ? 'bg-amber-500/15 text-amber-400' :
                          isFailed ? 'bg-red-500/15 text-red-400' :
                          isCompleted ? 'bg-emerald-500/15 text-emerald-400' :
                          'bg-gray-500/15 text-temper-text-dim',
                        )}>
                          {isRewind ? 'loop rewind' : cp.status}
                        </span>
                        {isPreviewed && (
                          <span className="text-[9px] px-1 py-px rounded bg-amber-500/20 text-amber-400">
                            viewing
                          </span>
                        )}
                        <span className="text-[10px] text-temper-text-dim ml-auto">
                          #{cp.sequence}
                        </span>
                      </div>

                      <div className="flex items-center gap-3 mt-0.5 text-[10px] text-temper-text-dim">
                        <span>{formatDuration(cp.duration_seconds)}</span>
                        {cp.total_tokens > 0 && <span>{cp.total_tokens.toLocaleString()} tok</span>}
                        {cp.cost_usd > 0 && <span>${cp.cost_usd.toFixed(4)}</span>}
                        <span>{formatTimestamp(cp.timestamp)}</span>
                      </div>

                      {/* Expanded details */}
                      {isSelected && (
                        <div className="mt-2 p-2 bg-temper-surface/50 rounded text-[10px] text-temper-text-dim space-y-1">
                          <div>Type: {cp.event_type}</div>
                          {cp.agent_name && <div>Agent: {cp.agent_name}</div>}
                          {cp.error && <div className="text-red-400">Error: {cp.error}</div>}
                          {Object.keys(cp.metadata).length > 0 && (
                            <div>Metadata: {JSON.stringify(cp.metadata)}</div>
                          )}

                          <div className="mt-2 pt-2 border-t border-temper-border/30 flex items-center gap-2 flex-wrap">
                            {/* View on DAG */}
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                handleViewOnDag(checkpoints, cp.sequence);
                              }}
                              className={cn(
                                'px-2 py-1 rounded text-[10px] font-medium transition-colors',
                                isPreviewed
                                  ? 'bg-amber-500/30 text-amber-300'
                                  : 'bg-amber-500/15 text-amber-400 hover:bg-amber-500/25',
                              )}
                            >
                              {isPreviewed ? 'Viewing on DAG' : 'View on DAG'}
                            </button>

                            {/* Re-run from here (fork) */}
                            {canFork && (
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  forkMutation.mutate(cp.sequence);
                                }}
                                disabled={forkMutation.isPending}
                                className={cn(
                                  'px-2 py-1 rounded text-[10px] font-medium transition-colors',
                                  'bg-temper-accent/20 text-temper-accent hover:bg-temper-accent/30',
                                  'disabled:opacity-50 disabled:cursor-not-allowed',
                                )}
                              >
                                {forkMutation.isPending ? 'Starting...' : 'Re-run from here'}
                              </button>
                            )}
                          </div>

                          {/* Resume hint for last checkpoint on failed/cancelled runs */}
                          {isLast && canResume && (
                            <div className="mt-1 pt-1 border-t border-temper-border/30">
                              <span className="text-temper-accent text-[9px]">
                                ↑ Use "Resume from Last Checkpoint" to continue from this point
                              </span>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
