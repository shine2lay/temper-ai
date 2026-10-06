import { useCallback, useRef, useState } from 'react';
import { postTeamMessage } from '@/lib/teamApi';
import { newAnswerRequestId } from '@/lib/teamAnswer';
import { messageFailed, messageRequestId, messageSent, type MessageOutcome, type MessageTry } from '@/lib/teamMessage';
import type { TeamRun } from '@/types/team';

export interface MessageResult {
  /** Counts up with every send. */
  seq: number;
  sent: MessageTry;
  outcome: MessageOutcome;
}

export interface TeamMessageSender {
  sending: boolean;
  result: MessageResult | null;
  send: (to: string, body: string) => Promise<MessageResult>;
  /** Sends the last message again with the same request id; only after Temper didn't answer. */
  retry: () => Promise<MessageResult | null>;
}

/**
 * Sends messages through team_message, one request id per message. When a
 * send gets no reply the id is kept: "Try again", or sending the same
 * words to the same member, reuses it, so Temper counts the message once.
 * After every send the run is read again, so the timeline shows it.
 */
export function useTeamMessage(
  executionId: string,
  refresh: () => Promise<TeamRun | null>,
  makeId: () => string = newAnswerRequestId,
): TeamMessageSender {
  const lastTry = useRef<MessageTry | null>(null);
  const seq = useRef(0);
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<MessageResult | null>(null);

  const sendTry = useCallback(
    async (attempt: MessageTry): Promise<MessageResult> => {
      lastTry.current = attempt;
      setSending(true);
      let outcome: MessageOutcome;
      try {
        outcome = messageSent(
          await postTeamMessage(executionId, { request_id: attempt.requestId, to: attempt.to, body: attempt.body }),
        );
      } catch (err) {
        outcome = messageFailed(err, attempt.requestId);
      }
      if (outcome.kind !== 'no_answer') lastTry.current = null;
      seq.current += 1;
      const done: MessageResult = { seq: seq.current, sent: attempt, outcome };
      setResult(done);
      setSending(false);
      void refresh();
      return done;
    },
    [executionId, refresh],
  );

  const send = useCallback(
    (to: string, body: string) =>
      sendTry({ requestId: messageRequestId(lastTry.current, to, body, makeId), to, body }),
    [sendTry, makeId],
  );

  const retry = useCallback(async () => {
    const last = lastTry.current;
    return last ? sendTry(last) : null;
  }, [sendTry]);

  return { sending, result, send, retry };
}
