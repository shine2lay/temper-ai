/**
 * The free-flowing team's event feed, for the glance page's motion.
 *
 * The first load reads the whole history quietly (it never animates: load,
 * reload and reconnect show history as it is). After that, each time the run
 * poll reports a newer events cursor, only the events past ours are read,
 * and the messages among them are handed out as one "fresh" batch to
 * animate. A batch after a failed read is quiet too, and a message sent more
 * than 12 s before the read never flies, by Temper's clock (the events
 * reply's as_of, D4), so after a hidden tab or a lost connection a pile of
 * old messages never flies at once, while a quiet team's next message still
 * does. Events are kept once by seq, and a message id already shown never
 * flies again (Design D6). Each page's as_of is Temper's clock at that read.
 */
import { useEffect, useRef, useState } from 'react';
import { fetchTeamEvents } from '@/lib/teamApi';
import { toGlanceEventPage } from '@/lib/teamGlanceAdapter';
import type { GlanceEvent, GlanceMessageEvent } from '@/lib/teamGlance';

/** Events per read. */
export const GLANCE_EVENTS_PAGE = 500;
/** Most pages one load reads (20,000 events) before it catches up in another read. */
const MAX_PAGES = 40;
/** A message flies only if Temper sent it at most this long before the read (Temper's clock). */
export const GLANCE_FRESH_MS = 12_000;

/**
 * Whether a message is young enough to fly: sent at most GLANCE_FRESH_MS
 * before `asOf`, the events reply's as_of. Never the device's clock (D4).
 * With no time on either side its age isn't known, and it flies (the 6-dot
 * cap and "+N more sent" still bound a batch).
 */
export function freshByClock(m: Pick<GlanceMessageEvent, 'at'>, asOf: string | null): boolean {
  if (asOf === null || m.at === null) return true;
  const now = Date.parse(asOf);
  const at = Date.parse(m.at);
  if (Number.isNaN(now) || Number.isNaN(at)) return true;
  const age = now - at;
  return age >= 0 && age <= GLANCE_FRESH_MS;
}

export interface GlanceFeed {
  /** Every event read so far, oldest first. */
  events: GlanceEvent[];
  /** Messages released since the page first loaded, from the newest read only. */
  fresh: GlanceMessageEvent[];
  /** Goes up by one with each fresh batch. */
  freshKey: number;
  /** The first load is done. */
  ready: boolean;
  /** The last read failed (the page keeps the events it has). */
  failed: boolean;
  /** Temper's clock at the newest good read (the events reply's as_of), or null. */
  asOf: string | null;
}

const EMPTY: GlanceFeed = { events: [], fresh: [], freshKey: 0, ready: false, failed: false, asOf: null };

export function useTeamGlanceEvents(executionId: string | undefined, runCursor: number | null): GlanceFeed {
  const [feed, setFeed] = useState<GlanceFeed>(EMPTY);
  // Goes up 5 s after a failed read, so an ended run (no more polls) still tries again.
  const [retry, setRetry] = useState(0);
  const cursor = useRef(0);
  const busy = useRef(false);
  const loaded = useRef(false);
  const lastFailed = useRef(false);
  const alive = useRef(true);
  // The newest cursor the run reported while a read was in flight.
  const wanted = useRef<number | null>(null);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  useEffect(() => {
    cursor.current = 0;
    loaded.current = false;
    lastFailed.current = false;
    wanted.current = null;
    setFeed(EMPTY);
  }, [executionId]);

  useEffect(() => {
    if (!executionId || runCursor === null) return;
    wanted.current = runCursor;
    if (busy.current) return;
    if (loaded.current && runCursor <= cursor.current && !lastFailed.current) return;

    const read = async () => {
      busy.current = true;
      const first = !loaded.current;
      const quiet = first || lastFailed.current;
      const got: GlanceEvent[] = [];
      const from = cursor.current;
      let after = from;
      let asOf: string | null = null;
      try {
        for (let page = 0; page < MAX_PAGES; page++) {
          const raw = await fetchTeamEvents(executionId, after, GLANCE_EVENTS_PAGE);
          const p = toGlanceEventPage(raw, after);
          got.push(...p.events.filter((e) => e.seq > after));
          after = Math.max(after, p.cursor);
          asOf = p.asOf ?? asOf;
          if (!p.more || p.events.length === 0) break;
        }
        if (!alive.current) return;
        cursor.current = after;
        loaded.current = true;
        lastFailed.current = false;
        const readAt = asOf;
        setFeed((f) => {
          const seen = new Set(f.events.map((e) => e.seq));
          const added = got.filter((e) => !seen.has(e.seq));
          const events = [...f.events, ...added].sort((a, b) => a.seq - b.seq);
          const shownIds = new Set(
            f.events.flatMap((e) => (e.kind === 'message' && e.messageId !== null ? [e.messageId] : [])),
          );
          const messages = added.filter(
            (e): e is GlanceMessageEvent =>
              e.kind === 'message' && (e.messageId === null || !shownIds.has(e.messageId)) && freshByClock(e, readAt),
          );
          const animate = !quiet && messages.length > 0;
          return {
            events,
            fresh: animate ? messages : [],
            freshKey: animate ? f.freshKey + 1 : f.freshKey,
            ready: true,
            failed: false,
            asOf: asOf ?? f.asOf,
          };
        });
      } catch {
        if (!alive.current) return;
        lastFailed.current = true;
        setFeed((f) => ({ ...f, failed: true, ready: f.ready || loaded.current }));
        window.setTimeout(() => {
          if (alive.current) setRetry((r) => r + 1);
        }, 5000);
      } finally {
        busy.current = false;
      }
      // The run moved on while we read: catch up now rather than at the next poll.
      // Only after a read that got further: Temper's cursor counts its hidden
      // bookkeeping too, so a feed that ends short of the run's cursor waits for
      // the next poll instead of asking again at once.
      if (
        alive.current &&
        loaded.current &&
        wanted.current !== null &&
        wanted.current > cursor.current &&
        cursor.current > from &&
        !lastFailed.current
      ) {
        void read();
      }
    };
    void read();
  }, [executionId, runCursor, retry]);

  return feed;
}
