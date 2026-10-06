/**
 * Messages to a member (team_message, Design's SPEC 5.6, board O2).
 *
 * One request id per message, reused only when the same message is sent
 * again after Temper didn't answer: then Temper counts it once. Any reply
 * settles it. Refusals show Temper's own words.
 */
import { TeamApiError } from '@/lib/teamApi';
import { refusalWords } from '@/lib/teamAnswer';
import type { TeamMessageSent, TeamRun } from '@/types/team';

/** Used only until /api/team/status is read. */
export const DEFAULT_MESSAGE_MAX_CHARS = 20_000;

/** The states a member can be messaged in (contract 4): the team is live. */
const MESSAGE_STATES = new Set(['running', 'paused', 'quiet', 'member_waiting', 'settings_changed']);

/** Whether the run view offers "Message a member". */
export function canMessage(run: Pick<TeamRun, 'state' | 'outcome'>): boolean {
  return run.outcome === null && MESSAGE_STATES.has(run.state);
}

/** One try at sending a message. */
export interface MessageTry {
  requestId: string;
  to: string;
  body: string;
}

/** The request id for a message: the last try's when it got no reply and nothing changed, else a new one. */
export function messageRequestId(last: MessageTry | null, to: string, body: string, make: () => string): string {
  if (last && last.to === to && last.body === body) return last.requestId;
  return make();
}

export type MessageOutcome =
  /** Temper took it: for the member's next turn, or held until the open question is answered. */
  | { kind: 'sent'; to: string; held: boolean; repeated: boolean }
  /** Temper said no, in its own words; nothing was sent. */
  | { kind: 'refused'; words: string; status: number }
  /** No reply: it may or may not have reached Temper. Trying again with the same id is safe. */
  | { kind: 'no_answer'; requestId: string };

export function messageSent(sent: TeamMessageSent): MessageOutcome {
  return {
    kind: 'sent',
    to: sent.to,
    held: sent.state === 'held' || sent.delivers === 'after_open_wait',
    repeated: sent.repeated === true,
  };
}

/** What a failed send means, from the error postTeamMessage threw. */
export function messageFailed(err: unknown, requestId: string): MessageOutcome {
  if (err instanceof TeamApiError) return { kind: 'refused', words: refusalWords(err.detail, err.status), status: err.status };
  return { kind: 'no_answer', requestId };
}
