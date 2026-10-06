import { forwardRef } from 'react';
import { Link } from 'react-router-dom';
import { ExternalLink, WifiOff } from 'lucide-react';
import { isoOf, shortId, teamSource, teamTime, teamTimeFull } from '@/lib/teamText';
import type { AnswerOutcome } from '@/lib/teamAnswer';
import { TeamNote } from '../TeamNote';
import { TeamWho } from '../TeamWho';
import { teamLink } from '../teamUi';

/** The id the page moves focus to after a send. */
export const ANSWER_RESULT_ID = 'team-answer-result';

/** Temper's words, then a full stop when they don't end with one. */
function Sentence({ words }: { words: string }) {
  return (
    <>
      <span data-engine-words="">{words}</span>
      {/[.!?]$/.test(words.trim()) ? '' : '.'}
    </>
  );
}

/**
 * What became of an answer (Design's O3 board): sent, kept but needing
 * Resume (Temper's own words), already answered by someone (who, from
 * where, when), replaced, ended, closed, refused (Temper's words, as
 * sent), or no reply at all (trying again is safe: same request id).
 */
export const AnswerResultNote = forwardRef<
  HTMLDivElement,
  { outcome: AnswerOutcome; executionId: string; hasWords: boolean }
>(function AnswerResultNote({ outcome, executionId, hasWords }, ref) {
  let note;
  switch (outcome.kind) {
    case 'sent':
      note = (
        <TeamNote tone="ok" live title={`Answer sent: ${outcome.answer}.`}>
          {outcome.repeated
            ? 'Temper already had it from your last try; it counted once.'
            : 'Temper has it. The page shows what happens next.'}
          {outcome.message && (
            <span className="mt-1 block" data-engine-words="">
              {outcome.message}
            </span>
          )}
        </TeamNote>
      );
      break;
    case 'needs_resume':
      note = (
        <TeamNote tone="info" live title={`Answer kept: ${outcome.answer}.`}>
          <p className="m-0">{outcome.message}</p>
          <p className="m-0 mt-1">
            <Link to={`/workflow/${executionId}`} className={teamLink}>
              <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
              <span>Open the run page</span>
            </Link>
          </p>
        </TeamNote>
      );
      break;
    case 'answered': {
      const source = outcome.source ? teamSource(outcome.source).inline : null;
      note = (
        <TeamNote
          tone="warn"
          live
          title={
            <>
              Already answered by <TeamWho by={outcome.by} unknownLabel="an unknown caller" />
              {source && ` ${source}`}
              {outcome.at && (
                <>
                  {' '}
                  at{' '}
                  <time dateTime={isoOf(outcome.at)} title={teamTimeFull(outcome.at)}>
                    {teamTime(outcome.at)}
                  </time>
                </>
              )}
              .
            </>
          }
        >
          Your answer wasn&apos;t used. The page shows what happened next.
        </TeamNote>
      );
      break;
    }
    case 'replaced':
      note = (
        <TeamNote tone="warn" live title="This question was replaced by a newer one.">
          Read the new question; your answer wasn&apos;t used.
        </TeamNote>
      );
      break;
    case 'ended':
      note = (
        <TeamNote tone="bad" live title="The team has ended.">
          Your answer wasn&apos;t used.
        </TeamNote>
      );
      break;
    case 'not_open':
      note = (
        <TeamNote tone="bad" live title={<Sentence words={outcome.words} />}>
          The page refreshes to show what changed.
        </TeamNote>
      );
      break;
    case 'refused':
      note = (
        <TeamNote tone="bad" live title="Temper refused the answer:">
          <span data-engine-words="">{outcome.words}</span>
          {hasWords && <span className="text-temper-text-muted"> Your words are kept.</span>}
        </TeamNote>
      );
      break;
    case 'no_answer':
      note = (
        <TeamNote tone="warn" icon={WifiOff} live title="Temper didn't answer.">
          <p className="m-0">Trying again is safe: the same request counts once.</p>
          <p className="m-0 mt-0.5 text-xs">
            Request <span className="font-mono">{shortId(outcome.requestId)}</span> · your inputs are kept.
          </p>
        </TeamNote>
      );
      break;
  }
  return (
    <div ref={ref} id={ANSWER_RESULT_ID} tabIndex={-1} data-answer-result={outcome.kind} className="outline-none focus-visible:outline-2">
      {note}
    </div>
  );
});
