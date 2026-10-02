/**
 * A script agent's log window (lib/scriptLog.ts): rows from pages and from the socket, in either
 * order, each kept once and in order, within a bounded window.
 */
import { describe, it, expect } from 'vitest';
import {
  WINDOW_MAX_CHARS,
  WINDOW_MAX_ROWS,
  PENDING_MAX_ROWS,
  applyAfter,
  applyBefore,
  applyTail,
  buildLines,
  emptyWindow,
  formatBytes,
  formatLogTime,
  offerLive,
  outcomeWords,
  parsePage,
  parseRow,
  scriptConfigOf,
  type LogWindow,
  type ScriptLogPage,
  type ScriptLogRow,
} from '@/lib/scriptLog';

const A = 'attempt-1';
const T = '2026-10-02T12:00:00.000+00:00';

type Entry = { stream?: string; text: string; kind?: string; outcome?: string; exit_code?: number };

function raw(seq: number, entries: Entry[] | string = `line ${seq}\n`, extra: Record<string, unknown> = {}) {
  const list = typeof entries === 'string' ? [{ text: entries }] : entries;
  return {
    attempt_id: A,
    seq,
    entries: list.map((e) => ({ stream: 'stdout', t: T, ...e })),
    bytes: list.reduce((n, e) => n + e.text.length, 0),
    saved_bytes: seq * 10,
    dropped_bytes: 0,
    lost_bytes: 0,
    limit: 10_000_000,
    truncated: false,
    ...extra,
  };
}

function row(seq: number, entries?: Entry[] | string, extra?: Record<string, unknown>): ScriptLogRow {
  const parsed = parseRow(raw(seq, entries, extra));
  if (!parsed) throw new Error('test row did not parse');
  return parsed;
}

function page(seqs: number[], over: Partial<ScriptLogPage> = {}): ScriptLogPage {
  const rows = seqs.map((s) => row(s));
  return {
    rows,
    newest_seq: seqs.length ? Math.max(...seqs) : 0,
    has_more_before: seqs.length > 0 && Math.min(...seqs) > 1,
    has_more_after: false,
    ...over,
  };
}

const seqs = (win: LogWindow) => win.rows.map((r) => r.seq);
const range = (from: number, to: number) => Array.from({ length: to - from + 1 }, (_, i) => from + i);

describe('reading rows', () => {
  it('drops anything that is not a row, without throwing', () => {
    for (const bad of [null, undefined, 'row', 7, [], {}, { seq: '1', attempt_id: A }, { seq: 0, attempt_id: A },
      { seq: 1.5, attempt_id: A }, { seq: 1 }, { seq: 1, attempt_id: '' }, { seq: Infinity, attempt_id: A }]) {
      expect(parseRow(bad)).toBeNull();
    }
  });

  it('keeps a row whose entries are partly malformed, with only the good ones', () => {
    const r = parseRow({ attempt_id: A, seq: 2, entries: [null, 5, { text: 3 }, { text: 'ok\n', stream: 7 }] });
    expect(r?.entries).toEqual([{ stream: 'stdout', t: '', text: 'ok\n' }]);
    expect(parseRow({ attempt_id: A, seq: 3, entries: 'nope' })?.entries).toEqual([]);
    expect(parseRow({ attempt_id: A, seq: 4, entries: { 0: 'x' } })?.entries).toEqual([]);
  });

  it('reads figures defensively', () => {
    const r = parseRow({ attempt_id: A, seq: 1, bytes: 'x', saved_bytes: NaN, limit: '10', truncated: 'yes' })!;
    expect([r.bytes, r.saved_bytes, r.limit, r.truncated]).toEqual([0, 0, null, false]);
  });

  it('reads the end and the stub mark', () => {
    expect(row(1, 'x', { end: { outcome: 'failed', exit_code: 3 } }).end).toEqual({ outcome: 'failed', exit_code: 3 });
    expect(row(1, 'x', { end: 'failed' }).end).toBeUndefined();
    expect(row(1, 'x', { stub: true }).stub).toBe(true);
  });

  it('a page is sorted, and its rows are never stubs', () => {
    const p = parsePage({ rows: [raw(3, 'c', { stub: true }), raw(1), 'junk', raw(2)], newest_seq: 3 })!;
    expect(p.rows.map((r) => r.seq)).toEqual([1, 2, 3]);
    expect(p.rows.some((r) => r.stub)).toBe(false);
    expect(parsePage({ rows: 'nope' })).toBeNull();
    expect(parsePage(null)).toBeNull();
  });
});

describe('history and live rows, in either order', () => {
  it('history first, then live rows: repeats are ignored and the next row is added', () => {
    let win = applyTail(emptyWindow(), page([1, 2, 3]));
    win = offerLive(win, row(3));
    win = offerLive(win, row(2));
    win = offerLive(win, row(4));
    expect(seqs(win)).toEqual([1, 2, 3, 4]);
    expect(win.needsCatchUp).toBe(false);
  });

  it('live rows first: they wait for the first page and follow on from it', () => {
    let win = offerLive(emptyWindow(), row(4));
    win = offerLive(win, row(5));
    expect(win.rows).toEqual([]);
    win = applyTail(win, page([1, 2, 3, 4]));
    expect(seqs(win)).toEqual([1, 2, 3, 4, 5]);
    expect(win.pending).toEqual([]);
    expect(win.needsCatchUp).toBe(false);
  });

  it('a live row saved while the page was read, past a gap, waits and asks to catch up', () => {
    let win = offerLive(emptyWindow(), row(6));
    win = applyTail(win, page([1, 2, 3]));
    expect(seqs(win)).toEqual([1, 2, 3]);
    expect(win.pending.map((r) => r.seq)).toEqual([6]);
    expect(win.needsCatchUp).toBe(true);
    win = applyAfter(win, page([4, 5, 6]));
    expect(seqs(win)).toEqual(range(1, 6));
    expect(win.pending).toEqual([]);
    expect(win.needsCatchUp).toBe(false);
  });

  it('a gap in live rows (a dropped socket) is filled by reading after the last row held', () => {
    let win = applyTail(emptyWindow(), page([1, 2]));
    win = offerLive(win, row(5));
    win = offerLive(win, row(6));
    expect(seqs(win)).toEqual([1, 2]);
    expect(win.needsCatchUp).toBe(true);
    win = applyAfter(win, page([3, 4, 5]));
    expect(seqs(win)).toEqual(range(1, 6));
    expect(win.needsCatchUp).toBe(false);
  });

  it('a catch-up page that overlaps what is held adds each row once', () => {
    let win = applyTail(emptyWindow(), page([1, 2, 3]));
    win = offerLive(win, row(4));
    win = applyAfter(win, page([3, 4, 5, 5, 6]));
    expect(seqs(win)).toEqual(range(1, 6));
    const texts = buildLines(win.rows).map((l) => l.text);
    expect(new Set(texts).size).toBe(texts.length);
  });

  it('a page that ended before the log did asks for more', () => {
    let win = applyTail(emptyWindow(), page([1]));
    win = offerLive(win, row(9));
    win = applyAfter(win, page([2, 3, 4], { newest_seq: 9, has_more_after: true }));
    expect(seqs(win)).toEqual([1, 2, 3, 4]);
    expect(win.needsCatchUp).toBe(true);
    win = applyAfter(win, page([5, 6, 7, 8, 9]));
    expect(seqs(win)).toEqual(range(1, 9));
    expect(win.needsCatchUp).toBe(false);
  });

  it('reconnecting with nothing missed reads nothing new and settles', () => {
    let win = applyTail(emptyWindow(), page([1, 2, 3]));
    win = { ...win, needsCatchUp: true }; // what the store does when the socket reconnects
    win = applyAfter(win, page([], { newest_seq: 3 }));
    expect(seqs(win)).toEqual([1, 2, 3]);
    expect(win.needsCatchUp).toBe(false);
  });

  it('a catch-up read before the waiting row was saved asks again; one read after drops the wait', () => {
    let win = applyTail(emptyWindow(), page([1, 2, 3]));
    win = offerLive(win, row(7));
    const early = applyAfter(win, page([], { newest_seq: 3 }));
    expect(early.needsCatchUp).toBe(true);
    expect(early.pending.map((r) => r.seq)).toEqual([7]);
    const late = applyAfter(win, page([], { newest_seq: 7 }));
    expect(late.needsCatchUp).toBe(false);
    expect(late.pending).toEqual([]);
  });

  it('a large row comes live without its text: it is counted, then read', () => {
    let win = applyTail(emptyWindow(), page([1, 2]));
    win = offerLive(win, row(3, [{ text: '' }], { stub: true, saved_bytes: 99_999 }));
    expect(seqs(win)).toEqual([1, 2]);
    expect(win.latest?.seq).toBe(3);
    expect(win.latest?.saved_bytes).toBe(99_999);
    expect(win.needsCatchUp).toBe(true);
    win = applyAfter(win, page([3]));
    expect(seqs(win)).toEqual([1, 2, 3]);
    expect(win.needsCatchUp).toBe(false);
  });

  it('a stub before the first page makes the first page catch up to it', () => {
    let win = offerLive(emptyWindow(), row(5, [{ text: '' }], { stub: true }));
    win = applyTail(win, page([1, 2, 3]));
    expect(win.needsCatchUp).toBe(true);
  });

  it('waiting rows are bounded', () => {
    let win = applyTail(emptyWindow(), page([1]));
    for (let s = 10; s < 10 + PENDING_MAX_ROWS * 2; s += 1) win = offerLive(win, row(s));
    expect(win.pending.length).toBe(PENDING_MAX_ROWS);
    expect(win.pending[win.pending.length - 1].seq).toBe(10 + PENDING_MAX_ROWS * 2 - 1);
  });

  it('an empty log reads as empty, and its first live row is taken', () => {
    let win = applyTail(emptyWindow(), page([]));
    expect(win.loaded).toBe(true);
    expect(win.rows).toEqual([]);
    win = offerLive(win, row(1));
    expect(seqs(win)).toEqual([1]);
  });

  it('the end note row sets how it ended', () => {
    let win = applyTail(emptyWindow(), page([1]));
    win = offerLive(win, row(2, [{ stream: 'temper', text: '[failed: exit code 3]', kind: 'end', outcome: 'failed', exit_code: 3 }],
      { end: { outcome: 'failed', exit_code: 3 } }));
    expect(win.latest?.end).toEqual({ outcome: 'failed', exit_code: 3 });
  });
});

describe('the window stays bounded', () => {
  it('rows on the end push the oldest out', () => {
    const big = 'x'.repeat(200_000);
    let win = applyTail(emptyWindow(), { rows: [row(1, big)], newest_seq: 1, has_more_before: false, has_more_after: false });
    for (let s = 2; s <= 20; s += 1) win = offerLive(win, row(s, big));
    expect(win.weight).toBeLessThanOrEqual(WINDOW_MAX_CHARS);
    expect(win.rows[win.rows.length - 1].seq).toBe(20);
    expect(win.hasMoreBefore).toBe(true);
    expect(seqs(win)).toEqual(range(win.rows[0].seq, 20));
  });

  it('many small rows are capped by count', () => {
    let win = applyTail(emptyWindow(), page([1]));
    for (let s = 2; s <= WINDOW_MAX_ROWS + 500; s += 1) win = offerLive(win, row(s, 'y\n'));
    expect(win.rows.length).toBeLessThanOrEqual(WINDOW_MAX_ROWS);
    expect(win.endSeq).toBe(WINDOW_MAX_ROWS + 500);
  });

  it('a single row larger than the window is still held', () => {
    const huge = 'z'.repeat(WINDOW_MAX_CHARS + 10);
    let win = applyTail(emptyWindow(), page([1]));
    win = offerLive(win, row(2, huge));
    expect(seqs(win)).toEqual([2]);
  });
});

describe('reading back', () => {
  function tailAt(from: number, to: number, text = 'line\n'): LogWindow {
    const rows = range(from, to).map((s) => row(s, text));
    return applyTail(emptyWindow(), { rows, newest_seq: to, has_more_before: from > 1, has_more_after: false });
  }

  it('older rows go on the front', () => {
    let win = tailAt(50, 60);
    expect(win.hasMoreBefore).toBe(true);
    win = applyBefore(win, page(range(40, 49), { has_more_before: true }));
    expect(seqs(win)).toEqual(range(40, 60));
    expect(win.hasMoreBefore).toBe(true);
    expect(win.hasMoreAfter).toBe(false);
  });

  it('older rows that do not join up are not taken', () => {
    const win = applyBefore(tailAt(50, 60), page([30, 31, 32]));
    expect(seqs(win)).toEqual(range(50, 60));
  });

  it('reading far back lets the newest go; live rows then wait until it is back at the end', () => {
    // Rows as large as the server makes them (64 KiB at most): 16 of them nearly fill the window.
    const big = 'q'.repeat(60_000);
    let win = tailAt(10, 25, big);
    expect(win.hasMoreAfter).toBe(false);
    const older = range(4, 9).map((s) => row(s, big));
    win = applyBefore(win, { rows: older, newest_seq: 25, has_more_before: true, has_more_after: false });
    expect(win.rows[0].seq).toBe(4);
    expect(win.endSeq).toBeLessThan(25);
    expect(win.hasMoreAfter).toBe(true);
    expect(win.weight).toBeLessThanOrEqual(WINDOW_MAX_CHARS);
    expect(seqs(win)).toEqual(range(4, win.endSeq));
    const before = seqs(win);
    win = offerLive(win, row(26));
    expect(seqs(win)).toEqual(before);
    expect(win.latest?.seq).toBe(26);
    // Paging forward again joins up, and says when it is back at the end.
    win = applyAfter(win, page(range(win.endSeq + 1, 26), { has_more_after: false }));
    expect(win.endSeq).toBe(26);
    expect(win.hasMoreAfter).toBe(false);
  });

  it('back at the end with no older rows, there are none to read', () => {
    const win = applyBefore(tailAt(1, 3), page([]));
    expect(win.hasMoreBefore).toBe(false);
  });
});

describe('lines', () => {
  const out = (text: string): Entry => ({ stream: 'stdout', text });
  const err = (text: string): Entry => ({ stream: 'stderr', text });

  it('a line printed in two pieces is one line, timed by its first piece, keyed by where it began', () => {
    const lines = buildLines([row(1, [out('half a line, ')]), row(2, [out('then the rest\nnext\n')])]);
    expect(lines.map((l) => l.text)).toEqual(['half a line, then the rest', 'next']);
    expect(lines[0].key).toBe('1:0:0');
  });

  it('a stream carries its own unfinished line when the other stream printed in between', () => {
    const lines = buildLines([row(1, [out('a'), err('warn\n'), out('b\n')])]);
    expect(lines.map((l) => [l.stream, l.text])).toEqual([['stdout', 'ab'], ['stderr', 'warn']]);
  });

  it('a note stands alone and nothing carries over it', () => {
    const lines = buildLines([row(1, [out('cut'), { stream: 'temper', text: '[limit]', kind: 'truncated' }, out('more\n')])]);
    expect(lines.map((l) => [l.stream, l.text, l.kind])).toEqual([
      ['stdout', 'cut', undefined], ['temper', '[limit]', 'truncated'], ['stdout', 'more', undefined]]);
  });

  it('empty lines are kept, empty entries are not', () => {
    const lines = buildLines([row(1, [out(''), out('\n\nx\n')])]);
    expect(lines.map((l) => l.text)).toEqual(['', '', 'x']);
  });

  it('keys are unique', () => {
    const lines = buildLines(range(1, 50).map((s) => row(s, [out('a\nb'), err('c\n'), out('d\n')])));
    expect(new Set(lines.map((l) => l.key)).size).toBe(lines.length);
  });
});

describe('small helpers', () => {
  it('finds a script agent however its config arrives', () => {
    expect(scriptConfigOf({ agent_config_snapshot: { agent: { agent: { type: 'script', log_max_bytes: 5 } } } }))
      .toEqual({ type: 'script', log_max_bytes: 5 });
    expect(scriptConfigOf({ agent_config_snapshot: { agent: { type: 'script' } } })).toEqual({ type: 'script' });
    expect(scriptConfigOf({ agent_config: { agent: { type: 'script' } } })).toEqual({ type: 'script' });
    expect(scriptConfigOf({ agent_type: 'script' })).toEqual({});
    expect(scriptConfigOf({ agent_config_snapshot: { agent: { type: 'llm', model: 'm' } } })).toBeNull();
    for (const bad of [null, undefined, 'script', 3, { agent_config_snapshot: 'x' }, { agent_config: { agent: 1 } }]) {
      expect(scriptConfigOf(bad)).toBeNull();
    }
  });

  it('sizes in decimal units, like the limit', () => {
    expect([999, 1000, 1500, 123_456, 10_000_000, 2_000_264].map(formatBytes))
      .toEqual(['999 B', '1 KB', '1.5 KB', '123 KB', '10 MB', '2 MB']);
  });

  it('times to the millisecond, and leaves what it cannot read alone', () => {
    expect(formatLogTime(T)).toMatch(/^\d\d:\d\d:\d\d\.000$/);
    expect(formatLogTime('not a time')).toBe('not a time');
    expect(formatLogTime('')).toBe('');
  });

  it('says how an attempt ended', () => {
    expect(outcomeWords({ outcome: 'completed', exit_code: 0 })).toBe('Finished · exit code 0');
    expect(outcomeWords({ outcome: 'failed', exit_code: 3 })).toBe('Failed · exit code 3');
    expect(outcomeWords({ outcome: 'failed' })).toBe('Failed');
    expect(outcomeWords({ outcome: 'timed_out' })).toBe('Timed out');
    expect(outcomeWords({ outcome: 'cancelled' })).toBe('Cancelled');
    expect(outcomeWords(undefined)).toBeNull();
  });
});
