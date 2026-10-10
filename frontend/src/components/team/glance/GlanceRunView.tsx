/**
 * The free-flowing team's run page, built to be read at a glance (Design's
 * GLANCE.md): header, status band (Now / You / Spend), Team now (the members
 * and who messages whom), shared work, the latest big moments, and the full
 * activity list below. Round runs never come here (TeamRunView keeps their
 * page as it was).
 *
 * Everything shown is read through the glance model (lib/teamGlance.ts);
 * only lib/teamGlanceAdapter.ts knows Temper's field names. The answer, stop
 * and message paths are the round page's own, unchanged.
 *
 * The page's clock is Temper's own (D4, D14): every age and duration counts
 * to the newest as_of of the run and events replies, live and ended, never
 * to the device's clock. Between reads nothing moves. While Temper doesn't
 * answer, durations stay as read, but every "ago" adds the time since the
 * last good read, and Now and You stop saying what is true now (D48, D64).
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { MessageSquare, RefreshCw, Square, WifiOff } from 'lucide-react';
import type { TeamRunRead } from '@/hooks/useTeamRun';
import type { TeamAnswerSender } from '@/hooks/useTeamAnswer';
import type { TeamMessageSender } from '@/hooks/useTeamMessage';
import { useTeamGlanceEvents } from '@/hooks/useTeamGlanceEvents';
import { toGlanceRun } from '@/lib/teamGlanceAdapter';
import {
  clockOf,
  composerHint,
  durationWords,
  glanceClock,
  msOf,
  nowCountsMembers,
  phaseEnded,
  type GlanceRun,
} from '@/lib/teamGlance';
import { teamWaits } from '@/lib/teamAnswer';
import { canMessage } from '@/lib/teamMessage';
import { firstLine } from '@/lib/teamText';
import type { TeamRun, TeamStatus } from '@/types/team';
import { TeamNote } from '@/components/team/TeamNote';
import { TeamGuardBanner } from '@/components/team/TeamGuardBanner';
import { teamBtn } from '@/components/team/teamUi';
import { cn } from '@/lib/utils';
import { StopRunDialog } from '@/components/team/run/StopRunDialog';
import { MessageComposer } from '@/components/team/run/MessageComposer';
import { StatusBand } from './StatusBand';
import { TeamMap } from './TeamMap';
import { SharedWork } from './SharedWork';
import { LatestMoments } from './LatestMoments';
import { AllActivity } from './AllActivity';
import { Facts } from './glanceUi';
import { glanceBodyBox, glanceHeadButton, glanceHeaderBox } from './glanceStyle';
import './glance.css';

const ANIMATE_KEY = 'temper_glance_animate';

/** Animate messages: on unless the owner switched it off in this browser session. */
function useAnimatePref(): [boolean, (on: boolean) => void] {
  const [on, setOn] = useState(() => {
    try {
      return window.sessionStorage.getItem(ANIMATE_KEY) !== 'off';
    } catch {
      return true;
    }
  });
  const set = useCallback((next: boolean) => {
    setOn(next);
    try {
      window.sessionStorage.setItem(ANIMATE_KEY, next ? 'on' : 'off');
    } catch {
      // Private mode: remembered for this page only.
    }
  }, []);
  return [on, set];
}

/** The system's reduced-motion setting, or the app's own "still" mode. */
function useReducedMotion(): boolean {
  const read = () =>
    (typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) ||
    (typeof document !== 'undefined' && document.documentElement.dataset.motion === 'still');
  const [reduced, setReduced] = useState(read);
  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-reduced-motion: reduce)');
    const update = () => setReduced(read());
    mq?.addEventListener?.('change', update);
    const mo = new MutationObserver(update);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-motion'] });
    return () => {
      mq?.removeEventListener?.('change', update);
      mo.disconnect();
    };
  }, []);
  return reduced;
}

function folderName(path: string | null): string | null {
  if (!path) return null;
  const parts = path.split('/').filter(Boolean);
  return parts[parts.length - 1] ?? path;
}

/**
 * Live: started_at to as_of; a start after Temper's clock has no age (D22),
 * it shows its clock time. Ended: the frozen elapsed_s (G5), never the clock.
 */
function runningWords(run: GlanceRun, now: number | null): string | null {
  const start = msOf(run.startedAt);
  if (!phaseEnded(run.phase.name)) {
    if (start === null || now === null) return null;
    return start > now ? `started at ${clockOf(run.startedAt)}` : `running ${durationWords(now - start)}`;
  }
  if (run.elapsedS !== null) return `ran ${durationWords(run.elapsedS * 1000)}`;
  return null;
}

/** The page's breadcrumbs, also on its loading and error views (SPEC 10). */
export function GlanceCrumbs() {
  // D35: every target at least 24 x 24 px, the breadcrumbs too.
  const crumb = 'inline-flex min-h-6 min-w-6 items-center underline-offset-2 hover:underline';
  return (
    <nav aria-label="Breadcrumb" className="text-sm text-temper-text-muted">
      <Link to="/team" className={crumb}>
        Team
      </Link>{' '}
      /{' '}
      <Link to="/team" className={crumb}>
        Projects
      </Link>
    </nav>
  );
}

function GlanceHeader({
  run,
  now,
  onMessage,
  onStop,
}: {
  run: GlanceRun;
  now: number | null;
  onMessage?: () => void;
  onStop?: () => void;
}) {
  const facts = [
    run.startedBy ? `Started by ${run.startedBy === 'owner' ? 'You' : run.startedBy}` : null,
    runningWords(run, now),
    run.leader ? `leader ${run.leader}` : null,
    {
      fact: `${run.members.length} ${run.members.length === 1 ? 'member' : 'members'}`,
      // D74: on a phone Now's "… of N members working" says it on the same first screen.
      className: nowCountsMembers(run) ? 'max-md:hidden' : undefined,
    },
    folderName(run.project) ? `code folder ${folderName(run.project)}` : null,
  ].filter((f) => f !== null);
  return (
    <header className={glanceHeaderBox}>
      <GlanceCrumbs />
      {/* D9, as the reference: on a phone 6 px round the goal, the buttons 10 px under it, full width in one row. */}
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-2.5 md:gap-y-3">
        <div className="flex min-w-0 flex-col gap-1.5 md:gap-1">
          {/* D40: the goal wraps balanced, never cut. SPEC 3: 28 px (22 on a phone); the meta line 15 px (14). */}
          <h1
            className="m-0 text-[22px] leading-[1.2] font-semibold text-balance break-words text-temper-text md:text-[28px]"
            data-testid="glance-title"
          >
            {firstLine(run.goal) || 'Team project'}
          </h1>
          <Facts className="text-sm text-temper-text-muted md:text-[15px]" testId="glance-facts" items={facts} />
        </div>
        {(onMessage || onStop) && (
          <div className="flex w-full flex-wrap gap-2 md:w-auto">
            {onMessage && (
              <button type="button" className={cn(teamBtn.secondary, glanceHeadButton)} onClick={onMessage}>
                <MessageSquare className="h-4 w-4" aria-hidden="true" />
                <span>Message a member</span>
              </button>
            )}
            {onStop && (
              <button type="button" className={cn(teamBtn.danger, glanceHeadButton)} onClick={onStop}>
                <Square className="h-4 w-4" aria-hidden="true" />
                <span>Stop project</span>
              </button>
            )}
          </div>
        )}
      </div>
    </header>
  );
}

export function GlanceRunView({
  raw,
  read,
  status,
  sender,
  messenger,
  stopOpen,
  onStopOpenChange,
  canStop,
}: {
  raw: TeamRun;
  read: TeamRunRead;
  status: TeamStatus | null;
  sender: TeamAnswerSender;
  messenger: TeamMessageSender;
  stopOpen: boolean;
  onStopOpenChange: (open: boolean) => void;
  canStop: boolean;
}) {
  const run = useMemo(() => toGlanceRun(raw), [raw]);
  const feed = useTeamGlanceEvents(run.executionId, run.eventsCursor);
  const now = glanceClock(run.asOf, feed.asOf);
  const [animate, setAnimate] = useAnimatePref();
  const reducedMotion = useReducedMotion();
  const { wait } = teamWaits(raw);
  const stale = read.failedAt !== null;
  // D64: how long Temper hasn't answered (device time since the last good read).
  const staleMs = stale && read.updatedAt !== null ? Math.max(0, (read.failedAt ?? 0) - read.updatedAt) : 0;
  const staleFor = stale ? durationWords(staleMs) : null;
  const agesAt = now !== null ? now + staleMs : null;
  const messaging = canMessage(raw);

  const toComposer = useCallback(() => {
    const box = document.getElementById('glance-message');
    if (!box) return;
    box.scrollIntoView({ block: 'center' });
    box.querySelector<HTMLElement>('select, textarea')?.focus();
  }, []);

  return (
    <div className="glance-root flex h-full flex-col overflow-auto bg-temper-bg" data-testid="glance-page" data-phase={run.phase.name}>
      <GlanceHeader
        run={run}
        now={now}
        onMessage={messaging ? toComposer : undefined}
        // Stop by liveness: offered until the phase has ended (owner_actions is history, never a menu).
        onStop={canStop && !phaseEnded(run.phase.name) ? () => onStopOpenChange(true) : undefined}
      />
      {/* Stays open when the run ends meanwhile: Temper's answer is read in it. */}
      <StopRunDialog
        open={stopOpen}
        onOpenChange={onStopOpenChange}
        executionId={raw.execution_id}
        workflow={raw.workflow}
        reasonLimit={status?.limits.stop_reason_max_chars}
        onStopped={read.refresh}
      />
      <div className={glanceBodyBox}>
        <TeamGuardBanner mode={status?.guard_mode} textScale="glance" />
        {/* D64: read out once when Temper stops answering; the note's count goes up every few seconds, so it isn't live. */}
        <p role="status" className="sr-only">
          {staleFor !== null ? 'Temper isn\u2019t answering. The page shows what it said last.' : ''}
        </p>
        {staleFor !== null && (
          <TeamNote
            tone="warn"
            icon={WifiOff}
            // SPEC 3: the stale note's words are 15 px. As the reference, Try again follows the words (not a column
            // beside them), so on a phone the note stays short and the band ends on the first screen (D84).
            className="text-[15px] max-md:px-2.5"
          >
            <b className="font-semibold">Temper hasn&apos;t answered for {staleFor}.</b>{' '}
            <span className="text-temper-text-muted">
              This is what it said last; nothing below moves until it answers again.
            </span>{' '}
            <button type="button" className={cn(teamBtn.secondary, 'ml-1.5 align-middle')} onClick={() => void read.refresh()}>
              <RefreshCw className="h-4 w-4" aria-hidden="true" />
              <span>Try again</span>
            </button>
          </TeamNote>
        )}
        <StatusBand
          run={run}
          now={now}
          agesAt={agesAt}
          staleFor={staleFor}
          wait={wait}
          sender={sender}
          limits={status?.limits ?? null}
          executionId={raw.execution_id}
        />
        <TeamMap
          run={run}
          feed={feed}
          now={now}
          animate={animate}
          onAnimateChange={setAnimate}
          reducedMotion={reducedMotion}
          staleFor={staleFor}
          agesAt={agesAt}
        />
        <div className="grid min-w-0 grid-cols-1 items-start gap-[14px] md:gap-4 lg:grid-cols-2">
          <SharedWork run={run} now={agesAt} />
          <LatestMoments run={run} events={feed.events} now={agesAt} ready={feed.ready} />
        </div>
        {/* The one history and the one count (home decision 3): no Timeline card on this page. */}
        <AllActivity run={run} events={feed.events} ready={feed.ready} />
        {(messaging || messenger.result !== null) && (
          <div id="glance-message" className="min-w-0">
            <MessageComposer
              textScale="glance"
              run={raw}
              limit={status?.limits.message_max_chars}
              sender={messenger}
              hint={(to) => {
                // D56: what happens to the message, from the chosen member's state.
                const h = composerHint(run, to);
                return h.name ? (
                  <>
                    <b className="font-semibold text-temper-text">{h.name}</b> {h.text}
                  </>
                ) : (
                  h.text
                );
              }}
            />
          </div>
        )}
      </div>
    </div>
  );
}
