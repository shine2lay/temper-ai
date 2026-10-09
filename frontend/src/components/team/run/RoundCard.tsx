import { cn } from '@/lib/utils';
import { decisionWords, ENDED_STATES } from '@/lib/teamText';
import { isRefusedDone, openReviewWords, reviewDecision, roundReviews } from '@/lib/teamReview';
import type { TeamReview, TeamRun } from '@/types/team';
import { EngineQuote } from '../TeamQuote';
import { teamCard, teamLabel } from '../teamUi';
import { VerdictChip } from './Timeline';
import { ClampedSummary } from './ClampedSummary';

/** At most this many segments are drawn; the words always carry the numbers. */
const MAX_SEGMENTS = 12;

/** Lines of the decided review's summary shown before "Show all". */
const ROUND_SUMMARY_LINES = 3;

function ReviewFacts({ review }: { review: TeamReview }) {
  return (
    <>
      {review.commit && (
        <>
          {' '}
          <span className="text-temper-text-muted">· commit</span>{' '}
          <span className="font-mono">{review.commit.slice(0, 7)}</span>
        </>
      )}
      {review.files_count != null && (
        <span className="text-temper-text-muted">
          {' '}
          · {review.files_count} {review.files_count === 1 ? 'file' : 'files'}
        </span>
      )}
    </>
  );
}

/**
 * Every reviewer's verdict, one chip each: the name and the verdict in
 * words, colour only as an extra. Disagreements show as they are.
 */
function Verdicts({ review }: { review: TeamReview }) {
  const verdicts = Object.entries(review.views);
  if (verdicts.length === 0) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {verdicts.map(([member, view]) => (
        <VerdictChip key={member} verdict={view.verdict} label={`${member}: ${view.verdict.replace(/_/g, ' ')}`} />
      ))}
    </div>
  );
}

/**
 * The round the team is on: how many rounds have gone by without done
 * (the team pauses for you when it reaches the limit); the latest decided
 * review with the leader's decision, every reviewer's verdict and the
 * leader's summary ("No decision yet" before the first); and a newer review
 * still going, on a line of its own, so an empty new review never hides the
 * last result.
 *
 * `inWait` draws it inside the needs-you card (under the question, no card
 * of its own), where it moves while Temper waits for you.
 */
export function RoundCard({ run, inWait = false }: { run: TeamRun; inWait?: boolean }) {
  const { round, reviews, trial } = run;
  if (round.current < 1 && reviews.length === 0) return null;

  const limit = round.pause_after_rounds || trial.pause_after_rounds;
  const without = round.keep_goings;
  const segments = limit > 0 && limit <= MAX_SEGMENTS ? limit : 0;
  const { decided, open } = roundReviews(reviews);
  // Ended runs (done, stopped, failed, didn't start) can have no outcome: one that ended
  // before the team wrote it reads by the run's own status (team_view.team_state). Their
  // undecided review is never decided, not open.
  const live = run.outcome === null && !ENDED_STATES.has(run.state) && run.state !== 'interrupted';
  // A done run's outcome card already shows that review's summary in full.
  const shownInOutcome = decided !== null && run.outcome?.done?.review_id === decided.review_id;
  const summary = decided?.summary?.trim() && !shownInOutcome ? decided.summary : null;
  const meterWords = `${without} of ${limit} rounds without done`;
  const decision = decided ? reviewDecision(decided) : null;
  const openLine = open ? openReviewWords(open, trial.leader, live) : null;

  const Heading = inWait ? 'h3' : 'h2';
  return (
    <section
      aria-labelledby="team-round-title"
      data-round-card={inWait ? 'in-wait' : 'card'}
      className={inWait ? 'border-t border-[var(--team-wait-card-border)] pt-3' : cn(teamCard, 'p-4')}
    >
      <Heading id="team-round-title" className={teamLabel}>
        Round {Math.max(round.current, 1)}
      </Heading>
      {segments > 0 && (
        <div role="img" aria-label={meterWords} className="mb-2 flex gap-1.5">
          {Array.from({ length: segments }, (_, i) => (
            <span
              key={i}
              className={cn(
                'h-2 w-10 rounded border',
                i < without ? 'border-temper-waiting bg-temper-waiting' : 'border-temper-control',
              )}
            />
          ))}
        </div>
      )}
      <p className="m-0 text-xs text-temper-text">
        <b className="font-semibold">
          {without} of {limit}
        </b>{' '}
        rounds without done <span className="text-temper-text-muted">· the team pauses for you at {limit}</span>
      </p>
      {decided ? (
        <div data-review="decided">
          <div className="my-3 border-t border-temper-border" />
          <p className="m-0 text-xs text-temper-text">
            <b className="font-semibold">Latest decided review</b>
            <ReviewFacts review={decided} />
          </p>
          {isRefusedDone(decided) ? (
            <>
              <p className="m-0 mt-1 text-xs text-temper-text" data-review-decision>
                <span className="text-temper-text-muted">Round {decided.round} ·</span> {trial.leader}{' '}
                <b className="font-semibold">said done; refused</b>
              </p>
              <EngineQuote className="mt-2" label="Temper said:">
                {decided.refusal ?? ''}
              </EngineQuote>
            </>
          ) : (
            <p className="m-0 mt-1 text-xs text-temper-text" data-review-decision>
              <span className="text-temper-text-muted">Round {decided.round} ·</span> {trial.leader} decided
              {decision && (
                <>
                  : <b className="font-semibold">{decisionWords(decision)}</b>
                </>
              )}
            </p>
          )}
          <Verdicts review={decided} />
          {summary && (
            <div className="mt-2 text-sm" data-review-summary>
              <p className="m-0 mb-1 text-xs text-temper-text-muted">{trial.leader}&apos;s summary</p>
              <ClampedSummary content={summary} lines={ROUND_SUMMARY_LINES} />
            </div>
          )}
        </div>
      ) : (
        <div data-review="none">
          <div className="my-3 border-t border-temper-border" />
          <p className="m-0 text-xs text-temper-text">
            <b className="font-semibold">No decision yet</b>
          </p>
        </div>
      )}
      {open && openLine && (
        <div data-review="open">
          <div className="my-3 border-t border-temper-border" />
          <p className="m-0 text-xs text-temper-text">
            <b className="font-semibold">{openLine.head}</b>{' '}
            <span className="text-temper-text-muted">· {openLine.rest}</span>
            <ReviewFacts review={open} />
          </p>
          <Verdicts review={open} />
        </div>
      )}
    </section>
  );
}
