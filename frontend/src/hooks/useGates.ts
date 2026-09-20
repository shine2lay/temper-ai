import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useExecutionStore } from '@/store/executionStore';
import { authFetch } from '@/lib/authFetch';

const GATE_POLL_INTERVAL_MS = 3_000;

/** One option of a question an upstream node asked (the ask_user_question shape). */
export interface GateQuestionOption {
  label: string;
  description?: string;
  preview?: string;
}

/** A question the previous node asked the human, normalised by the backend. */
export interface GateQuestion {
  id: string;
  question: string;
  header?: string;
  detail?: string;
  options?: GateQuestionOption[];
  multiSelect?: boolean;
  /** Which upstream node asked it. */
  node?: string;
}

/** What one upstream node produced — the thing being approved. */
export interface GateUpstream {
  node: string;
  /** What to show: the output, or its prose when the rest was the questions. */
  output: string;
  /** The whole output, when it is not what `output` already shows. */
  full_output?: string;
  structured_output?: Record<string, unknown> | null;
}

export interface WaitingGate {
  node_name: string;
  status: string;
  /** Id of the waiting event: a loop gating the same node again is a new gate. */
  event_id: string | null;
  upstream: GateUpstream[];
  questions: GateQuestion[];
}

/** The human's answer to one question. */
export interface GateAnswer {
  id: string;
  question: string;
  selected: string[];
  custom: string;
}

export interface GateApproval {
  nodeName: string;
  response?: string;
  answers?: GateAnswer[];
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
 *
 * A gate carries what the previous node produced and any questions it asked,
 * and approval carries the answers back — see GateModal.
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
    mutationFn: async ({ nodeName, response, answers }: GateApproval) => {
      const res = await authFetch(`/api/runs/${executionId}/approve/${nodeName}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ response: response ?? '', answers: answers ?? [] }),
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
