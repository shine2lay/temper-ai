import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useExecutionStore } from '@/store/executionStore';
import { authFetch } from '@/lib/authFetch';
import type { WorkflowExecution } from '@/types';

const POLL_INTERVAL_MS = 5_000;

/**
 * Build a fingerprint of the structural data that matters for the DAG.
 * Only when this changes do we need to re-apply the snapshot.
 */
export function snapshotFingerprint(wf: WorkflowExecution): string {
  const parts: string[] = [wf.status];
  // The whole tree, not the top level: the API nests a dispatcher's
  // children inside it, so a run whose work all happens in dispatched
  // nodes looked unchanged from its first poll to its last.
  const walk = (nodes: WorkflowExecution['nodes'] | undefined, depth: number) => {
    for (const node of nodes ?? []) {
      const agentKeys = (node.agents ?? []).map(
        (a) => `${a.agent_name}:${a.status}`,
      );
      if (node.agent) agentKeys.push(`${node.agent.agent_name}:${node.agent.status}`);
      parts.push(`${depth}:${node.name}:${node.status}:${node.type}:[${agentKeys.join(',')}]`);
      walk(node.child_nodes, depth + 1);
    }
  };
  walk(wf.nodes, 0);
  return parts.join('|');
}

/**
 * TanStack Query hook that fetches workflow data via REST.
 *
 * - First fetch: loads initial data.
 * - While running: polls every 5s, but only applies snapshot when the
 *   structure changes (new nodes, status transitions) to avoid redrawing
 *   the DAG unnecessarily.
 * - After completion: stops polling.
 */
/**
 * Statuses that mean "this run can still change". `running` alone was too
 * narrow: external-mode runs sit at `queued` until a worker claims them, and
 * a run parked at a human gate reports `waiting` — in both cases the view
 * froze until the user reloaded by hand.
 */
const ACTIVE_STATUSES = new Set([
  'running',
  'queued',
  'pending',
  'waiting',
  'resuming',
  'cancelling',
]);

export function useInitialData(workflowId: string | undefined) {
  const isRunning = useExecutionStore((s) => {
    const status = s.workflow?.status;
    return !status || ACTIVE_STATUSES.has(status);
  });
  const applySnapshot = useExecutionStore((s) => s.applySnapshot);
  const reset = useExecutionStore((s) => s.reset);
  const lastFingerprint = useRef('');

  // Reset store when navigating to a different workflow
  useEffect(() => {
    reset();
    lastFingerprint.current = '';
  }, [workflowId, reset]);

  const query = useQuery<WorkflowExecution>({
    queryKey: ['workflow', workflowId],
    queryFn: () =>
      authFetch(`/api/workflows/${workflowId}`).then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<WorkflowExecution>;
      }),
    enabled: !!workflowId,
    // Poll while the run can still change so the DAG picks up new nodes and
    // agents. Keep polling when the tab is in the background: runs are often
    // watched on a second screen, and react-query pauses interval refetches
    // for unfocused tabs by default.
    refetchInterval: isRunning ? POLL_INTERVAL_MS : false,
    refetchIntervalInBackground: isRunning,
  });

  // Apply snapshot only when structural data actually changed
  useEffect(() => {
    if (!query.data) return;
    const fp = snapshotFingerprint(query.data);
    if (fp !== lastFingerprint.current) {
      lastFingerprint.current = fp;
      applySnapshot(query.data);
    }
  }, [query.data, applySnapshot]);

  return query;
}
