import { useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { CalendarClock, ChevronDown, ChevronUp, CircleCheck, ExternalLink, Info } from 'lucide-react';
import { MarkdownDisplay } from '@/components/shared/MarkdownDisplay';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { cn } from '@/lib/utils';
import { isoOf, shortId, teamCost, teamSource, teamTime, teamTimeFull } from '@/lib/teamText';
import {
  branchWords,
  outcomeTitle,
  problemText,
  projectName,
  runListExplanation,
  stopAction,
} from '@/lib/teamOutcome';
import type { TeamDone, TeamRun } from '@/types/team';
import { TeamNote } from '../TeamNote';
import { EngineQuote, OwnerWords } from '../TeamQuote';
import { TeamStateBadge } from '../TeamStateBadge';
import { TeamWho } from '../TeamWho';
import { teamBtn, teamChip, teamChipTone, teamLabel, teamLink } from '../teamUi';
import { VerdictChip } from './Timeline';
import { OUTCOME_TITLE_ID } from './runFocus';

/** The card's quote labels in capitals, like its other labels (board R12). */
const QUOTE_LABEL = 'mb-2 uppercase tracking-[0.06em]';

/** How many files show before "Show all" (Design's spec, section 5.4). */
export const OUTCOME_FILES_FIRST = 20;

const BORDERS: Record<string, string> = {
  done: 'border-[var(--badge-completed-border)]',
  stopped: 'border-[var(--badge-cancelled-border)]',
  failed: 'border-[var(--badge-failed-border)]',
};

function Time({ iso }: { iso: string | null | undefined }) {
  if (!iso) return null;
  return (
    <time dateTime={isoOf(iso)} title={teamTimeFull(iso)}>
      {teamTime(iso)}
    </time>
  );
}

function ShowAll({ all, onToggle, more }: { all: boolean; onToggle: () => void; more: string }) {
  return (
    <button type="button" className={cn(teamBtn.ghostXs, 'mt-1 self-start')} aria-expanded={all} onClick={onToggle}>
      {all ? <ChevronUp className="h-4 w-4" aria-hidden="true" /> : <ChevronDown className="h-4 w-4" aria-hidden="true" />}
      <span>{all ? 'Show less' : more}</span>
    </button>
  );
}

/** The leader's summary: six lines, then the rest on request. Markdown without raw HTML. */
function Summary({ content }: { content: string }) {
  const [all, setAll] = useState(false);
  const [long, setLong] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const el = box.current;
    if (!el || all) return;
    const measure = () => setLong(el.scrollHeight > el.clientHeight + 1);
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [content, all]);

  return (
    <div className="flex flex-col">
      <div ref={box} className={cn(!all && 'line-clamp-6')}>
        <MarkdownDisplay content={content} className="rounded-none border-0 bg-transparent p-0" />
      </div>
      {(long || all) && <ShowAll all={all} onToggle={() => setAll((v) => !v)} more="Show all" />}
    </div>
  );
}

function Facts({ rows }: { rows: Array<{ label: string; value: ReactNode }> }) {
  return (
    <dl className="m-0 grid grid-cols-[96px_minmax(0,1fr)] gap-x-3 gap-y-2 text-sm">
      {rows.map((row) => (
        <div key={row.label} className="contents">
          <dt className="text-xs text-temper-text-muted">{row.label}</dt>
          <dd className="m-0 min-w-0 text-temper-text break-words">{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function Files({ files }: { files: TeamDone['files'] }) {
  const [all, setAll] = useState(false);
  const shown = all ? files : files.slice(0, OUTCOME_FILES_FIRST);
  return (
    <section aria-labelledby="team-outcome-files" className="flex flex-col">
      <h3 id="team-outcome-files" className={teamLabel}>
        Files in the approved version ({files.length})
      </h3>
      <ul className="m-0 flex list-none flex-col gap-0.5 p-0 font-mono text-xs text-temper-text">
        {shown.map((f) => (
          <li key={f.path} className="break-all">
            {f.path}
          </li>
        ))}
      </ul>
      {files.length > OUTCOME_FILES_FIRST && (
        <ShowAll all={all} onToggle={() => setAll((v) => !v)} more={`Show all ${files.length} files`} />
      )}
    </section>
  );
}

/** Problems as Temper wrote them, one per line, when there is more than one. */
function Problems({ problems }: { problems: unknown[] }) {
  if (problems.length < 2) return null;
  return (
    <ul className="m-0 flex list-disc flex-col gap-1 pl-5 text-sm text-temper-text" data-problems="">
      {problems.map((p, i) => (
        <li key={i} className="break-words">
          {problemText(p)}
        </li>
      ))}
    </ul>
  );
}

function DoneMain({ run, done }: { run: TeamRun; done: TeamDone }) {
  const summary = done.summary ?? run.outcome?.reason ?? '';
  return (
    <>
      {summary && (
        <section aria-labelledby="team-outcome-summary">
          <h3 id="team-outcome-summary" className={teamLabel}>
            {run.trial.leader}&apos;s summary
          </h3>
          <Summary content={summary} />
        </section>
      )}
      <section aria-labelledby="team-outcome-objections">
        <h3 id="team-outcome-objections" className={teamLabel}>
          Objections
        </h3>
        {done.objections.length === 0 ? (
          <p className="m-0 flex items-center gap-1.5 text-sm text-temper-text">
            <CircleCheck className="h-4 w-4 shrink-0 text-[var(--badge-completed-text)]" aria-hidden="true" />
            No objections
          </p>
        ) : (
          <ul className="m-0 flex list-none flex-col gap-2 p-0">
            {done.objections.map((o) => (
              <li key={o.member} className="flex flex-wrap items-start gap-2 text-sm text-temper-text">
                <b className="font-semibold">{o.member}</b>
                <VerdictChip verdict={o.verdict} />
                {o.note && (
                  <span className="min-w-0 flex-1 break-words">
                    {o.view_round != null && <span className="text-temper-text-muted">round {o.view_round}: </span>}
                    {o.note}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}

function DoneSide({ run, done }: { run: TeamRun; done: TeamDone }) {
  const source = run.trial.project?.source ?? null;
  const branch = branchWords(done.branch, source ? projectName(source) : null);
  const commit = done.commit ?? null;
  return (
    <>
      <Facts
        rows={[
          {
            label: 'Commit',
            value: commit ? (
              <span className="flex flex-col">
                <b className="font-mono font-semibold">{done.commit_short?.slice(0, 7) || commit.slice(0, 7)}</b>
                <span className="font-mono text-xs text-temper-text-muted break-all">{commit}</span>
              </span>
            ) : (
              <span className="text-temper-text-muted">none</span>
            ),
          },
          {
            label: 'Approved in',
            value: (
              <span>
                review <span className="font-mono">{shortId(done.review_id)}</span>, round {done.round}
              </span>
            ),
          },
          {
            label: 'Branch',
            value:
              branch.kind === 'made' ? (
                <span data-branch="made">
                  <span className="font-mono font-semibold">{done.branch?.name}</span>
                  {branch.words.slice((done.branch?.name ?? '').length)}
                </span>
              ) : (
                <span data-branch={branch.kind} className={branch.kind === 'none' ? 'text-temper-text-muted' : undefined}>
                  {branch.words}
                </span>
              ),
          },
          { label: 'Rounds', value: String(done.rounds ?? done.round) },
          { label: 'Cost', value: <span className="font-mono">{teamCost(run.cost_usd ?? 0)}</span> },
        ]}
      />
      {done.files.length > 0 && <Files files={done.files} />}
    </>
  );
}

/** "Stopped by You from the dashboard · 10:37 AM". */
function StoppedBy({ run }: { run: TeamRun }) {
  const outcome = run.outcome;
  if (!outcome) return null;
  const action = stopAction(run);
  const by = action?.by ?? outcome.by;
  const at = action?.at ?? outcome.at;
  const from = action?.source ? teamSource(action.source).inline : null;
  return (
    <p data-stopped-by="" className="m-0 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-sm text-temper-text">
      {/* The spaces keep the words apart for screen readers; the flex gap draws them. */}
      <span className="text-temper-text-muted">Stopped by</span>{' '}
      <TeamWho by={by} unknownLabel="an unknown caller" />
      {from && <> <span>{from}</span></>}
      {at && (
        <>
          {' '}
          <span className="text-temper-text-muted">
            · <Time iso={at} />
          </span>
        </>
      )}
    </p>
  );
}

/**
 * The outcome card of an ended run (Design's spec, section 5.4): the
 * state, Temper's reason word for word, who stopped it and their own
 * words, and the facts. The run list's status comes from run_status, with
 * a line on why it reads as it does.
 */
export function OutcomeCard({ run }: { run: TeamRun }) {
  const { outcome, state } = run;
  if (!outcome) return null;
  const done = state === 'done' ? (outcome.done ?? null) : null;
  const explanation = runListExplanation(run);
  const cost = <span className="font-mono">{teamCost(run.cost_usd ?? 0)}</span>;
  const runList = <StatusBadge status={run.run_status} />;

  let main: ReactNode;
  let side: ReactNode;
  if (done) {
    main = <DoneMain run={run} done={done} />;
    side = <DoneSide run={run} done={done} />;
  } else {
    main = (
      <>
        {outcome.reason && (
          <EngineQuote label="Temper's reason" labelClassName={QUOTE_LABEL}>
            {outcome.reason}
          </EngineQuote>
        )}
        {(state === 'failed' || state === 'didnt_start') && <Problems problems={outcome.problems} />}
        {state === 'stopped' && <StoppedBy run={run} />}
        {outcome.owner_words && (
          <OwnerWords by={stopAction(run)?.by ?? outcome.by} words={outcome.owner_words} labelClassName={QUOTE_LABEL} />
        )}
        {state === 'failed' && (
          <p className="m-0 text-sm text-temper-text">Resume it from the run page to retry or stop the turn.</p>
        )}
        {state === 'didnt_start' && (run.cost_usd ?? 0) === 0 && (
          <p className="m-0 flex items-center gap-1.5 text-sm text-temper-text">
            <CircleCheck className="h-4 w-4 shrink-0 text-[var(--badge-completed-text)]" aria-hidden="true" />
            Nothing was spent.
          </p>
        )}
      </>
    );
    const rows: Array<{ label: string; value: ReactNode }> = [{ label: 'Run list', value: runList }];
    if (state === 'stopped') rows.push({ label: 'Last round', value: String(run.round.current) });
    rows.push({ label: 'Cost', value: cost });
    side = (
      <>
        <Facts rows={rows} />
        {explanation && (
          <TeamNote tone="info" icon={Info}>
            <span data-run-list-explanation="">{explanation}</span>
          </TeamNote>
        )}
      </>
    );
  }

  return (
    <section
      data-card="outcome"
      data-outcome={state}
      aria-labelledby={OUTCOME_TITLE_ID}
      className={cn('flex flex-col gap-3 rounded-lg border bg-temper-panel p-4', BORDERS[state] ?? 'border-temper-border')}
    >
      <div className="flex flex-wrap items-center gap-3">
        <TeamStateBadge state={state} />
        <h2 id={OUTCOME_TITLE_ID} tabIndex={-1} className="m-0 min-w-0 flex-1 text-base font-semibold text-temper-text">
          {outcomeTitle(state)}
        </h2>
        {outcome.at && (
          <span className="text-xs text-temper-text-muted">
            Ended <Time iso={outcome.at} />
          </span>
        )}
        <Link to={`/workflow/${run.execution_id}`} className={cn(teamLink, 'text-xs')}>
          <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
          <span>Open the run page</span>
        </Link>
      </div>
      <div className="grid grid-cols-1 gap-x-6 gap-y-4 xl:grid-cols-[minmax(0,1fr)_384px]">
        <div className="flex min-w-0 flex-col gap-3">{main}</div>
        <div className="flex min-w-0 flex-col gap-3">{side}</div>
      </div>
    </section>
  );
}

/** The place kept for each member's debrief and lessons (M5, designed later). */
export function ReservedDebrief() {
  return (
    <section
      data-card="debrief"
      aria-labelledby="team-debrief-title"
      className="rounded-lg border border-dashed border-temper-control px-4 py-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        <h2 id="team-debrief-title" className="m-0 text-xs font-semibold uppercase tracking-[0.06em] text-temper-text-muted">
          Debrief and lessons
        </h2>
        <span className={cn(teamChip, teamChipTone.neutral)}>
          <CalendarClock className="h-3.5 w-3.5" aria-hidden="true" />
          M5, designed later
        </span>
      </div>
      <p className="m-0 mt-2 text-xs text-temper-text-muted">
        Reserved. Each member&apos;s debrief and the lessons it sent to its role&apos;s home chat will show here once M5
        is designed.
      </p>
    </section>
  );
}
