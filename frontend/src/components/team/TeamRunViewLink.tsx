import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { Users } from 'lucide-react';
import { useTeamStatus } from '@/hooks/useTeamStatus';
import { fetchTeamRun, teamKeys } from '@/lib/teamApi';

/**
 * The run page's way into the Team run view. It shows only when the Team
 * switch is on and Temper says this run is a team trial; with the switch
 * off it asks nothing and renders nothing.
 */
export function TeamRunViewLink({ executionId, className }: { executionId: string; className?: string }) {
  const team = useTeamStatus();
  const isTeamRun = useQuery({
    queryKey: teamKeys.run(executionId),
    queryFn: () => fetchTeamRun(executionId),
    enabled: team.on && executionId !== '',
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 30_000,
  });
  if (!team.on || !isTeamRun.data) return null;
  return (
    <Link to={`/team/runs/${encodeURIComponent(executionId)}`} className={className}>
      <Users className="w-3 h-3" aria-hidden="true" />
      Team run view
    </Link>
  );
}
