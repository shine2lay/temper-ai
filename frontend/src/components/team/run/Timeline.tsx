import { useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { LucideIcon } from 'lucide-react';
import {
  Check,
  ChevronDown,
  ChevronUp,
  CircleDot,
  CircleX,
  Clock,
  Eye,
  Gavel,
  GitCommitHorizontal,
  Hand,
  MessageSquare,
  Pause,
  Pencil,
  Play,
  Reply,
} from 'lucide-react';
import { MarkdownDisplay } from '@/components/shared/MarkdownDisplay';
import { cn } from '@/lib/utils';
import { fetchTeamMessage, teamKeys, TeamApiError } from '@/lib/teamApi';
import { teamStopper } from '@/lib/teamOutcome';
import { refusedDoneReview } from '@/lib/teamReview';
import { answerWaitWords, entryTime, waitEntryTitle } from '@/lib/teamTimeline';
import {
  countChars,
  decisionWords,
  formatNumber,
  isoOf,
  messageKindWord,
  messageStateWords,
  shortId,
  teamSource,
  teamTime,
  teamTimeFull,
} from '@/lib/teamText';
import type {
  TeamDecisionEntry,
  TeamEntry,
  TeamMemberTurnEntry,
  TeamMessageEntry,
  TeamOtherEntry,
  TeamOwnerAnswerEntry,
  TeamOwnerWaitEntry,
  TeamReviewRoundEntry,
  TeamRun,
  TeamViewEntry,
} from '@/types/team';
import { TeamNote } from '../TeamNote';
import { TeamWho } from '../TeamWho';
import { teamBtn, teamCard, teamChip, teamChipTone, teamLabel } from '../teamUi';

/** How many entries show before "Show all" (Design's boards). */
export const TIMELINE_FIRST = 8;

type AnyEntry = TeamEntry | TeamOtherEntry;

const ICONS: Record<string, LucideIcon> = {
  decision: Gavel,
  view: Eye,
  review_round: GitCommitHorizontal,
  message: MessageSquare,
  owner_wait: Hand,
  owner_answer: Reply,
  member_turn: Play,
};

/** A member, Temper or you, as the timeline names them. */
function Agent({ name }: { name: string | null | undefined }) {
  if (name === 'owner') return <TeamWho by="owner" />;
  if (name === 'temper') return <b className="font-semibold text-temper-text">Temper</b>;
  return <b className="font-semibold text-temper-text">{name || 'someone'}</b>;
}

function Muted({ children }: { children: ReactNode }) {
  return <span className="text-temper-text-muted">{children}</span>;
}

/** Member text under an entry's line: plain, two lines at most. */
function Preview({ text, engine }: { text: string | null | undefined; engine?: boolean }) {
  if (!text) return null;
  return (
    <p
      className={cn(
        'm-0 mt-1 max-w-[90ch] text-sm whitespace-pre-line break-words',
        engine ? 'border-l-[3px] border-temper-control pl-3 text-temper-text' : 'line-clamp-2 text-temper-text-muted',
      )}
    >
      {text}
    </p>
  );
}

function VerdictChip({ verdict, label }: { verdict: string; label?: string }) {
  const text = label ?? verdict;
  if (verdict === 'satisfied') {
    return (
      <span className={cn(teamChip, teamChipTone.done)}>
        <Check className="h-3.5 w-3.5" aria-hidden="true" />
        <span>{text}</span>
      </span>
    );
  }
  if (verdict === 'changes') {
    return (
      <span className={cn(teamChip, teamChipTone.neutral)}>
        <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
        <span>{text}</span>
      </span>
    );
  }
  return (
    <span className={cn(teamChip, teamChipTone.neutral)}>
      <span>{text.replace(/_/g, ' ')}</span>
    </span>
  );
}

export { VerdictChip };

const MESSAGE_STATE_ICONS: Record<string, LucideIcon> = {
  consumed: Check,
  pending: Clock,
  held: Pause,
  undelivered: CircleX,
};

function MessageState({ state, undelivered }: { state: string; undelivered?: string | null }) {
  const Icon = MESSAGE_STATE_ICONS[state];
  return (
    <span className="inline-flex items-center gap-1 text-xs text-temper-text-muted">
      {Icon && <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />}
      <span>{messageStateWords(state, undelivered)}</span>
    </span>
  );
}

/** A message's full body, read when it is opened. */
function OpenedMessage({ executionId, messageId }: { executionId: string; messageId: string }) {
  const query = useQuery({
    queryKey: teamKeys.message(executionId, messageId),
    queryFn: () => fetchTeamMessage(executionId, messageId),
    staleTime: Infinity,
    retry: false,
  });
  if (query.isPending) {
    return (
      <p role="status" className="m-0 mt-2 text-xs text-temper-text-muted">
        Opening the message…
      </p>
    );
  }
  if (query.isError) {
    const err = query.error;
    const words = err instanceof TeamApiError && typeof err.detail === 'string' ? err.detail : null;
    return (
      <TeamNote
        tone="bad"
        className="mt-2"
        action={
          <button type="button" className={teamBtn.secondaryXs} onClick={() => void query.refetch()}>
            Try again
          </button>
        }
      >
        Couldn&apos;t open this message{words ? `: ${words}` : '.'}
      </TeamNote>
    );
  }
  const message = query.data;
  return (
    <div data-message-body className="mt-2 rounded-md border border-temper-border bg-temper-bg p-3">
      <MarkdownDisplay content={message.body} className="rounded-none border-0 bg-transparent p-0" />
      <p className="m-0 mt-2 text-xs text-temper-text-muted">
        Message <span className="font-mono">{shortId(message.message_id)}</span> · {formatNumber(countChars(message.body))}{' '}
        characters
      </p>
    </div>
  );
}

function reviewRound(run: TeamRun, reviewId: string | undefined): number | null {
  if (!reviewId) return null;
  return run.reviews.find((r) => r.review_id === reviewId)?.round ?? null;
}

const TURN_WORDS: Record<string, string> = {
  running: 'started',
  completed: 'finished',
  failed: 'failed',
  uncertain: "didn't finish",
};

interface Row {
  head: ReactNode;
  body?: ReactNode;
  message?: { id: string };
}

/** What one entry says, from its typed fields only (never event_type). */
function describe(entry: AnyEntry, run: TeamRun): Row {
  switch (entry.entry) {
    case 'message': {
      const e = entry as TeamMessageEntry;
      const fromOwner = e.from_agent === 'owner';
      return {
        head: (
          <>
            <Agent name={e.from_agent} /> <Muted>to</Muted> <Agent name={e.to_agent} />{' '}
            <span className={cn(teamChip, teamChipTone.neutral)}>
              <span>{messageKindWord(e.message_kind, fromOwner)}</span>
            </span>{' '}
            <MessageState state={e.data.state} undelivered={e.data.undelivered} />
          </>
        ),
        body: <Preview text={e.data.preview} />,
        message: e.data.message_id ? { id: e.data.message_id } : undefined,
      };
    }
    case 'review_round': {
      const e = entry as TeamReviewRoundEntry;
      const round = e.round ?? reviewRound(run, e.data.review_id);
      const files = e.data.files ? Object.keys(e.data.files).length : null;
      return {
        head: (
          <>
            <Agent name={e.from_agent} /> <Muted>asked for review</Muted>
            {round != null && (
              <>
                {' '}
                <b className="font-semibold text-temper-text">round {round}</b>
              </>
            )}
            {e.data.commit && (
              <>
                {' '}
                <Muted>· commit</Muted> <span className="font-mono text-temper-text">{e.data.commit.slice(0, 7)}</span>
              </>
            )}
            {files != null && (
              <>
                {' '}
                <Muted>
                  · {files} {files === 1 ? 'file' : 'files'}
                </Muted>
              </>
            )}
          </>
        ),
      };
    }
    case 'view': {
      const e = entry as TeamViewEntry;
      const round = e.round ?? reviewRound(run, e.data.review_id);
      return {
        head: (
          <>
            <Agent name={e.from_agent} /> <Muted>{round != null ? `reviewed round ${round}:` : 'reviewed:'}</Muted>{' '}
            <VerdictChip verdict={e.data.verdict} />
          </>
        ),
        body: <Preview text={e.data.note} />,
      };
    }
    case 'decision': {
      const e = entry as TeamDecisionEntry;
      const refused = refusedDoneReview(e, run);
      if (refused) {
        return {
          head: (
            <>
              <Agent name={e.from_agent} /> <Muted>said done; refused</Muted>
            </>
          ),
          body: <Preview text={refused.refusal} engine />,
        };
      }
      if (e.decision === 'stopped') {
        // Who and from where come from the stopping action, as on the outcome
        // card: Temper's own entry always names the owner, whoever stopped it.
        const reason = (e.data as { reason?: string | null }).reason;
        const stopper = teamStopper(run);
        return {
          head: (
            <>
              <TeamWho by={stopper.by} />{' '}
              {stopper.source && (
                <>
                  <Muted>{teamSource(stopper.source).inline}</Muted>{' '}
                </>
              )}
              <Muted>stopped the team</Muted>
            </>
          ),
          body: <Preview text={reason} engine />,
        };
      }
      return {
        head: (
          <>
            <Agent name={e.from_agent} /> <Muted>decided:</Muted>{' '}
            <b className="font-semibold text-temper-text">{decisionWords(e.decision)}</b>
          </>
        ),
        body: <Preview text={e.data.summary} />,
      };
    }
    case 'owner_wait': {
      const e = entry as TeamOwnerWaitEntry;
      return {
        head: (
          <>
            <Muted>Temper asked you:</Muted> <b className="font-semibold text-temper-text">{waitEntryTitle(e, run)}</b>
          </>
        ),
      };
    }
    case 'owner_answer': {
      const e = entry as TeamOwnerAnswerEntry;
      const waitWords = answerWaitWords(e.wait_kind);
      return {
        head: (
          <>
            <TeamWho by={e.answered_by} /> <Muted>{teamSource(e.answered_source).inline}</Muted> <Muted>answered</Muted>{' '}
            <b className="font-semibold text-temper-text">{e.data.answer}</b>
            {waitWords && <Muted> ({waitWords})</Muted>}
            {e.data.applied === false && (
              <>
                {' '}
                <span data-chip="not-applied" className={cn(teamChip, teamChipTone.neutral)}>
                  not applied
                </span>
              </>
            )}
          </>
        ),
      };
    }
    case 'member_turn': {
      const e = entry as TeamMemberTurnEntry;
      return {
        head: (
          <>
            <Agent name={e.from_agent} /> <Muted>turn {e.data.turn_no}</Muted>{' '}
            <Muted>{TURN_WORDS[e.data.state] ?? e.data.state.replace(/_/g, ' ')}</Muted>
          </>
        ),
        body: e.data.error ? <Preview text={e.data.error} engine /> : undefined,
      };
    }
    default:
      return {
        head: (
          <>
            <Agent name={entry.from_agent} /> <Muted>{entry.entry.replace(/_/g, ' ')}</Muted>
          </>
        ),
      };
  }
}

function TimelineRow({ entry, run }: { entry: AnyEntry; run: TeamRun }) {
  const [open, setOpen] = useState(false);
  const row = describe(entry, run);
  const at = entryTime(entry, run);
  const Icon = ICONS[entry.entry] ?? CircleDot;
  const OpenIcon = open ? ChevronUp : ChevronDown;
  return (
    <li
      data-entry={entry.entry}
      className="grid grid-cols-[64px_20px_minmax(0,1fr)_auto] items-start gap-2 border-t border-temper-border py-2 first:border-t-0"
    >
      {at ? (
        <time dateTime={isoOf(at)} title={teamTimeFull(at) || undefined} className="pt-0.5 text-xs text-temper-text-muted">
          {teamTime(at)}
        </time>
      ) : (
        // Temper sent no time for this entry: none is made up.
        <span />
      )}
      <span className="pt-0.5 text-temper-text-muted">
        <Icon className="h-4 w-4" aria-hidden="true" />
      </span>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-sm text-temper-text">{row.head}</div>
        {row.message && open ? (
          <OpenedMessage executionId={run.execution_id} messageId={row.message.id} />
        ) : (
          row.body
        )}
      </div>
      <div>
        {row.message && (
          <button type="button" className={teamBtn.ghostXs} aria-expanded={open} onClick={() => setOpen((v) => !v)}>
            <OpenIcon className="h-4 w-4" aria-hidden="true" />
            <span>{open ? 'Close' : 'Open'}</span>
          </button>
        )}
      </div>
    </li>
  );
}

/**
 * The run's typed timeline, newest first: the first few entries, then the
 * rest on request. Entries the server left out of the view are counted at
 * the end, with the way to every event.
 */
export function Timeline({ run }: { run: TeamRun }) {
  const [all, setAll] = useState(false);
  const notShown = run.timeline.not_shown;
  // Keys before the list is turned round: an entry's place counted from the
  // run's first entry stays the same while newer ones arrive and older ones
  // drop out of the view (they are counted in not_shown).
  const entries = run.timeline.entries
    .map((entry, i) => ({ entry, key: entryKey(entry, notShown + i) }))
    .reverse();
  const shown = all ? entries : entries.slice(0, TIMELINE_FIRST);
  const more = entries.length - shown.length;
  return (
    <section aria-labelledby="team-timeline-title" className={cn(teamCard, 'p-4')}>
      <div className="flex items-baseline gap-2">
        <h2 id="team-timeline-title" className={teamLabel}>
          Timeline
        </h2>
        <span className="flex-1" />
        <span className="text-xs text-temper-text-muted">
          {formatNumber(entries.length)} {entries.length === 1 ? 'entry' : 'entries'}, newest first
        </span>
      </div>
      {entries.length > 0 && (
        <ol className="m-0 list-none p-0">
          {shown.map(({ entry, key }) => (
            <TimelineRow key={key} entry={entry} run={run} />
          ))}
        </ol>
      )}
      {more > 0 && (
        <p className="m-0 mt-2 flex items-center gap-1 text-xs text-temper-text-muted">
          {formatNumber(more)} more in this list ·
          <button type="button" className={teamBtn.ghostXs} onClick={() => setAll(true)}>
            <ChevronDown className="h-4 w-4" aria-hidden="true" />
            <span>Show all</span>
          </button>
        </p>
      )}
      {all && entries.length > TIMELINE_FIRST && (
        <p className="m-0 mt-2 text-xs">
          <button type="button" className={teamBtn.ghostXs} onClick={() => setAll(false)}>
            <ChevronUp className="h-4 w-4" aria-hidden="true" />
            <span>Show fewer</span>
          </button>
        </p>
      )}
      {notShown > 0 && (
        <p className="m-0 mt-2 text-xs text-temper-text-muted">
          {formatNumber(notShown)} earlier {notShown === 1 ? 'entry' : 'entries'} not shown. The run page&apos;s Event Log has
          every event.
        </p>
      )}
    </section>
  );
}

/** A stable key: a message keeps its id (an opened one stays open), the rest their place. */
function entryKey(entry: AnyEntry, place: number): string {
  const data = (entry.data ?? {}) as Record<string, unknown>;
  if (entry.entry === 'message' && typeof data.message_id === 'string') return `message:${data.message_id}`;
  return `${entry.entry}:${place}`;
}
