/**
 * All activity (SPEC 9): the one history of a free-flowing Project. Every
 * event of the feed, newest first, the 12 newest and then "Show older (N)",
 * each with its clock time to the second (D46) and its own words (Design's
 * eventRow). The count is Temper's events_total, the same number as
 * Latest's link (D14); the run's timeline list is not shown on this page
 * (home decision 3): round runs keep their Timeline card.
 */
import { useMemo, useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { cn } from '@/lib/utils';
import { ACTIVITY_FIRST, activityRows, clockSecOf, type GlanceEvent, type GlanceRun } from '@/lib/teamGlance';
import { formatNumber } from '@/lib/teamText';
import { teamBtn, teamCard, teamLabel } from '@/components/team/teamUi';
import { GIcon, PathText } from './glanceUi';

export function AllActivity({ run, events, ready }: { run: GlanceRun; events: GlanceEvent[]; ready: boolean }) {
  const [older, setOlder] = useState(false);
  const liveLimit = run.phase.name === 'limit';
  const rows = useMemo(() => activityRows(events, run, liveLimit), [events, run, liveLimit]);
  const total = run.eventsTotal ?? rows.length;
  const shown = older ? rows : rows.slice(0, ACTIVITY_FIRST);
  const more = Math.max(0, total - shown.length);
  return (
    <section id="glance-activity" className={cn(teamCard, 'flex min-w-0 flex-col gap-2 p-4')} aria-labelledby="glance-activity-title">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="glance-activity-title" className={cn(teamLabel, 'mb-0')}>
          All activity
        </h2>
        <p className="m-0 text-sm text-temper-text-muted" data-testid="glance-activity-count">
          {formatNumber(total)} {total === 1 ? 'entry' : 'entries'}, newest first
        </p>
      </div>
      {shown.length > 0 ? (
        <ol className="m-0 list-none p-0" data-testid="glance-activity">
          {shown.map((r) => {
            const clock = clockSecOf(r.at);
            return (
              <li
                key={r.key}
                data-row={r.key}
                className={cn(
                  'grid grid-cols-[68px_20px_minmax(0,1fr)] items-start gap-2 border-t border-temper-border py-2 text-sm first:border-t-0 md:grid-cols-[76px_20px_minmax(0,1fr)]',
                  // D74: under 360 px the time takes its own line above the entry, so the entry keeps the width.
                  'max-[359px]:grid-cols-[20px_minmax(0,1fr)] max-[359px]:gap-y-0.5',
                )}
              >
                {clock && r.at ? (
                  // D46: seconds, so same-minute rows read in order; in the viewer's own time.
                  <time
                    dateTime={r.at}
                    className="pt-0.5 text-right text-sm leading-5 break-words text-temper-text-muted tabular-nums max-[359px]:col-span-full max-[359px]:text-left"
                  >
                    {clock}
                  </time>
                ) : (
                  // Temper sent no time for this event: none is made up.
                  <span className="max-[359px]:hidden" />
                )}
                <GIcon name={r.icon} className="mt-0.5 h-4 w-4 shrink-0 text-temper-text-muted" />
                <span className="min-w-0 break-words text-temper-text">
                  {r.parts.map((p, i) =>
                    p.strong ? (
                      <b key={i} className="font-semibold">
                        {p.text}
                      </b>
                    ) : (
                      <span key={i}>
                        <PathText text={p.text} />
                      </span>
                    ),
                  )}
                </span>
              </li>
            );
          })}
        </ol>
      ) : (
        <p className="m-0 text-sm text-temper-text-muted">{ready ? 'Nothing yet.' : 'Reading the team\u2019s activity\u2026'}</p>
      )}
      {!older && more > 0 && (
        <p className="m-0">
          <button type="button" className={teamBtn.secondary} onClick={() => setOlder(true)} data-testid="glance-activity-older">
            <ChevronDown className="h-4 w-4" aria-hidden="true" />
            <span>Show older ({formatNumber(more)})</span>
          </button>
        </p>
      )}
      {older && rows.length > ACTIVITY_FIRST && (
        <p className="m-0">
          <button type="button" className={teamBtn.secondary} onClick={() => setOlder(false)}>
            <ChevronUp className="h-4 w-4" aria-hidden="true" />
            <span>Show fewer</span>
          </button>
        </p>
      )}
    </section>
  );
}
