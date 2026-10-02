/**
 * A script agent's log on the page: what its script printed, as the rows the server saved.
 *
 * The server saves a script's output in rows (temper_ai/observability/script_logs.py), one per
 * batch, numbered 1, 2, 3 ... within the attempt with no gaps; each row is a list of entries
 * {stream, t, text}. The page gets rows two ways: pages read from the API (the newest rows, older
 * ones, the ones after a row) and rows sent over the run's socket as they are saved. Either can
 * arrive first, and either can repeat what the other brought, so everything here goes by row
 * number:
 *
 * - the window holds one unbroken run of rows, oldest first;
 * - a row it already has is ignored, whichever way it came;
 * - a live row that is not the next one (rows were missed: the socket dropped, the page opened
 *   half way through, the first page is still loading) waits in `pending`, and the window asks
 *   to catch up (`needsCatchUp`): the rows after the last one held are read, and the waiting rows
 *   follow on once they fit;
 * - a large row comes live without its text (`stub`): it is never held, only counted, and the
 *   window asks to catch up, which reads it. So does any row known to exist past the end
 *   (`latest`) while the window follows the end.
 *
 * What is held is bounded: about WINDOW_MAX_CHARS of text and WINDOW_MAX_ROWS rows. Rows added at
 * the end push the oldest out (they can be read again with "older"); reading older rows pushes
 * the newest out instead, and the window then says there is newer output (`hasMoreAfter`) and
 * stops taking live rows until it is brought back to the end.
 *
 * Nothing here renders anything, and nothing here trusts a row's shape: a malformed row is
 * dropped or emptied, never allowed to throw.
 */

/** Text held for one attempt, about (UTF-16 code units, plus a little per entry). */
export const WINDOW_MAX_CHARS = 1_000_000;
export const WINDOW_MAX_ROWS = 2_000;
/** Live rows waiting for a gap to be filled, at most; the oldest go first (they are read again). */
export const PENDING_MAX_ROWS = 64;
/** What the server saves of one attempt unless the agent says otherwise (`log_max_bytes`). */
export const DEFAULT_LOG_LIMIT = 10_000_000;

export interface ScriptLogEntry {
  /** "stdout", "stderr", or "temper" for a note from temper itself. */
  stream: string;
  /** When the first piece of the entry was read: ISO 8601, UTC. */
  t: string;
  text: string;
  /** Notes only: "truncated", "lost" or "end". */
  kind?: string;
  outcome?: string;
  exit_code?: number;
  lost_bytes?: number;
}

export interface ScriptLogEnd {
  /** "completed", "failed", "timed_out" or "cancelled". */
  outcome: string;
  exit_code?: number;
}

export interface ScriptLogRow {
  attempt_id: string;
  seq: number;
  entries: ScriptLogEntry[];
  /** UTF-8 bytes of output in this row. */
  bytes: number;
  /** UTF-8 bytes saved up to and including this row. */
  saved_bytes: number;
  dropped_bytes: number;
  lost_bytes: number;
  limit: number | null;
  truncated: boolean;
  end?: ScriptLogEnd;
  /** Sent live without its entries (it was large): only its figures count, its text is read. */
  stub?: boolean;
  /** What holding the row costs, for the window's bound. */
  weight: number;
}

export interface ScriptLogPage {
  rows: ScriptLogRow[];
  newest_seq: number;
  has_more_before: boolean;
  has_more_after: boolean;
}

/** The figures of the newest row seen, kept without its text. */
export interface ScriptLogTotals {
  seq: number;
  saved_bytes: number;
  dropped_bytes: number;
  lost_bytes: number;
  limit: number | null;
  truncated: boolean;
  end?: ScriptLogEnd;
}

export interface LogWindow {
  /** One unbroken run of rows, oldest first. */
  rows: ScriptLogRow[];
  weight: number;
  /** A first page has been read. */
  loaded: boolean;
  /** The number of the last row held, 0 when none is. */
  endSeq: number;
  /** Older rows exist that are not held. */
  hasMoreBefore: boolean;
  /** Newer rows exist that are not held, on purpose: the reader went back. Live rows wait. */
  hasMoreAfter: boolean;
  /** Live rows that came ahead of a gap. */
  pending: ScriptLogRow[];
  /** Rows after `endSeq` are missing and should be read. */
  needsCatchUp: boolean;
  latest: ScriptLogTotals | null;
}

export function emptyWindow(): LogWindow {
  return {
    rows: [],
    weight: 0,
    loaded: false,
    endSeq: 0,
    hasMoreBefore: false,
    hasMoreAfter: false,
    pending: [],
    needsCatchUp: false,
    latest: null,
  };
}

// ---------------------------------------------------------------- reading what the server sent

function num(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function parseEntry(raw: unknown): ScriptLogEntry | null {
  if (!raw || typeof raw !== 'object') return null;
  const e = raw as Record<string, unknown>;
  if (typeof e.text !== 'string') return null;
  const entry: ScriptLogEntry = {
    stream: typeof e.stream === 'string' ? e.stream : 'stdout',
    t: typeof e.t === 'string' ? e.t : '',
    text: e.text,
  };
  if (typeof e.kind === 'string') entry.kind = e.kind;
  if (typeof e.outcome === 'string') entry.outcome = e.outcome;
  if (typeof e.exit_code === 'number') entry.exit_code = e.exit_code;
  if (typeof e.lost_bytes === 'number') entry.lost_bytes = e.lost_bytes;
  return entry;
}

/** One row as sent by the server, or null when it is not one. Never throws. */
export function parseRow(raw: unknown): ScriptLogRow | null {
  if (!raw || typeof raw !== 'object') return null;
  const r = raw as Record<string, unknown>;
  const seq = r.seq;
  if (typeof seq !== 'number' || !Number.isInteger(seq) || seq < 1) return null;
  if (typeof r.attempt_id !== 'string' || !r.attempt_id) return null;
  const entries: ScriptLogEntry[] = [];
  if (Array.isArray(r.entries)) {
    for (const item of r.entries) {
      const entry = parseEntry(item);
      if (entry) entries.push(entry);
    }
  }
  let weight = 64;
  for (const entry of entries) weight += entry.text.length + 32;
  const row: ScriptLogRow = {
    attempt_id: r.attempt_id,
    seq,
    entries,
    bytes: num(r.bytes),
    saved_bytes: num(r.saved_bytes),
    dropped_bytes: num(r.dropped_bytes),
    lost_bytes: num(r.lost_bytes),
    limit: typeof r.limit === 'number' ? r.limit : null,
    truncated: r.truncated === true,
    weight,
  };
  const end = r.end as Record<string, unknown> | undefined;
  if (end && typeof end === 'object' && typeof end.outcome === 'string') {
    row.end = { outcome: end.outcome };
    if (typeof end.exit_code === 'number') row.end.exit_code = end.exit_code;
  }
  if (r.stub === true) row.stub = true;
  return row;
}

/** A page from GET /api/runs/<run>/agents/<attempt>/log, or null when it is not one. */
export function parsePage(raw: unknown): ScriptLogPage | null {
  if (!raw || typeof raw !== 'object') return null;
  const p = raw as Record<string, unknown>;
  if (!Array.isArray(p.rows)) return null;
  const rows: ScriptLogRow[] = [];
  for (const item of p.rows) {
    const row = parseRow(item);
    // A page is read from the database, where rows are whole: a "stub" there is not one.
    if (row) {
      delete row.stub;
      rows.push(row);
    }
  }
  rows.sort((a, b) => a.seq - b.seq);
  return {
    rows,
    newest_seq: num(p.newest_seq),
    has_more_before: p.has_more_before === true,
    has_more_after: p.has_more_after === true,
  };
}

// ---------------------------------------------------------------- the window

function totalsOf(row: ScriptLogRow): ScriptLogTotals {
  const totals: ScriptLogTotals = {
    seq: row.seq,
    saved_bytes: row.saved_bytes,
    dropped_bytes: row.dropped_bytes,
    lost_bytes: row.lost_bytes,
    limit: row.limit,
    truncated: row.truncated,
  };
  if (row.end) totals.end = row.end;
  return totals;
}

function newer(current: ScriptLogTotals | null, row: ScriptLogRow | undefined): ScriptLogTotals | null {
  if (!row) return current;
  if (current && current.seq >= row.seq) return current;
  return totalsOf(row);
}

function weigh(rows: ScriptLogRow[]): number {
  let total = 0;
  for (const row of rows) total += row.weight;
  return total;
}

function addPending(pending: ScriptLogRow[], row: ScriptLogRow): ScriptLogRow[] {
  if (pending.some((p) => p.seq === row.seq)) return pending;
  const next = [...pending, row].sort((a, b) => a.seq - b.seq);
  return next.length > PENDING_MAX_ROWS ? next.slice(next.length - PENDING_MAX_ROWS) : next;
}

/** Take the waiting rows that now follow on from the end; drop the ones already held. */
function drainPending(win: LogWindow): LogWindow {
  if (win.pending.length === 0) return win;
  let rows = win.rows;
  let endSeq = win.endSeq;
  let weight = win.weight;
  const left: ScriptLogRow[] = [];
  for (const row of win.pending) {
    if (row.seq <= endSeq) continue;
    if (row.seq === endSeq + 1 && left.length === 0) {
      if (rows === win.rows) rows = [...rows];
      rows.push(row);
      weight += row.weight;
      endSeq = row.seq;
    } else {
      left.push(row);
    }
  }
  return { ...win, rows, weight, endSeq, pending: left, needsCatchUp: win.needsCatchUp || left.length > 0 };
}

/** Following the end, and a row past it is known to exist: it should be read. */
function behind(win: LogWindow): boolean {
  return !win.hasMoreAfter && win.latest !== null && win.latest.seq > win.endSeq;
}

function overBound(rows: ScriptLogRow[], weight: number): boolean {
  return weight > WINDOW_MAX_CHARS || rows.length > WINDOW_MAX_ROWS;
}

/** New rows went on the end: let the oldest go, keeping at least one row. */
function trimFront(win: LogWindow): LogWindow {
  if (!overBound(win.rows, win.weight) || win.rows.length <= 1) return win;
  let start = 0;
  let weight = win.weight;
  while (start < win.rows.length - 1 && overBound(win.rows.slice(start), weight)) {
    weight -= win.rows[start].weight;
    start += 1;
  }
  return { ...win, rows: win.rows.slice(start), weight, hasMoreBefore: true };
}

/** Older rows went on the front: let the newest go, keeping the `keep` oldest at least. */
function trimBack(win: LogWindow, keep: number): LogWindow {
  if (!overBound(win.rows, win.weight)) return win;
  let end = win.rows.length;
  let weight = win.weight;
  while (end > Math.max(1, keep) && overBound(win.rows.slice(0, end), weight)) {
    end -= 1;
    weight -= win.rows[end].weight;
  }
  if (end === win.rows.length) return win;
  const rows = win.rows.slice(0, end);
  return {
    ...win,
    rows,
    weight,
    endSeq: rows[rows.length - 1].seq,
    hasMoreAfter: true,
    pending: [],
    needsCatchUp: false,
  };
}

/** The longest unbroken run in sorted rows that ends at the last of them. */
function unbrokenTail(rows: ScriptLogRow[]): ScriptLogRow[] {
  let start = rows.length - 1;
  while (start > 0 && rows[start - 1].seq === rows[start].seq - 1) start -= 1;
  return start <= 0 ? rows : rows.slice(start);
}

/**
 * The newest page, read when a log is opened or brought back to its end. It replaces what is
 * held; held or waiting rows newer than the page (live rows that came while it was read) are
 * kept and follow on.
 */
export function applyTail(win: LogWindow, page: ScriptLogPage): LogWindow {
  const rows = unbrokenTail(dedupe(page.rows));
  const endSeq = rows.length > 0 ? rows[rows.length - 1].seq : 0;
  const carry = [...win.rows, ...win.pending].filter((r) => r.seq > endSeq);
  let next: LogWindow = {
    ...win,
    rows,
    weight: weigh(rows),
    loaded: true,
    endSeq,
    hasMoreBefore: rows.length > 0 ? rows[0].seq > 1 : false,
    hasMoreAfter: false,
    pending: [],
    needsCatchUp: page.has_more_after,
    latest: newer(win.latest, rows[rows.length - 1]),
  };
  for (const row of carry) next = { ...next, pending: addPending(next.pending, row) };
  next = drainPending(next);
  if (behind(next)) next = { ...next, needsCatchUp: true };
  return trimFront(next);
}

/**
 * Rows after the last one held: catching up, or paging forward after going back. Rows that do
 * not follow on are ignored. A page that brings nothing new ends the catching up: rows still
 * waiting are dropped (the next live row or poll asks again), unless the page was read before
 * they were saved, in which case it is read again.
 */
export function applyAfter(win: LogWindow, page: ScriptLogPage): LogWindow {
  if (!win.loaded) return win;
  let rows = win.rows;
  let endSeq = win.endSeq;
  let weight = win.weight;
  let latest = win.latest;
  for (const row of dedupe(page.rows)) {
    if (row.seq <= endSeq) continue;
    if (row.seq !== endSeq + 1) break;
    if (rows === win.rows) rows = [...rows];
    rows.push(row);
    weight += row.weight;
    endSeq = row.seq;
    latest = newer(latest, row);
  }
  const grew = endSeq !== win.endSeq;
  let next: LogWindow = { ...win, rows, weight, endSeq, latest };
  if (win.hasMoreAfter) {
    // Paging forward: back at the end once the server has nothing after this page.
    next.hasMoreAfter = grew ? page.has_more_after : win.hasMoreAfter && page.has_more_after;
    next.needsCatchUp = false;
    next.pending = [];
  } else {
    next.needsCatchUp = grew && page.has_more_after;
    next = drainPending(next);
    if (!grew) {
      // Nothing new: done, unless rows known to exist were saved after the page was read.
      const raced = (next.pending.length > 0 && page.newest_seq < next.pending[0].seq)
        || (behind(next) && page.newest_seq < (next.latest?.seq ?? 0));
      next = { ...next, pending: raced ? next.pending : [], needsCatchUp: raced };
    } else if (behind(next)) {
      next = { ...next, needsCatchUp: true };
    }
  }
  return trimFront(next);
}

/** Rows before the first one held, for reading back. The newest held rows make room. */
export function applyBefore(win: LogWindow, page: ScriptLogPage): LogWindow {
  if (!win.loaded || win.rows.length === 0) return win;
  const firstSeq = win.rows[0].seq;
  const older: ScriptLogRow[] = [];
  const sorted = dedupe(page.rows);
  let expect = firstSeq - 1;
  for (let i = sorted.length - 1; i >= 0; i -= 1) {
    const row = sorted[i];
    if (row.seq >= firstSeq) continue;
    if (row.seq !== expect) break;
    older.unshift(row);
    expect -= 1;
  }
  if (older.length === 0) return { ...win, hasMoreBefore: firstSeq > 1 && page.has_more_before };
  const rows = [...older, ...win.rows];
  const next: LogWindow = {
    ...win,
    rows,
    weight: win.weight + weigh(older),
    hasMoreBefore: rows[0].seq > 1,
  };
  return trimBack(next, older.length);
}

/** A row sent live, as it was saved. */
export function offerLive(win: LogWindow, row: ScriptLogRow): LogWindow {
  const latest = newer(win.latest, row);
  if (row.stub) {
    // Only its figures came: count it, and read it when following the end.
    const next = latest === win.latest ? win : { ...win, latest };
    return win.loaded && behind(next) && !next.needsCatchUp ? { ...next, needsCatchUp: true } : next;
  }
  if (!win.loaded) {
    return { ...win, latest, pending: addPending(win.pending, row) };
  }
  if (win.hasMoreAfter) return latest === win.latest ? win : { ...win, latest };
  if (row.seq <= win.endSeq) return latest === win.latest ? win : { ...win, latest };
  if (row.seq === win.endSeq + 1) {
    const next: LogWindow = {
      ...win,
      latest,
      rows: [...win.rows, row],
      weight: win.weight + row.weight,
      endSeq: row.seq,
    };
    return trimFront(drainPending(next));
  }
  return { ...win, latest, pending: addPending(win.pending, row), needsCatchUp: true };
}

function dedupe(rows: ScriptLogRow[]): ScriptLogRow[] {
  const sorted = [...rows].sort((a, b) => a.seq - b.seq);
  return sorted.filter((row, i) => i === 0 || sorted[i - 1].seq !== row.seq);
}

// ---------------------------------------------------------------- lines to show

export interface LogLine {
  /** Stable while the line grows: the row, entry and piece it started in. */
  key: string;
  t: string;
  stream: string;
  text: string;
  /** Notes only. */
  kind?: string;
  outcome?: string;
  exitCode?: number;
}

/**
 * The held rows as lines: each entry split at its line breaks, and a line a stream left
 * unfinished carried on by that stream's next entry, even when the other stream printed in
 * between (the line stays where it started). A note is a line of its own, and nothing carries
 * on across one. A line's time is when its first piece was read.
 */
export function buildLines(rows: readonly ScriptLogRow[]): LogLine[] {
  const lines: LogLine[] = [];
  // Per stream, the line it left unfinished.
  const open = new Map<string, number>();
  for (const row of rows) {
    row.entries.forEach((entry, ei) => {
      if (entry.stream === 'temper') {
        lines.push({
          key: `${row.seq}:${ei}`,
          t: entry.t,
          stream: 'temper',
          text: entry.text,
          kind: entry.kind,
          outcome: entry.outcome,
          exitCode: entry.exit_code,
        });
        open.clear();
        return;
      }
      if (!entry.text) return;
      const parts = entry.text.split('\n');
      parts.forEach((part, pi) => {
        if (pi === parts.length - 1 && part === '') return;
        const carry = pi === 0 ? open.get(entry.stream) : undefined;
        if (carry !== undefined) {
          const prev = lines[carry];
          lines[carry] = { ...prev, text: prev.text + part };
        } else {
          lines.push({ key: `${row.seq}:${ei}:${pi}`, t: entry.t, stream: entry.stream, text: part });
        }
      });
      if (parts[parts.length - 1] === '') {
        open.delete(entry.stream);
      } else if (parts.length > 1 || !open.has(entry.stream)) {
        open.set(entry.stream, lines.length - 1);
      }
    });
  }
  return lines;
}

// ---------------------------------------------------------------- small helpers for the view

/** The script part of an agent's config, if it is a script agent; `null` if it is not. */
export function scriptConfigOf(agent: unknown): Record<string, unknown> | null {
  if (!agent || typeof agent !== 'object') return null;
  const a = agent as Record<string, unknown>;
  for (const holder of [a.agent_config_snapshot, a.agent_config]) {
    if (!holder || typeof holder !== 'object') continue;
    const outer = (holder as Record<string, unknown>).agent;
    if (!outer || typeof outer !== 'object') continue;
    const o = outer as Record<string, unknown>;
    // A script agent's config arrives double-nested in a snapshot: agent.agent.type.
    const inner = o.agent && typeof o.agent === 'object' ? (o.agent as Record<string, unknown>) : null;
    if (inner?.type === 'script') return inner;
    if (o.type === 'script') return o;
  }
  return a.type === 'script' || a.agent_type === 'script' ? {} : null;
}

/** "14:03:07.215", local time; the stored time unchanged when it cannot be read. */
export function formatLogTime(t: string): string {
  const d = new Date(t);
  if (!t || Number.isNaN(d.getTime())) return t;
  const two = (n: number) => String(n).padStart(2, '0');
  return `${two(d.getHours())}:${two(d.getMinutes())}:${two(d.getSeconds())}.${String(d.getMilliseconds()).padStart(3, '0')}`;
}

/** "12.3 KB", "10 MB": decimal units, as the limit is set in bytes. */
export function formatBytes(n: number): string {
  if (n < 1000) return `${n} B`;
  const units = ['KB', 'MB', 'GB'];
  let value = n / 1000;
  let unit = 0;
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1000;
    unit += 1;
  }
  const shown = value >= 100 || Number.isInteger(value) ? Math.round(value) : Number(value.toFixed(1));
  return `${shown} ${units[unit]}`;
}

/** How an attempt ended, in words, from its end note. */
export function outcomeWords(end: ScriptLogEnd | undefined): string | null {
  if (!end) return null;
  switch (end.outcome) {
    case 'completed':
      return 'Finished · exit code 0';
    case 'timed_out':
      return 'Timed out';
    case 'cancelled':
      return 'Cancelled';
    case 'failed':
      return end.exit_code != null ? `Failed · exit code ${end.exit_code}` : 'Failed';
    default:
      return end.outcome;
  }
}
