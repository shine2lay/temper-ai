import { useCallback, useRef, useState } from 'react';
import { postTeamAnswer } from '@/lib/teamApi';
import type { TeamRun } from '@/types/team';
import {
  answerFailed,
  answerRequestId,
  answerSent,
  newAnswerRequestId,
  settlesRequest,
  type AnswerOutcome,
  type AnswerTry,
} from '@/lib/teamAnswer';

/** The last answer's outcome, with the question it was for. */
export interface AnswerResult {
  /** Counts up with every send, so the page can move focus to the newest result. */
  seq: number;
  waitId: string;
  outcome: AnswerOutcome;
  /**
   * The questions open at the first read after Temper replied: null until
   * that read is in, and when it failed.
   */
  openAfter: string[] | null;
}

export interface TeamAnswerSender {
  sending: boolean;
  result: AnswerResult | null;
  send: (waitId: string, answer: string, text: string) => Promise<AnswerOutcome>;
}

/**
 * Sends answers through team_answer, one request id per answer. When a
 * send gets no reply the id is kept, and sending the same answer and words
 * again reuses it, so Temper counts the answer once. Any reply settles it.
 * After every send the run is read again (`refresh`), so the page shows
 * what Temper did, including who answered first after a 409.
 */
export function useTeamAnswer(
  executionId: string,
  refresh: () => Promise<TeamRun | null>,
  makeId: () => string = newAnswerRequestId,
): TeamAnswerSender {
  const lastTry = useRef<AnswerTry | null>(null);
  const seq = useRef(0);
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<AnswerResult | null>(null);

  const send = useCallback(
    async (waitId: string, answer: string, text: string): Promise<AnswerOutcome> => {
      const requestId = answerRequestId(lastTry.current, waitId, answer, text, makeId);
      lastTry.current = { requestId, waitId, answer, text };
      setSending(true);
      let outcome: AnswerOutcome;
      try {
        outcome = answerSent(await postTeamAnswer(executionId, waitId, { request_id: requestId, answer, text }));
      } catch (err) {
        outcome = answerFailed(err, requestId);
      }
      if (settlesRequest(outcome)) lastTry.current = null;
      seq.current += 1;
      const mine = seq.current;
      setResult({ seq: mine, waitId, outcome, openAfter: null });
      setSending(false);
      void refresh().then((after) => {
        if (!after) return;
        const ids = after.open_waits.map((w) => w.wait_id);
        setResult((r) => (r && r.seq === mine ? { ...r, openAfter: ids } : r));
      });
      return outcome;
    },
    [executionId, refresh, makeId],
  );

  return { sending, result, send };
}
