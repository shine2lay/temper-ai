/**
 * The glance map's routing, off the page's main thread (useMapGeometry posts
 * each ask here and draws the answer). Routing a members-6 map the first time
 * costs a browser 30-200 ms while the router's code is still cold, and up to
 * 80 ms warm on a busy machine: in the page that is a long task on every load
 * and on every change the map must route again. Here it costs the page
 * nothing. The answer is mapGeometry's own: a structured clone of it.
 */
import { mapGeometry, type MapGeometry, type MapLineIn, type Rect } from './teamGlanceRoute';

/** One routing of the map, numbered by the page: an answer to an older ask is dropped there. */
export interface GeometryAsk {
  seq: number;
  lines: MapLineIn[];
  cards: Map<string, Rect>;
  hubs: Rect[];
  box: { w: number; h: number };
}

export type GeometryAnswer = { seq: number; geometry: MapGeometry } | { seq: number; error: string };

export function answerAsk(ask: GeometryAsk): GeometryAnswer {
  try {
    return { seq: ask.seq, geometry: mapGeometry(ask.lines, ask.cards, ask.hubs, ask.box) };
  } catch (e) {
    return { seq: ask.seq, error: e instanceof Error ? e.message : String(e) };
  }
}

interface WorkerScope {
  onmessage: ((e: MessageEvent<GeometryAsk>) => void) | null;
  postMessage(message: GeometryAnswer): void;
}

// A worker has no window; a test that imports answerAsk does, and gets no listener.
if (typeof window === 'undefined') {
  const scope = self as unknown as WorkerScope;
  scope.onmessage = (e) => scope.postMessage(answerAsk(e.data));
}
