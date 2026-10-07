import { Fragment, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ExternalLink, Square } from 'lucide-react';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { clockTime, firstLine, isoOf, teamCost, teamTime, teamTimeFull } from '@/lib/teamText';
import type { TeamRun } from '@/types/team';
import { projectName } from '@/lib/teamOutcome';
import { TeamStateBadge } from '../TeamStateBadge';
import { TeamWho } from '../TeamWho';
import { teamBtn, teamLink } from '../teamUi';
import { RUN_TITLE_ID } from './runFocus';

/**
 * The run view's header: where you are, when the page last heard from
 * Temper, the goal's first line, the team's state, the run's own status,
 * the way to the run page, Stop run while the team can still be stopped,
 * and one line of facts.
 */
export function RunHeader({
  run,
  updatedAt,
  stale,
  live,
  onStop,
}: {
  run: TeamRun;
  updatedAt: number | null;
  stale: boolean;
  /** Still running (not ended, not cut off): the cost is "so far". */
  live: boolean;
  /** Opens the Stop run confirm; no button when the run can't be stopped from here. */
  onStop?: () => void;
}) {
  const { trial } = run;
  const title = firstLine(trial.goal) || run.trial_id;
  const project = trial.project?.source ?? null;
  const facts: Array<{ key: string; node: ReactNode }> = [
    {
      key: 'started',
      node: (
        <span className="inline-flex flex-wrap items-center gap-1">
          Started{' '}
          <time dateTime={isoOf(trial.started_at)} title={teamTimeFull(trial.started_at)}>
            {teamTime(trial.started_at)}
          </time>{' '}
          by <TeamWho by={trial.started_by} className="text-xs" />
        </span>
      ),
    },
    {
      key: 'leader',
      node: (
        <span>
          Leader <b className="font-semibold text-temper-text">{trial.leader}</b>
        </span>
      ),
    },
    {
      key: 'members',
      node: (
        <span>
          {trial.members.length} {trial.members.length === 1 ? 'member' : 'members'}
        </span>
      ),
    },
    {
      key: 'pause',
      node: (
        <span>
          Pauses after <b className="font-semibold text-temper-text">{trial.pause_after_rounds}</b> rounds without done
        </span>
      ),
    },
    {
      key: 'talk',
      node: (
        <span>
          Talk: <b className="font-semibold text-temper-text">{trial.communication}</b>
        </span>
      ),
    },
  ];
  if (project) {
    facts.push({
      key: 'project',
      node: (
        <span>
          Code folder <b className="font-semibold text-temper-text" title={project}>{projectName(project)}</b>
          {trial.project?.start_commit && (
            <>
              {' '}
              at <span className="font-mono text-temper-text">{trial.project.start_commit.slice(0, 7)}</span>
            </>
          )}
        </span>
      ),
    });
  } else if (trial.project === null) {
    // A trial started from an empty project (board R11).
    facts.push({
      key: 'project',
      node: (
        <span>
          Code folder <b className="font-semibold text-temper-text">none</b> (an empty project)
        </span>
      ),
    });
  }
  facts.push({
    key: 'cost',
    node: (
      <span>
        {live ? 'Cost so far' : 'Cost'} <b className="font-mono font-semibold text-temper-text">{teamCost(run.cost_usd ?? 0)}</b>
      </span>
    ),
  });

  return (
    <header className="flex shrink-0 flex-col gap-2 border-b border-temper-border bg-temper-panel px-6 py-3">
      <div className="flex items-center gap-2 text-xs text-temper-text-muted">
        <nav aria-label="Breadcrumb">
          <ol className="m-0 flex list-none items-center gap-1.5 p-0">
            <li>
              <Link to="/team" className={teamLink}>
                Team
              </Link>
            </li>
            <li aria-hidden="true">/</li>
            <li>
              <Link to="/team" className={teamLink}>
                Projects
              </Link>
            </li>
            <li aria-hidden="true">/</li>
            <li>
              <span aria-current="page" className="font-mono text-temper-text">
                {run.trial_id}
              </span>
            </li>
          </ol>
        </nav>
        <span className="flex-1" />
        {updatedAt !== null && (
          <span className="whitespace-nowrap" data-testid="team-updated">
            Updated {clockTime(updatedAt)}
            {stale && <span> · not current</span>}
          </span>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        {/* A long goal wraps to two lines, then ends in an ellipsis; the goal card below shows it all. */}
        <h1
          id={RUN_TITLE_ID}
          tabIndex={-1}
          className="m-0 line-clamp-2 min-w-0 flex-1 break-words text-xl font-semibold text-temper-text"
          title={trial.goal}
        >
          {title}
        </h1>
        <span aria-live="polite" aria-atomic="true" className="inline-flex">
          <span className="sr-only">Team state: </span>
          <TeamStateBadge state={run.state} />
        </span>
        <span className="inline-flex items-center gap-1.5 text-xs text-temper-text-muted">
          Run <StatusBadge status={run.run_status} />
        </span>
        <Link to={`/workflow/${run.execution_id}`} className={teamBtn.secondary}>
          <ExternalLink className="h-4 w-4" aria-hidden="true" />
          <span>Run page</span>
        </Link>
        {onStop && (
          <button type="button" className={teamBtn.danger} onClick={onStop}>
            <Square className="h-4 w-4" aria-hidden="true" />
            <span>Stop run</span>
          </button>
        )}
      </div>
      <p className="m-0 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-temper-text-muted">
        {facts.map((f, i) => (
          <Fragment key={f.key}>
            {i > 0 && <span aria-hidden="true">·</span>}
            {f.node}
          </Fragment>
        ))}
      </p>
    </header>
  );
}
