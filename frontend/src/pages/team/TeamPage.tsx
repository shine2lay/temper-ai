import { useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useDocumentTitle } from '@/hooks/useDocumentTitle';
import { useTeamStatus } from '@/hooks/useTeamStatus';
import { useTeamRoles, useTeamTrials } from '@/hooks/useTeamLists';
import { lastTrialsPage } from '@/lib/teamTrials';
import { TeamGuardBanner } from '@/components/team/TeamGuardBanner';
import { TeamPageHeader, type TeamTab } from '@/components/team/TeamPageHeader';
import { TrialsList } from '@/components/team/trials/TrialsList';
import { RolesTable } from '@/components/team/roles/RolesTable';

/** The page in the address (?page=2), 0-based here; page 1 has no parameter. */
function pageOf(params: URLSearchParams): number {
  const n = Number(params.get('page'));
  return Number.isInteger(n) && n > 1 ? n - 1 : 0;
}

/**
 * The Team page: its header, its tabs and the open tab. The trials list
 * is read every 5 s while its tab is open; the role list once (and every
 * 5 s while it can't be read). Both feed the tabs' counts.
 */
export default function TeamPage({ tab }: { tab: TeamTab }) {
  useDocumentTitle(tab === 'roles' ? 'Team roles' : 'Team');
  const [params, setParams] = useSearchParams();
  const page = tab === 'trials' ? pageOf(params) : 0;
  const { status } = useTeamStatus();
  const trials = useTeamTrials(page, { poll: tab === 'trials' });
  const roles = useTeamRoles();
  const total = trials.data?.total ?? null;

  // A page past the end (the list got shorter): go to the last page that has rows.
  useEffect(() => {
    if (tab !== 'trials' || total === null) return;
    const last = lastTrialsPage(total);
    if (page > last) setParams(last > 0 ? { page: String(last + 1) } : {}, { replace: true });
  }, [tab, total, page, setParams]);

  function goTo(next: number) {
    setParams(next > 0 ? { page: String(next + 1) } : {});
  }

  const open = tab === 'trials' ? trials : roles;
  const roleCount = roles.data ? (roles.data.configured ? roles.data.roles.length : 0) : null;
  return (
    <div className="flex h-full flex-col overflow-auto bg-temper-bg">
      <TeamPageHeader
        tab={tab}
        counts={{ trials: total, roles: roleCount }}
        updatedAt={open.updatedAt}
        stale={open.failedAt !== null}
      />
      <div className="flex flex-col gap-4 px-6 py-4">
        <TeamGuardBanner mode={status?.guard_mode} />
        {tab === 'trials' ? (
          <TrialsList read={trials} rows={trials.rows} page={page} onPage={goTo} />
        ) : (
          <RolesTable read={roles} />
        )}
      </div>
    </div>
  );
}
