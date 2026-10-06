/**
 * Run statuses in which a run is still going: at work, or waiting on a person's answer.
 *
 * The server says "waiting" while a wait is open for a person (a gate, a step's question, a Pi
 * run's recovery question) and while a Pi run is parked on one. Such a run is not over: it keeps
 * its timer and its Cancel button, and offers no Resume. How it ended shows only once its
 * latest attempt has ended with no wait open.
 */
const GOING = new Set<string>(['running', 'waiting']);

export function isGoing(status: string | null | undefined): boolean {
  return GOING.has(status ?? '');
}
