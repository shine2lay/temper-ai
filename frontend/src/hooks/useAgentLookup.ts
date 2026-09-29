import { useEffect, useRef, useState } from 'react';
import { useExecutionStore } from '@/store/executionStore';
import { authFetch } from '@/lib/authFetch';
import type { AgentIndexEntry } from '@/types';

/** At most one lookup a second, however many agents start. */
export const LOOKUP_INTERVAL_MS = 1_000;
/** Tries per agent before its output is shown unnamed. */
export const MAX_LOOKUPS_PER_AGENT = 5;

/**
 * Names the agents whose output streams in before the page has a record of
 * them. The page otherwise learns agents from the run's snapshot, taken
 * every few seconds; an agent that started since, or a loop round the node
 * tree does not keep, was shown by its id until then, or for good, and its
 * panel had nothing to open. Asks the server's light agent list, not the
 * whole run.
 */
export function useAgentLookup(workflowId: string | undefined): void {
  const unknown = useExecutionStore((s) => s.unknownAgentIds);
  const applyAgentIndex = useExecutionStore((s) => s.applyAgentIndex);
  const giveUpAgentLookup = useExecutionStore((s) => s.giveUpAgentLookup);
  const [attempt, setAttempt] = useState(0);
  const tries = useRef(new Map<string, number>());
  const busy = useRef(false);
  const lastAt = useRef(0);
  const current = useRef(workflowId);

  useEffect(() => {
    current.current = workflowId;
    tries.current = new Map();
  }, [workflowId]);

  useEffect(() => {
    if (!workflowId || busy.current || unknown.size === 0) return;
    const ids = Array.from(unknown);
    const spent = ids.filter((id) => (tries.current.get(id) ?? 0) >= MAX_LOOKUPS_PER_AGENT);
    if (spent.length > 0) {
      giveUpAgentLookup(spent);
      return;
    }
    const wait = Math.max(0, lastAt.current + LOOKUP_INTERVAL_MS - Date.now());
    const timer = setTimeout(() => {
      busy.current = true;
      lastAt.current = Date.now();
      for (const id of ids) tries.current.set(id, (tries.current.get(id) ?? 0) + 1);
      authFetch(`/api/workflows/${workflowId}/agents`)
        .then((r) => (r.ok ? (r.json() as Promise<{ agents?: AgentIndexEntry[] }>) : null))
        .then((body) => {
          if (body?.agents && current.current === workflowId) applyAgentIndex(body.agents);
        })
        .catch(() => undefined)
        .finally(() => {
          busy.current = false;
          // Look again for any still unknown, after the interval.
          setAttempt((n) => n + 1);
        });
    }, wait);
    return () => clearTimeout(timer);
  }, [workflowId, unknown, attempt, applyAgentIndex, giveUpAgentLookup]);
}
