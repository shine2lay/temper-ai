import { Link } from 'react-router-dom';
import { CircleSlash, ExternalLink, Plus } from 'lucide-react';
import { cn } from '@/lib/utils';
import { teamTime } from '@/lib/teamText';
import type { TeamRun } from '@/types/team';
import { TeamNote } from '../TeamNote';
import { teamBtn } from '../teamUi';

/**
 * The note at the top of the run view while the team starts, and the card
 * of an interrupted run (resume is on the run page). A wait has its
 * needs-you card and an ended run its outcome card; running needs none.
 * An old review-round run (kind "rounds", said only by the new engine)
 * can't be resumed: its card says so and offers a new project instead
 * (Design's SPEC 14 b 7).
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

  if (state === 'interrupted' && run.kind === 'rounds') {
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
          <h2 className="m-0 flex-1 text-sm font-semibold text-temper-text">
            Interrupted: this round run can&apos;t be resumed here. Start a new project to carry on.
          </h2>
          <Link to="/team/new" className={teamBtn.primary}>
            <Plus className="h-4 w-4" aria-hidden="true" />
            <span>New project</span>
          </Link>
        </div>
        <p className="m-0 mt-2 text-xs text-temper-text-muted">The server restarted during a turn.</p>
      </div>
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

  return null;
}
