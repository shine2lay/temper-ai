/**
 * All activity (SPEC 9): the one history of a free-flowing Project. Every
 * event of the feed, newest first, the 12 newest and then "Show older (N)",
 * each with its clock time to the second (D46) and its own words (Design's
 * eventRow). The count is Temper's events_total, the same number as
 * Latest's link (D14); the run's timeline list is not shown on this page
 * (home decision 3): round runs keep their Timeline card.
 *
 * D85: a row whose words are cut gets a "Show all" text button after them,
 * which opens the row in place to the whole text and becomes "Show less". A
 * message's row quotes Temper's first line of it; its whole body is read
 * from Temper (once, kept for the page's life), and only a body that says
 * more makes the row a cut. Open rows stay open when new events arrive.
 */
import { useCallback, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { cn } from '@/lib/utils';
import { fetchTeamMessage, teamKeys } from '@/lib/teamApi';
import {
  ACTIVITY_FIRST,
  activityRows,
  clockSecOf,
  messageWholeParts,
  type GlanceEvent,
  type GlanceRun,
  type Moment,
  type MomentPart,
} from '@/lib/teamGlance';
import { formatNumber } from '@/lib/teamText';
import { teamBtn, teamCard, teamLink } from '@/components/team/teamUi';
import { GIcon, PathText } from './glanceUi';
import { glanceCardHead } from './glanceStyle';

export function AllActivity({ run, events, ready }: { run: GlanceRun; events: GlanceEvent[]; ready: boolean }) {
  const [older, setOlder] = useState(false);
  // D85: the rows opened with Show all, by row key (a row's key is its event's seq, so it survives new events).
  const [open, setOpen] = useState<ReadonlySet<string>>(() => new Set());
  const toggle = useCallback((key: string) => {
    setOpen((was) => {
      const next = new Set(was);
      if (!next.delete(key)) next.add(key);
      return next;
    });
  }, []);
  const liveLimit = run.phase.name === 'limit';
  const rows = useMemo(() => activityRows(events, run, liveLimit), [events, run, liveLimit]);
  const total = run.eventsTotal ?? rows.length;
  const shown = older ? rows : rows.slice(0, ACTIVITY_FIRST);
  const more = Math.max(0, total - shown.length);
  return (
    <section id="glance-activity" className={cn(teamCard, 'flex min-w-0 flex-col gap-2 p-4')} aria-labelledby="glance-activity-title">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="glance-activity-title" className={glanceCardHead}>
          All activity
        </h2>
        <p className="m-0 text-sm text-temper-text-muted" data-testid="glance-activity-count">
          {formatNumber(total)} {total === 1 ? 'entry' : 'entries'}, newest first
        </p>
      </div>
      {shown.length > 0 ? (
        <ol className="m-0 list-none p-0" data-testid="glance-activity">
          {shown.map((r) => (
            <ActivityRow key={r.key} row={r} executionId={run.executionId} open={open.has(r.key)} onToggle={toggle} />
          ))}
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

function ActivityRow({
  row,
  executionId,
  open,
  onToggle,
}: {
  row: Moment;
  executionId: string;
  open: boolean;
  onToggle: (key: string) => void;
}) {
  const more = row.more;
  const messageId = more && 'messageId' in more ? more.messageId : null;
  // A message's whole body (the round page's Timeline reads the same route); never re-read.
  const body = useQuery({
    queryKey: teamKeys.message(executionId, messageId ?? ''),
    queryFn: () => fetchTeamMessage(executionId, messageId as string),
    enabled: messageId !== null,
    staleTime: Infinity,
    retry: false,
  });
  const whole: MomentPart[] | null = !more ? null : 'whole' in more ? more.whole : messageWholeParts(more, body.data?.body);
  const expanded = open && whole !== null;
  const parts = expanded ? whole : row.parts;
  const button = useRef<HTMLButtonElement>(null);
  const textId = `glance-activity-${row.key}-text`;
  const clock = clockSecOf(row.at);
  return (
    <li
      data-row={row.key}
      className={cn(
        'grid grid-cols-[68px_20px_minmax(0,1fr)] items-start gap-2 border-t border-temper-border py-2 text-sm first:border-t-0 md:grid-cols-[76px_20px_minmax(0,1fr)]',
        // D74: under 360 px the time takes its own line above the entry, so the entry keeps the width.
        'max-[359px]:grid-cols-[20px_minmax(0,1fr)] max-[359px]:gap-y-0.5',
      )}
    >
      {clock && row.at ? (
        // D46: seconds, so same-minute rows read in order; in the viewer's own time.
        <time
          dateTime={row.at}
          className="pt-0.5 text-right text-sm leading-5 break-words text-temper-text-muted tabular-nums max-[359px]:col-span-full max-[359px]:text-left"
        >
          {clock}
        </time>
      ) : (
        // Temper sent no time for this event: none is made up.
        <span className="max-[359px]:hidden" />
      )}
      <GIcon name={row.icon} className="mt-0.5 h-4 w-4 shrink-0 text-temper-text-muted" />
      <span className={cn('min-w-0 break-words text-temper-text', expanded && 'whitespace-pre-wrap')}>
        <span id={textId}>
          {parts.map((p, i) =>
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
        {whole !== null && (
          // D85: a real button after the text: keyboard, aria-expanded, a 24 px target, the global focus ring.
          <button
            ref={button}
            type="button"
            aria-expanded={expanded}
            aria-controls={textId}
            data-testid="glance-activity-show-all"
            className={cn(teamLink, '-my-0.5 ml-1.5 min-w-6 cursor-pointer border-0 bg-transparent p-0 align-baseline whitespace-nowrap')}
            onClick={() => {
              onToggle(row.key);
              // Show less on a tall row: keep its button in view (the row's top never moves).
              if (expanded) requestAnimationFrame(() => button.current?.scrollIntoView({ block: 'nearest' }));
            }}
          >
            {expanded ? 'Show less' : 'Show all'}
          </button>
        )}
      </span>
    </li>
  );
}
