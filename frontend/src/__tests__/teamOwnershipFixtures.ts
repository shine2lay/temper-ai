/** Fictional IDs/text only; every field comes from captured Team serializer fixtures. */
import working from '../../e2e/fixtures/team/flow/real-g6/retry.json' with { type: 'json' };
import question from '../../e2e/fixtures/team/flow/real-g6/member_question.json' with { type: 'json' };
import settings from '../../e2e/fixtures/team/flow/derived/settings.json' with { type: 'json' };
import history from '../../e2e/fixtures/team/flow/real-g6/member_question-events.json' with { type: 'json' };
import round from '../../e2e/fixtures/team/run-running.json' with { type: 'json' };
import message from '../../e2e/fixtures/team/message-201-pending.json' with { type: 'json' };
import answer from '../../e2e/fixtures/team/journey-answer-200.json' with { type: 'json' };
import type { TeamRun } from '@/types/team';

export type Raw = Record<string, unknown>;
export const A = 'fixture-owner-a';
export const B = 'fixture-owner-b';
export const CLOCK = '2026-10-10T18:38:00.000Z';
const copy = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T;

export function flow(id: string, kind: 'working' | 'question' | 'settings' | 'ended' = 'working', cursor = 2): TeamRun {
  const raw = copy(kind === 'question' ? question : kind === 'settings' ? settings : working) as unknown as Raw;
  raw.execution_id = id;
  raw.trial_id = `trial-${id}`;
  raw.trial = { ...(raw.trial as Raw), goal: `Project ${id}`, request_id: `start-${id}` };
  raw.as_of = CLOCK;
  raw.events_cursor = cursor;
  raw.events_total = cursor;
  if (kind === 'ended') {
    raw.phase = { ...(raw.phase as Raw), name: 'done', reason: null };
    raw.state = 'done';
    raw.run_status = 'completed';
    raw.open_waits = [];
    raw.you = { count: 0, first: null };
  }
  return raw as unknown as TeamRun;
}

export function legacy(id: string): TeamRun {
  const run = copy(round.body) as unknown as TeamRun;
  run.execution_id = id;
  run.trial.goal = `Project ${id}`;
  return run;
}

/** Captured work-request shape, overlapping seq across Projects, distinct message IDs. */
export function event(id: string, seq: number, text = `Only ${id}`, at = CLOCK): Raw {
  return { ...copy(history.events[3]), seq, at, text, message_id: `${id}-message-${seq}` };
}
export function page(events: Raw[], cursor = 2, more = false, asOf = CLOCK) {
  return { events, cursor, more, as_of: asOf };
}
export const accepted = (to = 'lead', repeated = false) => ({ ...copy(message.body), to, repeated });
export function answered(waitId: string) {
  return { ...copy(answer.body), wait_id: waitId };
}
