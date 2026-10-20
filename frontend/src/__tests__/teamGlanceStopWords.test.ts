/**
 * Design SPEC's stopped row: a stopped or failed run's Now gives the words given with the stop (outcome.owner_words),
 * whole and as sent, with who gave them as the rounds outcome card names them (teamStopper: the stopping action's
 * caller, else the outcome's). Beside them Temper's generic "the run was cancelled" is left out; every other sentence
 * stays, and a run stopped without words reads as before. Known answers on real serializer replies (real-g7), with
 * neutral made-up words; the samples themselves stay unchanged.
 */
import { describe, expect, it } from 'vitest';
import { toGlanceRun } from '@/lib/teamGlanceAdapter';
import { nowCell } from '@/lib/teamGlance';
import { ownerWordsLabel } from '@/lib/teamText';
import stopped from '../../e2e/fixtures/team/flow/real-g7/stopped.json';
import stoppedCheckIn from '../../e2e/fixtures/team/flow/real-g7/stopped_check_in.json';
import failed from '../../e2e/fixtures/team/flow/real-g7/failed.json';
import working from '../../e2e/fixtures/team/flow/real-g7/starting.json';

type Raw = Record<string, unknown>;
const copy = (v: unknown): Raw => structuredClone(v) as Raw;

/** A stop with `words` given by `by`: the outcome and the stopping action say the same, as Temper records them. */
function stoppedBy(by: string, words: string | null): Raw {
  const body = copy(stopped);
  Object.assign(body.outcome as Raw, { owner_words: words, by });
  for (const action of body.owner_actions as Raw[]) {
    if (action.kind === 'stop') Object.assign(action, { by, source: 'api', detail: words === null ? {} : { reason: words } });
  }
  return body;
}

const WORDS = 'Stage window ended for today; no retry.';

describe('the words given with a stop, in Now', () => {
  it('happy path: a stop by temper with words shows them whole, labelled for temper, and drops the generic sentence', () => {
    const run = toGlanceRun(stoppedBy('temper', WORDS));
    expect(run.stopWords).toEqual({ words: WORDS, by: 'temper' });
    const cell = nowCell(run, null);
    expect(cell).toMatchObject({ word: 'Stopped', sentence: null, words: { words: WORDS, by: 'temper' }, edge: 'grey', icon: 'stop' });
    expect(ownerWordsLabel(cell.words?.by)).toBe("temper's words");
  });

  it("the owner's own stop: the real sample's words and caller, labelled \"Your words\"", () => {
    const run = toGlanceRun(copy(stopped));
    const outcome = stopped.outcome as Raw;
    expect(run.stopWords).toEqual({ words: outcome.owner_words, by: 'owner' });
    const cell = nowCell(run, null);
    expect(cell.sentence).toBeNull();
    expect(ownerWordsLabel(cell.words?.by)).toBe('Your words');
  });

  it("who: the stopping action's caller first, else the outcome's, else an unknown caller (teamStopper)", () => {
    const action = stoppedBy('temper', WORDS);
    (action.outcome as Raw).by = 'owner';
    expect(toGlanceRun(action).stopWords?.by).toBe('temper');
    const outcomeOnly = stoppedBy('temper', WORDS);
    outcomeOnly.owner_actions = (outcomeOnly.owner_actions as Raw[]).filter((a) => a.kind !== 'stop');
    expect(toGlanceRun(outcomeOnly).stopWords?.by).toBe('temper');
    (outcomeOnly.outcome as Raw).by = null;
    const unknown = toGlanceRun(outcomeOnly).stopWords;
    expect(unknown).toEqual({ words: WORDS, by: null });
    expect(ownerWordsLabel(unknown?.by)).toBe('Words from an unknown caller');
  });

  it('a failed run with words keeps its own sentence and adds the words', () => {
    const body = copy(failed);
    Object.assign(body.outcome as Raw, { owner_words: WORDS, by: 'temper' });
    const cell = nowCell(toGlanceRun(body), null);
    expect(cell.word).toBe('Failed');
    // The failed sample's own sentence: Temper's reason with its first letter capitalised (D119), the rest exact.
    expect(cell.sentence).toBe(failed.phase.reason.replace(/^./u, (first) => first.toUpperCase()));
    expect(cell.words).toEqual({ words: WORDS, by: 'temper' });
  });

  it('any other stop sentence stays beside the words (a stop at the check-in)', () => {
    const cell = nowCell(toGlanceRun(copy(stoppedCheckIn)), null);
    expect(cell.sentence).toBe('Stopped at the check-in at $100');
    expect(cell.words?.words).toBe((stoppedCheckIn.outcome as Raw).owner_words);
  });

  it.each(['the run was cancelled', 'The run was cancelled.', 'THE RUN WAS CANCELLED!', ' the run was cancelled \n'])(
    'the generic %j is left out beside the words, any case or end punctuation',
    (reason) => {
      const body = stoppedBy('temper', WORDS);
      (body.phase as Raw).reason = reason;
      expect(nowCell(toGlanceRun(body), null).sentence).toBeNull();
    },
  );

  it('a sentence that only starts like the generic one stays', () => {
    const body = stoppedBy('temper', WORDS);
    (body.phase as Raw).reason = 'the run was cancelled by the reviewer';
    expect(nowCell(toGlanceRun(body), null).sentence).toBe('The run was cancelled by the reviewer');
  });

  it.each([null, '', ' \n '])('no words (%j): no words, and the generic sentence as before', (words) => {
    const run = toGlanceRun(stoppedBy('temper', words));
    expect(run.stopWords).toBeNull();
    const cell = nowCell(run, null);
    expect(cell.sentence).toBe('The run was cancelled');
    expect(cell).not.toHaveProperty('words');
  });

  it('the words are kept as sent: a new line, a long word and HTML-looking text, never cut or trimmed', () => {
    const words = `  Pausing here.\nThen: ${'unbreakable'.repeat(12)} <b>stays</b> & whole.\n`;
    const cell = nowCell(toGlanceRun(stoppedBy('temper', words)), null);
    expect(cell.words?.words).toBe(words);
  });

  it('only stopped and failed runs show them: a live run with an outcome left over shows none', () => {
    const body = copy(working);
    body.outcome = { decision: 'cancelled', reason: null, owner_words: WORDS, problems: [], by: 'temper', at: null, done: null };
    expect(nowCell(toGlanceRun(body), null)).not.toHaveProperty('words');
  });
});
