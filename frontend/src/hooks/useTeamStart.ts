import { useCallback, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { postTeamCheck, postTeamTrial } from '@/lib/teamApi';
import { newAnswerRequestId } from '@/lib/teamAnswer';
import {
  checkAnswered,
  checkFailed,
  sameInput,
  startFailed,
  trialRequestId,
  type CheckOutcome,
  type StartOutcome,
  type TrialTry,
} from '@/lib/teamForm';
import type { TeamTrialInput } from '@/types/team';

export interface TeamStarter {
  /** What is being sent, if anything. */
  busy: 'check' | 'start' | null;
  check: (input: TeamTrialInput) => Promise<CheckOutcome>;
  start: (input: TeamTrialInput) => Promise<StartOutcome>;
  /** The request Temper didn't answer, while the form still matches it: Run trial reads "Try again". */
  retrying: (input: TeamTrialInput) => TrialTry | null;
}

/**
 * Check and Run trial. One request id per submission: when Temper doesn't
 * answer, the id is kept, and sending the same form again reuses it, so
 * Temper counts the trial once. Any answer settles it. A started trial
 * makes the trials list read again.
 */
export function useTeamStart(makeId: () => string = newAnswerRequestId): TeamStarter {
  const queryClient = useQueryClient();
  const lastTry = useRef<TrialTry | null>(null);
  const [busy, setBusy] = useState<'check' | 'start' | null>(null);
  // Re-render when the kept try changes, so the button's words follow it.
  const [, setKept] = useState<TrialTry | null>(null);

  const check = useCallback(async (input: TeamTrialInput): Promise<CheckOutcome> => {
    setBusy('check');
    try {
      return checkAnswered(await postTeamCheck(input));
    } catch (err) {
      return checkFailed(err);
    } finally {
      setBusy(null);
    }
  }, []);

  const start = useCallback(
    async (input: TeamTrialInput): Promise<StartOutcome> => {
      const attempt: TrialTry = { requestId: trialRequestId(lastTry.current, input, makeId), input };
      lastTry.current = attempt;
      setBusy('start');
      let outcome: StartOutcome;
      try {
        outcome = { kind: 'started', started: await postTeamTrial({ ...input, request_id: attempt.requestId }) };
      } catch (err) {
        outcome = startFailed(err, attempt.requestId);
      }
      if (outcome.kind !== 'no_answer') lastTry.current = null;
      setKept(lastTry.current);
      if (outcome.kind === 'started') void queryClient.invalidateQueries({ queryKey: ['team', 'trials'] });
      setBusy(null);
      return outcome;
    },
    [makeId, queryClient],
  );

  const retrying = useCallback((input: TeamTrialInput): TrialTry | null => {
    const last = lastTry.current;
    return last && sameInput(last.input, input) ? last : null;
  }, []);

  return { busy, check, start, retrying };
}
