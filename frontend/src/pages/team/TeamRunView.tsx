import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ExternalLink, RefreshCw, WifiOff } from 'lucide-react';
import { useDocumentTitle } from '@/hooks/useDocumentTitle';
import { useTeamRun } from '@/hooks/useTeamRun';
import { useTeamStatus } from '@/hooks/useTeamStatus';
import { useTeamAnswer, type AnswerResult } from '@/hooks/useTeamAnswer';
import { resultPlace, teamWaits } from '@/lib/teamAnswer';
import { clockTime, firstLine, waitTitle } from '@/lib/teamText';
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
import { NeedsYouCard } from '@/components/team/run/NeedsYouCard';
import { AnswerResultNote } from '@/components/team/run/AnswerResultNote';
import { OutcomeCard, ReservedDebrief } from '@/components/team/run/OutcomeCard';
import { StopRunDialog } from '@/components/team/run/StopRunDialog';
import { runResultHeading } from '@/components/team/run/runFocus';
import type { TeamRun } from '@/types/team';

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

/**
 * The last answer's result where the card was, once its question has
 * closed. When the card it was in went away with the focus, the focus
 * comes here, so the owner's place on the page isn't lost.
 */
function LoneResult({ result, executionId }: { result: AnswerResult; executionId: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const active = document.activeElement;
    if (!active || active === document.body) ref.current?.focus();
  }, [result.seq]);
  return <AnswerResultNote ref={ref} outcome={result.outcome} executionId={executionId} hasWords={false} />;
}

/** Stop run is offered while the team is live and not cut off. */
function stoppable(run: TeamRun | null, ended: boolean): boolean {
  return run !== null && !ended && run.outcome === null && run.state !== 'interrupted';
}

/**
 * When Stop run goes away under the focus (the run has ended), the focus
 * goes to the outcome's title instead of being lost on the page's body.
 */
function useFocusWhenStopGoes(canStop: boolean) {
  const was = useRef(canStop);
  useEffect(() => {
    if (was.current && !canStop) {
      const active = document.activeElement;
      if (!active || active === document.body) runResultHeading()?.focus();
    }
    was.current = canStop;
  }, [canStop]);
}

/**
 * A plain frame for the moments there is no run to show yet. `quietTitle`
 * keeps the page's heading for screen readers only, where the note says
 * it all (board R0).
 */
function Frame({ children, quietTitle = false }: { children: ReactNode; quietTitle?: boolean }) {
  return (
    <div className="flex h-full flex-col gap-4 overflow-auto bg-temper-bg px-6 py-4">
      <h1 className={quietTitle ? 'sr-only' : 'm-0 text-xl font-semibold text-temper-text'}>Team run</h1>
      {children}
    </div>
  );
}

/**
 * The run view: one team trial, read every 5 s while it is live and once
 * right after each of the owner's actions. While Temper waits for the
 * owner the needs-you card leads the page; an ended run shows its outcome.
 */
export default function TeamRunView() {
  const { executionId = '' } = useParams();
  const read = useTeamRun(executionId);
  const { run } = read;
  const { status } = useTeamStatus();
  const sender = useTeamAnswer(executionId, read.refresh);
  const [stopOpen, setStopOpen] = useState(false);
  const canStop = stoppable(run, read.ended);
  useFocusWhenStopGoes(canStop);
  useDocumentTitle(run ? `Team: ${firstLine(run.trial.goal) || run.trial_id}` : 'Team run');

  const result = sender.result;

  if (!run) {
    if (read.notTeam !== null) {
      return (
        <Frame quietTitle>
          {/* Nothing failed: the run is simply not a team trial (Design's R0). */}
          <TeamNote tone="info" title="This run isn't a team trial">
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
  const { wait, next } = teamWaits(run);
  const place = resultPlace(result?.waitId ?? null, wait?.wait_id ?? null, result?.openAfter ?? null);
  return (
    <div className="flex h-full flex-col overflow-auto bg-temper-bg">
      <RunHeader
        run={run}
        updatedAt={read.updatedAt}
        stale={stale}
        live={!read.ended && run.state !== 'interrupted'}
        onStop={canStop ? () => setStopOpen(true) : undefined}
      />
      {/* Stays open when the run ends meanwhile: Temper's answer (G13) is read in it. */}
      <StopRunDialog
        open={stopOpen}
        onOpenChange={setStopOpen}
        executionId={run.execution_id}
        workflow={run.workflow}
        reasonLimit={status?.limits.stop_reason_max_chars}
        onStopped={read.refresh}
      />
      <p className="sr-only" aria-live="polite" aria-atomic="true" data-testid="team-needs-you-live">
        {wait ? `Needs you: ${waitTitle(wait)}` : ''}
      </p>
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
        {result && place === 'alone' && <LoneResult result={result} executionId={run.execution_id} />}
        {wait && (
          <NeedsYouCard
            key={wait.wait_id}
            run={run}
            wait={wait}
            next={next}
            limits={status?.limits ?? null}
            sender={sender}
            result={place === 'card' ? result : null}
          />
        )}
        {run.outcome && (
          <>
            <OutcomeCard run={run} />
            <ReservedDebrief />
          </>
        )}
        <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(0,1fr)_384px]">
          <div className="flex min-w-0 flex-col gap-4">
            <Timeline run={run} />
            <WhoDidWhat run={run} />
          </div>
          <div className="flex min-w-0 flex-col gap-4">
            {!wait && <RoundCard run={run} />}
            <MembersCard run={run} />
            <GoalCard goal={run.trial.goal} />
          </div>
        </div>
      </div>
    </div>
  );
}
