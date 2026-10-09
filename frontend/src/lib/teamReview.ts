/**
 * A refused done (contract E14): the leader said done, Temper refused it,
 * and the round counts as keep going.
 *
 * The API never marks it on the decision entry. The timeline's decision
 * entry reads keep_going with data.review_id, and the same response's
 * reviews[] entry with that id reads done_refused with Temper's refusal.
 * The timeline and the round card both decide by these two helpers, so they
 * never disagree. Nothing here reads event_type, a summary, or a refusal
 * on the entry itself.
 */
import type { TeamDecisionEntry, TeamReview, TeamRun } from '@/types/team';

/**
 * A review is a refused done when its decision is done_refused AND it
 * carries Temper's refusal. Both are required: the review's decision and
 * its refusal come from different records, so together they never mark an
 * ordinary keep going.
 */
export function isRefusedDone(review: Pick<TeamReview, 'decision' | 'refusal'> | null | undefined): boolean {
  if (!review) return false;
  return review.decision === 'done_refused' && typeof review.refusal === 'string' && review.refusal.trim() !== '';
}

/**
 * The decision a review shows when it isn't a refused done. A done_refused
 * review without Temper's words counts as keep going, as the timeline's
 * entry for it reads, so the round card and the timeline agree.
 */
export function reviewDecision(review: Pick<TeamReview, 'decision'>): string | null {
  return review.decision === 'done_refused' ? 'keep_going' : review.decision;
}

/**
 * The refused review a timeline decision entry stands for, or null: the
 * entry reads keep_going, names its review, and that review is a refused
 * done.
 */
export function refusedDoneReview(
  entry: Pick<TeamDecisionEntry, 'entry' | 'decision' | 'data'>,
  run: Pick<TeamRun, 'reviews'>,
): TeamReview | null {
  if (entry.entry !== 'decision' || entry.decision !== 'keep_going') return null;
  const reviewId = entry.data?.review_id;
  if (!reviewId) return null;
  const review = run.reviews.find((r) => r.review_id === reviewId);
  return review && isRefusedDone(review) ? review : null;
}

function isDecided(review: TeamReview): boolean {
  return review.state === 'decided' || review.decision !== null;
}

function newest(reviews: TeamReview[], keep: (review: TeamReview) => boolean): TeamReview | null {
  return reviews.reduce<TeamReview | null>(
    (best, r) => (keep(r) && (best === null || r.round >= best.round) ? r : best),
    null,
  );
}

/**
 * The newest review with the leader's decision, and a newer one still
 * without it. Temper opens the next round's review in the same second it
 * records a keep going, so the newest review is often still empty: the
 * round card shows it on its own line, and it never takes the decided
 * one's place.
 */
export function roundReviews(reviews: TeamReview[]): { decided: TeamReview | null; open: TeamReview | null } {
  const decided = newest(reviews, isDecided);
  const open = newest(reviews, (r) => !isDecided(r) && (decided === null || r.round > decided.round));
  return { decided, open };
}

function verdictsIn(count: number): string {
  return count === 1 ? '1 verdict in' : `${count} verdicts in`;
}

/**
 * The line for a review without a decision, from Temper's own state, in
 * Design's words ("verdicts", never "views", which reads like a page view):
 * open, with members' verdicts coming in; collected, all in and the leader
 * decides next; or left undecided by a run that has ended (`live` false).
 * A review carries no expected number of verdicts, so the line never says
 * "2 of 4".
 */
export function openReviewWords(
  review: TeamReview,
  leader: string,
  live: boolean,
): { head: string; rest: string } {
  const count = Object.keys(review.views).length;
  const head = `Round ${review.round} review`;
  if (!live) return { head, rest: count === 0 ? 'never decided, no verdicts' : `never decided, ${verdictsIn(count)}` };
  if (review.state === 'collected') return { head, rest: `all verdicts in, waiting for ${leader}'s decision` };
  return { head: `${head} open`, rest: count === 0 ? 'no verdicts yet' : verdictsIn(count) };
}
