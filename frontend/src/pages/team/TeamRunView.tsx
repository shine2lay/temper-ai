import type { ReactNode } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ExternalLink, RefreshCw, WifiOff } from 'lucide-react';
import { useDocumentTitle } from '@/hooks/useDocumentTitle';
import { useTeamRun } from '@/hooks/useTeamRun';
import { clockTime, firstLine } from '@/lib/teamText';
import { TeamNote } from '@/components/team/TeamNote';
import { EngineQuote } from '@/components/team/TeamQuote';
import { teamBtn, teamLink } from '@/components/team/teamUi';
import { RunHeader } from '@/components/team/run/RunHeader';
import { RunStateCard } from '@/components/team/run/RunStateCard';
import { Timeline } from '@/components/team/run/Timeline';
import { WhoDidWhat } from '@/components/team/run/WhoDidWhat';
import { RoundCard } from '@/components/team/run/RoundCard';
import { MembersCard } from '@/components/team/run/MembersCard';
import { GoalCard } from '@/components/team/run/GoalCard';

function TryNow({ onClick }: { onClick: () => void }) {
  return (
    <button type="button" className={teamBtn.secondary} onClick={onClick}>
      <RefreshCw className="h-4 w-4" aria-hidden="true" />
      <span>Try now</span>
    </button>
  );
}

function RunPageLink({ executionId }: { executionId: string }) {
  return (
    <Link to={`/workflow/${executionId}`} className={teamLink}>
      <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
      <span>Open the run page</span>
    </Link>
  );
}

/** A plain frame for the moments there is no run to show yet. */
function Frame({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-full flex-col gap-4 overflow-auto bg-temper-bg px-6 py-4">
      <h1 className="m-0 text-xl font-semibold text-temper-text">Team run</h1>
      {children}
    </div>
  );
}

/**
 * The run view: one team trial, read every 5 s while it is live. This is
 * the read-only view; answering, messages and stopping come with the next
 * part of the page.
 */
export default function TeamRunView() {
  const { executionId = '' } = useParams();
  const read = useTeamRun(executionId);
  const { run } = read;
  useDocumentTitle(run ? `Team: ${firstLine(run.trial.goal) || run.trial_id}` : 'Team run');

  if (!run) {
    if (read.notTeam !== null) {
      return (
        <Frame>
          <TeamNote tone="bad" title="This run isn't a team trial">
            <EngineQuote className="mt-1" label="Temper's answer">
              {read.notTeam}
            </EngineQuote>
            <p className="m-0 mt-2">
              <RunPageLink executionId={executionId} />
            </p>
          </TeamNote>
        </Frame>
      );
    }
    if (read.firstReadFailed) {
      return (
        <Frame>
          <TeamNote tone="bad" live action={<TryNow onClick={read.refresh} />}>
            Couldn&apos;t read this team run. Trying again every 5 s.
          </TeamNote>
        </Frame>
      );
    }
    return (
      <Frame>
        <p role="status" className="m-0 text-sm text-temper-text-muted">
          Reading the team run…
        </p>
      </Frame>
    );
  }

  const stale = read.failedAt !== null;
  return (
    <div className="flex h-full flex-col overflow-auto bg-temper-bg">
      <RunHeader
        run={run}
        updatedAt={read.updatedAt}
        stale={stale}
        live={!read.ended && run.state !== 'interrupted'}
      />
      <div className="flex flex-col gap-4 px-6 pt-4 pb-8">
        {stale && read.failedAt !== null && (
          <TeamNote tone="warn" icon={WifiOff} live action={<TryNow onClick={read.refresh} />}>
            <b className="font-semibold">Couldn&apos;t refresh at {clockTime(read.failedAt)}.</b>{' '}
            <span className="text-temper-text-muted">
              Showing what Temper said at {read.updatedAt !== null ? clockTime(read.updatedAt) : 'the last read'}.
              Trying again every 5 s.
            </span>
          </TeamNote>
        )}
        <RunStateCard run={run} />
        <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(0,1fr)_384px]">
          <div className="flex min-w-0 flex-col gap-4">
            <Timeline run={run} />
            <WhoDidWhat run={run} />
          </div>
          <div className="flex min-w-0 flex-col gap-4">
            <RoundCard run={run} />
            <MembersCard run={run} />
            <GoalCard goal={run.trial.goal} />
          </div>
        </div>
      </div>
    </div>
  );
}
