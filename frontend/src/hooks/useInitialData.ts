import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useExecutionStore } from '@/store/executionStore';
import { authFetch } from '@/lib/authFetch';
import type { WorkflowExecution } from '@/types';

/**
 * TanStack Query hook that fetches initial workflow data via REST.
 * Only fires when the store has no data yet (i.e. the WS snapshot
 * has not arrived first). Handles the race between WS snapshot
 * and REST response by checking store emptiness before applying.
 */
export function useInitialData(workflowId: string | undefined) {
  const hasData = useExecutionStore((s) => s.workflow !== null);
  const applySnapshot = useExecutionStore((s) => s.applySnapshot);
  const reset = useExecutionStore((s) => s.reset);

  // Reset store when navigating to a different workflow
  useEffect(() => {
    reset();
  }, [workflowId, reset]);

  const query = useQuery<WorkflowExecution>({
    queryKey: ['workflow', workflowId],
    queryFn: () =>
      authFetch(`/api/workflows/${workflowId}`).then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<WorkflowExecution>;
      }),
    enabled: !!workflowId && !hasData,
  });

  // Apply snapshot only if store is still empty when data arrives
  useEffect(() => {
    if (query.data && !hasData) {
      applySnapshot(query.data);
    }
  }, [query.data, hasData, applySnapshot]);

  return query;
}
