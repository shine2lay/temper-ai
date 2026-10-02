/**
 * The script logs the page is showing: one window per attempt (lib/scriptLog.ts), read page by
 * page from the API and kept up to date by the rows the run's socket sends.
 *
 * Only attempts someone is looking at are kept. A view watches its attempt while it is open and
 * lets go when it closes; the last one to let go frees the attempt, so memory goes with the
 * views open (the live panel and the full-screen view), not with how many scripts a run has.
 * Rows sent live for an attempt nobody watches are not kept at all: the log is read from the
 * server when it is opened.
 *
 * One request per attempt at a time. A request's answer is used only if the attempt is still
 * watched and has not been reset since (`gen`), so a slow answer can never overwrite a newer one.
 */
import { create } from 'zustand';
import { authFetch } from '@/lib/authFetch';
import {
  applyAfter,
  applyBefore,
  applyTail,
  emptyWindow,
  offerLive as offerLiveRow,
  parsePage,
  parseRow,
  WINDOW_MAX_CHARS,
  type LogWindow,
  type ScriptLogPage,
} from '@/lib/scriptLog';

/** Text asked for in one page. */
export const PAGE_BYTES = 256 * 1024;
/** Catching up is never asked for more often than this, whatever the window says. */
export const CATCH_UP_MIN_GAP_MS = 300;

/**
 * Following the end, but further behind it than a window holds (a script printing as fast as
 * it can): reading every row in between would only push them out again, so the newest page is
 * read instead. What lies between can still be read with "older".
 */
export function farBehind(win: LogWindow): boolean {
  if (win.hasMoreAfter || !win.latest || win.rows.length === 0) return false;
  const last = win.rows[win.rows.length - 1];
  return win.latest.seq > last.seq && win.latest.saved_bytes - last.saved_bytes > WINDOW_MAX_CHARS;
}

export type LogLoad = 'tail' | 'before' | 'after';

/**
 * Every window ever opened gets a number of its own, never reused: a log closed and opened again
 * while a read for it was still out must not take that read's answer for its own.
 */
let lastGen = 0;
const nextGen = () => ++lastGen;

export interface AttemptLog {
  runId: string;
  win: LogWindow;
  loading: LogLoad | null;
  error: string | null;
  /** False when asking again cannot help (the run has no such agent). */
  retryable: boolean;
  watchers: number;
  /** New whenever the window is replaced (`nextGen`): an answer to an older request is dropped. */
  gen: number;
  /** When a live row for it last came (ms), for knowing whether to ask the server. */
  lastLiveAt: number;
  /** When it was last read from the server (ms). */
  lastReadAt: number;
}

interface ScriptLogState {
  attempts: Record<string, AttemptLog>;
  watch: (runId: string, attemptId: string) => void;
  unwatch: (attemptId: string) => void;
  /** A row the run's socket sent. Ignored unless its attempt is watched. */
  offerLive: (executionId: string | undefined, raw: unknown) => void;
  /** The socket (re)connected: rows may have been missed, so every open log catches up. */
  markStale: () => void;
  loadTail: (attemptId: string) => Promise<void>;
  loadBefore: (attemptId: string) => Promise<void>;
  loadAfter: (attemptId: string) => Promise<void>;
  /** Back to the end: the newest page again, after reading back. */
  jumpToLatest: (attemptId: string) => Promise<void>;
  reset: () => void;
}

class LogReadError extends Error {
  readonly retryable: boolean;

  constructor(message: string, retryable: boolean) {
    super(message);
    this.retryable = retryable;
  }
}

async function fetchPage(
  runId: string,
  attemptId: string,
  cursor: { after_seq?: number; before_seq?: number },
): Promise<ScriptLogPage> {
  const params = new URLSearchParams({ max_bytes: String(PAGE_BYTES) });
  if (cursor.after_seq != null) params.set('after_seq', String(cursor.after_seq));
  if (cursor.before_seq != null) params.set('before_seq', String(cursor.before_seq));
  const url = `/api/runs/${encodeURIComponent(runId)}/agents/${encodeURIComponent(attemptId)}/log?${params}`;
  const res = await authFetch(url);
  if (res.status === 404) throw new LogReadError('This agent has no saved log on this run.', false);
  if (!res.ok) throw new LogReadError(`The log could not be read (HTTP ${res.status}).`, true);
  const page = parsePage(await res.json());
  if (!page) throw new LogReadError('The server sent something that is not a log page.', true);
  return page;
}

export const useScriptLogStore = create<ScriptLogState>()((set, get) => {
  /** Change one attempt, if it is still there. */
  const update = (attemptId: string, change: (a: AttemptLog) => AttemptLog) =>
    set((state) => {
      const current = state.attempts[attemptId];
      if (!current) return state;
      return { attempts: { ...state.attempts, [attemptId]: change(current) } };
    });

  /** Read one page and fold it in, unless the attempt went away or was reset meanwhile. */
  const load = async (
    attemptId: string,
    kind: LogLoad,
    cursor: { after_seq?: number; before_seq?: number },
    apply: (win: LogWindow, page: ScriptLogPage) => LogWindow,
  ) => {
    const attempt = get().attempts[attemptId];
    if (!attempt) return;
    const gen = attempt.gen;
    update(attemptId, (a) => ({ ...a, loading: kind }));
    try {
      const page = await fetchPage(attempt.runId, attemptId, cursor);
      update(attemptId, (a) => (a.gen !== gen
        ? a
        : {
            ...a,
            win: apply(a.win, page),
            loading: null,
            error: null,
            retryable: true,
            lastReadAt: Date.now(),
          }));
    } catch (err) {
      update(attemptId, (a) => (a.gen !== gen
        ? a
        : {
            ...a,
            loading: null,
            error: err instanceof Error ? err.message : String(err),
            retryable: !(err instanceof LogReadError) || err.retryable,
            lastReadAt: Date.now(),
          }));
    }
  };

  return {
    attempts: {},

    watch: (runId, attemptId) =>
      set((state) => {
        const current = state.attempts[attemptId];
        if (current && current.runId === runId) {
          return { attempts: { ...state.attempts, [attemptId]: { ...current, watchers: current.watchers + 1 } } };
        }
        const fresh: AttemptLog = {
          runId,
          win: emptyWindow(),
          loading: null,
          error: null,
          retryable: true,
          watchers: 1,
          gen: nextGen(),
          lastLiveAt: 0,
          lastReadAt: 0,
        };
        return { attempts: { ...state.attempts, [attemptId]: fresh } };
      }),

    unwatch: (attemptId) =>
      set((state) => {
        const current = state.attempts[attemptId];
        if (!current) return state;
        const attempts = { ...state.attempts };
        if (current.watchers <= 1) delete attempts[attemptId];
        else attempts[attemptId] = { ...current, watchers: current.watchers - 1 };
        return { attempts };
      }),

    offerLive: (executionId, raw) => {
      const row = parseRow(raw);
      if (!row) return;
      const attempt = get().attempts[row.attempt_id];
      if (!attempt) return;
      if (executionId && attempt.runId !== executionId) return;
      update(row.attempt_id, (a) => ({ ...a, win: offerLiveRow(a.win, row), lastLiveAt: Date.now() }));
    },

    markStale: () =>
      set((state) => {
        let changed = false;
        const attempts: Record<string, AttemptLog> = {};
        for (const [id, a] of Object.entries(state.attempts)) {
          if (a.win.loaded && !a.win.hasMoreAfter && !a.win.needsCatchUp) {
            attempts[id] = { ...a, win: { ...a.win, needsCatchUp: true } };
            changed = true;
          } else {
            attempts[id] = a;
          }
        }
        return changed ? { attempts } : state;
      }),

    loadTail: async (attemptId) => {
      const a = get().attempts[attemptId];
      if (!a || a.loading) return;
      await load(attemptId, 'tail', {}, applyTail);
    },

    loadBefore: async (attemptId) => {
      const a = get().attempts[attemptId];
      if (!a || a.loading || !a.win.loaded || a.win.rows.length === 0 || !a.win.hasMoreBefore) return;
      await load(attemptId, 'before', { before_seq: a.win.rows[0].seq }, applyBefore);
    },

    loadAfter: async (attemptId) => {
      const a = get().attempts[attemptId];
      if (!a || a.loading || !a.win.loaded) return;
      if (Date.now() - a.lastReadAt < CATCH_UP_MIN_GAP_MS) return;
      if (farBehind(a.win)) {
        await load(attemptId, 'tail', {}, applyTail);
        return;
      }
      await load(attemptId, 'after', { after_seq: a.win.endSeq }, applyAfter);
    },

    jumpToLatest: async (attemptId) => {
      const a = get().attempts[attemptId];
      if (!a) return;
      // A new generation: whatever is in flight for the old window is dropped when it lands.
      // The rows held stay on screen until the newest page replaces them; live rows that come
      // meanwhile wait, as they do before a first page, and follow on from it.
      update(attemptId, (x) => ({
        ...x,
        gen: nextGen(),
        loading: null,
        win: { ...x.win, loaded: false, hasMoreAfter: false, pending: [], needsCatchUp: false },
      }));
      await load(attemptId, 'tail', {}, applyTail);
    },

    reset: () => set({ attempts: {} }),
  };
});
