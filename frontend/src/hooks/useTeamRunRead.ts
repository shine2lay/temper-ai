import { useQuery } from '@tanstack/react-query';
import { useTeamStatus } from '@/hooks/useTeamStatus';
import { fetchTeamRun, teamKeys } from '@/lib/teamApi';

/**
 * The run page's one read of GET /api/team/runs/{id}: whether the run is a
 * team trial, and which kind. Asked only when the Team switch is on; a run
 * that isn't a team trial answers 404 and is left at that (no retry).
 */
export function useTeamRunRead(executionId: string) {
  const team = useTeamStatus();
  const read = useQuery({
    queryKey: teamKeys.run(executionId),
    queryFn: () => fetchTeamRun(executionId),
    enabled: team.on && executionId !== '',
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 30_000,
  });
  return { on: team.on, run: team.on ? (read.data ?? null) : null };
}

/**
 * Whether the run page's re-run, fork and resume stay. Only a team run whose
 * reply says kind 'rounds' loses them: Temper keeps an old review-round run
 * read-only and refuses all three ("this team ran in review rounds, which
 * Temper no longer runs; start a new Project"). Any other run, a team run
 * without a kind (today's server) and every run while the answer is out keep
 * them, as today.
 */
export function useRunActionsAllowed(executionId: string): boolean {
  const { run } = useTeamRunRead(executionId);
  return run?.kind !== 'rounds';
}
