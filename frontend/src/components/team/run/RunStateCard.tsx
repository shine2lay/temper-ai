import { Link } from 'react-router-dom';
import { CircleSlash, ExternalLink } from 'lucide-react';
import { cn } from '@/lib/utils';
import { ENDED_STATES, WAIT_STATES, isoOf, teamTime, teamTimeFull, waitTitle } from '@/lib/teamText';
import type { TeamRun } from '@/types/team';
import { TeamNote } from '../TeamNote';
import { EngineQuote, OwnerWords } from '../TeamQuote';
import { TeamStateBadge } from '../TeamStateBadge';
import { teamBtn, teamCard, teamLink } from '../teamUi';

function RunPageLink({ executionId, label = 'Open the run page' }: { executionId: string; label?: string }) {
  return (
    <Link to={`/workflow/${executionId}`} className={teamLink}>
      <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
      <span>{label}</span>
    </Link>
  );
}

/**
 * The card at the top of the run view for the states the read-only view
 * covers: starting, interrupted, and (until answering is built) a wait or
 * an ended run, shown with Temper's own words and the way to the run page.
 * Running needs no card.
 */
export function RunStateCard({ run }: { run: TeamRun }) {
  const { state } = run;

  if (state === 'starting') {
    return (
      <TeamNote tone="info" title="Starting: no member turn has begun yet">
        Temper is setting the team up (queued, then making the project copies). Started{' '}
        {teamTime(run.trial.started_at) || 'just now'}. You can stop the run while it starts.
      </TeamNote>
    );
  }

  if (state === 'interrupted') {
    return (
      <div
        data-card="interrupted"
        className={cn(
          'rounded-lg border p-4',
          'bg-[var(--badge-interrupted-bg)] border-[var(--badge-interrupted-border)]',
        )}
      >
        <div className="flex flex-wrap items-center gap-3">
          <CircleSlash className="h-4 w-4 shrink-0 text-[var(--badge-interrupted-text)]" aria-hidden="true" />
          <h2 className="m-0 flex-1 text-sm font-semibold text-temper-text">Interrupted: resume it from the run page</h2>
          <Link to={`/workflow/${run.execution_id}`} className={teamBtn.primary}>
            <ExternalLink className="h-4 w-4" aria-hidden="true" />
            <span>Open the run page</span>
          </Link>
        </div>
        <p className="m-0 mt-2 text-xs text-temper-text-muted">
          The server restarted during a turn. Resume is on the run page; the Team page doesn&apos;t start work.
        </p>
      </div>
    );
  }

  if (WAIT_STATES.has(state)) {
    const wait = run.open_waits.find((w) => w.asked) ?? run.open_waits[0] ?? null;
    return (
      <section
        data-card="wait"
        aria-labelledby="team-wait-title"
        className="rounded-lg border p-4 bg-[var(--team-wait-card-bg)] border-[var(--team-wait-card-border)]"
      >
        <div className="flex flex-wrap items-center gap-3">
          <TeamStateBadge state={state} />
          <h2 id="team-wait-title" className="m-0 text-sm font-semibold text-temper-text">
            {wait ? waitTitle(wait) : 'Temper is waiting for you'}
          </h2>
          {wait?.opened_at && (
            <span className="text-xs text-temper-text-muted">
              Waiting since{' '}
              <time dateTime={isoOf(wait.opened_at)} title={teamTimeFull(wait.opened_at)}>
                {teamTime(wait.opened_at)}
              </time>
            </span>
          )}
        </div>
        {wait?.question && <EngineQuote className="mt-3" label="Temper asks">{wait.question}</EngineQuote>}
        <p className="m-0 mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-temper-text">
          <span>Answering on the Team page is still being built.</span>
          <RunPageLink executionId={run.execution_id} />
        </p>
      </section>
    );
  }

  if (ENDED_STATES.has(state) && run.outcome) {
    const { outcome } = run;
    return (
      <section data-card="ended" aria-labelledby="team-ended-title" className={cn(teamCard, 'p-4')}>
        <div className="flex flex-wrap items-center gap-3">
          <TeamStateBadge state={state} />
          <h2 id="team-ended-title" className="m-0 text-sm font-semibold text-temper-text">
            {outcome.at ? (
              <>
                Ended{' '}
                <time dateTime={isoOf(outcome.at)} title={teamTimeFull(outcome.at)}>
                  {teamTime(outcome.at)}
                </time>
              </>
            ) : (
              'Ended'
            )}
          </h2>
          <span className="flex-1" />
          <RunPageLink executionId={run.execution_id} />
        </div>
        {outcome.reason && (
          <EngineQuote className="mt-3" label="Temper's reason">
            {outcome.reason}
          </EngineQuote>
        )}
        {outcome.owner_words && <OwnerWords className="mt-3" by={outcome.by} words={outcome.owner_words} />}
      </section>
    );
  }

  return null;
}
