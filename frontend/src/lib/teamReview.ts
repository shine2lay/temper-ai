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
