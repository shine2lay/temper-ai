import { useDocumentTitle } from '@/hooks/useDocumentTitle';
import { TeamNote } from '@/components/team/TeamNote';
import { TeamPageHeader, type TeamTab } from '@/components/team/TeamPageHeader';

const BEING_BUILT: Record<TeamTab, string> = {
  trials: 'The trials list is still being built. For now, open a trial from its run page: Team run view.',
  roles: 'The roles list is still being built.',
};

/** The Team page: its header, its tabs and the open tab. */
export default function TeamPage({ tab }: { tab: TeamTab }) {
  useDocumentTitle(tab === 'roles' ? 'Team roles' : 'Team');
  return (
    <div className="flex h-full flex-col overflow-auto bg-temper-bg">
      <TeamPageHeader tab={tab} />
      <div className="px-6 py-4">
        <TeamNote tone="neutral">{BEING_BUILT[tab]}</TeamNote>
      </div>
    </div>
  );
}
