import { useQuery } from '@tanstack/react-query';
import { fetchTeamStatus, teamKeys } from '@/lib/teamApi';
import type { TeamStatus } from '@/types/team';

/** How often an open Team page reads the status again (guard mode, limits). */
export const TEAM_STATUS_POLL_MS = 60_000;

export interface TeamSwitch {
  /** True only when GET /api/team/status answered 200. */
  on: boolean;
  /** False until the first answer (or failure) is in: render nothing yet. */
  settled: boolean;
  status: TeamStatus | null;
}

/**
 * The Team switch, read once per app load.
 *
 * The Team is on only when /api/team/status answers 200. A 404 (switch
 * off), any other error and the wait for the first answer all mean off, so
 * nothing Team-shaped ever shows on a server without it. Team pages pass
 * `poll` to read it again every 60 s while they are open.
 */
export function useTeamStatus({ poll = false }: { poll?: boolean } = {}): TeamSwitch {
  const query = useQuery({
    queryKey: teamKeys.status,
    queryFn: fetchTeamStatus,
    staleTime: Infinity,
    gcTime: Infinity,
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    refetchOnMount: false,
    refetchInterval: poll ? TEAM_STATUS_POLL_MS : false,
  });
  const status = query.data ?? null;
  return { on: status !== null, settled: !query.isPending, status };
}
