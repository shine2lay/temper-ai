/**
 * Answering Temper from the Team page: the checks made before a send, the
 * request id an answer carries, and what each of Temper's replies means.
 *
 * Kept apart from the components so every rule and every word can be
 * tested on its own. Temper's own words (refusals, NEEDS_RESUME) are shown
 * as sent; the page's words are in Design's voice (SPEC sections 5.2, 5.8).
 */
import { TeamApiError, TeamNoAnswerError } from '@/lib/teamApi';
import { countChars, formatNumber } from '@/lib/teamText';
import type {
  TeamAnswerConflict,
  TeamAnswerOption,
  TeamAnswerResult,
  TeamLimits,
  TeamRun,
  TeamWait,
} from '@/types/team';

/** The limits the server sends; used only until /api/team/status is read. */
export const DEFAULT_TEAM_LIMITS: Pick<
  TeamLimits,
  'guide_max_chars' | 'reply_max_chars' | 'nudge_max_chars' | 'stop_reason_max_chars'
> = {
  guide_max_chars: 20_000,
  reply_max_chars: 20_000,
  nudge_max_chars: 4_000,
  stop_reason_max_chars: 2_000,
};

type WordLimits = typeof DEFAULT_TEAM_LIMITS;

/** How many characters an answer's words may have, as the server counts them. */
export function answerLimit(answer: string, limits: Partial<WordLimits> | null | undefined): number {
  const l = { ...DEFAULT_TEAM_LIMITS, ...(limits ?? {}) };
  switch (answer) {
    case 'reply':
      return l.reply_max_chars;
    case 'nudge':
      return l.nudge_max_chars;
    case 'stop':
      return l.stop_reason_max_chars;
    default:
      return l.guide_max_chars;
  }
}

/** Who the words go to: the member who asked, or else the leader. */
function wordsFor(wait: Pick<TeamWait, 'kind' | 'member'>, leader: string): string {
  return wait.kind === 'question' && wait.member ? wait.member : leader;
}

/** The words box's label for a picked answer ("Words for frontend", "Your reply to qa"). */
export function wordsLabel(option: TeamAnswerOption, wait: Pick<TeamWait, 'kind' | 'member'>, leader: string): string {
  if (option.answer === 'stop') return 'Your words with the stop';
  if (option.answer === 'reply') return `Your reply to ${wordsFor(wait, leader)}`;
  return `Words for ${wordsFor(wait, leader)}`;
}

/** " · needs words", " · words optional", or nothing for an answer that takes none. */
export function needsWordsTag(option: Pick<TeamAnswerOption, 'needs_text'>): string {
  if (option.needs_text === 'required') return 'needs words';
  if (option.needs_text === 'optional') return 'words optional';
  return '';
}

function characters(n: number): string {
  return `${formatNumber(n)} ${n === 1 ? 'character' : 'characters'}`;
}

/** Where a check failed: under the answers, or under the words box. */
export type AnswerCheck =
  | { ok: true; text: string }
  | { ok: false; field: 'answers' | 'words'; words: string };

/**
 * The checks made before anything is sent (Send itself is always enabled):
 * an answer is picked, required words are written, and the words fit.
 * `text` is what gets sent: no words for an answer that takes none, and
 * none for words that are only spaces.
 */
export function checkAnswer(
  option: TeamAnswerOption | null,
  rawText: string,
  wait: Pick<TeamWait, 'kind' | 'member'>,
  leader: string,
  limits: Partial<WordLimits> | null | undefined,
): AnswerCheck {
  if (!option) return { ok: false, field: 'answers', words: 'Pick an answer first.' };
  if (option.needs_text === 'none') return { ok: true, text: '' };
  const text = rawText.trim() === '' ? '' : rawText;
  if (option.needs_text === 'required' && text === '') {
    const who = wordsFor(wait, leader);
    return {
      ok: false,
      field: 'words',
      words: option.answer === 'reply' ? `Write your reply to ${who} first.` : `Write the words for ${who} first.`,
    };
  }
  const limit = answerLimit(option.answer, limits);
  const over = countChars(text) - limit;
  if (over > 0) {
    return {
      ok: false,
      field: 'words',
      words:
        option.answer === 'reply'
          ? `Shorten your reply first: it is ${characters(over)} over the limit of ${formatNumber(limit)}.`
          : `Shorten your words first: they are ${characters(over)} over the limit of ${formatNumber(limit)}.`,
    };
  }
  return { ok: true, text };
}

// --- request ids -----------------------------------------------------------------

/** A send whose reply never came: its id is reused for the same answer. */
export interface AnswerTry {
  requestId: string;
  waitId: string;
  answer: string;
  text: string;
}

/** A fresh id for one answer. */
export function newAnswerRequestId(): string {
  const c = globalThis.crypto;
  if (c && typeof c.randomUUID === 'function') return c.randomUUID();
  return `team-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/**
 * The request id for this send. One id per answer: the same id again only
 * when the last send got no reply and the answer and words are unchanged,
 * so Temper counts a retry once. Any reply from Temper settles the id
 * (the caller drops `last`), and the next send gets a new one.
 */
export function answerRequestId(
  last: AnswerTry | null,
  waitId: string,
  answer: string,
  text: string,
  make: () => string = newAnswerRequestId,
): string {
  if (last && last.waitId === waitId && last.answer === answer && last.text === text) return last.requestId;
  return make();
}

// --- Temper's replies --------------------------------------------------------------

export type AnswerOutcome =
  /** Kept, and the team goes on with it (Temper's own words, when it sent any). */
  | { kind: 'sent'; answer: string; repeated: boolean; at: string | null; message: string | null }
  /** Kept, but the run isn't running: Resume on the run page. Temper's words. */
  | { kind: 'needs_resume'; answer: string; message: string }
  /** 409: someone answered first. */
  | { kind: 'answered'; by: string | null; at: string | null; source: string | null }
  /** 409: a newer question replaced this one. */
  | { kind: 'replaced' }
  /** 409: the team has ended (closed or already rejected). */
  | { kind: 'ended' }
  /** 404: the question closed. Temper's words. */
  | { kind: 'not_open'; words: string }
  /** Any other refusal: Temper's words, as sent. */
  | { kind: 'refused'; words: string }
  /** No reply: the same request id is sent again on a retry. */
  | { kind: 'no_answer'; requestId: string };

/** Temper's NEEDS_RESUME words, in case a 200 ever comes without them. */
const NEEDS_RESUME_FALLBACK =
  'Approved and kept. The run is not running, so it needs Resume; when it comes back it goes on with this answer without asking again.';

export function answerSent(result: TeamAnswerResult): AnswerOutcome {
  if (result.needs_resume) {
    return { kind: 'needs_resume', answer: result.answer, message: result.message || NEEDS_RESUME_FALLBACK };
  }
  return {
    kind: 'sent',
    answer: result.answer,
    repeated: Boolean(result.repeated),
    at: result.at ?? null,
    message: result.message || null,
  };
}

/** The server's words in a refusal body: `problem`, `message` or the plain detail. */
export function refusalWords(detail: unknown, status: number): string {
  if (typeof detail === 'string' && detail.trim() !== '') return detail;
  if (detail && typeof detail === 'object') {
    const d = detail as { problem?: unknown; message?: unknown; detail?: unknown };
    if (typeof d.problem === 'string' && d.problem) return d.problem;
    if (typeof d.message === 'string' && d.message) return d.message;
    if (typeof d.detail === 'string' && d.detail) return d.detail;
  }
  return `Temper answered ${status}`;
}

/** What a failed send means, from the error postTeamAnswer threw. */
export function answerFailed(err: unknown, requestId: string): AnswerOutcome {
  if (err instanceof TeamApiError) {
    if (err.status === 409 && err.detail && typeof err.detail === 'object') {
      const c = err.detail as Partial<TeamAnswerConflict>;
      switch (c.reason) {
        case 'already_answered':
          return {
            kind: 'answered',
            by: c.answered_by ?? null,
            at: c.answered_at ?? null,
            source: c.answered_source ?? null,
          };
        case 'replaced':
          return { kind: 'replaced' };
        case 'closed':
        case 'already_rejected':
          return { kind: 'ended' };
        default:
          return { kind: 'refused', words: refusalWords(err.detail, err.status) };
      }
    }
    const words = refusalWords(err.detail, err.status);
    if (err.status === 404 && words === 'That question is no longer open') return { kind: 'not_open', words };
    return { kind: 'refused', words };
  }
  if (err instanceof TeamNoAnswerError) return { kind: 'no_answer', requestId };
  return { kind: 'no_answer', requestId };
}

/** The outcomes that settle the request id (anything Temper replied to). */
export function settlesRequest(outcome: AnswerOutcome): boolean {
  return outcome.kind !== 'no_answer';
}

// --- which question, and where a result shows ----------------------------------------

/**
 * The question the owner can answer now and the ones that come after it.
 * Temper asks one at a time: only the asked one has answers. None while
 * the team is cut off (interrupted) or has ended.
 */
export function teamWaits(
  run: Pick<TeamRun, 'open_waits' | 'state' | 'outcome'>,
): { wait: TeamWait | null; next: TeamWait[] } {
  if (run.outcome || ['interrupted', 'starting', 'done', 'stopped', 'failed', 'didnt_start'].includes(run.state)) {
    return { wait: null, next: [] };
  }
  const wait = run.open_waits.find((w) => w.asked) ?? run.open_waits[0] ?? null;
  return { wait, next: wait ? run.open_waits.filter((w) => w.wait_id !== wait.wait_id) : [] };
}

/**
 * Where the last answer's result shows:
 * - in the card, while its question is still the one asked;
 * - on its own where the card was, once that question has closed (sent,
 *   already answered, ended), and above a newer card when that newer
 *   question was already open when Temper replied (replaced);
 * - nowhere once a question has opened since: the owner has moved on.
 *
 * `openAfter` is the list of open questions at the first read after the
 * result came in, or null until that read is in.
 */
export function resultPlace(
  resultWaitId: string | null,
  cardWaitId: string | null,
  openAfter: readonly string[] | null,
): 'card' | 'alone' | 'none' {
  if (resultWaitId === null) return 'none';
  if (cardWaitId === null) return 'alone';
  if (cardWaitId === resultWaitId) return 'card';
  if (openAfter === null || openAfter.includes(cardWaitId)) return 'alone';
  return 'none';
}
