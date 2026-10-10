/**
 * Team now: the members as cards, the leader in the middle and the others
 * around it. Below 768 px the map is a list, working first, with no lines.
 *
 * Lines (Design home decision A, D42-D58): only pairs who messaged each
 * other in the 10 minutes before Temper's reply (`as_of`, never the
 * device's clock), at most 4, newest first. Each line runs through the
 * gutters, never across a card or the hub and never along another line,
 * with a socket at both ends; a crossing that can't be avoided gets a hop.
 * The count on a line is the pair's last-hour count, on the line's own
 * straight run. A dot runs along a drawn line each time a message is
 * released (only for messages newer than the page's first load); the rest
 * goes to one "+N more sent" cue.
 *
 * The lines, dots and counts are decoration (aria-hidden): the cards are
 * real text, and the visible "Messages in the last hour" list under the map
 * carries every pair with the same numbers (D44). Stale data (the last read
 * failed) keeps the cards and lines at their last read with no motion and
 * nothing green, and the words say their windows end at Temper's last
 * answer (D15, D75). An ended run has no Animate switch: nothing moves after
 * the end (D47). The You/Temper corner is a caption and two plain tags
 * (D76); owner and Temper messages start there.
 *
 * Card boxes are measured as painted: again on every size change of the map
 * or a card, and once the page's own fonts have loaded, so the lines never
 * keep a box measured with a fallback font. Cards that share grid rows take
 * the tallest one's height; the leader between two rows keeps its own,
 * centred (D78). Both are CSS, no height is stored.
 *
 * Paint order (Design D32): lines under the cards, a moving dot over them,
 * each opaque count over a dot passing under it, and the +N cue over both.
 */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { cn } from '@/lib/utils';
import {
  DOT_MS,
  dotPlan,
  drawnLines,
  extraWords,
  hourRows,
  justSent,
  lineGreen,
  listOrder,
  mapLines,
  mapSlots,
  msOf,
  pairKey,
  phaseEnded,
  sentLabel,
  teamCountWords,
  type GlanceMessageEvent,
  type GlanceRun,
} from '@/lib/teamGlance';
import { flightPoints, hubRoute, mapGeometry, type Point, type Rect } from '@/lib/teamGlanceRoute';
import { onFontsLoaded } from '@/lib/fontsLoaded';
import type { GlanceFeed } from '@/hooks/useTeamGlanceEvents';
import { teamCard, teamLabel } from '@/components/team/teamUi';
import { MemberCard } from './MemberCard';

interface Layout {
  box: { w: number; h: number };
  rects: Record<string, Rect>;
}

/** The You/Temper corner's key among the measured boxes: one box, the start of every owner or Temper flight (D5, D76). */
const HUB = 'hub';

/** A socket's radius: a 4.5 px dot at both ends of every line (D58). */
const SOCKET_R = 4.5;
/** How long the "+N more sent" cue shows (SPEC 6, D10). */
const EXTRA_MS = 1600;
/** How long a receiving ring glows when a dot lands (SPEC 6). */
const RING_GLOW_MS = 500;

/** The legend's first sentence; on stale data its windows end at Temper's last answer, `staleFor` ago (D75). */
function legendLines(staleFor: string | null): string {
  return staleFor === null
    ? 'Lines join members who messaged each other in the last 10 minutes (up to 4, newest first); the number is how many messages in the last hour. Every pair is listed below.'
    : `Lines join members who messaged each other in the 10 minutes before Temper\u2019s last answer, ${staleFor} ago (up to 4, newest first); the number is how many messages in the hour before it. Every pair is listed below.`;
}
/** The quiet line inside the map: pairs in the last hour, none in the line window (D45, D75). */
function quietWords(stale: boolean): string {
  return stale
    ? 'No messages between members in the 10 minutes before Temper\u2019s last answer'
    : 'No messages between members in the last 10 minutes';
}
/** The hour list's label and list name (D44, D75). */
function hourLabel(stale: boolean): string {
  return stale ? 'Messages in the hour before Temper\u2019s last answer' : 'Messages in the last hour';
}
const LEGEND_GREEN = 'A line turns green for a minute after a message is sent; it doesn\u2019t mean a turn is running.';
const LEGEND_DOTS =
  'A moving dot means a message was released, never that it was read or answered. Messages from you and Temper start at the corner.';

function rectIn(el: Element, box: DOMRect): Rect {
  const r = el.getBoundingClientRect();
  return { x: r.left - box.left, y: r.top - box.top, w: r.width, h: r.height };
}

function sameLayout(a: Layout | null, b: Layout): boolean {
  if (!a || a.box.w !== b.box.w || a.box.h !== b.box.h) return false;
  const ka = Object.keys(a.rects);
  if (ka.length !== Object.keys(b.rects).length) return false;
  return ka.every((k) => {
    const p = a.rects[k];
    const q = b.rects[k];
    return q && p.x === q.x && p.y === q.y && p.w === q.w && p.h === q.h;
  });
}

/** Whether moving dots are allowed right now (system setting and the page's still mode). */
function motionAllowed(): boolean {
  if (typeof window === 'undefined') return false;
  if (document.documentElement.dataset.motion === 'still') return false;
  return !window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
}

export function TeamMap({
  run,
  feed,
  now,
  animate,
  onAnimateChange,
  reducedMotion,
  staleFor = null,
  agesAt = null,
}: {
  run: GlanceRun;
  feed: GlanceFeed;
  /** Temper's clock (`as_of`): the cards' durations and the line window count to it. */
  now: number | null;
  animate: boolean;
  onAnimateChange: (on: boolean) => void;
  reducedMotion: boolean;
  /** The last read failed: how long Temper hasn't answered, in the stale note's words; null while it answers. */
  staleFor?: string | null;
  /** Temper's clock plus the time since the last good read: "ago" words count to it on stale data (D64). */
  agesAt?: number | null;
}) {
  // Show the last read as it was: rings still, nothing green, windows said to end at Temper's last answer.
  const stale = staleFor !== null;
  // "ago" words count to now on stale data (D64); while Temper answers, now is its reply time.
  const agoAt = stale ? (agesAt ?? now) : now;
  const boxRef = useRef<HTMLDivElement>(null);
  const dotsRef = useRef<HTMLDivElement>(null);
  const extrasRef = useRef<HTMLDivElement>(null);
  const cards = useRef(new Map<string, HTMLElement>());
  const [layout, setLayout] = useState<Layout | null>(null);
  const launched = useRef(0);
  const extras = useRef(0);
  // The last batch of fresh messages that was flown (or let go): each batch flies once.
  const flown = useRef(0);
  // Where the browser can't animate, timers take the dots away; cleared on leaving the page.
  const timers = useRef<number[]>([]);
  useEffect(() => {
    const pending = timers.current;
    return () => pending.forEach((t) => window.clearTimeout(t));
  }, []);

  const { slots, rows } = useMemo(() => mapSlots(run.members), [run.members]);
  const byName = useMemo(() => new Map(run.members.map((m) => [m.name, m])), [run.members]);
  const members = useMemo(() => new Set(run.members.map((m) => m.name)), [run.members]);
  // Recency is Temper's reply time, never the device's clock (D42): stale and ended runs keep theirs.
  const asOf = msOf(run.asOf) ?? now;
  const pairs = useMemo(() => mapLines(run), [run]);
  const drawn = useMemo(() => drawnLines(pairs, asOf), [pairs, asOf]);
  const hour = useMemo(() => hourRows(pairs, stale ? agoAt : asOf), [pairs, stale, agoAt, asOf]);
  const sent = useMemo(() => justSent(feed.events, run), [feed.events, run]);
  // No just-sent cue while Temper doesn't answer: nothing is green on stale data (D75).
  const said = sent ? sentLabel(sent, run.phase.name, agoAt, stale) : null;
  const ended = phaseEnded(run.phase.name);
  // The switch shows the viewer's choice (animate); what actually moves is
  // that choice, the system's reduced-motion setting, a fresh read and a
  // run that hasn't ended.
  const moving = animate && !reducedMotion;
  const ringsMove = moving && !stale && !ended;

  const setCard = useCallback(
    (key: string) => (el: HTMLElement | null) => {
      if (el) cards.current.set(key, el);
      else cards.current.delete(key);
    },
    [],
  );

  const measure = useCallback(() => {
    const box = boxRef.current;
    if (!box) return;
    const b = box.getBoundingClientRect();
    // Hidden (the phone list shows instead): nothing to draw.
    if (b.width === 0 || b.height === 0) {
      setLayout((l) => (l === null ? l : null));
      return;
    }
    const rects: Record<string, Rect> = {};
    cards.current.forEach((el, key) => {
      rects[key] = rectIn(el, b);
    });
    const next = { box: { w: Math.round(b.width), h: Math.round(b.height) }, rects };
    setLayout((l) => (sameLayout(l, next) ? l : next));
  }, []);

  useLayoutEffect(() => {
    measure();
    const box = boxRef.current;
    // The page's own font can arrive after the first layout: measure again once it has, so no box
    // measured with a fallback font is kept (a card can change size while the map box doesn't) [D80].
    const stopFonts = onFontsLoaded(measure);
    const ro = box && typeof ResizeObserver !== 'undefined' ? new ResizeObserver(() => measure()) : null;
    if (box && ro) {
      ro.observe(box);
      cards.current.forEach((el) => ro.observe(el));
    }
    return () => {
      stopFonts();
      ro?.disconnect();
    };
  }, [measure, slots, run]);

  // The member cards and the You/Temper corner, as the router sees them.
  const parts = useMemo(() => {
    if (!layout) return null;
    const entries = Object.entries(layout.rects);
    const hub = layout.rects[HUB];
    return {
      cards: new Map(entries.filter(([k]) => k !== HUB)),
      hubs: hub ? [hub] : [],
    };
  }, [layout]);

  // Routing needs only the drawn pairs, their counts (a badge's width) and
  // the measured boxes: keep the geometry while those are unchanged.
  const drawnKey = JSON.stringify(drawn.map((l) => [l.a, l.b, l.count]));
  const geometry = useMemo(() => {
    if (!layout || !parts) return null;
    const list = JSON.parse(drawnKey) as Array<[string, string, number]>;
    if (list.length === 0) return null;
    return mapGeometry(
      list.map(([a, b, count]) => ({ key: pairKey(a, b), a, b, count })),
      parts.cards,
      parts.hubs,
      layout.box,
    );
  }, [layout, parts, drawnKey]);
  const lines = useMemo(() => geometry?.lines ?? [], [geometry]);
  // Nothing is green while Temper doesn't answer: "in the last minute" can't be known then (D75).
  const green = useMemo(
    () => new Set(stale ? [] : drawn.filter((l) => lineGreen(l, asOf)).map((l) => pairKey(l.a, l.b))),
    [drawn, asOf, stale],
  );
  const anyGreen = lines.some((l) => green.has(l.key));
  const onMap = useMemo(() => new Set(lines.map((l) => l.key)), [lines]);

  // The flight of one message, from its sender (a member or a hub) to its receiver.
  const flightOf = useCallback(
    (m: GlanceMessageEvent): Point[] | null => {
      if (!layout || !parts) return null;
      if (m.fromKind === 'member') {
        const line = lines.find((l) => l.key === pairKey(m.from, m.to));
        if (!line) return null;
        const path = flightPoints(line.pts);
        return m.from === line.a ? path : [...path].reverse();
      }
      const hub = layout.rects[HUB];
      if (!hub || !parts.cards.has(m.to)) return null;
      // The corner's line leaves from the middle of its side that faces the receiver (D5).
      const route = hubRoute(hub, m.to, parts.cards, [], layout.box);
      return route ? flightPoints(route) : null;
    },
    [layout, parts, lines],
  );

  // Motion turned off, reduced by the system, the read went stale or the run
  // ended: any dot or ring pulse in flight stops at once, and nothing flies
  // again until a new batch arrives with motion on (no replay of what was let go).
  useEffect(() => {
    if (ringsMove) return;
    for (const layer of [dotsRef.current, extrasRef.current]) {
      if (!layer) continue;
      for (const el of Array.from(layer.children)) {
        (el as HTMLElement).getAnimations?.().forEach((a) => a.cancel());
        el.remove();
      }
    }
    boxRef.current
      ?.querySelectorAll<HTMLElement>('[data-pulse]')
      .forEach((el) => el.getAnimations?.().forEach((a) => a.cancel()));
    timers.current.splice(0).forEach((t) => window.clearTimeout(t));
  }, [ringsMove]);

  // Fresh messages: one dot each on a drawn line, as dotPlan spaces them. Never for history.
  useEffect(() => {
    if (feed.freshKey === 0 || feed.freshKey === flown.current) return;
    flown.current = feed.freshKey;
    if (feed.fresh.length === 0) return;
    const box = boxRef.current;
    const layer = dotsRef.current;
    const cues = extrasRef.current;
    if (!ringsMove || !motionAllowed() || !box || !layer || !cues || !layout) return;
    // A message between two members whose pair isn't drawn joins "+N more sent" (D43).
    const plan = dotPlan(feed.fresh, onMap, members);
    let lastDelay = 0;
    for (const { event, delay } of plan.dots) {
      const flight = flightOf(event);
      if (!flight || flight.length < 2) continue;
      lastDelay = delay;
      const dot = document.createElement('div');
      dot.className = 'glance-dot';
      dot.dataset.to = event.to;
      layer.appendChild(dot);
      // Distances give small corner and hop arcs their real share of the
      // 400 ms flight, not the same time as a long stretch (Design D29).
      let distance = 0;
      const distances = flight.map((p, i, all) => {
        if (i > 0) distance += Math.hypot(p.x - all[i - 1].x, p.y - all[i - 1].y);
        return distance;
      });
      const frames = flight.map((p, i, all) => ({
        transform: `translate(${p.x}px, ${p.y}px)`,
        offset: distance > 0 ? distances[i] / distance : i / Math.max(1, all.length - 1),
        opacity: i === 0 || i === all.length - 1 ? 0.2 : 1,
      }));
      const anim = dot.animate?.(frames, { duration: DOT_MS, delay, easing: 'ease-in-out', fill: 'both' });
      launched.current += 1;
      const done = () => {
        dot.remove();
        // The receiving ring glows 6 px in the accent for 500 ms (SPEC 6).
        const pulse = box.querySelector<HTMLElement>(`[data-pulse="${CSS.escape(event.to)}"]`);
        const accent = pulse ? getComputedStyle(pulse).getPropertyValue('--temper-accent').trim() : '';
        const glow = `0 0 0 6px color-mix(in srgb, ${accent || 'currentColor'} 45%, transparent)`;
        const none = `0 0 0 0 color-mix(in srgb, ${accent || 'currentColor'} 45%, transparent)`;
        pulse?.animate?.(
          [
            { boxShadow: none, offset: 0 },
            { boxShadow: glow, offset: 0.3 },
            { boxShadow: glow, offset: 0.7 },
            { boxShadow: none, offset: 1 },
          ],
          { duration: RING_GLOW_MS, easing: 'linear' },
        );
      };
      if (anim) anim.onfinish = done;
      else timers.current.push(window.setTimeout(done, delay + DOT_MS));
    }
    box.dataset.dotsLaunched = String(launched.current);
    if (plan.extra > 0) {
      extras.current += plan.extra;
      box.dataset.dotsExtra = String(extras.current);
      // One cue at the map's top right, never on a line (SPEC 6, D10, D43).
      const cue = document.createElement('div');
      cue.className = 'glance-extra';
      cue.textContent = extraWords(plan.extra);
      cues.appendChild(cue);
      const anim = cue.animate?.(
        [{ opacity: 0 }, { opacity: 1, offset: 0.1 }, { opacity: 1, offset: 0.85 }, { opacity: 0 }],
        { duration: EXTRA_MS, delay: lastDelay, fill: 'both' },
      );
      if (anim) anim.onfinish = () => cue.remove();
      else timers.current.push(window.setTimeout(() => cue.remove(), lastDelay + EXTRA_MS));
    }
    // Only a new batch starts dots; a re-measure mid-flight doesn't replay them.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [feed.freshKey, layout]);

  const ordered = useMemo(() => listOrder(run.members), [run.members]);
  const counts = teamCountWords(run);
  const badges = geometry?.badges ?? [];
  // A count with no allowed spot is never drawn over another line (D57); the
  // list under the map carries every count, and the checks reject it.
  const forced = badges.filter((b) => b.forced).length;
  const quiet = pairs.length > 0 && drawn.length === 0;

  return (
    <section className={cn(teamCard, 'flex min-w-0 flex-col gap-3 p-4')} aria-labelledby="glance-team-title">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div className="flex min-w-0 flex-wrap items-baseline gap-x-3">
          <h2 id="glance-team-title" className={cn(teamLabel, 'mb-0')}>
            Team now
          </h2>
          {counts && (
            <p className="m-0 text-sm text-temper-text" data-testid="glance-team-count">
              {counts}
            </p>
          )}
        </div>
        {/* An ended run has no switch: nothing moves after the end (D47). Under reduced motion it is
            off and disabled, with the reason next to it; it keeps focus so the reason can be read (SPEC 5). */}
        {!ended && (
          <div className="flex flex-wrap items-center gap-x-2">
            <button
              type="button"
              role="switch"
              aria-checked={animate && !reducedMotion}
              aria-disabled={reducedMotion || undefined}
              aria-describedby={reducedMotion ? 'glance-motion-off' : undefined}
              onClick={() => {
                if (!reducedMotion) onAnimateChange(!animate);
              }}
              className={cn(
                'inline-flex min-h-11 items-center gap-2 rounded-md px-2 text-sm text-temper-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-temper-accent',
                reducedMotion ? 'cursor-default' : 'hover:bg-temper-surface',
              )}
              data-testid="glance-animate"
            >
              <span>Animate messages</span>
              <span className="glance-switch" aria-hidden="true" />
            </button>
            {reducedMotion && (
              <span id="glance-motion-off" className="text-sm text-temper-text-muted">
                Off: your device asks for less motion
              </span>
            )}
          </div>
        )}
      </div>
      {/* On stale data, by the switch at every width (D30, D15). */}
      {!ended && stale && (
        <p className="m-0 text-sm text-temper-text-muted" data-testid="glance-motion-note">
          Paused until Temper answers; this switch saves your preference.
        </p>
      )}

      {/* The map, 768 px and wider. */}
      <div
        ref={boxRef}
        className="glance-map hidden md:block"
        data-testid="glance-map"
        data-dots-launched={0}
        data-dots-extra={0}
        data-motion={ringsMove ? 'on' : 'off'}
        data-lines-drawn={lines.length}
        data-route-failed={geometry?.failed.length ?? 0}
        data-lines-alongside={geometry?.shared.length ?? 0}
        data-crossing-hops={lines.reduce((n, l) => n + l.hops, 0)}
        data-unhopped={geometry?.unhopped ?? 0}
        data-badges-forced={forced}
        data-badge-tiers={badges.map((b) => b.tier).join(',')}
        // The boxes the lines were routed round, as last measured: the checks compare them with the painted cards [D80].
        data-card-boxes={layout ? JSON.stringify(layout.rects) : ''}
      >
        <svg className="glance-lines" aria-hidden="true" focusable="false" data-testid="glance-lines">
          {/* Each line over a 6 px panel-coloured casing, with a socket at both ends (D23, D58). */}
          {lines.map((l) => {
            const on = green.has(l.key);
            const ends = [l.pts[0], l.pts[l.pts.length - 1]];
            return (
              <g key={l.key} data-pair={l.key} data-green={on ? 'true' : 'false'}>
                <path className="glance-casing" d={l.path} />
                <path className={cn('glance-line', on && 'is-green')} d={l.path} data-line={l.key} data-hops={l.hops} />
                {ends.map((p, i) => (
                  <circle
                    key={i}
                    className={cn('glance-socket', on && 'is-green')}
                    cx={p.x}
                    cy={p.y}
                    r={SOCKET_R}
                    data-socket={i === 0 ? l.a : l.b}
                  />
                ))}
              </g>
            );
          })}
        </svg>
        {/* Decoration: the legend's last sentence says what it is (D76). One box, where owner and Temper lines start. */}
        <div ref={setCard(HUB)} className="glance-hub" aria-hidden="true" data-testid="glance-hub">
          <span className="glance-hub-cap">From outside the team:</span>
          <span className="glance-hub-tag">You</span>
          <span className="glance-hub-tag">Temper</span>
        </div>
        <ol className="glance-map-grid m-0 list-none" style={{ gridTemplateRows: `repeat(${rows}, auto)` }}>
          {slots.map((s) => {
            const m = byName.get(s.name);
            if (!m) return null;
            // D78: cards sharing a grid row stretch to the tallest one's height; the leader between
            // two or more rows keeps its own height, centred. CSS only: no height is stored.
            const staggered = s.col === 2 && rows > 1;
            return (
              <li
                key={s.name}
                className="flex min-w-0 flex-col"
                data-slot={`${s.col}:${s.col === 2 ? `1-${rows}` : s.row}`}
                style={{
                  gridColumn: s.col,
                  gridRow: s.col === 2 ? `1 / span ${rows}` : s.row,
                  alignSelf: staggered ? 'center' : 'stretch',
                }}
              >
                <MemberCard ref={setCard(s.name)} member={m} phase={run.phase.name} now={now} moving={ringsMove} />
              </li>
            );
          })}
        </ol>
        {quiet && (
          <p className="glance-map-quiet" data-testid="glance-map-quiet">
            {quietWords(stale)}
          </p>
        )}
        <div ref={dotsRef} className="glance-dots" aria-hidden="true" />
        {/* The counts over the dots, so a dot passing under one never hides its digits (D32). */}
        <svg className="glance-counts" aria-hidden="true" focusable="false" data-testid="glance-counts">
          {lines.map((l, i) => {
            const badge = badges[i];
            if (!badge || badge.forced) return null;
            return (
              <g key={`${l.key}-n`} className="glance-count" data-count={l.key} data-tier={badge.tier}>
                <rect x={badge.box.x} y={badge.box.y} width={badge.box.w} height={badge.box.h} rx={badge.box.h / 2} />
                <text x={badge.at.x} y={badge.at.y} textAnchor="middle" dominantBaseline="central">
                  {l.count}
                </text>
              </g>
            );
          })}
        </svg>
        {/* The +N cue over both (D32). */}
        <div ref={extrasRef} className="glance-extras" aria-hidden="true" />
      </div>

      {/* The list, under 768 px: working first. */}
      <ol className="m-0 list-none divide-y divide-temper-border p-0 md:hidden" data-testid="glance-list">
        {ordered.map((m) => (
          <li key={m.name} className="min-w-0">
            <MemberCard member={m} phase={run.phase.name} now={now} moving={ringsMove} row />
          </li>
        ))}
      </ol>

      <div
        className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-3 gap-y-1 rounded-md border border-temper-border bg-temper-surface px-3 py-2 text-sm"
        data-testid="glance-just-sent"
      >
        <p className="m-0 flex min-w-0 items-baseline gap-2 text-temper-text" aria-live="polite" aria-atomic="true">
          {sent && said ? (
            <>
              <span
                aria-hidden="true"
                data-testid="glance-sent-dot"
                data-tone={said.label === 'Just sent' ? 'accent' : 'neutral'}
                className={cn(
                  'inline-block size-2.5 shrink-0 rounded-full',
                  said.label === 'Just sent' ? 'bg-temper-accent' : 'bg-temper-control',
                )}
              />
              {/* D74: on a phone the label has its own line and no "\u00b7"; "From \u2192" stays together and the
                  receiver may start the next line, so a long name never breaks inside a word. */}
              <span className="min-w-0 break-words" data-testid="glance-sent-words">
                <span className="font-semibold max-md:block">{said.label}</span>
                <span className="max-md:hidden">{' \u00b7 '}</span>
                {sent.burst > 1 && `${sent.burst} messages in the same second, last: `}
                <span className="whitespace-nowrap">{`${sent.from}\u00a0\u2192`}</span> {sent.to}
                {sent.text !== null && <>: &ldquo;{sent.text}&rdquo;</>}
              </span>
            </>
          ) : feed.ready ? (
            <>
              {/* Nothing released yet: a neutral, unfilled mark, never the recent-send colour (D33). */}
              <span
                aria-hidden="true"
                data-testid="glance-sent-dot"
                data-tone="none"
                className="inline-block size-2.5 shrink-0 rounded-full border border-temper-control bg-transparent"
              />
              <span className="min-w-0 break-words text-temper-text-muted">No messages between members yet.</span>
            </>
          ) : (
            <span className="text-temper-text-muted">Reading the team&apos;s messages…</span>
          )}
        </p>
        {said?.time && <span className="text-sm text-temper-text-muted">{said.time}</span>}
      </div>
      {feed.failed && (
        <p className="m-0 text-sm text-temper-text-muted" role="status">
          Couldn&apos;t read the newest messages. Trying again every 5 s.
        </p>
      )}
      {lines.length > 0 && (
        <p className="glance-legend m-0 hidden md:block" data-testid="glance-legend">
          {legendLines(staleFor)}
          {anyGreen && <> {LEGEND_GREEN}</>} {LEGEND_DOTS}
        </p>
      )}
      {/* Every pair of the last hour, at every width, with the numbers on the lines (D44); none, no list. */}
      {hour.length > 0 && (
        <div className="glance-hour" data-testid="glance-pair-counts">
          <h3 className="glance-hour-label" id="glance-hour-title">
            {hourLabel(stale)}
          </h3>
          <ul className="glance-hour-list" aria-labelledby="glance-hour-title">
            {hour.map((r) => (
              <li key={r.key} data-pair={r.key} data-drawn={onMap.has(r.key) ? 'true' : 'false'}>
                <span className="glance-hour-pair">{r.pair}</span>
                <span className="glance-hour-time">{r.time}</span>
              </li>
            ))}
          </ul>
          {/* The phone note, under the list (D30). */}
          {!ended && (
            <p className="m-0 mt-1 text-sm text-temper-text-muted md:hidden" data-testid="glance-phone-note">
              The switch controls busy rings here; message dots appear on the wider map.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
