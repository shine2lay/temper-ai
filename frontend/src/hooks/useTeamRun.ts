import { useQuery } from '@tanstack/react-query';
import { fetchTeamRun, teamKeys, TeamApiError } from '@/lib/teamApi';
import { teamRunEnded } from '@/lib/teamText';
import type { TeamRun } from '@/types/team';

/** How often a live run is read again (Design's spec, section 6). */
export const TEAM_RUN_POLL_MS = 5_000;

export interface TeamRunRead {
  run: TeamRun | null;
  /** The first read is still on its way. */
  loading: boolean;
  /** The run isn't a team trial (or doesn't exist): Temper's own words. */
  notTeam: string | null;
  /** The last read failed: kept data stays on screen, marked not current. */
  failedAt: number | null;
  /** When the data on screen was read. */
  updatedAt: number | null;
  /** The first read failed and there is nothing to show. */
  firstReadFailed: boolean;
  ended: boolean;
  refresh: () => void;
}

/**
 * A team run, read every 5 s while it is live and never again once it has
 * ended. A read that fails keeps the last answer on screen; the page says
 * it is not current and keeps trying on the same 5 s beat.
 */
export function useTeamRun(executionId: string, { enabled = true }: { enabled?: boolean } = {}): TeamRunRead {
  const query = useQuery({
    queryKey: teamKeys.run(executionId),
    queryFn: () => fetchTeamRun(executionId),
    enabled: enabled && executionId !== '',
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 0,
    refetchInterval: (q) => {
      const data = q.state.data;
      if (data && teamRunEnded(data)) return false;
      // Not a team trial: nothing to keep reading.
      if (!data && q.state.error instanceof TeamApiError && q.state.error.status === 404) return false;
      return TEAM_RUN_POLL_MS;
    },
  });

  const run = query.data ?? null;
  const error = query.error;
  const notTeam =
    !run && error instanceof TeamApiError && error.status === 404
      ? typeof error.detail === 'string'
        ? error.detail
        : 'not a team trial, or no such run'
      : null;
  const failedAt = run && query.isError ? query.errorUpdatedAt : null;

  return {
    run,
    loading: query.isPending && query.fetchStatus !== 'idle',
    notTeam,
    failedAt,
    updatedAt: run ? query.dataUpdatedAt : null,
    firstReadFailed: !run && query.isError && notTeam === null,
    ended: run ? teamRunEnded(run) : false,
    refresh: () => {
      void query.refetch();
    },
  };
}
