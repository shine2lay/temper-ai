import { useId, useRef, useState } from 'react';
import { CircleAlert, Square, WifiOff } from 'lucide-react';
import { cn } from '@/lib/utils';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { postCancelRun, TeamApiError } from '@/lib/teamApi';
import { refusalWords, DEFAULT_TEAM_LIMITS } from '@/lib/teamAnswer';
import { countChars, formatNumber } from '@/lib/teamText';
import { TeamCharCount } from '../TeamCharCount';
import { TeamDialog, TeamDialogCancel, TeamDialogLabel } from '../TeamDialog';
import { TeamNote } from '../TeamNote';
import { teamBtn } from '../teamUi';
import { runResultHeading } from './runFocus';

/** The statuses that mean the stop took: the normal stopped flow follows. */
const STOPPED_STATUSES: ReadonlySet<string> = new Set(['cancelling', 'cancelled']);

type StopState =
  | { kind: 'idle' }
  | { kind: 'sending' }
  /** Temper refused (404, 400, 401, 403): its words, as sent. Nothing was stopped. */
  | { kind: 'refused'; words: string }
  /** No reply: trying again is safe. */
  | { kind: 'no_answer' }
  /** G13: the run had already ended; nothing was stopped. */
  | { kind: 'already_ended'; status: string; hadReason: boolean };

/**
 * Stop run (Design's O1): POST /api/runs/{id}/cancel with the owner's
 * reason. It ends the team and cancels the run. A refusal keeps the dialog
 * open with Temper's words (O1b); a run that had already ended answers 200
 * with its own status, and the dialog says nothing was stopped (G13).
 */
export function StopRunDialog({
  open,
  onOpenChange,
  executionId,
  workflow,
  reasonLimit,
  onStopped,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  executionId: string;
  workflow: string;
  reasonLimit: number | null | undefined;
  /** Read the run again: after a stop, and at once when it had already ended. */
  onStopped: () => void;
}) {
  const ids = useId();
  const reasonId = `${ids}-reason`;
  const countId = `${ids}-count`;
  const hintId = `${ids}-hint`;
  const errorId = `${ids}-error`;
  const limit = reasonLimit ?? DEFAULT_TEAM_LIMITS.stop_reason_max_chars;
  const [reason, setReason] = useState('');
  const [tooLong, setTooLong] = useState<string | null>(null);
  const [state, setState] = useState<StopState>({ kind: 'idle' });
  const reasonBox = useRef<HTMLTextAreaElement | null>(null);
  const closeButton = useRef<HTMLButtonElement | null>(null);

  const ended = state.kind === 'already_ended';
  const sending = state.kind === 'sending';

  function reset(nextOpen: boolean) {
    if (!nextOpen) {
      setReason('');
      setTooLong(null);
      setState({ kind: 'idle' });
    }
    onOpenChange(nextOpen);
  }

  async function stop() {
    const over = countChars(reason) - limit;
    if (over > 0) {
      setTooLong(
        `Shorten your reason first: it is ${formatNumber(over)} ${over === 1 ? 'character' : 'characters'} over the limit of ${formatNumber(limit)}.`,
      );
      reasonBox.current?.focus();
      return;
    }
    setTooLong(null);
    setState({ kind: 'sending' });
    const words = reason.trim() === '' ? '' : reason;
    try {
      const result = await postCancelRun(executionId, words);
      if (STOPPED_STATUSES.has(result.status)) {
        onStopped();
        reset(false);
        return;
      }
      setState({ kind: 'already_ended', status: result.status, hadReason: words !== '' });
      onStopped();
      // The footer is now one button, Close, and it takes focus.
      window.setTimeout(() => closeButton.current?.focus(), 0);
    } catch (err) {
      if (err instanceof TeamApiError) setState({ kind: 'refused', words: refusalWords(err.detail, err.status) });
      else setState({ kind: 'no_answer' });
    }
  }

  return (
    <TeamDialog
      open={open}
      onOpenChange={reset}
      busy={sending}
      initialFocus={reasonBox}
      focusWhenGone={runResultHeading}
      testId="team-stop-run-dialog"
      title={
        <>
          Stop run: <span className="font-mono font-semibold">{workflow}</span>
        </>
      }
      subtitle="Ends the team and cancels the run."
      hint="You can't undo this."
      buttons={
        ended ? (
          <TeamDialogCancel ref={closeButton} className={teamBtn.secondaryMd}>
            Close
          </TeamDialogCancel>
        ) : (
          <>
            <TeamDialogCancel className={teamBtn.secondaryMd} disabled={sending}>
              Keep running
            </TeamDialogCancel>
            <button type="button" className={teamBtn.dangerMd} onClick={() => void stop()} disabled={sending}>
              <Square className="h-4 w-4" aria-hidden="true" />
              <span>{sending ? 'Stopping…' : 'Stop run'}</span>
            </button>
          </>
        )
      }
    >
      <TeamDialogLabel>What stops</TeamDialogLabel>
      <ul className="m-0 flex list-disc flex-col gap-1 pl-5 text-sm text-temper-text">
        <li>Every member&apos;s turn ends, and any open question is closed with your reason.</li>
        <li>
          The run is cancelled: the run list will show it as <b className="font-semibold">cancelled</b>; this page shows
          Stopped, with &ldquo;the run was cancelled&rdquo;.
        </li>
        <li>Nothing more is spent.</li>
      </ul>
      <div className="mt-1 flex flex-col gap-1">
        <div className="flex flex-wrap items-baseline gap-2">
          <label htmlFor={reasonId} className="text-sm font-semibold text-temper-text">
            Your reason
          </label>
          <span className="text-xs text-temper-text-muted">optional</span>
          <TeamCharCount id={countId} className="ml-auto" text={reason} limit={limit} />
        </div>
        <textarea
          ref={reasonBox}
          id={reasonId}
          value={reason}
          readOnly={ended}
          onChange={(e) => {
            setReason(e.target.value);
            if (tooLong) setTooLong(null);
          }}
          aria-invalid={tooLong ? 'true' : undefined}
          aria-describedby={cn(countId, hintId, tooLong && errorId)}
          rows={3}
          className={cn(
            'min-h-[72px] w-full resize-y rounded-md border bg-temper-panel px-3 py-2 text-sm text-temper-text',
            tooLong ? 'border-[var(--badge-failed-border)]' : 'border-temper-control',
          )}
        />
        {tooLong && (
          <p id={errorId} className="m-0 inline-flex items-center gap-1.5 text-sm font-semibold text-[var(--badge-failed-text)]">
            <CircleAlert className="h-4 w-4 shrink-0" aria-hidden="true" />
            {tooLong}
          </p>
        )}
        <p id={hintId} className="m-0 text-xs text-temper-text-muted">
          Shown quoted with the outcome, labelled as yours.
        </p>
      </div>
      {state.kind === 'refused' && (
        <TeamNote tone="bad" live className="mt-1">
          <b className="font-semibold">Temper refused:</b> <span data-engine-words="">{state.words}</span> Nothing was
          stopped.
        </TeamNote>
      )}
      {state.kind === 'no_answer' && (
        <TeamNote tone="warn" icon={WifiOff} live className="mt-1" title="Temper didn't answer.">
          Trying again is safe: stopping a run that is already stopping changes nothing.
        </TeamNote>
      )}
      {state.kind === 'already_ended' && (
        <TeamNote tone="info" live className="mt-1">
          <span data-g13="">
            <b className="font-semibold">Nothing was stopped.</b> The run had already ended (
            {/* On the panel colour, as in the run list, so it reads the same and keeps its contrast. */}
            <span className="inline-flex rounded-md bg-temper-panel align-middle">
              <StatusBadge status={state.status} />
            </span>
            ) before your stop reached Temper.
            {state.hadReason && " Your reason wasn't recorded."}
          </span>
        </TeamNote>
      )}
    </TeamDialog>
  );
}
