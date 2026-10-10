/**
 * The glance map's geometry (TeamMap): routed in a worker
 * (teamGlanceRoute.worker.ts), so routing is never a long task on the page's
 * main thread. A members-6 map costs a browser 30-200 ms to route while the
 * router's code is cold, as it is on every load, and the map routes again
 * for a new pair, a resize, a member change or a count crossing a badge
 * width. Where the browser has no workers (jsdom) or the worker fails, the
 * map is routed in render, as before.
 *
 * Each ask is numbered as it is posted and only the answer to the latest one
 * is kept: a late answer to an older ask never draws. While an ask is
 * pending the map keeps what it drew (the lines it had stay until the new
 * ones arrive) and `ready` is false: the page marks its map with it
 * (data-geometry), the browser checks wait for it, and fresh messages fly
 * once the lines they fly on are drawn.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { mapGeometry, type MapGeometry, type MapLineIn, type Rect } from '@/lib/teamGlanceRoute';
import type { GeometryAnswer, GeometryAsk } from '@/lib/teamGlanceRoute.worker';

/** What the map routes: the drawn pairs in their order, the measured cards and hub, and the map's box. */
export interface MapAsk {
  lines: MapLineIn[];
  cards: Map<string, Rect>;
  hubs: Rect[];
  box: { w: number; h: number };
}

export interface MapGeometryState {
  /** The answer to the latest ask; while that is pending, the last one answered. Null: nothing to draw. */
  geometry: MapGeometry | null;
  /** The geometry answers the latest ask (true when there is nothing to route). */
  ready: boolean;
}

interface Router {
  /** Route this ask; only the latest ask's answer is passed on. */
  ask(ask: MapAsk, answered: (geometry: MapGeometry) => void): void;
  stop(): void;
}

/**
 * The router's worker, numbering its asks; null if the browser refuses it (a
 * policy can). `failed` hears a worker that fails to load, or to route.
 */
function startRouter(failed: () => void): Router | null {
  let worker: Worker;
  try {
    worker = new Worker(new URL('../lib/teamGlanceRoute.worker.ts', import.meta.url), { type: 'module' });
  } catch {
    return null;
  }
  let latest = 0;
  let answered: ((geometry: MapGeometry) => void) | null = null;
  const fail = () => {
    worker.terminate();
    answered = null;
    failed();
  };
  worker.onerror = fail;
  worker.onmessageerror = fail;
  worker.onmessage = (e: MessageEvent<GeometryAnswer>) => {
    if (e.data.seq !== latest || !answered) return;
    if ('error' in e.data) fail();
    else answered(e.data.geometry);
  };
  return {
    ask(ask, then) {
      latest += 1;
      answered = then;
      const message: GeometryAsk = { seq: latest, ...ask };
      worker.postMessage(message);
    },
    stop() {
      answered = null;
      worker.terminate();
    },
  };
}

export function useMapGeometry(ask: MapAsk | null): MapGeometryState {
  // The worker didn't load, refused the ask or failed: the map is routed in render from then on.
  const [failed, setFailed] = useState(false);
  const inPage = typeof Worker === 'undefined' || failed;
  const [answer, setAnswer] = useState<{ ask: MapAsk; geometry: MapGeometry } | null>(null);
  const router = useRef<Router | null>(null);

  // Nothing to route (no line drawn, or the map hidden): nothing is kept to show while a later ask is routed.
  if (!ask && answer) setAnswer(null);

  const routed = useMemo(
    () => (inPage && ask ? mapGeometry(ask.lines, ask.cards, ask.hubs, ask.box) : null),
    [inPage, ask],
  );

  useEffect(
    () => () => {
      router.current?.stop();
      router.current = null;
    },
    [],
  );

  useEffect(() => {
    if (inPage || !ask) return;
    router.current ??= startRouter(() => setFailed(true));
    const r = router.current;
    if (!r) {
      // Refused: route in the page, once this effect is over.
      queueMicrotask(() => setFailed(true));
      return;
    }
    r.ask(ask, (geometry) => setAnswer({ ask, geometry }));
  }, [inPage, ask]);

  if (!ask) return { geometry: null, ready: true };
  if (inPage) return { geometry: routed, ready: true };
  return { geometry: answer?.geometry ?? null, ready: answer?.ask === ask };
}
