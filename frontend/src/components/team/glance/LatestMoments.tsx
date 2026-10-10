/**
 * Latest: the team's big moments only, newest first, five rows, then a link
 * down to the full activity list. Plain info and reply messages, turn starts
 * and ends and wakes stay out (they are on the map and in the full list).
 * The link's count is Temper's events_total (D14); without it the link has
 * no count (the events cursor is a position, never a count).
 */
import { useMemo } from 'react';
import { ArrowDown } from 'lucide-react';
import { cn } from '@/lib/utils';
import { latestAgo, latestMoments, limitCheckShown, type GlanceEvent, type GlanceRun } from '@/lib/teamGlance';
import { teamCard, teamLink } from '@/components/team/teamUi';
import { GIcon, PathText } from './glanceUi';
import { glanceCardHead } from './glanceStyle';

export function LatestMoments({
  run,
  events,
  now,
  ready,
}: {
  run: GlanceRun;
  events: GlanceEvent[];
  now: number | null;
  ready: boolean;
}) {
  // D31: a limit row names its check only while Now does (never once verified or asked).
  const liveLimit = limitCheckShown(run.phase);
  // The team's cards: a receiver with none doesn't count towards D82's "sent a message to N members".
  const members = useMemo(() => new Set(run.members.map((m) => m.name)), [run.members]);
  // D110: All activity's words for each moment; D104: a future time in them gets its day by Temper's clock.
  const moments = useMemo(
    () => latestMoments(events, run.leader, 5, liveLimit, members, run, { now }),
    [events, run, liveLimit, members, now],
  );
  return (
    <section className={cn(teamCard, 'flex min-w-0 flex-col gap-2 p-4')} aria-labelledby="glance-latest-title">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="glance-latest-title" className={glanceCardHead}>
          Latest
        </h2>
        <p className="m-0 text-sm text-temper-text-muted">big moments only</p>
      </div>
      {moments.length > 0 ? (
        <ol className="m-0 flex list-none flex-col gap-2 p-0" data-testid="glance-latest">
          {moments.map((m) => (
            <li key={m.key} className="flex min-w-0 items-start gap-2 text-sm max-[360px]:flex-wrap max-[360px]:gap-y-0">
              {/* D59: the age says "ago" (All activity shows clock times), 76 px, 68 on a phone; it wraps, never clips.
                  D74: under 360 px it takes its own line above the entry, so the entry keeps the width. */}
              <span
                className="w-[68px] shrink-0 text-right text-sm leading-5 break-words whitespace-normal text-temper-text-muted tabular-nums md:w-[76px] max-[360px]:w-full max-[360px]:text-left"
                data-testid="glance-latest-time"
              >
                {latestAgo(m.at, now)}
              </span>
              <GIcon name={m.icon} className="mt-0.5 h-4 w-4 shrink-0 text-temper-text-muted" />
              <span className="min-w-0 break-words text-temper-text">
                {m.parts.map((p, i) =>
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
          ))}
        </ol>
      ) : (
        <p className="m-0 text-sm text-temper-text-muted">{ready ? 'Nothing big has happened yet.' : 'Reading the team\u2019s activity…'}</p>
      )}
      {(run.eventsTotal === null || run.eventsTotal > 0) && (
        <p className="m-0">
          <a href="#glance-activity" className={teamLink}>
            <span>
              All activity
              {run.eventsTotal !== null && ` (${run.eventsTotal} ${run.eventsTotal === 1 ? 'entry' : 'entries'})`}
            </span>
            <ArrowDown className="h-3.5 w-3.5" aria-hidden="true" />
          </a>
        </p>
      )}
    </section>
  );
}
