import { Link } from 'react-router-dom';
import { ChevronLeft, ChevronRight, CornerDownRight, ExternalLink, Hand, RefreshCw, WifiOff } from 'lucide-react';
import { cn } from '@/lib/utils';
import { clockTime, isoOf, readFailWords, shortId, teamCost, teamDateTime, teamTimeFull } from '@/lib/teamText';
import {
  personWords,
  showingWords,
  trialGroups,
  trialNeedsYou,
  trialPeople,
  trialPhrase,
  TRIALS_PAGE_SIZE,
  type TrialRow,
} from '@/lib/teamTrials';
import type { TeamListRead } from '@/hooks/useTeamLists';
import type { TeamTrialsPage } from '@/types/team';
import { EngineQuote } from '../TeamQuote';
import { TeamNote } from '../TeamNote';
import { TeamStateBadge } from '../TeamStateBadge';
import { TeamWho } from '../TeamWho';
import { teamBtn, teamChip, teamChipTone, teamLink } from '../teamUi';

/**
 * The columns, shared by the header and every row. From 1280 px a row is one line (board T1 at 1440);
 * below that it stacks as board T1 at 1024 draws it: the trial, the state, then round and cost, then
 * when it started and the run page link. The cells keep one order for screen readers.
 * The state column is sized from the list's width (100cqw), not from the row's, so a re-run row, set in
 * by 24 px, keeps every column after the trial under the same column name (board T1). 498 px is a
 * row's border, padding, fixed columns and gaps; 0.4118 is 0.7 / 1.7, the state column's old share.
 */
const COLUMNS =
  'grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-2 xl:grid-cols-[minmax(0,1fr)_minmax(176px,calc((100cqw_-_498px)*0.4118))_64px_152px_72px_96px] xl:gap-y-0';
const CELL = {
  wide: 'col-span-2 xl:col-span-1',
  round: 'col-start-1 row-start-3 xl:col-start-auto xl:row-start-auto',
  started: 'col-start-1 row-start-4 xl:col-start-auto xl:row-start-auto',
  cost: 'col-start-2 row-start-3 text-right xl:col-start-auto xl:row-start-auto xl:text-left',
  link: 'col-start-2 row-start-4 xl:col-start-auto xl:row-start-auto',
};

function TryButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button type="button" className={teamBtn.secondary} onClick={onClick}>
      <RefreshCw className="h-4 w-4" aria-hidden="true" />
      <span>{label}</span>
    </button>
  );
}

function StateCell({ row }: { row: TrialRow }) {
  const { item } = row;
  const phrase = trialPhrase(item);
  return (
    <div
      className={cn(
        CELL.wide,
        'flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 xl:flex-col xl:flex-nowrap xl:items-start',
      )}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <TeamStateBadge state={item.state} />
        {trialNeedsYou(item) && (
          <span data-chip="needs-you" className={cn(teamChip, teamChipTone.waiting, 'font-semibold')}>
            <Hand className="h-3.5 w-3.5" aria-hidden="true" />
            needs you
          </span>
        )}
      </div>
      {phrase && <p className="m-0 text-xs text-temper-text-muted">{phrase}</p>}
    </div>
  );
}

/** Round, start and cost, then the run page link: the same for a trial row and a sub-row. */
function RestCells({ row }: { row: TrialRow }) {
  const { item } = row;
  return (
    <>
      <p className={cn(CELL.round, 'm-0 text-sm text-temper-text')}>
        {item.round > 0 ? (
          `round ${item.round}`
        ) : (
          <span aria-label="no round yet" className="text-temper-text-muted">
            —
          </span>
        )}
      </p>
      <div className={cn(CELL.started, 'flex min-w-0 flex-col items-start text-xs text-temper-text-muted')}>
        <span className="sr-only">Started </span>
        <time dateTime={isoOf(item.started_at)} title={teamTimeFull(item.started_at)} className="text-temper-text">
          {teamDateTime(item.started_at)}
        </time>
        {/* The unknown-caller chip never breaks inside: if it doesn't fit after "by", it takes the next line. */}
        <span className="flex min-w-0 max-w-full flex-wrap items-center gap-x-1 gap-y-0.5">
          by <TeamWho by={item.started_by} className="min-w-0 max-w-full whitespace-nowrap" />
        </span>
      </div>
      <p className={cn(CELL.cost, 'm-0 font-mono text-sm text-temper-text')}>
        <span className="sr-only">Cost </span>
        {teamCost(item.cost_usd)}
      </p>
      <p className={cn(CELL.link, 'm-0 text-right text-sm')}>
        <Link to={`/workflow/${item.execution_id}`} className={teamLink}>
          <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
          <span>Run page</span>
        </Link>
      </p>
    </>
  );
}

function TrialMainRow({ row }: { row: TrialRow }) {
  const { item } = row;
  const needs = trialNeedsYou(item);
  const { leader, others } = trialPeople(item);
  const goal = item.goal_first_line || item.workflow;
  return (
    <div
      data-trial-row=""
      data-needs-you={needs || undefined}
      className={cn(
        COLUMNS,
        'rounded-lg border px-4 py-3',
        needs
          ? 'border-[var(--badge-waiting-border)] bg-[var(--badge-waiting-bg)]'
          : 'border-temper-border bg-temper-panel',
      )}
    >
      <div className={cn(CELL.wide, 'min-w-0')}>
        <Link
          to={`/team/runs/${item.execution_id}`}
          title={item.goal_first_line}
          className="block min-h-6 truncate text-sm leading-6 font-semibold text-temper-text no-underline hover:underline"
        >
          {goal}
        </Link>
        <p className="m-0 truncate text-xs text-temper-text-muted">
          <span className="font-mono">{item.workflow}</span>
          {leader && (
            <>
              {' · '}Leader <b className="font-semibold text-temper-text">{leader.name}</b>
              {leader.role && leader.role !== leader.name && <> ({leader.role})</>}
            </>
          )}
          {others.length > 0 && <> · {others.map(personWords).join(', ')}</>}
        </p>
      </div>
      <StateCell row={row} />
      <RestCells row={row} />
    </div>
  );
}

/** A re-run or fork of the trial above, from the run page (contract A-8). */
function TrialSubRow({ row }: { row: TrialRow }) {
  const { item } = row;
  return (
    <div
      data-trial-subrow=""
      data-orphan={row.orphan || undefined}
      className={cn(COLUMNS, 'ml-6 rounded-lg border border-dashed border-temper-control bg-temper-panel/60 px-4 py-3')}
    >
      <div className={cn(CELL.wide, 'min-w-0')}>
        <Link
          to={`/team/runs/${item.execution_id}`}
          className="flex min-h-6 items-center gap-1.5 text-xs text-temper-text no-underline hover:underline"
        >
          <CornerDownRight className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span className="truncate">Re-run or fork from the run page</span>
        </Link>
        <p className="m-0 truncate text-xs text-temper-text-muted">
          run <span className="font-mono">{shortId(item.execution_id)}</span>
          {/* Its trial row is on the page before: name the trial here. */}
          {row.orphan && (
            <>
              {' · of '}
              <span className="font-mono">{item.workflow}</span>
            </>
          )}
        </p>
      </div>
      <StateCell row={row} />
      <RestCells row={row} />
    </div>
  );
}

function Pager({
  page,
  total,
  count,
  onPage,
}: {
  page: number;
  total: number;
  count: number;
  onPage: (page: number) => void;
}) {
  const offset = page * TRIALS_PAGE_SIZE;
  const hasNext = offset + count < total;
  return (
    <div className="flex flex-wrap items-center gap-3">
      <p className="m-0 flex-1 text-xs text-temper-text-muted" data-testid="trials-showing">
        {showingWords(offset, count, total)}
      </p>
      <button type="button" className={teamBtn.secondaryMd} disabled={page === 0} onClick={() => onPage(page - 1)}>
        <ChevronLeft className="h-4 w-4" aria-hidden="true" />
        <span>Previous</span>
      </button>
      <button type="button" className={teamBtn.secondaryMd} disabled={!hasNext} onClick={() => onPage(page + 1)}>
        <ChevronRight className="h-4 w-4" aria-hidden="true" />
        <span>Next</span>
      </button>
    </div>
  );
}

/** The visual column names; each row says what its cells are for screen readers. */
function ColumnNames() {
  return (
    <div
      aria-hidden="true"
      data-column-names=""
      className={cn(
        COLUMNS,
        'hidden px-4 text-xs font-semibold tracking-[0.06em] text-temper-text-muted uppercase xl:grid',
      )}
    >
      <span>Trial</span>
      <span>State</span>
      <span>Round</span>
      <span>Started</span>
      <span>Cost</span>
      <span />
    </div>
  );
}

/**
 * The Trials tab (SPEC 4, boards T1-T3b): every team trial, newest first,
 * its re-runs and forks under it. Rows that wait for the owner are tinted
 * and say "needs you". Read every 5 s while the tab is open; a failed
 * refresh keeps the rows and says so.
 */
export function TrialsList({
  read,
  rows,
  page,
  onPage,
}: {
  read: TeamListRead<TeamTrialsPage>;
  rows: TrialRow[];
  page: number;
  onPage: (page: number) => void;
}) {
  const { data } = read;

  if (!data) {
    if (read.error) {
      return (
        <TeamNote
          tone="bad"
          live
          title="Couldn't load the trials."
          action={<TryButton label="Try again" onClick={read.refresh} />}
        >
          <EngineQuote className="mt-1" label="Temper said:">
            {readFailWords(read.error)}
          </EngineQuote>
          <p className="m-0 mt-2 text-temper-text-muted">
            Nothing changed. The page tries again every 5 s while it is open.
          </p>
        </TeamNote>
      );
    }
    return (
      <div className="flex flex-col gap-2" aria-busy="true">
        <ColumnNames />
        <p role="status" className="m-0 px-4 text-sm text-temper-text-muted">
          Loading the trials…
        </p>
      </div>
    );
  }

  if (data.total === 0) {
    return (
      <section aria-labelledby="trials-empty" className="rounded-lg border border-temper-border bg-temper-panel px-6 py-8">
        <h2 id="trials-empty" className="m-0 text-base font-semibold text-temper-text">
          No trials yet
        </h2>
        <p className="m-0 mt-2 max-w-[60ch] text-sm text-temper-text-muted">
          A trial puts a few pi roles on one goal. They work in rounds, review each other&apos;s work and stop when the
          leader&apos;s version is approved. Start one with New trial at the top right.
        </p>
      </section>
    );
  }

  const groups = trialGroups(rows);
  return (
    <div className="@container flex flex-col gap-2">
      {read.failedAt !== null && (
        <TeamNote tone="warn" icon={WifiOff} live action={<TryButton label="Try now" onClick={read.refresh} />}>
          <b className="font-semibold">Couldn&apos;t refresh at {clockTime(read.failedAt)}.</b>{' '}
          <span className="text-temper-text-muted">
            Showing what Temper said at {read.updatedAt !== null ? clockTime(read.updatedAt) : 'the last read'}. Trying
            again every 5 s.
          </span>
        </TeamNote>
      )}
      <ColumnNames />
      <ul aria-label="Trials" className="m-0 flex list-none flex-col gap-2 p-0">
        {groups.map((g) => (
          <li key={g.key} className="flex flex-col gap-2">
            {g.head && <TrialMainRow row={g.head} />}
            {g.subs.length > 0 && (
              <ul aria-label="Re-runs and forks" className="m-0 flex list-none flex-col gap-2 p-0">
                {g.subs.map((s) => (
                  <li key={s.item.execution_id}>
                    <TrialSubRow row={s} />
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>
      <Pager page={page} total={data.total} count={rows.length} onPage={onPage} />
    </div>
  );
}
