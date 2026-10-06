import { useDocumentTitle } from '@/hooks/useDocumentTitle';
import { TeamNote } from '@/components/team/TeamNote';
import { TeamPageHeader } from '@/components/team/TeamPageHeader';

/** New trial: the form's own page. */
export default function TeamNewTrial() {
  useDocumentTitle('New trial');
  return (
    <div className="flex h-full flex-col overflow-auto bg-temper-bg">
      <TeamPageHeader tab={null} />
      <div className="px-6 py-4">
        <TeamNote tone="neutral">Starting a trial from here is still being built.</TeamNote>
      </div>
    </div>
  );
}
