import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useExecutionStore } from '@/store/executionStore';
import { authFetch } from '@/lib/authFetch';

const GATE_POLL_INTERVAL_MS = 3_000;

export interface WaitingGate {
  node_name: string;
  status: string;
}

/** Statuses in which a run may still be parked at a gate. */
const ACTIVE_STATUSES = new Set([
  'running',
  'queued',
  'pending',
  'waiting',
  'resuming',
  'cancelling',
]);

/**
 * Human-approval gates for a run.
 *
 * A workflow node with `gate: true` pauses until someone approves it. The
 * engine and the API have supported this for a long time, but nothing in the
 * dashboard ever read `/gates` or called `/approve`, so a gated workflow
 * looked like it had silently stalled and could only be released with curl.
 */
export function useGates(executionId: string | undefined) {
  const queryClient = useQueryClient();
  const isActive = useExecutionStore((s) => {
    const status = s.workflow?.status;
    return !status || ACTIVE_STATUSES.has(status);
  });

  const query = useQuery<WaitingGate[]>({
    queryKey: ['gates', executionId],
    queryFn: async () => {
      const res = await authFetch(`/api/runs/${executionId}/gates`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body = await res.json();
      return body.gates ?? [];
    },
    enabled: !!executionId && isActive,
    refetchInterval: isActive ? GATE_POLL_INTERVAL_MS : false,
    refetchIntervalInBackground: isActive,
  });

  const approve = useMutation({
    mutationFn: async (nodeName: string) => {
      const res = await authFetch(`/api/runs/${executionId}/approve/${nodeName}`, {
        method: 'POST',
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => null);
        throw new Error(detail?.detail ?? `HTTP ${res.status}`);
      }
      return res.json();
    },
    onSuccess: () => {
      // Refresh both the gate list and the run itself: the node moves on
      // immediately and the DAG should follow without waiting for the poll.
      queryClient.invalidateQueries({ queryKey: ['gates', executionId] });
      queryClient.invalidateQueries({ queryKey: ['workflow', executionId] });
    },
  });

  return { gates: query.data ?? [], approve };
}
