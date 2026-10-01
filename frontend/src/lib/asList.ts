/**
 * A list, whatever arrived.
 *
 * The run page draws things the server describes, and the same word can mean
 * two things in two messages: an agent's `llm_calls` is the calls themselves
 * in a snapshot and the number of them in a completion event. Walking a
 * number throws "calls is not iterable", and a throw while drawing takes the
 * whole run page down mid-run.
 *
 * The store refuses to store a list field that is not a list (see
 * `_mergeable` in store/executionStore.ts) — that is the fix. This is the
 * second lock, for the places that read: a missing or bent list draws as
 * nothing instead of ending the render.
 */
// Two signatures so a typed field keeps its element type (the first) while a
// value of unknown shape is still accepted (the second).
export function asList<T>(value: readonly T[] | null | undefined): T[];
export function asList<T = unknown>(value: unknown): T[];
export function asList<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}
