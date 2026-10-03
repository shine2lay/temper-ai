/**
 * Keep one script attempt's log on the page while a view shows it.
 *
 * Watching the attempt (store/scriptLogStore.ts) is what makes the run's socket rows for it
 * count. On top of that this reads from the server whenever the rows that came may not be all:
 *
 * - the newest page when the view opens (live rows that arrive meanwhile wait and follow on);
 * - the rows after the last one held when a gap shows (a live row that is not the next one),
 *   after the socket reconnects, or when a page ended before the log did;
 * - every few seconds while the script runs and nothing came over the socket, which covers a
 *   socket that cannot carry the rows at all;
 * - once more when the script has ended and its end note is not here yet.
 */
import { useEffect, useRef } from 'react';
import { CATCH_UP_MIN_GAP_MS, useScriptLogStore, type AttemptLog } from '@/store/scriptLogStore';

/** While the script runs and no row has come for this long, ask the server. */
export const POLL_IDLE_MS = 3000;

function afterGap(attemptId: string): number {
  const a = useScriptLogStore.getState().attempts[attemptId];
  return a ? Math.max(0, CATCH_UP_MIN_GAP_MS - (Date.now() - a.lastReadAt)) : 0;
}

/**
 * Call `read` once the store would take it: CATCH_UP_MIN_GAP_MS after the last read, by
 * Date.now(). setTimeout runs on another clock, so a timer can fire a moment before Date.now()
 * says its delay is over, and the store turns a read asked for too soon down without a word.
 * So look again when the timer fires and wait out what is left, rather than lose the read.
 * Returns the cancel.
 */
function afterReadGap(attemptId: string, read: () => void): () => void {
  let timer: ReturnType<typeof setTimeout>;
  const tryRead = () => {
    const wait = afterGap(attemptId);
    if (wait > 0) timer = setTimeout(tryRead, wait);
    else read();
  };
  timer = setTimeout(tryRead, afterGap(attemptId));
  return () => clearTimeout(timer);
}

export function useScriptLog(
  runId: string | undefined,
  attemptId: string | undefined,
  running: boolean,
): AttemptLog | undefined {
  const attempt = useScriptLogStore((s) => (attemptId ? s.attempts[attemptId] : undefined));
  const watch = useScriptLogStore((s) => s.watch);
  const unwatch = useScriptLogStore((s) => s.unwatch);

  useEffect(() => {
    if (!runId || !attemptId) return;
    watch(runId, attemptId);
    return () => unwatch(attemptId);
  }, [runId, attemptId, watch, unwatch]);

  const present = attempt !== undefined;
  const loaded = attempt?.win.loaded ?? false;
  const loading = attempt?.loading ?? null;
  const error = attempt?.error ?? null;
  const needsCatchUp = attempt?.win.needsCatchUp ?? false;
  const anchored = attempt?.win.hasMoreAfter ?? false;
  const ended = attempt?.win.latest?.end != null;

  // The newest page, when the view opens.
  useEffect(() => {
    if (!attemptId || !present || loaded || loading || error) return;
    void useScriptLogStore.getState().loadTail(attemptId);
  }, [attemptId, present, loaded, loading, error]);

  // Rows were missed: read the ones after the last held.
  useEffect(() => {
    if (!attemptId || !loaded || !needsCatchUp || loading || anchored) return;
    return afterReadGap(attemptId, () => void useScriptLogStore.getState().loadAfter(attemptId));
  }, [attemptId, loaded, needsCatchUp, loading, anchored]);

  // While it runs: ask the server when the socket has gone quiet, and try a failed read again.
  useEffect(() => {
    if (!attemptId || !running) return;
    const timer = setInterval(() => {
      const store = useScriptLogStore.getState();
      const a = store.attempts[attemptId];
      if (!a || a.loading) return;
      const now = Date.now();
      if (now - a.lastReadAt < POLL_IDLE_MS) return;
      if (!a.win.loaded) {
        if (a.error && a.retryable) void store.loadTail(attemptId);
        return;
      }
      if (a.win.hasMoreAfter || now - a.lastLiveAt < POLL_IDLE_MS) return;
      void store.loadAfter(attemptId);
    }, 1000);
    return () => clearInterval(timer);
  }, [attemptId, running]);

  // It has ended and its end note is not here: one more read for the rest.
  const finalRead = useRef<string | null>(null);
  useEffect(() => {
    if (!attemptId || running || !loaded || ended || loading || anchored) return;
    if (finalRead.current === attemptId) return;
    return afterReadGap(attemptId, () => {
      const store = useScriptLogStore.getState();
      const busy = store.attempts[attemptId]?.loading != null;
      void store.loadAfter(attemptId);
      // Done once this read is under way (a read sets `loading` before it waits). Skipped,
      // because another read was going, it is tried again when that one lands.
      if (!busy && useScriptLogStore.getState().attempts[attemptId]?.loading != null) {
        finalRead.current = attemptId;
      }
    });
  }, [attemptId, running, loaded, ended, loading, anchored]);

  return attempt;
}
