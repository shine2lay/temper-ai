import { useQuery } from '@tanstack/react-query';
import { fetchTeamRoles, fetchTeamTrials, teamKeys } from '@/lib/teamApi';
import { TEAM_TRIALS_POLL_MS, trialRows, trialsRead, type TrialRow } from '@/lib/teamTrials';
import type { TeamRoles, TeamTrialsPage } from '@/types/team';

/** A list read: what is on screen, and whether the last read of it failed. */
export interface TeamListRead<T> {
  data: T | null;
  /** The first read is still on its way. */
  loading: boolean;
  /** The last read failed: kept data stays on screen, marked not current. */
  failedAt: number | null;
  /** The read failed and there is nothing to show; the error says why. */
  error: unknown;
  /** When the data on screen was read. */
  updatedAt: number | null;
  refresh: () => void;
}

/** How often a list that couldn't be read is tried again (SPEC 2 and 4: every 5 s while open). */
export const TEAM_LIST_RETRY_MS = 5_000;

/**
 * One page of the trials list. While the Trials tab is open it is read
 * every 5 s (`poll`); a read that fails keeps the rows on screen.
 */
export function useTeamTrials(
  page: number,
  { poll }: { poll: boolean },
): TeamListRead<TeamTrialsPage> & { rows: TrialRow[] } {
  const read = trialsRead(page);
  const query = useQuery({
    queryKey: teamKeys.trials(read.limit, read.offset),
    queryFn: () => fetchTeamTrials(read.limit, read.offset),
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: poll ? 0 : 30_000,
    refetchInterval: poll ? TEAM_TRIALS_POLL_MS : false,
  });
  const data = query.data ?? null;
  return {
    data,
    rows: data ? trialRows(data.trials, read.lead) : [],
    loading: query.isPending && query.fetchStatus !== 'idle',
    failedAt: data && query.isError ? query.errorUpdatedAt : null,
    error: data ? null : query.error,
    updatedAt: data ? query.dataUpdatedAt : null,
    refresh: () => void query.refetch(),
  };
}

/**
 * The box's role list, read once; tried again every 5 s while it can't be
 * read (L4). "Not set up" is an answer, not a failure: nothing more to read.
 */
export function useTeamRoles(): TeamListRead<TeamRoles> {
  const query = useQuery({
    queryKey: teamKeys.roles,
    queryFn: fetchTeamRoles,
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 30_000,
    refetchInterval: (q) => (q.state.status === 'error' ? TEAM_LIST_RETRY_MS : false),
  });
  const data = query.data ?? null;
  return {
    data,
    loading: query.isPending && query.fetchStatus !== 'idle',
    failedAt: data && query.isError ? query.errorUpdatedAt : null,
    error: data ? null : query.error,
    updatedAt: data ? query.dataUpdatedAt : null,
    refresh: () => void query.refetch(),
  };
}
