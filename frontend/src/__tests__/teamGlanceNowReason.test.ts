/** H17: Now alone retains every genuine Stopped/Failed reason character.
 * Fixed inputs; serializer samples remain immutable. Activity/Interrupted/D121
 * counter-cases fence this correction from changing their existing contracts. */
import { describe, expect, it } from 'vitest';
import { toGlanceRun, toGlanceEvent } from '@/lib/teamGlanceAdapter';
import { activityRow, cutAt, endedWords, nowCell, type GlanceRun } from '@/lib/teamGlance';
import stopped from '../../e2e/fixtures/team/flow/real-g7/stopped.json';
import failed from '../../e2e/fixtures/team/flow/real-g7/failed.json';
import interrupted from '../../e2e/fixtures/team/flow/real-g6/interrupted.json';
import didntStart from '../../e2e/fixtures/team/flow/real-g7/didnt_start.json';

function run(phase: 'stopped' | 'failed', reason: string | null): GlanceRun {
  const body = structuredClone(phase === 'stopped' ? stopped : failed);
  return toGlanceRun({ ...body, phase: { ...body.phase, reason } });
}
const cap = (s: string) => s.replace(/^./u, (first) => first.toUpperCase());

describe('H17 known negatives: genuine multiline Now reason', () => {
  it.each([
    ['stopped', 'the owner cancelled it.\nThe CSV is kept.'],
    ['failed', 'account refused the call.\nThe recorded work is kept.'],
  ] as const)('%s retains the full supplied remainder', (phase, supplied) => {
    const cell = nowCell(run(phase, supplied), null);
    expect(cell.sentence).toBe(cap(supplied));
    expect(cell.sentence?.slice(1)).toBe(supplied.slice(1));
  });
});

describe('H17 full-reason edges and unchanged counter-cases', () => {
  it.each(['stopped', 'failed'] as const)('%s keeps ending newline, blank line, punctuation and Unicode', (phase) => {
    const supplied = 'the CSV is kept; do not infer any new work.\n\nCSV: 東京 🧪\n';
    expect(nowCell(run(phase, supplied), null).sentence).toBe(cap(supplied));
    expect(nowCell(run(phase, supplied), null).sentence?.endsWith('\n')).toBe(true);
  });
  it.each(['team_done', 'run_completed', 'team_stopped', 'run_cancelled', 'account_refused'])('token %s followed by explanation is genuine, not token-only', (token) => {
    const supplied = `${token}\nThe genuine supplied explanation.\n`;
    expect(nowCell(run('failed', supplied), null).sentence).toBe(cap(supplied));
  });
  it.each(['team_done', 'run_completed', 'team_stopped', 'run_cancelled'])('whole token %s alone stays suppressed', (token) => {
    for (const phase of ['stopped', 'failed'] as const) {
      for (const reason of [token, `  ${token.toUpperCase()}!!!\n`]) {
        expect(nowCell(run(phase, reason), null).sentence).toBeNull();
        expect(endedWords(phase, reason)).toBe(phase === 'failed' ? 'Failed' : 'Stopped');
      }
    }
  });
  it.each(['account_refused', ' ACCOUNT_REFUSED.\n'])('whole %s retains D118 translation', (reason) => {
    expect(nowCell(run('failed', reason), null).sentence).toBe('The model account refused a call.');
    expect(endedWords('failed', reason)).toBe('Failed: the model account refused a call.');
  });
  it.each([null, '', ' \n '])('absent/empty %j stays absent', (reason) => {
    expect(nowCell(run('stopped', reason), null).sentence).toBeNull();
  });
  it('G7 single-line ordinary reasons retain their exact initial-cap-only output', () => {
    // A stop's own words leave the generic sentence out (teamGlanceStopWords.test.ts); these are stops without them.
    for (const sample of [stopped, failed]) {
      const body = { ...structuredClone(sample), outcome: { ...sample.outcome, owner_words: null } };
      expect(nowCell(toGlanceRun(body), null).sentence).toBe(cap(sample.phase.reason));
    }
  });
  it('activity keeps its first line and Show all whole reason, not Now capitalisation', () => {
    const supplied = 'the owner cancelled it.\nThe CSV is kept.\n';
    const event = toGlanceEvent({ kind: 'ended', seq: 99, decision: 'stopped', reason: supplied });
    expect(event).not.toBeNull();
    const row = activityRow(event!, run('stopped', supplied));
    expect(row.parts.map((p) => p.text).join('')).toBe('Stopped: the owner cancelled it.');
    const more = row.more;
    if (!more || !('whole' in more)) throw new Error('expected whole-text Show all');
    expect(more.whole.map((p) => p.text).join('')).toBe('Stopped: the owner cancelled it.\nThe CSV is kept.');
  });
  it('Interrupted keeps first-line, 80-character whole-word cut and generic-template suppression', () => {
    const supplied = 'the API timed out; ' + 'recorded work is kept '.repeat(9) + '\nSecond supplied line.';
    const body = { ...interrupted, phase: { ...interrupted.phase, reason: supplied } };
    expect(nowCell(toGlanceRun(body), null).reason).toBe(cutAt(cap(supplied.split('\n')[0].trim()), 80));
    body.phase.reason = 'the run ended (interrupted) without the team ending';
    expect(nowCell(toGlanceRun(body), null).reason).toBeUndefined();
  });
  it('D121 lowercase/multiline remains verbatim and its existing no-reason fallback stays exact', () => {
    const supplied = 'the team could not start.\nThe exact API explanation.\n';
    expect(nowCell(toGlanceRun({ ...didntStart, phase: { ...didntStart.phase, reason: supplied } }), null).sentence).toBe(supplied);
    expect(nowCell(toGlanceRun({ ...didntStart, phase: { ...didntStart.phase, reason: null, words: null }, outcome: { reason: supplied } }), null).sentence).toBe(supplied);
    expect(nowCell(toGlanceRun({ ...didntStart, phase: { ...didntStart.phase, reason: null, words: `Failed: ${supplied}` }, outcome: null }), null).sentence).toBe(supplied.trim());
    expect(nowCell(toGlanceRun({ ...didntStart, phase: { ...didntStart.phase, reason: null, words: null }, outcome: null }), null).sentence).toBe("The project couldn't start. Temper gave no reason.");
  });
});
